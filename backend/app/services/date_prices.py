"""Price Landscape (Phase 7A): the proven cheapest complete holiday for every eligible start date.

Every price comes from the Phase 3 planner run with objective MINIMUM_COST - flights, every hotel
night, airport and intercity transfers, the required attractions and all quantities - never an
estimate. A date gets exactly one status:

  FOUND              the minimum-cost search completed and a valid package exists; the total is the
                     proven minimum (an OVER_BUDGET planner result is FOUND here: budget is not a
                     feasibility constraint for a price calendar)
  INFEASIBLE         the search completed and proved that no valid package exists
  SEARCH_INCOMPLETE  no proof either way (search limit, time budget, planner error, or missing proof
                     metadata); never carries a price

Nothing is persisted: no package rows, ids, reservations or catalog changes.
"""

import calendar
import copy
import dataclasses
import logging
import time
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.engine.build import (FOUND as PLAN_FOUND, INFEASIBLE as PLAN_INFEASIBLE, MINIMUM_COST,
                              OVER_BUDGET as PLAN_OVER_BUDGET, build_package)
from app.rules.request import resolve_country
from app.services.date_price_cache import (CACHE, DatePriceCache, cache_key, catalog_fingerprint,
                                           requirements_key)

log = logging.getLogger(__name__)

FOUND, INFEASIBLE, SEARCH_INCOMPLETE = "FOUND", "INFEASIBLE", "SEARCH_INCOMPLETE"
MAX_RANGE_DAYS = 62              # about two calendar months per request; clients page by month
DEFAULT_TIME_BUDGET_S = 25.0     # stop starting new searches after this; the rest are SEARCH_INCOMPLETE

# why a cell is SEARCH_INCOMPLETE
SEARCH_LIMIT = "SEARCH_LIMIT"           # the planner stopped before it could prove anything
TIME_BUDGET = "TIME_BUDGET"             # not computed in this request; ask again (cached cells are free)
PLANNER_ERROR = "PLANNER_ERROR"         # unexpected error; details are only logged
NO_PROOF = "NO_PROOF"                   # the planner result lacked completeness/minimum evidence


class DateRangeError(ValueError):
    """A comparison range that cannot be served (reversed, too large, malformed)."""


@dataclass(frozen=True)
class DatePriceResult:
    date: date
    status: str
    min_total_inr: int | None
    proven_minimum: bool
    catalog_fingerprint: str
    requirements: tuple            # requirements_key(...) - who travels, from where, how long
    incomplete_reason: str | None = None
    combinations_evaluated: int | None = None   # planner instrumentation, when reported

    def as_cell(self) -> dict:
        return {"date": self.date.isoformat(), "status": self.status,
                "min_total_inr": self.min_total_inr, "proven_minimum": self.proven_minimum}


# ------------------------------------------------------------------ date enumeration

def data_window(catalog) -> tuple[date, date]:
    """(first night, last departure) from the catalog's own rules."""
    w = catalog.catalog.destinations["rules"]["data_window"]
    return date.fromisoformat(w["first_night"]), date.fromisoformat(w["last_departure"])


def enumerate_valid_start_dates(request, catalog, range_start: date, range_end: date) -> list[date]:
    """Every start date in [range_start, range_end] whose whole trip fits the catalog window.

    A trip of N nights starting on S ends (return flight, no hotel night) on S + N days, which must
    be on or before the window's last departure; S itself must be on or after its first night.
    Eligible is not feasible: an eligible date can still have no flights or rooms.
    """
    if range_start > range_end:
        raise DateRangeError("range_start must be on or before range_end")
    first, last = data_window(catalog)
    nights = int(request.nights)
    lo = max(range_start, first)
    hi = min(range_end, last - timedelta(days=nights))
    out, d = [], lo
    while d <= hi:
        out.append(d)
        d += timedelta(days=1)
    return out


def default_range(start: date) -> tuple[date, date]:
    """The calendar month of the traveler's chosen start date."""
    return start.replace(day=1), start.replace(day=calendar.monthrange(start.year, start.month)[1])


def check_range(range_start: date, range_end: date) -> None:
    if range_start > range_end:
        raise DateRangeError("range_start must be on or before range_end")
    if (range_end - range_start).days + 1 > MAX_RANGE_DAYS:
        raise DateRangeError(f"Ask for at most {MAX_RANGE_DAYS} days at a time (one or two months).")


# ------------------------------------------------------------------ one date

def _with_start_date(request, start_date: date):
    """A copy of the request with another start date; the original is never touched."""
    if hasattr(request, "model_copy"):
        return request.model_copy(update={"start_date": start_date})
    if dataclasses.is_dataclass(request):
        return dataclasses.replace(request, start_date=start_date)
    clone = copy.copy(request)
    clone.start_date = start_date
    return clone


def _requirements(request, catalog) -> tuple:
    country = resolve_country(request.destination_country, catalog)
    code = country["code"] if country else str(request.destination_country)
    return requirements_key(request.departure_airport, code, request.nights, request.adults,
                            request.children_ages)


def interpret(result, start_date: date, fingerprint: str, requirements: tuple) -> DatePriceResult:
    """Map a MINIMUM_COST PlanningResult to a calendar cell. Proof is required, never assumed."""
    def cell(status, total=None, proven=False, reason=None):
        stats = getattr(result, "stats", None)
        return DatePriceResult(start_date, status, total, proven, fingerprint, requirements, reason,
                               getattr(stats, "combinations_evaluated", None))

    status = getattr(result, "status", None)
    complete = getattr(result, "search_complete", None) is True
    if not complete:
        return cell(SEARCH_INCOMPLETE, reason=SEARCH_LIMIT if status == "SEARCH_INCOMPLETE" else NO_PROOF)
    if status in (PLAN_FOUND, PLAN_OVER_BUDGET):
        package = getattr(result, "package", None)
        total = getattr(result, "cheapest_total", None)
        package_total = getattr(package, "total", None)
        # a FOUND cell needs: a complete package, an integer total, and the two agreeing
        if (package is None or not isinstance(total, int) or isinstance(total, bool)
                or package_total != total or total < 0):
            return cell(SEARCH_INCOMPLETE, reason=NO_PROOF)
        return cell(FOUND, total, True)
    if status == PLAN_INFEASIBLE:
        if "INVALID_REQUEST" in (getattr(result, "reason_codes", None) or []):
            # cannot happen for an enumerated date; never present it as "no trip exists"
            return cell(SEARCH_INCOMPLETE, reason=NO_PROOF)
        return cell(INFEASIBLE)
    return cell(SEARCH_INCOMPLETE, reason=NO_PROOF)


def calculate_date_price(request, start_date: date, catalog, *, cache: DatePriceCache | None = CACHE,
                         planner=build_package, counters: dict | None = None) -> DatePriceResult:
    """The proven minimum complete-holiday price for one start date (cache first)."""
    fingerprint = catalog_fingerprint(catalog)
    reqs = _requirements(request, catalog)
    key = cache_key(fingerprint, reqs, start_date)
    if cache is not None:
        hit = cache.get(key)
        if hit is not None:
            _count(counters, "cache_hits")
            return hit
        _count(counters, "cache_misses")
    _count(counters, "planner_searches")
    try:
        result = planner(_with_start_date(request, start_date), catalog, objective=MINIMUM_COST)
    except Exception:  # noqa: BLE001 - logged in full; the client only sees an incomplete cell
        log.exception("date-price search failed for %s", start_date)
        out = DatePriceResult(start_date, SEARCH_INCOMPLETE, None, False, fingerprint, reqs, PLANNER_ERROR)
    else:
        out = interpret(result, start_date, fingerprint, reqs)
    _count(counters, "searches_incomplete" if out.status == SEARCH_INCOMPLETE else "searches_completed")
    if out.combinations_evaluated is not None:
        _count(counters, "combinations_evaluated", out.combinations_evaluated)
    if cache is not None:
        cache.put(key, out)
    return out


def _count(counters, name, n=1):
    if counters is not None:
        counters[name] = counters.get(name, 0) + n


# ------------------------------------------------------------------ comparisons

def calculate_proven_savings(reference: DatePriceResult, alternative: DatePriceResult) -> int | None:
    """reference - alternative, only when both are proven minima for the same travelers and catalog.
    None otherwise. A positive value is a genuine saving; zero or negative is not one."""
    for r in (reference, alternative):
        if r is None or r.status != FOUND or not r.proven_minimum or not isinstance(r.min_total_inr, int):
            return None
    if reference.requirements != alternative.requirements:
        return None
    if reference.catalog_fingerprint != alternative.catalog_fingerprint:
        return None
    return reference.min_total_inr - alternative.min_total_inr


def _cheapest(results: list[DatePriceResult]) -> DatePriceResult | None:
    """Lowest proven price; ties go to the earliest date."""
    proven = [r for r in results if r.status == FOUND and r.proven_minimum]
    return min(proven, key=lambda r: (r.min_total_inr, r.date)) if proven else None


@dataclass
class Calendar:
    request: object
    reference_date: date
    range_start: date
    range_end: date
    results: list[DatePriceResult]
    counters: dict = field(default_factory=dict)
    elapsed_ms: float = 0.0


def build_calendar(request, catalog, range_start: date | None = None, range_end: date | None = None, *,
                   cache: DatePriceCache | None = CACHE, planner=build_package,
                   time_budget_s: float = DEFAULT_TIME_BUDGET_S) -> Calendar:
    """Price every eligible start date in the range, chronologically. Dates not reached within the
    time budget come back SEARCH_INCOMPLETE (TIME_BUDGET) and are not cached; asking again continues
    where this left off because finished dates are cached."""
    if range_start is None and range_end is None:
        range_start, range_end = default_range(request.start_date)
    elif range_start is None or range_end is None:
        raise DateRangeError("Give both range_start and range_end, or neither.")
    check_range(range_start, range_end)
    t0 = time.perf_counter()
    counters: dict = {}
    dates = enumerate_valid_start_dates(request, catalog, range_start, range_end)
    counters["dates_requested"] = len(dates)
    fingerprint = catalog_fingerprint(catalog)
    reqs = _requirements(request, catalog)
    results = []
    for d in dates:
        over_time = time.perf_counter() - t0 > time_budget_s
        if over_time:
            hit = cache.get(cache_key(fingerprint, reqs, d)) if cache is not None else None
            if hit is not None:
                _count(counters, "cache_hits")
                results.append(hit)
            else:
                _count(counters, "searches_incomplete")
                results.append(DatePriceResult(d, SEARCH_INCOMPLETE, None, False, fingerprint, reqs, TIME_BUDGET))
            continue
        results.append(calculate_date_price(request, d, catalog, cache=cache, planner=planner, counters=counters))
    return Calendar(request, request.start_date, range_start, range_end, results, counters,
                    round((time.perf_counter() - t0) * 1000, 1))


def calendar_payload(cal: Calendar, catalog) -> dict:
    """The JSON contract for the Phase 7B Price Landscape (see routes/date_prices.py)."""
    req = cal.request
    country = resolve_country(req.destination_country, catalog) or {}
    budget = getattr(req, "budget", None)
    results = cal.results
    fully = all(r.status != SEARCH_INCOMPLETE for r in results)
    best = _cheapest(results)
    proven_prices = [r.min_total_inr for r in results if r.status == FOUND]
    reference = next((r for r in results if r.date == cal.reference_date), None)

    cells = []
    for r in results:
        c = r.as_cell()
        c["within_budget"] = (r.min_total_inr <= budget) if (r.status == FOUND and budget is not None) else None
        diff = calculate_proven_savings(reference, r) if reference is not None else None
        c["difference_vs_reference_inr"] = (-diff) if diff is not None else None   # alt - ref
        c["proven_savings_inr"] = diff if (diff is not None and diff > 0) else None
        if r.status == SEARCH_INCOMPLETE:
            c["incomplete_reason"] = r.incomplete_reason
        cells.append(c)

    savings = [calculate_proven_savings(reference, r) for r in results] if reference else []
    savings = [s for s in savings if s is not None]
    best_saving = max(savings) if savings else None
    comparison = {
        "reference_date": cal.reference_date.isoformat(),
        "reference_in_range": reference is not None,
        "reference_status": reference.status if reference else None,
        "reference_min_total_inr": reference.min_total_inr if reference and reference.status == FOUND else None,
        # largest genuine saving against the reference among PROVEN dates (null when not provable)
        "max_proven_savings_inr": (best_saving if best_saving and best_saving > 0 else 0)
        if best_saving is not None else None,
        "best_saving_date": (best.date.isoformat() if best and best_saving and best_saving > 0 else None),
    }
    counts = {s: sum(1 for r in results if r.status == s) for s in (FOUND, INFEASIBLE, SEARCH_INCOMPLETE)}
    return {
        "country": country.get("name", req.destination_country),
        "country_code": country.get("code"),
        "departure": req.departure_airport,
        "nights": req.nights,
        "adults": req.adults,
        "child_ages": list(req.children_ages),
        "budget_inr": budget,
        "range_start": cal.range_start.isoformat(),
        "range_end": cal.range_end.isoformat(),
        "data_window": {k: v.isoformat() for k, v in zip(("first_night", "last_departure"), data_window(catalog))},
        "dates": cells,
        "status_counts": counts,
        "range_fully_evaluated": fully,
        # lowest among dates whose minimum was PROVEN (always meaningful)
        "lowest_proven_date": best.date.isoformat() if best else None,
        "lowest_proven_total_inr": best.min_total_inr if best else None,
        "highest_proven_total_inr": max(proven_prices) if proven_prices else None,
        # the cheapest date of the whole range - only claimed when every date was evaluated
        "cheapest_date": best.date.isoformat() if (best and fully) else None,
        "cheapest_total_inr": best.min_total_inr if (best and fully) else None,
        "comparison": comparison,
        "diagnostics": {
            "dates_requested": cal.counters.get("dates_requested", 0),
            "cache_hits": cal.counters.get("cache_hits", 0),
            "cache_misses": cal.counters.get("cache_misses", 0),
            "planner_searches": cal.counters.get("planner_searches", 0),
            "searches_completed": cal.counters.get("searches_completed", 0),
            "searches_incomplete": cal.counters.get("searches_incomplete", 0),
            "planner_combinations_evaluated": cal.counters.get("combinations_evaluated", 0),
            "elapsed_ms": cal.elapsed_ms,
        },
    }
