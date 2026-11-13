"""Display views for package changes: named changed items, readable violations, one-line headlines.

Display only: no rule is checked, no price computed and nothing decided here. Shared by
services.alternatives (the options list) and services.modifications (preview / apply).

  changed_item_view(item, catalog)   engine ChangedItem -> JSON-ready dict with names and a summary
  violation_view(v, catalog)         {rule, item_id, message}; catalog ids in the message are named
  headline(violations, catalog)      one sentence a traveler can act on, for an impossible change
"""

import re
from datetime import date, datetime

from app.engine.model import ARRIVAL_LEG, DEPARTURE_LEG
from app.engine.repair import ChangedItem
from app.lib.money import rupees
from app.rules.common import Violation
from app.rules.transfers import BUFFER_TEXT

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")


def catalog_label(catalog_id: str | None, catalog) -> str | None:
    """What a traveler calls a catalog record: the flight number, else the record's name."""
    if not catalog_id:
        return None
    ix = catalog.indexes
    flight = ix.flights_by_id.get(catalog_id)
    if flight is not None:
        return flight.get("flight_number") or catalog_id
    for table in (ix.hotels_by_id, ix.rooms_by_id, ix.transfers_by_id, ix.attractions_by_id):
        rec = table.get(catalog_id)
        if rec is not None:
            return rec.get("name") or catalog_id
    return None


def name_ids(text: str, catalog) -> str:
    """'Flight FL-1001 has 2 seats' -> 'Flight NS 432 has 2 seats' (only exact catalog ids change)."""
    return _TOKEN.sub(lambda m: catalog_label(m.group(0), catalog) or m.group(0), text)


def item_kind(item_id: str) -> tuple[str, str]:
    """(item type, label) of a stable package item id."""
    if item_id == "flight:arrival":
        return "flight", "Arrival flight"
    if item_id == "flight:return":
        return "flight", "Return flight"
    if item_id == ARRIVAL_LEG:
        return "transfer", "Arrival airport transfer"
    if item_id == DEPARTURE_LEG:
        return "transfer", "Departure airport transfer"
    if item_id.startswith("leg:") and ">" in item_id:  # leg:<from>><to>:<date>
        a, b = item_id[4:].rsplit(":", 1)[0].split(">", 1)
        return "transfer", f"Transfer {a} → {b}"
    if item_id.startswith("stay:"):  # stay:<city>:<in>:<out>
        return "hotel", f"Hotel in {item_id.split(':')[1]}"
    if item_id.startswith("visit:"):
        return "attraction", "Attraction"
    return "item", item_id


def signed_rupees(value: int) -> str:
    return ("+" if value > 0 else "") + rupees(value)


def _when(text: str) -> datetime | date:
    return datetime.fromisoformat(text) if "T" in text else date.fromisoformat(text)


def _at(text: str) -> str:
    """'Sat 10 Apr 15:00' for a time, 'Sat 10 Apr' for a date."""
    t = _when(text)
    return f"{t:%a %d %b %H:%M}" if isinstance(t, datetime) else f"{t:%a %d %b}"


def _side(desc: dict | None, catalog) -> dict | None:
    if desc is None:
        return None
    out = {**desc, "name": catalog_label(desc["catalog_id"], catalog) or desc["catalog_id"]}
    if desc.get("room_id"):
        out["room_name"] = catalog_label(desc["room_id"], catalog) or desc["room_id"]
    return out


def _title(side: dict) -> str:
    rooms = f" × {side['rooms']}" if side.get("rooms", 1) != 1 else ""
    return side["name"] + (f" ({side['room_name']}{rooms})" if side.get("room_name") else "")


def _summary(c: ChangedItem, label: str, before: dict | None, after: dict | None) -> str:
    price = f" ({signed_rupees(c.price_delta)})" if c.price_delta else ""
    timed = (before or after) and "T" in (before or after)["start"]
    if c.action == "ADDED":
        return f"{label}: {after['name']} added, {_at(after['start'])}{price}"
    if c.action == "REMOVED":
        return f"{label}: {before['name']} on {_at(before['start'])} removed{price}"
    if c.action == "RESCHEDULED":
        return f"{label}: {after['name']} moves from {_at(before['start'])} to {_at(after['start'])}{price}"
    text = f"{label}: {_title(before)} → {_title(after)}"
    if timed and before["start"] != after["start"]:
        text += f", now {_at(after['start'])}"
    return text + price


def changed_item_view(c: ChangedItem, catalog) -> dict:
    kind, label = item_kind(c.component)
    before, after = _side(c.before, catalog), _side(c.after, catalog)
    return {
        "item_id": c.component,
        "type": kind,
        "label": label,
        "source": c.source,
        "action": c.action,
        "before": before,
        "after": after,
        "price_difference_inr": c.price_delta,
        "summary": _summary(c, label, before, after),
        "reason": name_ids(c.reason, catalog),
        "start": (c.after or c.before or {}).get("start"),   # ISO local time of the visit (or of the item)
        "end": (c.after or c.before or {}).get("end"),
    }


def batch_headline(command) -> str | None:
    """'Adding 3 attractions.' for a batch command, None for every other kind."""
    if command.kind == "ADD_ATTRACTIONS":
        n, verb = len(command.additions), "Adding"
    elif command.kind == "REMOVE_ATTRACTIONS":
        n, verb = len(command.item_ids), "Removing"
    else:
        return None
    return f"{verb} {n} attraction{'s' if n != 1 else ''}."


def violation_view(v: Violation, catalog) -> dict:
    return {"rule": v.rule, "item_id": v.item_id, "message": name_ids(v.message, catalog)}


# rule code -> what the traveler needs to hear first (first match in this order wins)
_HEADLINES = (
    ("NO_CHANGE", None),  # None: the violation's own message says it best
    ("CHANGE_TARGET_NOT_FOUND", None),
    ("R-FLT-3", "Not enough seats are left on this flight for every traveler."),
    ("R-FLT-4", "This flight does not arrive on your holiday's first day."),
    ("R-FLT-6", "This flight does not leave on your holiday's last day."),
    ("R-FLT-5", "This flight lands at an airport that does not serve your first city."),
    ("R-FLT-7", "This flight leaves from an airport that does not serve your last city."),
    ("R-FLT-2", "This flight does not leave from your home airport."),
    ("R-FLT-8", "This flight does not return to your home airport."),
    ("R-FLT-0", "This flight does not fly to or from your destination country."),
    ("R-FLT-9", "This flight is not in the catalog."),
    ("R-HTL-6", "This hotel room is not available for every night of the stay."),
    ("R-HTL-5", "This room type cannot fit your group."),
    ("R-HTL-2", "This hotel is not in the city of this stay."),
    ("R-HTL-3", "This room type does not belong to the selected hotel."),
    ("R-HTL-1", "This hotel is not in the catalog."),
    ("NO_ARRIVAL_TRANSFER", "No airport transfer can take you from this flight to your hotel."),
    (
        "NO_DEPARTURE_TRANSFER",
        f"No airport transfer can get you to this flight with {BUFFER_TEXT} to spare.",
    ),
    ("NO_INTERCITY_TRANSFER", "No city-to-city transfer works with this change."),
    ("R-ATR-7", f"This transfer would reach the airport less than {BUFFER_TEXT} before your flight."),
    ("R-ATR-6", "This transfer does not run at the time it would be needed."),
    ("R-ATR-5", "This transfer cannot meet your flight at a valid time."),
    ("R-ATR-4", "This transfer does not serve your hotel's area."),
    ("R-ATR-3", "This transfer does not serve the airport of your flight."),
    ("R-ATR-2", "This is not an airport transfer."),
    ("R-ICT-6", "This train or bus does not depart at that time."),
    ("R-ICT-5", "This transfer does not run at that time."),
    ("R-ICT-3", "This transfer does not run between these two cities."),
    ("R-ICT-2", "This transfer is not in the catalog."),
    ("R-ATT-7", None),
    ("R-ATT-11", None),
    ("R-ATT-3", None),
    ("R-ATT-4", None),
    ("R-ATT-2", None),
    ("R-ATT-8", None),
    ("R-ATT-1", "This attraction is not in the catalog."),
    ("REPAIR_OUT_OF_SCOPE", None),
)


def headline(violations: list[Violation], catalog) -> str:
    """One actionable sentence for an impossible change, from the most specific rule present."""
    if not violations:
        return ""
    for rule, text in _HEADLINES:
        hit = next((v for v in violations if v.rule == rule), None)
        if hit is not None:
            return text or name_ids(hit.message, catalog)
    return name_ids(violations[0].message, catalog)
