"""Airport transfer rules: the arrival transfer (airport -> first hotel) and the departure transfer
(last hotel -> airport). Pure functions of the selections and the catalog."""
from datetime import timedelta

from app.lib.time import in_window, parse_dt
from app.rules.common import TransferSel, Violation

ARRIVAL_MIN_AFTER_LANDING = timedelta(minutes=60)
ARRIVAL_MAX_AFTER_LANDING = timedelta(hours=24)
DEPARTURE_BUFFER_BEFORE_FLIGHT = timedelta(minutes=180)


def check_airport_transfers(
    arrival: list[TransferSel],
    departure: list[TransferSel],
    outbound: dict | None,
    inbound: dict | None,
    first_hotel: dict | None,
    last_hotel: dict | None,
    data,
) -> list[Violation]:
    out: list[Violation] = []
    if len(arrival) != 1:
        out.append(Violation(
            "R-ATR-1", f"Package needs exactly one arrival airport transfer, found {len(arrival)}."))
    if len(departure) != 1:
        out.append(Violation(
            "R-ATR-1", f"Package needs exactly one departure airport transfer, found {len(departure)}."))
    for sel in arrival:
        out.extend(_check_leg(sel, "arrival", outbound, first_hotel, data))
    for sel in departure:
        out.extend(_check_leg(sel, "departure", inbound, last_hotel, data))
    return out


def _check_leg(sel: TransferSel, leg: str, flight: dict | None, hotel: dict | None, data) -> list[Violation]:
    label = f"{leg.capitalize()} transfer {sel.transfer_id}"
    rec = data.indexes.transfers_by_id.get(sel.transfer_id)
    if rec is None:
        return [Violation("R-ATR-2", f"{label} is not in the catalog.", sel.item_id)]
    if rec.get("airport") is None:
        return [Violation("R-ATR-2", f"{label} is not an airport transfer (no airport).", sel.item_id)]

    out: list[Violation] = []
    if flight is not None:
        expected_airport = flight["to"] if leg == "arrival" else flight["from"]
        if rec["airport"] != expected_airport:
            out.append(Violation(
                "R-ATR-3",
                f"{label} is at {rec['airport']} but the {leg} flight needs {expected_airport}.",
                sel.item_id))

    if hotel is not None:
        hotel_area = hotel.get("area")
        if rec.get("city") != hotel["city"] or (rec.get("area") is not None and rec["area"] != hotel_area):
            out.append(Violation(
                "R-ATR-4",
                f"{label} serves {rec.get('city')}/{rec.get('area')} but hotel {hotel['hotel_id']} "
                f"is in {hotel['city']}/{hotel_area}.",
                sel.item_id))

    pickup = sel.pickup
    if leg == "arrival" and flight is not None:
        landed = parse_dt(flight["arrival_local"])
        if pickup < landed + ARRIVAL_MIN_AFTER_LANDING or pickup > landed + ARRIVAL_MAX_AFTER_LANDING:
            out.append(Violation(
                "R-ATR-5",
                f"{label} picks up at {pickup:%Y-%m-%dT%H:%M}; it must be at least 60 minutes and at most "
                f"24 hours after landing ({flight['arrival_local'][:16]}).",
                sel.item_id))

    if not in_window(pickup, rec["service_from"], rec["service_until"]):
        out.append(Violation(
            "R-ATR-6",
            f"{label} picks up at {pickup:%H:%M}, outside its service window "
            f"{rec['service_from']}-{rec['service_until']}.",
            sel.item_id))

    if leg == "departure" and flight is not None:
        departs = parse_dt(flight["departure_local"])
        latest_end = departs - DEPARTURE_BUFFER_BEFORE_FLIGHT
        ends = pickup + timedelta(minutes=rec["duration_minutes"])
        if ends > latest_end:
            out.append(Violation(
                "R-ATR-7",
                f"{label} ends at {ends:%Y-%m-%dT%H:%M}, later than 180 minutes before the departure "
                f"flight leaves ({flight['departure_local'][:16]}).",
                sel.item_id))
    return out
