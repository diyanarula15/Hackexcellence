"""Trip alternatives API: POST /api/trip-alternatives. Read-only, real catalog and real planner.

Run from backend/: ../.venv/bin/python -m pytest -q tests/test_trip_alternatives.py
Each test gets a fresh temporary database. Nothing is stubbed.
"""

import contextlib
import sqlite3
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.catalog.load import load_catalog
from app.db import db_path
from app.main import app
from app.services import trip_alternatives

CAT = load_catalog()
# INFEASIBLE original (the planner proves no holiday starts 1 Apr 2027 for this party)
INFEASIBLE = {
    "departure": "BLR", "country": "Japan", "start_date": "2027-04-01", "nights": 6,
    "adults": 4, "child_ages": [3, 9], "budget": 600_000,
}
# FOUND original
FEASIBLE = {**INFEASIBLE, "start_date": "2027-04-10"}
API_FIELDS = {"departure", "country", "start_date", "nights", "adults", "child_ages", "budget"}
RULES = CAT.catalog.destinations["rules"]
FIRST_NIGHT = date.fromisoformat(RULES["data_window"]["first_night"])
LAST_DEPARTURE = date.fromisoformat(RULES["data_window"]["last_departure"])


@pytest.fixture(autouse=True)
def _fresh_cache():
    from app.services.date_price_cache import CACHE
    CACHE.clear()
    yield
    CACHE.clear()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HOLIDAY_DB_PATH", str(tmp_path / "app.db"))
    with TestClient(app) as c:  # runs the lifespan: catalog check + create_tables()
        yield c


def _alternatives(client, body):
    return client.post("/api/trip-alternatives", json=body)


def _snapshot() -> dict:
    """Every row of every table in the app's SQLite file, in a stable order."""
    with contextlib.closing(sqlite3.connect(db_path())) as conn:
        names = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        out = {}
        for name in names:
            if name.startswith("sqlite_"):
                continue
            out[name] = sorted(conn.execute(f'SELECT * FROM "{name}"').fetchall(), key=repr)
        return out


# ------------------------------------------------------------------ an infeasible request gets alternatives


def test_infeasible_original_gets_suggestions(client):
    r = _alternatives(client, INFEASIBLE)
    assert r.status_code == 200
    body = r.json()
    assert body["original_status"] == "INFEASIBLE"
    assert body["original"]["start_date"] == "2027-04-01"
    assert body["original"]["country"] == "Japan" and body["original"]["departure"] == "BLR"
    assert len(body["suggestions"]) >= 1
    assert {"suggestions", "planner_searches"} <= set(body)


def test_each_suggestion_changes_exactly_one_field(client):
    body = _alternatives(client, INFEASIBLE).json()
    original = body["original"]
    for s in body["suggestions"]:
        assert set(s["request"]) == API_FIELDS
        changed = {k for k in API_FIELDS if s["request"][k] != original[k]}
        assert changed == {s["change"]["field"]}
        assert s["request"][s["change"]["field"]] == s["change"]["to"]
        assert original[s["change"]["field"]] == s["change"]["from"]
        assert s["within_budget"] == (s["min_total_inr"] <= original["budget"])


def test_suggested_prices_are_the_real_prices(client):
    body = _alternatives(client, INFEASIBLE).json()
    for s in body["suggestions"]:
        req = s["request"]
        day = req["start_date"]
        cal = client.post("/api/date-prices", json={**req, "range_start": day, "range_end": day}).json()
        cell = cal["dates"][0]
        assert cell["status"] == "FOUND" and cell["proven_minimum"] is True
        assert cell["min_total_inr"] == s["min_total_inr"]


def test_start_date_suggestions_are_near_eligible_and_nearest_first(client):
    body = _alternatives(client, INFEASIBLE).json()
    original = date.fromisoformat(body["original"]["start_date"])
    starts = [s for s in body["suggestions"] if s["kind"] == "START_DATE"]
    assert 0 <= len(starts) <= 2
    gaps = []
    for s in starts:
        day = date.fromisoformat(s["request"]["start_date"])
        assert 1 <= abs((day - original).days) <= 7
        assert FIRST_NIGHT <= day and day + timedelta(days=body["original"]["nights"]) <= LAST_DEPARTURE
        gaps.append((abs((day - original).days), day))
    assert gaps == sorted(gaps)


def test_departure_suggestions_never_repeat_the_original_airport(client):
    for body_in in (INFEASIBLE, FEASIBLE):
        body = _alternatives(client, body_in).json()
        deps = [s for s in body["suggestions"] if s["kind"] == "DEPARTURE"]
        assert len(deps) <= 2
        for s in deps:
            assert s["request"]["departure"] != body["original"]["departure"]
            assert s["change"]["field"] == "departure"


def test_nights_suggestion_stays_within_rules(client):
    for body_in in (INFEASIBLE, FEASIBLE):
        body = _alternatives(client, body_in).json()
        nights = [s for s in body["suggestions"] if s["kind"] == "NIGHTS"]
        assert len(nights) <= 1
        for s in nights:
            n = s["request"]["nights"]
            assert RULES["min_nights"] <= n <= RULES["max_nights"]
            start = date.fromisoformat(s["request"]["start_date"])
            assert start + timedelta(days=n) <= LAST_DEPARTURE
            assert abs(n - body["original"]["nights"]) <= 3 and n != body["original"]["nights"]


def test_suggestions_are_ordered_start_date_then_departure_then_nights(client):
    for body_in in (INFEASIBLE, FEASIBLE):
        kinds = [s["kind"] for s in _alternatives(client, body_in).json()["suggestions"]]
        order = {"START_DATE": 0, "DEPARTURE": 1, "NIGHTS": 2}
        assert [order[k] for k in kinds] == sorted(order[k] for k in kinds)


def test_feasible_request_is_reported_as_found(client):
    body = _alternatives(client, FEASIBLE).json()
    assert body["original_status"] == "FOUND"
    assert 0 <= body["planner_searches"] <= trip_alternatives.MAX_PLANNER_SEARCHES


# ------------------------------------------------------------------ bounds, validation, read-only


def test_planner_searches_never_exceed_the_cap(client, monkeypatch):
    for body_in in (INFEASIBLE, FEASIBLE):
        assert _alternatives(client, body_in).json()["planner_searches"] <= 30
    monkeypatch.setattr(trip_alternatives, "MAX_PLANNER_SEARCHES", 2)
    body = _alternatives(client, INFEASIBLE).json()
    assert body["planner_searches"] == 2


@pytest.mark.parametrize(
    "over, field",
    [
        ({"country": "Atlantis"}, "country"),
        ({"departure": "XXX"}, "departure"),
        ({"nights": 2}, "nights"),
        ({"adults": 0}, "adults"),
    ],
    ids=["unknown-country", "unsupported-departure", "nights-2", "adults-0"],
)
def test_invalid_request_returns_422_invalid_request(client, over, field):
    r = _alternatives(client, {**INFEASIBLE, **over})
    assert r.status_code == 422
    body = r.json()
    assert body["status"] == "INVALID_REQUEST" and body["error"] == "INVALID_REQUEST"
    assert body["field_errors"][field]


def test_alternatives_write_nothing_to_the_database(client):
    before = _snapshot()
    assert set(before) >= {"packages", "reservations"}
    assert _alternatives(client, INFEASIBLE).status_code == 200
    assert _alternatives(client, FEASIBLE).status_code == 200
    assert _snapshot() == before
