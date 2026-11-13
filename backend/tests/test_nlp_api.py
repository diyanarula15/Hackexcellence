"""Read-only API contract for natural-language trip requests."""

import sys

import pytest
from fastapi.testclient import TestClient

from app.db import connect
from app.main import app
from app.repositories import packages as package_repo


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HOLIDAY_DB_PATH", str(tmp_path / "nlp.db"))
    with TestClient(app) as test_client:
        # Schema setup during startup is expected. Request handling must not plan
        # or save packages while the traveler is reviewing parsed values.
        def forbidden(*args, **kwargs):
            raise AssertionError("parse-trip-request must not plan or save packages")

        monkeypatch.setattr(package_repo, "save_package", forbidden)
        from app.engine import build
        monkeypatch.setattr(build, "build_package", forbidden)
        for module_name in ("app.routes.packages", "app.routes.natural_language"):
            module = sys.modules.get(module_name)
            if module is not None and hasattr(module, "build_package"):
                monkeypatch.setattr(module, "build_package", forbidden)
        yield test_client


def _table_counts():
    """Count every SQLite table, catching writes beyond the packages table too."""
    with connect() as conn:
        names = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )]
        return {
            name: conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            for name in names
        }


def _assert_contract(body):
    assert body["status"] in {"READY", "NEEDS_DETAILS", "NEEDS_CORRECTION", "UNSUPPORTED_INTENT"}
    assert body["intent"] in {"PLAN_HOLIDAY", "UNSUPPORTED", "WEATHER", "INFORMATION", "LOOKUP_RESERVATION", "CANCEL_RESERVATION"}
    assert set(body["fields"]) == {
        "departure", "country", "start_date", "nights", "adults", "child_ages", "budget"
    }
    assert set(body["interpretations"]) == set(body["fields"])
    assert all(set(value) >= {"value", "status", "source_text", "spans"}
               for value in body["interpretations"].values())
    assert isinstance(body["missing_fields"], list)
    assert isinstance(body["issues"], list)
    assert all(set(issue) >= {"field", "code", "message", "severity"} for issue in body["issues"])
    assert isinstance(body["assumptions"], list)
    assert isinstance(body["evidence"], dict)
    assert isinstance(body["entities"], list)
    assert isinstance(body["tokens"], list)
    assert isinstance(body["can_search"], bool)
    assert isinstance(body["original_text"], str)
    assert isinstance(body["normalized_text"], str)
    assert isinstance(body["reference_date"], (str, type(None)))
    assert isinstance(body["timezone"], str)


def test_complete_canonical_request_is_ready_with_provenance_and_no_writes(client):
    before = _table_counts()
    text = (
        "Plan a 6-night Japan trip from Bangalore starting 10 April 2027 "
        "for 2 adults and my 6-year-old daughter. Budget around 3.5 lakh."
    )
    response = client.post("/api/parse-trip-request", json={"text": text})

    assert response.status_code == 200
    body = response.json()
    _assert_contract(body)
    assert body["status"] == "READY"
    assert body["fields"] == {
        "departure": "BLR", "country": "Japan", "start_date": "2027-04-10",
        "nights": 6, "adults": 2, "child_ages": [6], "budget": 350000,
    }
    assert body["can_search"] is True
    assert body["original_text"] == text
    for field, excerpt in {
        "departure": "Bangalore", "country": "Japan", "start_date": "10 April 2027",
        "nights": "6-night", "adults": "2 adults", "child_ages": "6-year-old",
        "budget": "3.5 lakh",
    }.items():
        evidence = " ".join(body["evidence"][field])
        assert excerpt.lower() in evidence.lower()
        interpretation = body["interpretations"][field]
        assert interpretation["spans"]
        for start, end in interpretation["spans"]:
            assert 0 <= start < end <= len(text)
            assert text[start:end]
    assert _table_counts() == before


def test_incomplete_request_keeps_partial_fields_and_requests_missing_details(client):
    response = client.post("/api/parse-trip-request", json={"text": "Japan for two adults"})

    assert response.status_code == 200
    body = response.json()
    _assert_contract(body)
    assert body["status"] == "NEEDS_DETAILS"
    assert body["fields"]["country"] == "Japan"
    assert body["fields"]["adults"] == 2
    assert body["fields"]["departure"] is None
    assert body["fields"]["start_date"] is None
    assert body["fields"]["nights"] is None
    assert body["fields"]["budget"] is None
    assert body["can_search"] is False
    assert body["missing_fields"]


def test_contradictory_party_is_not_arbitrarily_resolved(client):
    response = client.post(
        "/api/parse-trip-request",
        json={"text": "Japan trip for 2 adults, actually 4 adults, for 5 nights."},
    )

    assert response.status_code == 200
    body = response.json()
    _assert_contract(body)
    assert body["status"] == "NEEDS_CORRECTION"
    assert body["can_search"] is False
    assert body["fields"]["adults"] is None
    assert any(issue["field"] == "adults" for issue in body["issues"])


def test_unsupported_destination_has_field_diagnostic(client):
    response = client.post(
        "/api/parse-trip-request",
        json={"text": "Plan a 5-night trip to France from Bangalore for 2 adults."},
    )

    assert response.status_code == 200
    body = response.json()
    _assert_contract(body)
    assert body["status"] in {"NEEDS_DETAILS", "NEEDS_CORRECTION"}
    assert body["can_search"] is False
    assert any(issue["field"] == "country" for issue in body["issues"])


@pytest.mark.parametrize("payload", [
    {},
    {"text": "   "},
    {"text": 42},
    {"text": "Japan", "unexpected": True},
    {"text": "Japan", "reference_date": "13/11/2026"},
    {"text": "Japan", "reference_date": 20261113},
    {"text": "Japan", "timezone": "Mars/Olympus"},
    {"text": "x" * 2001},
    [],
])
def test_invalid_body_is_rejected_as_structured_422_without_writes(client, payload):
    before = _table_counts()
    response = client.post("/api/parse-trip-request", json=payload)

    assert response.status_code == 422
    assert isinstance(response.json(), dict)
    assert response.json().get("error") == "INVALID_NATURAL_LANGUAGE_REQUEST"
    assert _table_counts() == before


def test_relative_date_resolves_against_reference_in_supplied_timezone(client):
    response = client.post(
        "/api/parse-trip-request",
        json={
            "text": "Japan trip from Bangalore next Friday for 2 adults for 5 nights",
            "reference_date": "2027-04-01",
            "timezone": "Asia/Kolkata",
        },
    )

    assert response.status_code == 200
    body = response.json()
    _assert_contract(body)
    assert body["reference_date"] == "2027-04-01"
    assert body["timezone"] == "Asia/Kolkata"
    # With 1 April (Thursday) as the reference date, the upcoming Friday is
    # 2 April. The parser resolves relative weekdays against this explicit date.
    assert body["fields"]["start_date"] == "2027-04-02"
    assert body["interpretations"]["start_date"]["spans"]


def test_day_or_week_duration_requires_nights_clarification(client):
    response = client.post(
        "/api/parse-trip-request",
        json={"text": "Japan trip from Bangalore for a week for 2 adults with a budget of 2 lakh"},
    )

    assert response.status_code == 200
    body = response.json()
    _assert_contract(body)
    assert body["fields"]["nights"] is None
    assert body["status"] == "NEEDS_DETAILS"
    assert any(issue["field"] == "nights" for issue in body["issues"])


def test_multiple_child_ages_and_budget_amounts_keep_reviewable_values(client):
    response = client.post(
        "/api/parse-trip-request",
        json={"text": "Japan for 2 adults and children aged 6 and 9, 5 nights, budget target 3 lakh, maximum 4 lakh"},
    )

    assert response.status_code == 200
    body = response.json()
    _assert_contract(body)
    assert body["fields"]["child_ages"] == [6, 9]
    assert body["fields"]["budget"] == 400000
    assert body["metadata"].get("budget_targets") == [300000]


def test_unreal_calendar_date_is_diagnosed_and_never_searchable(client):
    response = client.post(
        "/api/parse-trip-request",
        json={"text": "Japan trip from Bangalore starting 31 February 2027 for 2 adults for 5 nights"},
    )

    assert response.status_code == 200
    body = response.json()
    _assert_contract(body)
    assert body["status"] == "NEEDS_CORRECTION"
    assert body["can_search"] is False
    assert any(issue["field"] == "start_date" for issue in body["issues"])


def test_non_holiday_intent_is_reported_without_searchability(client):
    response = client.post("/api/parse-trip-request", json={"text": "What's the weather in Japan?"})

    assert response.status_code == 200
    body = response.json()
    _assert_contract(body)
    assert body["intent"] == "WEATHER"
    assert body["status"] == "UNSUPPORTED_INTENT"
    assert body["can_search"] is False
