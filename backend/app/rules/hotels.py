"""Hotel rules (R-HTL-*): hotel and room identity, room capacity and per-night availability."""
from app.lib.time import date_range
from app.rules.common import Party, Stay, Violation


def check_hotels(stays: list[Stay], party: Party, data) -> list[Violation]:
    violations: list[Violation] = []
    indexes = data.indexes
    for stay in stays:
        hotel = indexes.hotels_by_id.get(stay.hotel_id)
        if hotel is None:
            violations.append(Violation("R-HTL-1", f"Hotel {stay.hotel_id} is not in the catalog.", stay.item_id))
            continue
        if hotel["city"] != stay.city:
            violations.append(Violation(
                "R-HTL-2",
                f"Hotel {stay.hotel_id} is in {hotel['city']}, but the stay says {stay.city}.",
                stay.item_id))

        room = indexes.rooms_by_id.get(stay.room_id)
        if room is None:
            violations.append(Violation("R-HTL-3", f"Room {stay.room_id} is not in the catalog.", stay.item_id))
            continue
        if room["hotel_id"] != stay.hotel_id:
            violations.append(Violation(
                "R-HTL-3",
                f"Room {stay.room_id} belongs to hotel {room['hotel_id']}, not {stay.hotel_id}.",
                stay.item_id))
            continue

        k = stay.rooms
        if type(k) is not int or k < 1:
            violations.append(Violation(
                "R-HTL-4", f"Stay {stay.item_id} rooms must be a positive whole number, got {k!r}.",
                stay.item_id))
            continue

        adults, children = party.adults, party.children
        fits = (adults <= k * room["max_adults"]
                and adults + children <= k * (room["max_adults"] + room["max_children"])
                and adults >= k)
        if not fits:
            violations.append(Violation(
                "R-HTL-5",
                f"Room {stay.room_id} x{k} cannot hold {adults} adults and {children} children "
                f"(each room takes {room['max_adults']} adults and {room['max_children']} children, "
                f"and every room needs at least one adult).",
                stay.item_id))

        for night in date_range(stay.check_in, stay.nights):
            rooms_left = indexes.availability_by_room_date.get((stay.room_id, night.isoformat()))
            if rooms_left is None:
                violations.append(Violation(
                    "R-HTL-6",
                    f"Room {stay.room_id} has no availability record for the night of {night}.",
                    stay.item_id))
            elif rooms_left < k:
                violations.append(Violation(
                    "R-HTL-6",
                    f"Room {stay.room_id} has {rooms_left} rooms left on the night of {night}; "
                    f"the stay needs {k}.",
                    stay.item_id))
    return violations
