"""G4: Cheapest, Fastest and Best rated, checked against a brute-force oracle and the metric rules.

Run from backend/: ../.venv/bin/python -m pytest -q tests/test_g4_recommendations.py
Real catalog. The oracle enumerates EVERY combination of every candidate (city plan, flights, hotel
rooms, transfers) for a small request and validates each one; it never calls the label search.
"""

import math
from dataclasses import replace
from datetime import date, timedelta
from fractions import Fraction

import pytest
from fastapi.testclient import TestClient

from app.catalog.load import load_catalog
from app.db import connect
from app.engine.build import MINIMUM_COST, _product_in_cost_order, _Search, build_package
from app.engine.constraints import PlanningConstraints
from app.engine.options import (
    BEST_RATED,
    CHEAPEST,
    FASTEST,
    FASTEST_IN_BUDGET,
    _flight_minutes,
    find_package_options,
    travel_minutes,
    weighted_stars,
)
from app.export.to_trip import to_trip_json
from app.main import app
from app.models import TripRequest
from app.rules.common import INITIAL
from app.validate.validate_trip import validate_trip

CAT = load_catalog()
# small enough to enumerate (9 472 combinations), and every G4 trade-off shows up in it:
# cheapest != fastest != best rated, a night-weighted average (23/5 stars) decides best rated, and
# five-star stays exist but cost more than the budget
SMALL = dict(
    departure_airport="DEL",
    destination_country="JP",
    start_date=date(2027, 4, 10),
    nights=5,
    adults=1,
    children_ages=[],
    budget=150_000,
)
MENON = {
    "departure": "BLR",
    "country": "Japan",
    "start_date": "2027-04-10",
    "nights": 6,
    "adults": 2,
    "child_ages": [6],
    "budget": 350_000,
}


def _stars_of(pkg):
    """Independent re-computation: catalog stars x nights / nights, as an exact fraction."""
    num = sum(
        CAT.indexes.hotels_by_id[h.hotel_id]["stars"] * (h.check_out - h.check_in).days
        for h in pkg.hotels
    )
    return Fraction(num, sum((h.check_out - h.check_in).days for h in pkg.hotels))


def _minutes_of(pkg):
    """Independent re-computation from the catalog duration fields."""
    F, T = CAT.indexes.flights_by_id, CAT.indexes.transfers_by_id
    return (
        F[pkg.arrival_flight.flight_id]["duration_minutes"]
        + F[pkg.return_flight.flight_id]["duration_minutes"]
        + sum(T[t.transfer_id]["duration_minutes"] for t in pkg.intercity)
    )


@pytest.fixture(scope="module")
def every_package():
    """Every complete, validator-clean package for SMALL (with its cheapest attraction schedule)."""
    s = _Search(TripRequest(**SMALL), CAT, PlanningConstraints())
    triples = s.triples()
    assert sum(math.prod(len(sl) for sl in t[5]) for t in triples) < 20_000
    out = []
    for _, _, plan, arr, ret, slots, _ in triples:
        n = len(plan.stays)
        for _, choice in _product_in_cost_order(slots):  # the full product, every element
            sched = s.attractions(plan, choice[0][1], choice[n:], choice[n - 1][2])
            if not sched.feasible:
                continue
            pkg = s.assemble(plan, arr, ret, choice, sched.visits)
            if not validate_trip(to_trip_json(pkg, CAT), CAT, INITIAL):
                out.append(pkg)
    assert len(out) > 1000
    return out


@pytest.fixture(scope="module")
def small():
    return find_package_options(TripRequest(**SMALL), CAT)


def _by_label(found, label):
    return next(
        p for p, labels in zip(found.packages, found.labels, strict=True) if label in labels
    )


# ------------------------------------------------------------------ the oracle


def test_cheapest_matches_the_oracle(small, every_package):
    assert _by_label(small, CHEAPEST).total == min(p.total for p in every_package)


def test_fastest_matches_the_oracle(small, every_package):
    best = min(_minutes_of(p) for p in every_package)
    fastest = _by_label(small, FASTEST)
    assert travel_minutes(fastest, CAT) == _minutes_of(fastest) == best
    # it travels less than the cheapest package: price alone does not decide it
    assert best < _minutes_of(_by_label(small, CHEAPEST))


def test_best_rated_matches_the_oracle_within_budget(small, every_package):
    budget = SMALL["budget"]
    best = max(_stars_of(p) for p in every_package if p.total <= budget)
    assert best == Fraction(23, 5)  # 5 stars x 3 nights + 4 x 2, over 5
    rated = _by_label(small, BEST_RATED)
    assert weighted_stars(rated, CAT) == _stars_of(rated) == best and rated.total <= budget
    # a higher rating exists but costs more than the budget, so it is excluded
    assert max(_stars_of(p) for p in every_package) > best


def test_the_three_winners_are_different_packages(small):
    assert small.complete and small.unproven == ()
    assert small.labels == ((CHEAPEST,), (FASTEST,), (BEST_RATED,))


# ------------------------------------------------------------------ metric rules


@pytest.fixture(scope="module")
def menon_pkg():
    return build_package(
        TripRequest(
            departure_airport="BLR",
            destination_country="JP",
            start_date=date(2027, 4, 10),
            nights=6,
            adults=2,
            children_ages=[6],
            budget=350_000,
        ),
        CAT,
        MINIMUM_COST,
    ).package


def test_travel_time_ignores_airport_transfers_and_visits(menon_pkg):
    later = timedelta(hours=5)
    moved = menon_pkg.with_(
        arrival_transfer=replace(
            menon_pkg.arrival_transfer, arrive=menon_pkg.arrival_transfer.arrive + later
        ),
        departure_transfer=replace(
            menon_pkg.departure_transfer, pickup=menon_pkg.departure_transfer.pickup - later
        ),
        visits=(),
    )
    assert travel_minutes(moved, CAT) == travel_minutes(menon_pkg, CAT)


def test_travel_time_counts_every_transfer_between_cities(small):
    pkg = _by_label(small, BEST_RATED)
    assert pkg.intercity
    leg = pkg.intercity[0]
    slower = pkg.with_(
        intercity=(replace(leg, arrive=leg.arrive + timedelta(minutes=30)),) + pkg.intercity[1:]
    )
    assert travel_minutes(slower, CAT) == travel_minutes(pkg, CAT) + 30


def test_flight_time_uses_the_catalog_duration_not_local_clock_times(menon_pkg):
    f = menon_pkg.arrival_flight  # BLR (IST) -> Japan (JST), overnight
    clock = int((f.arrival - f.departure).total_seconds() // 60)
    assert _flight_minutes(f, CAT) == CAT.indexes.flights_by_id[f.flight_id]["duration_minutes"]
    assert _flight_minutes(f, CAT) != clock  # 3h30 time difference


def test_stars_are_weighted_by_nights_not_rooms(small):
    pkg = _by_label(small, BEST_RATED)
    more_rooms = pkg.with_(hotels=tuple(replace(h, rooms=h.rooms + 3) for h in pkg.hotels))
    assert weighted_stars(more_rooms, CAT) == weighted_stars(pkg, CAT) == Fraction(23, 5)
    # 5 stars for 1 night + 3 stars for 4 nights is 3.4, below 4 stars every night
    assert Fraction(5 * 1 + 3 * 4, 5) < Fraction(4)


def test_guest_rating_never_changes_best_rated(monkeypatch, small):
    rated = _by_label(small, BEST_RATED)
    for hotel_id, rec in list(CAT.indexes.hotels_by_id.items()):
        monkeypatch.setitem(
            CAT.indexes.hotels_by_id, hotel_id, {**rec, "rating": 10 - rec.get("rating", 5)}
        )
    again = find_package_options(TripRequest(**SMALL), CAT)
    assert [h.hotel_id for h in _by_label(again, BEST_RATED).hotels] == [
        h.hotel_id for h in rated.hotels
    ]


def test_a_hotel_without_stars_is_never_used_for_best_rated(monkeypatch, small):
    rated = _by_label(small, BEST_RATED)
    top = next(
        h.hotel_id for h in rated.hotels if CAT.indexes.hotels_by_id[h.hotel_id]["stars"] == 5
    )
    monkeypatch.setitem(
        CAT.indexes.hotels_by_id, top, {**CAT.indexes.hotels_by_id[top], "stars": None}
    )
    again = find_package_options(TripRequest(**SMALL), CAT)
    best = _by_label(again, BEST_RATED)
    assert top not in [h.hotel_id for h in best.hotels]
    assert weighted_stars(best, CAT) is not None
    assert weighted_stars(rated, CAT) is None  # no guessed value for the unrated stay


def test_results_are_deterministic():
    a = find_package_options(TripRequest(**SMALL), CAT)
    b = find_package_options(TripRequest(**SMALL), CAT)
    assert a.labels == b.labels
    assert [to_trip_json(p, CAT)["items"] for p in a.packages] == [
        to_trip_json(p, CAT)["items"] for p in b.packages
    ]


# ------------------------------------------------------------------ API: budget, landscape, booking


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HOLIDAY_DB_PATH", str(tmp_path / "app.db"))
    with TestClient(app) as c:
        yield c


def _rows():
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM packages").fetchone()[0]


SMALL_API = {
    "departure": "DEL",
    "country": "Japan",
    "start_date": "2027-04-10",
    "nights": 5,
    "adults": 1,
    "child_ages": [],
}


def test_fastest_above_the_budget_is_shown_with_a_within_budget_fastest(client):
    # 100 000: the fastest holiday costs 106 439 (1145 min); the cheapest (87 483) is the fastest
    # one within the budget, and a better-rated one (97 507) still fits
    body = client.post("/api/package-options", json={**SMALL_API, "budget": 100_000}).json()
    labels = [o["labels"] for o in body["options"]]
    assert labels == [[CHEAPEST, FASTEST_IN_BUDGET], [FASTEST], [BEST_RATED]]
    over = body["options"][1]
    assert over["over_budget"] is True and over["budget_remaining_inr"] < 0
    assert over["metrics"]["travel_minutes"] < body["options"][0]["metrics"]["travel_minutes"]
    assert "costs more than your budget" in body["note"]
    assert {w["label"] for w in over["why"]} == {FASTEST}

    sid = body["search_id"]
    refused = client.post(f"/api/package-options/{sid}/select", json={"option_id": "opt-2"})
    assert refused.status_code == 409 and refused.json()["error"] == "OVER_BUDGET_NOT_ACCEPTED"
    assert _rows() == 0
    saved = client.post(
        f"/api/package-options/{sid}/select",
        json={"option_id": "opt-2", "accept_over_budget": True},
    )
    assert saved.status_code == 201 and _rows() == 1


def test_option_metrics_are_exact_and_explained(client):
    body = client.post("/api/package-options", json=MENON).json()
    for opt in body["options"]:
        m = opt["metrics"]
        assert m["total_inr"] == opt["total_inr"]
        assert m["weighted_hotel_stars"] == m["star_nights"] / m["hotel_nights"]
        assert m["hotel_nights"] == opt["nights"]
        assert [w["label"] for w in opt["why"]] == opt["labels"]


def test_cheapest_matches_the_price_landscape_minimum(client):
    cheapest = client.post("/api/package-options", json=MENON).json()["options"][0]
    assert cheapest["labels"][0] == CHEAPEST
    cells = client.post(
        "/api/date-prices",
        json={**MENON, "range_start": MENON["start_date"], "range_end": MENON["start_date"]},
    ).json()["dates"]
    cell = next(c for c in cells if c["date"] == MENON["start_date"])
    assert cell["proven_minimum"] is True and cell["min_total_inr"] == cheapest["total_inr"]


def test_booking_the_fastest_keeps_exactly_that_holiday(client):
    body = client.post("/api/package-options", json=MENON).json()
    fastest = next(o for o in body["options"] if FASTEST in o["labels"])
    sid = body["search_id"]
    saved = client.post(
        f"/api/package-options/{sid}/select", json={"option_id": fastest["option_id"]}
    )
    package_id = saved.json()["package"]["id"]
    confirmed = client.post(f"/api/packages/{package_id}/confirm", json={"base_version": 1}).json()
    assert confirmed["status"] == "BOOKED" and confirmed["total_inr"] == fastest["total_inr"]
    trip = client.get(f"/api/reservations/{confirmed['reference']}").json()["trip"]
    by_type = {}
    for i in trip["items"]:
        by_type.setdefault(i["type"], []).append(i["catalog_id"])
    flights, hotels = CAT.indexes.flights_by_id, CAT.indexes.hotels_by_id
    assert [flights[f]["flight_number"] for f in by_type["flight"]] == [
        fastest["flights"]["arrival"]["flight_number"],
        fastest["flights"]["return"]["flight_number"],
    ]
    assert [hotels[h]["name"] for h in by_type["hotel"]] == [h["name"] for h in fastest["hotels"]]
    assert _rows() == 1  # only the chosen option was saved
