"""Phase 4 API: POST /api/packages, GET /api/packages/{id}, GET /api/packages/{id}/export.

Run from backend/: ../.venv/bin/python -m pytest -q tests/test_package_api.py
Each test gets a fresh temporary database. The planner is stubbed where the point of the test is
the route's own behaviour (and to prove reads/exports never call it).
"""

import pytest
from fastapi.testclient import TestClient

from app.catalog.load import load_catalog
from app.db import connect
from app.engine.build import INFEASIBLE, SEARCH_INCOMPLETE, PlanningResult
from app.export.to_trip import to_trip_json
from app.main import app
from app.repositories import packages as repo
from app.routes import packages as routes
from app.validate.validate_trip import validate_trip

MENON = {
    "departure": "BLR",
    "country": "Japan",
    "start_date": "2027-04-10",
    "nights": 6,
    "adults": 2,
    "child_ages": [6],
    "budget": 350_000,
}
CAT = load_catalog()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HOLIDAY_DB_PATH", str(tmp_path / "app.db"))
    with TestClient(app) as c:  # runs the lifespan: catalog check + create_tables()
        yield c


def _rows():
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM packages").fetchone()[0]


def _no_planner(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the planner must not run here")

    monkeypatch.setattr(routes, "build_package", boom)


def _create(client, **over):
    r = client.post("/api/packages", json={**MENON, **over})
    return r, r.json()


# ------------------------------------------------------------------ POST


def test_valid_request_returns_a_persisted_package(client):
    r, body = _create(client)
    assert r.status_code == 201 and body["status"] == "FOUND"
    pkg = body["package"]
    assert (pkg["version"], pkg["status"], pkg["validation_mode"]) == (1, "PLANNED", "INITIAL")
    assert (
        pkg["country"] == "Japan"
        and pkg["start_date"] == "2027-04-10"
        and pkg["end_date"] == "2027-04-16"
    )
    assert pkg["city_plan"] and pkg["items"] and len(pkg["days"]) == 7
    assert _rows() == 1
    assert (
        client.get(f"/api/packages/{pkg['id']}").json() == body
    )  # what was returned is what was saved


def test_prices_and_budget_add_up(client):
    _, body = _create(client)
    pkg = body["package"]
    pricing, budget = pkg["pricing"], pkg["budget"]
    parts = ("flights", "hotels", "airport_transfers", "intercity_transfers", "attractions")
    assert sum(pricing[k] for k in parts) == pricing["total_inr"] == pkg["total_inr"]
    assert sum(i["price_inr"] for i in pkg["items"]) == pkg["total_inr"]
    assert budget == {
        "budget_inr": 350_000,
        "total_inr": pkg["total_inr"],
        "remaining_inr": 350_000 - pkg["total_inr"],
        "over_budget_inr": 0,
        "within_budget": True,
    }
    assert pkg["budget_remaining"] == budget["remaining_inr"]


def test_items_carry_stable_ids_for_later_changes(client):
    pkg = _create(client)[1]["package"]
    ids = [i["item_id"] for i in pkg["items"]]
    assert len(ids) == len(set(ids))
    assert ids[0] == "flight:arrival" and ids[1] == "leg:arrival"
    assert ids[-2:] == ["leg:departure", "flight:return"]
    hotels = [i for i in pkg["items"] if i["type"] == "hotel"]
    assert [h["item_id"] for h in hotels] == [c["stay_id"] for c in pkg["city_plan"]]
    assert all(h["room_id"] and h["item_id"].startswith("stay:") for h in hotels)
    assert all(
        i["item_id"] == f"visit:{i['catalog_id']}"
        for i in pkg["items"]
        if i["type"] == "attraction"
    )
    assert all(i["catalog_id"] for i in pkg["items"])


def test_day_timeline_follows_the_itinerary(client):
    pkg = _create(client)[1]["package"]
    days = pkg["days"]
    assert [d["day_number"] for d in days] == list(range(1, 8))
    assert days[0]["day_type"] == "ARRIVAL" and days[-1]["day_type"] == "DEPARTURE"
    assert days[0]["events"][0]["item_id"] == "flight:arrival"
    assert days[0]["events"][1]["item_id"] == "leg:arrival"
    assert days[-1]["events"][-1]["item_id"] == "flight:return"
    assert not [e for e in days[-1]["events"] if e["kind"] == "ATTRACTION"]
    assert days[-1]["overnight"] is None
    for d in days:
        if d["day_type"] == "FULL_DAY":
            assert 1 <= len([e for e in d["events"] if e["kind"] == "ATTRACTION"]) <= 2
        if d["day_type"] == "CITY_CHANGE":
            moves = [e for e in d["events"] if e["kind"] == "TRANSFER"]
            assert moves and moves[0]["display_details"]["to_city"] == d["city"] != d["from_city"]
        # in-country events share one time zone and are in time order
        timed = [e["start"] for e in d["events"] if e["kind"] in ("TRANSFER", "ATTRACTION")]
        assert timed == sorted(timed)
    shown = {e["item_id"] for d in days for e in d["events"]}
    assert shown == {i["item_id"] for i in pkg["items"]}


def test_invalid_request_returns_field_errors(client):
    r, body = _create(
        client, departure="XXX", nights=20, adults=0, child_ages=[6, "six"], budget=-1
    )
    assert r.status_code == 422 and body["status"] == "INVALID_REQUEST"
    assert set(body["field_errors"]) == {"departure", "nights", "adults", "child_ages", "budget"}
    assert body["field_errors"]["child_ages"] == [
        "Child 2's age 'six' must be a whole age from 0 to 17."
    ]
    assert _rows() == 0


def test_too_many_travelers_is_a_request_error(client):
    r, body = _create(client, adults=9, child_ages=[5])
    assert r.status_code == 422 and "travelers" in body["field_errors"]["request"][0]


def test_infeasible_result_returns_reasons_and_saves_nothing(client, monkeypatch):
    stub = PlanningResult(
        INFEASIBLE,
        None,
        None,
        None,
        None,
        ["No return flight has 3 seats."],
        True,
        ["INSUFFICIENT_FLIGHT_SEATS"],
    )
    monkeypatch.setattr(routes, "build_package", lambda *a, **k: stub)
    r, body = _create(client)
    assert r.status_code == 200
    assert body == {
        "status": "INFEASIBLE",
        "package": None,
        "reasons": ["No return flight has 3 seats."],
        "reason_codes": ["INSUFFICIENT_FLIGHT_SEATS"],
        "suggestions": [],
        "search_complete": True,
    }
    assert _rows() == 0


def test_real_infeasible_request(client):
    # every return flight from Japan to BLR on 2027-04-04 has fewer than 8 seats left
    r, body = _create(
        client, start_date="2027-04-01", nights=3, adults=6, child_ages=[3, 5], budget=900_000
    )
    assert r.status_code == 200 and body["status"] == "INFEASIBLE" and body["package"] is None
    assert body["reason_codes"] == ["INSUFFICIENT_FLIGHT_SEATS"] and body["reasons"]


def test_incomplete_search_is_not_called_infeasible(client, monkeypatch):
    stub = PlanningResult(
        SEARCH_INCOMPLETE,
        None,
        None,
        None,
        None,
        ["The search stopped."],
        False,
        [SEARCH_INCOMPLETE],
    )
    monkeypatch.setattr(routes, "build_package", lambda *a, **k: stub)
    r, body = _create(client)
    assert (
        r.status_code == 200
        and body["status"] == "SEARCH_INCOMPLETE"
        and body["search_complete"] is False
    )
    assert _rows() == 0


def test_over_budget_returns_the_proven_cheapest_package(client):
    r, body = _create(client, budget=1_000)
    assert r.status_code == 201 and body["status"] == "OVER_BUDGET"
    pkg = body["package"]
    assert body["cheapest_total_inr"] == pkg["total_inr"]
    assert body["shortfall_inr"] == pkg["total_inr"] - 1_000 == pkg["budget"]["over_budget_inr"]
    assert pkg["budget"]["remaining_inr"] == 0 and pkg["budget_remaining"] == 0
    assert body["reasons"] and body["suggestions"]
    again = client.get(f"/api/packages/{pkg['id']}").json()
    assert again["status"] == "OVER_BUDGET" and again["reasons"] == body["reasons"]


def test_planner_defect_is_not_saved(client, monkeypatch):
    real = routes.build_package

    def tampered(*a, **k):
        result = real(*a, **k)
        flight = result.package.arrival_flight
        result.package = result.package.with_(
            arrival_flight=flight.__class__(**{**vars(flight), "price": 1})
        )
        return result

    monkeypatch.setattr(routes, "build_package", tampered)
    r, body = _create(client)
    assert r.status_code == 500 and body["error"] == "PACKAGE_INVALID"
    assert _rows() == 0


# ------------------------------------------------------------------ GET


def test_unknown_package_is_404(client):
    r = client.get("/api/packages/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404
    assert r.json() == {
        "error": "PACKAGE_NOT_FOUND",
        "message": "This holiday package could not be found.",
    }


def test_get_does_not_call_the_planner(client, monkeypatch):
    _, created = _create(client)
    _no_planner(monkeypatch)
    r = client.get(f"/api/packages/{created['package']['id']}")
    assert r.status_code == 200 and r.json() == created


def test_package_survives_an_app_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("HOLIDAY_DB_PATH", str(tmp_path / "restart.db"))
    with TestClient(app) as first:
        created = first.post("/api/packages", json=MENON).json()
    _no_planner(monkeypatch)
    with TestClient(app) as second:  # a new lifespan on the same database file
        assert second.get(f"/api/packages/{created['package']['id']}").json() == created


def test_unreadable_package_is_500_not_a_replanned_one(client):
    package_id = _create(client)[1]["package"]["id"]
    with connect() as conn:
        conn.execute("UPDATE packages SET total_inr = 1 WHERE id = ?", (package_id,))
    r = client.get(f"/api/packages/{package_id}")
    assert r.status_code == 500 and r.json()["error"] == "PACKAGE_UNREADABLE"


# ------------------------------------------------------------------ export


def test_export_is_the_saved_package_in_the_trip_format(client, monkeypatch):
    package_id = _create(client)[1]["package"]["id"]
    _no_planner(monkeypatch)
    r = client.get(f"/api/packages/{package_id}/export")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert r.headers["content-disposition"] == 'attachment; filename="holiday-package.json"'
    trip = r.json()
    assert trip == to_trip_json(repo.get_package(package_id).package, CAT)
    assert trip["trip_id"] == package_id and trip["country"] == "Japan"
    assert (trip["start_date"], trip["end_date"]) == ("2027-04-10", "2027-04-16")
    assert all(i["status"] == "PLANNED" and i["booking"] is None for i in trip["items"])
    assert all(i["room_id"] for i in trip["items"] if i["type"] == "hotel")
    assert {"flight", "hotel", "transfer", "attraction"} <= {i["type"] for i in trip["items"]}
    assert validate_trip(trip, CAT, "INITIAL") == []
    assert r.headers["x-trip-valid"] == "true"


def test_export_of_unknown_package_is_404(client):
    assert client.get("/api/packages/nope/export").status_code == 404
