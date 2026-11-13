"""Candidate city plans for one country: which cities to visit, in what order, for how many nights.

Every rule value (cities, one-way links, minimum nights per city) comes from the catalog.
"""
from datetime import date, timedelta
from typing import Iterator

from app.engine.model import CityPlan, CityStay


def _find_country(destinations: dict, country: str) -> dict | None:
    key = country.strip().casefold()
    for co in destinations["countries"]:
        if co["code"].casefold() == key or co["name"].casefold() == key:
            return co
    return None


def _sequences(names: list[str], edges: set[tuple[str, str]], max_cities: int) -> list[tuple[str, ...]]:
    """Every ordered sequence of distinct cities, each consecutive pair a directed link, DFS order."""
    out: list[tuple[str, ...]] = []

    def extend(path: list[str]) -> None:
        out.append(tuple(path))
        if len(path) == max_cities:
            return
        for nxt in names:
            if nxt not in path and (path[-1], nxt) in edges:
                path.append(nxt)
                extend(path)
                path.pop()

    for start in names:
        extend([start])
    return out


def _allocations(cities: int, total: int, minimum: int) -> Iterator[tuple[int, ...]]:
    """Every split of `total` nights into `cities` parts, each >= minimum, in lexicographic order."""
    if cities == 1:
        if total >= minimum:
            yield (total,)
        return
    for first in range(minimum, total - minimum * (cities - 1) + 1):
        for rest in _allocations(cities - 1, total - first, minimum):
            yield (first,) + rest


def generate_city_plans(country: str, nights: int, catalog, start_date: date) -> list[CityPlan]:
    destinations = catalog.catalog.destinations
    co = _find_country(destinations, country)
    if co is None:
        return []
    per_city = destinations["rules"]["min_nights_per_city"]
    if per_city < 1 or nights < per_city:
        return []

    max_cities = nights // per_city
    names = [c["name"] for c in co["cities"]]
    edges = {(ln["from_city"], ln["to_city"]) for ln in co["links"]}

    sequences = sorted(_sequences(names, edges, max_cities), key=len)  # stable: DFS order within a length

    plans: list[CityPlan] = []
    for seq in sequences:
        for alloc in _allocations(len(seq), nights, per_city):
            stays = []
            check_in = start_date
            for city, n in zip(seq, alloc):
                check_out = check_in + timedelta(days=n)
                stays.append(CityStay(city, check_in, check_out))
                check_in = check_out
            plans.append(CityPlan(co["code"], tuple(stays)))
    return plans
