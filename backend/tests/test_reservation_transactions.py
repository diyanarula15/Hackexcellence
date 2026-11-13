"""Phase 6 transaction, collision, identity and immutable-snapshot guarantees."""
import copy
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from types import SimpleNamespace

import pytest

from app.catalog.load import load_catalog
from app.db import connect, create_tables
from app.engine.build import FOUND, build_package
from app.export.to_trip import to_trip_json
from app.lib import ref
from app.repositories import packages
from app.repositories.reservations import get_reservation
from app.rules.common import EDITED
from app.services import reservations as service
from app.validate.validate_trip import validate_trip


@pytest.fixture(scope="module")
def holiday():
    result = build_package(SimpleNamespace(departure_airport="BLR", destination_country="JP",
        start_date=date(2027, 4, 10), nights=6, adults=2, children_ages=[6], budget=350000), load_catalog())
    assert result.status == FOUND
    return result.package


@pytest.fixture(autouse=True)
def database(tmp_path, monkeypatch):
    monkeypatch.setenv("HOLIDAY_DB_PATH", str(tmp_path / "reservations.db"))
    create_tables()


def save(holiday):
    return packages.save_package(holiday, request={})


def counts():
    with connect() as conn:
        return conn.execute("SELECT count(*) FROM reservations").fetchone()[0]


def test_secure_reference_format_and_leading_zero(monkeypatch):
    monkeypatch.setattr(ref.secrets, "randbelow", lambda upper: 42)
    assert ref.generate_reference() == "0000000042"
    monkeypatch.undo()
    assert all(len(r) == 10 and r.isascii() and r.isdecimal() for r in (ref.generate_reference() for _ in range(100)))


def test_confirm_is_atomic_and_idempotent(holiday):
    pid = save(holiday)
    before = packages.get_package(pid)
    reservation = service.confirm_package(pid, 1)
    assert counts() == 1
    booked = packages.get_package(pid)
    assert booked.status == booked.package.status == "BOOKED"
    assert booked.version == 2
    assert booked.package.booking_reference == reservation.reference
    assert booked.total_inr == before.total_inr
    assert service.confirm_package(pid, 1) == reservation
    assert service.confirm_package(pid, 999) == reservation
    assert counts() == 1
    assert validate_trip(reservation.trip_json, load_catalog()) == []
    expected = to_trip_json(before.package, load_catalog())
    for item in expected["items"]:
        item.update(status="BOOKED", booking={"reference": reservation.reference})
    assert reservation.trip_json == expected


def test_concurrent_confirmation_has_one_reference(holiday):
    pid = save(holiday)
    start = threading.Barrier(2)
    def confirm():
        start.wait()
        return service.confirm_package(pid, 1).reference
    with ThreadPoolExecutor(max_workers=2) as pool:
        refs = list(pool.map(lambda _: confirm(), range(2)))
    assert refs[0] == refs[1]
    assert counts() == 1
    assert packages.get_package(pid).version == 2


def test_collision_retries_database_unique_constraint(holiday, monkeypatch):
    ids = [save(holiday), save(holiday)]
    refs = iter(["0000000001", "0000000001", "0000000002"])
    monkeypatch.setattr(service, "generate_reference", lambda: next(refs))
    assert service.confirm_package(ids[0], 1).reference == "0000000001"
    assert service.confirm_package(ids[1], 1).reference == "0000000002"
    assert counts() == 2


def test_collision_exhaustion_leaves_planned(holiday, monkeypatch):
    first, second = save(holiday), save(holiday)
    monkeypatch.setattr(service, "generate_reference", lambda: "0000000001")
    service.confirm_package(first, 1)
    with pytest.raises(service.ConfirmationError) as exc:
        service.confirm_package(second, 1)
    assert exc.value.payload["error"] == "RESERVATION_CREATION_FAILED"
    assert packages.get_package(second).status == "PLANNED"
    assert counts() == 1


def test_failure_after_insert_rolls_back_both_writes(holiday):
    pid = save(holiday)
    with connect() as conn:
        conn.execute("CREATE TRIGGER fail_booking BEFORE UPDATE ON packages BEGIN SELECT RAISE(ABORT, 'test failure'); END")
    before = packages.get_package(pid)
    with pytest.raises(service.ConfirmationError):
        service.confirm_package(pid, 1)
    assert packages.get_package(pid) == before
    assert counts() == 0


def test_stale_confirmation_leaves_unchanged(holiday):
    pid = save(holiday)
    with pytest.raises(service.ConfirmationError) as exc:
        service.confirm_package(pid, 2)
    assert exc.value.payload["error"] == "PACKAGE_VERSION_CONFLICT"
    assert packages.get_package(pid).status == "PLANNED" and counts() == 0


def test_invalid_price_rejected(holiday):
    flight = holiday.arrival_flight
    from dataclasses import replace
    pid = save(holiday.with_(arrival_flight=replace(flight, price=1)))
    with pytest.raises(service.ConfirmationError) as exc:
        service.confirm_package(pid, 1)
    assert exc.value.payload["error"] == "PACKAGE_VALIDATION_FAILED"
    assert counts() == 0 and packages.get_package(pid).status == "PLANNED"


def test_corrupt_total_rejected(holiday):
    pid = save(holiday)
    with connect() as conn:
        conn.execute("UPDATE packages SET total_inr = 1 WHERE id = ?", (pid,))
    with pytest.raises(service.ConfirmationError) as exc:
        service.confirm_package(pid, 1)
    assert exc.value.payload["error"] == "PACKAGE_VALIDATION_FAILED"
    assert counts() == 0


def test_edited_mode_and_overbudget_confirm_exact_saved_trip(holiday):
    pid = save(holiday)
    # An edited package may deliberately have fewer attractions and an accepted higher total.
    edited = packages.modify_package(pid, 1, lambda stored: stored.package.with_(visits=(), budget=1))
    assert edited.validation_mode == EDITED
    reservation = service.confirm_package(pid, 2)
    assert reservation.trip_json["total_inr"] > reservation.trip_json["budget_inr"]
    assert not any(i["type"] == "attraction" for i in reservation.trip_json["items"])
    assert validate_trip(reservation.trip_json, load_catalog(), EDITED) == []


def test_confirm_modified_hotel_preserves_room_and_quantity(holiday):
    # Use the existing Phase 5 engine to obtain a real valid hotel modification.
    from app.engine.change import propose_change
    from app.models import CHANGE_COMMAND
    catalog = load_catalog()
    pid = save(holiday)
    stored = packages.get_package(pid)
    proposed = None
    for hotel in stored.package.hotels:
        for candidate in catalog.indexes.hotels_by_city[hotel.city]:
            for room in catalog.indexes.rooms_by_hotel[candidate["hotel_id"]]:
                cmd = CHANGE_COMMAND.validate_python(dict(kind="CHANGE_HOTEL", base_version=1,
                    stay_id=hotel.stay_id, hotel_id=candidate["hotel_id"], room_id=room["room_id"]))
                result = propose_change(stored.package, cmd, catalog)
                if result.valid and result.proposed_package != stored.package:
                    proposed = result.proposed_package
                    break
            if proposed: break
        if proposed: break
    assert proposed is not None
    edited = packages.modify_package(pid, 1, lambda _: proposed)
    actual = service.confirm_package(pid, 2).trip_json
    planned = to_trip_json(edited.package, catalog)
    assert [(i["catalog_id"], i["room_id"], i["quantity"], i["price_inr"]) for i in actual["items"]] == [
        (i["catalog_id"], i["room_id"], i["quantity"], i["price_inr"]) for i in planned["items"]]


def test_catalog_mismatch_rejects_new_booking_but_not_existing(holiday, monkeypatch):
    old = service.confirm_package(save(holiday), 1)
    pid = save(holiday)
    changed = copy.deepcopy(load_catalog())
    changed.catalog.flights[0]["flight_number"] += "-changed"
    monkeypatch.setattr(service, "load_catalog", lambda: changed)
    with pytest.raises(service.ConfirmationError) as exc:
        service.confirm_package(pid, 1)
    assert exc.value.payload["error"] == "PACKAGE_CATALOG_MISMATCH"
    assert get_reservation(old.reference) == old
    assert service.confirm_package(old.package_id, 1) == old
    assert counts() == 1


def test_missing_legacy_identity_requires_replan(holiday):
    pid = save(holiday)
    with connect() as conn:
        conn.execute("UPDATE packages SET catalog_fingerprint = NULL WHERE id = ?", (pid,))
    with pytest.raises(service.ConfirmationError) as exc:
        service.confirm_package(pid, 1)
    assert exc.value.payload["error"] == "PACKAGE_CATALOG_MISMATCH"
    assert counts() == 0


def test_immutable_snapshot_and_booked_package(holiday):
    reservation = service.confirm_package(save(holiday), 1)
    retrieved = get_reservation(reservation.reference)
    retrieved.trip_json["items"].clear()
    assert get_reservation(reservation.reference) == reservation
    for sql in ("UPDATE reservations SET trip_json = '{}'", "DELETE FROM reservations",
                "UPDATE packages SET status = 'PLANNED'"):
        with pytest.raises(sqlite3.IntegrityError):
            with connect() as conn:
                conn.execute(sql)
    with pytest.raises(packages.PackageLocked):
        packages.modify_package(reservation.package_id, 2, lambda stored: stored.package)
    with pytest.raises(packages.PackageLocked):
        packages.update_package(reservation.package_id, holiday.with_(trip_id=reservation.package_id), expected_version=2, validation_mode=EDITED)
    assert get_reservation(reservation.reference) == reservation


def test_unique_package_constraint_is_authoritative(holiday):
    original = service.confirm_package(save(holiday), 1)
    with pytest.raises(sqlite3.IntegrityError):
        with connect() as conn:
            conn.execute("INSERT INTO reservations VALUES (?, ?, ?, ?)", ("0000000042", original.package_id, json.dumps(original.trip_json), original.created_at))


def test_confirmation_and_modification_serialize(holiday):
    pid = save(holiday)
    barrier = threading.Barrier(2)
    def book():
        barrier.wait()
        try:
            return service.confirm_package(pid, 1)
        except service.ConfirmationError as exc:
            return exc
    def edit():
        barrier.wait()
        try:
            return packages.modify_package(pid, 1, lambda stored: stored.package.with_(budget=1))
        except packages.PackageLocked as exc:
            return exc
    with ThreadPoolExecutor(max_workers=2) as pool:
        b, e = pool.submit(book), pool.submit(edit)
        booking, editing = b.result(), e.result()
    stored = packages.get_package(pid)
    if stored.status == "BOOKED":
        assert isinstance(editing, packages.PackageLocked)
        assert booking.trip_json["budget_inr"] == holiday.budget and counts() == 1
    else:
        assert isinstance(booking, service.ConfirmationError)
        assert booking.payload["error"] == "PACKAGE_VERSION_CONFLICT"
        assert stored.version == 2 and stored.package.budget == 1 and counts() == 0


def test_additive_migration_is_idempotent_and_preserves_rows(holiday):
    pid = save(holiday)
    reservation = service.confirm_package(pid, 1)
    create_tables()
    create_tables()
    assert get_reservation(reservation.reference) == reservation
    assert packages.get_package(pid).status == "BOOKED"


def test_migration_from_actual_legacy_schema_preserves_package(holiday):
    pid = save(holiday)
    with connect() as conn:
        # Emulate the Phase 4 database, before source identity was recorded.
        conn.execute("ALTER TABLE packages DROP COLUMN catalog_fingerprint")
    create_tables()
    create_tables()
    assert packages.get_package(pid).package.with_(trip_id=holiday.trip_id) == holiday
    with connect() as conn:
        assert conn.execute("SELECT catalog_fingerprint FROM packages WHERE id = ?", (pid,)).fetchone()[0] is None
    with pytest.raises(service.ConfirmationError) as exc:
        service.confirm_package(pid, 1)
    assert exc.value.payload["error"] == "PACKAGE_CATALOG_MISMATCH"


@pytest.mark.parametrize("reference", [None, "123", "abcdefghij", "１２３４５６７８９０"])
def test_database_rejects_malformed_references(holiday, reference):
    pid = save(holiday)
    with pytest.raises(sqlite3.IntegrityError):
        with connect() as conn:
            conn.execute("INSERT INTO reservations VALUES (?, ?, '{}', 'now')", (reference, pid))
    assert counts() == 0
