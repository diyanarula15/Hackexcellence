"""Flight candidates for a holiday request: arrival and return legs, and the subset compatible with a city plan.

Pure functions over the Loaded catalog. Every price comes from app.rules.pricing.
"""
from datetime import timedelta

from app.catalog.load import Loaded
from app.engine.model import CityPlan, FlightOption
from app.lib.time import parse_dt
from app.rules import pricing
from app.rules.common import Party


def _party(request) -> Party:
    return Party(adults=request.adults, child_ages=tuple(request.children_ages))


def _country_city_names(catalog: Loaded, country_code: str) -> set[str]:
    country = catalog.indexes.countries_by_code.get(country_code)
    if country is None:
        return set()
    return {city["name"] for city in country["cities"]}


def _in_country(catalog: Loaded, airport_code: str, country_code: str) -> bool:
    airport = catalog.indexes.airports_by_code.get(airport_code)
    return airport is not None and airport["country"] == country_code


def _serves(catalog: Loaded, airport_code: str) -> list[str]:
    airport = catalog.indexes.airports_by_code.get(airport_code) or {}
    return airport.get("serves_cities") or []


def _serves_any(catalog: Loaded, airport_code: str, cities: set[str]) -> bool:
    return any(city in cities for city in _serves(catalog, airport_code))


def _seats_ok(rec: dict, party: Party, ignore_seats: bool) -> bool:
    return ignore_seats or rec["seats_left"] >= party.travelers


def _option(rec: dict, party: Party) -> FlightOption:
    quantity, price = pricing.flight_price(rec, party)
    return FlightOption(
        flight_id=rec["flight_id"],
        from_airport=rec["from"],
        to_airport=rec["to"],
        departure=parse_dt(rec["departure_local"]),
        arrival=parse_dt(rec["arrival_local"]),
        quantity=quantity,
        price=price,
    )


def _sorted(options: list[FlightOption]) -> list[FlightOption]:
    return sorted(options, key=lambda o: (o.price, o.flight_id))


def find_arrival_flights(request, catalog: Loaded, ignore_seats: bool = False) -> list[FlightOption]:
    """Flights from the departure airport that land on the trip start date at an airport in the
    destination country which serves one of that country's cities."""
    ix = catalog.indexes
    party = _party(request)
    cities = _country_city_names(catalog, request.destination_country)
    out: list[FlightOption] = []
    for rec in ix.flights_by_arrival_date.get(request.start_date.isoformat(), []):
        if rec["from"] != request.departure_airport:
            continue
        if not _in_country(catalog, rec["to"], request.destination_country):
            continue
        if not _serves_any(catalog, rec["to"], cities):
            continue
        if not _seats_ok(rec, party, ignore_seats):
            continue
        out.append(_option(rec, party))
    return _sorted(out)


def find_return_flights(request, catalog: Loaded, ignore_seats: bool = False) -> list[FlightOption]:
    """Flights to the departure airport that leave on the trip end date from an airport in the
    destination country which serves one of that country's cities."""
    ix = catalog.indexes
    party = _party(request)
    cities = _country_city_names(catalog, request.destination_country)
    end_day = request.start_date + timedelta(days=request.nights)
    out: list[FlightOption] = []
    for rec in ix.flights_by_departure_date.get(end_day.isoformat(), []):
        if rec["to"] != request.departure_airport:
            continue
        if not _in_country(catalog, rec["from"], request.destination_country):
            continue
        if not _serves_any(catalog, rec["from"], cities):
            continue
        if not _seats_ok(rec, party, ignore_seats):
            continue
        out.append(_option(rec, party))
    return _sorted(out)


def compatible_arrivals(plan: CityPlan, flights: list[FlightOption], catalog: Loaded) -> list[FlightOption]:
    """Arrival flights whose airport serves the plan's first city."""
    return _sorted([f for f in flights if plan.first_city in _serves(catalog, f.to_airport)])


def compatible_returns(plan: CityPlan, flights: list[FlightOption], catalog: Loaded) -> list[FlightOption]:
    """Return flights whose departure airport serves the plan's last city."""
    return _sorted([f for f in flights if plan.last_city in _serves(catalog, f.from_airport)])
