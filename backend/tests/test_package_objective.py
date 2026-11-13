"""POST /api/packages accepts an optional planning objective (audit fix for the Price Landscape)."""
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.catalog.load import load_catalog
from app.engine.build import MINIMUM_COST, build_package
from app.models import TripRequest

TRIP = {"departure": "BLR", "country": "Japan", "start_date": "2027-04-10", "nights": 6, "adults": 2,
        "child_ages": [6], "budget": 350000}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HOLIDAY_DB_PATH", str(tmp_path / "objective.db"))
    with TestClient(main.app) as c:
        yield c


def test_minimum_cost_objective_saves_the_proven_cheapest_package(client):
    proven = build_package(TripRequest(departure_airport="BLR", destination_country="JP", start_date="2027-04-10",
                                       nights=6, adults=2, children_ages=[6], budget=350000),
                           load_catalog(), objective=MINIMUM_COST)
    assert proven.search_complete
    r = client.post("/api/packages", json={**TRIP, "objective": "MINIMUM_COST"})
    assert r.status_code == 201
    assert r.json()["package"]["budget"]["total_inr"] == proven.cheapest_total


def test_default_objective_is_unchanged(client):
    default = client.post("/api/packages", json=TRIP).json()
    explicit = client.post("/api/packages", json={**TRIP, "objective": "WITHIN_BUDGET"}).json()
    assert default["package"]["budget"]["total_inr"] == explicit["package"]["budget"]["total_inr"]


@pytest.mark.parametrize("bad", ["CHEAPEST", 1, None, ""])
def test_unknown_objective_is_rejected_with_a_field_error(client, bad):
    r = client.post("/api/packages", json={**TRIP, "objective": bad})
    assert r.status_code == 422
    assert r.json()["status"] == "INVALID_REQUEST"
