"""Tiny same-schema catalogs for planner tests, plus an independent brute-force oracle.

World: a mutable description of a miniature dataset (home airport HOM in India, destination country
"ZZ"). `world.loaded()` validates and indexes it with the production loader. Nothing here touches
the real catalog files.

oracle_minimum(): enumerates EVERY discrete package (city plan x flights x hotel/room/room-count x
transfer services x attraction choice) with its own code - it does not call the planner or the
candidate functions - prices each with its own arithmetic, and lets the Phase 2 validator decide
validity. Its minimum is the ground truth the planner's MINIMUM_COST result is compared with.
Times are canonical (earliest allowed pickup, latest allowed airport run, first usable slot), so
keep service windows generous in worlds that are fed to the oracle.
"""
import itertools
import math
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from app.catalog.load import build_loaded
from app.export.to_trip import to_trip_json
from app.lib.time import at, in_window, on_slot, parse_dt
from app.validate.validate_trip import validate_trip

ALL_DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
INR = lambda n: {"amount": n, "currency": "INR"}
WINDOW_DAYS = [date(2027, 4, d) for d in range(1, 21)]


class World:
    def __init__(self, cities=("X", "Y"), links=(("X", "Y"),), min_nights=3, max_nights=10, per_city=2):
        self.cities = {c: [f"A{c}"] for c in cities}         # city -> airports serving it
        self.links = {pair: [] for pair in links}             # (from, to) -> transfer ids
        self.rules = {"min_nights": min_nights, "max_nights": max_nights, "min_nights_per_city": per_city,
                      "data_window": {"first_night": "2027-04-01", "last_departure": "2027-04-20"}}
        self.airports = [{"code": "HOM", "name": "Home", "city": "Hometown", "country": "IN",
                          "timezone": "Asia/Kolkata", "lat": 0, "lng": 0}]
        for c in cities:
            self.airports.append({"code": f"A{c}", "name": f"{c} Airport", "city": c, "country": "ZZ",
                                  "timezone": "Asia/Tokyo", "lat": 0, "lng": 0, "serves_cities": [c]})
        self.flights, self.hotels, self.rooms, self.availability = [], [], [], {}
        self.transfers, self.attractions = [], []

    # ---- builders (each returns the record so a test can tweak it)
    def flight(self, fid, frm, to, dep, arr, price, seats=9):
        rec = {"flight_id": fid, "airline": "Synth", "flight_number": fid, "from": frm, "to": to,
               "departure_local": dep, "arrival_local": arr, "stops": 0, "duration_minutes": 300,
               "price_per_seat": INR(price), "seats_left": seats, "cabin": "ECONOMY"}
        self.flights.append(rec)
        return rec

    def hotel(self, hid, city, area="Centre", stars=3):
        rec = {"hotel_id": hid, "name": hid, "aliases": [], "city": city, "area": area, "lat": 0, "lng": 0,
               "rating": 8.0, "stars": stars, "check_in_from": "15:00", "check_out_until": "11:00",
               "family_friendly": True, "image": None}
        self.hotels.append(rec)
        return rec

    def room(self, rid, hotel_id, price, max_adults=2, max_children=2, rooms_left=5):
        rec = {"room_id": rid, "hotel_id": hotel_id, "room_type": "FAMILY", "name": rid,
               "max_adults": max_adults, "max_children": max_children, "price_per_night": INR(price),
               "refundable": True}
        self.rooms.append(rec)
        for d in WINDOW_DAYS:
            self.availability[(rid, d.isoformat())] = rooms_left
        return rec

    def set_rooms_left(self, rid, day: str, n):          # n=None deletes the record
        if n is None:
            self.availability.pop((rid, day), None)
        else:
            self.availability[(rid, day)] = n

    def airport_transfer(self, tid, airport, city, price, area=None, pricing="PER_VEHICLE",
                         window=("00:00", "24:00"), duration=30, max_passengers=4, child_price=None):
        rec = {"transfer_id": tid, "type": "AIRPORT_TAXI", "name": tid, "airport": airport, "city": city,
               "area": area, "from_point": airport, "to_point": city, "max_passengers": max_passengers,
               "service_from": window[0], "service_until": window[1], "duration_minutes": duration,
               "pricing": pricing, "price": INR(price)}
        if child_price is not None:
            rec["child_price"] = INR(child_price)
        self.transfers.append(rec)
        return rec

    def intercity(self, tid, a, b, price, frequency=None, window=("00:00", "24:00"), duration=60,
                  pricing="PER_PERSON", child_price=None, max_passengers=99):
        rec = {"transfer_id": tid, "type": "TRAIN", "name": tid, "airport": None, "city": None, "area": None,
               "from_city": a, "to_city": b, "from_point": a, "to_point": b, "max_passengers": max_passengers,
               "service_from": window[0], "service_until": window[1], "duration_minutes": duration,
               "pricing": pricing, "price": INR(price)}
        if frequency:
            rec["frequency_minutes"] = frequency
        if child_price is not None:
            rec["child_price"] = INR(child_price)
        self.transfers.append(rec)
        self.links.setdefault((a, b), []).append(tid)
        return rec

    def attraction(self, aid, city, price, child_price=None, open_days=None, hours=("00:00", "24:00"),
                   minutes=60, closed_dates=None, child_friendly=True):
        rec = {"attraction_id": aid, "name": aid, "name_ja": None, "city": city, "category": "MUSEUM",
               "lat": 0, "lng": 0, "open_days": list(open_days or ALL_DAYS), "open_from": hours[0],
               "open_until": hours[1], "aliases": [], "visit_minutes": minutes, "child_friendly": child_friendly,
               "accessible": True, "price_per_person": INR(price), "image": None}
        if child_price is not None:
            rec["child_price"] = INR(child_price)
        if closed_dates:
            rec["closed_dates"] = list(closed_dates)
        self.attractions.append(rec)
        return rec

    # ---- output
    def raw(self) -> dict:
        return {
            "destinations": {
                "departure_cities": [{"airport": "HOM", "city": "Hometown"}],
                "countries": [{"code": "ZZ", "name": "Zedland", "timezone": "Asia/Tokyo",
                               "cities": [{"name": c, "airports": list(a)} for c, a in self.cities.items()],
                               "links": [{"from_city": a, "to_city": b, "transfer_ids": list(t)}
                                         for (a, b), t in self.links.items()]}],
                "rules": self.rules},
            "airports": self.airports, "flights": self.flights, "hotels": self.hotels, "rooms": self.rooms,
            "availability": [{"room_id": r, "date": d, "rooms_left": n}
                             for (r, d), n in sorted(self.availability.items())],
            "transfers": self.transfers, "attractions": self.attractions}

    def loaded(self):
        return build_loaded(self.raw())


def request(nights=3, start=date(2027, 4, 10), adults=2, children=(), budget=10 ** 9):
    return SimpleNamespace(departure_airport="HOM", destination_country="ZZ", start_date=start,
                           nights=nights, adults=adults, children_ages=list(children), budget=budget)


def simple_world(cities=("X",), links=(), **kw) -> World:
    """A minimal feasible single-city world: one flight each way, one hotel, one taxi, three
    attractions. Start date 2027-04-10; flights exist for trips of 3..6 nights."""
    w = World(cities=cities, links=links, **kw)
    c = cities[0]
    w.flight("F-IN", "HOM", f"A{c}", "2027-04-09T22:00:00", "2027-04-10T08:00:00", 1000)
    for n in range(3, 7):
        d = date(2027, 4, 10) + timedelta(days=n)
        w.flight(f"F-OUT-{n}", f"A{c}", "HOM", f"{d.isoformat()}T18:00:00", f"{d.isoformat()}T23:00:00", 1000)
    w.hotel("H1", c)
    w.room("R1", "H1", 500)
    w.airport_transfer("T-AIR", f"A{c}", c, 100)
    for i in range(1, 4):
        w.attraction(f"ATT-{c}-{i}", c, 10 * i)
    return w


# ---------------------------------------------------------------- independent oracle

def _plans(raw, nights):
    co = raw["destinations"]["countries"][0]
    per = raw["destinations"]["rules"]["min_nights_per_city"]
    cities = [c["name"] for c in co["cities"]]
    linked = {(l["from_city"], l["to_city"]) for l in co["links"]}
    for k in range(1, len(cities) + 1):
        for seq in itertools.permutations(cities, k):
            if any(pair not in linked for pair in zip(seq, seq[1:])):
                continue
            for split in itertools.product(range(per, nights + 1), repeat=k):
                if sum(split) == nights:
                    yield seq, split


def _vehicles_or_people(rec, adults, children):
    if rec["pricing"] == "PER_VEHICLE":
        q = math.ceil((adults + children) / rec["max_passengers"])
        return q, rec["price"]["amount"] * q
    child = rec["child_price"]["amount"] if "child_price" in rec else rec["price"]["amount"]
    return adults + children, adults * rec["price"]["amount"] + children * child


def oracle_minimum(world: World, req) -> tuple[int | None, int]:
    """(cheapest valid total or None, number of valid packages) by exhaustive enumeration."""
    raw, data = world.raw(), world.loaded()
    adults, children = req.adults, len(req.children_ages)
    n = adults + children
    start, end = req.start_date, req.start_date + timedelta(days=req.nights)
    serves = {a["code"]: a.get("serves_cities", []) for a in raw["airports"]}
    best, count = None, 0

    def first_ok(cands, rec):
        return next((t for t in cands if in_window(t, rec["service_from"], rec["service_until"])), None)

    for seq, split in _plans(raw, req.nights):
        stays, d = [], start
        for c, k in zip(seq, split):
            stays.append((c, d, d + timedelta(days=k)))
            d += timedelta(days=k)
        change_days = {s[1] for s in stays[1:]}
        full_days = [(c, day) for c, ci, co_ in stays
                     for day in (ci + timedelta(days=i) for i in range((co_ - ci).days))
                     if day != start and day not in change_days]
        ins = [f for f in raw["flights"] if f["from"] == "HOM" and seq[0] in serves.get(f["to"], [])]
        outs = [f for f in raw["flights"] if f["to"] == "HOM" and seq[-1] in serves.get(f["from"], [])]
        hotel_choices = []
        for c, ci, co_ in stays:
            opts = [(h, r, k) for h in raw["hotels"] if h["city"] == c
                    for r in raw["rooms"] if r["hotel_id"] == h["hotel_id"] for k in range(1, adults + 1)]
            hotel_choices.append(opts)
        leg_choices = []
        for (a, _, _), (b, day, _) in zip(stays, stays[1:]):
            ids = next((l["transfer_ids"] for l in raw["destinations"]["countries"][0]["links"]
                        if (l["from_city"], l["to_city"]) == (a, b)), [])
            opts = []
            for t in (t for t in raw["transfers"] if t["transfer_id"] in ids):
                slots = [at(day, "00:00") + timedelta(minutes=30 * i) for i in range(48)]
                ok = [s for s in slots if in_window(s, t["service_from"], t["service_until"])
                      and ("frequency_minutes" not in t
                           or on_slot(s, t["service_from"], t["service_until"], t["frequency_minutes"]))]
                if ok:
                    opts.append((t, ok[len(ok) // 2]))
            leg_choices.append(opts)
        by_city = {}
        for a in raw["attractions"]:
            by_city.setdefault(a["city"], []).append(a)
        attr_choices = [by_city.get(c, []) for c, _ in full_days]

        for fin, fout in itertools.product(ins, outs):
            landing, takeoff = parse_dt(fin["arrival_local"]), parse_dt(fout["departure_local"])
            for hsel in itertools.product(*hotel_choices):
                first_h, last_h = hsel[0][0], hsel[-1][0]
                arr_ts = [t for t in raw["transfers"] if t.get("airport") == fin["to"]]
                dep_ts = [t for t in raw["transfers"] if t.get("airport") == fout["from"]]
                for ta, td in itertools.product(arr_ts, dep_ts):
                    pa = first_ok([landing + timedelta(minutes=60), at(landing.date(), ta["service_from"]),
                                   at(landing.date() + timedelta(days=1), ta["service_from"])], ta)
                    deadline = takeoff - timedelta(minutes=180 + td["duration_minutes"])
                    pd = first_ok([deadline, at(takeoff.date(), td["service_until"]),
                                   at(takeoff.date(), td["service_from"])], td)
                    if pa is None or pd is None:
                        continue
                    for lsel in itertools.product(*leg_choices):
                        for asel in itertools.product(*attr_choices):
                            if len({a["attraction_id"] for a in asel}) != len(asel):
                                continue
                            items = [("flight", fin["flight_id"], None, parse_dt(fin["departure_local"]),
                                      landing, n, fin["price_per_seat"]["amount"] * n)]
                            q, p = _vehicles_or_people(ta, adults, children)
                            items.append(("transfer", ta["transfer_id"], None, pa,
                                          pa + timedelta(minutes=ta["duration_minutes"]), q, p))
                            ai = 0
                            for i, ((c, ci, co_), (h, r, k)) in enumerate(zip(stays, hsel)):
                                items.append(("hotel", h["hotel_id"], r["room_id"], ci, co_, k,
                                              r["price_per_night"]["amount"] * k * (co_ - ci).days))
                                while ai < len(full_days) and full_days[ai][0] == c and ci <= full_days[ai][1] < co_:
                                    a, day = asel[ai], full_days[ai][1]
                                    st = max(at(day, a["open_from"]), at(day, "10:00"))
                                    child = (a["child_price"]["amount"] if "child_price" in a
                                             else a["price_per_person"]["amount"])
                                    items.append(("attraction", a["attraction_id"], None, st,
                                                  st + timedelta(minutes=a["visit_minutes"]), n,
                                                  adults * a["price_per_person"]["amount"] + children * child))
                                    ai += 1
                                if i < len(lsel):
                                    t, s = lsel[i]
                                    q, p = _vehicles_or_people(t, adults, children)
                                    items.append(("transfer", t["transfer_id"], None, s,
                                                  s + timedelta(minutes=t["duration_minutes"]), q, p))
                            q, p = _vehicles_or_people(td, adults, children)
                            items.append(("transfer", td["transfer_id"], None, pd,
                                          pd + timedelta(minutes=td["duration_minutes"]), q, p))
                            items.append(("flight", fout["flight_id"], None, takeoff,
                                          parse_dt(fout["arrival_local"]), n, fout["price_per_seat"]["amount"] * n))
                            pkg = {"trip_id": "oracle", "traveler": {"name": "O", "home_airport": "HOM",
                                                                     "adults": adults,
                                                                     "child_ages": list(req.children_ages)},
                                   "country": "Zedland", "start_date": start, "end_date": end,
                                   "budget_inr": req.budget,
                                   "items": [{"type": t, "catalog_id": cid, "room_id": rid, "start": s, "end": e,
                                              "quantity": q, "price_inr": p} for t, cid, rid, s, e, q, p in items]}
                            trip = to_trip_json(pkg, data)
                            if not validate_trip(trip, data, "INITIAL"):
                                count += 1
                                if best is None or trip["total_inr"] < best:
                                    best = trip["total_inr"]
    return best, count
