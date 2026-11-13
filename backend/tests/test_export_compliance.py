"""Export compliance: every package export is valid in the shared trip format (DATA_DICTIONARY section 4).

Covers a draft (PLANNED) and a booked (BOOKED) export, the UAE and the expanded-catalog countries, and an
export after a saved change (EDITED). Each export is checked by scripts/check_trip_export.py (stdlib shape and
type checks, plus the backend rule validator, which must actually run).

Run from backend/: ../.venv/bin/python -m pytest -q tests/test_export_compliance.py
Each test gets its own temporary database; packages are created through POST /api/packages with the real catalog.
"""

import copy
import importlib.util
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "check_trip_export", ROOT / "scripts" / "check_trip_export.py"
)
checker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checker)

INITIAL, EDITED = "INITIAL", "EDITED"
FOUND = "FOUND"
MENON = {
    "departure": "BLR",
    "country": "Japan",
    "start_date": "2027-04-10",
    "nights": 6,
    "adults": 2,
    "child_ages": [6],
    "budget": 350_000,
}
BIG_BUDGET = 10_000_000  # scan requests: a budget no package can exceed, so FOUND means "a valid package exists"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HOLIDAY_DB_PATH", str(tmp_path / "app.db"))
    with TestClient(app) as c:
        yield c


def _create(client, body) -> str:
    r = client.post("/api/packages", json=body)
    assert r.status_code == 201, r.text
    assert r.json()["status"] == FOUND, r.json()["reasons"]
    return r.json()["package"]["id"]


def _find_found(client, candidates) -> str:
    """Package id of the first candidate request that planner reports FOUND (a small scan)."""
    tried = []
    for body in candidates:
        r = client.post("/api/packages", json=body)
        tried.append((body["departure"], body["country"], body["start_date"], body["nights"], r.status_code,
                      r.json().get("status")))
        if r.status_code == 201 and r.json()["status"] == FOUND:
            return r.json()["package"]["id"]
    pytest.fail(f"no FOUND package in the scan: {tried}")


def _export(client, package_id):
    r = client.get(f"/api/packages/{package_id}/export")
    assert r.status_code == 200, r.text
    return r


def _assert_compliant(trip: dict, mode: str):
    checks, validator_ran = checker.run_checks(trip, mode)
    assert validator_ran, "the backend rule validator did not run, so the travel rules were not checked"
    failures = checker.check_trip(trip, mode)
    assert failures == [], failures
    assert all(c.ok for c in checks)


def _json(response):
    return json.loads(response.content)


# ------------------------------------------------------------------ (a) Menon request, draft export

def test_menon_draft_export_is_compliant_and_downloadable(client):
    pid = _create(client, MENON)
    r = _export(client, pid)
    trip = _json(r)
    assert r.headers["X-Validation-Mode"] == INITIAL
    assert r.headers["X-Trip-Valid"] == "true"
    assert r.headers["content-disposition"] == 'attachment; filename="holiday-package.json"'
    assert r.headers["content-type"].startswith("application/json")
    assert trip["country"] == "Japan"
    assert all(it["status"] == "PLANNED" and it["booking"] is None for it in trip["items"])
    assert any(it["type"] == "hotel" and isinstance(it["room_id"], str) for it in trip["items"])
    _assert_compliant(trip, INITIAL)


# ------------------------------------------------------------------ (b) UAE request

UAE_CANDIDATES = [
    {"departure": dep, "country": "United Arab Emirates", "start_date": f"2027-04-{d:02d}", "nights": 4,
     "adults": 2, "child_ages": [], "budget": BIG_BUDGET}
    for dep in ("BLR", "DEL") for d in (2, 5, 8, 11)
]


def test_uae_draft_export_is_compliant(client):
    pid = _find_found(client, UAE_CANDIDATES)
    trip = _json(_export(client, pid))
    assert trip["country"] == "United Arab Emirates"
    _assert_compliant(trip, INITIAL)


# ------------------------------------------------------------------ (c) expanded-catalog countries

EXPANDED = ["Thailand", "Singapore", "Malaysia", "Indonesia", "Vietnam"]
EXPANDED_CANDIDATES = [
    {"departure": "BLR", "country": country, "start_date": f"2027-04-{d:02d}", "nights": 5,
     "adults": 2, "child_ages": [], "budget": BIG_BUDGET}
    for country in EXPANDED for d in (2, 5, 8)
]


def test_expanded_catalog_country_export_is_compliant(client):
    pid = _find_found(client, EXPANDED_CANDIDATES)
    trip = _json(_export(client, pid))
    assert trip["country"] in EXPANDED
    _assert_compliant(trip, INITIAL)


# ------------------------------------------------------------------ (d) export after a saved change

def test_export_after_saved_attraction_removal_validates_in_edited_mode(client):
    pid = _create(client, MENON)
    trip = _json(_export(client, pid))
    attractions = [it for it in trip["items"] if it["type"] == "attraction"]
    assert attractions, "the Menon package has no attraction to remove"

    body = None
    for it in attractions:
        candidate = {"kind": "REMOVE_ATTRACTION", "item_id": f"visit:{it['catalog_id']}", "base_version": 1}
        preview = client.post(f"/api/packages/{pid}/preview-change", json=candidate)
        assert preview.status_code == 200, preview.text
        if preview.json()["valid"]:
            body = candidate
            token = preview.json()["preview_token"]
            break
    assert body is not None, "no attraction removal was valid in this package"

    applied = client.post(f"/api/packages/{pid}/apply-change", json={**body, "preview_token": token})
    assert applied.status_code == 200, applied.text
    assert applied.json()["applied"] is True
    assert applied.json()["package"]["version"] == 2

    r = _export(client, pid)
    assert r.headers["X-Validation-Mode"] == EDITED
    assert r.headers["X-Trip-Valid"] == "true"
    edited = _json(r)
    assert len([it for it in edited["items"] if it["type"] == "attraction"]) == len(attractions) - 1
    _assert_compliant(edited, EDITED)


# ------------------------------------------------------------------ (e) booked export

def test_booked_export_is_compliant_and_draft_differs_only_in_status_and_booking(client):
    pid = _create(client, MENON)
    draft_response = _export(client, pid)
    draft = _json(draft_response)
    assert draft_response.headers["content-disposition"] == 'attachment; filename="holiday-package.json"'

    confirmed = client.post(f"/api/packages/{pid}/confirm", json={"base_version": 1})
    assert confirmed.status_code == 200, confirmed.text
    reference = confirmed.json()["reference"]

    booked_response = _export(client, pid)
    booked = _json(booked_response)
    assert booked_response.headers["content-disposition"] == (
        f'attachment; filename="holiday-reservation-{reference}.json"'
    )
    assert booked_response.headers["content-type"].startswith("application/json")
    assert booked == confirmed.json()["trip"]
    assert all(it["status"] == "BOOKED" and it["booking"] == {"reference": reference}
               for it in booked["items"])
    _assert_compliant(booked, INITIAL)

    # The draft and booked exports of the same package differ only in status and booking.
    def without_status(trip):
        t = copy.deepcopy(trip)
        for it in t["items"]:
            it.pop("status")
            it.pop("booking")
        return t

    assert without_status(draft) == without_status(booked)
    assert [it["status"] for it in draft["items"]] == ["PLANNED"] * len(draft["items"])


# ------------------------------------------------------------------ the checker itself must not be vacuous

def test_checker_rejects_a_broken_trip(client):
    pid = _create(client, MENON)
    good = _json(_export(client, pid))
    assert checker.check_trip(good, INITIAL) == []

    cases = {
        "missing country": lambda t: t.pop("country"),
        "total off by one rupee": lambda t: t.__setitem__("total_inr", t["total_inr"] + 1),
        "float price": lambda t: t["items"][0].__setitem__("price_inr", 1.5),
        "PLANNED with booking": lambda t: t["items"][0].__setitem__("booking", {"reference": "1234567890"}),
        "hotel without room_id": lambda t: next(
            i for i in t["items"] if i["type"] == "hotel").__setitem__("room_id", None),
        "extra item key": lambda t: t["items"][0].__setitem__("note", "x"),
        "duplicate item_id": lambda t: t["items"][1].__setitem__("item_id", t["items"][0]["item_id"]),
        "country not in catalog": lambda t: t.__setitem__("country", "Atlantis"),
        "children mismatch": lambda t: t["traveler"].__setitem__("children", 2),
    }
    for label, break_it in cases.items():
        bad = copy.deepcopy(good)
        break_it(bad)
        assert checker.check_trip(bad, INITIAL), f"checker missed: {label}"
