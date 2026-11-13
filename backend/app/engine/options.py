"""Three labelled packages for one request (problem statement G4).

    Cheapest    the lowest total price (the proven minimum build_package finds)
    Fastest     the least total travel time: both flight durations plus every transfer between
                cities. Not limited by budget (the problem statement puts "within budget" on best
                rated only). When it costs more than the budget the card says so, the traveler must
                accept the price to choose it, and "Fastest within budget" is added.
    Best rated  the highest average hotel stars per night (guest rating does not count), within
                budget. A hotel with no star value is never used for this label: it cannot be
                compared, and its stars are never guessed.

Travel time is not airport transfers, attraction visits or nights in hotels.

Ties: when one package is best on two criteria it is shown once and carries both labels. A tie in
the metric itself counts as best too ("on a tie show either one"), so the cheapest package also
carries Fastest when no package travels less, and so on. Fastest and Best rated prefer the lower
total on a tie, then the search order (catalog order), so the answer is deterministic.

Fastest and Best rated use a best-first search over the same triples and slots build.py uses, so
every objective has the same feasibility rules. Each slot option is keyed (metric, cost) as one
integer, metric * _SCALE + cost, so the slot product is visited in metric order and, within one
metric value, in cost order. Pruning is safe: a triple's metric floor (fixed part plus the smallest
metric per slot) never exceeds the metric of any of its packages. Stars are compared exactly
(integers, or Fraction), never rounded.

Honesty: that search is capped (MAX_OPTION_COMBINATIONS). When the cap is hit the label is not given
to a package that was not proven best; the label is listed in `unproven` instead.
"""

from dataclasses import dataclass
from fractions import Fraction

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
FASTEST_IN_BUDGET = "Fastest within budget"
MAX_STARS = 5
# above any sum of slot prices, so metric * _SCALE + cost sorts by metric first and by cost second
_SCALE = 10**9


@dataclass(frozen=True)
class OptionSet:
    primary: PlanningResult
    packages: tuple[Package, ...]  # empty unless primary is FOUND
    complete: bool  # False when a labelled search stopped before a proof
    labels: tuple[tuple[str, ...], ...] = ()  # aligned with packages; every label is proven
    unproven: tuple[str, ...] = ()  # labels whose search stopped before a proof


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
    """The catalog's elapsed duration. Local departure and arrival times are in different time
    zones, so they are never subtracted when the catalog gives the duration."""
    rec = catalog.indexes.flights_by_id.get(flight.flight_id) or {}
    if rec.get("duration_minutes") is not None:
        return int(rec["duration_minutes"])
    return int((flight.arrival - flight.departure).total_seconds() // 60)  # same zone only


def _transfer_minutes(t) -> int:
    return int((t.arrive - t.pickup).total_seconds() // 60)


def _stars(hotel_id: str, catalog) -> int | None:
    """The catalog star class, or None when the hotel has none (never the guest rating)."""
    stars = (catalog.indexes.hotels_by_id.get(hotel_id) or {}).get("stars")
    if isinstance(stars, bool) or not isinstance(stars, (int, float)):
        return None
    return int(stars)


def _nights(h) -> int:
    return (h.check_out - h.check_in).days


def travel_minutes(pkg: Package, catalog) -> int:
    """Both flight durations plus every transfer between cities (G4 "fastest")."""
    return (
        _flight_minutes(pkg.arrival_flight, catalog)
        + _flight_minutes(pkg.return_flight, catalog)
        + sum(_transfer_minutes(t) for t in pkg.intercity)
    )


def weighted_stars(pkg: Package, catalog) -> Fraction | None:
    """Hotel stars weighted by nights (G4 "best rated"), exact. The number of rooms does not weight
    it and guest rating does not count. None when a hotel has no star value."""
    nights = sum(_nights(h) for h in pkg.hotels)
    stars = [_stars(h.hotel_id, catalog) for h in pkg.hotels]
    if not nights or any(s is None for s in stars):
        return None
    return Fraction(sum(s * _nights(h) for s, h in zip(stars, pkg.hotels, strict=True)), nights)


def avg_stars_per_night(pkg: Package, catalog) -> float | None:
    """weighted_stars as a float, for display and JSON only (never for choosing a winner)."""
    exact = weighted_stars(pkg, catalog)
    return None if exact is None else float(exact)


# ------------------------------------------------------------------ search


def _clean(pkg: Package, catalog) -> bool:
    return not validate_trip(to_trip_json(pkg, catalog), catalog, INITIAL)


class _Capped(Exception):
    pass


def _best_by(s: _Search, triples, budget, slot_metric, fixed_metric):
    """The validated package with total <= budget (None: any total) that has the lowest metric, the
    cheaper on a tie. slot_metric(k, n, payload) -> int for slot k of a plan with n stays, or None to
    leave that option out; fixed_metric(arr, ret) -> int. Raises _Capped when the work cap is hit."""
    budget = float("inf") if budget is None else budget
    keyed = []
    for bound, key, plan, arr, ret, slots, floor in triples:
        if bound > budget:
            continue
        n = len(plan.stays)
        mslots = []
        for k, slot in enumerate(slots):
            scored = [(m, c, p) for c, p in slot if (m := slot_metric(k, n, p)) is not None]
            mslots.append(sorted(((m * _SCALE + c, p) for m, c, p in scored), key=lambda x: x[0]))
        if not all(mslots):
            continue  # a slot with no usable option (e.g. no hotel with a star value)
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
    def deficit(k, n, p):
        """Sum over the stay's nights of (MAX_STARS - stars): exact, lower is better rated."""
        if k >= n:
            return 0
        stars = _stars(p[0].hotel_id, catalog)
        return None if stars is None else (MAX_STARS - stars) * _nights(p[0])

    return _best_by(s, triples, budget, deficit, lambda arr, ret: 0)


def find_package_options(
    request, catalog, objective: str = WITHIN_BUDGET, count: int = 3
) -> OptionSet:
    """Cheapest, Fastest and Best rated, merged when one package wins more than one (plus Fastest
    within budget when the fastest costs more than the budget). `count` is kept for callers."""
    primary = build_package(request, catalog, objective)
    if primary.status != FOUND or primary.package is None:
        return OptionSet(primary, (), True)
    if not _clean(primary.package, catalog):
        return OptionSet(primary, (), True)  # build_package's own check is re-run by the route
    budget = request.budget
    enrich_mode = "BUDGET" if objective == WITHIN_BUDGET else "FREE"

    # Cheapest: the proven minimum. If that search could not finish, the label is not given.
    minimum = (
        primary if objective == MINIMUM_COST else build_package(request, catalog, MINIMUM_COST)
    )
    cheapest_proven = minimum.status == FOUND and minimum.package is not None
    cheapest = minimum.package if cheapest_proven else primary.package
    unproven = [] if cheapest_proven else [CHEAPEST]
    if count <= 1:
        labels = ((CHEAPEST,) if cheapest_proven else (),)
        return OptionSet(primary, (cheapest,), not unproven, labels, tuple(unproven))

    s = _Search(request, catalog, PlanningConstraints())
    triples = s.triples()

    def run(label, search, limit):
        try:
            pkg = search(s, triples, limit, catalog)
        except _Capped:
            unproven.append(label)
            return None
        if pkg is None:
            return None
        richer = s.enrich(pkg, enrich_mode if pkg.total <= budget else "FREE")
        return richer if (richer.total <= budget or pkg.total > budget) else pkg

    found = {FASTEST: run(FASTEST, _fastest, None)}
    if found[FASTEST] is not None and found[FASTEST].total > budget:
        found[FASTEST_IN_BUDGET] = run(FASTEST_IN_BUDGET, _fastest, budget)
    found[BEST_RATED] = run(BEST_RATED, _best_rated, budget)

    # one card per winner; a package that ties the winning metric takes the label instead of a new
    # card. Only the global Fastest label may sit on a card above the budget.
    def stars_key(p):
        w = weighted_stars(p, catalog)
        return Fraction(1) if w is None else -w  # no star value: never ties a real rating

    metric = {
        FASTEST: lambda p: travel_minutes(p, catalog),
        FASTEST_IN_BUDGET: lambda p: travel_minutes(p, catalog),
        BEST_RATED: stars_key,
    }
    cards: list[tuple[Package, list[str]]] = [(cheapest, [CHEAPEST] if cheapest_proven else [])]
    for label in (FASTEST, FASTEST_IN_BUDGET, BEST_RATED):
        pkg = found.get(label)
        if pkg is None:
            continue
        score = metric[label](pkg)
        holder = next(
            (
                c
                for c in cards
                if metric[label](c[0]) <= score and (label == FASTEST or c[0].total <= budget)
            ),
            None,
        )
        if holder is not None:
            holder[1].append(label)
        else:
            cards.append((pkg, [label]))

    # every final option is re-checked; a failing one is dropped, never shown
    cards = [c for c in cards if _clean(c[0], catalog)]
    return OptionSet(
        primary,
        tuple(c[0] for c in cards),
        not unproven,
        tuple(tuple(c[1]) for c in cards),
        tuple(unproven),
    )
