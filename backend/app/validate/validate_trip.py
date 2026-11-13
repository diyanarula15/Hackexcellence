"""Independent full-package validator for the shared trip format (DATA_DICTIONARY.md section 4).

It never trusts client values for prices, durations, capacity or availability: everything is
re-derived from the catalog. It shares only the pure rule predicates in app/rules with the planner.
"""
import re
from datetime import date, datetime, timedelta

from app.lib.time import parse_date, parse_dt, in_window
from app.rules import pricing
from app.rules.attractions import check_attractions
from app.rules.common import EDITED, INITIAL, Busy, FlightSel, Party, Stay, TransferSel, Violation, Visit
from app.rules.flights import check_flights, classify_flights
from app.rules.hotels import check_hotels
from app.rules.intercity import check_intercity
from app.rules.plan import check_city_plan
from app.rules.request import check_request
from app.rules.transfers import check_airport_transfers

ITEM_TYPES = ("flight", "hotel", "transfer", "attraction")
STATUSES = ("PLANNED", "BOOKED")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$")
_REF = re.compile(r"^\d{10}$")


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _valid_date(s) -> bool:
    if not isinstance(s, str) or not _DATE.match(s):
        return False
    try:
        date.fromisoformat(s)
        return True
    except ValueError:
        return False


def _valid_dt(s) -> bool:
    if not isinstance(s, str) or not _DT.match(s):
        return False
    try:
        datetime.fromisoformat(s)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------- 1. schema

def check_schema(trip) -> list[Violation]:
    v: list[Violation] = []
    S = lambda msg, iid=None: v.append(Violation("R-SCHEMA-1" if iid is None else "R-SCHEMA-2", msg, iid))
    if not isinstance(trip, dict):
        return [Violation("R-SCHEMA-1", "Trip must be a JSON object.")]

    if not isinstance(trip.get("trip_id"), str):
        S("trip_id must be a string.")
    tr = trip.get("traveler")
    if not isinstance(tr, dict):
        S("traveler must be an object.")
    else:
        if not isinstance(tr.get("home_airport"), str):
            S("traveler.home_airport must be a string.")
        if not _is_int(tr.get("adults")):
            S("traveler.adults must be an integer.")
        ages = tr.get("child_ages")
        if not isinstance(ages, list) or not all(_is_int(a) for a in ages):
            S("traveler.child_ages must be a list of integers.")
        elif not _is_int(tr.get("children")) or tr["children"] != len(ages):
            v.append(Violation("R-SCHEMA-5", "traveler.children must equal the number of child_ages."))
    for k in ("start_date", "end_date"):
        if not _valid_date(trip.get(k)):
            S(f"{k} must be a date YYYY-MM-DD.")
    if not isinstance(trip.get("country"), str):
        S("country must be a string.")
    for k in ("budget_inr", "total_inr"):
        if not _is_num(trip.get(k)):
            S(f"{k} must be a number.")
    items = trip.get("items")
    if not isinstance(items, list) or not items:
        S("items must be a non-empty list.")
        return v

    seen: set[str] = set()
    for n, it in enumerate(items):
        if not isinstance(it, dict):
            S(f"items[{n}] must be an object.")
            continue
        iid = it.get("item_id")
        if not isinstance(iid, str) or not iid:
            S(f"items[{n}].item_id must be a non-empty string.")
            iid = f"items[{n}]"
        elif iid in seen:
            v.append(Violation("R-SCHEMA-3", f"item_id {iid} is used more than once.", iid))
        seen.add(iid)
        E = lambda msg: S(f"Item {iid}: {msg}", iid)
        t = it.get("type")
        if t not in ITEM_TYPES:
            E(f"type must be one of {list(ITEM_TYPES)}.")
        for k in ("name", "city", "catalog_id"):
            if not isinstance(it.get(k), str):
                E(f"{k} must be a string.")
        if it.get("status") not in STATUSES:
            E(f"status must be one of {list(STATUSES)}.")
        if not _is_int(it.get("quantity")):
            E("quantity must be an integer.")
        if not _is_num(it.get("price_inr")):
            E("price_inr must be a number.")
        if it.get("sources") != []:
            E("sources must be an empty list.")
        if "warnings" in it and not (isinstance(it["warnings"], list)
                                     and all(isinstance(w, str) for w in it["warnings"])):
            E("warnings must be a list of strings.")
        if "booking" in it and it["booking"] is not None and not isinstance(it["booking"], dict):
            E("booking must be an object or null.")
        rid = it.get("room_id")
        if t == "hotel" and not isinstance(rid, str):
            E("hotel items need a room_id string.")
        if t in ("flight", "transfer", "attraction") and rid is not None:
            E("room_id must be null for non-hotel items.")
        st, en = it.get("start"), it.get("end")
        if t == "hotel":
            if not _valid_date(st) or not _valid_date(en):
                E("hotel start and end must be dates YYYY-MM-DD.")
        elif t in ("flight", "attraction"):
            if not _valid_dt(st) or not _valid_dt(en):
                E("start and end must be local date-times YYYY-MM-DDTHH:MM.")
        elif t == "transfer":
            if not _valid_dt(st) or not (en is None or _valid_dt(en)):
                E("transfer start must be a local date-time; end a date-time or null.")
    return v


# ---------------------------------------------------------------- helpers

def _country(trip, data) -> dict | None:
    want = trip["country"].strip().lower()
    for co in data.catalog.destinations["countries"]:
        if want in (co["code"].lower(), co["name"].lower()):
            return co
    return None


def _booking_checks(items) -> list[Violation]:
    v: list[Violation] = []
    statuses = {it["status"] for it in items}
    if len(statuses) > 1:
        v.append(Violation("R-BOOK-2", "All items must share one status (PLANNED or BOOKED)."))
    refs = set()
    for it in items:
        b = it.get("booking")
        if it["status"] == "BOOKED":
            ref = b.get("reference") if isinstance(b, dict) else None
            if not isinstance(ref, str) or not _REF.match(ref):
                v.append(Violation("R-BOOK-1", f"Item {it['item_id']}: a BOOKED item needs booking.reference "
                                               "as a 10-digit string.", it["item_id"]))
            else:
                refs.add(ref)
        elif b is not None:
            v.append(Violation("R-BOOK-1", f"Item {it['item_id']}: a PLANNED item must have booking null.",
                               it["item_id"]))
    if len(refs) > 1:
        v.append(Violation("R-BOOK-2", "BOOKED items carry different reservation numbers."))
    return v


# ---------------------------------------------------------------- 2. full validation

def validate_trip(trip: dict, catalog, mode: str = INITIAL) -> list[Violation]:
    """Validate a complete exported trip. `catalog` is the Loaded catalog from load_catalog()."""
    if mode not in (INITIAL, EDITED):
        raise ValueError(f"mode must be {INITIAL!r} or {EDITED!r}")
    data, ix = catalog, catalog.indexes

    schema = check_schema(trip)
    if schema:
        return schema

    v: list[Violation] = []
    tr = trip["traveler"]
    party = Party(tr["adults"], tuple(tr["child_ages"]))
    start_date, end_date = parse_date(trip["start_date"]), parse_date(trip["end_date"])
    nights = (end_date - start_date).days

    v += check_request({
        "departure_airport": tr["home_airport"], "destination_country": trip["country"],
        "start_date": trip["start_date"], "nights": nights, "adults": tr["adults"],
        "children_ages": tr["child_ages"], "budget": trip["budget_inr"]}, data)
    co = _country(trip, data)
    v += _booking_checks(trip["items"])

    # Known catalog ids only go further; unknown ones are reported once here.
    lookup = {"flight": ix.flights_by_id, "hotel": ix.hotels_by_id,
              "transfer": ix.transfers_by_id, "attraction": ix.attractions_by_id}
    items = []
    for it in trip["items"]:
        if it["catalog_id"] not in lookup[it["type"]]:
            v.append(Violation("R-ID-1", f"Item {it['item_id']}: {it['type']} {it['catalog_id']} "
                                         "is not in the catalog.", it["item_id"]))
        else:
            items.append(it)
    if co is None:
        return v  # nothing below can be judged without the destination country

    # ---- reconstruct selections
    flights = [FlightSel(it["item_id"], it["catalog_id"], it["start"][:16], it["end"][:16])
               for it in items if it["type"] == "flight"]
    stays = sorted((Stay(it["item_id"], it["catalog_id"], it["room_id"], it["city"],
                         parse_date(it["start"]), parse_date(it["end"]), it["quantity"])
                    for it in items if it["type"] == "hotel"), key=lambda s: (s.check_in, s.item_id))
    visits = [Visit(it["item_id"], it["catalog_id"], parse_dt(it["start"]), parse_dt(it["end"]))
              for it in items if it["type"] == "attraction"]
    arrival_tr, departure_tr, moves, city_tr = [], [], [], []
    for it in items:
        if it["type"] != "transfer":
            continue
        rec = ix.transfers_by_id[it["catalog_id"]]
        sel = TransferSel(it["item_id"], it["catalog_id"], parse_dt(it["start"]))
        if rec.get("airport"):
            if sel.pickup.date() == end_date:
                departure_tr.append(sel)
            elif sel.pickup.date() in (start_date, start_date + timedelta(days=1)):
                arrival_tr.append(sel)
            else:
                v.append(Violation("R-ATR-1", f"Airport transfer {it['item_id']} is neither on the arrival "
                                              "nor on the departure day.", it["item_id"]))
        elif rec.get("from_city") or rec.get("to_city"):
            moves.append(sel)
        else:
            city_tr.append((sel, rec))

    hotel_city = lambda s: ix.hotels_by_id[s.hotel_id]["city"]
    first_city = hotel_city(stays[0]) if stays else None
    last_city = hotel_city(stays[-1]) if stays else None

    # ---- rule groups
    v += check_city_plan(stays, co["code"], start_date, nights, data)
    v += check_flights(flights, tr["home_airport"], co["code"], first_city, last_city,
                       start_date, end_date, party, data)
    v += check_hotels(stays, party, data)

    out, inb, _ = classify_flights(flights, co["code"], data)
    outbound = out[0][1] if len(out) == 1 else None
    inbound = inb[0][1] if len(inb) == 1 else None
    first_hotel = ix.hotels_by_id[stays[0].hotel_id] if stays else None
    last_hotel = ix.hotels_by_id[stays[-1].hotel_id] if stays else None
    v += check_airport_transfers(arrival_tr, departure_tr, outbound, inbound, first_hotel, last_hotel, data)
    v += check_intercity(moves, stays, data)

    # Optional city taxis / buses: must serve a planned city, run in service hours.
    plan_cities = {hotel_city(s) for s in stays}
    for sel, rec in city_tr:
        if rec.get("city") not in plan_cities:
            v.append(Violation("R-TRN-2", f"City transfer {sel.transfer_id} is not in a city of the plan.",
                               sel.item_id))
        if not in_window(sel.pickup, rec["service_from"], rec["service_until"]):
            v.append(Violation("R-TRN-3", f"City transfer {sel.transfer_id} pickup "
                                          f"{sel.pickup:%Y-%m-%d %H:%M} is outside its service hours.",
                               sel.item_id))

    # Transfer end, when given, must equal pickup + catalog duration.
    busy: list[Busy] = []
    for it in items:
        if it["type"] != "transfer":
            continue
        rec = ix.transfers_by_id[it["catalog_id"]]
        p = parse_dt(it["start"])
        arrive = p + timedelta(minutes=rec["duration_minutes"])
        busy.append(Busy(p, arrive, it["item_id"], rec["name"]))
        if it["end"] is not None and parse_dt(it["end"]) != arrive:
            v.append(Violation("R-TRN-1", f"Transfer {it['item_id']}: end {it['end']} does not equal pickup + "
                                          f"{rec['duration_minutes']} min.", it["item_id"]))

    # When the traveler reaches the city on the arrival day and on each city-change day.
    ready_at: dict[date, datetime] = {}
    if len(arrival_tr) == 1:
        rec = ix.transfers_by_id[arrival_tr[0].transfer_id]
        ready_at[start_date] = arrival_tr[0].pickup + timedelta(minutes=rec["duration_minutes"])
        # nothing can be visited before the traveler reaches the first hotel, even if that is
        # after midnight on the following day
        busy.append(Busy(datetime.min, ready_at[start_date], arrival_tr[0].item_id, "the arrival transfer"))
    for a, b in zip(stays, stays[1:]):
        for m in moves:
            rec = ix.transfers_by_id[m.transfer_id]
            if (rec.get("from_city"), rec.get("to_city")) == (hotel_city(a), hotel_city(b)) \
                    and m.pickup.date() == a.check_out:
                ready_at[a.check_out] = m.pickup + timedelta(minutes=rec["duration_minutes"])
    v += check_attractions(visits, stays, start_date, end_date, ready_at, busy, mode, data)

    # ---- prices: recomputed from the catalog, never trusted
    stay_by_item = {s.item_id: s for s in stays}
    for it in items:
        rec = lookup[it["type"]][it["catalog_id"]]
        if it["type"] == "flight":
            exp = pricing.flight_price(rec, party)
        elif it["type"] == "hotel":
            room = ix.rooms_by_id.get(it["room_id"])
            if room is None:
                continue  # reported by R-HTL-3
            s = stay_by_item[it["item_id"]]
            exp = pricing.hotel_price(room, it["quantity"], max(s.nights, 0))
        elif it["type"] == "transfer":
            exp = pricing.transfer_price(rec, party)
        else:
            exp = pricing.attraction_price(rec, party)
        v += pricing.check_item_price(it["item_id"], exp, it["quantity"], it["price_inr"])
    v += pricing.check_total(sum(it["price_inr"] for it in trip["items"]), trip["total_inr"])
    return v
