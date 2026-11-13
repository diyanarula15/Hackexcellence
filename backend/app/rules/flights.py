"""Flight rules (R-FLT-*): classify the selected flights and check the arrival and return legs."""
from datetime import date

from app.lib.time import parse_date
from app.rules.common import FlightSel, Party, Violation

Role = str  # "outbound" | "inbound" | "none" | "unknown"


def _roles(flights: list[FlightSel], country_code: str, data) -> list[tuple[FlightSel, dict | None, Role]]:
    """One (selection, catalog record, role) per input, in input order."""
    airports = data.indexes.airports_by_code
    out: list[tuple[FlightSel, dict | None, Role]] = []
    for fs in flights:
        rec = data.indexes.flights_by_id.get(fs.flight_id)
        if rec is None:
            out.append((fs, None, "unknown"))
            continue
        to_ap = airports.get(rec["to"])
        from_ap = airports.get(rec["from"])
        if to_ap is not None and to_ap["country"] == country_code:
            role = "outbound"
        elif from_ap is not None and from_ap["country"] == country_code:
            role = "inbound"
        else:
            role = "none"
        out.append((fs, rec, role))
    return out


def classify_flights(flights: list[FlightSel], country_code: str, data):
    """Split the selected flights into (outbound, inbound, violations).

    outbound / inbound are lists of (FlightSel, catalog record). Outbound arrives in the country,
    inbound departs from it. Unknown flight ids give R-FLT-9; flights touching neither give R-FLT-0.
    """
    outbound: list[tuple[FlightSel, dict]] = []
    inbound: list[tuple[FlightSel, dict]] = []
    violations: list[Violation] = []
    for fs, rec, role in _roles(flights, country_code, data):
        if role == "unknown":
            violations.append(Violation("R-FLT-9", f"Flight {fs.flight_id} is not in the catalog.", fs.item_id))
        elif role == "none":
            violations.append(Violation(
                "R-FLT-0",
                f"Flight {fs.flight_id} neither arrives in nor departs from the chosen country ({country_code}).",
                fs.item_id))
        elif role == "outbound":
            outbound.append((fs, rec))
        else:
            inbound.append((fs, rec))
    return outbound, inbound, violations


def _seat_and_time_checks(fs: FlightSel, rec: dict, party: Party) -> list[Violation]:
    out: list[Violation] = []
    seats = rec["seats_left"]
    if seats < party.travelers:
        out.append(Violation(
            "R-FLT-3",
            f"Flight {rec['flight_id']} has {seats} seats but requires {party.travelers}.",
            fs.item_id))
    if fs.start is not None and fs.start != rec["departure_local"][:16]:
        out.append(Violation(
            "R-FLT-10",
            f"Flight {rec['flight_id']} start {fs.start} does not match catalog departure "
            f"{rec['departure_local'][:16]}.",
            fs.item_id))
    if fs.end is not None and fs.end != rec["arrival_local"][:16]:
        out.append(Violation(
            "R-FLT-10",
            f"Flight {rec['flight_id']} end {fs.end} does not match catalog arrival "
            f"{rec['arrival_local'][:16]}.",
            fs.item_id))
    return out


def _outbound_checks(fs: FlightSel, rec: dict, home_airport: str, first_city: str,
                     start_date: date, data) -> list[Violation]:
    out: list[Violation] = []
    fid = rec["flight_id"]
    if rec["from"] != home_airport:
        out.append(Violation(
            "R-FLT-2", f"Outbound flight {fid} departs from {rec['from']}, not the home airport {home_airport}.",
            fs.item_id))
    arrival_date = parse_date(rec["arrival_local"])
    if arrival_date != start_date:
        out.append(Violation(
            "R-FLT-4", f"Outbound flight {fid} arrives on {arrival_date} but the trip starts {start_date}.",
            fs.item_id))
    serves = (data.indexes.airports_by_code.get(rec["to"]) or {}).get("serves_cities") or []
    if first_city not in serves:
        out.append(Violation(
            "R-FLT-5", f"Outbound flight {fid} lands at {rec['to']}, which does not serve {first_city}.",
            fs.item_id))
    return out


def _inbound_checks(fs: FlightSel, rec: dict, home_airport: str, last_city: str,
                    end_date: date, data) -> list[Violation]:
    out: list[Violation] = []
    fid = rec["flight_id"]
    departure_date = parse_date(rec["departure_local"])
    if departure_date != end_date:
        out.append(Violation(
            "R-FLT-6", f"Return flight {fid} departs on {departure_date} but the trip ends {end_date}.",
            fs.item_id))
    serves = (data.indexes.airports_by_code.get(rec["from"]) or {}).get("serves_cities") or []
    if last_city not in serves:
        out.append(Violation(
            "R-FLT-7", f"Return flight {fid} departs from {rec['from']}, which does not serve {last_city}.",
            fs.item_id))
    if rec["to"] != home_airport:
        out.append(Violation(
            "R-FLT-8", f"Return flight {fid} arrives at {rec['to']}, not the home airport {home_airport}.",
            fs.item_id))
    return out


def check_flights(flights: list[FlightSel], home_airport: str, country_code: str, first_city: str,
                  last_city: str, start_date: date, end_date: date, party: Party, data) -> list[Violation]:
    _, _, violations = classify_flights(flights, country_code, data)
    outbound_count = sum(1 for _, _, role in _roles(flights, country_code, data) if role == "outbound")
    inbound_count = sum(1 for _, _, role in _roles(flights, country_code, data) if role == "inbound")
    violations = list(violations)
    if outbound_count != 1 or inbound_count != 1:
        violations.append(Violation(
            "R-FLT-1",
            f"Package needs exactly one outbound flight to {country_code} and one inbound flight from it; "
            f"found {outbound_count} outbound and {inbound_count} inbound."))

    for fs, rec, role in _roles(flights, country_code, data):
        if role not in ("outbound", "inbound") or rec is None:
            continue  # unknown or unrelated flights were already reported by classify_flights
        violations.extend(_seat_and_time_checks(fs, rec, party))
        if role == "outbound":
            violations.extend(_outbound_checks(fs, rec, home_airport, first_city, start_date, data))
        else:
            violations.extend(_inbound_checks(fs, rec, home_airport, last_city, end_date, data))
    return violations
