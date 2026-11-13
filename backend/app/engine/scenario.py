"""Delay Rescue (Phase 5B): what a HYPOTHETICAL later landing of the arrival flight does to a package.

simulate_arrival_delay(package, delay_minutes, catalog) is pure: the package is an immutable value,
the catalog is only read, and nothing is persisted. The arrival flight stays exactly the catalog
flight (its scheduled times are never changed); the delay exists only inside this function as
`simulated_landing`, which the existing candidate search and the existing airport-transfer rule are
given as the effective landing time.

Outcomes
  ABSORBED       the saved pickup is still >= simulated landing + the pickup buffer (config.py): nothing changes
  REPAIRED       a valid repair exists inside the arrival dependency scope
                 (arrival transfer -> hotel arrival -> arrival-day / next-day visits)
  UNRECOVERABLE  no repair exists without touching flights, hotels, cities, dates or intercity legs

Repair search (complete over the scope): every airport-transfer service that serves the saved
arrival airport and first hotel, each at its EARLIEST pickup >= simulated landing + the pickup buffer (an
earlier pickup is impossible and a later one only blocks more of the day). For each, the visits the
later hotel arrival collides with are moved later the same day, or - only on the arrival day, where
visits are optional - removed and disclosed. Candidates are ranked by minimum disruption:
  (components changed, visits removed, service replaced, minutes moved, extra cost, transfer id)
so a later pickup of the same service always beats a different service of equal disruption.

A REPAIRED proposal must pass BOTH checks:
  A. scenario check: the airport-transfer rule with effective_landing = simulated landing
  B. validate_trip(export, catalog, "EDITED") == []  (the normal rules, scheduled flight times)
"""

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from app.engine.model import ARRIVAL_LEG, Package
from app.engine.repair import AUTOMATIC_REPAIR, ChangedItem, _desc_transfer, _desc_visit
from app.engine.schedule import find_start, fits, make_visit, transfer_blocks
from app.engine.transfers import find_arrival_transfers
from app.export.to_trip import to_trip_json
from app.rules.common import EDITED, Party, TransferSel, Violation
from app.rules.transfers import PICKUP_TEXT, check_airport_transfers
from app.validate.validate_trip import validate_trip

ABSORBED, REPAIRED, UNRECOVERABLE = "ABSORBED", "REPAIRED", "UNRECOVERABLE"
SUPPORTED_DELAYS = (60, 120, 180, 240)

NO_ARRIVAL_TRANSFER_AFTER_DELAY = "NO_ARRIVAL_TRANSFER_AFTER_DELAY"
VISIT_CANNOT_MOVE = "VISIT_CANNOT_MOVE"
REPAIR_FAILED_VALIDATION = "REPAIR_FAILED_VALIDATION"


@dataclass(frozen=True)
class DelayScenarioResult:
    delay_minutes: int
    scheduled_landing: str            # catalog arrival, destination-local "YYYY-MM-DDTHH:MM"
    simulated_landing: str            # scheduled + delay (may be the next day)
    outcome: str
    proposed_package: Package | None  # unchanged package for ABSORBED, None for UNRECOVERABLE
    changed_items: list = field(default_factory=list)       # ChangedItem, all AUTOMATIC_REPAIR
    automatic_repairs: list = field(default_factory=list)
    removed_activities: list = field(default_factory=list)  # ChangedItem with action REMOVED
    original_total_inr: int = 0
    proposed_total_inr: int | None = None
    price_difference_inr: int | None = None
    budget_remaining_inr: int | None = None
    over_budget_inr: int | None = None
    violations: list = field(default_factory=list)          # Violation
    warnings: list = field(default_factory=list)            # str
    original_pickup: str | None = None
    proposed_pickup: str | None = None
    explanation: str = ""


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M")


def _party(pkg: Package) -> Party:
    return Party(pkg.adults, tuple(pkg.child_ages))


def scenario_violations(pkg: Package, simulated_landing: datetime, catalog) -> list[Violation]:
    """Check A: the airport-transfer rule against the simulated landing (catalog untouched)."""
    ix = catalog.indexes
    return check_airport_transfers(
        [TransferSel(ARRIVAL_LEG, pkg.arrival_transfer.transfer_id, pkg.arrival_transfer.pickup)],
        [TransferSel("leg:departure", pkg.departure_transfer.transfer_id, pkg.departure_transfer.pickup)],
        ix.flights_by_id[pkg.arrival_flight.flight_id], ix.flights_by_id[pkg.return_flight.flight_id],
        ix.hotels_by_id[pkg.hotels[0].hotel_id], ix.hotels_by_id[pkg.hotels[-1].hotel_id],
        catalog, effective_landing=simulated_landing)


def normal_violations(pkg: Package, catalog) -> list[Violation]:
    """Check B: the independent validator, EDITED mode, scheduled (real) flight times."""
    return validate_trip(to_trip_json(pkg, catalog), catalog, EDITED)


def _replan_visits(pkg: Package, new_transfer, catalog):
    """(visits, changed items, removed items) after the later hotel arrival, or a failure Violation.

    Visits that still fit keep their exact time. A colliding visit moves to the nearest valid later
    start the same day; on the arrival day (optional visits) it is removed if no time fits; on any
    other day the repair fails, because removing a required full-day visit is not a delay repair."""
    A = catalog.indexes.attractions_by_id
    plan = pkg.plan
    blocks = transfer_blocks(plan, new_transfer, list(pkg.intercity), pkg.departure_transfer)
    keep, colliding = [], []
    for v in sorted(pkg.visits, key=lambda v: (v.start, v.attraction_id)):
        (keep if fits(A[v.attraction_id], v.start.date(), v.start, blocks) else colliding).append(v)
    placed = list(keep)
    changed, removed = [], []
    party = _party(pkg)
    for v in colliding:
        a, day = A[v.attraction_id], v.start.date()
        taken = blocks + [(p.start, p.end) for p in placed]
        start = find_start(a, day, taken, prefer=v.start)   # nearest valid start, later preferred
        if start is not None:
            new = make_visit(a, start, party)
            placed.append(new)
            changed.append(ChangedItem(
                f"visit:{v.attraction_id}", AUTOMATIC_REPAIR, "RESCHEDULED", _desc_visit(v), _desc_visit(new),
                new.price - v.price,
                f"{a['name']} moves from {v.start:%H:%M} to {new.start:%H:%M} because you would reach "
                f"the hotel at {new_transfer.arrive:%H:%M}."))
        elif day == plan.start_date:
            item = ChangedItem(
                f"visit:{v.attraction_id}", AUTOMATIC_REPAIR, "REMOVED", _desc_visit(v), None, -v.price,
                f"{a['name']} is removed: after the delayed arrival you would reach the hotel at "
                f"{new_transfer.arrive:%H:%M}, and no later visit fits its opening hours "
                f"({a['open_from']}-{a['open_until']}) that day.")
            changed.append(item)
            removed.append(item)
        else:
            return None, Violation(VISIT_CANNOT_MOVE,
                                   f"{a['name']} on {day.isoformat()} conflicts with the later hotel arrival "
                                   f"({new_transfer.arrive:%Y-%m-%d %H:%M}) and cannot be moved within its "
                                   f"opening hours.", f"visit:{v.attraction_id}")
    return (sorted(placed, key=lambda v: (v.start, v.attraction_id)), changed, removed), None


def _disruption(pkg: Package, t, changed) -> int:
    minutes = abs((t.pickup - pkg.arrival_transfer.pickup).total_seconds()) / 60
    for c in changed:
        if c.action == "RESCHEDULED":
            minutes += abs((datetime.fromisoformat(c.after["start"])
                            - datetime.fromisoformat(c.before["start"])).total_seconds()) / 60
    return int(minutes)


def _money(pkg: Package, proposed: Package | None) -> dict:
    if proposed is None:
        return {}
    remaining = proposed.budget - proposed.total
    return {"proposed_total_inr": proposed.total, "price_difference_inr": proposed.total - pkg.total,
            "budget_remaining_inr": max(remaining, 0), "over_budget_inr": max(-remaining, 0)}


def simulate_arrival_delay(package: Package, delay_minutes: int, catalog) -> DelayScenarioResult:
    """Pure simulation of the arrival flight landing `delay_minutes` later (any positive minutes;
    the API only offers 60/120/180/240)."""
    if not isinstance(delay_minutes, int) or isinstance(delay_minutes, bool) or delay_minutes <= 0:
        raise ValueError("delay_minutes must be a positive whole number of minutes")
    pkg = package
    scheduled = pkg.arrival_flight.arrival                      # catalog arrival (dated, local)
    simulated = scheduled + timedelta(minutes=delay_minutes)    # dated: may cross midnight
    base = dict(delay_minutes=delay_minutes, scheduled_landing=_fmt(scheduled),
                simulated_landing=_fmt(simulated), original_total_inr=pkg.total,
                original_pickup=_fmt(pkg.arrival_transfer.pickup))
    airport = pkg.arrival_flight.to_airport
    first = pkg.hotels[0]

    # 1. absorbed: the saved pickup still respects the simulated landing (nothing else depends on it)
    if not scenario_violations(pkg, simulated, catalog):
        problems = normal_violations(pkg, catalog)
        if not problems:
            return DelayScenarioResult(
                outcome=ABSORBED, proposed_package=pkg, proposed_pickup=_fmt(pkg.arrival_transfer.pickup),
                **base, **_money(pkg, pkg),
                explanation=f"No changes needed: your {pkg.arrival_transfer.pickup:%H:%M} pickup is still at least "
                            f"{PICKUP_TEXT} after a {simulated:%H:%M} landing.")
        return DelayScenarioResult(outcome=UNRECOVERABLE, proposed_package=None, violations=problems, **base,
                                   explanation="The saved package does not pass validation, so no scenario "
                                               "repair is offered.")

    # 2./3. every service that can still collect the traveler, at its earliest valid pickup
    sim_flight = replace(pkg.arrival_flight, arrival=simulated)   # scenario copy, never stored
    candidates = find_arrival_transfers(sim_flight, first, _party(pkg), catalog)
    failures: list[Violation] = []
    best = None
    for t in candidates:
        result, failure = _replan_visits(pkg, t, catalog)
        if failure is not None:
            failures.append(failure)
            continue
        visits, visit_changes, removed = result
        same_service = t.transfer_id == pkg.arrival_transfer.transfer_id
        transfer_change = ChangedItem(
            ARRIVAL_LEG, AUTOMATIC_REPAIR, "RESCHEDULED" if same_service else "REPLACED",
            _desc_transfer(pkg.arrival_transfer), _desc_transfer(t), t.price - pkg.arrival_transfer.price,
            (f"Same airport transfer, later pickup: {pkg.arrival_transfer.pickup:%H:%M} → {t.pickup:%H:%M} "
             f"(earliest service time at least {PICKUP_TEXT} after the {simulated:%H:%M} landing).")
            if same_service else
            (f"The current transfer cannot collect you at least {PICKUP_TEXT} after a {simulated:%H:%M} landing; "
             f"{catalog.indexes.transfers_by_id[t.transfer_id]['name']} can at {t.pickup:%H:%M}."))
        proposed = pkg.with_(arrival_transfer=t, visits=tuple(visits))
        problems = scenario_violations(proposed, simulated, catalog) + normal_violations(proposed, catalog)
        if problems:
            failures.append(Violation(REPAIR_FAILED_VALIDATION,
                                      f"A repair using {t.transfer_id} at {t.pickup:%H:%M} breaks a rule: "
                                      f"{problems[0].message}", ARRIVAL_LEG))
            continue
        changes = [transfer_change] + visit_changes
        key = (len(changes), len(removed), 0 if same_service else 1, _disruption(pkg, t, visit_changes),
               proposed.total - pkg.total, t.transfer_id)
        if best is None or key < best[0]:
            best = (key, proposed, changes, removed, t)

    if best is None:
        why = scenario_violations(pkg, simulated, catalog)
        lead = Violation(
            NO_ARRIVAL_TRANSFER_AFTER_DELAY,
            f"No airport transfer from {airport} to your {first.city} hotel ({first.area or 'all areas'}) can "
            f"pick you up between {simulated + timedelta(minutes=60):%Y-%m-%d %H:%M} and 24 hours after the "
            f"simulated {simulated:%H:%M} landing while keeping the rest of the holiday."
            if not candidates else
            f"Airport transfers exist after the delayed landing, but none keeps the rest of the holiday valid.",
            ARRIVAL_LEG)
        return DelayScenarioResult(
            outcome=UNRECOVERABLE, proposed_package=None, violations=[lead] + why + failures, **base,
            explanation=lead.message + " Your saved holiday stays unchanged.")

    _, proposed, changes, removed, t = best
    money = _money(pkg, proposed)
    warnings = [c.reason for c in changes]
    if money["over_budget_inr"]:
        warnings.append(f"This repair puts the package {money['over_budget_inr']} INR over your budget.")
    return DelayScenarioResult(
        outcome=REPAIRED, proposed_package=proposed, changed_items=changes, automatic_repairs=changes,
        removed_activities=removed, violations=[], warnings=warnings, proposed_pickup=_fmt(t.pickup),
        **base, **money,
        explanation="Your holiday can still work with this delay: "
                    + "; ".join(c.reason for c in changes))


def exact_absorbed_tolerance(package: Package, catalog) -> int | None:
    """The largest delay (minutes) the saved plan absorbs with no change, VERIFIED with the scenario
    predicates at the boundary and one minute past it. None when even a 1-minute delay needs a change
    or the boundary could not be confirmed."""
    slack = int((package.arrival_transfer.pickup - package.arrival_flight.arrival
                 - timedelta(minutes=60)).total_seconds() // 60)
    if slack < 1:
        return None
    if simulate_arrival_delay(package, slack, catalog).outcome != ABSORBED:
        return None
    if simulate_arrival_delay(package, slack + 1, catalog).outcome == ABSORBED:
        return None
    return slack
