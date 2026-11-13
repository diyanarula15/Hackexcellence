"""Focused Phase 6 API checks for durable holiday confirmation and lookup."""

from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.catalog.load import load_catalog
from app.db import connect
from app.engine.build import FOUND, WITHIN_BUDGET, build_package
from app.main import app
from app.repositories import packages as package_repo
from app.routes import packages as package_routes


REQUEST = {
    "departure": "BLR",
    "country": "Japan",
    "start_date": "2027-04-10",
    "nights": 6,
    "adults": 2,
    "child_ages": [6],
    "budget": 350_000,
}
ENGINE_REQUEST = SimpleNamespace(
    departure_airport="BLR",
    destination_country="JP",
    start_date=date(2027, 4, 10),
    nights=6,
    adults=2,
    children_ages=[6],
    budget=350_000,
)


@pytest.fixture(scope="module")
def valid_package():
    """Plan once with the real catalog; each test stores this valid result in its own DB."""
    result = build_package(ENGINE_REQUEST, load_catalog(), WITHIN_BUDGET)
    assert result.status == FOUND
    return result.package


@pytest.fixture
def client(tmp_path, monkeypatch, valid_package):
    monkeypatch.setenv("HOLIDAY_DB_PATH", str(tmp_path / "app.db"))
    with TestClient(app) as c:
        package_id = package_repo.save_package(valid_package, request=REQUEST)
        c.package_id = package_id
        yield c


def _confirm(client, version=1, **extra):
    return client.post(
        f"/api/packages/{client.package_id}/confirm",
        json={"base_version": version, **extra},
    )


def _reservation_rows():
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM reservations").fetchone()[0]


def test_confirm_persists_booked_package_and_exports_identical_trip(client, monkeypatch):
    def unexpected_planning(*args, **kwargs):
        raise AssertionError("confirmation and reservation reads must not re-plan")

    monkeypatch.setattr(package_routes, "build_package", unexpected_planning)
    response = _confirm(client)
    assert response.status_code == 200
    confirmed = response.json()
    assert set(confirmed) == {
        "status", "package_id", "reference", "total_inr", "confirmed_at", "trip"
    }
    assert confirmed["status"] == "BOOKED"
    assert confirmed["package_id"] == client.package_id
    assert len(confirmed["reference"]) == 10 and confirmed["reference"].isascii()
    assert confirmed["reference"].isdigit()
    assert confirmed["total_inr"] == confirmed["trip"]["total_inr"]
    assert all(
        item["status"] == "BOOKED"
        and item["booking"] == {"reference": confirmed["reference"]}
        for item in confirmed["trip"]["items"]
    )

    pkg = client.get(f"/api/packages/{client.package_id}")
    assert pkg.status_code == 200
    assert pkg.json()["package"]["status"] == "BOOKED"
    assert pkg.json()["package"]["version"] == 2
    exported = client.get(f"/api/packages/{client.package_id}/export")
    assert exported.status_code == 200
    assert exported.json() == confirmed["trip"]
    looked_up = client.get(f"/api/reservations/{confirmed['reference']}")
    assert looked_up.status_code == 200 and looked_up.json() == confirmed
    assert _reservation_rows() == 1


def test_reservation_and_export_survive_backend_restart(client):
    confirmed = _confirm(client).json()
    package_id, reference, trip = (
        client.package_id, confirmed["reference"], confirmed["trip"]
    )

    # Re-enter the FastAPI lifespan against the same persisted SQLite file.
    with TestClient(app) as restarted:
        assert restarted.get(f"/api/reservations/{reference}").json() == confirmed
        assert restarted.get(f"/api/reservations/{reference}/export").json() == trip
        assert restarted.get(f"/api/packages/{package_id}/export").json() == trip


@pytest.mark.parametrize(
    "reference", ["123", "１２３４５６７８９０", "１２３456789", "abcdefghij", "123456789０"]
)
def test_lookup_rejects_malformed_or_unicode_references(client, reference):
    response = client.get(f"/api/reservations/{reference}")
    assert response.status_code == 422
    assert response.json()["error"] == "INVALID_RESERVATION_REFERENCE"


def test_lookup_and_confirmation_report_unknown_ids(client):
    assert client.get("/api/reservations/1234567890").status_code == 404
    assert client.get("/api/reservations/1234567890/export").status_code == 404
    missing = client.post("/api/packages/no-such-package/confirm", json={"base_version": 1})
    assert missing.status_code == 404
    assert missing.json()["error"] == "PACKAGE_NOT_FOUND"


@pytest.mark.parametrize(
    "body", [None, {}, {"base_version": "1"}, {"base_version": 1.0},
             {"base_version": True}, {"base_version": 0},
             {"base_version": 1, "unexpected": "field"}]
)
def test_confirmation_requires_a_strict_positive_integer_version(client, body):
    response = client.post(f"/api/packages/{client.package_id}/confirm", json=body)
    assert response.status_code == 422
    assert response.json()["error"] == "INVALID_CONFIRMATION_REQUEST"
    assert _reservation_rows() == 0


def test_confirmation_rejects_a_stale_package_version(client, valid_package):
    package_repo.update_package(
        client.package_id, valid_package.with_(trip_id=client.package_id),
        expected_version=1, validation_mode="INITIAL",
    )
    response = _confirm(client, version=1)
    assert response.status_code == 409
    assert response.json()["error"] == "PACKAGE_VERSION_CONFLICT"
    assert response.json()["current_version"] == 2
    assert _reservation_rows() == 0


def test_retry_after_confirmation_returns_same_reservation_even_with_stale_version(client):
    first = _confirm(client, version=1)
    assert first.status_code == 200
    retry = _confirm(client, version=1)
    assert retry.status_code == 200
    assert retry.json() == first.json()
    assert _reservation_rows() == 1


def test_booked_package_rejects_changes(client):
    assert _confirm(client).status_code == 200
    response = client.post(
        f"/api/packages/{client.package_id}/apply-change", json={"kind": "REMOVE_ATTRACTION"}
    )
    assert response.status_code == 409
    assert response.json()["error"] == "PACKAGE_ALREADY_BOOKED"


def test_saved_reservation_reads_do_not_consult_catalog(client, monkeypatch):
    from app.services import reservations as service
    confirmed = _confirm(client).json()
    def unavailable():
        raise AssertionError("catalog must not be read for reservation retrieval or retry")
    monkeypatch.setattr(package_routes, "load_catalog", unavailable)
    monkeypatch.setattr(service, "load_catalog", unavailable)
    reference = confirmed["reference"]
    assert client.get(f"/api/reservations/{reference}").json() == confirmed
    exported = client.get(f"/api/reservations/{reference}/export")
    assert exported.json() == confirmed["trip"]
    assert exported.headers["content-disposition"] == f'attachment; filename="holiday-reservation-{reference}.json"'
    assert client.get(f"/api/packages/{client.package_id}/export").json() == confirmed["trip"]
    assert _confirm(client).json() == confirmed
