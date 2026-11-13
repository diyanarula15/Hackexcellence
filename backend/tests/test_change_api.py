"""Phase 5 API: GET /options, POST /preview-change, POST /apply-change, and their transactions.

Run from backend/: ../.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_change_api.py
Each test gets a fresh temporary database. Packages are made through POST /api/packages with the real
catalog; concrete changes are found by asking the engine (propose_change) which ones are valid or not,
never hardcoded.
"""

import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.catalog.load import load_catalog
from app.db import db_path
from app.engine.change import propose_change
from app.export.to_trip import to_trip_json
from app.main import app
from app.models import CHANGE_COMMAND
from app.repositories import packages as repo
from app.rules.common import EDITED
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
VERSION_MESSAGE = "This holiday was updated after your preview. Reload the latest package before applying another change."


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HOLIDAY_DB_PATH", str(tmp_path / "app.db"))
    with TestClient(app) as c:
        yield c


def _create(client, **over) -> str:
    r = client.post("/api/packages", json={**MENON, **over})
    assert r.status_code == 201, r.text
    return r.json()["package"]["id"]


def _row(package_id):
    conn = sqlite3.connect(db_path())
    try:
        return conn.execute(
            "SELECT * FROM packages WHERE id = ?", (package_id,)
        ).fetchone()
    finally:
        conn.close()


def _candidates(package):
    """Every hotel/room and every flight the catalog could offer, as command bodies (no version)."""
    out = []
    for stay, hotel in zip(package.plan.stays, package.hotels):
        for h in CAT.indexes.hotels_by_city.get(stay.city, []):
            for room in CAT.indexes.rooms_by_hotel.get(h["hotel_id"], []):
                out.append(
                    {
                        "kind": "CHANGE_HOTEL",
                        "stay_id": hotel.stay_id,
                        "hotel_id": h["hotel_id"],
                        "room_id": room["room_id"],
                    }
                )
    for flight_id in CAT.indexes.flights_by_id:
        out.append({"kind": "CHANGE_ARRIVAL_FLIGHT", "flight_id": flight_id})
        out.append({"kind": "CHANGE_RETURN_FLIGHT", "flight_id": flight_id})
    return out


def _pick(package, version, *, valid, nonzero=False, repairs=None):
    """The first candidate body (with base_version) the engine accepts / refuses."""
    for body in _candidates(package):
        body = {"base_version": version, **body}
        p = propose_change(package, CHANGE_COMMAND.validate_python(body), CAT)
        if p.valid != valid:
            continue
        if valid and nonzero and not p.price_difference:
            continue
        if valid and repairs is not None and bool(p.automatic_repairs) != repairs:
            continue
        if not valid and p.violations[0].rule == "NO_CHANGE":
            continue
        return body
    pytest.skip("no candidate of that kind in the catalog for this package")


def _stored(package_id):
    return repo.get_package(package_id)


# ------------------------------------------------------------------ 30 preview never writes


def test_30_preview_leaves_the_row_byte_identical_valid_or_not(client):
    pid = _create(client)
    s = _stored(pid)
    good = _pick(s.package, 1, valid=True, nonzero=True)
    bad = _pick(s.package, 1, valid=False)
    before = _row(pid)
    r_good = client.post(f"/api/packages/{pid}/preview-change", json=good)
    r_bad = client.post(f"/api/packages/{pid}/preview-change", json=bad)
    assert r_good.status_code == r_bad.status_code == 200
    assert r_good.json()["valid"] is True and r_bad.json()["valid"] is False
    assert _row(pid) == before


def test_valid_preview_body_has_the_full_contract(client):
    pid = _create(client)
    s = _stored(pid)
    body = _pick(s.package, 1, valid=True, nonzero=True)
    r = client.post(f"/api/packages/{pid}/preview-change", json=body).json()
    assert (
        r["package_id"] == pid and r["base_version"] == 1 and r["kind"] == body["kind"]
    )
    assert r["old_total_inr"] == s.total_inr
    assert r["new_total_inr"] - r["old_total_inr"] == r["price_difference_inr"] != 0
    assert r["budget_remaining_inr"] == max(s.package.budget - r["new_total_inr"], 0)
    assert r["over_budget_inr"] == 0 and r["violations"] == []
    assert r["changed_items"] and r["message"].startswith("This change ")
    assert r["proposed_package"]["version"] == 1 and r["proposed_package"]["id"] == pid
    assert r["proposed_package"]["budget"]["total_inr"] == r["new_total_inr"]
    assert len(r["preview_token"]) == 64
    again = client.post(f"/api/packages/{pid}/preview-change", json=body).json()
    assert again == r  # deterministic


def test_invalid_preview_explains_why(client):
    pid = _create(client)
    bad = _pick(_stored(pid).package, 1, valid=False)
    r = client.post(f"/api/packages/{pid}/preview-change", json=bad).json()
    assert (
        r["valid"] is False
        and r["proposed_package"] is None
        and r["preview_token"] is None
    )
    assert r["violations"] and all(
        {"rule", "item_id", "message"} <= set(v) for v in r["violations"]
    )
    assert (
        r["message"]
        and r["new_total_inr"] is None
        and r["price_difference_inr"] is None
    )


# ------------------------------------------------------------------ 31 / 34 / 36 / 38 apply


def test_31_apply_increments_the_version_once_and_marks_edited(client):
    pid = _create(client)
    body = _pick(_stored(pid).package, 1, valid=True, nonzero=True)
    r = client.post(f"/api/packages/{pid}/apply-change", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["applied"] is True
    assert (out["package"]["version"], out["package"]["validation_mode"]) == (2, EDITED)
    ch = out["change"]
    assert (ch["previous_version"], ch["version"], ch["kind"]) == (1, 2, body["kind"])
    row = _row(pid)
    assert row[4] == 2 and row[7] == EDITED  # version, validation_mode columns (6 is catalog_fingerprint)


def test_34_applied_change_persists_for_get_export_and_a_reopened_database(client):
    pid = _create(client)
    body = _pick(_stored(pid).package, 1, valid=True, nonzero=True)
    applied = client.post(f"/api/packages/{pid}/apply-change", json=body).json()
    got = client.get(f"/api/packages/{pid}").json()
    assert got["package"] == applied["package"] and got["package"]["version"] == 2
    exported = client.get(f"/api/packages/{pid}/export")
    assert exported.status_code == 200 and exported.headers["X-Trip-Valid"] == "true"
    assert exported.headers["X-Validation-Mode"] == EDITED
    conn = sqlite3.connect(db_path())  # a brand-new connection
    try:
        version, mode, total = conn.execute(
            "SELECT version, validation_mode, total_inr FROM packages WHERE id=?",
            (pid,),
        ).fetchone()
    finally:
        conn.close()
    assert (version, mode, total) == (2, EDITED, applied["change"]["new_total_inr"])


def test_36_total_reflects_every_dependent_change(client):
    pid = _create(client)
    s = _stored(pid)
    body = _pick(s.package, 1, valid=True, repairs=True)
    out = client.post(f"/api/packages/{pid}/apply-change", json=body).json()
    ch = out["change"]
    assert ch["automatic_repairs"], "this change should trigger a dependent repair"
    saved = _stored(pid)
    assert saved.total_inr == saved.package.total == ch["new_total_inr"]
    assert ch["new_total_inr"] - s.total_inr == sum(
        c["price_difference_inr"] for c in ch["changed_items"]
    )
    assert out["package"]["budget"]["total_inr"] == saved.total_inr


def test_38_the_saved_package_passes_edited_validation(client):
    pid = _create(client)
    body = _pick(_stored(pid).package, 1, valid=True, nonzero=True)
    assert (
        client.post(f"/api/packages/{pid}/apply-change", json=body).status_code == 200
    )
    saved = _stored(pid)
    assert validate_trip(to_trip_json(saved.package, CAT), CAT, EDITED) == []


def test_apply_with_the_matching_preview_token_succeeds(client):
    pid = _create(client)
    body = _pick(_stored(pid).package, 1, valid=True, nonzero=True)
    token = client.post(f"/api/packages/{pid}/preview-change", json=body).json()[
        "preview_token"
    ]
    r = client.post(
        f"/api/packages/{pid}/apply-change", json={**body, "preview_token": token}
    )
    assert r.status_code == 200 and r.json()["package"]["version"] == 2


def test_a_wrong_preview_token_is_outdated_and_changes_nothing(client):
    pid = _create(client)
    body = _pick(_stored(pid).package, 1, valid=True, nonzero=True)
    before = _row(pid)
    r = client.post(
        f"/api/packages/{pid}/apply-change", json={**body, "preview_token": "0" * 64}
    )
    assert r.status_code == 409 and r.json()["error"] == "PREVIEW_OUTDATED"
    assert _row(pid) == before


def test_a_non_text_preview_token_is_a_422(client):
    pid = _create(client)
    body = _pick(_stored(pid).package, 1, valid=True, nonzero=True)
    r = client.post(
        f"/api/packages/{pid}/apply-change", json={**body, "preview_token": 5}
    )
    assert r.status_code == 422 and "preview_token" in r.json()["field_errors"]


# ------------------------------------------------------------------ 32 / 33 / 39 failures


def test_32_failed_apply_leaves_json_and_version_unchanged(client):
    pid = _create(client)
    bad = _pick(_stored(pid).package, 1, valid=False)
    before = _row(pid)
    r = client.post(f"/api/packages/{pid}/apply-change", json=bad)
    assert r.status_code == 422
    out = r.json()
    assert out["error"] == "CHANGE_INVALID" and out["message"] and out["violations"]
    assert _row(pid) == before


def test_33_outdated_base_version_is_a_409_with_the_spec_message(client):
    pid = _create(client)
    body = _pick(_stored(pid).package, 1, valid=True, nonzero=True)
    assert (
        client.post(f"/api/packages/{pid}/apply-change", json=body).status_code == 200
    )
    before = _row(pid)
    r = client.post(f"/api/packages/{pid}/apply-change", json=body)
    assert r.status_code == 409
    assert r.json() == {
        "error": "PACKAGE_VERSION_CONFLICT",
        "message": VERSION_MESSAGE,
        "current_version": 2,
    }
    assert _row(pid) == before
    p = client.post(f"/api/packages/{pid}/preview-change", json=body)
    assert p.status_code == 409 and p.json()["current_version"] == 2


def test_39_a_duplicate_apply_cannot_apply_twice(client):
    pid = _create(client)
    body = _pick(_stored(pid).package, 1, valid=True, nonzero=True)
    first = client.post(f"/api/packages/{pid}/apply-change", json=body)
    second = client.post(f"/api/packages/{pid}/apply-change", json=body)
    assert (first.status_code, second.status_code) == (200, 409)
    assert _stored(pid).version == 2
    assert _stored(pid).total_inr == first.json()["change"]["new_total_inr"]


def test_two_simultaneous_applies_on_one_version_yield_one_success_and_one_409(client):
    pid = _create(client)
    s = _stored(pid)
    first = _pick(s.package, 1, valid=True, nonzero=True)
    others = [
        b
        for b in _candidates(s.package)
        if b != {k: v for k, v in first.items() if k != "base_version"}
        and propose_change(
            s.package, CHANGE_COMMAND.validate_python({"base_version": 1, **b}), CAT
        ).valid
    ]
    second = {"base_version": 1, **others[-1]}
    barrier = threading.Barrier(2)

    def go(body):
        barrier.wait()
        return client.post(f"/api/packages/{pid}/apply-change", json=body).status_code

    with ThreadPoolExecutor(2) as pool:
        codes = sorted(pool.map(go, [first, second]))
    assert codes == [200, 409]
    assert _stored(pid).version == 2


def test_modify_package_serialises_writers_with_begin_immediate(client):
    pid = _create(client)
    s = _stored(pid)
    results = []

    def slow(stored):
        time.sleep(0.4)  # holds the write lock while the other caller waits
        return stored.package

    def go():
        try:
            results.append(repo.modify_package(pid, 1, slow).version)
        except repo.VersionConflict as e:
            results.append(("conflict", e.current))

    threads = [threading.Thread(target=go) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(map(str, results)) == sorted(map(str, [2, ("conflict", 2)]))
    assert _stored(pid).version == 2 and s.version == 1


def test_modify_package_rolls_back_when_the_change_raises(client):
    pid = _create(client)
    before = _row(pid)

    def boom(stored):
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError):
        repo.modify_package(pid, 1, boom)
    assert _row(pid) == before
    with pytest.raises(repo.PackageNotFound):
        repo.modify_package("missing", 1, boom)


# ------------------------------------------------------------------ 35 BOOKED, 404, 422


def _book(pid):
    conn = sqlite3.connect(db_path())
    try:
        conn.execute("UPDATE packages SET status='BOOKED' WHERE id=?", (pid,))
        conn.commit()
    finally:
        conn.close()


def test_35_a_booked_package_cannot_be_changed(client):
    pid = _create(client)
    body = _pick(_stored(pid).package, 1, valid=True, nonzero=True)
    _book(pid)
    before = _row(pid)
    expected = {
        "error": "PACKAGE_ALREADY_BOOKED",
        "message": "This holiday is already booked, so it can no longer be changed.",
    }
    for r in (
        client.get(f"/api/packages/{pid}/options", params={"kind": "arrival_flight"}),
        client.post(f"/api/packages/{pid}/preview-change", json=body),
        client.post(f"/api/packages/{pid}/apply-change", json=body),
    ):
        assert r.status_code == 409 and r.json() == expected
    assert _row(pid) == before


def test_modify_package_refuses_a_booked_row(client):
    pid = _create(client)
    _book(pid)
    with pytest.raises(repo.PackageLocked):
        repo.modify_package(pid, 1, lambda s: s.package)


def test_unknown_package_is_a_404_everywhere(client):
    body = {"base_version": 1, "kind": "CHANGE_ARRIVAL_FLIGHT", "flight_id": "X"}
    for r in (
        client.get("/api/packages/nope/options", params={"kind": "arrival_flight"}),
        client.post("/api/packages/nope/preview-change", json=body),
        client.post("/api/packages/nope/apply-change", json=body),
    ):
        assert r.status_code == 404 and r.json()["error"] == "PACKAGE_NOT_FOUND"


MALFORMED = [
    ({"base_version": 1, "kind": "TELEPORT"}, "kind"),
    ({"base_version": 1}, "kind"),
    ({"base_version": 1, "kind": "CHANGE_ARRIVAL_FLIGHT"}, "flight_id"),
    ({"kind": "CHANGE_ARRIVAL_FLIGHT", "flight_id": "F"}, "base_version"),
    (
        {
            "base_version": 1,
            "kind": "ADD_ATTRACTION",
            "date": "2027-13-45",
            "attraction_id": "A",
        },
        "date",
    ),
    (
        {
            "base_version": 1,
            "kind": "CHANGE_ARRIVAL_FLIGHT",
            "flight_id": "F",
            "price_inr": 1,
        },
        "price_inr",
    ),
    ([1, 2], "request"),
]


@pytest.mark.parametrize("path", ["preview-change", "apply-change"])
@pytest.mark.parametrize("body,field", MALFORMED)
def test_malformed_bodies_are_422_with_the_field_named(client, path, body, field):
    pid = _create(client)
    before = _row(pid)
    r = client.post(f"/api/packages/{pid}/{path}", json=body)
    assert r.status_code == 422, r.text
    out = r.json()
    assert (
        out["error"] == "INVALID_CHANGE_REQUEST"
        and out["message"] == "This change request is not valid."
    )
    assert field in out["field_errors"] and out["errors"] and out["reasons"]
    if field == "price_inr":
        assert "computed by the server" in out["field_errors"][field][0]
    assert _row(pid) == before


# ------------------------------------------------------------------ 37 over budget


def test_37_over_budget_but_valid_change_is_previewable_and_appliable_with_a_warning(
    client,
):
    pid = _create(
        client, budget=60_000
    )  # the planner's cheapest package is already over budget
    s = _stored(pid)
    assert s.total_inr > s.package.budget
    body = _pick(s.package, 1, valid=True, nonzero=True)
    prev = client.post(f"/api/packages/{pid}/preview-change", json=body).json()
    assert (
        prev["valid"] is True
        and prev["over_budget_inr"] == prev["new_total_inr"] - 60_000 > 0
    )
    assert prev["budget_remaining_inr"] == 0
    assert any("over your budget" in w for w in prev["warnings"])
    r = client.post(f"/api/packages/{pid}/apply-change", json=body)
    assert r.status_code == 200 and r.json()["change"]["warnings"]
    assert _stored(pid).version == 2


# ------------------------------------------------------------------ options


def test_options_for_a_hotel_lists_alternatives_and_writes_nothing(client):
    pid = _create(client)
    s = _stored(pid)
    before = _row(pid)
    stay_id = s.package.hotels[0].stay_id
    r = client.get(
        f"/api/packages/{pid}/options", params={"kind": "hotel", "stay_id": stay_id}
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert (out["package_id"], out["version"], out["kind"]) == (pid, 1, "hotel")
    assert out["target_item_id"] == stay_id and out["alternatives"]
    assert _row(pid) == before


def test_options_rejects_an_unknown_kind_or_target(client):
    pid = _create(client)
    bad_kind = client.get(f"/api/packages/{pid}/options", params={"kind": "spaceship"})
    assert bad_kind.status_code == 422
    assert (
        bad_kind.json()["error"] == "INVALID_OPTIONS_REQUEST"
        and bad_kind.json()["field"]
    )
    bad_stay = client.get(
        f"/api/packages/{pid}/options", params={"kind": "hotel", "stay_id": "stay:X"}
    )
    assert (
        bad_stay.status_code == 422
        and bad_stay.json()["error"] == "INVALID_OPTIONS_REQUEST"
    )


def test_modify_package_refuses_a_stale_version_without_calling_the_change(client):
    pid = _create(client)
    before = _row(pid)

    def never(stored):
        raise AssertionError("must not run")

    with pytest.raises(repo.VersionConflict) as e:
        repo.modify_package(pid, 7, never)
    assert (e.value.expected, e.value.current) == (7, 1)
    assert _row(pid) == before


def test_a_late_landing_flight_change_picks_up_the_same_night_not_the_next_morning(client):
    # judge-check run: changing Menon to FL-405 (lands 21:30) kept the airport bus, which stops at
    # 22:00, so the pickup moved to 06:30 the next morning. The repair now prefers a service that
    # picks up on the landing day (a taxi runs until 23:00), like the first build does.
    pid = _create(client)
    pkg = client.get(f"/api/packages/{pid}").json()["package"]
    body = {"kind": "CHANGE_ARRIVAL_FLIGHT", "flight_id": "FL-405", "base_version": pkg["version"]}
    preview = client.post(f"/api/packages/{pid}/preview-change", json=body).json()
    assert preview["valid"] is True, preview["violations"]
    items = preview["proposed_package"]["items"]
    flight = next(i for i in items if i["item_id"] == "flight:arrival")
    pickup = next(i for i in items if i["item_id"] == "leg:arrival")
    assert flight["end"][:10] == "2027-04-10"
    assert pickup["start"][:10] == "2027-04-10", pickup
