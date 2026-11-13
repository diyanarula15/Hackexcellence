"""G3 API coverage for replacing a package's city itinerary."""

import copy
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.catalog.load import build_loaded, load_catalog, load_raw
from app.db import db_path
from app.engine.build import INFEASIBLE, OVER_BUDGET, PlanningResult, SEARCH_INCOMPLETE
from app.export.to_trip import to_trip_json
from app.main import app
from app.repositories import packages as repo
from app.rules.common import EDITED
from app.services import city_plans as city_plan_service
from app.services.modifications import InvalidCityPlan
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
NEW_PLAN = [
    {"city_id": "Tokyo", "nights": 4},
    {"city_id": "Kyoto", "nights": 2},
]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HOLIDAY_DB_PATH", str(tmp_path / "city-plan.db"))
    with TestClient(app) as c:
        yield c


def _create(client, **overrides) -> str:
    response = client.post("/api/packages", json={**MENON, **overrides})
    assert response.status_code == 201, response.text
    return response.json()["package"]["id"]


def _options(client, package_id):
    return client.get(f"/api/packages/{package_id}/city-plan-options")


def _command(city_plan=None, base_version=1, **extra):
    return {
        "kind": "CHANGE_CITY_PLAN",
        "base_version": base_version,
        "city_plan": copy.deepcopy(NEW_PLAN if city_plan is None else city_plan),
        **extra,
    }


def _preview(client, package_id, **kwargs):
    return client.post(
        f"/api/packages/{package_id}/preview-change", json=_command(**kwargs)
    )


def _snapshot():
    """All application tables, to catch writes beyond the package row."""
    conn = sqlite3.connect(db_path())
    try:
        names = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
        return {name: conn.execute(f"SELECT * FROM {name}").fetchall() for name in names}
    finally:
        conn.close()


def test_options_describe_the_saved_plan_and_catalog_graph(client):
    package_id = _create(client)

    response = _options(client, package_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["package_id"] == package_id and body["base_version"] == 1
    assert body["country_code"] == "JP" and body["country"] == "Japan"
    assert body["total_nights"] == 6 and body["min_nights_per_city"] == 2
    assert sum(s["nights"] for s in body["current_city_plan"]) == body["total_nights"]
    assert all(set(s) == {"city_id", "nights"} for s in body["current_city_plan"])
    assert all(set(c) == {"city_id", "name"} and c["city_id"] == c["name"] for c in body["cities"])
    assert all(set(c) == {"from_city", "to_city"} for c in body["connections"])
    assert {c["city_id"] for c in body["cities"]} == {"Tokyo", "Kyoto", "Osaka"}
    japan = next(c for c in load_catalog().catalog.destinations["countries"] if c["code"] == "JP")
    assert {(c["from_city"], c["to_city"]) for c in body["connections"]} == {
        (edge["from_city"], edge["to_city"]) for edge in japan["links"]
    }


@pytest.mark.parametrize(
    "plan",
    [
        [{"city_id": "Atlantis", "nights": 6}],
        [{"city_id": "Hanoi", "nights": 6}],  # known city, wrong country
        [{"city_id": "Tokyo", "nights": 3}, {"city_id": "Tokyo", "nights": 3}],
        [{"city_id": "Tokyo", "nights": 5}, {"city_id": "Kyoto", "nights": 1}],
        [{"city_id": "Tokyo", "nights": 4}, {"city_id": "Kyoto", "nights": 3}],
    ],
)
def test_structurally_invalid_plans_return_422_without_writes(client, plan):
    package_id = _create(client)
    before = _snapshot()

    response = _preview(client, package_id, city_plan=plan)

    assert response.status_code == 422, response.text
    assert response.json()["error"] == "INVALID_CITY_PLAN"
    assert response.json()["errors"]
    assert _snapshot() == before


def test_city_sequence_requires_a_directed_catalog_connection(client):
    package_id = _create(client)
    raw = load_raw()
    japan = next(c for c in raw["destinations"]["countries"] if c["code"] == "JP")
    japan["links"] = [
        edge
        for edge in japan["links"]
        if (edge["from_city"], edge["to_city"]) != ("Tokyo", "Kyoto")
    ]

    with pytest.raises(InvalidCityPlan) as exc:
        city_plan_service.validate_city_plan(
            repo.get_package(package_id), NEW_PLAN, build_loaded(raw)
        )

    assert any(error["rule"] == "INVALID_CITY_CONNECTION" for error in exc.value.errors)


def test_preview_is_read_only_and_reports_a_complete_planning_outcome(client):
    package_id = _create(client)
    before = _snapshot()

    response = _preview(client, package_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] in {"FOUND", "OVER_BUDGET", "INFEASIBLE", "SEARCH_INCOMPLETE"}
    assert body["valid"] is True
    assert body["package_id"] == package_id and body["base_version"] == 1
    assert body["proposed_package"]["city_plan"]
    assert [(s["city"], s["nights"]) for s in body["proposed_package"]["city_plan"]] == [
        ("Tokyo", 4), ("Kyoto", 2)
    ]
    assert body["old_total_inr"] is not None and body["new_total_inr"] is not None
    assert body["new_total_inr"] - body["old_total_inr"] == body["price_difference_inr"]
    assert isinstance(body["warnings"], list) and isinstance(body["violations"], list)
    assert body["preview_token"] and len(body["preview_token"]) == 64
    assert _snapshot() == before


def test_incomplete_exact_route_search_is_reported_without_claiming_success(client, monkeypatch):
    package_id = _create(client)
    monkeypatch.setattr(
        city_plan_service,
        "build_package",
        lambda *args, **kwargs: PlanningResult(
            SEARCH_INCOMPLETE,
            None,
            None,
            None,
            None,
            ["The search limit was reached before a complete route was verified."],
            False,
        ),
    )

    response = _preview(client, package_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "SEARCH_INCOMPLETE"
    assert body["search_complete"] is False and body["valid"] is False
    assert body["proposed_package"] is None and body["preview_token"] is None


def test_real_infeasible_exact_route_is_reported_without_claiming_success(client):
    # Delhi has a feasible 6-night Tokyo package, but no matching KIX arrival flight on this date.
    package_id = _create(client, departure="DEL")
    response = _preview(
        client,
        package_id,
        city_plan=[{"city_id": "Kyoto", "nights": 6}],
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == INFEASIBLE
    assert body["search_complete"] is True and body["valid"] is False
    assert body["proposed_package"] is None and body["preview_token"] is None


def test_real_budget_one_city_plan_preview_reports_over_budget(client):
    package_id = _create(client, budget=1)

    response = _preview(client, package_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == OVER_BUDGET
    assert body["valid"] is True and body["search_complete"] is True
    assert body["proposed_package"] is not None and body["preview_token"]
    assert body["over_budget_inr"] == body["new_total_inr"] - 1 > 0


def test_eight_night_three_city_route_previews_and_applies_exactly(client):
    package_id = _create(client, nights=8)
    route = [
        {"city_id": "Tokyo", "nights": 2},
        {"city_id": "Osaka", "nights": 2},
        {"city_id": "Kyoto", "nights": 4},
    ]
    before = repo.get_package(package_id)
    preview = _preview(client, package_id, city_plan=route).json()
    assert preview["valid"] is True and preview["status"] in {"FOUND", OVER_BUDGET}
    assert [(s["city"], s["nights"]) for s in preview["proposed_package"]["city_plan"]] == [
        ("Tokyo", 2), ("Osaka", 2), ("Kyoto", 4)
    ]

    applied = client.post(
        f"/api/packages/{package_id}/apply-change",
        json=_command(city_plan=route, preview_token=preview["preview_token"]),
    )

    assert applied.status_code == 200, applied.text
    saved = repo.get_package(package_id)
    assert saved.id == before.id == package_id and saved.version == 2
    assert [(s.city, s.nights) for s in saved.package.plan.stays] == [
        ("Tokyo", 2), ("Osaka", 2), ("Kyoto", 4)
    ]
    assert validate_trip(to_trip_json(saved.package, load_catalog()), load_catalog(), EDITED) == []


def test_apply_with_preview_token_keeps_identity_bookmark_and_edited_validation(client):
    package_id = _create(client)
    saved = client.post(f"/api/packages/{package_id}/save", json={"name": "Japan spring"})
    assert saved.status_code == 201, saved.text
    prior = repo.get_package(package_id)
    preview = _preview(client, package_id).json()
    assert preview["valid"] is True

    applied = client.post(
        f"/api/packages/{package_id}/apply-change",
        json=_command(preview_token=preview["preview_token"]),
    )

    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert body["applied"] is True
    assert body["package"]["id"] == package_id
    assert body["package"]["version"] == 2
    assert body["package"]["validation_mode"] == EDITED
    assert body["change"]["previous_version"] == 1 and body["change"]["version"] == 2
    assert repo.get_package(package_id).version == 2
    assert [(s.city, s.nights) for s in repo.get_package(package_id).package.plan.stays] == [
        ("Tokyo", 4), ("Kyoto", 2)
    ]
    assert validate_trip(
        to_trip_json(repo.get_package(package_id).package, load_catalog()),
        load_catalog(),
        EDITED,
    ) == []
    assert client.get("/api/saved-trips").json()["trips"][0]["name"] == "Japan spring"
    # The package keeps the same route endpoints; those catalog flights remain compatible.
    flights = {item["details"]["direction"]: item for item in body["package"]["items"] if item["type"] == "flight"}
    assert flights["ARRIVAL"]["catalog_id"] == prior.package.arrival_flight.flight_id
    assert flights["RETURN"]["catalog_id"] == prior.package.return_flight.flight_id
    assert {s["city"] for s in body["package"]["city_plan"]} == {"Tokyo", "Kyoto"}
    assert all(item["city"] != "Osaka" for item in body["package"]["items"])


def test_apply_requires_the_preview_token_and_rejects_a_changed_token_atomically(client):
    package_id = _create(client)
    preview = _preview(client, package_id).json()
    before = _snapshot()

    missing = client.post(
        f"/api/packages/{package_id}/apply-change", json=_command()
    )
    changed = client.post(
        f"/api/packages/{package_id}/apply-change",
        json=_command(preview_token="0" * 64),
    )

    assert missing.status_code == changed.status_code == 409
    assert missing.json()["error"] == changed.json()["error"] == "PREVIEW_OUTDATED"
    assert _snapshot() == before
    assert preview["preview_token"]


def test_apply_rejects_token_when_recomputed_valid_proposal_changes(client, monkeypatch):
    package_id = _create(client)
    preview = _preview(client, package_id).json()
    before = _snapshot()
    retain = city_plan_service._retain

    def changed_retain(old, candidate, request, constraints, catalog, proposed_plan):
        rebuilt = retain(old, candidate, request, constraints, catalog, proposed_plan)
        # The planner restored package identity fields after retaining. Dropping valid, optional
        # visits is still a valid EDITED package and gives apply a different real proposal.
        return rebuilt.with_(visits=())

    monkeypatch.setattr(city_plan_service, "_retain", changed_retain)

    response = client.post(
        f"/api/packages/{package_id}/apply-change",
        json=_command(preview_token=preview["preview_token"]),
    )

    assert response.status_code == 409
    assert response.json()["error"] == "PREVIEW_OUTDATED"
    assert _snapshot() == before


def test_exception_after_package_update_rolls_back_every_table(client, monkeypatch):
    package_id = _create(client)
    preview = _preview(client, package_id).json()
    before = _snapshot()
    row_to_stored = repo._row_to_stored

    def fail_after_update(row):
        if row["version"] == 2:
            raise RuntimeError("injected failure after package UPDATE")
        return row_to_stored(row)

    monkeypatch.setattr(repo, "_row_to_stored", fail_after_update)

    with pytest.raises(RuntimeError, match="injected failure after package UPDATE"):
        client.post(
            f"/api/packages/{package_id}/apply-change",
            json=_command(preview_token=preview["preview_token"]),
        )

    assert _snapshot() == before


def test_stale_version_apply_is_a_conflict_without_a_second_version_bump(client):
    package_id = _create(client)
    first = _preview(client, package_id).json()
    applied = client.post(
        f"/api/packages/{package_id}/apply-change",
        json=_command(preview_token=first["preview_token"]),
    )
    assert applied.status_code == 200, applied.text
    current = _snapshot()

    stale = client.post(
        f"/api/packages/{package_id}/apply-change",
        json=_command(preview_token=first["preview_token"]),
    )

    assert stale.status_code == 409
    assert stale.json()["error"] == "PACKAGE_VERSION_CONFLICT"
    assert repo.get_package(package_id).version == 2
    assert _snapshot() == current


def test_stale_preview_base_version_is_rejected_without_writes(client):
    package_id = _create(client)
    first = _preview(client, package_id).json()
    applied = client.post(
        f"/api/packages/{package_id}/apply-change",
        json=_command(preview_token=first["preview_token"]),
    )
    assert applied.status_code == 200, applied.text
    current = _snapshot()

    stale = _preview(client, package_id, base_version=1)

    assert stale.status_code == 409
    assert stale.json()["error"] == "PACKAGE_VERSION_CONFLICT"
    assert stale.json()["current_version"] == 2
    assert _snapshot() == current


def test_reversed_route_rebuilds_endpoint_flights_and_removes_old_city_items(client):
    package_id = _create(client)
    prior = repo.get_package(package_id).package
    route = [
        {"city_id": "Kyoto", "nights": 4},
        {"city_id": "Tokyo", "nights": 2},
    ]
    preview = _preview(client, package_id, city_plan=route).json()
    assert preview["valid"] is True
    proposed = preview["proposed_package"]
    flights = {
        item["details"]["direction"]: item
        for item in proposed["items"]
        if item["type"] == "flight"
    }
    assert flights["ARRIVAL"]["catalog_id"] != prior.arrival_flight.flight_id
    assert flights["RETURN"]["catalog_id"] != prior.return_flight.flight_id
    # KIX is in Osaka; a compatible flight can display Osaka as the airport city even when the
    # selected hotel/attraction/transfer route contains no Osaka stay.
    assert all(
        item["city"] != "Osaka"
        for item in proposed["items"]
        if item["type"] != "flight"
    )
    assert any(item["type"] == "transfer" for item in proposed["items"])

    applied = client.post(
        f"/api/packages/{package_id}/apply-change",
        json=_command(city_plan=route, preview_token=preview["preview_token"]),
    )
    assert applied.status_code == 200, applied.text
    assert {s["city"] for s in applied.json()["package"]["city_plan"]} == {"Kyoto", "Tokyo"}


def test_booked_package_rejects_city_plan_apply_without_mutating_any_table(client):
    package_id = _create(client)
    preview = _preview(client, package_id).json()
    conn = sqlite3.connect(db_path())
    try:
        conn.execute("UPDATE packages SET status='BOOKED' WHERE id=?", (package_id,))
        conn.commit()
    finally:
        conn.close()
    before = _snapshot()

    response = client.post(
        f"/api/packages/{package_id}/apply-change",
        json=_command(preview_token=preview["preview_token"]),
    )

    assert response.status_code == 409
    assert response.json()["error"] == "PACKAGE_ALREADY_BOOKED"
    assert _snapshot() == before


def test_confirmed_edited_package_stays_immutable_after_rejected_booked_edit(client):
    package_id = _create(client)
    preview = _preview(client, package_id).json()
    applied = client.post(
        f"/api/packages/{package_id}/apply-change",
        json=_command(preview_token=preview["preview_token"]),
    )
    assert applied.status_code == 200, applied.text
    confirmation = client.post(
        f"/api/packages/{package_id}/confirm", json={"base_version": 2}
    )
    assert confirmation.status_code == 200, confirmation.text
    confirmed = confirmation.json()
    package_export = client.get(f"/api/packages/{package_id}/export").json()
    reservation_export = client.get(
        f"/api/reservations/{confirmed['reference']}/export"
    ).json()
    assert package_export == reservation_export == confirmed["trip"]
    booked_snapshot = _snapshot()

    rejected = client.post(
        f"/api/packages/{package_id}/apply-change",
        json=_command(base_version=2, preview_token=preview["preview_token"]),
    )

    assert rejected.status_code == 409
    assert rejected.json()["error"] == "PACKAGE_ALREADY_BOOKED"
    assert _snapshot() == booked_snapshot
    assert client.get(f"/api/packages/{package_id}/export").json() == package_export
    assert client.get(
        f"/api/reservations/{confirmed['reference']}/export"
    ).json() == reservation_export


def test_applied_version_remains_exportable_and_delay_scenarios_use_it(client):
    package_id = _create(client)
    preview = _preview(client, package_id).json()
    applied = client.post(
        f"/api/packages/{package_id}/apply-change",
        json=_command(preview_token=preview["preview_token"]),
    )
    assert applied.status_code == 200, applied.text

    exported = client.get(f"/api/packages/{package_id}/export")
    delayed = client.post(
        f"/api/packages/{package_id}/delay-scenarios", json={"base_version": 2}
    )

    assert exported.status_code == 200 and exported.headers["X-Trip-Valid"] == "true"
    assert exported.headers["X-Validation-Mode"] == EDITED
    assert delayed.status_code == 200, delayed.text
    assert delayed.json()["base_version"] == 2
