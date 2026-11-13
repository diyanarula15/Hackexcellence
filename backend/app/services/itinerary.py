"""Display presenter for a saved package: items, the day-by-day timeline, prices and the budget.

It formats a package that the planner already chose and validated. It makes no travel decision,
computes no new price and never changes the package; names and details come from the catalog.

Item ids are stable and are the same component ids engine/repair.py uses, so Phase 5 change
requests can target them:
  flight:arrival · flight:return · stay:<city>:<in>:<out> · leg:arrival · leg:departure ·
  leg:<from>><to>:<date> · visit:<attraction id>

Time zones: every time is local to its place (catalog convention). Events inside the destination
country share one zone, so they are sorted by time. The two flights are placed by structure
instead (outbound flight first on the arrival day, flight home last on the departure day): each
flight's departure and arrival are in different zones and must not be compared with the rest.
"""

from datetime import date
from itertools import count

from app.catalog.load import load_catalog
from app.engine.model import FlightOption, HotelOption, Package, TransferOption, VisitOption
from app.engine.schedule import ARRIVAL, CHANGE, DEPARTURE, FULL, classify_days
from app.lib.money import amount
from app.lib.time import fmt_dt, weekday_code
from app.services.photos import attraction_photo_url, hotel_photo_url

ARRIVAL_FLIGHT, RETURN_FLIGHT = "flight:arrival", "flight:return"
DAY_TYPES = {ARRIVAL: "ARRIVAL", FULL: "FULL_DAY", CHANGE: "CITY_CHANGE", DEPARTURE: "DEPARTURE"}

# event kinds shown on the timeline
FLIGHT, TRANSFER, CHECK_IN, CHECK_OUT, ATTRACTION = (
    "FLIGHT",
    "TRANSFER",
    "CHECK_IN",
    "CHECK_OUT",
    "ATTRACTION",
)


def _price(rec: dict, key: str) -> int | None:
    return amount(rec[key]) if rec.get(key) is not None else None


# ------------------------------------------------------------------ items


def _airport(ix, code: str) -> dict:
    rec = ix.airports_by_code.get(code) or {}
    return {
        "code": code,
        "name": rec.get("name"),
        "city": rec.get("city"),
        "timezone": rec.get("timezone"),
    }


def _flight_item(item_id: str, f: FlightOption, ix) -> dict:
    rec = ix.flights_by_id.get(f.flight_id) or {}
    number = rec.get("flight_number") or f.flight_id
    to = _airport(ix, f.to_airport)
    return {
        "item_id": item_id,
        "type": "flight",
        "catalog_id": f.flight_id,
        "room_id": None,
        "name": f"{number} {f.from_airport} to {f.to_airport}",
        "city": to["city"],
        "start": fmt_dt(f.departure),
        "end": fmt_dt(f.arrival),
        "quantity": f.quantity,
        "price_inr": f.price,
        "details": {
            "direction": "ARRIVAL" if item_id == ARRIVAL_FLIGHT else "RETURN",
            "airline": rec.get("airline"),
            "flight_number": number,
            "from": _airport(ix, f.from_airport),
            "to": to,
            "duration_minutes": rec.get("duration_minutes"),
            "stops": rec.get("stops"),
            "cabin": rec.get("cabin"),
            "seats": f.quantity,
            "price_per_seat_inr": _price(rec, "price_per_seat"),
        },
    }


def _hotel_item(h: HotelOption, ix) -> dict:
    hotel = ix.hotels_by_id.get(h.hotel_id) or {}
    room = ix.rooms_by_id.get(h.room_id) or {}
    return {
        "item_id": h.stay_id,
        "type": "hotel",
        "catalog_id": h.hotel_id,
        "room_id": h.room_id,
        "stay_id": h.stay_id,
        "name": hotel.get("name") or h.hotel_id,
        "city": h.city,
        "start": h.check_in.isoformat(),
        "end": h.check_out.isoformat(),
        "quantity": h.rooms,
        "price_inr": h.total_price,
        "details": {
            "area": h.area,
            "stars": hotel.get("stars"),
            "rating": hotel.get("rating"),
            "check_in_from": hotel.get("check_in_from"),
            "check_out_until": hotel.get("check_out_until"),
            "image_url": hotel_photo_url(hotel),
            "nights": (h.check_out - h.check_in).days,
            "rooms": h.rooms,
            "room": {
                "room_id": h.room_id,
                "name": room.get("name"),
                "room_type": room.get("room_type"),
                "max_adults": room.get("max_adults"),
                "max_children": room.get("max_children"),
                "price_per_night_inr": _price(room, "price_per_night"),
                "refundable": room.get("refundable"),
            },
        },
    }


def transfer_route(rec: dict, departure: bool) -> tuple[str, str | None, str | None]:
    """(name, from, to) as the traveler rides it. The catalog has one record per airport transfer,
    written airport -> hotels ("Narita limousine bus to Ueno", NRT -> Ueno area hotels); on the way
    home the same service runs hotels -> airport, so it reads "... from Ueno", Ueno area hotels -> NRT."""
    name = rec.get("name") or rec.get("transfer_id") or ""
    start, end = rec.get("from_point"), rec.get("to_point")
    if departure and rec.get("airport"):
        head, sep, area = name.rpartition(" to ")
        if sep:
            name = f"{head} from {area}"
        start, end = end, start
    return name, start, end


def _transfer_item(t: TransferOption, role: str, ix) -> dict:
    rec = ix.transfers_by_id.get(t.transfer_id) or {}
    per_vehicle = rec.get("pricing") == "PER_VEHICLE"
    name, start, end = transfer_route(rec, role == "AIRPORT_DEPARTURE")
    return {
        "item_id": t.leg_id,
        "type": "transfer",
        "catalog_id": t.transfer_id,
        "room_id": None,
        "leg_id": t.leg_id,
        "name": name or t.transfer_id,
        "city": rec.get("city") or rec.get("to_city"),
        "start": fmt_dt(t.pickup),
        "end": fmt_dt(t.arrive),
        "quantity": t.quantity,
        "price_inr": t.price,
        "details": {
            "role": role,
            "mode": rec.get("type"),
            "from_point": start,
            "to_point": end,
            "from_city": rec.get("from_city"),
            "to_city": rec.get("to_city"),
            "duration_minutes": rec.get("duration_minutes"),
            "pricing": rec.get("pricing"),
            "unit": "vehicles" if per_vehicle else "tickets",
            "max_passengers": rec.get("max_passengers"),
            "unit_price_inr": _price(rec, "price"),
            "child_price_inr": _price(rec, "child_price"),
        },
    }


def _visit_item(v: VisitOption, ix) -> dict:
    rec = ix.attractions_by_id.get(v.attraction_id) or {}
    return {
        "item_id": f"visit:{v.attraction_id}",
        "type": "attraction",
        "catalog_id": v.attraction_id,
        "room_id": None,
        "name": rec.get("name") or v.attraction_id,
        "city": rec.get("city"),
        "start": fmt_dt(v.start),
        "end": fmt_dt(v.end),
        "quantity": v.quantity,
        "price_inr": v.price,
        "details": {
            "category": rec.get("category"),
            "visit_minutes": rec.get("visit_minutes"),
            "open_from": rec.get("open_from"),
            "open_until": rec.get("open_until"),
            "child_friendly": rec.get("child_friendly"),
            "image_url": attraction_photo_url(rec),
            "tickets": v.quantity,
            "price_per_person_inr": _price(rec, "price_per_person"),
            "child_price_inr": _price(rec, "child_price"),
        },
    }


def _items_by_id(p: Package, ix) -> dict[str, dict]:
    items = [
        _flight_item(ARRIVAL_FLIGHT, p.arrival_flight, ix),
        _flight_item(RETURN_FLIGHT, p.return_flight, ix),
        _transfer_item(p.arrival_transfer, "AIRPORT_ARRIVAL", ix),
        _transfer_item(p.departure_transfer, "AIRPORT_DEPARTURE", ix),
        *(_transfer_item(t, "INTERCITY", ix) for t in p.intercity),
        *(_hotel_item(h, ix) for h in p.hotels),
        *(_visit_item(v, ix) for v in p.visits),
    ]
    return {i["item_id"]: i for i in items}


# ------------------------------------------------------------------ timeline


def _event(item: dict, kind: str) -> dict:
    ev = {
        "item_id": item["item_id"],
        "catalog_id": item["catalog_id"],
        "type": item["type"],
        "kind": kind,
        "name": item["name"],
        "city": item["city"],
        "start": item["start"],
        "end": item["end"],
        "quantity": item["quantity"],
        "price_inr": item["price_inr"],
        "display_details": item["details"],
    }
    if (
        kind == CHECK_OUT
    ):  # same stay item, shown again on the day the traveler leaves; priced once (check-in)
        ev.update(start=item["end"], end=None, price_inr=None)
    return ev


def _timeline(p: Package, items: dict[str, dict]) -> list[dict]:
    days = classify_days(p.plan)
    first, last = days[0].day, days[-1].day
    local: dict[date, list] = {d.day: [] for d in days}
    seq = count()

    def add(day: date, when, rank: int, event: dict):
        day = min(max(day, first), last)  # defensive: never drop an event outside the trip window
        local[day].append(((when, rank, next(seq)), event))

    # in-country events; rank orders events at the same minute: check-out, transfer, check-in, visit
    incoming = [p.arrival_transfer, *p.intercity]  # brings the traveler to stay i
    outgoing = [*p.intercity, p.departure_transfer]  # takes the traveler away from stay i
    for t in (p.arrival_transfer, *p.intercity, p.departure_transfer):
        add(t.pickup.date(), t.pickup, 1, _event(items[t.leg_id], TRANSFER))
    for i, h in enumerate(p.hotels):
        add(h.check_in, incoming[i].arrive, 2, _event(items[h.stay_id], CHECK_IN))
        add(outgoing[i].pickup.date(), outgoing[i].pickup, 0, _event(items[h.stay_id], CHECK_OUT))
    for v in p.visits:
        add(v.start.date(), v.start, 3, _event(items[f"visit:{v.attraction_id}"], ATTRACTION))

    out = []
    for n, d in enumerate(days, start=1):
        events = [e for _, e in sorted(local[d.day], key=lambda ke: ke[0])]
        if d.kind == ARRIVAL:
            events.insert(0, _event(items[ARRIVAL_FLIGHT], FLIGHT))
        if d.kind == DEPARTURE:
            events.append(_event(items[RETURN_FLIGHT], FLIGHT))
        night = next((h for h in p.hotels if h.check_in <= d.day < h.check_out), None)
        before = next((h for h in p.hotels if h.check_out == d.day), None)
        out.append(
            {
                "date": d.day.isoformat(),
                "day_number": n,
                "weekday": weekday_code(d.day),
                "city": d.city,
                "from_city": before.city if d.kind == CHANGE and before else None,
                "day_type": DAY_TYPES[d.kind],
                "overnight": {"item_id": night.stay_id, "name": items[night.stay_id]["name"]}
                if night
                else None,
                "events": events,
            }
        )
    return out


def build_day_timeline(package: Package, catalog=None) -> list[dict]:
    """Every day from the holiday start date to the return day, events in itinerary order."""
    ix = (catalog or load_catalog()).indexes
    return _timeline(package, _items_by_id(package, ix))


# ------------------------------------------------------------------ prices and budget


def price_breakdown(p: Package) -> dict:
    """Itemized totals from the saved items. Sums to Package.total by construction (checked)."""
    parts = {
        "flights": p.arrival_flight.price + p.return_flight.price,
        "hotels": sum(h.total_price for h in p.hotels),
        "airport_transfers": p.arrival_transfer.price + p.departure_transfer.price,
        "intercity_transfers": sum(t.price for t in p.intercity),
        "attractions": sum(v.price for v in p.visits),
    }
    total = sum(parts.values())
    if total != p.total:
        raise ValueError(f"price breakdown {total} does not match package total {p.total}")
    return {**parts, "total_inr": total}


def budget_summary(p: Package) -> dict:
    """Never a negative remaining amount: an overspend is reported as over_budget_inr."""
    total, budget = p.total, p.budget
    return {
        "budget_inr": budget,
        "total_inr": total,
        "remaining_inr": max(budget - total, 0),
        "over_budget_inr": max(total - budget, 0),
        "within_budget": total <= budget,
    }


# ------------------------------------------------------------------ whole package


def present_package(stored, catalog=None) -> dict:
    """The frontend view of a StoredPackage (app.repositories.packages)."""
    cat = catalog or load_catalog()
    p = stored.package
    items = _items_by_id(p, cat.indexes)
    days = _timeline(p, items)
    ordered = list(
        dict.fromkeys(e["item_id"] for d in days for e in d["events"])
    )  # first appearance
    if set(ordered) != set(items):
        raise ValueError("timeline does not show every package item")
    budget = budget_summary(p)
    home = next(
        (c for c in cat.catalog.destinations["departure_cities"] if c["airport"] == p.home_airport),
        {},
    )
    return {
        "id": stored.id,
        "package_id": stored.id,
        "trip_id": p.trip_id,
        "version": stored.version,
        "status": stored.status,
        "booking_reference": p.booking_reference,
        "validation_mode": stored.validation_mode,
        "created_at": stored.created_at,
        "updated_at": stored.updated_at,
        "country": p.country_name,
        "country_code": p.country_code,
        "departure": {"airport": p.home_airport, "city": home.get("city")},
        "travelers": {
            "adults": p.adults,
            "children": len(p.child_ages),
            "child_ages": list(p.child_ages),
            "total": p.adults + len(p.child_ages),
        },
        "start_date": p.plan.start_date.isoformat(),
        "end_date": p.plan.end_date.isoformat(),
        "nights": (p.plan.end_date - p.plan.start_date).days,
        "total_inr": stored.total_inr,
        "budget_inr": p.budget,
        "budget_remaining": budget["remaining_inr"],
        "city_plan": [
            {
                "stay_id": s.stay_id,
                "city": s.city,
                "check_in": s.check_in.isoformat(),
                "check_out": s.check_out.isoformat(),
                "nights": s.nights,
                "hotel_item_id": h.stay_id,
                "hotel_name": items[h.stay_id]["name"],
                "room_id": h.room_id,
            }
            for s, h in zip(p.plan.stays, p.hotels, strict=True)
        ],
        "items": [items[i] for i in ordered],
        "days": days,
        "pricing": price_breakdown(p),
        "budget": budget,
        "request": stored.request,
    }
