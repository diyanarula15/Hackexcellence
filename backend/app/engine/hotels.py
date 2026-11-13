"""Hotel candidates for one city stay: room counts, per-night availability and pricing.

Pure functions over the Loaded catalog. Prices come from app.rules.pricing.
"""
from datetime import date

from app.catalog.load import Loaded
from app.engine.constraints import HotelLock
from app.engine.model import CityStay, HotelOption
from app.lib.time import date_range
from app.rules import pricing

NO_HOTEL_CAPACITY = "NO_HOTEL_CAPACITY"
NO_HOTEL_AVAILABILITY = "NO_HOTEL_AVAILABILITY"


def _rooms_fit(room: dict, k: int, adults: int, children: int) -> bool:
    return (adults <= k * room["max_adults"]
            and adults + children <= k * (room["max_adults"] + room["max_children"])
            and adults >= k)


def min_rooms(room: dict, adults: int, children: int) -> int | None:
    """Smallest room count k (k >= 1) that holds the party in this room type, or None if impossible."""
    cap_adults = room["max_adults"]
    cap_total = room["max_adults"] + room["max_children"]
    if cap_adults <= 0 or cap_total <= 0:
        return None
    k = max(1, -(-adults // cap_adults), -(-(adults + children) // cap_total))
    return k if _rooms_fit(room, k, adults, children) else None


def _nightly_available(catalog: Loaded, room_id: str, check_in: date, nights: int, k: int) -> bool:
    for night in date_range(check_in, nights):
        rooms_left = catalog.indexes.availability_by_room_date.get((room_id, night.isoformat()))
        if rooms_left is None or rooms_left < k:
            return False
    return True


def find_hotel_options(city: str, check_in: date, check_out: date, adults: int, children: int,
                       catalog: Loaded, locked: HotelLock | None = None) -> list[HotelOption]:
    """One option per (hotel, room type) that fits the party and has enough rooms on every night.

    With `locked`, only that exact hotel and room are considered, using locked.rooms when given."""
    ix = catalog.indexes
    nights = (check_out - check_in).days
    if nights < 1:
        return []

    pairs: list[tuple[dict, dict]] = []
    if locked is not None:
        hotel = ix.hotels_by_id.get(locked.hotel_id)
        room = ix.rooms_by_id.get(locked.room_id)
        if hotel is None or room is None or hotel["city"] != city or room["hotel_id"] != locked.hotel_id:
            return []
        pairs.append((hotel, room))
    else:
        for hotel in ix.hotels_by_city.get(city, []):
            for room in ix.rooms_by_hotel.get(hotel["hotel_id"], []):
                pairs.append((hotel, room))

    options: list[HotelOption] = []
    for hotel, room in pairs:
        if locked is not None and locked.rooms is not None:
            k = locked.rooms if (type(locked.rooms) is int and locked.rooms >= 1
                                 and _rooms_fit(room, locked.rooms, adults, children)) else None
        else:
            k = min_rooms(room, adults, children)
        if k is None or not _nightly_available(catalog, room["room_id"], check_in, nights, k):
            continue
        _, total = pricing.hotel_price(room, k, nights)
        stay = CityStay(city=city, check_in=check_in, check_out=check_out)
        options.append(HotelOption(
            stay_id=stay.stay_id,
            hotel_id=hotel["hotel_id"],
            room_id=room["room_id"],
            city=city,
            area=hotel.get("area"),
            check_in=check_in,
            check_out=check_out,
            rooms=k,
            total_price=total,
        ))
    return sorted(options, key=lambda o: (o.total_price, o.hotel_id, o.room_id))


def hotel_failure_reason(city: str, check_in: date, check_out: date, adults: int, children: int,
                         catalog: Loaded) -> str | None:
    """None when an option exists; NO_HOTEL_CAPACITY when no room type in the city can hold the party;
    otherwise NO_HOTEL_AVAILABILITY."""
    if find_hotel_options(city, check_in, check_out, adults, children, catalog):
        return None
    ix = catalog.indexes
    has_capacity = any(
        min_rooms(room, adults, children) is not None
        for hotel in ix.hotels_by_city.get(city, [])
        for room in ix.rooms_by_hotel.get(hotel["hotel_id"], [])
    )
    return NO_HOTEL_AVAILABILITY if has_capacity else NO_HOTEL_CAPACITY
