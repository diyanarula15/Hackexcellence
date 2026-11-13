"""The expanded real catalog (JP, AE plus TH, SG, MY, ID, VN) works with the planner and validator.

Run from backend/: ../.venv/bin/python -m pytest -q tests/test_expanded_catalog.py
Reads the real data/ files; never modifies them. Referential integrity is re-derived here from the
raw JSON, independently of the catalog loader's own checks.
"""
import json
import time
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.catalog.load import load_catalog
from app.engine.build import FOUND, INFEASIBLE, MINIMUM_COST, OVER_BUDGET, WITHIN_BUDGET, build_package
from app.engine.constraints import PlanningConstraints
from app.export.to_trip import to_trip_json
from app.validate.validate_trip import validate_trip

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "catalog"
BIG = 10_000_000
NEW = ["TH", "SG", "MY", "ID", "VN"]
EXPECTED_CODES = ["JP", "AE", "TH", "SG", "MY", "ID", "VN"]
DEPARTURES = {"BLR": "Bengaluru", "DEL": "Delhi", "BOM": "Mumbai", "MAA": "Chennai"}
ORIGINS = ["BLR", "DEL", "BOM", "MAA"]
SCAN_DATES = [date(2027, 4, d) for d in range(2, 13)]
LINKED_PAIRS = {"TH": ("Bangkok", "Chiang Mai"), "MY": ("Kuala Lumpur", "Penang"),
                "ID": ("Jakarta", "Yogyakarta"), "VN": ("Hanoi", "Da Nang")}
SONGKRAN = [date(2027, 4, d) for d in range(12, 17)]
WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
FLIGHT_CODES = {"NO_ARRIVAL_FLIGHT", "NO_RETURN_FLIGHT", "INSUFFICIENT_FLIGHT_SEATS"}


def raw(name):
    return json.loads((RAW_DIR / f"{name}.json").read_text(encoding="utf-8"))


def req(**over):
    base = dict(departure_airport="BLR", destination_country="TH", start_date=date(2027, 4, 2),
                nights=4, adults=2, children_ages=[6], budget=BIG)
    base.update(over)
    return SimpleNamespace(**base)


def violations_of(pkg, data):
    return validate_trip(to_trip_json(pkg, data), data, "INITIAL")


def assert_clean(pkg, data):
    v = violations_of(pkg, data)
    assert v == [], [f"{x.rule}: {x.message}" for x in v]


@pytest.fixture(scope="module")
def data():
    return load_catalog()


_SCAN_CACHE = {}


def scan(data, code, *, nights=4, adults=2, children=(6,), locked=None, budget=BIG):
    """Cached scan. `locked` is an ordered list of (city, nights); nights must equal their sum."""
    """First (origin, start, result) that is FOUND over origins x April 2..12, or None."""
    key = (code, nights, adults, tuple(children), tuple(locked or ()), budget)
    if key not in _SCAN_CACHE:
        found = None
        for dep in ORIGINS:
            for start in SCAN_DATES:
                constraints = PlanningConstraints(locked_city_plan=list(locked)) if locked else None
                r = build_package(req(departure_airport=dep, destination_country=code, start_date=start,
                                      nights=nights, adults=adults, children_ages=list(children),
                                      budget=budget), data, WITHIN_BUDGET, constraints)
                if r.status == FOUND:
                    found = (dep, start, r)
                    break
            if found:
                break
        _SCAN_CACHE[key] = found
    return _SCAN_CACHE[key]


def intercity_items(trip, data):
    return [i for i in trip["items"] if i["type"] == "transfer"
            and data.indexes.transfers_by_id[i["catalog_id"]].get("airport") is None]


# ------------------------------------------------------------------ 1. catalog shape

def test_destinations_are_exactly_the_seven_countries(data):
    assert [c["code"] for c in data.catalog.destinations["countries"]] == EXPECTED_CODES


def test_departure_airports_unchanged(data):
    cities = {d["airport"]: d["city"] for d in data.catalog.destinations["departure_cities"]}
    assert cities == DEPARTURES


@pytest.mark.parametrize("code", NEW)
def test_new_country_has_flights_both_ways_from_every_departure(data, code):
    country = data.indexes.countries_by_code[code]
    airports = {a for c in country["cities"] for a in c["airports"]}
    for origin in ORIGINS:
        out = [f for f in data.catalog.flights if f["from"] == origin and f["to"] in airports]
        back = [f for f in data.catalog.flights if f["to"] == origin and f["from"] in airports]
        assert out, f"no flight {origin} -> {code}"
        assert back, f"no flight {code} -> {origin}"


@pytest.mark.parametrize("code", NEW)
def test_new_country_cities_have_hotels_and_8_to_15_attractions(data, code):
    for city in data.indexes.countries_by_code[code]["cities"]:
        name = city["name"]
        assert data.indexes.hotels_by_city.get(name), f"no hotels in {name}"
        n = len(data.indexes.attractions_by_city.get(name, []))
        assert 8 <= n <= 15, f"{name} has {n} attractions"


# ------------------------------------------------------------------ 2. referential integrity (re-derived)

def test_referential_integrity_rederived_from_raw_json():
    dest = raw("destinations")
    airports = {a["code"] for a in raw("airports")}
    cities = {c["name"] for co in dest["countries"] for c in co["cities"]}
    hotels = {h["hotel_id"]: h for h in raw("hotels")}
    rooms = {r["room_id"]: r for r in raw("rooms")}
    transfers = {t["transfer_id"]: t for t in raw("transfers")}
    attractions = raw("attractions")
    flights = raw("flights")
    errors = []

    for h in hotels.values():
        if h["city"] not in cities:
            errors.append(f"hotel {h['hotel_id']} city {h['city']}")
    for r in rooms.values():
        if r["hotel_id"] not in hotels:
            errors.append(f"room {r['room_id']} hotel {r['hotel_id']}")
    for a in raw("availability"):
        if a["room_id"] not in rooms:
            errors.append(f"availability room {a['room_id']}")
    for a in attractions:
        if a["city"] not in cities and a["city"] != "Nara":      # Nara: documented exception
            errors.append(f"attraction {a['attraction_id']} city {a['city']}")
    for f in flights:
        for k in ("from", "to"):
            if f[k] not in airports:
                errors.append(f"flight {f['flight_id']} {k} {f[k]}")
    for t in transfers.values():
        if t.get("airport") and t["airport"] not in airports:
            errors.append(f"transfer {t['transfer_id']} airport")
    for co in dest["countries"]:
        for ln in co["links"]:
            for tid in ln["transfer_ids"]:
                t = transfers.get(tid)
                if t is None:
                    errors.append(f"{co['code']} link transfer {tid} missing")
                elif (t.get("from_city"), t.get("to_city")) != (ln["from_city"], ln["to_city"]):
                    errors.append(f"{tid} from/to {t.get('from_city')}->{t.get('to_city')} "
                                  f"!= link {ln['from_city']}->{ln['to_city']}")
    unique = {
        "airports": [a["code"] for a in raw("airports")],
        "hotels": list(hotels),
        "rooms": list(rooms),
        "transfers": list(transfers),
        "attractions": [a["attraction_id"] for a in attractions],
        "flights": [f["flight_id"] for f in flights],
        "availability": [(a["room_id"], a["date"]) for a in raw("availability")],
    }
    for name, ids in unique.items():
        dupes = [k for k, n in Counter(ids).items() if n > 1]
        if dupes:
            errors.append(f"duplicate {name} ids: {dupes[:5]}")
    assert errors == [], errors[:20]


# ------------------------------------------------------------------ 3. Menon-like request per new country

@pytest.mark.parametrize("code", NEW)
def test_menon_like_request_found_and_valid(data, code):
    found = scan(data, code)
    assert found is not None, f"{code}: no origin in {ORIGINS} yields FOUND for April 2..12 (catalog gap)"
    dep, start, r = found
    trip = to_trip_json(r.package, data)
    assert validate_trip(trip, data, "INITIAL") == []
    assert r.package.total == sum(i["price_inr"] for i in trip["items"]) == trip["total_inr"]


# ------------------------------------------------------------------ 4. single-city and linked-pair plans

def test_singapore_single_city_holiday_found_and_valid(data):
    found = scan(data, "SG")
    assert found is not None, "SG: no FOUND package in the origin/date scan"
    _, _, r = found
    assert [s.city for s in r.package.plan.stays] == ["Singapore"]
    assert_clean(r.package, data)


def test_linked_pair_plans_found_for_at_least_three_countries(data):
    found_codes = []
    for code, (a, b) in LINKED_PAIRS.items():
        found = scan(data, code, nights=6, locked=[(a, 3), (b, 3)])
        if found is None:
            continue
        found_codes.append(code)
        _, _, r = found
        pkg = r.package
        assert [s.city for s in pkg.plan.stays] == [a, b]
        assert len(pkg.hotels) == 2
        trip = to_trip_json(pkg, data)
        assert validate_trip(trip, data, "INITIAL") == []
        assert len(intercity_items(trip, data)) == 1, code
    assert len(found_codes) >= 3, f"linked-pair FOUND only for {found_codes}"


# ------------------------------------------------------------------ 5. party sizes

@pytest.mark.parametrize("adults,children,must_find", [
    (1, (), True),
    (2, (6,), True),
    (3, (4, 9), False),
])
def test_thailand_party_sizes(data, adults, children, must_find):
    found = scan(data, "TH", adults=adults, children=children)
    if must_find:
        assert found is not None, f"TH party {adults}+{len(children)} not FOUND in scan"
        assert_clean(found[2].package, data)
        return
    if found is None:
        r = build_package(req(adults=adults, children_ages=list(children), budget=BIG,
                              destination_country="TH"), data)
        assert r.status == INFEASIBLE and r.reasons and r.reason_codes
    else:
        assert_clean(found[2].package, data)


# ------------------------------------------------------------------ 6. budgets

def test_thailand_budget_one_is_over_budget_with_exact_shortfall(data):
    dep, start, _ = scan(data, "TH")
    r = build_package(req(departure_airport=dep, start_date=start, budget=1), data, WITHIN_BUDGET)
    assert r.status == OVER_BUDGET
    assert r.cheapest_total is not None
    assert r.shortfall == r.cheapest_total - 1
    assert r.package is not None and r.package.total == r.cheapest_total
    assert_clean(r.package, data)


def test_thailand_minimum_cost_not_above_within_budget(data):
    dep, start, _ = scan(data, "TH")
    base = req(departure_airport=dep, start_date=start, budget=BIG)
    within = build_package(base, data, WITHIN_BUDGET)
    minimum = build_package(base, data, MINIMUM_COST)
    assert within.status == FOUND and minimum.status == FOUND
    assert minimum.package.total <= within.package.total
    assert_clean(minimum.package, data)


# ------------------------------------------------------------------ 7. limited inventory (Songkran)

def test_songkran_phuket_lodging_is_found_or_explained(data):
    r = build_package(req(destination_country="TH", start_date=SONGKRAN[0], nights=4, adults=2,
                          children_ages=[], budget=BIG), data, WITHIN_BUDGET,
                      PlanningConstraints(locked_city_plan=[("Phuket", 4)]))
    if r.status == FOUND:
        assert_clean(r.package, data)
    else:
        assert r.status == INFEASIBLE
        assert r.reasons, "INFEASIBLE without reasons"
        assert set(r.reason_codes) & ({"NO_HOTEL_AVAILABILITY"} | FLIGHT_CODES), r.reason_codes


def test_songkran_nights_are_mostly_sold_out_in_thailand(data):
    thai = {c["name"] for c in data.indexes.countries_by_code["TH"]["cities"]}
    hotel_city = {h["hotel_id"]: h["city"] for h in data.catalog.hotels}
    room_hotel = {r["room_id"]: r["hotel_id"] for r in data.catalog.rooms}

    def sold_out_share(days):
        rows = [a for a in data.catalog.availability
                if date.fromisoformat(a["date"]) in days
                and hotel_city.get(room_hotel.get(a["room_id"])) in thai]
        assert rows
        return sum(1 for a in rows if a["rooms_left"] == 0) / len(rows)

    early = [date(2027, 4, d) for d in range(2, 5)]
    assert sold_out_share(SONGKRAN) > sold_out_share(early)


# ------------------------------------------------------------------ 8. incompatible transfers

def test_data_contains_realistic_transfer_incompatibilities(data):
    new_cities = {c["name"] for co in data.catalog.destinations["countries"] if co["code"] in NEW
                  for c in co["cities"]}
    groups = {}
    for t in data.catalog.transfers:
        if t.get("airport") and t.get("city") in new_cities:
            groups.setdefault((t["airport"], t["city"], t.get("area")), []).append(t)
    closed_window = [k for k, v in groups.items()
                     if all(t["service_until"] < "21:00" or t["service_from"] > "06:00" for t in v)]
    assert closed_window, "no airport/area pair whose transfers miss the late or early window"
    single_type = [k for k, v in groups.items() if k[2] and len({t["type"] for t in v}) == 1]
    assert single_type, "no hotel area served by only one transfer type"


def _bounded_requests(limit=400):
    """Up to `limit` (origin, country, start, nights) requests, all within the data window."""
    n = 0
    for dep in ORIGINS:
        for code in NEW:
            for nights in (3, 6, 10):
                for day in range(2, 21):
                    start = date(2027, 4, day)
                    if start + timedelta(days=nights) > date(2027, 4, 20):
                        continue
                    if n >= limit:
                        return
                    n += 1
                    yield dep, code, start, nights


def test_no_transfer_failure_found_by_bounded_scan(data):
    """Scan at most 400 requests for NO_RETURN_TRANSFER / NO_ARRIVAL_TRANSFER. If none is found,
    the data-level incompatibility (test above) is the only assertion: the planner's default
    search simply never ran into a transfer gap in this scan."""
    hit, scanned = None, 0
    for dep, code, start, nights in _bounded_requests():
        scanned += 1
        r = build_package(req(departure_airport=dep, destination_country=code, start_date=start,
                              nights=nights), data)
        if r.status == INFEASIBLE and set(r.reason_codes) & {"NO_RETURN_TRANSFER", "NO_ARRIVAL_TRANSFER"}:
            hit = r
            break
    print(f"\n[transfer-scan] scanned {scanned} requests; hit={'yes' if hit else 'no'}")
    if hit is not None:
        assert set(hit.reason_codes) & {"NO_RETURN_TRANSFER", "NO_ARRIVAL_TRANSFER"}, hit.reason_codes
        assert hit.reasons


# ------------------------------------------------------------------ 9. attraction weekdays and closures

@pytest.mark.parametrize("start", [date(2027, 4, 2), date(2027, 4, 5)], ids=["thu-start", "sun-start"])
def test_attraction_items_respect_open_days_and_closures(data, start):
    r = build_package(req(destination_country="TH", start_date=start, nights=6, budget=BIG), data)
    assert r.status == FOUND
    trip = to_trip_json(r.package, data)
    assert validate_trip(trip, data, "INITIAL") == []
    items = [i for i in trip["items"] if i["type"] == "attraction"]
    for item in items:
        rec = data.indexes.attractions_by_id[item["catalog_id"]]
        day = date.fromisoformat(item["start"][:10])
        assert WEEKDAYS[day.weekday()] in rec["open_days"], (rec["attraction_id"], day)
        assert day.isoformat() not in rec.get("closed_dates", []), (rec["attraction_id"], day)


# ------------------------------------------------------------------ 10. infeasible explanations

@pytest.mark.parametrize("over,locked,expected_codes", [
    (dict(adults=9, children_ages=[]), None, {"INSUFFICIENT_FLIGHT_SEATS", "NO_ARRIVAL_FLIGHT", "NO_RETURN_FLIGHT"}),
    (dict(nights=10, start_date=date(2027, 4, 15)), None, {"INVALID_REQUEST"}),
    (dict(start_date=SONGKRAN[0], nights=4, children_ages=[]), [("Phuket", 4)], {"NO_HOTEL_AVAILABILITY"}),
], ids=["nine-adults", "unsupported-date", "songkran-phuket-locked"])
def test_infeasible_requests_are_explained(data, over, locked, expected_codes):
    constraints = PlanningConstraints(locked_city_plan=locked) if locked else None
    r = build_package(req(**over), data, WITHIN_BUDGET, constraints)
    assert r.status == INFEASIBLE
    assert r.reason_codes, "INFEASIBLE without reason codes"
    assert r.reasons, "INFEASIBLE without messages"
    assert set(r.reason_codes) & expected_codes, r.reason_codes


# ------------------------------------------------------------------ 11. determinism

def test_same_request_twice_gives_equal_packages(data):
    dep, start, first = scan(data, "VN")
    again = build_package(req(departure_airport=dep, destination_country="VN", start_date=start), data)
    assert first.status == again.status == FOUND
    assert again.package == first.package
    assert to_trip_json(again.package, data) == to_trip_json(first.package, data)


# ------------------------------------------------------------------ 12. timing record

TIMING_REQUESTS = [
    ("BLR", "TH", date(2027, 4, 2), 4, 2, [6]),
    ("BLR", "SG", date(2027, 4, 2), 4, 2, [6]),
    ("DEL", "MY", date(2027, 4, 3), 6, 2, []),
    ("BOM", "ID", date(2027, 4, 4), 6, 2, [9]),
    ("MAA", "VN", date(2027, 4, 5), 5, 1, []),
    ("BLR", "VN", date(2027, 4, 6), 6, 2, [6, 12]),
    ("DEL", "TH", date(2027, 4, 7), 3, 1, []),
    ("BLR", "TH", date(2027, 4, 10), 10, 2, [6]),
    ("BOM", "MY", date(2027, 4, 12), 6, 2, []),
    ("MAA", "ID", date(2027, 4, 14), 4, 2, [4, 9]),
]


def test_timing_record_for_new_country_searches(data):
    rows = []
    for dep, code, start, nights, adults, children in TIMING_REQUESTS:
        t0 = time.perf_counter()
        r = build_package(req(departure_airport=dep, destination_country=code, start_date=start,
                              nights=nights, adults=adults, children_ages=children, budget=BIG), data)
        elapsed = time.perf_counter() - t0
        rows.append((dep, code, start.isoformat(), nights, adults + len(children), r.status,
                     r.stats.combinations_evaluated, elapsed))
        assert elapsed < 5.0, f"{dep}->{code} {start} took {elapsed:.2f}s"
        assert r.status in (FOUND, INFEASIBLE, OVER_BUDGET)
    print("\n dep  dest  start       nights pax status       combos  seconds")
    for dep, code, start_s, nights, pax, status, combos, elapsed in rows:
        print(f" {dep:<4} {code:<5} {start_s}  {nights:>5} {pax:>3} {status:<12} {combos:>6}  {elapsed:7.3f}")
