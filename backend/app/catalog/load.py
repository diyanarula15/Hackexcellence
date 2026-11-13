"""Loads the read-only dataset once, validates files and cross-file references, builds indexes."""
import json
from collections import defaultdict
from dataclasses import dataclass, fields
from functools import lru_cache

from app.config import CATALOG_DIR


class CatalogError(Exception):
    """Missing/malformed file, missing key, or a broken reference between files."""


REQUIRED_KEYS = {
    "airports": ["code", "name", "city", "country", "timezone"],
    "flights": ["flight_id", "from", "to", "departure_local", "arrival_local",
                "duration_minutes", "price_per_seat", "seats_left"],
    "hotels": ["hotel_id", "name", "city", "stars", "check_in_from", "check_out_until"],
    "rooms": ["room_id", "hotel_id", "room_type", "max_adults", "max_children", "price_per_night"],
    "availability": ["room_id", "date", "rooms_left"],
    "transfers": ["transfer_id", "type", "pricing", "price", "max_passengers",
                  "service_from", "service_until", "duration_minutes"],
    "attractions": ["attraction_id", "name", "city", "open_days", "open_from",
                    "open_until", "visit_minutes", "price_per_person"],
}
DESTINATIONS_KEYS = ["departure_cities", "countries", "rules"]
RULE_KEYS = ["min_nights", "max_nights", "min_nights_per_city", "data_window"]
COUNTRY_KEYS = ["code", "name", "timezone", "cities", "links"]


@dataclass(frozen=True)
class Catalog:
    destinations: dict
    airports: list
    flights: list
    hotels: list
    rooms: list
    availability: list
    transfers: list
    attractions: list


@dataclass
class Indexes:
    flights_by_id: dict
    flights_by_origin: dict              # origin airport -> [flights]
    flights_by_arrival_date: dict        # YYYY-MM-DD (local arrival) -> [flights]
    flights_by_departure_date: dict      # YYYY-MM-DD (local departure) -> [flights]
    airports_by_code: dict
    hotels_by_city: dict
    rooms_by_hotel: dict
    availability_by_room_date: dict      # (room_id, YYYY-MM-DD) -> rooms_left
    transfers_by_airport_city: dict      # (airport, city) -> [transfers]
    transfers_by_id: dict
    attractions_by_city: dict
    city_links_by_origin: dict           # from_city -> [link objects]


@dataclass
class Loaded:
    catalog: Catalog
    indexes: Indexes


def _read(name: str):
    path = CATALOG_DIR / f"{name}.json"
    if not path.is_file():
        raise CatalogError(f"Missing catalog file: {path}")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise CatalogError(f"Malformed JSON in {path.name}: line {e.lineno} col {e.colno}: {e.msg}") from e


def _check_shapes(c: Catalog) -> None:
    d = c.destinations
    if not isinstance(d, dict):
        raise CatalogError("destinations.json must be an object")
    miss = [k for k in DESTINATIONS_KEYS if k not in d]
    if miss:
        raise CatalogError(f"destinations.json is missing keys: {miss}")
    miss = [k for k in RULE_KEYS if k not in d["rules"]]
    if miss:
        raise CatalogError(f"destinations.json rules is missing keys: {miss}")
    for i, dc in enumerate(d["departure_cities"]):
        if "airport" not in dc or "city" not in dc:
            raise CatalogError(f"destinations.json departure_cities[{i}] needs 'airport' and 'city'")
    for i, co in enumerate(d["countries"]):
        miss = [k for k in COUNTRY_KEYS if k not in co]
        if miss:
            raise CatalogError(f"destinations.json countries[{i}] is missing keys: {miss}")
    for name, keys in REQUIRED_KEYS.items():
        data = getattr(c, name)
        if not isinstance(data, list) or not data:
            raise CatalogError(f"{name}.json must be a non-empty list")
        for i, rec in enumerate(data):
            if not isinstance(rec, dict):
                raise CatalogError(f"{name}.json[{i}] is not an object")
            miss = [k for k in keys if k not in rec]
            if miss:
                raise CatalogError(f"{name}.json[{i}] is missing keys: {miss}")


def _check_references(c: Catalog) -> None:
    errs: list[str] = []
    airports = {a["code"] for a in c.airports}
    cities = {x["name"] for co in c.destinations["countries"] for x in co["cities"]}
    hotels = {h["hotel_id"] for h in c.hotels}
    rooms = {r["room_id"] for r in c.rooms}
    transfers = {t["transfer_id"] for t in c.transfers}

    for dc in c.destinations["departure_cities"]:
        if dc["airport"] not in airports:
            errs.append(f"departure city {dc['city']}: airport {dc['airport']} not in airports.json")
    for co in c.destinations["countries"]:
        for city in co["cities"]:
            for ap in city["airports"]:
                if ap not in airports:
                    errs.append(f"{co['code']}/{city['name']}: airport {ap} not in airports.json")
        for ln in co["links"]:
            for k in ("from_city", "to_city"):
                if ln[k] not in cities:
                    errs.append(f"{co['code']} link: unknown city {ln[k]}")
            for tid in ln["transfer_ids"]:
                if tid not in transfers:
                    errs.append(f"{co['code']} link {ln['from_city']}->{ln['to_city']}: unknown transfer {tid}")
    for f in c.flights:
        for k in ("from", "to"):
            if f[k] not in airports:
                errs.append(f"flight {f['flight_id']}: unknown airport {f[k]}")
    for h in c.hotels:
        if h["city"] not in cities:
            errs.append(f"hotel {h['hotel_id']}: unknown city {h['city']}")
    for r in c.rooms:
        if r["hotel_id"] not in hotels:
            errs.append(f"room {r['room_id']}: unknown hotel {r['hotel_id']}")
    for a in c.availability:
        if a["room_id"] not in rooms:
            errs.append(f"availability: unknown room {a['room_id']}")
    for t in c.transfers:
        if t.get("airport") and t["airport"] not in airports:
            errs.append(f"transfer {t['transfer_id']}: unknown airport {t['airport']}")
        if t.get("city") and t["city"] not in cities:
            errs.append(f"transfer {t['transfer_id']}: unknown city {t['city']}")
    # Attractions in a city with no hotels (e.g. Nara) are valid data: the planner can never
    # use them, so they are deliberately not checked against destinations.json.
    if errs:
        more = f" (+{len(errs) - 10} more)" if len(errs) > 10 else ""
        raise CatalogError("Broken references in catalog:\n  " + "\n  ".join(errs[:10]) + more)


def _group(items, key):
    out = defaultdict(list)
    for i in items:
        out[key(i)].append(i)
    return dict(out)


def build_indexes(c: Catalog) -> Indexes:
    return Indexes(
        flights_by_id={f["flight_id"]: f for f in c.flights},
        flights_by_origin=_group(c.flights, lambda f: f["from"]),
        flights_by_arrival_date=_group(c.flights, lambda f: f["arrival_local"][:10]),
        flights_by_departure_date=_group(c.flights, lambda f: f["departure_local"][:10]),
        airports_by_code={a["code"]: a for a in c.airports},
        hotels_by_city=_group(c.hotels, lambda h: h["city"]),
        rooms_by_hotel=_group(c.rooms, lambda r: r["hotel_id"]),
        availability_by_room_date={(a["room_id"], a["date"]): a["rooms_left"] for a in c.availability},
        transfers_by_airport_city=_group(
            [t for t in c.transfers if t.get("airport") and t.get("city")],
            lambda t: (t["airport"], t["city"])),
        transfers_by_id={t["transfer_id"]: t for t in c.transfers},
        attractions_by_city=_group(c.attractions, lambda a: a["city"]),
        city_links_by_origin=_group(
            [ln for co in c.destinations["countries"] for ln in co["links"]],
            lambda ln: ln["from_city"]),
    )


@lru_cache(maxsize=1)
def load_catalog() -> Loaded:
    """Read, validate and index the dataset once. Raises CatalogError on any problem."""
    c = Catalog(**{f.name: _read(f.name) for f in fields(Catalog)})
    _check_shapes(c)
    _check_references(c)
    return Loaded(catalog=c, indexes=build_indexes(c))
