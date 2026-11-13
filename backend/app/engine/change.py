"""Package change commands -> one validated, fully priced change proposal (pure, in memory).

`propose_change(package, command, catalog)` is the Phase 5 entry point. It edits a saved package; it
never re-plans the holiday:

  A. copy     the saved package is an immutable value; every step builds new values from it
  B. apply    the command becomes hard PlanningConstraints: the traveler's exact choice is locked
              (never swapped for another option); every other component starts out unchanged
  C. scope    engine.dependencies.affected_components names what this edit may repair
  D. repair   engine.repair.propose_repair keeps whatever still works and repairs only inside that
              scope (same service same time, same service new time, closest other service)
  E. reprice  every price comes from the catalog through the candidate functions; total recomputed
  F. validate the whole proposal is exported and checked by validate_trip in EDITED mode
  G. report   a ChangeProposal: changed items, automatic repairs and warnings, or violations

Checks that belong to the command rather than to the generic repair live here: the target must exist
in this package, a no-op is refused, an added attraction may not duplicate one already planned and
may not displace any other visit, and a removal changes nothing else.
"""

from dataclasses import replace
from datetime import datetime, timedelta

from app.engine import dependencies as dep
from app.engine.constraints import HotelLock, PlanningConstraints, RequiredAttraction, TransferLock
from app.engine.model import ARRIVAL_LEG, DEPARTURE_LEG, Package, intercity_leg_id
from app.engine.repair import REPAIR_OUT_OF_SCOPE, ChangeProposal, propose_repair
from app.engine.schedule import (
    DEPARTURE,
    FULL,
    GAP_MINUTES,
    classify_days,
    find_start,
    fits,
    make_visit,
    transfer_blocks,
)
from app.lib.money import rupees
from app.lib.time import at
from app.models import (
    ADD_ATTRACTION,
    ADD_ATTRACTIONS,
    CHANGE_AIRPORT_TRANSFER,
    CHANGE_ARRIVAL_FLIGHT,
    CHANGE_HOTEL,
    CHANGE_INTERCITY_TRANSFER,
    CHANGE_RETURN_FLIGHT,
    REMOVE_ATTRACTION,
    REMOVE_ATTRACTIONS,
)
from app.rules.attractions import check_attractions
from app.rules.common import EDITED, Busy, Party, Stay, Violation, Visit

ARRIVAL_FLIGHT_ITEM, RETURN_FLIGHT_ITEM = "flight:arrival", "flight:return"
NO_CHANGE = "NO_CHANGE"
CHANGE_TARGET_NOT_FOUND = "CHANGE_TARGET_NOT_FOUND"

# command kind -> its row in the dependency table (engine.dependencies)
DEPENDENCY_KIND = {
    CHANGE_ARRIVAL_FLIGHT: dep.ARRIVAL_FLIGHT,
    CHANGE_RETURN_FLIGHT: dep.RETURN_FLIGHT,
    CHANGE_HOTEL: dep.HOTEL,
    CHANGE_AIRPORT_TRANSFER: dep.AIRPORT_TRANSFER,
    CHANGE_INTERCITY_TRANSFER: dep.INTERCITY_TRANSFER,
    ADD_ATTRACTION: dep.ADD_ATTRACTION,
    REMOVE_ATTRACTION: dep.REMOVE_ATTRACTION,
}


def visit_item_id(attraction_id: str) -> str:
    """Package item id of a visit. Unique in a package: an attraction is visited at most once (R-ATT-7)."""
    return f"visit:{attraction_id}"


def target_item_id(command) -> str:
    """The stable package item id a command changes (for an added visit, the id it will get)."""
    kind = command.kind
    if kind == CHANGE_ARRIVAL_FLIGHT:
        return ARRIVAL_FLIGHT_ITEM
    if kind == CHANGE_RETURN_FLIGHT:
        return RETURN_FLIGHT_ITEM
    if kind == CHANGE_HOTEL:
        return command.stay_id
    if kind == ADD_ATTRACTION:
        return visit_item_id(command.attraction_id)
    if kind == ADD_ATTRACTIONS:
        return visit_item_id(command.additions[0].attraction_id)  # a batch is named by its first item
    if kind == REMOVE_ATTRACTIONS:
        return command.item_ids[0]
    return command.item_id  # airport / intercity transfer leg, or the visit to remove


def command_targets(command) -> set[str]:
    """Every package item id a command is allowed to change. Only these may appear in a proposal."""
    if command.kind == ADD_ATTRACTIONS:
        return {visit_item_id(a.attraction_id) for a in command.additions}
    if command.kind == REMOVE_ATTRACTIONS:
        return set(command.item_ids)
    return {target_item_id(command)}


def _batch_impact(package: Package, command) -> dep.DependencyImpact | None:
    """The union of the dependency rows of every item in a batch."""
    if command.kind == ADD_ATTRACTIONS:
        changes = [dep.Change(dep.ADD_ATTRACTION, a.attraction_id, a.date) for a in command.additions]
    else:
        changes = [dep.Change(dep.REMOVE_ATTRACTION, i.removeprefix("visit:")) for i in command.item_ids]
    try:
        impacts = [dep.affected_components(c, package) for c in changes]
    except ValueError:
        return None
    recheck = tuple(dict.fromkeys(r for i in impacts for r in i.recheck))
    scope = frozenset().union(*(i.repair_scope for i in impacts))
    return dep.DependencyImpact(change=changes[0], recheck=recheck, repair_scope=scope)


def dependency_impact(package: Package, command) -> dep.DependencyImpact | None:
    """What the change makes stale and may repair (the dependency table), or None for an unknown target."""
    kind = command.kind
    if kind in (ADD_ATTRACTIONS, REMOVE_ATTRACTIONS):
        return _batch_impact(package, command)
    if kind == CHANGE_HOTEL:
        change = dep.Change(dep.HOTEL, command.stay_id)
    elif kind in (CHANGE_AIRPORT_TRANSFER, CHANGE_INTERCITY_TRANSFER):
        change = dep.Change(DEPENDENCY_KIND[kind], command.item_id)
    elif kind == ADD_ATTRACTION:
        change = dep.Change(dep.ADD_ATTRACTION, command.attraction_id, command.date)
    elif kind == REMOVE_ATTRACTION:
        change = dep.Change(dep.REMOVE_ATTRACTION, command.item_id.removeprefix("visit:"))
    else:
        change = dep.Change(DEPENDENCY_KIND[kind])
    try:
        return dep.affected_components(change, package)
    except ValueError:
        return None


class _Refuse(Exception):
    def __init__(self, violations: list[Violation]):
        super().__init__("change refused")
        self.violations = violations


def propose_change(package: Package, command, catalog) -> ChangeProposal:
    """The complete consequence of one traveler change, or the reasons it is impossible.

    Pure: `package` and `catalog` are only read. Deterministic for the same inputs. A valid proposal
    has passed validate_trip in EDITED mode; an invalid one carries violations and no package."""
    target = target_item_id(command)
    try:
        constraints, notes = _constraints(package, command, catalog)
        proposal = propose_repair(package, constraints, catalog)
        if not proposal.valid:
            raise _Refuse(proposal.violations)
        _check_command_scope(command, proposal, catalog)
    except _Refuse as r:
        violations = [v if v.item_id else replace(v, item_id=target) for v in r.violations]
        return ChangeProposal(False, None, violations, [], [], package.total, None, None, None)
    return replace(proposal, warnings=_warnings(package, proposal, catalog) + notes)


# ------------------------------------------------------------------ B. command -> hard constraints


def _not_found(message: str, item_id: str) -> Violation:
    return Violation(CHANGE_TARGET_NOT_FOUND, message, item_id)


def _constraints(pkg: Package, cmd, cat) -> tuple[PlanningConstraints, list[str]]:
    kind = cmd.kind
    if kind in (CHANGE_ARRIVAL_FLIGHT, CHANGE_RETURN_FLIGHT):
        arrival = kind == CHANGE_ARRIVAL_FLIGHT
        current = pkg.arrival_flight if arrival else pkg.return_flight
        if cmd.flight_id == current.flight_id:
            which = "arrival" if arrival else "return"
            raise _Refuse(
                [
                    Violation(
                        NO_CHANGE,
                        f"This flight is already your {which} flight.",
                        ARRIVAL_FLIGHT_ITEM if arrival else RETURN_FLIGHT_ITEM,
                    )
                ]
            )
        if arrival:
            return PlanningConstraints(arrival_flight_id=cmd.flight_id), []
        return PlanningConstraints(return_flight_id=cmd.flight_id), []

    if kind == CHANGE_HOTEL:
        stay = next((h for h in pkg.hotels if h.stay_id == cmd.stay_id), None)
        if stay is None:
            raise _Refuse(
                [_not_found(f"This holiday has no hotel stay {cmd.stay_id}.", cmd.stay_id)]
            )
        if (cmd.hotel_id, cmd.room_id) == (stay.hotel_id, stay.room_id):
            raise _Refuse(
                [
                    Violation(
                        NO_CHANGE,
                        "This hotel and room type are already booked for this stay.",
                        cmd.stay_id,
                    )
                ]
            )
        # the room count is not the client's to choose: the fewest rooms of this type that fit the party
        return PlanningConstraints(
            locked_hotels={cmd.stay_id: HotelLock(cmd.hotel_id, cmd.room_id)}
        ), []

    if kind == CHANGE_AIRPORT_TRANSFER:
        current = {ARRIVAL_LEG: pkg.arrival_transfer, DEPARTURE_LEG: pkg.departure_transfer}.get(
            cmd.item_id
        )
        if current is None:
            raise _Refuse(
                [
                    _not_found(
                        f"{cmd.item_id} is not an airport transfer of this holiday "
                        f"(use {ARRIVAL_LEG} or {DEPARTURE_LEG}).",
                        cmd.item_id,
                    )
                ]
            )
        if cmd.transfer_id == current.transfer_id:
            raise _Refuse(
                [Violation(NO_CHANGE, "This transfer is already booked for this leg.", cmd.item_id)]
            )
        # the pickup time follows from the flight; the engine finds the valid one for this service
        return PlanningConstraints(
            locked_transfers={cmd.item_id: TransferLock(cmd.transfer_id)}
        ), []

    if kind == CHANGE_INTERCITY_TRANSFER:
        current = next((t for t in pkg.intercity if t.leg_id == cmd.item_id), None)
        day = next(
            (d for a, b, d in pkg.plan.legs() if intercity_leg_id(a, b, d) == cmd.item_id), None
        )
        if current is None or day is None:
            raise _Refuse(
                [_not_found(f"This holiday has no city-to-city move {cmd.item_id}.", cmd.item_id)]
            )
        pickup = at(day, cmd.pickup) if cmd.pickup else None
        if cmd.transfer_id == current.transfer_id and pickup in (None, current.pickup):
            raise _Refuse(
                [Violation(NO_CHANGE, "This transfer is already booked at this time.", cmd.item_id)]
            )
        return PlanningConstraints(
            locked_transfers={cmd.item_id: TransferLock(cmd.transfer_id, pickup)}
        ), []

    if kind == ADD_ATTRACTION:
        return _add_attractions(pkg, [(cmd.attraction_id, cmd.date, cmd.preferred_start)], cat)

    if kind == ADD_ATTRACTIONS:
        return _add_attractions(
            pkg, [(a.attraction_id, a.date, a.preferred_start) for a in cmd.additions], cat
        )

    if kind == REMOVE_ATTRACTION:
        return _remove_attractions(pkg, [cmd.item_id])

    if kind == REMOVE_ATTRACTIONS:
        return _remove_attractions(pkg, cmd.item_ids)

    raise ValueError(f"unknown change kind {kind!r}")


def _remove_attractions(pkg: Package, item_ids) -> tuple[PlanningConstraints, list[str]]:
    """Exclude the named visits; every one must be planned. Nothing else is locked."""
    missing, aids = [], set()
    for item in item_ids:
        aid = item.removeprefix("visit:")
        if not item.startswith("visit:") or all(v.attraction_id != aid for v in pkg.visits):
            missing.append(_not_found(f"This holiday has no attraction visit {item}.", item))
        else:
            aids.add(aid)
    if missing:
        raise _Refuse(missing)
    return PlanningConstraints(excluded_attraction_ids=aids), []


def _add_attractions(pkg: Package, additions, cat) -> tuple[PlanningConstraints, list[str]]:
    """Lock each new visit at a time that leaves every other visit exactly where it is.

    `additions` = [(attraction_id, day, preferred_start 'HH:MM' | None)] in the order the traveler gave.
    Each addition must avoid transfers, the existing visits AND the visits placed earlier in the batch.
    If any addition cannot be placed, every failure is reported and nothing is planned (no partial
    batch)."""
    plan = pkg.plan
    party = Party(pkg.adults, tuple(pkg.child_ages))
    blocks = transfer_blocks(plan, pkg.arrival_transfer, pkg.intercity, pkg.departure_transfer)
    required: list[RequiredAttraction] = []
    placed = []  # VisitOption of the earlier additions in this batch
    notes: list[str] = []
    violations: list[Violation] = []
    seen: set[str] = set()
    for aid, day, preferred in additions:
        a = cat.indexes.attractions_by_id.get(aid)
        item = visit_item_id(aid)
        if a is None:
            violations.append(Violation("R-ATT-1", f"Attraction {aid} is not in the catalog.", item))
            continue
        if aid in seen:
            violations.append(
                Violation(
                    "R-ATT-7",
                    f"{a['name']} is in this change more than once; an attraction can be visited only once.",
                    item,
                )
            )
            continue
        seen.add(aid)
        planned = next((v for v in pkg.visits if v.attraction_id == aid), None)
        if planned is not None:
            # R-ATT-7 (each attraction at most once), checked here because the generic repair reads
            # "require X on day D" as "move X there", which an Add must never do.
            violations.append(
                Violation(
                    "R-ATT-7",
                    f"{a['name']} is already in this holiday on "
                    f"{planned.start:%a %d %b %Y} at {planned.start:%H:%M}; "
                    "an attraction can be visited only once.",
                    item,
                )
            )
            continue
        slot = next((s for s in classify_days(plan) if s.day == day), None)
        want = at(day, preferred) if preferred else None
        start = None
        if slot is not None and slot.kind != DEPARTURE and slot.city == a["city"]:
            others = [*pkg.visits, *placed]
            taken = list(blocks) + [(v.start, v.end) for v in others]
            # Like the first build, keep GAP_MINUTES between visits when the day allows it (time to
            # get from one sight to the next); back to back only when nothing else fits. A time the
            # traveler picked is kept as long as it does not overlap.
            gap = timedelta(minutes=GAP_MINUTES)
            spaced = list(blocks) + [(v.start - gap, v.end + gap) for v in others]
            start = (
                want
                if want is not None and fits(a, day, want, taken)
                else find_start(a, day, spaced, prefer=want) or find_start(a, day, taken, prefer=want)
            )
        if start is None:
            later = sorted((*pkg.visits, *placed), key=lambda v: (v.start, v.attraction_id))
            violations.extend(_why_no_time(pkg.with_(visits=tuple(later)), a, day, want, cat))
            continue
        if want is not None and start != want:
            notes.append(
                f"{a['name']} cannot start at {want:%H:%M} on {day:%a %d %b} without moving your other "
                f"plans, so it is planned at {start:%H:%M} instead."
            )
        required.append(RequiredAttraction(aid, day, start))
        placed.append(make_visit(a, start, party))
    if violations:
        raise _Refuse(violations)
    return PlanningConstraints(required_attractions=required), notes


def _transfer_label(t, cat) -> str:
    rec = cat.indexes.transfers_by_id.get(t.transfer_id) or {}
    return f"the transfer {rec.get('name') or t.transfer_id}"


def _why_no_time(pkg: Package, a: dict, day, want, cat) -> list[Violation]:
    """Why `a` fits nowhere on `day`: the shared R-ATT rules, applied to the package's visits plus the
    new visit at the requested time (else its opening time), keeping only what the new visit causes."""
    aid, item = a["attraction_id"], visit_item_id(a["attraction_id"])
    plan = pkg.plan
    party = Party(pkg.adults, tuple(pkg.child_ages))
    new = make_visit(a, want or at(day, a["open_from"]), party)
    stays = [
        Stay(h.stay_id, h.hotel_id, h.room_id, h.city, h.check_in, h.check_out, h.rooms)
        for h in pkg.hotels
    ]
    ready = {
        plan.start_date: pkg.arrival_transfer.arrive,
        **{d: t.arrive for (_, _, d), t in zip(plan.legs(), pkg.intercity, strict=True)},
    }
    busy = [
        Busy(t.pickup, t.arrive, t.leg_id, _transfer_label(t, cat))
        for t in (pkg.arrival_transfer, *pkg.intercity, pkg.departure_transfer)
    ]
    existing = [
        Visit(visit_item_id(v.attraction_id), v.attraction_id, v.start, v.end) for v in pkg.visits
    ]

    def check(visits):
        return check_attractions(
            visits, stays, plan.start_date, plan.end_date, ready, busy, EDITED, cat
        )

    before = set(check(existing))
    found = [v for v in check(existing + [Visit(item, aid, new.start, new.end)]) if v not in before]

    slot = next((s for s in classify_days(plan) if s.day == day), None)
    when = f"{day:%a %d %b %Y}"
    if slot is None:
        head = Violation(
            "R-ATT-2",
            f"{when} is not a day of this holiday "
            f"({plan.start_date:%d %b} – {plan.end_date:%d %b %Y}).",
            item,
        )
    elif slot.kind == DEPARTURE:
        head = Violation(
            "R-ATT-11", f"{when} is your departure day; no attraction can be added on it.", item
        )
    elif slot.city != a["city"]:
        head = Violation(
            "R-ATT-2", f"{a['name']} is in {a['city']}, but on {when} you are in {slot.city}.", item
        )
    elif any(v.rule == "R-ATT-3" for v in found):
        head = Violation("R-ATT-3", f"{a['name']} is closed on {when}.", item)
    elif any(v.rule == "R-ATT-4" for v in found):
        head = Violation(
            "R-ATT-4",
            f"{a['name']} is not open on {day:%A}s (open {', '.join(a['open_days'])}).",
            item,
        )
    else:
        blocking = sorted(
            (
                v.start,
                (cat.indexes.attractions_by_id.get(v.attraction_id) or {}).get(
                    "name", v.attraction_id
                ),
                v.end,
            )
            for v in pkg.visits
            if v.start.date() == day
        )
        taken = (
            "; ".join(f"{name} {s:%H:%M}–{e:%H:%M}" for s, name, e in blocking) or "travel that day"
        )
        head = Violation(
            "R-ATT-8",
            f"No free time for {a['name']} on {when}: it needs {a['visit_minutes']} "
            f"minutes within {a['open_from']}–{a['open_until']}, and that time is "
            f"taken ({taken}). Other visits are never moved to make room.",
            item,
        )
    if (
        head.rule == "R-ATT-11"
    ):  # the departure day has no hotel night: the city finding is noise there
        found = [v for v in found if v.rule == "R-ATT-11"]
    return [head] + found


# ------------------------------------------------------------------ G. command-level checks and warnings


def _visit_name(component: str, cat) -> str:
    aid = component.removeprefix("visit:")
    return (cat.indexes.attractions_by_id.get(aid) or {}).get("name", aid)


def _check_command_scope(cmd, proposal: ChangeProposal, cat) -> None:
    """An added or removed attraction (or batch) changes exactly the requested visits and nothing else."""
    if cmd.kind not in (ADD_ATTRACTION, REMOVE_ATTRACTION, ADD_ATTRACTIONS, REMOVE_ATTRACTIONS):
        return
    target = target_item_id(cmd)
    allowed = command_targets(cmd)
    others = [c for c in proposal.changed_items if c.component not in allowed]
    if others:
        what = ", ".join(
            _visit_name(c.component, cat) if c.component.startswith("visit:") else c.component
            for c in others
        )
        adding = cmd.kind in (ADD_ATTRACTION, ADD_ATTRACTIONS)
        verb = "Adding" if adding else "Removing"
        subject = _visit_name(target, cat) if len(allowed) == 1 else f"{len(allowed)} attractions"
        raise _Refuse(
            [
                Violation(
                    REPAIR_OUT_OF_SCOPE,
                    f"{verb} {subject} would also change "
                    f"{what}, which this edit does not allow.",
                    target,
                )
            ]
        )


def _warnings(old: Package, proposal: ChangeProposal, cat) -> list[str]:
    """What the traveler must know before accepting: budget, removed visits, days left empty."""
    new = proposal.proposed_package
    out = []
    if new.total > new.budget:
        out.append(
            f"The package will cost {rupees(new.total)}, {rupees(new.total - new.budget)} over your "
            f"budget of {rupees(new.budget)}. You can still apply this change."
        )
    for c in proposal.automatic_repairs:
        if c.action == "REMOVED" and c.component.startswith("visit:"):
            # never silent: a paid visit that has to go is named, dated and priced before acceptance
            price, when = c.before["price_inr"], datetime.fromisoformat(c.before["start"])
            paid = f"; its {rupees(price)} comes off the total" if price else ""
            out.append(
                f"{_visit_name(c.component, cat)} on {when:%a %d %b} at {when:%H:%M} no longer fits after "
                f"this change and will be removed{paid}."
            )
    had = {v.start.date() for v in old.visits}
    have = {v.start.date() for v in new.visits}
    for s in classify_days(new.plan):
        if s.kind == FULL and s.day in had and s.day not in have:
            out.append(
                f"{s.day:%a %d %b} in {s.city} will have no attraction planned. That is allowed for an "
                "edited package."
            )
    return out
