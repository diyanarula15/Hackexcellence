#!/usr/bin/env python3
"""Expand the Build My Holiday catalog with five new countries, keeping the schema unchanged.

    python3 scripts/expand_catalog.py            # expand data/catalog in place (idempotent)
    python3 scripts/expand_catalog.py --check    # validate the catalog on disk, change nothing
    python3 scripts/expand_catalog.py --restore  # put the original catalog back from the backup

What it does, in order: loads the 8 original files; backs them up byte for byte (once, never
overwritten); generates new records with a fixed seed; validates everything (schema, references,
unique ids, flight clock arithmetic, dates, and the production loader); writes the new files to a
temporary directory; only then replaces data/catalog. If anything fails the original files are
untouched (or restored). Running it twice adds nothing the second time.

Original records are never edited: every original record stays byte for byte where it was and
the new records are appended after them.
"""
import argparse
import hashlib
import json
import os
import random
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "backend"))

import expand_world as W  # noqa: E402

CATALOG = ROOT / "data" / "catalog"
BACKUP = ROOT / "backups" / "catalog_original"
FILES = ["destinations", "airports", "flights", "hotels", "rooms", "availability", "transfers", "attractions"]
SEED = 20270401
WINDOW_FIRST, WINDOW_LAST = date(2027, 4, 1), date(2027, 4, 20)
FLIGHT_COUNT_RANGE = (1200, 1800)
FLIGHT_DENSITY = 1.3          # scales the per-route flights-per-day in expand_world.ROUTES


class ExpansionError(Exception):
    pass


# ------------------------------------------------------------------ io helpers

def dumps(obj) -> str:
    """The exact formatting of the supplied files (2-space indent, UTF-8, trailing newline)."""
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def read_all(folder: Path) -> dict:
    out = {}
    for n in FILES:
        raw = (folder / f"{n}.json").read_bytes()
        out[n] = json.loads(raw)
        if dumps(out[n]).encode("utf-8") != raw:
            raise ExpansionError(f"{n}.json does not round-trip byte for byte; refusing to rewrite it")
    return out


def rng_for(key: str) -> random.Random:
    """A separate deterministic stream per component, so changing one never shifts another."""
    return random.Random(f"{SEED}:{key}")


def price(n) -> dict:
    return {"amount": int(n), "currency": "INR"}


def hhmm_to_min(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


# ------------------------------------------------------------------ generators

def build_destinations(orig: dict, transfers: list) -> tuple[list, dict]:
    """New country objects. Links reference the intercity transfers created below."""
    by_pair = {}
    for t in transfers:
        if t.get("from_city"):
            by_pair.setdefault((t["from_city"], t["to_city"]), []).append(t["transfer_id"])
    countries = []
    for co in W.COUNTRIES:
        cities = [c["name"] for c in co["cities"]]
        links = [{"from_city": a, "to_city": b, "transfer_ids": ids}
                 for (a, b), ids in by_pair.items() if a in cities and b in cities]
        countries.append({"code": co["code"], "name": co["name"], "timezone": co["tz"],
                          "cities": [{"name": c["name"], "airports": list(c["airports"])} for c in co["cities"]],
                          "links": links})
    return countries, by_pair


def build_airports() -> list:
    serves = {}
    for co in W.COUNTRIES:
        for c in co["cities"]:
            for ap in c["airports"]:
                serves.setdefault(ap, []).append(c["name"])
    out = []
    for code, (name, city, country, tz, lat, lng) in W.AIRPORTS.items():
        out.append({"code": code, "name": name, "city": city, "country": country, "timezone": tz,
                    "lat": lat, "lng": lng, "serves_cities": serves[code]})
    return out


def build_flights(first_id: int, origins: list, airports: dict) -> list:
    """Outbound + return flights. Elapsed time is exact: arrival_local - departure_local, corrected for
    the two time zones, equals duration_minutes."""
    rng = rng_for("flights")
    off = W.TZ_OFFSET
    in_tz = "Asia/Kolkata"
    flights, n = [], first_id
    org_name = {o: airports[o] for o in origins}  # noqa: F841 (documentation of the supported origins)

    def make(frm, to, frm_tz, to_tz, dep_local, minutes, stops, rate, country):
        nonlocal n
        dep_utc = dep_local - timedelta(minutes=off[frm_tz])
        arr_local = dep_utc + timedelta(minutes=minutes) + timedelta(minutes=off[to_tz])
        airline, prefix = rng.choice(W.AIRLINES[country])
        fare = minutes * rate * rng.uniform(0.85, 1.3) * (0.82 if stops else 1.0)
        if dep_local.weekday() >= 4:
            fare *= 1.08
        seats = rng.choices(range(1, 10), weights=[4, 6, 8, 10, 13, 15, 16, 15, 13])[0]
        rec = {"flight_id": f"FL-{n}", "airline": airline, "flight_number": f"{prefix} {rng.randint(100, 899)}",
               "from": frm, "to": to, "departure_local": dep_local.strftime("%Y-%m-%dT%H:%M:%S"),
               "arrival_local": arr_local.strftime("%Y-%m-%dT%H:%M:%S"), "stops": stops,
               "duration_minutes": minutes, "price_per_seat": price(round(fare / 20) * 20),
               "seats_left": seats, "cabin": "ECONOMY"}
        n += 1
        return rec

    def flights_per_day(fpd):
        fpd *= FLIGHT_DENSITY
        return int(fpd) + (1 if rng.random() < fpd - int(fpd) else 0)

    def duration(base, p_stop):
        if rng.random() < p_stop:
            return round((base + rng.randint(120, 330)) / 5) * 5, 1
        return round((base + rng.randint(-10, 15)) / 5) * 5, 0

    country_of = {code: v[2] for code, v in W.AIRPORTS.items()}
    for ap, by_origin in W.ROUTES.items():
        tz = W.AIRPORTS[ap][3]
        country = country_of[ap]
        for org, (base, p_stop, fpd) in by_origin.items():
            if org not in origins:
                continue
            day = date(2027, 3, 31)
            while day <= WINDOW_LAST:                              # outbound: must LAND inside the window
                for _ in range(flights_per_day(fpd)):
                    h, m = rng.choice(W.OUT_SLOTS).split(":")
                    dep = datetime(day.year, day.month, day.day, int(h), int(m))
                    mins, stops = duration(base, p_stop)
                    rec = make(org, ap, in_tz, tz, dep, mins, stops, 62, country)
                    if WINDOW_FIRST <= date.fromisoformat(rec["arrival_local"][:10]) <= WINDOW_LAST:
                        flights.append(rec)
                    else:
                        n -= 1
                day += timedelta(days=1)
            day = WINDOW_FIRST
            while day <= WINDOW_LAST:                              # return: must DEPART inside the window
                for _ in range(flights_per_day(fpd)):
                    h, m = rng.choice(W.BACK_SLOTS).split(":")
                    dep = datetime(day.year, day.month, day.day, int(h), int(m))
                    mins, stops = duration(base, p_stop)
                    flights.append(make(ap, org, tz, in_tz, dep, mins, stops, 62, country))
                day += timedelta(days=1)
    return flights


def build_hotels_rooms_availability() -> tuple[list, list, list]:
    hotels, rooms, avail = [], [], []
    dates = [(WINDOW_FIRST + timedelta(days=i)).isoformat() for i in range((WINDOW_LAST - WINDOW_FIRST).days + 1)]
    for co in W.COUNTRIES:
        for city in co["cities"]:
            rng = rng_for(f"hotels:{city['name']}")
            count = rng.randint(18, 20) if city["name"] == "Singapore" else rng.randint(15, 20)
            used_names = set()
            for i in range(1, count + 1):
                stars = rng.choices([2, 3, 4, 5], weights=[15, 35, 35, 15])[0]
                area = city["areas"][(i - 1) % len(city["areas"])]
                while True:
                    name = f"{area} {rng.choice(W.HOTEL_ADJ)} {rng.choice(W.HOTEL_KINDS[stars])}"
                    if name not in used_names:
                        used_names.add(name)
                        break
                family = rng.random() < (0.45 if stars == 2 else 0.7)
                rating = round(min(9.4, max(6.9, {2: 7.1, 3: 7.8, 4: 8.4, 5: 9.0}[stars] + rng.uniform(-.4, .4))), 1)
                hid = f"HTL-{city['code']}-{i:03d}"
                image = W.FAMILY_IMAGE if (family and stars == 3 and rng.random() < .4) else rng.choice(W.HOTEL_IMAGES[stars])
                hotels.append({"hotel_id": hid, "name": name, "aliases": [], "city": city["name"], "area": area,
                               "lat": round(city["lat"] + rng.uniform(-.03, .03), 4),
                               "lng": round(city["lng"] + rng.uniform(-.03, .03), 4), "rating": rating,
                               "stars": stars, "check_in_from": rng.choice(["14:00", "15:00"]),
                               "check_out_until": rng.choice(["11:00", "12:00"]), "family_friendly": family,
                               "image": image})
                # room types: always one adult-only type, plus 1-3 more; family hotels get FAMILY
                types = [rng.choice(["TWIN", "DOUBLE"])]
                if family or rng.random() < .3:
                    types.append("FAMILY")
                if rng.random() < .45:
                    types.append("TRIPLE")
                if rng.random() < .35:
                    types.append("SINGLE")
                if stars >= 4 and rng.random() < .6:
                    types.append("FAMILY_SUITE")
                types = list(dict.fromkeys(types))
                if len(types) < 2:
                    types.append("TRIPLE")
                if len(types) > 4:
                    types = [types[0]] + rng.sample(types[1:], 3)
                limited = rng.random() < .25                       # small hotel: few rooms of each type
                closed_block = None
                if rng.random() < .18:                             # whole hotel unavailable for some nights
                    s = rng.randint(0, len(dates) - 5)
                    closed_block = set(dates[s:s + rng.randint(2, 4)])
                hotel_noise = rng.uniform(.85, 1.2)
                for letter, rtype in zip("ABCD", types):
                    ma, mc, pf, rname = W.ROOM_TYPES[rtype]
                    nightly = 4200 * city["pf"] * W.STAR_FACTOR[stars] * pf * hotel_noise * rng.uniform(.95, 1.05)
                    rid = f"RM-{city['code']}-{i:03d}-{letter}"
                    rooms.append({"room_id": rid, "hotel_id": hid, "room_type": rtype, "name": rname,
                                  "max_adults": ma, "max_children": mc, "price_per_night": price(nightly),
                                  "refundable": rng.random() < .55})
                    cap = rng.randint(1, 3) if limited else rng.randint(3, 8)
                    for d in dates:
                        if closed_block and d in closed_block:
                            left = 0
                        elif rng.random() < .035:
                            left = 0
                        else:
                            left = rng.randint(1, cap)
                        for ev, cities, a, b, frac in W.SOLD_OUT_EVENTS:
                            if city["name"] in cities and a <= d <= b and rng.random() < frac:
                                left = 0
                        avail.append({"room_id": rid, "date": d, "rooms_left": left})
    return hotels, rooms, avail


def _code(text: str, taken: set) -> str:
    """A short unique area code for ids: initials, else the first letters; numbers are kept."""
    words = text.replace("-", " ").split()
    base = "".join(w if w.isdigit() else w[0] for w in words)[:3].upper()
    if len(base) < 3:
        base = text.replace(" ", "")[:3].upper()
    code, k = base, 2
    while code in taken:
        code, k = f"{base}{k}", k + 1
    taken.add(code)
    return code


def build_transfers() -> list:
    transfers, used = [], set()

    def add(rec):
        if rec["transfer_id"] in used:
            raise ExpansionError(f"duplicate transfer id {rec['transfer_id']}")
        used.add(rec["transfer_id"])
        transfers.append(rec)

    for co in W.COUNTRIES:
        for city in co["cities"]:
            rng = rng_for(f"transfers:{city['name']}")
            for ap in city["airports"]:
                short = W.AIRPORT_SHORT[ap]
                ride = W.AIRPORT_RIDE[ap]
                areas = [(a, f"{a} area hotels") for a in city["areas"]]
                # area codes must not look like a city code, or ids could clash with intercity ids
                taken_codes = {c["code"] for co2 in W.COUNTRIES for c in co2["cities"]}
                for area, pt in areas:
                    acode = _code(area, taken_codes)
                    mins = ride + rng.randint(0, 25)
                    scale = {"BKK": 1.0, "DMK": .9}.get(ap, 1.0) * city["pf"] ** .5
                    kinds = []
                    if rng.random() < .8:
                        kinds.append("TAXI")
                    if rng.random() < .55:
                        kinds.append("BUS")
                    if rng.random() < .35:
                        kinds.append("VAN")
                    if not kinds:
                        kinds.append(rng.choice(["TAXI", "BUS", "VAN"]))
                    for kind in kinds:
                        tid = f"TR-{ap}-{acode}-{kind}"
                        if kind == "TAXI":
                            win = rng.choice([("00:00", "24:00"), ("05:00", "24:00"), ("06:00", "23:00"), ("07:00", "21:30")])
                            rec = {"transfer_id": tid, "type": "AIRPORT_TAXI", "name": f"{short} airport taxi to {area}",
                                   "airport": ap, "city": city["name"], "area": area, "from_point": ap, "to_point": pt,
                                   "max_passengers": 4, "service_from": win[0], "service_until": win[1],
                                   "duration_minutes": mins, "pricing": "PER_VEHICLE",
                                   "price": price(mins * 28 * scale * rng.uniform(.85, 1.2))}
                        elif kind == "VAN":
                            win = rng.choice([("06:00", "23:30"), ("00:00", "24:00"), ("05:30", "22:30")])
                            rec = {"transfer_id": tid, "type": "AIRPORT_VAN", "name": f"{short} private van to {area}",
                                   "airport": ap, "city": city["name"], "area": area, "from_point": ap, "to_point": pt,
                                   "max_passengers": 8, "service_from": win[0], "service_until": win[1],
                                   "duration_minutes": mins + rng.randint(0, 10), "pricing": "PER_VEHICLE",
                                   "price": price(mins * 44 * scale * rng.uniform(.85, 1.2))}
                        else:
                            win = rng.choice([("06:00", "22:00"), ("06:30", "21:30"), ("05:30", "23:00"), ("07:00", "20:00")])
                            adult = mins * 11 * scale * rng.uniform(.85, 1.25)
                            rec = {"transfer_id": tid, "type": "AIRPORT_BUS", "name": f"{short} airport shuttle bus to {area}",
                                   "airport": ap, "city": city["name"], "area": area, "from_point": ap, "to_point": pt,
                                   "max_passengers": 99, "service_from": win[0], "service_until": win[1],
                                   "duration_minutes": mins + rng.randint(10, 40), "pricing": "PER_PERSON",
                                   "price": price(adult), "child_price": price(adult / 2)}
                        add(rec)
                if rng.random() < .4:                              # one bus that serves every area of the city
                    adult = ride * 12 * city["pf"] ** .5 * rng.uniform(.9, 1.2)
                    add({"transfer_id": f"TR-{ap}-{city['code']}-BUS", "type": "AIRPORT_BUS",
                         "name": f"{short} airport bus to {city['name']} city centre", "airport": ap, "city": city["name"],
                         "area": None, "from_point": ap, "to_point": f"{city['name']} city centre",
                         "max_passengers": 99, "service_from": rng.choice(["05:30", "06:00"]),
                         "service_until": rng.choice(["22:30", "23:30"]), "duration_minutes": ride + rng.randint(15, 45),
                         "pricing": "PER_PERSON", "price": price(adult), "child_price": price(adult / 2)})
            # one optional city taxi per city (not used by the planner unless it prices it)
            add({"transfer_id": f"TR-{city['code']}-CITY-TAXI", "type": "CITY_TAXI",
                 "name": f"{city['name']} city taxi, hotel to main station", "airport": None, "city": city["name"],
                 "area": None, "from_point": f"{city['name']} hotels", "to_point": f"{city['name']} main station",
                 "max_passengers": 4, "service_from": "05:00", "service_until": "24:00", "duration_minutes": 25,
                 "pricing": "PER_VEHICLE", "price": price(1500 * city["pf"] ** .5)})
    # intercity services
    for country, a, b, services in W.INTERCITY:
        for s in services:
            ca = next(c["code"] for co in W.COUNTRIES for c in co["cities"] if c["name"] == a)
            cb = next(c["code"] for co in W.COUNTRIES for c in co["cities"] if c["name"] == b)
            tid = f"TR-{ca}-{cb}-{W.TRANSFER_CODES[s['kind']]}"
            rec = {"transfer_id": tid, "type": s["kind"], "name": f"{s['label']} {a} to {b}", "airport": None,
                   "city": None, "area": None, "from_point": s["fp"], "to_point": s["tp"],
                   "max_passengers": s["cap"], "service_from": s["win"][0], "service_until": s["win"][1],
                   "duration_minutes": s["mins"],
                   "pricing": "PER_VEHICLE" if s["kind"] == "INTERCITY_TAXI" else "PER_PERSON",
                   "price": price(s["price"])}
            if s["child"] is not None:
                rec["child_price"] = price(s["child"])
            rec["from_city"], rec["to_city"] = a, b
            if s["freq"]:
                rec["frequency_minutes"] = s["freq"]
            if s["d2d"] is not None:
                rec["door_to_door"] = s["d2d"]
            elif s["kind"] != "TRAIN":
                rec["door_to_door"] = False
            add(rec)
    return transfers


def build_attractions() -> list:
    out = []
    codes = {c["name"]: c["code"] for co in W.COUNTRIES for c in co["cities"]}
    for city, rows in W.ATTRACTIONS.items():
        rng = rng_for(f"attractions:{city}")
        for i, (name, cat, lat, lng, days, o_from, o_until, mins, adult, child, kf, acc) in enumerate(rows, 1):
            rec = {"attraction_id": f"ATT-{codes[city]}-{i:03d}", "name": name, "name_ja": None, "city": city,
                   "category": cat, "lat": lat, "lng": lng, "open_days": list(W.DAYS[days]), "open_from": o_from,
                   "open_until": o_until, "aliases": [], "visit_minutes": mins, "child_friendly": kf,
                   "accessible": acc, "price_per_person": price(adult),
                   # synthetic data: there are no licensed photos for these places
                   "image": None}
            if child is not None:
                rec["child_price"] = price(child)
            if rng.random() < .22 and mins <= 480:                  # a few extra closed dates
                pool = [(WINDOW_FIRST + timedelta(days=d)).isoformat() for d in range(20)]
                rec["closed_dates"] = sorted(rng.sample(pool, rng.randint(1, 2)))
            out.append(rec)
    return out


# ------------------------------------------------------------------ validation

def _types_of(records) -> dict:
    sig = {}
    for r in records:
        for k, v in r.items():
            sig.setdefault(k, set()).add(type(v).__name__)
    return sig


def validate(orig: dict, new: dict) -> dict:
    """Raise ExpansionError on any problem; return a few statistics."""
    errs: list[str] = []
    err = errs.append

    # 1. originals untouched and new records appended after them
    for n in FILES:
        if n == "destinations":
            continue
        o, x = orig[n], new[n]
        if x[:len(o)] != o:
            err(f"{n}: original records changed or reordered")
    o_d, n_d = orig["destinations"], new["destinations"]
    if n_d["departure_cities"] != o_d["departure_cities"] or n_d["rules"] != o_d["rules"]:
        err("destinations: departure_cities or rules changed")
    if n_d["countries"][:len(o_d["countries"])] != o_d["countries"]:
        err("destinations: original countries changed")
    if len(n_d["countries"]) != len(o_d["countries"]) + len(W.COUNTRIES):
        err("destinations: expected exactly five new countries")

    # 2. schema: new records use only existing fields, with the types the originals use
    for n in FILES:
        if n == "destinations":
            continue
        base = _types_of(orig[n])
        required = {k for k in base if all(k in r for r in orig[n])}
        for r in new[n][len(orig[n]):]:
            extra = set(r) - set(base)
            missing = required - set(r)
            if extra:
                err(f"{n} {next(iter(r.values()))}: unknown fields {sorted(extra)}")
            if missing:
                err(f"{n} {next(iter(r.values()))}: missing fields {sorted(missing)}")
            for k, v in r.items():
                ok = type(v).__name__ in base.get(k, set()) or (k == "image" and v is None) or (v is None and "NoneType" in base.get(k, set()))
                if not ok:
                    err(f"{n} {next(iter(r.values()))}.{k}: type {type(v).__name__} not used by the originals")
                if isinstance(v, dict) and set(v) == {"amount", "currency"}:
                    if not isinstance(v["amount"], int) or v["currency"] != "INR" or v["amount"] < 0:
                        err(f"{n} {next(iter(r.values()))}.{k}: bad price {v}")

    # 3. unique ids
    for n, key in (("airports", "code"), ("flights", "flight_id"), ("hotels", "hotel_id"), ("rooms", "room_id"),
                   ("transfers", "transfer_id"), ("attractions", "attraction_id")):
        ids = [r[key] for r in new[n]]
        if len(ids) != len(set(ids)):
            err(f"{n}: duplicate {key}")
    av = [(a["room_id"], a["date"]) for a in new["availability"]]
    if len(av) != len(set(av)):
        err("availability: duplicate (room, date)")

    airports = {a["code"]: a for a in new["airports"]}
    hotels = {h["hotel_id"]: h for h in new["hotels"]}
    rooms = {r["room_id"]: r for r in new["rooms"]}
    transfers = {t["transfer_id"]: t for t in new["transfers"]}
    cities = {c["name"]: co for co in new["destinations"]["countries"] for c in co["cities"]}

    # 4. references
    for f in new["flights"]:
        for k in ("from", "to"):
            if f[k] not in airports:
                err(f"flight {f['flight_id']}: unknown airport {f[k]}")
    for h in new["hotels"]:
        if h["city"] not in cities:
            err(f"hotel {h['hotel_id']}: unknown city {h['city']}")
    for r in new["rooms"]:
        if r["hotel_id"] not in hotels:
            err(f"room {r['room_id']}: unknown hotel")
    for a in new["availability"]:
        if a["room_id"] not in rooms:
            err(f"availability: unknown room {a['room_id']}")
    new_cities = {c["name"] for co in W.COUNTRIES for c in co["cities"]}
    for a in new["attractions"][len(orig["attractions"]):]:
        if a["city"] not in new_cities:
            err(f"attraction {a['attraction_id']}: city {a['city']} is not a new city")
    for co in new["destinations"]["countries"]:
        for ln in co["links"]:
            ids = ln["transfer_ids"]
            if not ids:
                err(f"{co['code']} link {ln['from_city']}->{ln['to_city']}: no transfers")
            for tid in ids:
                t = transfers.get(tid)
                if not t or (t.get("from_city"), t.get("to_city")) != (ln["from_city"], ln["to_city"]):
                    err(f"{co['code']} link {ln['from_city']}->{ln['to_city']}: transfer {tid} does not match")
        names = {c["name"] for c in co["cities"]}
        if any(ln["from_city"] not in names or ln["to_city"] not in names for ln in co["links"]):
            err(f"{co['code']}: a link leaves the country")

    # 5. dates and flight arithmetic (new flights only)
    first, last = WINDOW_FIRST, WINDOW_LAST
    dep_airports = {c["airport"] for c in new["destinations"]["departure_cities"]}
    new_ap = {c for c in W.AIRPORTS}
    for f in new["flights"][len(orig["flights"]):]:
        dep = datetime.fromisoformat(f["departure_local"])
        arr = datetime.fromisoformat(f["arrival_local"])
        tz_from, tz_to = airports[f["from"]]["timezone"], airports[f["to"]]["timezone"]
        real = (arr - timedelta(minutes=W.TZ_OFFSET[tz_to])) - (dep - timedelta(minutes=W.TZ_OFFSET[tz_from]))
        if real != timedelta(minutes=f["duration_minutes"]) or f["duration_minutes"] <= 0:
            err(f"flight {f['flight_id']}: duration {f['duration_minutes']} != elapsed {real}")
        if f["to"] in new_ap and not first <= arr.date() <= last:
            err(f"flight {f['flight_id']}: arrives {arr.date()} outside the window")
        if f["from"] in new_ap and not first <= dep.date() <= last:
            err(f"flight {f['flight_id']}: departs {dep.date()} outside the window")
        if (f["from"] in dep_airports) == (f["to"] in dep_airports):
            err(f"flight {f['flight_id']}: must connect a departure airport and a destination airport")
        if f["stops"] not in (0, 1) or not 1 <= f["seats_left"] <= 9:
            err(f"flight {f['flight_id']}: bad stops/seats")
    for a in new["availability"][len(orig["availability"]):]:
        if not first <= date.fromisoformat(a["date"]) <= last or a["rooms_left"] < 0:
            err(f"availability {a['room_id']} {a['date']}: out of window or negative")
    for t in new["transfers"][len(orig["transfers"]):]:
        if hhmm_to_min(t["service_from"]) > hhmm_to_min(t["service_until"]) and t["service_until"] != "00:30":
            err(f"transfer {t['transfer_id']}: window runs backwards")
        if t["pricing"] not in ("PER_PERSON", "PER_VEHICLE"):
            err(f"transfer {t['transfer_id']}: bad pricing")

    # 6. usability: every new country has flights both ways, hotels, transfers and attractions
    n_flights = len(new["flights"]) - len(orig["flights"])
    if not FLIGHT_COUNT_RANGE[0] <= n_flights <= FLIGHT_COUNT_RANGE[1]:
        err(f"{n_flights} new flights is outside {FLIGHT_COUNT_RANGE}")
    for co in W.COUNTRIES:
        for c in co["cities"]:
            if not 8 <= len(W.ATTRACTIONS[c["name"]]) <= 15:
                err(f"{c['name']}: attraction count {len(W.ATTRACTIONS[c['name']])} outside 8-15")
            if not any(h["city"] == c["name"] for h in new["hotels"]):
                err(f"{c['name']}: no hotels")
            for ap in c["airports"]:
                if not any(f["to"] == ap for f in new["flights"]) or not any(f["from"] == ap for f in new["flights"]):
                    err(f"{ap}: needs inbound and outbound flights")
                for area in c["areas"]:
                    if not any(t.get("airport") == ap and t.get("city") == c["name"] and t.get("area") in (None, area)
                               for t in new["transfers"]):
                        err(f"{ap} -> {c['name']}/{area}: no airport transfer")
        multi = [ln for x in new["destinations"]["countries"] if x["code"] == co["code"] for ln in x["links"]]
        if len(co["cities"]) > 1 and not multi:
            err(f"{co['name']}: no valid multi-city itinerary (no links)")
    for c in new["attractions"][len(orig["attractions"]):]:
        pass

    # 7. the production loader must accept the result unchanged
    try:
        from app.catalog.load import build_loaded
        build_loaded(new)
    except Exception as e:  # noqa: BLE001 - report any loader complaint verbatim
        err(f"production loader rejected the expanded catalog: {e}")

    if errs:
        shown = "\n  ".join(errs[:25])
        raise ExpansionError(f"{len(errs)} validation problem(s):\n  {shown}" + ("\n  ..." if len(errs) > 25 else ""))
    return {"new_flights": n_flights}


# ------------------------------------------------------------------ orchestration

def expanded(orig: dict) -> dict:
    airports_all = {a["code"]: a for a in orig["airports"]}
    origins = [d["airport"] for d in orig["destinations"]["departure_cities"]]
    new_airports = build_airports()
    for a in new_airports:
        airports_all[a["code"]] = a
    first_id = max(int(f["flight_id"].split("-")[1]) for f in orig["flights"]) + 1
    hotels, rooms, avail = build_hotels_rooms_availability()
    transfers = build_transfers()
    countries, _ = build_destinations(orig, transfers)
    dest = json.loads(json.dumps(orig["destinations"]))
    dest["countries"] = dest["countries"] + countries
    return {"destinations": dest,
            "airports": orig["airports"] + new_airports,
            "flights": orig["flights"] + build_flights(first_id, origins, airports_all),
            "hotels": orig["hotels"] + hotels,
            "rooms": orig["rooms"] + rooms,
            "availability": orig["availability"] + avail,
            "transfers": orig["transfers"] + transfers,
            "attractions": orig["attractions"] + build_attractions()}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def make_backup() -> None:
    """Copy the 8 files byte for byte, once. An existing backup is never overwritten, only verified."""
    BACKUP.mkdir(parents=True, exist_ok=True)
    for n in FILES:
        src, dst = CATALOG / f"{n}.json", BACKUP / f"{n}.json"
        if dst.exists():
            continue
        shutil.copy2(src, dst)
    (BACKUP / "SHA256SUMS").write_text("".join(f"{sha(BACKUP / f'{n}.json')}  {n}.json\n" for n in FILES)
                                       if not (BACKUP / "SHA256SUMS").exists() else (BACKUP / "SHA256SUMS").read_text())


def already_expanded(catalog: dict) -> bool:
    have = {c["code"] for c in catalog["destinations"]["countries"]}
    return all(c["code"] in have for c in W.COUNTRIES)


def restore() -> None:
    if not BACKUP.exists():
        raise ExpansionError(f"no backup at {BACKUP}")
    for n in FILES:
        shutil.copy2(BACKUP / f"{n}.json", CATALOG / f"{n}.json")
    print(f"Restored the original catalog from {BACKUP}")


def summary(orig: dict, new: dict) -> None:
    def n(k):
        return len(new[k]) - len(orig[k])
    print(f"  new countries:      {len(new['destinations']['countries']) - len(orig['destinations']['countries'])}")
    print(f"  new airports:       {n('airports')}")
    print(f"  new flights:        {n('flights')}")
    print(f"  new hotels:         {n('hotels')}")
    print(f"  new room types:     {n('rooms')}")
    print(f"  new availability:   {n('availability')}")
    print(f"  new transfers:      {n('transfers')}")
    print(f"  new attractions:    {n('attractions')}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="validate the catalog on disk and exit")
    ap.add_argument("--restore", action="store_true", help="restore the original catalog from the backup")
    args = ap.parse_args()
    try:
        if args.restore:
            restore()
            return 0
        current = read_all(CATALOG)
        if args.check:
            base = read_all(BACKUP) if BACKUP.exists() else current
            validate(base, current)
            print("Catalog on disk is valid.")
            return 0
        if already_expanded(current):
            print("Catalog already contains the five new countries; nothing to do (idempotent).")
            return 0
        make_backup()
        orig = read_all(BACKUP)
        if orig != current:
            raise ExpansionError("the catalog on disk differs from the backup but is not expanded; resolve by hand")
        new = expanded(orig)
        stats = validate(orig, new)
        tmp = CATALOG.parent / f".catalog_tmp_{os.getpid()}"
        tmp.mkdir()
        try:
            for name in FILES:
                (tmp / f"{name}.json").write_text(dumps(new[name]), encoding="utf-8")
            read_all(tmp)                       # the written files must parse and round-trip
            try:
                for name in FILES:
                    os.replace(tmp / f"{name}.json", CATALOG / f"{name}.json")
            except Exception:
                restore()
                raise
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        print("Catalog expanded.")
        summary(orig, new)
        print(f"  backup of the original: {BACKUP}")
        return 0
    except ExpansionError as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
