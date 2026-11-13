"""Menon-family test fixture: a valid Japan package built from real catalog records.

Ids and itinerary times are test data, picked by searching data/catalog (Tokyo 3 nights, Kyoto 3 nights,
link Tokyo -> Kyoto). Every quantity and price is computed here from app/rules/pricing.py.
"""
from datetime import date, datetime, timedelta

from app.catalog.load import load_catalog
from app.export.to_trip import to_trip_json
from app.rules import pricing
from app.rules.common import Party

PARTY = Party(adults=2, child_ages=(6,))

# Itinerary order. Flight/transfer/attraction times are local; hotel times are dates.
_ITEMS = [
    {"type": "flight", "id": "FL-401", "city": "Tokyo"},                      # BLR -> NRT, lands 10 Apr
    {"type": "transfer", "id": "TR-NRT-UEN-BUS", "city": "Tokyo", "start": "2027-04-10T11:30"},
    {"type": "hotel", "id": "HTL-TYO-004", "room": "RM-TYO-004-B", "city": "Tokyo",
     "start": "2027-04-10", "end": "2027-04-13", "rooms": 1},
    {"type": "attraction", "id": "ATT-TYO-004", "city": "Tokyo", "start": "2027-04-11T06:00"},
    {"type": "attraction", "id": "ATT-TYO-008", "city": "Tokyo", "start": "2027-04-11T07:30"},
    {"type": "attraction", "id": "ATT-TYO-009", "city": "Tokyo", "start": "2027-04-12T10:00"},
    {"type": "attraction", "id": "ATT-TYO-010", "city": "Tokyo", "start": "2027-04-12T11:30"},
    {"type": "transfer", "id": "TR-TYO-KYO-01", "city": "Kyoto", "start": "2027-04-13T06:00"},  # change day
    {"type": "hotel", "id": "HTL-KYO-004", "room": "RM-KYO-004-B", "city": "Kyoto",
     "start": "2027-04-13", "end": "2027-04-16", "rooms": 1},
    {"type": "attraction", "id": "ATT-KYO-002", "city": "Kyoto", "start": "2027-04-14T06:00"},
    {"type": "attraction", "id": "ATT-KYO-004", "city": "Kyoto", "start": "2027-04-14T08:30"},
    {"type": "attraction", "id": "ATT-KYO-005", "city": "Kyoto", "start": "2027-04-15T10:00"},
    {"type": "attraction", "id": "ATT-KYO-006", "city": "Kyoto", "start": "2027-04-15T11:30"},
    {"type": "transfer", "id": "TR-KIX-KYO-BUS", "city": "Kyoto", "start": "2027-04-16T06:30"},  # departure
    {"type": "flight", "id": "FL-411", "city": "Bengaluru"},                  # KIX -> BLR, leaves 16 Apr
]


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M")


def _item(spec: dict, ix) -> dict:
    """One package item: catalog record in, quantity and price from pricing.py out."""
    kind, cid = spec["type"], spec["id"]
    room_id = None
    if kind == "flight":
        rec = ix.flights_by_id[cid]
        qty, price = pricing.flight_price(rec, PARTY)
        start, end = rec["departure_local"][:16], rec["arrival_local"][:16]
    elif kind == "transfer":
        rec = ix.transfers_by_id[cid]
        qty, price = pricing.transfer_price(rec, PARTY)
        start = spec["start"]
        end = _fmt(datetime.fromisoformat(start) + timedelta(minutes=rec["duration_minutes"]))
    elif kind == "hotel":
        rec = ix.rooms_by_id[spec["room"]]
        nights = (date.fromisoformat(spec["end"]) - date.fromisoformat(spec["start"])).days
        qty, price = pricing.hotel_price(rec, spec["rooms"], nights)
        start, end, room_id = spec["start"], spec["end"], spec["room"]
    else:
        rec = ix.attractions_by_id[cid]
        qty, price = pricing.attraction_price(rec, PARTY)
        start = spec["start"]
        end = _fmt(datetime.fromisoformat(start) + timedelta(minutes=rec["visit_minutes"]))
    return {"type": kind, "catalog_id": cid, "room_id": room_id, "city": spec["city"],
            "start": start, "end": end, "quantity": qty, "price_inr": price}


def menon_package() -> dict:
    """Internal package dict (input for to_trip_json). Status PLANNED."""
    ix = load_catalog().indexes
    return {
        "trip_id": "menon-japan-2027",
        "traveler": {"name": "Menon family", "home_airport": "BLR", "adults": PARTY.adults,
                     "child_ages": list(PARTY.child_ages)},
        "country": "Japan",
        "start_date": "2027-04-10",
        "end_date": "2027-04-16",
        "budget_inr": 350000,
        "status": "PLANNED",
        "items": [_item(spec, ix) for spec in _ITEMS],
    }


def menon_trip() -> dict:
    """Shared trip format (DATA_DICTIONARY section 4) for the Menon package."""
    return to_trip_json(menon_package(), load_catalog())
