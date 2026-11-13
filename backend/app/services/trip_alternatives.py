"""Trip alternatives: the nearest changed requests that DO have a valid holiday. Read-only.

  POST /api/trip-alternatives  (see app/routes/alternatives.py)

Every price comes from calculate_date_price (the planner, MINIMUM_COST, cached). Only FOUND results
with a proven minimum become suggestions, and each suggestion changes exactly one field of the
request. Nothing is saved. The whole search makes at most MAX_PLANNER_SEARCHES calls, the original
request included, cache hits counted too.
"""

from datetime import timedelta

from app.rules.request import resolve_country
from app.services.date_prices import FOUND, calculate_date_price, data_window, enumerate_valid_start_dates

MAX_PLANNER_SEARCHES = 30
START_DATE_SPAN_DAYS = 7
DEPARTURE_SUGGESTIONS = 2
NIGHT_STEPS = (-1, 1, -2, 2, -3, 3)   # smaller change first; on a tie, fewer nights first


class _Searches:
    """Counts calculate_date_price calls and refuses to make more than MAX_PLANNER_SEARCHES."""

    def __init__(self, catalog):
        self.catalog = catalog
        self.calls = 0

    @property
    def left(self) -> bool:
        return self.calls < MAX_PLANNER_SEARCHES

    def price(self, request, day):
        """The DatePriceResult for `request` starting on `day`, or None when the cap is reached."""
        if not self.left:
            return None
        self.calls += 1
        return calculate_date_price(request, day, self.catalog)


def _proven(result) -> bool:
    return (result is not None and result.status == FOUND and result.proven_minimum
            and isinstance(result.min_total_inr, int) and not isinstance(result.min_total_inr, bool))


def _fmt(day) -> str:
    return f"{day.day} {day:%b %Y}"


def api_fields(request, catalog) -> dict:
    """The 7 trip fields as the API names them, normalised (same shape as the traveler's request)."""
    country = resolve_country(request.destination_country, catalog)
    return {
        "departure": request.departure_airport,
        "country": country["name"] if country else request.destination_country,
        "start_date": request.start_date.isoformat(),
        "nights": request.nights,
        "adults": request.adults,
        "child_ages": list(request.children_ages),
        "budget": request.budget,
    }


def _suggestion(kind, label, field, old, new, variant, result, request, catalog) -> dict:
    return {
        "kind": kind,
        "label": label,
        "change": {"field": field, "from": old, "to": new},
        "request": api_fields(variant, catalog),
        "min_total_inr": result.min_total_inr,
        "within_budget": result.min_total_inr <= request.budget,
    }


def _start_date_suggestions(request, catalog, searches) -> list[dict]:
    start = request.start_date
    eligible = set(enumerate_valid_start_dates(
        request, catalog, start - timedelta(days=START_DATE_SPAN_DAYS),
        start + timedelta(days=START_DATE_SPAN_DAYS)))
    # ordered by distance, then earlier date first
    candidates = [(k, day) for k in range(1, START_DATE_SPAN_DAYS + 1)
                  for day in (start - timedelta(days=k), start + timedelta(days=k)) if day in eligible]
    nearest = {"before": None, "after": None}
    for k, day in candidates:
        side = "before" if day < start else "after"
        if nearest[side] is not None:
            continue
        result = searches.price(request, day)
        if result is None:
            break
        if _proven(result):
            nearest[side] = (k, day, result)
        if all(nearest.values()):
            break
    found = sorted((hit for hit in nearest.values() if hit), key=lambda hit: (hit[0], hit[1]))
    out = []
    for _k, day, result in found:
        variant = request.model_copy(update={"start_date": day})
        out.append(_suggestion(
            "START_DATE", f"Start on {_fmt(day)} instead of {_fmt(start)}",
            "start_date", start.isoformat(), day.isoformat(), variant, result, request, catalog))
    return out


def _departure_suggestions(request, catalog, searches) -> list[dict]:
    cities = {}  # airport -> city, in catalog order
    for dc in catalog.catalog.destinations["departure_cities"]:
        cities.setdefault(dc["airport"], dc["city"])
    priced = []
    for index, airport in enumerate(cities):
        if airport == request.departure_airport:
            continue
        variant = request.model_copy(update={"departure_airport": airport})
        result = searches.price(variant, request.start_date)
        if result is None:
            break
        if _proven(result):
            priced.append((result.min_total_inr, index, airport, variant, result))
    priced.sort(key=lambda row: (row[0], row[1]))   # cheapest first, ties in catalog order
    out = []
    for _total, _index, airport, variant, result in priced[:DEPARTURE_SUGGESTIONS]:
        old_city = cities.get(request.departure_airport, request.departure_airport)
        out.append(_suggestion(
            "DEPARTURE",
            f"Fly from {cities[airport]} ({airport}) instead of {old_city} ({request.departure_airport})",
            "departure", request.departure_airport, airport, variant, result, request, catalog))
    return out


def _nights_suggestions(request, catalog, searches) -> list[dict]:
    rules = catalog.catalog.destinations["rules"]
    _first, last_departure = data_window(catalog)
    for step in NIGHT_STEPS:
        nights = request.nights + step
        if not rules["min_nights"] <= nights <= rules["max_nights"]:
            continue
        if request.start_date + timedelta(days=nights) > last_departure:
            continue
        variant = request.model_copy(update={"nights": nights})
        result = searches.price(variant, request.start_date)
        if result is None:
            break
        if _proven(result):
            return [_suggestion(
                "NIGHTS", f"Stay {nights} nights instead of {request.nights}",
                "nights", request.nights, nights, variant, result, request, catalog)]
    return []


def find_alternatives(request, catalog) -> dict:
    """Price the request, then search for the nearest changed requests that have a proven holiday."""
    searches = _Searches(catalog)
    original = searches.price(request, request.start_date)
    suggestions = []
    suggestions += _start_date_suggestions(request, catalog, searches)
    suggestions += _departure_suggestions(request, catalog, searches)
    suggestions += _nights_suggestions(request, catalog, searches)
    return {
        "original": api_fields(request, catalog),
        "original_status": original.status,
        "suggestions": suggestions,
        "planner_searches": searches.calls,
    }
