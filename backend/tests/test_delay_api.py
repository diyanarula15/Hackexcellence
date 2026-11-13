"""Delay Rescue API (Phase 5B): delay-scenarios, ARRIVAL_DELAY preview-change and apply-change.

Real catalog, real planner: each test creates the Menon-family package (BLR -> Japan, 2027-04-10, 6 nights,
2 adults, child 6, budget 350000) through POST /api/packages in a fresh temporary database. The expected
outcomes are the engine's own answers, read from the sweep or the stored package, never guessed.
Run from backend/:
    ../.venv/bin/python -m pytest -q tests/test_delay_api.py
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.db import db_path
from app.main import app
from app.repositories import packages as repo

MENON = {
    "departure": "BLR",
    "country": "Japan",
    "start_date": "2027-04-10",
    "nights": 6,
    "adults": 2,
    "child_ages": [6],
    "budget": 350_000,
}
LEVELS = [60, 120, 180, 240]
NOT_FOUND_ID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HOLIDAY_DB_PATH", str(tmp_path / "app.db"))
    with TestClient(app) as c:
        yield c


def _create(client) -> str:
    r = client.post("/api/packages", json=MENON)
    assert r.status_code == 201, r.text
    return r.json()["package"]["id"]


def _sweep(client, pid, base_version):
    return client.post(f"/api/packages/{pid}/delay-scenarios", json={"base_version": base_version})


def _preview(client, pid, minutes, base_version, **extra):
    body = {"kind": "ARRIVAL_DELAY", "delay_minutes": minutes, "base_version": base_version, **extra}
    return client.post(f"/api/packages/{pid}/preview-change", json=body)


def _apply(client, pid, minutes, base_version, token=None):
    body = {"kind": "ARRIVAL_DELAY", "delay_minutes": minutes, "base_version": base_version}
    if token is not None:
        body["preview_token"] = token
    return client.post(f"/api/packages/{pid}/apply-change", json=body)


def _version(pid) -> int:
    return repo.get_package(pid).version


def _snapshot():
    """Every row of every table, as plain tuples (catches any write, however small)."""
    conn = sqlite3.connect(db_path())
    try:
        names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {n: conn.execute(f"SELECT * FROM {n}").fetchall() for n in names}
    finally:
        conn.close()


def _book(pid):
    conn = sqlite3.connect(db_path())
    try:
        conn.execute("UPDATE packages SET status='BOOKED' WHERE id=?", (pid,))
        conn.commit()
    finally:
        conn.close()


def _repair_240(client, pid):
    """Apply the +240 repair (version 1 -> 2); after it the +60 .. +240 levels are absorbed."""
    p = _preview(client, pid, 240, 1).json()
    assert p["outcome"] == "REPAIRED" and p["preview_token"]
    r = _apply(client, pid, 240, 1, p["preview_token"])
    assert r.status_code == 200, r.text
    assert _version(pid) == 2
    return r.json()


# ------------------------------------------------------------------ 19 sweep agrees with previews


def test_19_sweep_levels_match_individual_previews(client):
    pid = _create(client)
    sweep = _sweep(client, pid, 1)
    assert sweep.status_code == 200, sweep.text
    body = sweep.json()
    assert [s["delay_minutes"] for s in body["scenarios"]] == LEVELS
    for scenario in body["scenarios"]:
        m = scenario["delay_minutes"]
        one = _preview(client, pid, m, 1)
        assert one.status_code == 200, one.text
        one = one.json()
        assert one["outcome"] == scenario["outcome"]
        assert one["proposed_pickup"] == scenario["proposed_pickup"]
        assert one["price_difference_inr"] == scenario["price_difference_inr"]
        assert one["preview_token"] == scenario["preview_token"]
        assert one["simulated_landing"] == scenario["simulated_landing"]


# ------------------------------------------------------------------ 20 unknown package


def test_20_unknown_package_is_404_for_sweep_and_preview(client):
    for r in (
        _sweep(client, NOT_FOUND_ID, 1),
        _preview(client, NOT_FOUND_ID, 60, 1),
    ):
        assert r.status_code == 404
        assert r.json()["error"] == "PACKAGE_NOT_FOUND"


# ------------------------------------------------------------------ 21 request validation


def test_21_bad_delay_values_are_422_with_field_errors(client):
    pid = _create(client)
    for bad in (90, "60"):
        r = _preview(client, pid, bad, 1)
        assert r.status_code == 422, r.text
        assert r.json()["field_errors"]


def test_21_missing_base_version_and_extra_fields_are_422(client):
    pid = _create(client)
    missing = client.post(f"/api/packages/{pid}/delay-scenarios", json={})
    assert missing.status_code == 422 and missing.json()["field_errors"]
    extra = client.post(f"/api/packages/{pid}/delay-scenarios", json={"base_version": 1, "delay_minutes": 60})
    assert extra.status_code == 422 and extra.json()["field_errors"]

    no_base = client.post(f"/api/packages/{pid}/preview-change",
                          json={"kind": "ARRIVAL_DELAY", "delay_minutes": 60})
    assert no_base.status_code == 422 and no_base.json()["field_errors"]
    extra_field = _preview(client, pid, 60, 1, flight_id="F-IN")
    assert extra_field.status_code == 422 and extra_field.json()["field_errors"]


# ------------------------------------------------------------------ 22 stale version


def test_22_stale_base_version_is_409_for_sweep_preview_and_apply(client):
    pid = _create(client)
    _repair_240(client, pid)                       # the stored version is now 2
    for r in (_sweep(client, pid, 1), _preview(client, pid, 60, 1), _apply(client, pid, 60, 1)):
        assert r.status_code == 409, r.text
        assert r.json()["error"] == "PACKAGE_VERSION_CONFLICT"
        assert r.json()["current_version"] == 2
    assert _version(pid) == 2


# ------------------------------------------------------------------ 23 / 24 apply a repair


def test_23_apply_repair_with_its_token_increments_version_once(client):
    pid = _create(client)
    p = _preview(client, pid, 60, 1).json()
    assert p["outcome"] == "REPAIRED" and p["can_apply"] is True
    r = _apply(client, pid, 60, 1, p["preview_token"])
    assert r.status_code == 200, r.text
    assert r.json()["applied"] is True
    assert _version(pid) == 2


def test_24_saved_package_shows_the_new_pickup_and_the_catalog_flight(client):
    pid = _create(client)
    before = repo.get_package(pid).package
    p = _preview(client, pid, 60, 1).json()
    assert _apply(client, pid, 60, 1, p["preview_token"]).status_code == 200
    stored = repo.get_package(pid)
    assert stored.version == 2
    assert stored.package.arrival_transfer.pickup.strftime("%Y-%m-%dT%H:%M") == p["proposed_pickup"]
    assert stored.package.arrival_flight == before.arrival_flight
    assert stored.package.return_flight == before.return_flight
    got = client.get(f"/api/packages/{pid}")
    assert got.status_code == 200
    view = got.json()["package"]
    assert view["version"] == 2
    [pickup] = [i for i in view["items"] if i["item_id"] == "leg:arrival"]
    assert pickup["start"] == p["proposed_pickup"]
    [flight] = [i for i in view["items"] if i["item_id"] == "flight:arrival"]
    assert flight["catalog_id"] == before.arrival_flight.flight_id
    assert flight["start"] == before.arrival_flight.departure.strftime("%Y-%m-%dT%H:%M")
    assert flight["end"] == before.arrival_flight.arrival.strftime("%Y-%m-%dT%H:%M")


def test_apply_with_a_wrong_token_is_409_and_nothing_changes(client):
    pid = _create(client)
    before = _snapshot()
    r = _apply(client, pid, 60, 1, "0" * 64)
    assert r.status_code == 409
    assert r.json()["error"] == "PREVIEW_OUTDATED"
    assert _version(pid) == 1
    assert _snapshot() == before


def test_applying_an_absorbed_scenario_is_422_change_invalid(client):
    pid = _create(client)
    _repair_240(client, pid)                       # pickup now 240 minutes after landing: +60 is absorbed
    assert _preview(client, pid, 60, 2).json()["outcome"] == "ABSORBED"
    r = _apply(client, pid, 60, 2)
    assert r.status_code == 422
    assert r.json()["error"] == "CHANGE_INVALID"
    assert _version(pid) == 2


# ------------------------------------------------------------------ 25 booked packages


def test_25_a_booked_package_previews_read_only_and_cannot_apply(client):
    pid = _create(client)
    _book(pid)
    before = _snapshot()
    sweep = _sweep(client, pid, 1)
    assert sweep.status_code == 200 and sweep.json()["package_status"] == "BOOKED"
    p = _preview(client, pid, 60, 1)
    assert p.status_code == 200
    body = p.json()
    assert body["can_apply"] is False and body["apply_blocked_reason"]
    assert body["preview_token"] is None
    token = "x" * 64
    r = _apply(client, pid, 60, 1, token)
    assert r.status_code == 409 and r.json()["error"] == "PACKAGE_ALREADY_BOOKED"
    assert _snapshot() == before


# ------------------------------------------------------------------ 26 no leaking between versions


def test_26_results_for_a_new_version_differ_and_the_old_version_is_rejected(client):
    pid = _create(client)
    old = _sweep(client, pid, 1).json()
    assert old["exact_absorbed_tolerance_minutes"] is None
    _repair_240(client, pid)
    new = _sweep(client, pid, 2).json()
    assert [s["outcome"] for s in old["scenarios"]] == ["REPAIRED"] * 4
    assert [s["outcome"] for s in new["scenarios"]] == ["ABSORBED"] * 4
    assert new["tested_absorbed_continuous_minutes"] == 240
    assert new["exact_absorbed_tolerance_minutes"] == 240
    assert new["base_version"] == 2
    assert _sweep(client, pid, 1).status_code == 409


# ------------------------------------------------------------------ read-only


def test_sweep_and_previews_never_write(client):
    pid = _create(client)
    before = _snapshot()
    assert _sweep(client, pid, 1).status_code == 200
    for m in LEVELS:
        assert _preview(client, pid, m, 1).status_code == 200
    assert _snapshot() == before
