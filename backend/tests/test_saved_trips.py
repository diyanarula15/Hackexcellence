"""Saved trips: bookmarks on planned packages. Saving never books, re-plans or copies a package."""

from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.catalog.load import load_catalog
from app.db import connect
from app.engine.build import FOUND, WITHIN_BUDGET, build_package
from app.main import app
from app.repositories import packages as package_repo


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
    result = build_package(ENGINE_REQUEST, load_catalog(), WITHIN_BUDGET)
    assert result.status == FOUND
    return result.package


@pytest.fixture
def client(tmp_path, monkeypatch, valid_package):
    monkeypatch.setenv("HOLIDAY_DB_PATH", str(tmp_path / "saved.db"))
    with TestClient(app) as c:
        c.package_id = package_repo.save_package(valid_package, request=REQUEST)
        c.other_id = package_repo.save_package(valid_package, request=REQUEST)
        yield c


def _packages_row(package_id):
    with connect() as conn:
        row = conn.execute("SELECT * FROM packages WHERE id = ?", (package_id,)).fetchone()
        return dict(row)


def _count(table):
    with connect() as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _save(client, package_id=None, **body):
    return client.post(f"/api/packages/{package_id or client.package_id}/save", json=body)


def _confirm(client, package_id=None):
    return client.post(
        f"/api/packages/{package_id or client.package_id}/confirm", json={"base_version": 1}
    )


def _trips(client):
    return client.get("/api/saved-trips").json()["trips"]


def test_save_keeps_package_planned_and_unchanged(client):
    before = _packages_row(client.package_id)
    reservations_before = _count("reservations")

    response = _save(client)

    assert response.status_code == 201
    after = _packages_row(client.package_id)
    assert after == before  # total, version, package_json, status all untouched
    assert after["status"] == "PLANNED" and after["version"] == 1
    assert _count("reservations") == reservations_before
    assert client.get(f"/api/packages/{client.package_id}").json()["package"]["status"] == "PLANNED"


def test_default_name_is_country_and_dates(client):
    card = _save(client).json()
    assert card["name"] == "Japan · 10 Apr–16 Apr 2027"
    assert card["package_id"] == client.package_id
    assert card["country"] == "Japan"
    assert card["start_date"] == "2027-04-10" and card["end_date"] == "2027-04-16"
    assert card["nights"] == 6
    assert card["travelers"] == {"adults": 2, "child_ages": [6]}
    assert isinstance(card["cities"], list) and card["cities"]
    assert card["status"] == "PLANNED" and card["booking_reference"] is None
    assert card["total_inr"] == _packages_row(client.package_id)["total_inr"]


def test_custom_name_is_trimmed_and_persists(client):
    assert _save(client, name="  Cherry blossom trip  ").json()["name"] == "Cherry blossom trip"
    assert _trips(client)[0]["name"] == "Cherry blossom trip"


def test_two_different_packages_are_both_listed(client):
    _save(client, name="First")
    _save(client, package_id=client.other_id, name="Second")
    trips = _trips(client)
    assert {t["name"] for t in trips} == {"First", "Second"}
    assert {t["package_id"] for t in trips} == {client.package_id, client.other_id}


def test_saving_the_same_package_twice_keeps_one_bookmark(client):
    assert _save(client, name="One").status_code == 201
    second = _save(client)  # no name: keeps the existing name
    assert second.status_code == 200
    assert second.json()["name"] == "One"
    assert len(_trips(client)) == 1
    third = _save(client, name="Two")
    assert third.status_code == 200 and third.json()["name"] == "Two"
    assert len(_trips(client)) == 1


def test_list_is_newest_updated_first(client):
    _save(client, name="Older")
    _save(client, package_id=client.other_id, name="Newer")
    assert [t["name"] for t in _trips(client)] == ["Newer", "Older"]


@pytest.mark.parametrize("name", ["", "   ", "x" * 61, "bad\nname"])
def test_invalid_names_are_rejected_on_save(client, name):
    response = _save(client, name=name)
    assert response.status_code == 422
    assert response.json()["error"] == "INVALID_TRIP_NAME"
    assert _trips(client) == []


def test_rename_valid_and_invalid(client):
    _save(client, name="Old")
    renamed = client.patch(f"/api/saved-trips/{client.package_id}", json={"name": "New name"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "New name"
    assert _trips(client)[0]["name"] == "New name"

    for bad in ["x" * 61, "   ", None]:
        response = client.patch(f"/api/saved-trips/{client.package_id}", json={"name": bad})
        assert response.status_code == 422, bad
        assert response.json()["error"] == "INVALID_TRIP_NAME"
    assert _trips(client)[0]["name"] == "New name"


def test_rename_unsaved_package_is_404(client):
    response = client.patch(f"/api/saved-trips/{client.package_id}", json={"name": "X"})
    assert response.status_code == 404
    assert response.json()["error"] == "SAVED_TRIP_NOT_FOUND"


def test_remove_deletes_only_the_bookmark(client):
    _save(client, name="Bookmark")
    before = _packages_row(client.package_id)

    response = client.delete(f"/api/saved-trips/{client.package_id}")

    assert response.status_code == 204
    assert _trips(client) == []
    assert _packages_row(client.package_id) == before
    still_there = client.get(f"/api/packages/{client.package_id}")
    assert still_there.status_code == 200
    assert still_there.json()["package"]["status"] == "PLANNED"


def test_remove_unsaved_is_404(client):
    response = client.delete(f"/api/saved-trips/{client.package_id}")
    assert response.status_code == 404
    assert response.json()["error"] == "SAVED_TRIP_NOT_FOUND"


def test_unknown_package_is_404(client):
    response = _save(client, package_id="does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"] == "PACKAGE_NOT_FOUND"


def test_booked_package_cannot_be_saved_or_renamed(client):
    _save(client, name="Before booking")
    assert _confirm(client).status_code == 200
    # the bookmark from before confirmation is still listed, now as BOOKED
    trips = _trips(client)
    assert trips[0]["status"] == "BOOKED"

    response = _save(client, name="After booking")
    assert response.status_code == 409
    assert response.json()["error"] == "PACKAGE_ALREADY_BOOKED"

    renamed = client.patch(f"/api/saved-trips/{client.package_id}", json={"name": "Renamed"})
    assert renamed.status_code == 409
    assert renamed.json()["error"] == "PACKAGE_ALREADY_BOOKED"
    assert _trips(client)[0]["name"] == "Before booking"


def test_saved_trip_later_confirmed_lists_booked_with_reference(client):
    _save(client, name="Will be booked")
    _save(client, package_id=client.other_id, name="Stays planned")
    confirmed = _confirm(client).json()

    by_id = {t["package_id"]: t for t in _trips(client)}
    booked = by_id[client.package_id]
    assert booked["status"] == "BOOKED"
    assert booked["booking_reference"] == confirmed["reference"]
    assert booked["total_inr"] == confirmed["total_inr"]
    assert by_id[client.other_id]["status"] == "PLANNED"
    assert by_id[client.other_id]["booking_reference"] is None


def test_saved_trips_survive_a_restart(client):
    _save(client, name="Kept across restart")
    with TestClient(app) as restarted:
        trips = restarted.get("/api/saved-trips").json()["trips"]
    assert [(t["package_id"], t["name"]) for t in trips] == [(client.package_id, "Kept across restart")]
