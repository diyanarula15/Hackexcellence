"""Several distinct complete packages for one request (the "multi-itinerary" search).

The primary result is exactly build_package(request, catalog, objective). Only when that is FOUND
does the search look for up to count-1 more packages. Every extra is a complete, validator-clean,
within-budget package whose stay pattern differs from the primary and from every other option:

    signature(package) = ((city, nights) for each stay in order, hotel id of each stay)

Two packages with the same signature differ only in flights, transfers or times, so only the
cheapest of them is kept. The extras are the cheapest distinct signatures found by a best-first
branch and bound over the same triples and slot products build.py uses, enriched the same way the
primary was.

Honesty: the search is capped (MAX_OPTION_COMBINATIONS). When the cap is hit `complete` is False and
the extras found so far are returned without any claim that they are the cheapest possible ones.
"""
from dataclasses import dataclass

from app.engine.build import (FOUND, WITHIN_BUDGET, PlanningResult, _product_in_cost_order,
                              _Search, build_package)
from app.engine.constraints import PlanningConstraints
from app.engine.model import Package
from app.export.to_trip import to_trip_json
from app.rules.common import INITIAL
from app.validate.validate_trip import validate_trip

MAX_OPTION_COMBINATIONS = 20_000     # work cap for the extra search only (the primary has its own)


@dataclass(frozen=True)
class OptionSet:
    primary: PlanningResult
    packages: tuple[Package, ...]     # packages[0] is primary.package; empty unless primary is FOUND
    complete: bool                    # False when the extra search hit its cap


def signature(package: Package) -> tuple:
    """Where the traveler stays: (city, nights) per stay in order, and the hotel of each stay."""
    return (tuple((s.city, s.nights) for s in package.plan.stays),
            tuple(h.hotel_id for h in package.hotels))


def cheapest_per_signature(packages) -> dict:
    """signature -> the cheapest package with that signature (first one wins a tie)."""
    best: dict = {}
    for p in packages:
        sig = signature(p)
        if sig not in best or p.total < best[sig].total:
            best[sig] = p
    return best


def _clean(pkg: Package, catalog) -> bool:
    return not validate_trip(to_trip_json(pkg, catalog), catalog, INITIAL)


class _Capped(Exception):
    pass


def find_package_options(request, catalog, objective: str = WITHIN_BUDGET, count: int = 3) -> OptionSet:
    primary = build_package(request, catalog, objective)
    if primary.status != FOUND or primary.package is None:
        return OptionSet(primary, (), True)
    if not _clean(primary.package, catalog):
        return OptionSet(primary, (), True)          # build_package's own check is re-run by the route
    if count <= 1:
        return OptionSet(primary, (primary.package,), True)

    s = _Search(request, catalog, PlanningConstraints())
    enrich_mode = "BUDGET" if objective == WITHIN_BUDGET else "FREE"
    budget, wanted = request.budget, count - 1
    primary_sig = signature(primary.package)
    best: dict = {}                                  # signature -> cheapest enriched package so far
    limit = budget + 1                               # a candidate must total below this to matter
    work, complete = 0, True

    def refresh_limit():
        nonlocal limit
        if len(best) >= wanted:
            limit = sorted(p.total for p in best.values())[wanted - 1]
        else:
            limit = budget + 1

    try:
        for bound, _, plan, arr, ret, slots, floor in sorted(s.triples(), key=lambda t: (t[0], t[1])):
            if bound >= limit:
                break                                # sorted by bound: nothing later can enter the set
            flights, n = arr.price + ret.price, len(plan.stays)
            for slot_sum, choice in _product_in_cost_order(slots):
                lower = flights + slot_sum + floor
                if lower >= limit:
                    break
                work += 1
                if work > MAX_OPTION_COMBINATIONS:
                    raise _Capped()
                sig = (tuple((st.city, st.nights) for st in plan.stays),
                       tuple(c[0].hotel_id for c in choice[:n]))
                if sig == primary_sig:
                    continue
                known = best.get(sig)
                if known is not None and lower >= known.total:
                    continue                         # cannot beat the cheapest already kept
                arrival_t, departure_t, legs = choice[0][1], choice[n - 1][2], choice[n:]
                sched = s.attractions(plan, arrival_t, legs, departure_t)
                if not sched.feasible:
                    continue
                pkg = s.assemble(plan, arr, ret, choice, sched.visits)
                if pkg.total >= limit or pkg.total > budget:
                    continue
                if not s.validated(pkg):
                    continue
                pkg = s.enrich(pkg, enrich_mode)
                if pkg.total > budget or (known is not None and pkg.total >= known.total):
                    continue
                best[sig] = pkg
                refresh_limit()
    except _Capped:
        complete = False

    extras = sorted(best.items(), key=lambda kv: (kv[1].total, str(kv[0])))[:wanted]
    kept = [primary.package] + [p for _, p in extras]
    # every final option is re-checked; a failing one is dropped, never shown
    clean = [p for p in kept if _clean(p, catalog)]
    if clean[:1] != [primary.package]:
        return OptionSet(primary, (), complete)
    return OptionSet(primary, tuple(clean), complete)
