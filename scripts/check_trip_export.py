#!/usr/bin/env python3
"""Check trip JSON files against the shared trip format (DATA_DICTIONARY.md section 4).

Usage:
  python3 scripts/check_trip_export.py trip.json [more.json] [--mode INITIAL|EDITED]

Stdlib checks always run (shape, types, booking, totals, country name).
When the project venv is used, the backend rule validator (validate_trip, section 4 travel rules)
also runs. If it cannot be imported the output says "validator skipped" and the exit code is 1,
because the travel rules were then not verified.

Exit code 0 only if every check passes for every file.

Library use: run_checks(trip, mode) -> (checks, validator_ran); check_trip(trip, mode) -> failure messages.
"""

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import NamedTuple, Optional

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DESTINATIONS = ROOT / "data" / "catalog" / "destinations.json"

INITIAL, EDITED = "INITIAL", "EDITED"
TOP_KEYS = {"trip_id", "traveler", "start_date", "end_date", "country", "budget_inr", "total_inr", "items"}
TRAVELER_KEYS = {"name", "home_airport", "adults", "children", "child_ages"}
ITEM_KEYS = {"item_id", "type", "name", "city", "status", "catalog_id", "start", "end", "room_id",
             "quantity", "price_inr", "booking", "sources", "warnings"}
ITEM_TYPES = ("flight", "hotel", "transfer", "attraction")
STATUSES = ("PLANNED", "BOOKED")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
DATETIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")
REFERENCE_RE = re.compile(r"[0-9]{10}")


class Check(NamedTuple):
    name: str
    item_id: Optional[str]
    ok: bool
    message: str  # empty when ok


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _parse_date(s):
    if not isinstance(s, str) or not DATE_RE.fullmatch(s):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _parse_datetime(s):
    if not isinstance(s, str) or not DATETIME_RE.fullmatch(s):
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _country_names():
    data = json.loads(DESTINATIONS.read_text(encoding="utf-8"))
    return [c["name"] for c in data["countries"]]


class _Report:
    def __init__(self):
        self.checks: list[Check] = []

    def add(self, name, ok, message="", item_id=None):
        self.checks.append(Check(name, item_id, bool(ok), "" if ok else message))

    def keys(self, name, obj, expected, item_id=None):
        extra = sorted(set(obj) - expected)
        missing = sorted(expected - set(obj))
        self.add(name, not extra and not missing,
                 f"extra {extra}, missing {missing}", item_id)


def _schema_checks(trip, r: _Report):
    if not isinstance(trip, dict):
        r.add("trip is a JSON object", False, "trip must be a JSON object")
        return
    r.keys("top-level keys", trip, TOP_KEYS)
    r.add("trip_id is a string", isinstance(trip.get("trip_id"), str), "trip_id must be a string")

    tr = trip.get("traveler")
    if not isinstance(tr, dict):
        r.add("traveler is an object", False, "traveler must be an object")
    else:
        r.keys("traveler keys", tr, TRAVELER_KEYS)
        r.add("traveler.name and home_airport are strings",
              isinstance(tr.get("name"), str) and isinstance(tr.get("home_airport"), str),
              f"name={tr.get('name')!r} home_airport={tr.get('home_airport')!r}")
        r.add("traveler.adults is an integer >= 1",
              _is_int(tr.get("adults")) and tr["adults"] >= 1, f"adults={tr.get('adults')!r}")
        ages = tr.get("child_ages")
        ages_ok = isinstance(ages, list) and all(_is_int(a) and 0 <= a <= 17 for a in ages)
        r.add("traveler.child_ages is a list of integers 0-17", ages_ok,
              f"child_ages={ages!r}")
        r.add("traveler.children is an integer equal to len(child_ages)",
              _is_int(tr.get("children")) and isinstance(ages, list)
              and tr["children"] == len(ages),
              f"children={tr.get('children')!r}, child_ages={ages!r}")

    start, end = _parse_date(trip.get("start_date")), _parse_date(trip.get("end_date"))
    r.add("start_date and end_date are YYYY-MM-DD dates", start is not None and end is not None,
          f"start_date={trip.get('start_date')!r} end_date={trip.get('end_date')!r}")
    if start and end:
        r.add("end_date is after start_date", end > start,
              f"end_date {end} is not after start_date {start}")

    country = trip.get("country")
    names = _country_names()
    r.add("country is a country name in destinations.json",
          isinstance(country, str) and country in names,
          f"country={country!r}, expected one of {names}")

    for key in ("budget_inr", "total_inr"):
        r.add(f"{key} is an integer", _is_int(trip.get(key)), f"{key}={trip.get(key)!r}")

    items = trip.get("items")
    if not isinstance(items, list) or not items:
        r.add("items is a non-empty list", False, "items must be a non-empty list")
        return
    r.add("items is a non-empty list", True)

    ids = [it.get("item_id") for it in items if isinstance(it, dict)]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    r.add("item_id values are unique", not dup, f"duplicate item_id {dup}")

    statuses = set()
    refs = set()
    for n, it in enumerate(items):
        if not isinstance(it, dict):
            r.add("item is an object", False, f"items[{n}] is not an object", f"items[{n}]")
            continue
        _item_checks(it, r, statuses, refs)
    r.add("all items share one status", len(statuses) <= 1 and statuses <= set(STATUSES),
          f"statuses {sorted(statuses)}")
    r.add("all BOOKED items carry the same reservation reference", len(refs) <= 1,
          f"references {sorted(refs)}")

    total = trip.get("total_inr")
    prices = [it.get("price_inr") for it in items if isinstance(it, dict)]
    if all(_is_int(p) for p in prices) and _is_int(total):
        r.add("total_inr equals the sum of price_inr", total == sum(prices),
              f"total_inr {total} != sum {sum(prices)}")
    else:
        r.add("total_inr equals the sum of price_inr", False, "prices or total are not integers")


def _item_checks(it, r: _Report, statuses: set, refs: set):
    iid = it.get("item_id") if isinstance(it.get("item_id"), str) and it.get("item_id") else "?"
    r.keys("item fields (14)", it, ITEM_KEYS, iid)
    kind = it.get("type")
    r.add("item type is flight/hotel/transfer/attraction", kind in ITEM_TYPES,
          f"type={kind!r}", iid)
    r.add("item item_id is a non-empty string", iid != "?", f"item_id={it.get('item_id')!r}", iid)
    for key in ("name", "city", "catalog_id"):
        r.add(f"item {key} is a string", isinstance(it.get(key), str), f"{key}={it.get(key)!r}", iid)
    status = it.get("status")
    r.add("item status is PLANNED or BOOKED", status in STATUSES, f"status={status!r}", iid)
    if status in STATUSES:
        statuses.add(status)
    r.add("item quantity is an integer >= 1",
          _is_int(it.get("quantity")) and it["quantity"] >= 1, f"quantity={it.get('quantity')!r}", iid)
    price = it.get("price_inr")
    r.add("item price_inr is an integer >= 0", _is_int(price) and price >= 0,
          f"price_inr={price!r}", iid)
    r.add("item sources is an empty list", it.get("sources") == [],
          f"sources={it.get('sources')!r}", iid)
    w = it.get("warnings")
    r.add("item warnings is a list of strings",
          isinstance(w, list) and all(isinstance(x, str) for x in w), f"warnings={w!r}", iid)

    rid = it.get("room_id")
    if kind == "hotel":
        r.add("hotel room_id is a string", isinstance(rid, str), f"room_id={rid!r}", iid)
    else:
        r.add("non-hotel room_id is null", rid is None, f"room_id={rid!r}", iid)

    start, end = it.get("start"), it.get("end")
    if kind == "hotel":
        s, e = _parse_date(start), _parse_date(end)
        r.add("hotel start/end are YYYY-MM-DD", s is not None and e is not None,
              f"start={start!r} end={end!r}", iid)
        if s and e:
            r.add("hotel check-out is after check-in", e > s, f"{start} -> {end}", iid)
    elif kind in ("flight", "attraction", "transfer"):
        s = _parse_datetime(start)
        r.add("start is YYYY-MM-DDTHH:MM", s is not None, f"start={start!r}", iid)
        if kind == "transfer" and end is None:
            r.add("transfer end is YYYY-MM-DDTHH:MM or null", True, "", iid)
        else:
            e = _parse_datetime(end)
            r.add("end is YYYY-MM-DDTHH:MM" + (" or null" if kind == "transfer" else ""),
                  e is not None, f"end={end!r}", iid)
            if kind == "attraction" and s and e:
                r.add("attraction visit ends after it starts", e > s, f"{start} -> {end}", iid)
    else:
        r.add("start/end format (unknown type)", False, f"type={kind!r}", iid)

    booking = it.get("booking")
    if status == "BOOKED":
        ok = (isinstance(booking, dict) and set(booking) == {"reference"}
              and isinstance(booking.get("reference"), str)
              and REFERENCE_RE.fullmatch(booking["reference"]) is not None)
        r.add("BOOKED item has booking == {reference: 10 digits}", ok,
              f"booking={booking!r}", iid)
        if ok:
            refs.add(booking["reference"])
    elif status == "PLANNED":
        r.add("PLANNED item has booking null", booking is None, f"booking={booking!r}", iid)


def _rule_validator():
    """(catalog, validate_trip) from the backend, or an error string."""
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    try:
        from app.catalog.load import load_catalog
        from app.validate.validate_trip import validate_trip
        return (load_catalog(), validate_trip), None
    except Exception as exc:  # the venv may be missing; report it rather than crash
        return None, f"{type(exc).__name__}: {exc}"


def run_checks(trip, mode=INITIAL):
    """All checks for one trip. Returns (checks, validator_ran)."""
    if mode not in (INITIAL, EDITED):
        raise ValueError(f"mode must be {INITIAL!r} or {EDITED!r}")
    r = _Report()
    _schema_checks(trip, r)
    loaded, error = _rule_validator()
    if loaded is None:
        return r.checks, False
    catalog, validate_trip = loaded
    try:
        violations = validate_trip(trip, catalog, mode)
    except Exception as exc:
        r.add(f"travel rules ({mode}) run", False, f"{type(exc).__name__}: {exc}")
        return r.checks, True
    if not violations:
        r.add(f"travel rules ({mode}) hold", True)
    for v in violations:
        r.add(f"travel rule {v.rule}", False, v.message, v.item_id)
    return r.checks, True


def check_trip(trip, mode=INITIAL):
    """Failure messages for one trip; an empty list means the trip passes every check."""
    checks, _ = run_checks(trip, mode)
    return [
        f"{c.name}" + (f" [{c.item_id}]" if c.item_id else "") + f": {c.message}"
        for c in checks if not c.ok
    ]


def _main(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("files", nargs="+")
    parser.add_argument("--mode", choices=(INITIAL, EDITED), default=INITIAL)
    args = parser.parse_args(argv)

    all_ok = True
    for path in args.files:
        print(f"== {path}")
        try:
            trip = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"FAIL  file could not be read as JSON: {exc}")
            all_ok = False
            continue
        checks, validator_ran = run_checks(trip, args.mode)
        file_ok = validator_ran
        for c in checks:
            label = f"[{c.item_id}] " if c.item_id else ""
            if c.ok:
                print(f"PASS  {label}{c.name}")
            else:
                print(f"FAIL  {label}{c.name}: {c.message}")
                file_ok = False
        if not validator_ran:
            print("validator skipped (run with ../.venv/bin/python from the project to check the travel rules)")
        print(f"{'OK' if file_ok else 'NOT OK'}: {sum(c.ok for c in checks)}/{len(checks)} checks passed")
        all_ok = all_ok and file_ok
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
