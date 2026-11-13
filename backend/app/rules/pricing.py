"""Exact integer-INR price formulas (problem section 4). Each returns (quantity, price_inr)."""
import math

from app.lib.money import amount, child_unit
from app.rules.common import Party, Violation


def flight_price(flight: dict, party: Party) -> tuple[int, int]:
    q = party.travelers
    return q, amount(flight["price_per_seat"]) * q


def hotel_price(room: dict, rooms: int, nights: int) -> tuple[int, int]:
    return rooms, amount(room["price_per_night"]) * rooms * nights


def transfer_price(transfer: dict, party: Party) -> tuple[int, int]:
    if transfer["pricing"] == "PER_VEHICLE":
        vehicles = math.ceil(party.travelers / transfer["max_passengers"])
        return vehicles, amount(transfer["price"]) * vehicles
    if transfer["pricing"] == "PER_PERSON":
        price = party.adults * amount(transfer["price"]) + party.children * child_unit(transfer, "price")
        return party.travelers, price
    raise ValueError(f"Unknown pricing {transfer['pricing']!r} on {transfer['transfer_id']}")


def attraction_price(attraction: dict, party: Party) -> tuple[int, int]:
    price = (party.adults * amount(attraction["price_per_person"])
             + party.children * child_unit(attraction, "price_per_person"))
    return party.travelers, price


def check_item_price(item_id: str | None, expected: tuple[int, int], quantity, price_inr) -> list[Violation]:
    """Compare an exported item's quantity and price_inr with the catalog-derived values (exact)."""
    out: list[Violation] = []
    q, p = expected
    if quantity != q:
        out.append(Violation("R-PRICE-1", f"Item {item_id}: quantity is {quantity}, catalog requires {q}.", item_id))
    if price_inr != p:
        out.append(Violation("R-PRICE-2", f"Item {item_id}: price_inr is {price_inr}, catalog price is {p}.", item_id))
    return out


def check_total(items_sum: int, total_inr) -> list[Violation]:
    if total_inr != items_sum:
        return [Violation("R-PRICE-3", f"total_inr is {total_inr}, but the items add up to {items_sum}.")]
    return []
