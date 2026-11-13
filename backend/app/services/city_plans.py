"""G3: rebuild an exact traveler-selected route through the existing complete planner.

No persistence lives here. Preview and apply use this same deterministic proposal function;
modifications.apply and the existing package repository own token checks and the write transaction.
"""
from dataclasses import dataclass, field, replace

from app.engine.build import FOUND, INFEASIBLE, OVER_BUDGET, SEARCH_INCOMPLETE, WITHIN_BUDGET, build_package
from app.engine.constraints import HotelLock, PlanningConstraints, RequiredAttraction, TransferLock
from app.engine.repair import (
    AUTOMATIC_REPAIR, ChangeProposal, ChangedItem, _desc_flight, _desc_hotel,
    _desc_transfer, _desc_visit, request_of,
)
from app.export.to_trip import to_trip_json
from app.lib.catalog_identity import catalog_fingerprint
from app.repositories import packages as repo
from app.rules.common import EDITED, Violation
from app.services.modifications import InvalidCityPlan
from app.validate.validate_trip import validate_trip


@dataclass
class CityPlanProposal(ChangeProposal):
    status: str = INFEASIBLE
    search_complete: bool = True
    city_changes: dict = field(default_factory=dict)
    preserved_items: list[dict] = field(default_factory=list)


def city_plan_options(stored, catalog) -> dict:
    p = stored.package
    country = catalog.indexes.countries_by_code[p.country_code]
    return {
        "package_id": stored.id, "base_version": stored.version,
        "country_code": p.country_code, "country": p.country_name,
        "current_city_plan": [{"city_id": s.city, "nights": s.nights} for s in p.plan.stays],
        "cities": [{"city_id": c["name"], "name": c["name"]} for c in country["cities"]],
        "connections": [{"from_city": e["from_city"], "to_city": e["to_city"]} for e in country["links"]],
        "min_nights_per_city": catalog.catalog.destinations["rules"]["min_nights_per_city"],
        "total_nights": (p.plan.end_date - p.plan.start_date).days,
    }


def validate_city_plan(stored, city_plan, catalog) -> list[tuple[str, int]]:
    options = city_plan_options(stored, catalog)
    allowed = {c["city_id"] for c in options["cities"]}
    known = {c["name"] for country in catalog.catalog.destinations["countries"] for c in country["cities"]}
    edges = {(e["from_city"], e["to_city"]) for e in options["connections"]}
    minimum, total = options["min_nights_per_city"], options["total_nights"]
    errors, seen, plan = [], set(), []
    def error(rule, message):
        errors.append({"field": "city_plan", "rule": rule, "message": message})
    if not city_plan:
        error("CITY_PLAN_EMPTY", "Choose at least one city.")
    for stop in city_plan:
        city, nights = (stop["city_id"], stop["nights"]) if isinstance(stop, dict) else (stop.city_id, stop.nights)
        plan.append((city, nights))
        if city not in allowed:
            error("CITY_COUNTRY_MISMATCH" if city in known else "UNKNOWN_CITY",
                  f"{city} is not a catalog city in {options['country']}.")
        if city in seen:
            error("DUPLICATE_CITY", f"Visit {city} only once in the route.")
        seen.add(city)
        if type(nights) is not int or nights < minimum:
            error("MINIMUM_CITY_NIGHTS", f"Stay at least {minimum} consecutive nights in {city}.")
    if all(type(n) is int for _, n in plan) and sum(n for _, n in plan) != total:
        error("TOTAL_NIGHTS_MISMATCH", f"Allocate exactly {total} nights across the route.")
    if len(plan) > total // minimum:
        error("TOO_MANY_CITIES", f"A {total}-night holiday supports at most {total // minimum} cities.")
    for (a, _), (b, _) in zip(plan, plan[1:]):
        if (a, b) not in edges:
            error("INVALID_CITY_CONNECTION", f"The catalog has no directed connection from {a} to {b}.")
    if errors:
        raise InvalidCityPlan(errors)
    return plan


def _parts(p):
    """Semantic pairing preserves shortened stays as one disclosed hotel change."""
    out = {
        "flight:arrival": ("flight:arrival", p.arrival_flight, _desc_flight(p.arrival_flight)),
        "flight:return": ("flight:return", p.return_flight, _desc_flight(p.return_flight)),
    }
    for h in p.hotels:
        out[f"hotel:{h.city}"] = (h.stay_id, h, _desc_hotel(h))
    for t in (p.arrival_transfer, p.departure_transfer, *p.intercity):
        out[t.leg_id] = (t.leg_id, t, _desc_transfer(t))
    for v in p.visits:
        key = f"visit:{v.attraction_id}"
        out[key] = (key, v, _desc_visit(v))
    return out


def _comparison(old, new, catalog):
    from app.services.change_view import catalog_label, item_kind
    before, after, changed, preserved = _parts(old), _parts(new), [], []
    for key in dict.fromkeys([*before, *after]):
        a, b = before.get(key), after.get(key)
        component = (b or a)[0]
        if a is not None and b is not None and a[1] == b[1]:
            preserved.append({"item_id": component, "type": item_kind(component)[0],
                              "name": catalog_label(b[2]["catalog_id"], catalog)})
            continue
        x, y = a[2] if a else None, b[2] if b else None
        if x is None:
            action = "ADDED"
        elif y is None:
            action = "REMOVED"
        elif (x["catalog_id"], x.get("room_id")) != (y["catalog_id"], y.get("room_id")):
            action = "REPLACED"
        elif (x["start"], x["end"]) != (y["start"], y["end"]):
            action = "RESCHEDULED"
        else:
            action = "REPRICED"
        changed.append(ChangedItem(component, AUTOMATIC_REPAIR, action, x, y,
            (y["price_inr"] if y else 0) - (x["price_inr"] if x else 0),
            "Rebuilt to honor the selected city sequence and nights."))
    return changed, preserved


def _retain(old, candidate, request, constraints, catalog, proposed_plan):
    """Greedily retain compatible selections using planner locks, never relaxing the route.

    A retained selection may raise a within-budget total, but may not turn an affordable route into
    an over-budget one. For an already over-budget route we keep its proven minimum cost.
    """
    price_limit = max(old.budget, candidate.total)
    current, locks = candidate, constraints
    def attempt(trial, already_matches):
        nonlocal current, locks
        if already_matches:
            locks = trial
            return
        result = build_package(request, catalog, WITHIN_BUDGET, constraints=trial)
        if (result.status in (FOUND, OVER_BUDGET) and result.package is not None
                and result.package.total <= price_limit
                and [(s.city, s.nights) for s in result.package.plan.stays] == proposed_plan):
            current, locks = result.package, trial
    attempt(replace(locks, arrival_flight_id=old.arrival_flight.flight_id), current.arrival_flight == old.arrival_flight)
    attempt(replace(locks, return_flight_id=old.return_flight.flight_id), current.return_flight == old.return_flight)
    for h in old.hotels:
        same = next((s for s in current.plan.stays if s.stay_id == h.stay_id), None)
        if same is not None:
            trial = replace(locks, locked_hotels={**locks.locked_hotels, h.stay_id: HotelLock(h.hotel_id, h.room_id, h.rooms)})
            attempt(trial, any(n == h for n in current.hotels))
    for t in (old.arrival_transfer, old.departure_transfer, *old.intercity):
        current_t = next((n for n in (current.arrival_transfer, current.departure_transfer, *current.intercity)
                          if n.leg_id == t.leg_id), None)
        if current_t is not None:
            trial = replace(locks, locked_transfers={**locks.locked_transfers, t.leg_id: TransferLock(t.transfer_id, t.pickup)})
            attempt(trial, current_t == t)
    # Existing visits are pinned only on a day still spent in the same catalog city.
    for v in old.visits:
        city = catalog.indexes.attractions_by_id[v.attraction_id]["city"]
        stay = next((s for s in current.plan.stays if s.check_in <= v.start.date() < s.check_out and s.city == city), None)
        if stay is not None:
            trial = replace(locks, required_attractions=[*locks.required_attractions, RequiredAttraction(v.attraction_id, v.start.date(), v.start)])
            attempt(trial, any(n == v for n in current.visits))
    # EDITED permits more than two visits per full day. Retain any additional old visits that
    # remain legal, without imposing the INITIAL planner's population policy on the final edit.
    for v in old.visits:
        if any(n.attraction_id == v.attraction_id for n in current.visits):
            continue
        extra = current.with_(visits=tuple(sorted((*current.visits, v), key=lambda n: (n.start, n.attraction_id))))
        if extra.total <= price_limit and not validate_trip(to_trip_json(extra, catalog), catalog, EDITED):
            current = extra
    return current


def propose_city_plan(stored, command, catalog) -> CityPlanProposal:
    old = stored.package
    plan = validate_city_plan(stored, command.city_plan, catalog)
    if plan == [(s.city, s.nights) for s in old.plan.stays]:
        raise InvalidCityPlan([{"field": "city_plan", "rule": "NO_CHANGE", "message": "Choose a different route or night allocation before previewing."}])
    # Use the same catalog identity policy as booking; never reinterpret a saved package's IDs.
    from app.db import connect
    with connect() as conn:
        row = conn.execute("SELECT catalog_fingerprint FROM packages WHERE id = ?", (stored.id,)).fetchone()
    if row is not None and row[0] != catalog_fingerprint(catalog):
        raise InvalidCityPlan([{"field": "city_plan", "rule": "PACKAGE_CATALOG_MISMATCH", "message": "The package's source catalog has changed. Plan a new holiday before editing its route."}])
    request = request_of(old)
    locks = PlanningConstraints(locked_city_plan=plan)
    result = build_package(request, catalog, WITHIN_BUDGET, constraints=locks)
    if result.status not in (FOUND, OVER_BUDGET) or result.package is None:
        return CityPlanProposal(False, None,
            [Violation(code, message) for code, message in zip(result.reason_codes, result.reasons)]
            or [Violation(result.status, "; ".join(result.reasons) or "The exact route could not be completed.")],
            [], [], old.total, None, None, None, list(result.reasons),
            status=result.status, search_complete=result.search_complete)
    rebuilt = _retain(old, result.package, request, locks, catalog, plan)
    rebuilt = rebuilt.with_(trip_id=old.trip_id, traveler_name=old.traveler_name,
                            home_airport=old.home_airport, country_code=old.country_code,
                            country_name=old.country_name, adults=old.adults,
                            child_ages=old.child_ages, budget=old.budget,
                            status=repo.PLANNED, booking_reference=None)
    # Prove the hard route lock again at the integration boundary.
    if ([(s.city, s.nights) for s in rebuilt.plan.stays] != plan
            or rebuilt.plan.start_date != old.plan.start_date
            or rebuilt.plan.end_date != old.plan.end_date):
        return CityPlanProposal(False, None, [Violation("CITY_PLAN_LOCK_FAILED", "The planner did not honor the exact selected route.")],
                                [], [], old.total, None, None, None, status=SEARCH_INCOMPLETE, search_complete=False)
    violations = validate_trip(to_trip_json(rebuilt, catalog), catalog, EDITED)
    if violations:
        return CityPlanProposal(False, None, violations, [], [], old.total, None, None, None,
                                status=SEARCH_INCOMPLETE, search_complete=False)
    changed, preserved = _comparison(old, rebuilt, catalog)
    before = {s.city: s.nights for s in old.plan.stays}
    after = dict(plan)
    common_old = [s.city for s in old.plan.stays if s.city in after]
    common_new = [city for city, _ in plan if city in before]
    cities = {
        "added": [city for city, _ in plan if city not in before],
        "removed": [s.city for s in old.plan.stays if s.city not in after],
        "reordered": common_old != common_new,
        "nights_changed": [{"city": c, "old_nights": before[c], "new_nights": n}
                           for c, n in plan if c in before and before[c] != n],
    }
    warnings = ["This price is for your chosen route; it is not a claim about the cheapest holiday across other routes."]
    if rebuilt.total > old.budget:
        warnings.append(f"The rebuilt holiday is INR {rebuilt.total - old.budget} over your original budget.")
    return CityPlanProposal(True, rebuilt, [], changed, changed, old.total, rebuilt.total,
                            rebuilt.total - old.total, old.budget - rebuilt.total, warnings,
                            status=OVER_BUDGET if rebuilt.total > old.budget else FOUND,
                            search_complete=True, city_changes=cities, preserved_items=preserved)
