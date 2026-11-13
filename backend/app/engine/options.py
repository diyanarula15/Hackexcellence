"""Three labelled packages for one request (problem statement G4).

    Cheapest    the lowest total price (the proven minimum build_package finds)
    Fastest     the least total travel time: both flight durations plus every transfer between
                cities, within budget
    Best rated  the highest average hotel stars per night (guest rating does not count), within
                budget

Ties: when one package is best on two criteria it is shown once and carries both labels. A tie in
the metric itself counts as best too ("on a tie show either one"), so the cheapest package also
carries Fastest when no package travels less, and so on.

Fastest and Best rated use a best-first search over the same triples and slots build.py uses. Each
slot option is keyed (metric, cost) as one integer, metric * _SCALE + cost, so the slot product is
visited in metric order and, within one metric value, in cost order. The first validated
within-budget package at the lowest metric is the answer; a tie in the metric goes to the cheaper
one.

Honesty: that search is capped (MAX_OPTION_COMBINATIONS). When the cap is hit `complete` is False
and the label is not given to a package that was not proven best.
"""

from dataclasses import dataclass

from app.engine.build import (
    FOUND,
    MINIMUM_COST,
    WITHIN_BUDGET,
    PlanningResult,
    _product_in_cost_order,
    _Search,
    build_package,
)
from app.engine.constraints import PlanningConstraints
from app.engine.model import Package
from app.export.to_trip import to_trip_json
from app.rules.common import INITIAL
from app.validate.validate_trip import validate_trip

MAX_OPTION_COMBINATIONS = 20_000  # work cap for each labelled search (the cheapest has its own)
CHEAPEST, FASTEST, BEST_RATED = "Cheapest", "Fastest", "Best rated"
MAX_STARS = 5
_SCALE = 10**9  # above any sum of slot prices, so metric * _SCALE + cost sorts
# by metric first and by cost second


@dataclass(frozen=True)
class OptionSet:
    primary: PlanningResult
    packages: tuple[Package, ...]  # empty unless primary is FOUND
    complete: bool  # False when a labelled search hit its cap
    labels: tuple[tuple[str, ...], ...] = ()  # aligned with packages


def signature(package: Package) -> tuple:
    """Where the traveler stays: (city, nights) per stay in order, and the hotel of each stay."""
    return (
        tuple((s.city, s.nights) for s in package.plan.stays),
        tuple(h.hotel_id for h in package.hotels),
    )


def cheapest_per_signature(packages) -> dict:
    """signature -> the cheapest package with that signature (first one wins a tie)."""
    best: dict = {}
    for p in packages:
        sig = signature(p)
        if sig not in best or p.total < best[sig].total:
            best[sig] = p
    return best


# ------------------------------------------------------------------ the two metrics


def _flight_minutes(flight, catalog) -> int:
    rec = catalog.indexes.flights_by_id.get(flight.flight_id) or {}
    if rec.get("duration_minutes") is not None:
        return int(rec["duration_minutes"])
    return int((flight.arrival - flight.departure).total_seconds() // 60)  # same zone only


def _transfer_minutes(t) -> int:
    return int((t.arrive - t.pickup).total_seconds() // 60)


def _stars(hotel_id: str, catalog) -> int:
    return int((catalog.indexes.hotels_by_id.get(hotel_id) or {}).get("stars") or 0)


def _nights(h) -> int:
    return (h.check_out - h.check_in).days


def travel_minutes(pkg: Package, catalog) -> int:
    """Both flight durations plus every transfer between cities (G4 "fastest")."""
    return (
        _flight_minutes(pkg.arrival_flight, catalog)
        + _flight_minutes(pkg.return_flight, catalog)
        + sum(_transfer_minutes(t) for t in pkg.intercity)
    )


def avg_stars_per_night(pkg: Package, catalog) -> float:
    """Hotel stars weighted by nights (G4 "best rated"); guest rating does not count."""
    nights = sum(_nights(h) for h in pkg.hotels)
    if not nights:
        return 0.0
    return sum(_stars(h.hotel_id, catalog) * _nights(h) for h in pkg.hotels) / nights


def _star_deficit(pkg: Package, catalog) -> int:
    """Sum over nights of (MAX_STARS - stars): lower is better rated, and an exact integer."""
    return sum((MAX_STARS - _stars(h.hotel_id, catalog)) * _nights(h) for h in pkg.hotels)


# ------------------------------------------------------------------ search


def _clean(pkg: Package, catalog) -> bool:
    return not validate_trip(to_trip_json(pkg, catalog), catalog, INITIAL)


class _Capped(Exception):
    pass


def _best_by(s: _Search, triples, budget: int, slot_metric, fixed_metric):
    """The validated package with total <= budget that has the lowest metric, the cheaper on a tie.
    slot_metric(k, n, payload) -> int for slot k of a plan with n stays; fixed_metric(arr, ret) -> int.
    Raises _Capped when the work cap is hit."""
    keyed = []
    for bound, key, plan, arr, ret, slots, floor in triples:
        if bound > budget:
            continue
        n = len(plan.stays)
        mslots = [
            sorted(((slot_metric(k, n, p) * _SCALE + c, p) for c, p in slot), key=lambda x: x[0])
            for k, slot in enumerate(slots)
        ]
        fixed = fixed_metric(arr, ret)
        lower_metric = fixed + sum(m[0][0] // _SCALE for m in mslots)
        keyed.append((lower_metric, bound, key, fixed, plan, arr, ret, mslots, floor))
    keyed.sort(key=lambda t: (t[0], t[1], t[2]))

    best, best_key, work = None, None, 0
    for lower_metric, _, _, fixed, plan, arr, ret, mslots, floor in keyed:
        if best_key is not None and lower_metric > best_key[0]:
            break  # sorted: no later triple can do better
        flights, n = arr.price + ret.price, len(plan.stays)
        for combined, choice in _product_in_cost_order(mslots):
            metric, cost = fixed + combined // _SCALE, combined % _SCALE
            lower = flights + cost + floor
            if best_key is not None and (metric, lower) >= best_key:
                break  # metric order, then cost order: nothing better follows
            if lower > budget:
                continue
            work += 1
            if work > MAX_OPTION_COMBINATIONS:
                raise _Capped()
            sched = s.attractions(plan, choice[0][1], choice[n:], choice[n - 1][2])
            if not sched.feasible:
                continue
            pkg = s.assemble(plan, arr, ret, choice, sched.visits)
            if pkg.total > budget or (best_key is not None and (metric, pkg.total) >= best_key):
                continue
            if not s.validated(pkg):
                continue
            best, best_key = pkg, (metric, pkg.total)
    return best


def _fastest(s, triples, budget, catalog):
    return _best_by(
        s,
        triples,
        budget,
        lambda k, n, p: _transfer_minutes(p) if k >= n else 0,
        lambda arr, ret: _flight_minutes(arr, catalog) + _flight_minutes(ret, catalog),
    )


def _best_rated(s, triples, budget, catalog):
    return _best_by(
        s,
        triples,
        budget,
        lambda k, n, p: (
            0 if k >= n else (MAX_STARS - _stars(p[0].hotel_id, catalog)) * _nights(p[0])
        ),
        lambda arr, ret: 0,
    )


def find_package_options(
    request, catalog, objective: str = WITHIN_BUDGET, count: int = 3
) -> OptionSet:
    """Cheapest, Fastest and Best rated, merged when one package wins more than one. `count` is kept
    for callers; at most three packages are returned (fewer when packages tie)."""
    primary = build_package(request, catalog, objective)
    if primary.status != FOUND or primary.package is None:
        return OptionSet(primary, (), True)
    if not _clean(primary.package, catalog):
        return OptionSet(primary, (), True)  # build_package's own check is re-run by the route
    enrich_mode = "BUDGET" if objective == WITHIN_BUDGET else "FREE"

    # Cheapest: the proven minimum. If that search could not finish, the label is not given.
    minimum = (
        primary if objective == MINIMUM_COST else build_package(request, catalog, MINIMUM_COST)
    )
    cheapest_proven = minimum.status == FOUND and minimum.package is not None
    cheapest = minimum.package if cheapest_proven else primary.package
    if count <= 1:
        return OptionSet(primary, (cheapest,), True, ((CHEAPEST,) if cheapest_proven else (),))

    s = _Search(request, catalog, PlanningConstraints())
    complete = True
    found: dict[str, Package | None] = {}
    triples = s.triples()
    for label, search in ((FASTEST, _fastest), (BEST_RATED, _best_rated)):
        try:
            pkg = search(s, triples, request.budget, catalog)
        except _Capped:
            complete, pkg = False, None
        if pkg is not None:
            richer = s.enrich(pkg, enrich_mode)
            pkg = richer if richer.total <= request.budget else pkg
        found[label] = pkg

    # one card per winner; a package that ties the best metric takes the label instead of a new card
    cards: list[tuple[Package, list[str]]] = [(cheapest, [CHEAPEST] if cheapest_proven else [])]
    metric = {FASTEST: travel_minutes, BEST_RATED: lambda p, c: -avg_stars_per_night(p, c)}
    for label in (FASTEST, BEST_RATED):
        pkg = found[label]
        if pkg is None:
            continue
        score = metric[label](pkg, catalog)
        holder = next((c for c in cards if metric[label](c[0], catalog) <= score), None)
        if holder is not None:
            holder[1].append(label)
        else:
            cards.append((pkg, [label]))

    # every final option is re-checked; a failing one is dropped, never shown
    cards = [c for c in cards if _clean(c[0], catalog)]
    return OptionSet(
        primary, tuple(c[0] for c in cards), complete, tuple(tuple(c[1]) for c in cards)
    )
