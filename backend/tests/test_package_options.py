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
from app.engine.options import cheapest_per_signature, find_package_options, signature
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
    base = dict(departure_airport="BLR", destination_country="Japan", start_date=date(2027, 4, 10),
                nights=6, adults=2, children_ages=[6], budget=350_000)
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


# ------------------------------------------------------------------ 1-2: complete and distinct

def test_menon_returns_up_to_three_complete_clean_options(menon):
    assert menon.primary.status == FOUND
    assert 1 <= len(menon.packages) <= 3
    assert len(menon.packages) == 3                       # Menon has three distinct options
    for pkg in menon.packages:
        assert validate_trip(to_trip_json(pkg, CAT), CAT, INITIAL) == []
        assert pkg.arrival_flight and pkg.return_flight
        assert len(pkg.hotels) == len(pkg.plan.stays)
        assert len(pkg.intercity) == len(pkg.plan.legs())
        assert pkg.arrival_transfer and pkg.departure_transfer
        assert pkg.total <= pkg.budget


def test_menon_options_are_pairwise_distinct_by_signature(menon):
    sigs = [signature(p) for p in menon.packages]
    assert len(set(sigs)) == len(sigs)


def test_primary_is_the_package_the_planner_builds(menon):
    primary = build_package(_trip(), CAT, WITHIN_BUDGET)
    assert menon.packages[0].total == primary.package.total
    assert signature(menon.packages[0]) == signature(primary.package)


# ------------------------------------------------------------------ 3: near-duplicates filtered

def test_same_signature_keeps_only_the_cheapest(menon):
    base = menon.packages[0]
    pricier_twin = base.with_(return_flight=replace(base.return_flight,
                                                    price=base.return_flight.price + 1_000))
    assert signature(pricier_twin) == signature(base)
    kept = cheapest_per_signature([pricier_twin, base])
    assert list(kept.values()) == [base]
    other = menon.packages[1]
    kept = cheapest_per_signature([pricier_twin, base, other])
    assert len(kept) == 2 and kept[signature(base)].total == base.total


# ------------------------------------------------------------------ 4: totals add up

def test_each_option_total_is_its_price_breakdown_and_the_package_total(client, menon):
    _, body = _search(client)
    assert len(body["options"]) == len(menon.packages)
    for opt, pkg in zip(body["options"], menon.packages):
        parts = opt["preview"]["pricing"]
        assert sum(v for k, v in parts.items() if k != "total_inr") == parts["total_inr"]
        assert opt["total_inr"] == parts["total_inr"] == pkg.total == price_breakdown(pkg)["total_inr"]
        assert opt["budget_remaining_inr"] == opt["budget_inr"] - opt["total_inr"]


# ------------------------------------------------------------------ 5: count, headline, note

def _headline_for(count):
    return {3: "We found 3 holiday options for your trip",
            2: "We found 2 distinct holiday options for your search.",
            1: "We found 1 complete holiday option for your search."}[count]


def test_menon_count_headline_and_note_are_truthful(client):
    r, body = _search(client)
    assert r.status_code == 200 and body["status"] == "OPTIONS"
    assert body["count"] == len(body["options"]) == 3
    assert body["headline"] == _headline_for(3) and body["note"] is None
    assert body["subline"] == "Choose the one you like best"


def test_two_options_say_two_with_no_note(client):
    # budget 220 000: the planner's best is 219 884 and the next distinct stay is 219 520 (verified)
    r, body = _search(client, budget=220_000)
    assert r.status_code == 200 and body["status"] == "OPTIONS"
    assert body["count"] == len(body["options"]) == 2
    assert body["headline"] == _headline_for(2) and body["note"] is None


def test_one_option_says_one_and_states_no_more_were_verified(client):
    # a real request: 4 nights, one adult, Delhi, budget 80 000. The search finished (complete)
    # and found only one distinct stay pattern within budget.
    r, body = _search(client, nights=4, adults=1, child_ages=[], departure="DEL", budget=80_000)
    assert r.status_code == 200 and body["status"] == "OPTIONS"
    assert body["count"] == len(body["options"]) == 1
    assert body["headline"] == _headline_for(1)
    assert body["note"] == "No additional distinct package options were verified."


def test_capped_extra_search_returns_fewer_and_says_so(client, monkeypatch):
    # the work cap stops the extra search at once: only the primary can be shown, and the note says
    # that no other option was verified (never that the cheapest was proven)
    monkeypatch.setattr(engine_options, "MAX_OPTION_COMBINATIONS", 0)
    r, body = _search(client)
    assert r.status_code == 200 and body["count"] == 1 and len(body["options"]) == 1
    assert body["note"] == "No additional distinct package options were verified."
    assert body["options"][0]["option_id"] == "opt-1" and body["options"][0]["recommended"] is True


# ------------------------------------------------------------------ 6: no option missing parts

def test_no_option_is_missing_flights_hotels_transfers_or_totals(client):
    _, body = _search(client)
    for opt in body["options"]:
        assert opt["flights"]["arrival"]["flight_number"] and opt["flights"]["return"]["flight_number"]
        assert opt["flights"]["arrival"]["from"] == "BLR" and opt["flights"]["return"]["to"] == "BLR"
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
    _, body = _search(client)
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
    assert totals == [chosen["total_inr"]]                 # the unselected options were never saved
    assert client.get(f"/api/packages/{pkg['id']}").json()["package"]["total_inr"] == chosen["total_inr"]


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
    assert first["proven_minimum"] is True
    assert "Proven lowest price for this date" in first["badges"]
    assert all(o["total_inr"] >= proven.package.total for o in body["options"])
    assert all(o["proven_minimum"] is False for o in body["options"][1:])


# ------------------------------------------------------------------ 10: unchanged answers

def _strip_ids(value):
    """Drop what a save generates (package id, trip id, timestamps) so two answers can be compared."""
    if isinstance(value, dict):
        return {k: _strip_ids(v) for k, v in value.items()
                if k not in {"id", "package_id", "trip_id", "created_at", "updated_at"}}
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
    assert _rows() == 2                                    # each call saved its one OVER_BUDGET package


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
    assert r.json() == {"error": "SEARCH_EXPIRED",
                        "message": "These options have expired. Search again to see fresh ones."}


def test_expired_search_is_search_expired(client, monkeypatch):
    _, body = _search(client)
    monkeypatch.setattr(store, "TTL_SECONDS", -1)           # every search is now older than the TTL
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
    r = client.post(f"/api/package-options/{first['search_id']}/select", json={"option_id": "opt-1"})
    assert r.status_code == 404 and r.json()["error"] == "SEARCH_EXPIRED"
