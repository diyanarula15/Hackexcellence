"""Export an internal package to the judge "shared trip format" (DATA_DICTIONARY section 4).

Input is a package dict (see to_trip_json). The input is never mutated.
"""
import re
from datetime import date, datetime

from app.catalog.load import load_catalog
from app.lib.time import fmt_dt

_TRIP_STATUSES = ("PLANNED", "BOOKED")
_REFERENCE_RE = re.compile(r"[0-9]{10}")


def _dt_out(v):
    """Local date-time -> "YYYY-MM-DDTHH:MM". Date-only strings pass through; None stays None."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return fmt_dt(v)
    if isinstance(v, date):
        return v.isoformat()
    s = str(v)
    if "T" in s:
        return s[:16]
    return s


def _date_out(v):
    """Date -> "YYYY-MM-DD". Date-times are cut to their date part; None stays None."""
    if v is None:
        return None
    if isinstance(v, date):  # also covers datetime
        return v.isoformat()[:10]
    return str(v)[:10]


def _indexes(data):
    """Accept a Loaded object (has .indexes) or an Indexes object; default to the catalog."""
    if data is None:
        data = load_catalog()
    return getattr(data, "indexes", data)


def _fill(item: dict, idx) -> tuple:
    """Return (name, city) for an item, using catalog defaults for anything missing."""
    name = item.get("name")
    city = item.get("city")
    cid = item.get("catalog_id")
    kind = item.get("type")

    if kind == "flight":
        rec = idx.flights_by_id.get(cid) or {}
        if name is None and rec:
            name = f"{rec.get('flight_number')} {rec.get('from')} to {rec.get('to')}"
        if city is None and rec:
            airport = idx.airports_by_code.get(rec.get("to")) or {}
            city = airport.get("city")
    elif kind == "hotel":
        rec = idx.hotels_by_id.get(cid) or {}
        name = name if name is not None else rec.get("name")
        city = city if city is not None else rec.get("city")
    elif kind == "attraction":
        rec = idx.attractions_by_id.get(cid) or {}
        name = name if name is not None else rec.get("name")
        city = city if city is not None else rec.get("city")
    elif kind == "transfer":
        rec = idx.transfers_by_id.get(cid) or {}
        name = name if name is not None else rec.get("name")
        if city is None:
            city = rec.get("city") or rec.get("to_city")

    return name, city


def to_trip_json(package: dict, data=None) -> dict:
    """Convert an internal package into the shared trip format.

    package keys: trip_id, traveler {name, home_airport, adults, child_ages},
    country (name), start_date, end_date, budget_inr, status ("PLANNED"|"BOOKED", default PLANNED),
    booking_reference (10 digits, required when BOOKED), items (itinerary order).
    data: catalog (Loaded or Indexes); defaults to load_catalog().

    Raises ValueError for an unknown status or a BOOKED package without a valid reference.
    """
    status = package.get("status") or "PLANNED"
    if status not in _TRIP_STATUSES:
        raise ValueError(f"status must be PLANNED or BOOKED, got {status!r}")

    reference = package.get("booking_reference")
    if status == "BOOKED":
        if not isinstance(reference, str) or not _REFERENCE_RE.fullmatch(reference):
            raise ValueError("booking_reference must be exactly 10 digits when status is BOOKED")

    idx = _indexes(data)

    traveler_in = package.get("traveler") or {}
    child_ages = list(traveler_in.get("child_ages") or [])
    traveler = {
        "name": traveler_in.get("name"),
        "home_airport": traveler_in.get("home_airport"),
        "adults": traveler_in.get("adults"),
        "children": len(child_ages),
        "child_ages": child_ages,
    }

    items = []
    for n, item in enumerate(package.get("items") or [], start=1):
        kind = item.get("type")
        name, city = _fill(item, idx)
        if kind == "hotel":
            start = _date_out(item.get("start"))
            end = _date_out(item.get("end"))
            room_id = item.get("room_id")
        else:
            start = _dt_out(item.get("start"))
            end = _dt_out(item.get("end"))
            room_id = None
        price = item.get("price_inr")
        items.append({
            "item_id": f"i{n}",
            "type": kind,
            "name": name,
            "city": city,
            "status": status,
            "catalog_id": item.get("catalog_id"),
            "room_id": room_id,
            "start": start,
            "end": end,
            "quantity": item.get("quantity"),
            "price_inr": price,
            "booking": {"reference": reference} if status == "BOOKED" else None,
            "sources": [],
            "warnings": list(item.get("warnings") or []),
        })

    total = sum(i["price_inr"] or 0 for i in items)

    return {
        "trip_id": package.get("trip_id"),
        "traveler": traveler,
        "start_date": _date_out(package.get("start_date")),
        "end_date": _date_out(package.get("end_date")),
        "country": package.get("country"),
        "budget_inr": package.get("budget_inr"),
        "total_inr": total,
        "items": items,
    }
