"""Package-level tests: the Menon fixture validates clean, single mutations trip the expected rule,
the JSON export has the shared format, and the /api/validate route behaves.

Run from backend/: ../.venv/bin/python -m pytest -q tests/test_package.py
"""
import copy
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from app.catalog.load import load_catalog
from app.export.to_trip import to_trip_json
from app.config import CATALOG_DIR
from app.main import app
from app.rules import pricing
from app.rules.common import EDITED, INITIAL
from app.validate.validate_trip import validate_trip
from fixtures import PARTY, menon_package, menon_trip

L = load_catalog()
ITEM_KEYS = {"item_id", "type", "name", "city", "status", "catalog_id", "room_id", "start", "end",
             "quantity", "price_inr", "booking", "sources", "warnings"}


def _item(trip, cid):
    return next(i for i in trip["items"] if i["catalog_id"] == cid)


def _rules(trip, mode=INITIAL):
    return {v.rule for v in validate_trip(trip, L, mode)}


def test_valid_fixture_has_no_violations():
    assert validate_trip(menon_trip(), L) == []


def test_validation_is_deterministic():
    trip = menon_trip()
    assert validate_trip(trip, L) == validate_trip(trip, L) == []


def _seat_shortage(trip):
    # FL-403 (BLR -> HND, 2 seats left) replaces the outbound flight; its own times and price are used.
    low = L.indexes.flights_by_id["FL-403"]
    _item(trip, "FL-401").update(catalog_id="FL-403", start=low["departure_local"][:16],
                                 end=low["arrival_local"][:16],
                                 price_inr=pricing.flight_price(low, PARTY)[1])


MUTATIONS = [
    ("seat shortage", _seat_shortage, "R-FLT-3"),
    ("item price", lambda t: _item(t, "FL-401").update(price_inr=1), "R-PRICE-2"),
    ("total price", lambda t: t.update(total_inr=t["total_inr"] + 1), "R-PRICE-3"),
    # Hotel price is priced from the item's own quantity, so a quantity that still fits only trips R-PRICE-2;
    # 5 rooms for 2 adults does not fit (adults >= rooms) and trips R-HTL-5.
    ("hotel quantity", lambda t: _item(t, "HTL-TYO-004").update(quantity=5), "R-HTL-5"),
    ("hotel end on departure day", lambda t: _item(t, "HTL-KYO-004").update(end="2027-04-17"), "R-PLAN-7"),
    ("arrival pickup 59 min after landing",
     lambda t: _item(t, "TR-NRT-UEN-BUS").update(start="2027-04-10T11:29", end="2027-04-10T12:59"), "R-ATR-5"),
    ("intercity transfer removed",
     lambda t: t.update(items=[i for i in t["items"] if i["catalog_id"] != "TR-TYO-KYO-01"]), "R-ICT-1"),
    ("attraction moved onto end date",
     lambda t: _item(t, "ATT-KYO-006").update(start="2027-04-16T11:30", end="2027-04-16T13:00"), "R-ATT-11"),
    ("unknown catalog id", lambda t: _item(t, "ATT-KYO-006").update(catalog_id="ATT-XXX-999"), "R-ID-1"),
    ("missing items", lambda t: t.pop("items"), "R-SCHEMA-1"),
]


@pytest.mark.parametrize("label,mutate,rule", MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_single_mutation_triggers_rule(label, mutate, rule):
    trip = copy.deepcopy(menon_trip())
    mutate(trip)
    assert rule in _rules(trip)


@pytest.mark.parametrize("mode,expected", [(INITIAL, True), (EDITED, False)])
def test_empty_full_day_depends_on_mode(mode, expected):
    trip = copy.deepcopy(menon_trip())
    trip["items"] = [i for i in trip["items"] if not (i["type"] == "attraction" and i["start"].startswith("2027-04-12"))]
    assert ("R-ATT-12" in _rules(trip, mode)) is expected


def test_export_shape():
    trip = menon_trip()
    json.dumps(trip)
    assert set(trip) == {"trip_id", "traveler", "start_date", "end_date", "country", "budget_inr",
                         "total_inr", "items"}
    assert all(set(i) == ITEM_KEYS for i in trip["items"])
    assert trip["total_inr"] == sum(i["price_inr"] for i in trip["items"])


def test_booked_export_validates():
    pkg = menon_package()
    pkg["status"], pkg["booking_reference"] = "BOOKED", "1234567890"
    trip = to_trip_json(pkg, L)
    assert all(i["status"] == "BOOKED" for i in trip["items"])
    assert all(i["booking"] == {"reference": "1234567890"} for i in trip["items"])
    assert validate_trip(trip, L) == []


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_api_valid_trip(client):
    r = client.post("/api/validate", json=menon_trip())
    assert r.status_code == 200
    assert r.json() == {"valid": True, "violations": []}


def test_api_mutated_price(client):
    trip = menon_trip()
    _item(trip, "FL-401")["price_inr"] = 1
    r = client.post("/api/validate", json=trip)
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is False
    assert "R-PRICE-2" in {v["rule"] for v in body["violations"]}


def test_api_schema_error_is_422(client):
    assert client.post("/api/validate", json={"x": 1}).status_code == 422


def test_api_malformed_json_is_422(client):
    r = client.post("/api/validate", content='{"x":', headers={"content-type": "application/json"})
    assert r.status_code == 422


def test_validation_does_not_change_catalog_files():
    def digests():
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(CATALOG_DIR.glob("*.json"))}
    before = digests()
    validate_trip(menon_trip(), L)
    assert digests() == before
