"""Multi-itinerary search: POST /api/package-options and POST /api/package-options/{id}/select.

Run from backend/: ../.venv/bin/python -m pytest -q tests/test_package_options.py
Real catalog throughout. Each test gets its own temporary database, so a search that saves a row
(or a select that does not) is visible in the row count. The only stubbed piece is the search work
cap, and only in the one test that says so.
"""

import re
from dataclasses import replace
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.catalog.load import load_catalog
from app.db import connect
from app.engine import options as engine_options
from app.engine.build import FOUND, MINIMUM_COST, OVER_BUDGET, WITHIN_BUDGET, build_package
from app.engine.options import (
    BEST_RATED,
    CHEAPEST,
    FASTEST,
    avg_stars_per_night,
    cheapest_per_signature,
    find_package_options,
    signature,
    travel_minutes,
)
from app.engine.build import _Search
from app.engine.constraints import PlanningConstraints
from app.export.to_trip import to_trip_json
from app.main import app
from app.models import TripRequest
from app.rules.common import INITIAL
from app.services import package_options as store
from app.services.itinerary import price_breakdown
from app.validate.validate_trip import validate_trip

CAT = load_catalog()
MENON = {
    "departure": "BLR",
    "country": "Japan",
    "start_date": "2027-04-10",
    "nights": 6,
    "adults": 2,
    "child_ages": [6],
    "budget": 350_000,
}
# Delhi, 5 nights, one adult: three different winners (Menon's cheapest is also its fastest)
THREE_WAY = {
    "departure": "DEL",
    "country": "Japan",
    "start_date": "2027-04-10",
    "nights": 5,
    "adults": 1,
    "child_ages": [],
    "budget": 150_000,
}
THREE_WAY_TRIP = dict(departure_airport="DEL", nights=5, adults=1, children_ages=[], budget=150_000)
BLR_JAPAN_INFEASIBLE = {
    "departure": "BLR",
    "country": "Japan",
    "start_date": "2027-04-01",
    "nights": 3,
    "adults": 6,
    "child_ages": [3, 5],
    "budget": 900_000,
}


def _trip(**over) -> TripRequest:
    base = dict(
        departure_airport="BLR",
        destination_country="Japan",
        start_date=date(2027, 4, 10),
        nights=6,
        adults=2,
        children_ages=[6],
        budget=350_000,
    )
    return TripRequest(**{**base, **over})


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HOLIDAY_DB_PATH", str(tmp_path / "app.db"))
    with TestClient(app) as c:  # runs the lifespan: catalog check + create_tables()
        yield c


def _rows():
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM packages").fetchone()[0]


def _search(client, **over):
    r = client.post("/api/package-options", json={**MENON, **over})
    return r, r.json()


@pytest.fixture(scope="module")
def menon():
    """The engine's answer for Menon, computed once (the API answer is checked separately)."""
    return find_package_options(_trip(), CAT, WITHIN_BUDGET, count=3)


@pytest.fixture(scope="module")
def three_way():
    return find_package_options(_trip(**THREE_WAY_TRIP), CAT, WITHIN_BUDGET, count=3)


# ------------------------------------------------------------------ 1-2: complete, labelled, distinct


def test_three_different_winners_are_three_complete_clean_labelled_options(three_way, menon):
    assert three_way.primary.status == FOUND and three_way.complete
    assert len(three_way.packages) == 3
    assert three_way.labels == ((CHEAPEST,), (FASTEST,), (BEST_RATED,))
    assert menon.labels == ((CHEAPEST, FASTEST), (BEST_RATED,))  # Menon: cheapest is also fastest
    for pkg in three_way.packages + menon.packages:
        assert validate_trip(to_trip_json(pkg, CAT), CAT, INITIAL) == []
        assert pkg.arrival_flight and pkg.return_flight
        assert len(pkg.hotels) == len(pkg.plan.stays)
        assert len(pkg.intercity) == len(pkg.plan.legs())
        assert pkg.arrival_transfer and pkg.departure_transfer
        assert pkg.total <= pkg.budget


def test_cheapest_is_the_proven_minimum(menon):
    proven = build_package(_trip(), CAT, MINIMUM_COST)
    assert proven.status == FOUND
    assert menon.packages[0].total == proven.package.total
    assert all(p.total >= proven.package.total for p in menon.packages)


def _travel_floor(trip):
    """A lower bound on travel time over every (city plan, arrival, return) the planner considers:
    both flight durations plus the quickest transfer the catalog offers for each city change."""
    search = _Search(trip, CAT, PlanningConstraints())
    floors = []
    for _, _, plan, arr, ret, slots, _ in search.triples():
        n = len(plan.stays)
        legs = sum(
            min(CAT.indexes.transfers_by_id[t.transfer_id]["duration_minutes"] for _, t in slot)
            for slot in slots[n:]
        )
        floors.append(
            CAT.indexes.flights_by_id[arr.flight_id]["duration_minutes"]
            + CAT.indexes.flights_by_id[ret.flight_id]["duration_minutes"]
            + legs
        )
    return min(floors)


def test_fastest_travels_no_longer_than_any_other_option_and_meets_the_floor(three_way):
    times = [travel_minutes(p, CAT) for p in three_way.packages]
    fastest = times[three_way.labels.index((FASTEST,))]
    assert fastest == min(times) and fastest < times[0]
    # nothing can travel less than the floor, and the fastest holiday reaches it exactly
    assert fastest == _travel_floor(_trip(**THREE_WAY_TRIP))


def test_travel_time_is_flights_plus_transfers_between_cities(menon):
    for pkg in menon.packages:
        flights = sum(
            CAT.indexes.flights_by_id[f.flight_id]["duration_minutes"]
            for f in (pkg.arrival_flight, pkg.return_flight)
        )
        legs = sum(
            CAT.indexes.transfers_by_id[t.transfer_id]["duration_minutes"] for t in pkg.intercity
        )
        assert travel_minutes(pkg, CAT) == flights + legs


def test_best_rated_has_the_highest_average_stars_per_night(menon):
    stars = [avg_stars_per_night(p, CAT) for p in menon.packages]
    best = stars[menon.labels.index((BEST_RATED,))]
    assert best == max(stars) == 5.0  # 350 000 affords five-star stays
    pkg = menon.packages[menon.labels.index((BEST_RATED,))]
    nights = sum(s.nights for s in pkg.plan.stays)
    by_hand = (
        sum(
            CAT.indexes.hotels_by_id[h.hotel_id]["stars"] * s.nights
            for h, s in zip(pkg.hotels, pkg.plan.stays, strict=True)
        )
        / nights
    )
    assert best == by_hand


def test_same_signature_keeps_only_the_cheapest(three_way):
    base = three_way.packages[0]
    pricier_twin = base.with_(
        return_flight=replace(base.return_flight, price=base.return_flight.price + 1_000)
    )
    assert signature(pricier_twin) == signature(base)
    kept = cheapest_per_signature([pricier_twin, base])
    assert list(kept.values()) == [base]
    other = three_way.packages[2]  # a different hotel (higher stars)
    kept = cheapest_per_signature([pricier_twin, base, other])
    assert len(kept) == 2 and kept[signature(base)].total == base.total


# ------------------------------------------------------------------ 4: totals add up


def test_each_option_total_is_its_price_breakdown_and_the_package_total(client, menon):
    _, body = _search(client)
    assert len(body["options"]) == len(menon.packages)
    for opt, pkg in zip(body["options"], menon.packages, strict=True):
        parts = opt["preview"]["pricing"]
        assert sum(v for k, v in parts.items() if k != "total_inr") == parts["total_inr"]
        assert (
            opt["total_inr"] == parts["total_inr"] == pkg.total == price_breakdown(pkg)["total_inr"]
        )
        assert opt["budget_remaining_inr"] == opt["budget_inr"] - opt["total_inr"]


# ------------------------------------------------------------------ 5: count, labels, headline, note


def test_three_winners_show_cheapest_fastest_and_best_rated(client):
    r, body = _search(client, **THREE_WAY)
    assert r.status_code == 200 and body["status"] == "OPTIONS"
    assert body["count"] == len(body["options"]) == 3
    assert [o["labels"] for o in body["options"]] == [["Cheapest"], ["Fastest"], ["Best rated"]]
    assert [o["badges"] for o in body["options"]] == [o["labels"] for o in body["options"]]
    assert body["headline"] == "Cheapest, fastest and best rated: three holidays for your trip"
    assert body["note"] is None and body["subline"] == "Choose the one you like best"
    stats = [o["stats"] for o in body["options"]]
    assert stats[1]["travel_minutes"] == min(s["travel_minutes"] for s in stats)
    assert stats[2]["avg_stars"] == max(s["avg_stars"] for s in stats)


def test_a_tie_puts_two_labels_on_one_card(client):
    # Menon: the cheapest package also travels least, so it carries both labels on one card
    r, body = _search(client)
    assert r.status_code == 200 and body["count"] == len(body["options"]) == 2
    assert [o["labels"] for o in body["options"]] == [["Cheapest", "Fastest"], ["Best rated"]]
    assert body["headline"] == "Two holidays for your trip"
    assert "carries more than one label" in body["note"]


def test_one_holiday_can_win_all_three(client):
    # 4 nights, one adult, Delhi, budget 80 000: the cheapest package is also the fastest and the
    # best rated one that fits
    r, body = _search(client, nights=4, adults=1, child_ages=[], departure="DEL", budget=80_000)
    assert r.status_code == 200 and body["status"] == "OPTIONS"
    assert body["count"] == len(body["options"]) == 1
    assert body["options"][0]["labels"] == ["Cheapest", "Fastest", "Best rated"]
    assert body["headline"] == "One holiday for your trip"


def test_capped_search_drops_the_unproven_labels_and_says_so(client, monkeypatch):
    # the work cap stops the fastest and best-rated searches at once: only the proven cheapest is
    # shown, and the note says which labels could not be proven (never that they were)
    monkeypatch.setattr(engine_options, "MAX_OPTION_COMBINATIONS", 0)
    r, body = _search(client)
    assert r.status_code == 200 and body["count"] == 1 and len(body["options"]) == 1
    assert body["options"][0]["labels"] == ["Cheapest"]
    assert body["note"] == (
        "We could not prove which holiday is the fastest or best rated, so that label is not shown."
    )
    assert body["options"][0]["option_id"] == "opt-1" and body["options"][0]["recommended"] is True


# ------------------------------------------------------------------ 6: no option missing parts


def test_no_option_is_missing_flights_hotels_transfers_or_totals(client):
    _, body = _search(client)
    for opt in body["options"]:
        assert (
            opt["flights"]["arrival"]["flight_number"] and opt["flights"]["return"]["flight_number"]
        )
        assert (
            opt["flights"]["arrival"]["from"] == "BLR" and opt["flights"]["return"]["to"] == "BLR"
        )
        assert len(opt["hotels"]) == len(opt["cities"]) == len(opt["city_nights"])
        assert all(h["name"] and h["room"] for h in opt["hotels"])
        assert sum(c["nights"] for c in opt["city_nights"]) == opt["nights"] == 6
        days = opt["preview"]["days"]
        assert len(days) == opt["nights"] + 1
        pricing = opt["preview"]["pricing"]
        assert pricing["flights"] > 0 and pricing["hotels"] > 0 and pricing["airport_transfers"] > 0
        assert (pricing["intercity_transfers"] > 0) == (len(opt["cities"]) > 1)
        assert opt["stats"]["transfers"] == 2 + opt["stats"]["city_changes"]
        assert opt["stats"]["city_changes"] == len(opt["cities"]) - 1


# ------------------------------------------------------------------ 7-8: select saves exactly one


def test_a_search_saves_no_package(client):
    _, body = _search(client, **THREE_WAY)
    assert body["count"] == 3
    assert _rows() == 0


def test_select_saves_exactly_the_chosen_option_as_planned(client):
    _, body = _search(client)
    chosen = next(o for o in body["options"] if o["option_id"] == "opt-2")
    r = client.post(f"/api/package-options/{body['search_id']}/select", json={"option_id": "opt-2"})
    assert r.status_code == 201
    pkg = r.json()["package"]
    assert pkg["status"] == "PLANNED" and pkg["total_inr"] == chosen["total_inr"]
    assert pkg["pricing"]["total_inr"] == chosen["total_inr"]
    assert _rows() == 1
    with connect() as conn:
        totals = [row[0] for row in conn.execute("SELECT total_inr FROM packages")]
    assert totals == [chosen["total_inr"]]  # the unselected options were never saved
    assert (
        client.get(f"/api/packages/{pkg['id']}").json()["package"]["total_inr"]
        == chosen["total_inr"]
    )


def test_selecting_the_same_option_again_creates_no_second_row(client):
    _, body = _search(client)
    url = f"/api/package-options/{body['search_id']}/select"
    first = client.post(url, json={"option_id": "opt-1"})
    again = client.post(url, json={"option_id": "opt-1"})
    assert first.status_code == 201 and again.status_code == 200
    assert first.json()["package"]["id"] == again.json()["package"]["id"]
    assert _rows() == 1


# ------------------------------------------------------------------ 9: MINIMUM_COST


def test_minimum_cost_first_option_is_the_proven_minimum(client):
    proven = build_package(_trip(), CAT, MINIMUM_COST)
    assert proven.status == FOUND
    r, body = _search(client, objective=MINIMUM_COST)
    assert r.status_code == 200 and body["objective"] == MINIMUM_COST
    first = body["options"][0]
    assert first["total_inr"] == proven.package.total
    assert first["proven_minimum"] is True and first["labels"][0] == "Cheapest"
    assert all(o["total_inr"] >= proven.package.total for o in body["options"])
    assert all(o["proven_minimum"] is False for o in body["options"][1:])


# ------------------------------------------------------------------ 10: unchanged answers


def _strip_ids(value):
    """Drop what a save generates (package id, trip id, timestamps) so two answers can be compared."""
    if isinstance(value, dict):
        return {
            k: _strip_ids(v)
            for k, v in value.items()
            if k not in {"id", "package_id", "trip_id", "created_at", "updated_at"}
        }
    if isinstance(value, list):
        return [_strip_ids(v) for v in value]
    return value


def test_infeasible_request_answers_like_post_packages(client):
    old = client.post("/api/packages", json=BLR_JAPAN_INFEASIBLE)
    new = client.post("/api/package-options", json=BLR_JAPAN_INFEASIBLE)
    assert old.status_code == new.status_code == 200
    assert new.json() == old.json()
    assert new.json()["status"] == "INFEASIBLE"
    assert _rows() == 0


def test_over_budget_request_answers_like_post_packages(client):
    over = {**MENON, "budget": 200_000}
    old = client.post("/api/packages", json=over)
    new = client.post("/api/package-options", json=over)
    assert old.status_code == new.status_code == 201
    assert new.json()["status"] == OVER_BUDGET
    assert _strip_ids(new.json()) == _strip_ids(old.json())
    assert _rows() == 2  # each call saved its one OVER_BUDGET package


def test_invalid_request_is_422_like_post_packages(client):
    bad = {**MENON, "nights": 1}
    old = client.post("/api/packages", json=bad)
    new = client.post("/api/package-options", json=bad)
    assert old.status_code == new.status_code == 422
    assert new.json() == old.json()


def test_invalid_objective_is_422(client):
    r, body = _search(client, objective="CHEAPEST_EVER")
    assert r.status_code == 422 and body["error"] == "INVALID_REQUEST"


# ------------------------------------------------------------------ 404s and store rules


def test_unknown_search_is_search_expired(client):
    r = client.post("/api/package-options/not-a-search/select", json={"option_id": "opt-1"})
    assert r.status_code == 404
    assert r.json() == {
        "error": "SEARCH_EXPIRED",
        "message": "These options have expired. Search again to see fresh ones.",
    }


def test_expired_search_is_search_expired(client, monkeypatch):
    _, body = _search(client)
    monkeypatch.setattr(store, "TTL_SECONDS", -1)  # every search is now older than the TTL
    r = client.post(f"/api/package-options/{body['search_id']}/select", json={"option_id": "opt-1"})
    assert r.status_code == 404 and r.json()["error"] == "SEARCH_EXPIRED"
    assert _rows() == 0


def test_unknown_option_is_option_not_found(client):
    _, body = _search(client)
    r = client.post(f"/api/package-options/{body['search_id']}/select", json={"option_id": "opt-9"})
    assert r.status_code == 404 and r.json()["error"] == "OPTION_NOT_FOUND"
    assert _rows() == 0


def test_bad_select_body_is_422(client):
    _, body = _search(client)
    r = client.post(f"/api/package-options/{body['search_id']}/select", json={})
    assert r.status_code == 422


def test_store_keeps_at_most_max_searches_and_evicts_the_oldest(client, monkeypatch):
    monkeypatch.setattr(store, "MAX_SEARCHES", 2)
    _, first = _search(client)
    _search(client, budget=220_000)
    _search(client, budget=300_000)
    r = client.post(
        f"/api/package-options/{first['search_id']}/select", json={"option_id": "opt-1"}
    )
    assert r.status_code == 404 and r.json()["error"] == "SEARCH_EXPIRED"


def test_every_option_picks_up_on_the_landing_day_when_a_transfer_runs_that_night(menon):
    # the 21:30 landing would only have the next morning's bus (it stops at 22:00), so Menon now
    # flies in at 10:30 and takes the 11:30 bus: nobody waits overnight at the airport
    for pkg in menon.packages:
        assert pkg.arrival_transfer.pickup.date() == pkg.arrival_flight.arrival.date()
