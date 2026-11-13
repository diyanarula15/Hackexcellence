"""Complete package search.

Why the search is exact
-----------------------
For a fixed (city plan, arrival flight, return flight) the package total is a sum of "slots" that
do not constrain each other:

    first stay  = hotel/room + arrival transfer (+ departure transfer when it is the only stay)
    middle stay = hotel/room
    last stay   = hotel/room + departure transfer
    each move   = one intercity transfer
    attractions = cheapest distinct assignment for the plan's full days

The only coupling is that attraction times must avoid the chosen transfer times, so the attraction
cost of a combination can never be LOWER than the cost with no transfers at all. That gives a safe
lower bound:  flights + sum(cheapest of each slot) + attractions_without_transfers.

The search is best-first branch and bound over every (plan, arrival, return) triple, ordered by
that bound, and inside a triple over the product of ALL slot options in increasing cost. A branch
is cut only when its bound cannot beat the best validated package. Nothing is cut by "top N"
limits. Every package that could be returned is exported and checked by the independent Phase 2
validator first; a rejected candidate is counted as a planner defect and the search continues.
"""
import hashlib
import heapq
import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta
from types import SimpleNamespace

from app.engine.city_plans import generate_city_plans
from app.engine.constraints import LOCKED_CHOICE_INCOMPATIBLE, PlanningConstraints
from app.engine.flights import (compatible_arrivals, compatible_returns, find_arrival_flights,
                                find_return_flights)
from app.engine.hotels import find_hotel_options, hotel_failure_reason
from app.engine.model import ARRIVAL_LEG, DEPARTURE_LEG, CityPlan, Package, intercity_leg_id
from app.engine.schedule import (classify_days, find_start, fits, make_visit, schedule_attractions,
                                 transfer_blocks)
from app.engine.transfers import (find_arrival_transfers, find_intercity_transfers,
                                  find_return_transfers)
from app.export.to_trip import to_trip_json
from app.rules.common import INITIAL, Party
from app.rules.request import check_request, resolve_country
from app.validate.validate_trip import validate_trip
from app.lib.money import rupees

log = logging.getLogger(__name__)

WITHIN_BUDGET, MINIMUM_COST = "WITHIN_BUDGET", "MINIMUM_COST"
FOUND, OVER_BUDGET, INFEASIBLE, SEARCH_INCOMPLETE = "FOUND", "OVER_BUDGET", "INFEASIBLE", "SEARCH_INCOMPLETE"
MAX_COMBINATIONS = 2_000_000     # engineering safeguard only; reported as SEARCH_INCOMPLETE if hit


class _Incomplete(Exception):
    pass


@dataclass
class SearchStats:
    city_plans: int = 0
    arrival_flights: int = 0
    return_flights: int = 0
    flight_pairs: int = 0            # compatible (plan, arrival, return) triples
    hotel_options: int = 0
    combinations_evaluated: int = 0
    branches_pruned: int = 0
    packages_validated: int = 0
    validator_rejections: int = 0
    elapsed_ms: float = 0.0


@dataclass
class PlanningResult:
    status: str
    package: Package | None
    cheapest_total: int | None
    budget_remaining: int | None
    shortfall: int | None
    reasons: list[str]
    search_complete: bool
    reason_codes: list[str] = field(default_factory=list)
    stats: SearchStats = field(default_factory=SearchStats)
    proposal: object | None = None      # ChangeProposal when existing_package was given


# ------------------------------------------------------------------ helpers

def _req_dict(request) -> dict:
    return {"departure_airport": request.departure_airport,
            "destination_country": request.destination_country,
            "start_date": request.start_date, "nights": request.nights, "adults": request.adults,
            "children_ages": list(request.children_ages), "budget": request.budget}


def _trip_id(request) -> str:
    key = repr(sorted(_req_dict(request).items(), key=lambda kv: kv[0]))
    return "T" + hashlib.sha1(key.encode()).hexdigest()[:10]


def _product_in_cost_order(slots):
    """Yield (sum, choice tuple) over the full product of slots in non-decreasing sum.
    Each slot is a non-empty list of (cost, payload) sorted by cost. Complete: every combination
    is eventually produced."""
    start = (0,) * len(slots)
    heap = [(sum(s[0][0] for s in slots), start)]
    seen = {start}
    while heap:
        total, idx = heapq.heappop(heap)
        yield total, tuple(slots[k][i][1] for k, i in enumerate(idx))
        for k, i in enumerate(idx):
            if i + 1 < len(slots[k]):
                nxt = idx[:k] + (i + 1,) + idx[k + 1:]
                if nxt not in seen:
                    seen.add(nxt)
                    heapq.heappush(heap, (total - slots[k][i][0] + slots[k][i + 1][0], nxt))


class _Search:
    def __init__(self, request, catalog, constraints: PlanningConstraints):
        self.req, self.cat, self.con = request, catalog, constraints
        self.party = Party(request.adults, tuple(request.children_ages))
        self.country = resolve_country(request.destination_country, catalog)
        self.stats = SearchStats()
        self.failures: dict[str, dict] = {}        # code -> {"plans": set, "message": str}
        self._hotels, self._arr, self._dep, self._legs, self._attr = {}, {}, {}, {}, {}
        self.plans_tried: set = set()

    # ---- failure bookkeeping
    def fail(self, code: str, plan: CityPlan, message: str):
        f = self.failures.setdefault(code, {"plans": set(), "message": message})
        f["plans"].add(plan)

    # ---- cached candidate lookups (all options, never truncated)
    def hotels(self, stay):
        if stay.stay_id not in self._hotels:
            opts = find_hotel_options(stay.city, stay.check_in, stay.check_out, self.party.adults,
                                      self.party.children, self.cat,
                                      locked=self.con.locked_hotels.get(stay.stay_id))
            self.stats.hotel_options += len(opts)
            self._hotels[stay.stay_id] = opts
        return self._hotels[stay.stay_id]

    def arr_transfers(self, flight, hotel):
        k = (flight.flight_id, hotel.city, hotel.area)
        if k not in self._arr:
            self._arr[k] = find_arrival_transfers(flight, hotel, self.party, self.cat,
                                                  locked=self.con.locked_transfers.get(ARRIVAL_LEG))
        return self._arr[k]

    def dep_transfers(self, flight, hotel):
        k = (flight.flight_id, hotel.city, hotel.area)
        if k not in self._dep:
            self._dep[k] = find_return_transfers(flight, hotel, self.party, self.cat,
                                                 locked=self.con.locked_transfers.get(DEPARTURE_LEG))
        return self._dep[k]

    def leg_transfers(self, a, b, day):
        k = intercity_leg_id(a, b, day)
        if k not in self._legs:
            self._legs[k] = find_intercity_transfers(a, b, day, self.party, self.cat,
                                                     locked=self.con.locked_transfers.get(k))
        return self._legs[k]

    def attractions(self, plan, arrival, intercity, departure, second="NONE", budget_left=None):
        """Cheapest attraction schedule given concrete transfers (None = no transfer blocks)."""
        key = (plan, arrival.arrive if arrival else None, tuple(t.arrive for t in intercity),
               departure.pickup if departure else None, second, budget_left)
        if key not in self._attr:
            self._attr[key] = self._schedule(plan, arrival, intercity, departure, second, budget_left)
        return self._attr[key]

    def _schedule(self, plan, arrival, intercity, departure, second, budget_left):
        pinned = []
        if self.con.required_attractions:
            A = self.cat.indexes.attractions_by_id
            day_city = {s.day: s for s in classify_days(plan)}
            blocks = transfer_blocks(plan, arrival, intercity, departure)
            for r in self.con.required_attractions:
                a, slot = A.get(r.attraction_id), day_city.get(r.day)
                bad = (a is None or slot is None or slot.kind == "DEPARTURE" or a["city"] != slot.city
                       or r.attraction_id in self.con.excluded_attraction_ids
                       or any(p.attraction_id == r.attraction_id for p in pinned))
                taken = blocks + [(p.start, p.end) for p in pinned]
                start = None if bad else (r.start if r.start and fits(a, r.day, r.start, taken)
                                          else None if r.start else find_start(a, r.day, taken))
                if start is None:
                    return SimpleNamespace(feasible=False, visits=(), total_price=0, failed_day=r.day,
                                           code=LOCKED_CHOICE_INCOMPATIBLE,
                                           reason=f"Required attraction {r.attraction_id} cannot be "
                                                  f"visited on {r.day.isoformat()} in this plan.")
                pinned.append(make_visit(a, start, self.party))
        res = schedule_attractions(plan, (arrival, list(intercity), departure), self.req, self.cat,
                                   excluded=frozenset(self.con.excluded_attraction_ids),
                                   pinned=tuple(pinned), second=second, budget_left=budget_left)
        extra = sum(p.price for p in pinned)
        return SimpleNamespace(feasible=res.feasible, visits=res.visits,
                               total_price=res.total_price + extra, failed_day=res.failed_day,
                               code="NO_REQUIRED_ATTRACTION", reason=res.reason)

    # ---- one (plan, arrival flight, return flight) triple
    def slots(self, plan, arr, ret):
        """Sorted option lists for every slot, or None (after recording why) if one is empty."""
        stays, n = plan.stays, len(plan.stays)
        locked = lambda key: " (locked choice)" if key in self.con.locked_hotels or key in self.con.locked_transfers else ""
        per_stay = []
        for s in stays:
            opts = self.hotels(s)
            if not opts:
                if s.stay_id in self.con.locked_hotels:
                    self.fail(LOCKED_CHOICE_INCOMPATIBLE, plan,
                              f"The locked hotel/room cannot host the travelers in {s.city} for "
                              f"{s.check_in.isoformat()} to {s.check_out.isoformat()}.")
                else:
                    code = hotel_failure_reason(s.city, s.check_in, s.check_out, self.party.adults,
                                                self.party.children, self.cat) or "NO_HOTEL_AVAILABILITY"
                    what = ("No room type can accommodate" if code == "NO_HOTEL_CAPACITY"
                            else "No hotel has rooms free on every night for")
                    self.fail(code, plan, f"{what} {self.party.adults} adult(s) and "
                                          f"{self.party.children} child(ren) in {s.city} from "
                                          f"{s.check_in.isoformat()} to {s.check_out.isoformat()}.")
                return None
            per_stay.append(opts)

        out = []
        first = []
        for h in per_stay[0]:
            for ta in self.arr_transfers(arr, h):
                if n == 1:
                    for td in self.dep_transfers(ret, h):
                        first.append((h.total_price + ta.price + td.price, (h, ta, td)))
                else:
                    first.append((h.total_price + ta.price, (h, ta, None)))
        if not first:
            no_arr = not any(self.arr_transfers(arr, h) for h in per_stay[0])
            code, leg = ("NO_ARRIVAL_TRANSFER", ARRIVAL_LEG) if no_arr else ("NO_RETURN_TRANSFER", DEPARTURE_LEG)
            msg = (f"No airport transfer from {arr.to_airport} reaches a bookable {stays[0].city} hotel "
                   f"after flight {arr.flight_id} lands{locked(ARRIVAL_LEG)}." if no_arr else
                   f"No airport transfer gets from a bookable {stays[-1].city} hotel to {ret.from_airport} "
                   f"180 minutes before flight {ret.flight_id}{locked(DEPARTURE_LEG)}.")
            self.fail(LOCKED_CHOICE_INCOMPATIBLE if leg in self.con.locked_transfers else code, plan, msg)
            return None
        out.append(first)
        for opts in per_stay[1:-1] if n > 1 else []:
            out.append([(h.total_price, (h, None, None)) for h in opts])
        if n > 1:
            last = [(h.total_price + td.price, (h, None, td))
                    for h in per_stay[-1] for td in self.dep_transfers(ret, h)]
            if not last:
                self.fail(LOCKED_CHOICE_INCOMPATIBLE if DEPARTURE_LEG in self.con.locked_transfers
                          else "NO_RETURN_TRANSFER", plan,
                          f"No airport transfer gets from a bookable {stays[-1].city} hotel to "
                          f"{ret.from_airport} 180 minutes before flight {ret.flight_id}"
                          f"{locked(DEPARTURE_LEG)}.")
                return None
            out.append(last)
        for a, b, day in plan.legs():
            opts = self.leg_transfers(a, b, day)
            if not opts:
                lid = intercity_leg_id(a, b, day)
                self.fail(LOCKED_CHOICE_INCOMPATIBLE if lid in self.con.locked_transfers
                          else "NO_INTERCITY_TRANSFER", plan,
                          f"No transfer runs from {a} to {b} on {day.isoformat()}{locked(lid)}.")
                return None
            out.append([(t.price, t) for t in opts])
        for s in out:
            s.sort(key=lambda x: x[0])     # stable: candidate lists are already deterministic
        return out

    def assemble(self, plan, arr, ret, choice, visits) -> Package:
        n = len(plan.stays)
        stay_parts, legs = choice[:n], choice[n:]
        return Package(
            trip_id=_trip_id(self.req), traveler_name=getattr(self.req, "traveler_name", None) or "Traveler",
            home_airport=self.req.departure_airport, country_code=self.country["code"],
            country_name=self.country["name"], adults=self.party.adults,
            child_ages=tuple(self.party.child_ages), budget=self.req.budget, plan=plan,
            arrival_flight=arr, return_flight=ret, hotels=tuple(p[0] for p in stay_parts),
            arrival_transfer=stay_parts[0][1], departure_transfer=stay_parts[-1][2],
            intercity=tuple(legs), visits=tuple(visits))

    def validated(self, pkg: Package) -> bool:
        """Export and run the independent validator. A failure is a planner defect: log, count, skip."""
        self.stats.packages_validated += 1
        violations = validate_trip(to_trip_json(pkg, self.cat), self.cat, INITIAL)
        if violations:
            self.stats.validator_rejections += 1
            log.error("planner produced an invalid package (%s): %s", pkg.trip_id,
                      sorted({v.rule for v in violations}))
            return False
        return True

    def best_in_triple(self, plan, arr, ret, slots, attr_floor, cutoff):
        """The cheapest validated package of this triple with total < cutoff, or None."""
        flights = arr.price + ret.price
        best = None
        n = len(plan.stays)
        for slot_sum, choice in _product_in_cost_order(slots):
            if flights + slot_sum + attr_floor >= cutoff:
                self.stats.branches_pruned += 1
                break
            self.stats.combinations_evaluated += 1
            if self.stats.combinations_evaluated > MAX_COMBINATIONS:
                raise _Incomplete()
            arrival_t, departure_t, legs = choice[0][1], choice[n - 1][2], choice[n:]
            sched = self.attractions(plan, arrival_t, legs, departure_t)
            if not sched.feasible:
                self.fail(sched.code, plan, sched.reason)
                continue
            total = flights + slot_sum + sched.total_price
            if total >= cutoff:
                continue
            pkg = self.assemble(plan, arr, ret, choice, sched.visits)
            if not self.validated(pkg):
                continue
            best, cutoff = pkg, total      # later combinations must be strictly cheaper
        return best

    # ---- candidates
    def triples(self):
        """Every compatible (bound, plan, arrival, return, slots, attraction floor)."""
        req, cat, con = self.req, self.cat, self.con
        plans = generate_city_plans(self.country["code"], req.nights, cat, req.start_date)
        if con.locked_city_plan is not None:
            want = tuple((c, n) for c, n in con.locked_city_plan)
            plans = [p for p in plans if tuple((s.city, s.nights) for s in p.stays) == want]
        self.stats.city_plans = len(plans)
        arrivals = find_arrival_flights(req, cat)
        returns = find_return_flights(req, cat)
        if con.arrival_flight_id:
            arrivals = [f for f in arrivals if f.flight_id == con.arrival_flight_id]
        if con.return_flight_id:
            returns = [f for f in returns if f.flight_id == con.return_flight_id]
        self.stats.arrival_flights, self.stats.return_flights = len(arrivals), len(returns)
        self.plans, self.arrivals, self.returns = plans, arrivals, returns

        out = []
        for plan in plans:
            ca, cr = compatible_arrivals(plan, arrivals, cat), compatible_returns(plan, returns, cat)
            if not ca:
                self.fail("NO_ARRIVAL_FLIGHT", plan, f"No bookable arrival flight lands at an airport "
                                                     f"serving {plan.first_city} on {plan.start_date.isoformat()}.")
            if not cr:
                self.fail("NO_RETURN_FLIGHT", plan, f"No bookable return flight leaves from an airport "
                                                    f"serving {plan.last_city} on {plan.end_date.isoformat()}.")
            if not ca or not cr:
                continue
            floor = self.attractions(plan, None, (), None)
            if not floor.feasible:
                self.fail(floor.code, plan, floor.reason)
                continue
            for arr in ca:
                for ret in cr:
                    self.stats.flight_pairs += 1
                    slots = self.slots(plan, arr, ret)
                    if slots is None:
                        continue
                    bound = arr.price + ret.price + sum(s[0][0] for s in slots) + floor.total_price
                    key = (tuple((s.city, s.nights) for s in plan.stays), arr.flight_id, ret.flight_id)
                    out.append((bound, key, plan, arr, ret, slots, floor.total_price))
        return out

    def minimum(self, triples, cutoff=None):
        """Global cheapest validated package (below cutoff if given). Best-first by lower bound."""
        best, limit = None, cutoff if cutoff is not None else float("inf")
        for bound, _, plan, arr, ret, slots, floor in sorted(triples, key=lambda t: (t[0], t[1])):
            if bound >= limit:
                self.stats.branches_pruned += 1
                break                       # sorted by bound: nothing later can be cheaper
            pkg = self.best_in_triple(plan, arr, ret, slots, floor, limit)
            if pkg is not None:
                best, limit = pkg, pkg.total
        return best

    def within_budget(self, triples):
        """A validated package with total <= budget, preferring the house city rule, or None.
        Complete: every within-budget package lives in a triple whose bound <= budget."""
        preferred = max(1, self.req.nights // 3)
        key = lambda t: (abs(len(t[2].stays) - preferred), t[0], t[1])
        # Comfort pass (a preference, never a rule): only arrival transfers that leave on the
        # landing day, so nobody waits overnight at the airport. The second pass drops the
        # preference, which keeps the search complete.
        comfort = []
        for bound, k, plan, arr, ret, slots, floor in triples:
            same_day = [o for o in slots[0] if o[1][1].pickup.date() == plan.start_date]
            if same_day:
                comfort.append((bound - slots[0][0][0] + same_day[0][0], k, plan, arr, ret,
                                [same_day] + slots[1:], floor))
        for candidates in (comfort, triples):
            for bound, _, plan, arr, ret, slots, floor in sorted(candidates, key=key):
                if bound > self.req.budget:
                    self.stats.branches_pruned += 1
                    continue
                pkg = self.best_in_triple(plan, arr, ret, slots, floor, self.req.budget + 1)
                if pkg is not None:
                    return pkg
        return None

    def enrich(self, pkg: Package, second: str) -> Package:
        """Add optional second visits (free ones, or ones that fit the budget). Falls back to the
        unenriched package if the richer one is not validator-clean."""
        sched = self.attractions(pkg.plan, pkg.arrival_transfer, pkg.intercity, pkg.departure_transfer,
                                 second, pkg.budget_remaining if second == "BUDGET" else None)
        if not sched.feasible or len(sched.visits) == len(pkg.visits):
            return pkg
        richer = pkg.with_(visits=tuple(sched.visits))
        if second == "BUDGET" and richer.total > pkg.budget:
            return pkg
        return richer if self.validated(richer) else pkg

    # ---- explanations
    def reasons(self):
        """(codes, messages). A reason is called a blocker only when it stopped every city plan."""
        req, codes, msgs = self.req, [], []
        n = self.party.travelers
        when_in = req.start_date.isoformat()
        when_out = (req.start_date + timedelta(days=req.nights)).isoformat()
        if not self.plans:
            codes.append("NO_COMPATIBLE_CITY_PLAN")
            msgs.append(f"No city plan of {req.nights} nights exists in {self.country['name']}"
                        + (" for the locked city plan." if self.con.locked_city_plan is not None else "."))
        for which, flights, finder, lock, date_s, direction in (
                ("ARRIVAL", self.arrivals, find_arrival_flights, self.con.arrival_flight_id, when_in,
                 f"from {req.departure_airport} lands in {self.country['name']} on {when_in}"),
                ("RETURN", self.returns, find_return_flights, self.con.return_flight_id, when_out,
                 f"leaves {self.country['name']} for {req.departure_airport} on {when_out}")):
            if flights:
                continue
            if lock:
                codes.append(LOCKED_CHOICE_INCOMPATIBLE)
                msgs.append(f"The locked {which.lower()} flight {lock} does not fit this request "
                            f"(wrong date, airport or not enough seats).")
            elif finder(req, self.cat, ignore_seats=True):
                codes.append("INSUFFICIENT_FLIGHT_SEATS")
                msgs.append(f"A flight {direction}, but none has {n} seats left.")
            else:
                codes.append(f"NO_{which}_FLIGHT")
                msgs.append(f"No flight {direction}.")
        if codes:
            return codes, msgs
        total = len(self.plans)
        for code, f in sorted(self.failures.items(), key=lambda kv: (-len(kv[1]["plans"]), kv[0])):
            codes.append(code)
            k = len(f["plans"])
            if k == total:
                msgs.append(f"Every one of the {total} possible city plan(s) fails for this reason: "
                            f"{f['message']}")
            else:
                msgs.append(f"{k} of {total} possible city plan(s) fail for this reason, for example: "
                            f"{f['message']}")
        if not codes:
            codes.append("NO_COMPATIBLE_CITY_PLAN")
            msgs.append("No combination of flights, hotels and transfers forms a complete package.")
        return codes, msgs


# ------------------------------------------------------------------ public API

def build_package(request, catalog, objective: str = WITHIN_BUDGET,
                  constraints: PlanningConstraints | None = None,
                  existing_package: Package | None = None) -> PlanningResult:
    """Plan a holiday. `request` is a TripRequest (or any object with the same attributes);
    `catalog` is the Loaded catalog.

    WITHIN_BUDGET: a valid package within budget if one exists (FOUND); otherwise the PROVEN
    cheapest valid package (OVER_BUDGET) or INFEASIBLE.  MINIMUM_COST: the proven global minimum.
    With `existing_package`, the result is a minimal-change repair proposal (see engine/repair.py):
    budget is then a warning, and no global re-planning happens.
    """
    if objective not in (WITHIN_BUDGET, MINIMUM_COST):
        raise ValueError(f"objective must be {WITHIN_BUDGET!r} or {MINIMUM_COST!r}")
    constraints = constraints or PlanningConstraints()
    if existing_package is not None:
        from app.engine.repair import propose_repair
        p = propose_repair(existing_package, constraints, catalog)
        if not p.valid:
            return PlanningResult(INFEASIBLE, None, None, None, None,
                                  [v.message for v in p.violations], True,
                                  sorted({v.rule for v in p.violations}), proposal=p)
        pkg = p.proposed_package
        over = pkg.total > pkg.budget
        return PlanningResult(OVER_BUDGET if over else FOUND, pkg, pkg.total, pkg.budget_remaining,
                              pkg.total - pkg.budget if over else None, list(p.warnings), True,
                              proposal=p)

    t0 = time.perf_counter()
    bad = check_request(_req_dict(request), catalog)
    if bad:
        return PlanningResult(INFEASIBLE, None, None, None, None, [v.message for v in bad], True,
                              ["INVALID_REQUEST"] + sorted({v.rule for v in bad}))
    s = _Search(request, catalog, constraints)

    def done(status, pkg, reasons=(), codes=()):
        s.stats.elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        total = pkg.total if pkg else None
        return PlanningResult(
            status, pkg, total,
            (request.budget - total) if pkg and status == FOUND else None,
            (total - request.budget) if pkg and status == OVER_BUDGET else None,
            list(reasons), status != SEARCH_INCOMPLETE, list(codes), s.stats)

    try:
        triples = s.triples()
        if objective == WITHIN_BUDGET:
            pkg = s.within_budget(triples)
            if pkg is not None:
                return done(FOUND, s.enrich(pkg, "BUDGET"))
        cheapest = s.minimum(triples)
    except _Incomplete:
        return done(SEARCH_INCOMPLETE, None,
                    [f"The search stopped after {MAX_COMBINATIONS} combinations without a proof."],
                    [SEARCH_INCOMPLETE])
    if cheapest is None:
        codes, msgs = s.reasons()
        if s.stats.validator_rejections:
            msgs.append(f"{s.stats.validator_rejections} candidate package(s) were rejected by the "
                        "validator (internal planner defect, see log).")
        return done(INFEASIBLE, None, msgs, codes)
    cheapest = s.enrich(cheapest, "FREE")
    if cheapest.total <= request.budget:
        return done(FOUND, cheapest)
    return done(OVER_BUDGET, cheapest,
                [f"The cheapest valid package costs {rupees(cheapest.total)}, which is "
                 f"{rupees(cheapest.total - request.budget)} over the budget of {rupees(request.budget)}."],
                ["OVER_BUDGET"])
