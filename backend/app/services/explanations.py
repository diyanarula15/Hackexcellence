"""Plain-language, structured explanation of a planning result that has no package to show.

Built only from the PlanningResult the search already produced (its status, the proven cheapest
total and its `failures` list). Nothing is searched again here, and no wording goes beyond what the
data proves:

  OVER_BUDGET       the proven cheapest valid holiday and how far it is over the budget
  INFEASIBLE        a reason is ALL only when it blocked every city plan (or is request-level, such
                    as no flight at all); a reason that stopped only some plans is SOME. When no
                    reason is ALL, the summary says the combination left no valid package.
  SEARCH_INCOMPLETE the search did not finish; this is never a claim that no holiday exists.
  FOUND             None (there is nothing to explain).
"""
from datetime import date, timedelta

from app.engine.build import FOUND, INFEASIBLE, OVER_BUDGET, SEARCH_INCOMPLETE
from app.lib.money import rupees
from app.rules.request import resolve_country

ALL, SOME, REQUEST = "ALL", "SOME", "REQUEST"

# Plan-level reasons, completing "... had {phrase}." (k of n possible city plans, or every one).
PLAN_PHRASE = {
    "NO_HOTEL_AVAILABILITY": "no hotel with rooms free every night of its stay",
    "NO_HOTEL_CAPACITY": "no room type large enough for the travelers",
    "NO_ARRIVAL_TRANSFER": "no airport transfer from the arrival airport to a bookable hotel after the flight lands",
    "NO_RETURN_TRANSFER": "no airport transfer from a bookable hotel to the return flight",
    "NO_INTERCITY_TRANSFER": "no transfer between two of its cities on the travel day",
    "NO_REQUIRED_ATTRACTION": "no way to fit a required attraction into its days",
    "NO_ARRIVAL_FLIGHT": "no bookable arrival flight into its first city on the start date",
    "NO_RETURN_FLIGHT": "no bookable return flight out of its last city on the end date",
    "LOCKED_CHOICE_INCOMPATIBLE": "a locked choice that does not fit",
    "NO_COMPATIBLE_CITY_PLAN": "no complete combination of flights, hotels and transfers",
}


def explain(result, request, catalog) -> dict | None:
    """The explanation for a PlanningResult of a request, or None when there is nothing to explain
    (a package was found), the result is not a search result (a repair proposal, an invalid request), or an
    INFEASIBLE result has no structured failure data."""
    if result.proposal is not None or "INVALID_REQUEST" in result.reason_codes:
        return None
    if result.status == OVER_BUDGET:
        if not result.search_complete or result.cheapest_total is None:
            return _incomplete()
        return _over_budget(result, request)
    if result.status == INFEASIBLE:
        return _infeasible(result, request, catalog)
    if result.status == SEARCH_INCOMPLETE:
        return _incomplete()
    return None  # FOUND


# ------------------------------------------------------------------ kinds

def _over_budget(result, request) -> dict:
    budget, cheapest = request.budget, result.cheapest_total
    over = cheapest - budget
    return {
        "kind": OVER_BUDGET,
        "headline": f"No complete holiday fits your budget of {rupees(budget)}",
        "summary": (f"The cheapest valid holiday for your dates and travelers costs {rupees(cheapest)} "
                    f"- {rupees(over)} over your budget."),
        "reasons": [{"code": "OVER_BUDGET", "scope": REQUEST,
                     "message": f"The cheapest valid package costs {rupees(cheapest)}, which is "
                                f"{rupees(over)} over the budget of {rupees(budget)}."}],
        "suggest_alternatives": True,
    }


def _incomplete() -> dict:
    return {
        "kind": SEARCH_INCOMPLETE,
        "headline": "We couldn't finish checking every holiday combination",
        "summary": ("The search stopped before it had checked every possible combination, so this is not an "
                    "answer about whether a holiday is possible. Try another start date or fewer nights."),
        "reasons": [],
        "suggest_alternatives": False,
    }


def _infeasible(result, request, catalog) -> dict | None:
    if not result.failures:       # no structured search data (never produced by the real search): nothing to add
        return None
    reasons = [_reason(e, request, catalog) for e in result.failures]
    blockers = [r for r in reasons if r["scope"] == ALL]
    if blockers:
        summary = f"{blockers[0]['message']} So no complete holiday is possible for these dates and travelers."
    elif reasons:
        summary = ("No single reason stopped every possible city plan. Together, the reasons below "
                   "left no valid package.")
    else:
        summary = ("The search checked every possible combination and found no valid package, "
                   "but it did not record a specific cause.")
    return {
        "kind": INFEASIBLE,
        "headline": "No complete holiday found for your search",
        "summary": summary,
        "reasons": reasons,
        "suggest_alternatives": True,
    }


# ------------------------------------------------------------------ reasons

def _reason(entry: dict, request, catalog) -> dict:
    code, failed, total = entry["code"], entry["plans_failed"], entry["plans_total"]
    scope = ALL if failed == total else SOME
    return {"code": code, "scope": scope,
            "message": _message(code, scope, failed, total, entry["message"], request, catalog)}


def _message(code, scope, failed, total, example, request, catalog) -> str:
    country = _country_name(request, catalog)
    dep = request.departure_airport
    start = request.start_date
    back = start + timedelta(days=request.nights)
    party = request.adults + len(request.children_ages)

    if code == "INSUFFICIENT_FLIGHT_SEATS":       # request-level only: no flight in that direction has the seats
        if "leaves" in example:
            return f"No flight leaves {country} for {dep} on {_date(back)} with {party} free seats."
        return f"No flight from {dep} lands in {country} on {_date(start)} with {party} free seats."
    if total == 0:                                 # no city plan at all: request-level wording
        if code == "NO_COMPATIBLE_CITY_PLAN":
            return f"No city plan of {request.nights} nights exists in {country}."
        if code == "NO_ARRIVAL_FLIGHT":
            return f"No bookable flight from {dep} lands in {country} on {_date(start)}."
        if code == "NO_RETURN_FLIGHT":
            return f"No bookable flight leaves {country} for {dep} on {_date(back)}."
        return example
    phrase = PLAN_PHRASE.get(code)
    if phrase is None:
        return example if scope == ALL else f"{failed} of {total} possible city plans failed: {example}"
    if scope == ALL:
        if total == 1:
            return f"The only possible city plan had {phrase}."
        return f"Every one of the {total} possible city plans had {phrase}."
    return f"{failed} of {total} possible city plans had {phrase}."


# ------------------------------------------------------------------ helpers

def _country_name(request, catalog) -> str:
    country = resolve_country(request.destination_country, catalog)
    return country["name"] if country else request.destination_country


def _date(d: date) -> str:
    return f"{d.day} {d:%b %Y}"
