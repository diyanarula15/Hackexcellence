"""Phase 4 persistence: SQLite schema, the package repository and package serialization.

Run from backend/: ../.venv/bin/python -m pytest -q tests/test_package_store.py
Every test uses its own temporary database (HOLIDAY_DB_PATH); backend/app.db is never touched.
"""

import copy
import hashlib
import json
import sqlite3
import uuid
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from app.catalog.load import load_catalog
from app.config import CATALOG_DIR
from app.db import connect, create_tables
from app.engine.build import FOUND, WITHIN_BUDGET, build_package
from app.repositories import packages as repo
from app.rules.common import EDITED, INITIAL

MENON = dict(
    departure_airport="BLR",
    destination_country="JP",
    start_date=date(2027, 4, 10),
    nights=6,
    adults=2,
    children_ages=[6],
    budget=350_000,
)
REQUEST = {
    "departure": "BLR",
    "country": "Japan",
    "start_date": "2027-04-10",
    "nights": 6,
    "adults": 2,
    "child_ages": [6],
    "budget": 350_000,
}


@pytest.fixture(scope="module")
def menon():
    result = build_package(SimpleNamespace(**MENON), load_catalog(), WITHIN_BUDGET)
    assert result.status == FOUND
    return result.package


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("HOLIDAY_DB_PATH", str(tmp_path / "test.db"))
    create_tables()


def _rows():
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM packages").fetchone()[0]


# ------------------------------------------------------------------ serialization


def test_serialization_round_trip_is_exact(menon):
    data = json.loads(json.dumps(repo.package_to_dict(menon)))
    back = repo.package_from_dict(data)
    assert back == menon
    assert type(back.plan.start_date) is date
    assert type(back.arrival_flight.departure) is datetime
    assert isinstance(back.hotels, tuple) and isinstance(back.child_ages, tuple)
    assert type(back.hotels[0].total_price) is int


def test_malformed_document_is_rejected(menon):
    data = repo.package_to_dict(menon)
    data["arrival_flight"]["price"] = "75600"  # a string where an int is required
    with pytest.raises(TypeError):
        repo.package_from_dict(data)
    with pytest.raises(ValueError):
        repo.package_from_dict({**repo.package_to_dict(menon), "schema_version": 99})


# ------------------------------------------------------------------ repository


def test_save_and_get_returns_the_same_package(menon):
    package_id = repo.save_package(menon, request=REQUEST)
    assert uuid.UUID(package_id)  # a UUID
    stored = repo.get_package(package_id)
    assert stored.id == package_id
    assert stored.package.trip_id == package_id  # export identity = saved package id
    assert stored.package.with_(trip_id=menon.trip_id) == menon  # every item survived unchanged
    assert stored.request == REQUEST
    assert stored.total_inr == menon.total


def test_new_package_starts_planned_at_version_1(menon):
    stored = repo.get_package(repo.save_package(menon, request=REQUEST))
    assert (stored.version, stored.status, stored.validation_mode) == (1, "PLANNED", INITIAL)
    assert stored.created_at == stored.updated_at


def test_unknown_id_returns_none():
    assert repo.get_package(str(uuid.uuid4())) is None
    assert repo.get_package("not-a-uuid") is None


def test_only_planned_packages_can_be_saved(menon):
    with pytest.raises(ValueError):
        repo.save_package(
            menon.with_(status="BOOKED", booking_reference="1234567890"), request=REQUEST
        )
    assert _rows() == 0


def test_update_checks_the_version(menon):
    package_id = repo.save_package(menon, request=REQUEST)
    stored = repo.get_package(package_id)
    fewer = stored.package.with_(visits=stored.package.visits[:-1])
    assert repo.update_package(package_id, fewer, expected_version=1, validation_mode=EDITED) == 2
    again = repo.get_package(package_id)
    assert (again.version, again.validation_mode, again.total_inr) == (2, EDITED, fewer.total)
    with pytest.raises(repo.VersionConflict):
        repo.update_package(package_id, fewer, expected_version=1, validation_mode=EDITED)
    missing = str(uuid.uuid4())
    with pytest.raises(repo.PackageNotFound):
        repo.update_package(
            missing, fewer.with_(trip_id=missing), expected_version=1, validation_mode=EDITED
        )


def test_corrupted_total_is_detected(menon):
    package_id = repo.save_package(menon, request=REQUEST)
    with connect() as conn:
        conn.execute("UPDATE packages SET total_inr = total_inr + 1 WHERE id = ?", (package_id,))
    with pytest.raises(repo.PackageIntegrityError):
        repo.get_package(package_id)


# ------------------------------------------------------------------ database


def test_failed_write_rolls_back():
    with pytest.raises(RuntimeError):
        with connect() as conn:
            conn.execute(
                "INSERT INTO packages (id, request_json, package_json, total_inr, status, created_at, updated_at)"
                " VALUES ('x', '{}', '{}', 1, 'PLANNED', 't', 't')"
            )
            raise RuntimeError("boom")
    assert _rows() == 0


def test_foreign_keys_and_status_check_are_enforced():
    with pytest.raises(sqlite3.IntegrityError):
        with connect() as conn:
            conn.execute(
                "INSERT INTO reservations (reference, package_id, trip_json, created_at) VALUES (?, ?, ?, ?)",
                ("1234567890", "no-such-package", "{}", "t"),
            )
    with pytest.raises(sqlite3.IntegrityError):
        with connect() as conn:
            conn.execute(
                "INSERT INTO packages (id, request_json, package_json, total_inr, status, created_at, updated_at)"
                " VALUES ('x', '{}', '{}', 1, 'DRAFT', 't', 't')"
            )


def test_create_tables_is_idempotent(menon):
    package_id = repo.save_package(menon, request=REQUEST)
    create_tables()
    assert repo.get_package(package_id) is not None


def test_database_work_does_not_touch_the_catalog(menon):
    def digest():
        return {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(CATALOG_DIR.glob("*.json"))
        }

    files_before = digest()
    memory_before = copy.deepcopy(load_catalog().catalog)
    package_id = repo.save_package(menon, request=REQUEST)
    stored = repo.get_package(package_id)
    repo.update_package(package_id, stored.package, expected_version=1, validation_mode=INITIAL)
    assert digest() == files_before
    assert load_catalog().catalog == memory_before
