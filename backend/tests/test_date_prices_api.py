"""Phase 7A Price Landscape API: POST /api/date-prices, plus persistence isolation.

Run from backend/: /Users/apple/Desktop/HackCellence/.venv/bin/python -m pytest -q tests/test_date_prices_api.py
Each test gets a fresh temporary database and an empty process-wide price cache. The real catalog
and the real planner are used throughout; nothing is stubbed.
"""

import contextlib
import sqlite3
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.catalog.load import load_catalog
from app.db import db_path
from app.engine.build import MINIMUM_COST, build_package
from app.export.to_trip import to_trip_json
from app.main import app
from app.models import TripRequest
from app.services.date_price_cache import CACHE
from app.validate.validate_trip import validate_trip

BASE = {
    "departure": "BLR",
    "country": "Japan",
    "start_date": "2027-04-10",
    "nights": 6,
    "adults": 2,
    "child_ages": [6],
    "budget": 350_000,
}
RANGE = {"range_start": "2027-04-05", "range_end": "2027-04-09"}  # 5 days, all eligible for 6 nights
CAT = load_catalog()
FRONTEND_FIELDS = (
    "range_fully_evaluated", "lowest_proven_date", "lowest_proven_total_inr",
    "highest_proven_total_inr", "cheapest_date", "cheapest_total_inr",
)
FORBIDDEN_KEYS = {"package", "items", "booking"}


@pytest.fixture(autouse=True)
def _fresh_cache():
    CACHE.clear()
    yield
    CACHE.clear()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HOLIDAY_DB_PATH", str(tmp_path / "app.db"))
    with TestClient(app) as c:  # runs the lifespan: catalog check + create_tables()
        yield c


def _post(client, **over):
    return client.post("/api/date-prices", json={**BASE, **over})


def _eligible(start: str, end: str, nights: int = 6) -> list[str]:
    """Start dates in [start, end] whose trip fits the catalog data window, from the catalog itself."""
    rules = CAT.catalog.destinations["rules"]["data_window"]
    first, last = date.fromisoformat(rules["first_night"]), date.fromisoformat(rules["last_departure"])
    lo = max(date.fromisoformat(start), first)
    hi = min(date.fromisoformat(end), last - timedelta(days=nights))
    out, d = [], lo
    while d <= hi:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _walk_keys(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk_keys(v)


# ------------------------------------------------------------------ 32: a 5-day range


def test_five_day_range_returns_one_cell_per_eligible_date(client):
    r = _post(client, **RANGE)
    assert r.status_code == 200
    body = r.json()
    dates = [c["date"] for c in body["dates"]]
    assert dates == sorted(dates) and len(set(dates)) == len(dates)  # strictly chronological
    assert dates == _eligible(RANGE["range_start"], RANGE["range_end"])
    assert len(dates) == 5
    for cell in body["dates"]:
        assert {"date", "status", "min_total_inr", "proven_minimum"} <= set(cell)
        assert cell["status"] in ("FOUND", "INFEASIBLE", "SEARCH_INCOMPLETE")
        if cell["status"] == "FOUND":
            assert isinstance(cell["min_total_inr"], int) and not isinstance(cell["min_total_inr"], bool)
            assert cell["proven_minimum"] is True
        else:
            assert cell["min_total_inr"] is None
            assert cell["proven_minimum"] is False


# ------------------------------------------------------------------ 33: invalid requests


@pytest.mark.parametrize(
    "over, field",
    [
        ({"country": "Atlantis"}, "country"),
        ({"departure": "XXX"}, "departure"),
        ({"nights": 2}, "nights"),
        ({"adults": 0}, "adults"),
        ({"child_ages": [18]}, "child_ages"),
        ({"start_date": "not-a-date"}, "start_date"),
    ],
    ids=["unknown-country", "unsupported-departure", "nights-2", "adults-0", "child-18", "bad-start-date"],
)
def test_invalid_trip_fields_return_422_invalid_request(client, over, field):
    r = _post(client, **over)
    assert r.status_code == 422
    body = r.json()
    assert body["status"] == "INVALID_REQUEST" and body["error"] == "INVALID_REQUEST"
    assert field in body["field_errors"] and body["field_errors"][field]
    assert body["reasons"]


@pytest.mark.parametrize(
    "range_body",
    [
        {"range_start": "2027-04-09", "range_end": "2027-04-05"},   # reversed
        {"range_start": "2027-04-05"},                              # start without end
        {"range_start": "2027-04-01", "range_end": "2027-07-09"},   # 100 days
        {"range_start": "2027-13-01", "range_end": "2027-04-05"},   # malformed month
    ],
    ids=["reversed", "start-only", "100-days", "month-13"],
)
def test_invalid_range_returns_422_invalid_range(client, range_body):
    r = _post(client, **range_body)
    assert r.status_code == 422
    body = r.json()
    assert body["status"] == "INVALID_RANGE" and body["error"] == "INVALID_RANGE"
    assert body["field_errors"]["range"] and body["message"]


# ------------------------------------------------------------------ 34: range handling


def test_explicit_range_is_echoed_back(client):
    body = _post(client, **RANGE).json()
    assert body["range_start"] == RANGE["range_start"]
    assert body["range_end"] == RANGE["range_end"]


def test_omitted_range_is_the_calendar_month_of_the_start_date(client):
    body = _post(client).json()  # start_date 2027-04-10 -> April 2027
    assert body["range_start"] == "2027-04-01" and body["range_end"] == "2027-04-30"
    window = body["data_window"]
    assert window["last_departure"] == "2027-04-20"
    dates = [c["date"] for c in body["dates"]]
    # only eligible starts: the whole trip must end by the window's last departure (20 Apr - 6 nights)
    assert dates[0] == "2027-04-01"
    assert dates[-1] == "2027-04-14"
    assert dates == _eligible("2027-04-01", "2027-04-30")


def test_range_entirely_outside_the_data_window_is_empty(client):
    r = _post(client, range_start="2027-06-01", range_end="2027-06-05")
    assert r.status_code == 200
    assert r.json()["dates"] == []


# ------------------------------------------------------------------ 35-37: persistence isolation


def _snapshot() -> dict:
    """Every row of every table in the app's SQLite file, in a stable order."""
    with contextlib.closing(sqlite3.connect(db_path())) as conn:
        names = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        out = {}
        for name in names:
            if name.startswith("sqlite_"):
                continue
            rows = conn.execute(f'SELECT * FROM "{name}"').fetchall()
            out[name] = sorted(rows, key=repr)
        return out


def test_date_prices_writes_nothing_to_the_database(client):
    created = client.post("/api/packages", json=BASE)
    assert created.status_code == 201
    package_id = created.json()["package"]["id"]

    before = _snapshot()
    assert set(before) >= {"packages", "reservations"}
    assert len(before["packages"]) == 1
    assert before["reservations"] == []

    assert _post(client, **RANGE).status_code == 200
    assert _post(client, range_start="2027-04-11", range_end="2027-04-13").status_code == 200

    after = _snapshot()
    assert after == before                                # identical rows in every table
    assert len(after["packages"]) == 1                    # no package was created
    assert client.get(f"/api/packages/{package_id}").status_code == 200  # the saved one still reads


# ------------------------------------------------------------------ 38: every destination works


def _departure_for(country_code: str) -> str | None:
    """A departure airport that has at least one flight into this country (from the catalog)."""
    cat = CAT.catalog
    dep_codes = [d["airport"] for d in cat.destinations["departure_cities"]]
    country_airports = {a["code"] for a in cat.airports if a["country"] == country_code}
    for dep in dep_codes:
        if any(f["from"] == dep and f["to"] in country_airports for f in cat.flights):
            return dep
    return None


def test_every_destination_is_priced_without_special_casing(client):
    meta = client.get("/api/meta").json()
    others = [c for c in meta["countries"] if c["code"] != "JP"]
    assert others, "the catalog should list destinations other than Japan"
    found_by_country = {}
    for country in others:
        dep = _departure_for(country["code"])
        if dep is None:
            found_by_country[country["code"]] = None
            continue
        r = _post(client, departure=dep, country=country["name"],
                  range_start="2027-04-05", range_end="2027-04-07", nights=4)
        assert r.status_code == 200, (country["code"], r.text[:300])
        found_by_country[country["code"]] = sum(1 for c in r.json()["dates"] if c["status"] == "FOUND")
    assert any(
        count for code, count in found_by_country.items()
        if code not in ("JP", "AE") and count
    ), f"no destination other than JP/AE priced a date: {found_by_country}"


# ------------------------------------------------------------------ oracle and contract


def _found(cells):
    return [c for c in cells if c["status"] == "FOUND"]


def test_found_prices_match_the_minimum_cost_planner_and_validate(client):
    body = _post(client, range_start="2027-04-05", range_end="2027-04-07").json()
    found = _found(body["dates"])
    assert found, "this range should have at least one priced date"
    for cell in found:
        request = TripRequest(
            departure_airport=BASE["departure"], destination_country=BASE["country"],
            start_date=cell["date"], nights=BASE["nights"], adults=BASE["adults"],
            children_ages=BASE["child_ages"], budget=BASE["budget"],
        )
        result = build_package(request, CAT, objective=MINIMUM_COST)
        assert result.search_complete is True, cell
        assert result.cheapest_total == cell["min_total_inr"], cell
        assert validate_trip(to_trip_json(result.package, CAT), CAT, "INITIAL") == [], cell


def test_budget_never_changes_prices_only_within_budget(client):
    first = _post(client, **RANGE).json()
    CACHE.clear()  # a cold recomputation, so the budget really is a fresh input
    other_budget = 1_000
    second = _post(client, budget=other_budget, **RANGE).json()

    assert [(c["date"], c["status"], c["min_total_inr"], c["proven_minimum"]) for c in first["dates"]] == \
        [(c["date"], c["status"], c["min_total_inr"], c["proven_minimum"]) for c in second["dates"]]
    for cell in second["dates"]:
        if cell["status"] == "FOUND":
            assert cell["within_budget"] is (cell["min_total_inr"] <= other_budget)
        else:
            assert cell["within_budget"] is None
    for cell in first["dates"]:
        if cell["status"] == "FOUND":
            assert cell["within_budget"] is (cell["min_total_inr"] <= BASE["budget"])


def test_response_carries_the_fields_the_frontend_reads(client):
    body = _post(client, **RANGE).json()
    for key in FRONTEND_FIELDS:
        assert key in body, key
    assert {"reference_date", "max_proven_savings_inr"} <= set(body["comparison"])
    assert "cache_hits" in body["diagnostics"]
    assert not FORBIDDEN_KEYS & set(_walk_keys(body)), "no package or booking objects may appear"
