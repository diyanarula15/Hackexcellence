"""Explanations for holidays that cannot be generated (services/explanations.py) and the
create_package responses that carry them.

Run from backend/: ../.venv/bin/python -m pytest -q tests/test_explanations.py
Real catalog for the Menon and BLR-Japan cases; tiny synth catalogs where the point is a
partial (SOME) failure. The planner is only stubbed where a SEARCH_INCOMPLETE result is needed.
"""

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.catalog.load import load_catalog
from app.engine.build import (FOUND, INFEASIBLE, MINIMUM_COST, OVER_BUDGET, SEARCH_INCOMPLETE,
                              PlanningResult, build_package)
from app.engine.flights import find_return_flights
from app.lib.money import rupees
from app.main import app
from app.models import TripRequest
from app.routes import packages as routes
from app.services.explanations import explain
from synth import World, request

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
BLR_JAPAN = {
    "departure": "BLR",
    "country": "Japan",
    "start_date": "2027-04-01",
    "nights": 6,
    "adults": 4,
    "child_ages": [3, 9],
    "budget": 600_000,
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HOLIDAY_DB_PATH", str(tmp_path / "app.db"))
    with TestClient(app) as c:  # runs the lifespan: catalog check + create_tables()
        yield c


def _trip(**over) -> TripRequest:
    base = dict(departure_airport="BLR", destination_country="Japan", start_date=date(2027, 4, 10),
                nights=6, adults=2, children_ages=[6], budget=350_000)
    return TripRequest(**{**base, **over})


# ------------------------------------------------------------------ OVER_BUDGET


def test_menon_under_budget_is_over_budget_with_the_proven_minimum():
    trip = _trip(budget=100_000)
    res = build_package(trip, CAT)
    assert res.status == OVER_BUDGET                       # not INFEASIBLE: a package exists

    minimum = build_package(trip, CAT, MINIMUM_COST).cheapest_total
    assert res.cheapest_total == minimum
    expl = explain(res, trip, CAT)

    assert expl["kind"] == OVER_BUDGET
    assert expl["headline"] == f"No complete holiday fits your budget of {rupees(100_000)}"
    assert expl["summary"] == (f"The cheapest valid holiday for your dates and travelers costs "
                               f"{rupees(minimum)} - {rupees(minimum - 100_000)} over your budget.")
    assert expl["reasons"] == [{
        "code": "OVER_BUDGET", "scope": "REQUEST",
        "message": (f"The cheapest valid package costs {rupees(minimum)}, which is "
                    f"{rupees(minimum - 100_000)} over the budget of {rupees(100_000)}."),
    }]
    assert expl["suggest_alternatives"] is True


def test_menon_over_budget_numbers_match_the_minimum_cost_objective():
    trip = _trip(budget=100_000)
    minimum = build_package(trip, CAT, MINIMUM_COST).cheapest_total
    expl = explain(build_package(trip, CAT), trip, CAT)
    assert str(rupees(minimum)) in expl["summary"]
    assert str(rupees(minimum - 100_000)) in expl["summary"]
    assert f"{rupees(minimum)}" in expl["reasons"][0]["message"]


# ------------------------------------------------------------------ INFEASIBLE (real catalog)


def test_blr_japan_has_no_return_seats_and_every_reason_is_global_for_that_data():
    trip = TripRequest(**{"departure_airport": "BLR", "destination_country": "Japan",
                          "start_date": date(2027, 4, 1), "nights": 6, "adults": 4,
                          "children_ages": [3, 9], "budget": 600_000})
    res = build_package(trip, CAT)
    assert res.status == INFEASIBLE and res.package is None

    # The catalog really has the return flight on that date, but no seats for 6 travelers.
    end = trip.start_date + timedelta(days=trip.nights)
    with_seats = find_return_flights(trip, CAT)
    without_seats = find_return_flights(trip, CAT, ignore_seats=True)
    assert not with_seats and without_seats

    expl = explain(res, trip, CAT)
    assert expl["kind"] == INFEASIBLE
    assert expl["headline"] == "No complete holiday found for your search"
    assert expl["suggest_alternatives"] is True
    assert expl["reasons"], "an infeasible result must give at least one reason"

    failures = {f["code"]: f for f in res.failures}
    for reason in expl["reasons"]:
        entry = failures[reason["code"]]
        assert entry["plans_failed"] <= entry["plans_total"]
        if reason["scope"] == "ALL":
            assert entry["plans_failed"] == entry["plans_total"]        # blocked every city plan
        else:
            assert entry["plans_failed"] < entry["plans_total"]

    seats = next(r for r in expl["reasons"] if r["code"] == "INSUFFICIENT_FLIGHT_SEATS")
    assert seats["scope"] == "ALL"
    assert seats["message"] == f"No flight leaves Japan for BLR on {end.day} {end:%b %Y} with 6 free seats."
    assert expl["summary"].startswith(seats["message"])


def test_infeasible_summary_never_names_a_single_cause_when_no_reason_is_global():
    # Two city plans. Every plan is blocked, but no single reason blocks both of them.
    w = _mixed_world()
    req = request(nights=4, adults=2)
    res = build_package(req, w.loaded(), MINIMUM_COST)
    assert res.status == INFEASIBLE

    expl = explain(res, req, w.loaded())
    assert expl["reasons"] and all(r["scope"] == "SOME" for r in expl["reasons"])
    assert expl["summary"].startswith("No single reason stopped every possible city plan.")


# ------------------------------------------------------------------ SOME is not ALL (synth)


def _mixed_world() -> World:
    """Two single-city plans. The X plan has no hotel that fits the party (so it fails on its hotel).
    The Y plan has flights that land and leave at AX, which does not serve Y (so it fails on flights).
    Only the hotel reason is about some plans and not others, and it is the one under test."""
    w = World(cities=("X", "Y"), links=(), per_city=1)
    w.flight("F-IN-AX", "HOM", "AX", "2027-04-09T22:00:00", "2027-04-10T08:00:00", 1000)
    out = "2027-04-14"
    w.flight("F-OUT-AX", "AX", "HOM", f"{out}T18:00:00", f"{out}T23:00:00", 1000)
    w.hotel("H-Y", "Y")
    w.room("R-Y", "H-Y", 400)
    w.airport_transfer("T-AY", "AY", "Y", 120)
    for i in (1, 2, 3):
        w.attraction(f"ATT-X{i}", "X", 50)
        w.attraction(f"ATT-Y{i}", "Y", 40)
    return w


def test_hotel_gap_that_stops_only_some_plans_is_reported_as_some_not_all():
    w = _mixed_world()
    req = request(nights=4, adults=2)
    res = build_package(req, w.loaded(), MINIMUM_COST)
    assert res.status == INFEASIBLE

    hotel = next(f for f in res.failures if f["code"] == "NO_HOTEL_CAPACITY")
    assert (hotel["plans_failed"], hotel["plans_total"]) == (1, 2)

    expl = explain(res, req, w.loaded())
    reason = next(r for r in expl["reasons"] if r["code"] == "NO_HOTEL_CAPACITY")
    assert reason["scope"] == "SOME"
    assert reason["message"] == "1 of 2 possible city plans had no room type large enough for the travelers."
    assert not [r for r in expl["reasons"] if r["code"] == "NO_HOTEL_CAPACITY" and r["scope"] == "ALL"]
    assert "No single reason stopped every possible city plan" in expl["summary"]


# ------------------------------------------------------------------ SEARCH_INCOMPLETE and FOUND


def test_search_incomplete_explanation_never_claims_no_holiday_exists():
    trip = _trip()
    result = PlanningResult(SEARCH_INCOMPLETE, None, None, None, None,
                            ["The search stopped after 2000000 combinations without a proof."], False,
                            ["SEARCH_INCOMPLETE"])
    expl = explain(result, trip, CAT)
    assert expl["kind"] == SEARCH_INCOMPLETE
    assert expl["headline"] == "We couldn't finish checking every holiday combination"
    assert expl["reasons"] == []
    assert expl["suggest_alternatives"] is False
    assert "fewer nights" in expl["summary"] and "start date" in expl["summary"]
    text = str.lower(expl["headline"] + " " + expl["summary"])
    assert "no trip" not in text and "impossible" not in text and "no holiday exists" not in text


def test_found_or_within_budget_has_no_explanation():
    trip = _trip()                                          # budget 350,000
    res = build_package(trip, CAT)
    assert res.status == FOUND
    assert explain(res, trip, CAT) is None


# ------------------------------------------------------------------ create_package responses


def test_menon_within_budget_response_is_unchanged_and_has_no_explanation(client):
    body = {"departure": "BLR", "country": "Japan", "start_date": "2027-04-10", "nights": 6,
            "adults": 2, "child_ages": [6], "budget": 350_000}
    r = client.post("/api/packages", json=body)
    data = r.json()
    assert r.status_code == 201
    assert data["status"] == FOUND
    assert data["package"] is not None
    assert set(data) == {"status", "package", "reasons", "reason_codes", "suggestions",
                         "cheapest_total_inr", "shortfall_inr"}


def test_menon_over_budget_response_carries_explanation_with_the_same_numbers(client):
    r = client.post("/api/packages", json={**MENON, "budget": 100_000})
    data = r.json()
    assert r.status_code == 201 and data["status"] == OVER_BUDGET
    minimum = build_package(_trip(budget=100_000), CAT, MINIMUM_COST).cheapest_total
    assert data["cheapest_total_inr"] == minimum
    assert data["shortfall_inr"] == minimum - 100_000
    assert data["explanation"]["kind"] == OVER_BUDGET
    assert data["explanation"]["summary"].startswith(f"The cheapest valid holiday for your dates and travelers costs {rupees(minimum)}")
    assert data["package"]["budget"]["within_budget"] is False     # existing fields unchanged


def test_blr_japan_infeasible_response_carries_explanation(client):
    r = client.post("/api/packages", json=BLR_JAPAN)
    data = r.json()
    assert r.status_code == 200
    assert data["status"] == INFEASIBLE and data["package"] is None
    assert data["search_complete"] is True
    assert "INSUFFICIENT_FLIGHT_SEATS" in data["reason_codes"]
    assert data["explanation"]["kind"] == INFEASIBLE
    assert {r["code"] for r in data["explanation"]["reasons"]} == set(data["reason_codes"])


def test_search_incomplete_response_carries_explanation(client, monkeypatch):
    def incomplete(*a, **k):
        return PlanningResult(SEARCH_INCOMPLETE, None, None, None, None,
                              ["The search stopped after 2000000 combinations without a proof."], False,
                              ["SEARCH_INCOMPLETE"])

    monkeypatch.setattr(routes, "build_package", incomplete)
    r = client.post("/api/packages", json=MENON)
    data = r.json()
    assert r.status_code == 200
    assert data["status"] == SEARCH_INCOMPLETE and data["search_complete"] is False
    assert data["explanation"]["kind"] == SEARCH_INCOMPLETE
    text = str.lower(data["explanation"]["headline"] + " " + data["explanation"]["summary"])
    assert "no trip" not in text and "impossible" not in text
