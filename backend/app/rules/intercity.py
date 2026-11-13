"""City-to-city transfer rules. A city change happens on stays[k].check_out when the city of stays[k]
differs from the city of stays[k+1]; each such change needs exactly one matching move."""
from app.lib.time import in_window, on_slot
from app.rules.common import Stay, TransferSel, Violation


def _city(stay: Stay, data) -> str:
    hotel = data.indexes.hotels_by_id.get(stay.hotel_id)
    return hotel["city"] if hotel is not None else stay.city


def check_intercity(moves: list[TransferSel], stays: list[Stay], data) -> list[Violation]:
    out: list[Violation] = []

    # City changes in itinerary order: (change date, from city, to city).
    changes: list[tuple] = []
    for k in range(len(stays) - 1):
        a, b = _city(stays[k], data), _city(stays[k + 1], data)
        if a != b:
            changes.append((stays[k].check_out, a, b))

    assigned: dict[int, list[int]] = {}   # change index -> indexes of moves on that change
    for i, mv in enumerate(moves):
        rec = data.indexes.transfers_by_id.get(mv.transfer_id)
        if rec is None:
            out.append(Violation("R-ICT-2", f"Move {mv.transfer_id} is not in the catalog.", mv.item_id))
            continue
        if rec.get("from_city") is None or rec.get("to_city") is None:
            out.append(Violation(
                "R-ICT-2", f"Move {mv.transfer_id} has no from_city/to_city (not a city-to-city transfer).",
                mv.item_id))
            continue

        pair = (rec["from_city"], rec["to_city"])
        pair_changes = [ci for ci, (_, a, b) in enumerate(changes) if (a, b) == pair]
        same_day = [ci for ci in pair_changes if changes[ci][0] == mv.pickup.date()]
        if same_day:
            assigned.setdefault(same_day[0], []).append(i)
            link = _link(data, pair)
            if link is None or mv.transfer_id not in link["transfer_ids"]:
                out.append(Violation(
                    "R-ICT-3",
                    f"Move {mv.transfer_id} is not a transfer of the directed link "
                    f"{pair[0]} -> {pair[1]}.",
                    mv.item_id))
        elif pair_changes:
            day = changes[pair_changes[0]][0]
            out.append(Violation(
                "R-ICT-4",
                f"Move {mv.transfer_id} picks up on {mv.pickup.date().isoformat()} but the city change "
                f"{pair[0]} -> {pair[1]} is on {day.isoformat()}.",
                mv.item_id))
        else:
            out.append(Violation(
                "R-ICT-3",
                f"Move {mv.transfer_id} ({pair[0]} -> {pair[1]}) matches no city change in the package.",
                mv.item_id))

        if not in_window(mv.pickup, rec["service_from"], rec["service_until"]):
            out.append(Violation(
                "R-ICT-5",
                f"Move {mv.transfer_id} picks up at {mv.pickup:%H:%M}, outside its service window "
                f"{rec['service_from']}-{rec['service_until']}.",
                mv.item_id))

        freq = rec.get("frequency_minutes")
        if freq is not None and not on_slot(mv.pickup, rec["service_from"], rec["service_until"], freq):
            out.append(Violation(
                "R-ICT-6",
                f"Move {mv.transfer_id} picks up at {mv.pickup:%H:%M}, which is not a departure "
                f"(one every {freq} minutes from {rec['service_from']}).",
                mv.item_id))

    for ci, (day, a, b) in enumerate(changes):
        n = len(assigned.get(ci, []))
        if n == 0:
            out.append(Violation(
                "R-ICT-1", f"No move for the city change {a} -> {b} on {day.isoformat()}."))
        elif n > 1:
            out.append(Violation(
                "R-ICT-1", f"{n} moves for the city change {a} -> {b} on {day.isoformat()}; exactly one is required."))
    return out


def _link(data, pair: tuple[str, str]) -> dict | None:
    for ln in data.indexes.city_links_by_origin.get(pair[0], []):
        if ln["to_city"] == pair[1]:
            return ln
    return None
