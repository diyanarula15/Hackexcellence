"""Multi-itinerary searches: an in-memory store of the options one search returned, the option
summaries the frontend shows, and the save of the one option the traveler chooses.

Nothing is saved by a search. A search keeps its packages here (30 minutes, at most 100 searches);
only select() writes one of them to the packages table, as a normal PLANNED package.
"""
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass

from app.engine.build import MINIMUM_COST
from app.engine.options import OptionSet
from app.export.to_trip import to_trip_json
from app.lib.time import fmt_dt
from app.repositories import packages as repo
from app.rules.common import INITIAL
from app.services.itinerary import budget_summary, build_day_timeline, price_breakdown
from app.validate.validate_trip import validate_trip

TTL_SECONDS = 30 * 60
MAX_SEARCHES = 100
PROVEN_BADGE = "Proven lowest price for this date"

_lock = threading.Lock()
_searches: "OrderedDict[str, dict]" = OrderedDict()


class SearchExpired(LookupError):
    pass


class OptionNotFound(LookupError):
    pass


class PlanInvalid(Exception):
    def __init__(self, violations):
        super().__init__("planned package breaks a rule")
        self.violations = violations


# ------------------------------------------------------------------ store

def _prune(now: float) -> None:
    """Drop expired searches, then the oldest beyond MAX_SEARCHES. Caller holds _lock."""
    for sid in [k for k, v in _searches.items() if now - v["created"] > TTL_SECONDS]:
        del _searches[sid]
    while len(_searches) > MAX_SEARCHES:
        _searches.popitem(last=False)


def _get(search_id: str, now: float) -> dict:
    _prune(now)
    entry = _searches.get(search_id)
    if entry is None:
        raise SearchExpired(search_id)
    return entry


# ------------------------------------------------------------------ summaries

def _differences(opt: dict, first: dict) -> list[str]:
    """What is different from options[0], each only when true (see the contract)."""
    out = []
    if opt["total_inr"] < first["total_inr"]:
        out.append("Lower price")
    cities, first_cities = opt["cities"], first["cities"]
    seq = [(c["city"], c["nights"]) for c in opt["city_nights"]]
    first_seq = [(c["city"], c["nights"]) for c in first["city_nights"]]
    if set(cities) != set(first_cities):
        out.append("Different city mix")
    elif seq != first_seq:
        out.append("Different night split")
    if opt["stats"]["city_changes"] != first["stats"]["city_changes"]:
        out.append("Fewer city changes" if opt["stats"]["city_changes"] < first["stats"]["city_changes"]
                   else "More city changes")
    if opt["_hotel_ids"] != first["_hotel_ids"]:
        out.append("Different hotel choice")
    if opt["_avg_stars"] != first["_avg_stars"]:
        out.append("Higher-rated stays" if opt["_avg_stars"] > first["_avg_stars"] else "Simpler stays")
    if opt["_flight_ids"] != first["_flight_ids"]:
        out.append("Different flights")
    return out


def _summary(pkg, catalog, rank: int, proven: bool) -> dict:
    ix = catalog.indexes
    plan = pkg.plan
    n = len(plan.stays)
    stars = []
    hotels, names = [], []
    for stay, h in zip(plan.stays, pkg.hotels):
        hotel = ix.hotels_by_id.get(h.hotel_id) or {}
        room = ix.rooms_by_id.get(h.room_id) or {}
        stars.append(hotel.get("stars") or 0)
        hotels.append({
            "city": stay.city, "name": hotel.get("name") or h.hotel_id, "stars": hotel.get("stars"),
            "nights": stay.nights, "room": room.get("name") or h.room_id, "rooms": h.rooms,
        })
    visits = sorted(pkg.visits, key=lambda v: (v.start, v.attraction_id))
    names = [(ix.attractions_by_id.get(v.attraction_id) or {}).get("name") or v.attraction_id for v in visits]
    avg = sum(stars) / len(stars) if stars else 0.0
    hotel_parts = [f"{h['stars']:g}★ {h['name']} ({h['city']})" if h["stars"] is not None
                   else f"{h['name']} ({h['city']})" for h in hotels]

    def flight(f):
        rec = ix.flights_by_id.get(f.flight_id) or {}
        return {"flight_number": rec.get("flight_number") or f.flight_id, "airline": rec.get("airline"),
                "from": f.from_airport, "to": f.to_airport,
                "depart": fmt_dt(f.departure), "arrive": fmt_dt(f.arrival)}

    arr, ret = pkg.arrival_flight, pkg.return_flight
    city_changes = n - 1
    return {
        "option_id": f"opt-{rank}",
        "rank": rank,
        "recommended": rank == 1,
        "proven_minimum": proven,
        "total_inr": pkg.total,
        "budget_inr": pkg.budget,
        "budget_remaining_inr": pkg.budget - pkg.total,
        "country": pkg.country_name,
        "start_date": plan.start_date.isoformat(),
        "end_date": plan.end_date.isoformat(),
        "nights": (plan.end_date - plan.start_date).days,
        "travelers": {"adults": pkg.adults, "child_ages": list(pkg.child_ages)},
        "cities": list(plan.cities),
        "city_nights": [{"city": s.city, "nights": s.nights} for s in plan.stays],
        "flights": {
            "summary": f"{arr.from_airport} → {arr.to_airport} · return {ret.from_airport} → {ret.to_airport}",
            "arrival": flight(arr),
            "return": flight(ret),
        },
        "hotels": hotels,
        "hotel_summary": " · ".join(hotel_parts),
        "attractions": names,
        "experience_summary": (f"{len(names)} visits incl. {', '.join(names[:3])}" if names
                               else "No planned visits"),
        "stats": {"cities": len(plan.cities), "city_changes": city_changes,
                  "transfers": 2 + city_changes, "attractions": len(visits),
                  "avg_stars": round(avg, 1)},
        "badges": [],
        "differences": [],
        "preview": {
            "days": build_day_timeline(pkg, catalog),
            "pricing": price_breakdown(pkg),
            "budget": budget_summary(pkg),
        },
        # comparison helpers, removed before the response is sent
        "_hotel_ids": tuple(h.hotel_id for h in pkg.hotels),
        "_avg_stars": avg,
        "_flight_ids": (arr.flight_id, ret.flight_id),
    }


def _response(search_id: str, original: dict, objective: str, packages, proven: bool, catalog) -> dict:
    summaries = [_summary(p, catalog, i + 1, proven and i == 0) for i, p in enumerate(packages)]
    first = summaries[0]
    lowest = min(s["total_inr"] for s in summaries)
    for s in summaries:
        s["differences"] = [] if s is first else _differences(s, first)
        badges = []
        if s is first:
            badges.append("Recommended")
        if s["proven_minimum"]:
            badges.append(PROVEN_BADGE)
        if s["total_inr"] == lowest:
            badges.append("Lowest price in this set")
        s["badges"] = badges
    count = len(summaries)
    if count >= 3:
        headline, note = "We found 3 holiday options for your trip", None
    elif count == 2:
        headline, note = "We found 2 distinct holiday options for your search.", None
    else:
        headline = "We found 1 complete holiday option for your search."
        note = "No additional distinct package options were verified."
    for s in summaries:
        for key in ("_hotel_ids", "_avg_stars", "_flight_ids"):
            s.pop(key)
    return {
        "status": "OPTIONS",
        "search_id": search_id,
        "objective": objective,
        "count": count,
        "headline": headline,
        "subline": "Choose the one you like best",
        "note": note,
        "request": original,
        "options": summaries,
    }


def open_search(trip, original: dict, objective: str, found: OptionSet, catalog) -> dict:
    """Remember the options of one search and return the OPTIONS response. Saves nothing."""
    search_id = uuid.uuid4().hex
    proven = objective == MINIMUM_COST
    response = _response(search_id, original, objective, found.packages, proven, catalog)
    now = time.monotonic()
    with _lock:
        _prune(now)
        _searches[search_id] = {
            "created": now, "trip": trip, "original": original, "objective": objective,
            "primary": found.primary, "complete": found.complete,
            "packages": {f"opt-{i + 1}": p for i, p in enumerate(found.packages)},
            "chosen": {},
        }
    return response


def choose(search_id: str, option_id: str, catalog) -> tuple[str, bool]:
    """Save one option as a PLANNED package. Returns (package_id, created). Choosing the same option
    of the same search again returns the package saved the first time."""
    with _lock:
        entry = _get(search_id, time.monotonic())
        package = entry["packages"].get(option_id)
        if package is None:
            raise OptionNotFound(option_id)
        existing = entry["chosen"].get(option_id)
        if existing is not None:
            return existing, False
        violations = validate_trip(to_trip_json(package, catalog), catalog, INITIAL)
        if violations:
            raise PlanInvalid(violations)
        package_id = repo.save_package(package, request=entry["original"])
        entry["chosen"][option_id] = package_id
        return package_id, True
