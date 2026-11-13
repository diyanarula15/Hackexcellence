"""Request-level rules (R-REQ-*): the trip request as the traveler states it, checked against the catalog.

Pure: (request dict, catalog) -> list[Violation]. Nothing is fixed or normalised here.
"""
from datetime import date, datetime, timedelta

from app.rules.common import Violation


def resolve_country(value, data) -> dict | None:
    """The catalog country whose code or name equals `value` (trimmed, case-insensitive), else None."""
    if not isinstance(value, str):
        return None
    wanted = value.strip().lower()
    return next((c for c in data.catalog.destinations["countries"]
                 if wanted in (c["code"].lower(), c["name"].lower())), None)


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _as_date(v) -> date | None:
    """A date object or a "YYYY-MM-DD" string; anything else is None (not a date)."""
    if isinstance(v, datetime):
        return None
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        try:
            return date.fromisoformat(v.strip())
        except ValueError:
            return None
    return None


def check_request(req: dict, data) -> list[Violation]:
    dest = data.catalog.destinations
    rules = dest["rules"]
    window = rules["data_window"]
    first = date.fromisoformat(window["first_night"])
    last = date.fromisoformat(window["last_departure"])
    out: list[Violation] = []

    airport = req.get("departure_airport")
    airports = sorted({d["airport"] for d in dest["departure_cities"]})
    if not (isinstance(airport, str) and airport.strip().upper() in airports):
        out.append(Violation("R-REQ-1",
                             f"departure_airport {airport!r} must be one of {airports}."))

    country = resolve_country(req.get("destination_country"), data)
    if country is None:
        codes = [c["code"] for c in dest["countries"]]
        out.append(Violation("R-REQ-2",
                             f"destination_country {req.get('destination_country')!r} must be one of "
                             f"{codes} (country code or name)."))

    nights = req.get("nights")
    mn, mx = rules["min_nights"], rules["max_nights"]
    nights_ok = _is_int(nights) and mn <= nights <= mx
    if not nights_ok:
        out.append(Violation("R-REQ-3",
                             f"nights must be a whole number from {mn} to {mx}, got {nights!r}."))

    start = _as_date(req.get("start_date"))
    if start is None or start < first:
        out.append(Violation("R-REQ-4",
                             f"start_date must be a YYYY-MM-DD date on or after {first}, "
                             f"got {req.get('start_date')!r}."))

    if start is not None and nights_ok:
        end = start + timedelta(days=nights)
        if end > last:
            out.append(Violation("R-REQ-5",
                                 f"start_date plus {nights} nights returns on {end}, after the last "
                                 f"available departure {last}."))

    adults = req.get("adults")
    if not (_is_int(adults) and adults >= 1):
        out.append(Violation("R-REQ-6", f"adults must be a whole number of at least 1, got {adults!r}."))

    ages = req.get("children_ages", [])
    if not isinstance(ages, (list, tuple)):
        out.append(Violation("R-REQ-7", f"children_ages must be a list of ages, got {ages!r}."))
    else:
        for i, age in enumerate(ages):
            if not (_is_int(age) and 0 <= age <= 17):
                out.append(Violation("R-REQ-7",
                                     f"children_ages[{i}] {age!r} must be a whole age from 0 to 17."))

    budget = req.get("budget")
    if not (_is_int(budget) and budget >= 0):
        out.append(Violation("R-REQ-8", f"budget must be a whole number of at least 0, got {budget!r}."))

    return out
