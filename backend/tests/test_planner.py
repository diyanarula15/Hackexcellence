"""Planner end-to-end on the real catalog (and one extended catalog).

Run from backend/: ../.venv/bin/python -m pytest -q tests/test_planner.py
Only structural facts are asserted for ids; prices and ids come from the planner and the validator.
"""
import copy
import hashlib
import json
from collections import Counter
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from app.catalog.load import build_loaded, load_catalog, load_raw
from app.config import CATALOG_DIR
from app.engine.build import (FOUND, INFEASIBLE, MINIMUM_COST, OVER_BUDGET, SEARCH_INCOMPLETE,
                              WITHIN_BUDGET, build_package)
from app.engine.constraints import PlanningConstraints
from app.export.to_trip import to_trip_json
from app.validate.validate_trip import validate_trip

BIG = 10_000_000
MENON = dict(departure_airport="BLR", destination_country="JP", start_date=date(2027, 4, 10),
             nights=6, adults=2, children_ages=[6], budget=350_000)


def req(**over):
    return SimpleNamespace(**{**MENON, **over})


def assert_clean(pkg, cat):
    violations = validate_trip(to_trip_json(pkg, cat), cat, "INITIAL")
    assert violations == [], [f"{v.rule}: {v.message}" for v in violations]


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


@pytest.fixture(scope="module")
def menon(cat):
    return build_package(req(), cat, WITHIN_BUDGET)


# ------------------------------------------------------------------ A. Menon

def test_menon_found_within_budget_with_consistent_totals(menon):
    assert menon.status == FOUND
    pkg = menon.package
    assert pkg.total <= 350_000
    assert menon.budget_remaining == 350_000 - pkg.total


def test_menon_flights_and_stays(menon, cat):
    pkg = menon.package
    arr, ret = pkg.arrival_flight, pkg.return_flight
    assert arr.from_airport == "BLR" and arr.arrival.date() == date(2027, 4, 10)
    assert ret.to_airport == "BLR" and ret.departure.date() == date(2027, 4, 16)
    assert len(pkg.hotels) == len(pkg.plan.stays)
    assert sum(s.nights for s in pkg.plan.stays) == 6
    assert sum((h.check_out - h.check_in).days for h in pkg.hotels) == 6
    assert_clean(pkg, cat)


# ------------------------------------------------------------------ B. varied requests

CASES = [
    # dep, country, start, nights, adults, children
    ("BLR", "JP", date(2027, 4, 1), 3, 1, ()),
    ("BLR", "AE", date(2027, 4, 1), 10, 2, ()),
    ("DEL", "JP", date(2027, 4, 1), 6, 2, (6, 12)),
    ("DEL", "AE", date(2027, 4, 17), 3, 2, ()),             # returns 2027-04-20
    ("BOM", "JP", date(2027, 4, 14), 6, 4, (9,)),           # returns 2027-04-20
    ("BOM", "AE", date(2027, 4, 10), 10, 2, (6, 12)),       # returns 2027-04-20
    ("MAA", "JP", date(2027, 4, 17), 3, 1, ()),             # returns 2027-04-20
    ("MAA", "AE", date(2027, 4, 1), 6, 4, (9,)),
    ("BLR", "JP", date(2027, 4, 10), 10, 2, (6, 12)),
    ("DEL", "JP", date(2027, 4, 17), 3, 2, ()),
    ("BOM", "AE", date(2027, 4, 1), 3, 1, ()),
    ("MAA", "JP", date(2027, 4, 10), 6, 2, ()),
    ("BLR", "AE", date(2027, 4, 14), 6, 4, (9,)),
    ("DEL", "AE", date(2027, 4, 1), 10, 2, (6, 12)),
]


@pytest.mark.parametrize("dep,country,start,nights,adults,children", CASES,
                         ids=[f"{c[0]}-{c[1]}-{c[2]:%m%d}-{c[3]}n-{c[4]}a{len(c[5])}c" for c in CASES])
def test_varied_requests_found_or_infeasible_and_valid(cat, dep, country, start, nights, adults, children):
    r = build_package(req(departure_airport=dep, destination_country=country, start_date=start,
                          nights=nights, adults=adults, children_ages=list(children), budget=BIG), cat)
    assert r.status in (FOUND, INFEASIBLE), r.status
    if r.status == INFEASIBLE:
        assert r.reasons
        return
    pkg = r.package
    trip = to_trip_json(pkg, cat)
    assert validate_trip(trip, cat, "INITIAL") == []
    assert trip["total_inr"] == sum(i["price_inr"] for i in trip["items"]) == pkg.total
    hotels = [i for i in trip["items"] if i["type"] == "hotel"]
    assert all(h["room_id"] for h in hotels)
    kinds = Counter(i["type"] for i in trip["items"])
    transfers = [cat.indexes.transfers_by_id[i["catalog_id"]] for i in trip["items"] if i["type"] == "transfer"]
    airport = sum(1 for t in transfers if t.get("airport"))
    assert kinds["flight"] == 2
    assert kinds["hotel"] == len(pkg.plan.stays) == len(hotels)
    assert airport == 2
    assert kinds["transfer"] - airport == len(pkg.plan.stays) - 1


def test_locked_single_city_and_multi_city_plans_validate_clean(cat):
    jp = next(c for c in cat.catalog.destinations["countries"] if c["code"] == "JP")
    city = jp["cities"][0]["name"]
    link = jp["links"][0]                                   # a real linked city pair
    single = build_package(req(nights=6, budget=BIG), cat,
                           constraints=PlanningConstraints(locked_city_plan=[(city, 6)]))
    multi = build_package(req(nights=6, budget=BIG), cat,
                          constraints=PlanningConstraints(locked_city_plan=[
                              (link["from_city"], 3), (link["to_city"], 3)]))
    for r in (single, multi):
        assert r.status == FOUND, r.reasons
        assert_clean(r.package, cat)
    assert single.package.plan.cities == (city,)
    assert multi.package.plan.cities == (link["from_city"], link["to_city"])


def test_over_budget_reports_shortfall_and_still_validates(cat):
    r = build_package(req(budget=1), cat, WITHIN_BUDGET)
    assert r.status == OVER_BUDGET
    assert r.cheapest_total is not None
    assert r.shortfall == r.cheapest_total - 1
    assert_clean(r.package, cat)


def test_minimum_cost_is_never_more_than_within_budget(cat):
    within = build_package(req(), cat, WITHIN_BUDGET)
    minimum = build_package(req(), cat, MINIMUM_COST)
    assert within.status == FOUND
    assert minimum.package.total <= within.package.total


def test_invalid_request_is_infeasible_with_invalid_request_code(cat):
    r = build_package(req(nights=2), cat)
    assert r.status == INFEASIBLE
    assert "INVALID_REQUEST" in r.reason_codes
    assert r.reasons


# ------------------------------------------------------------------ E. export

def test_export_is_json_serialisable_with_dates_and_item_order(menon, cat):
    trip = to_trip_json(menon.package, cat)
    json.dumps(trip)
    assert trip["start_date"] == "2027-04-10"
    assert trip["end_date"] == "2027-04-16"
    types = [i["type"] for i in trip["items"]]
    assert types[:2] == ["flight", "transfer"]
    assert types[-2:] == ["transfer", "flight"]


# ------------------------------------------------------------------ F. extensibility

def _extended_raw():
    raw = copy.deepcopy(load_raw())
    airport = copy.deepcopy(raw["airports"][0])
    airport.update(code="XAP", name="Xland Airport", city="XCity", country="XX",
                   serves_cities=["XCity"])
    raw["airports"].append(airport)

    hotel = copy.deepcopy(raw["hotels"][0])
    hotel.update(hotel_id="HTL-XX-001", name="Xland Hotel", city="XCity", area="Centre", aliases=[])
    raw["hotels"].append(hotel)

    room = copy.deepcopy(raw["rooms"][0])
    room.update(room_id="RM-XX-001-A", hotel_id="HTL-XX-001", max_adults=2, max_children=2,
                price_per_night={"amount": 5000, "currency": "INR"})
    raw["rooms"].append(room)
    for d in ("2027-04-10", "2027-04-11", "2027-04-12", "2027-04-13"):
        raw["availability"].append({"room_id": "RM-XX-001-A", "date": d, "rooms_left": 5})

    taxi = copy.deepcopy(next(t for t in raw["transfers"] if t.get("airport") and t.get("city")))
    taxi.pop("child_price", None)
    taxi.update(transfer_id="TR-XAP-XCITY-TAXI", airport="XAP", city="XCity", area=None,
                from_point="XAP", to_point="XCity hotels", service_from="00:00", service_until="24:00",
                duration_minutes=60, pricing="PER_VEHICLE", max_passengers=4,
                price={"amount": 2000, "currency": "INR"})
    raw["transfers"].append(taxi)

    inbound = copy.deepcopy(raw["flights"][0])
    inbound.update(flight_id="FL-XX-IN", **{"from": "BLR", "to": "XAP"},
                   departure_local="2027-04-09T20:00:00", arrival_local="2027-04-10T06:00:00",
                   price_per_seat={"amount": 30000, "currency": "INR"}, seats_left=9)
    outbound = copy.deepcopy(raw["flights"][0])
    outbound.update(flight_id="FL-XX-OUT", **{"from": "XAP", "to": "BLR"},
                    departure_local="2027-04-13T18:00:00", arrival_local="2027-04-13T23:00:00",
                    price_per_seat={"amount": 30000, "currency": "INR"}, seats_left=9)
    raw["flights"] += [inbound, outbound]

    for i in range(1, 4):
        att = copy.deepcopy(raw["attractions"][0])
        att.update(attraction_id=f"ATT-XX-00{i}", name=f"Xland Sight {i}", city="XCity",
                   open_days=["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"], open_from="09:00",
                   open_until="18:00", visit_minutes=60, child_friendly=True,
                   price_per_person={"amount": 300 * i, "currency": "INR"})
        att.pop("closed_dates", None)
        att["child_price"] = {"amount": 150 * i, "currency": "INR"}
        raw["attractions"].append(att)

    raw["destinations"]["countries"].append({
        "code": "XX", "name": "Xland", "timezone": "Asia/Dubai",
        "cities": [{"name": "XCity", "airports": ["XAP"]}], "links": []})
    return raw


def _hashes():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(CATALOG_DIR.glob("*.json"))}


def test_extended_catalog_with_new_country_plans_and_validates():
    before = _hashes()
    ext = build_loaded(_extended_raw())
    r = build_package(req(destination_country="XX", start_date=date(2027, 4, 10), nights=3,
                          adults=2, children_ages=[], budget=BIG), ext)
    assert r.status == FOUND, r.reasons
    assert r.package.country_code == "XX"
    assert validate_trip(to_trip_json(r.package, ext), ext, "INITIAL") == []
    assert _hashes() == before, "catalog files on disk were modified"


# ------------------------------------------------------------------ G. determinism

def test_same_request_twice_gives_equal_packages(cat):
    a = build_package(req(), cat, WITHIN_BUDGET)
    b = build_package(req(), cat, WITHIN_BUDGET)
    assert a.package == b.package
    assert a.status == b.status


def test_search_does_not_mutate_the_loaded_catalog(cat):
    before = copy.deepcopy(cat)
    build_package(req(), cat, WITHIN_BUDGET)
    assert cat.catalog.flights == before.catalog.flights
    assert cat.catalog.hotels == before.catalog.hotels
    assert cat.catalog.availability == before.catalog.availability
    assert cat.catalog == before.catalog and cat.indexes == before.indexes


def test_failed_search_does_not_affect_the_next_good_search(cat):
    good = build_package(req(), cat, WITHIN_BUDGET).package
    failed = build_package(req(), cat, WITHIN_BUDGET,
                           constraints=PlanningConstraints(locked_city_plan=[("Atlantis", 6)]))
    assert failed.status == INFEASIBLE
    again = build_package(req(), cat, WITHIN_BUDGET).package
    assert again == good
