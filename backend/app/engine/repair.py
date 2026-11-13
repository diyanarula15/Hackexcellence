"""Minimal-change repair of an existing package after a traveler edit (pure, in memory).

lock -> preserve -> repair -> revalidate:
  1. hard locks from PlanningConstraints are applied exactly or the proposal is rejected;
  2. every other component of the existing package is kept as it is whenever it is still valid;
  3. only components inside the dependency scope of the edit may be repaired automatically, in the
     order: same service at the same time, same service at another time, another service
     (closest in time, then cheapest, then catalog id);
  4. the whole package is repriced, exported and checked by the full validator in EDITED mode.

Nothing is persisted and neither the existing package (immutable) nor the catalog is modified.
The traveler's budget is reported as a warning, never used to reject an explicit edit, and the
city plan, dates, country and travelers are never changed here (that is a separate request change).
"""
from dataclasses import dataclass, field, replace
from datetime import date
from types import SimpleNamespace

from app.engine import dependencies as dep
from app.engine.constraints import (LOCKED_CHOICE_INCOMPATIBLE, HotelLock, PlanningConstraints,
                                    TransferLock)
from app.engine.flights import (compatible_arrivals, compatible_returns, find_arrival_flights,
                                find_return_flights)
from app.engine.hotels import find_hotel_options, min_rooms
from app.engine.model import ARRIVAL_LEG, DEPARTURE_LEG, Package, intercity_leg_id
from app.engine.schedule import classify_days, find_start, fits, make_visit, transfer_blocks
from app.engine.transfers import (find_arrival_transfers, find_intercity_transfers,
                                  find_return_transfers)
from app.export.to_trip import to_trip_json
from app.lib.time import at, overlaps, parse_dt
from app.rules.common import EDITED, FlightSel, Party, Stay, TransferSel, Violation, Visit
from app.rules.attractions import check_attractions
from app.rules.flights import check_flights
from app.rules.hotels import check_hotels
from app.rules.intercity import check_intercity
from app.rules.transfers import check_airport_transfers
from app.validate.validate_trip import validate_trip
from app.lib.money import rupees

USER_CHOICE, AUTOMATIC_REPAIR = "USER_CHOICE", "AUTOMATIC_REPAIR"
REPAIR_OUT_OF_SCOPE = "REPAIR_OUT_OF_SCOPE"
CITY_PLAN_CHANGE_NOT_ALLOWED = "CITY_PLAN_CHANGE_NOT_ALLOWED"


@dataclass(frozen=True)
class ChangedItem:
    component: str             # "flight:arrival", "flight:return", stay_id, leg_id, "visit:<attraction id>"
    source: str                # USER_CHOICE or AUTOMATIC_REPAIR
    action: str                # "REPLACED" | "RESCHEDULED" | "ADDED" | "REMOVED" | "REPRICED"
    before: dict | None
    after: dict | None
    price_delta: int
    reason: str


@dataclass
class ChangeProposal:
    valid: bool
    proposed_package: Package | None
    violations: list[Violation]
    changed_items: list[ChangedItem]
    automatic_repairs: list[ChangedItem]
    old_total: int
    new_total: int | None
    price_difference: int | None
    budget_difference: int | None      # budget - new_total (negative = over budget)
    warnings: list[str] = field(default_factory=list)


class _Reject(Exception):
    def __init__(self, violations):
        self.violations = violations


def _lock_violation(message, item=None):
    return Violation(LOCKED_CHOICE_INCOMPATIBLE, message, item)


def _desc_flight(f):
    return {"catalog_id": f.flight_id, "start": f.departure.isoformat(), "end": f.arrival.isoformat(),
            "price_inr": f.price}


def _desc_hotel(h):
    return {"catalog_id": h.hotel_id, "room_id": h.room_id, "rooms": h.rooms,
            "start": h.check_in.isoformat(), "end": h.check_out.isoformat(), "price_inr": h.total_price}


def _desc_transfer(t):
    return {"catalog_id": t.transfer_id, "start": t.pickup.isoformat(), "end": t.arrive.isoformat(),
            "price_inr": t.price}


def _desc_visit(v):
    return {"catalog_id": v.attraction_id, "start": v.start.isoformat(), "end": v.end.isoformat(),
            "price_inr": v.price}


def request_of(pkg: Package):
    """The original request as an object the candidate functions accept."""
    return SimpleNamespace(departure_airport=pkg.home_airport, destination_country=pkg.country_code,
                           start_date=pkg.plan.start_date,
                           nights=(pkg.plan.end_date - pkg.plan.start_date).days, adults=pkg.adults,
                           children_ages=list(pkg.child_ages), budget=pkg.budget)


def derive_changes(pkg: Package, con: PlanningConstraints) -> list[dep.Change]:
    """The explicit traveler edits implied by the constraints, compared with the existing package."""
    out: list[dep.Change] = []
    if con.arrival_flight_id and con.arrival_flight_id != pkg.arrival_flight.flight_id:
        out.append(dep.Change(dep.ARRIVAL_FLIGHT))
    if con.return_flight_id and con.return_flight_id != pkg.return_flight.flight_id:
        out.append(dep.Change(dep.RETURN_FLIGHT))
    for h in pkg.hotels:
        lock = con.locked_hotels.get(h.stay_id)
        if lock and (lock.hotel_id, lock.room_id, lock.rooms or h.rooms) != (h.hotel_id, h.room_id, h.rooms):
            out.append(dep.Change(dep.HOTEL, h.stay_id))
    current = {ARRIVAL_LEG: pkg.arrival_transfer, DEPARTURE_LEG: pkg.departure_transfer,
               **{t.leg_id: t for t in pkg.intercity}}
    for leg_id, lock in con.locked_transfers.items():
        t = current.get(leg_id)
        if t and (lock.catalog_id, lock.pickup or t.pickup) != (t.transfer_id, t.pickup):
            kind = dep.AIRPORT_TRANSFER if leg_id in (ARRIVAL_LEG, DEPARTURE_LEG) else dep.INTERCITY_TRANSFER
            out.append(dep.Change(kind, leg_id))
    have = {v.attraction_id: v for v in pkg.visits}
    for r in con.required_attractions:
        v = have.get(r.attraction_id)
        if v is None or v.start.date() != r.day or (r.start and r.start != v.start):
            out.append(dep.Change(dep.ADD_ATTRACTION, r.attraction_id, r.day))
    for aid in sorted(con.excluded_attraction_ids):
        if aid in have:
            out.append(dep.Change(dep.REMOVE_ATTRACTION, aid))
    return out


def component_ids(trip: dict, pkg: Package) -> dict[str, str]:
    """Export item id (i1, i2, ...) -> package item id (flight:arrival, stay id, leg id, visit:<id>),
    matched by type, catalog id and start, so validator findings name the package's own items."""
    stays = {(h.hotel_id, h.check_in.isoformat()): h.stay_id for h in pkg.hotels}
    legs = {(t.transfer_id, t.pickup): t.leg_id
            for t in (pkg.arrival_transfer, *pkg.intercity, pkg.departure_transfer)}
    out = {}
    for it in trip["items"]:
        kind, cid = it["type"], it["catalog_id"]
        if kind == "flight":
            comp = "flight:arrival" if cid == pkg.arrival_flight.flight_id else "flight:return"
        elif kind == "hotel":
            comp = stays.get((cid, str(it["start"])[:10]))
        elif kind == "transfer":
            comp = legs.get((cid, parse_dt(it["start"])))
        else:
            comp = f"visit:{cid}"
        if comp:
            out[it["item_id"]] = comp
    return out


def propose_repair(existing_package: Package, constraints: PlanningConstraints, catalog) -> ChangeProposal:
    old = existing_package
    try:
        return _repair(old, constraints, catalog)
    except _Reject as r:
        return ChangeProposal(False, None, list(r.violations), [], [], old.total, None, None, None)


def _repair(old: Package, con: PlanningConstraints, cat) -> ChangeProposal:
    ix, plan, req = cat.indexes, old.plan, request_of(old)
    party = Party(old.adults, tuple(old.child_ages))
    changed: list[ChangedItem] = []

    # ---- the boundary: an edit never changes the city plan
    if con.locked_city_plan is not None and \
            tuple((c, n) for c, n in con.locked_city_plan) != tuple((s.city, s.nights) for s in plan.stays):
        raise _Reject([Violation(CITY_PLAN_CHANGE_NOT_ALLOWED,
                                 "Changing cities or nights is a new request, not an edit of this package.")])
    stay_ids = {s.stay_id for s in plan.stays}
    leg_ids = {ARRIVAL_LEG, DEPARTURE_LEG, *(intercity_leg_id(a, b, d) for a, b, d in plan.legs())}
    for sid in con.locked_hotels:
        if sid not in stay_ids:
            raise _Reject([_lock_violation(f"There is no stay {sid} in this package.")])
    for lid in con.locked_transfers:
        if lid not in leg_ids:
            raise _Reject([_lock_violation(f"There is no transfer leg {lid} in this package.")])
    clash = con.excluded_attraction_ids & {r.attraction_id for r in con.required_attractions}
    if clash:
        raise _Reject([_lock_violation(f"Attraction {sorted(clash)[0]} is both required and removed.")])

    changes = derive_changes(old, con)
    scope = dep.combined_scope(changes, old)

    # ---- 1. flights (locked exactly, or kept)
    def pick_flight(want, current, finder, compat, which):
        if not want or want == current.flight_id:
            return current
        match = [f for f in compat(plan, finder(req, cat), cat) if f.flight_id == want]
        if match:
            changed.append(ChangedItem(f"flight:{which}", USER_CHOICE, "REPLACED", _desc_flight(current),
                                       _desc_flight(match[0]), match[0].price - current.price,
                                       f"Traveler chose {which} flight {want}."))
            return match[0]
        sels = ([FlightSel("flight:arrival", want), FlightSel("flight:return", old.return_flight.flight_id)]
                if which == "arrival" else
                [FlightSel("flight:arrival", old.arrival_flight.flight_id), FlightSel("flight:return", want)])
        why = check_flights(sels, old.home_airport, old.country_code, plan.first_city, plan.last_city,
                            plan.start_date, plan.end_date, party, cat)
        raise _Reject([_lock_violation(f"The chosen {which} flight {want} cannot be used for this trip.",
                                      f"flight:{which}")] + why)

    arr = pick_flight(con.arrival_flight_id, old.arrival_flight, find_arrival_flights, compatible_arrivals, "arrival")
    ret = pick_flight(con.return_flight_id, old.return_flight, find_return_flights, compatible_returns, "return")

    # ---- 2. hotels (locked exactly, or kept; never another hotel)
    hotels = []
    for stay, h in zip(plan.stays, old.hotels):
        lock = con.locked_hotels.get(stay.stay_id)
        if not lock or (lock.hotel_id, lock.room_id, lock.rooms or h.rooms) == (h.hotel_id, h.room_id, h.rooms):
            hotels.append(h)
            continue
        opts = find_hotel_options(stay.city, stay.check_in, stay.check_out, party.adults, party.children,
                                  cat, locked=lock)
        if not opts:
            room = ix.rooms_by_id.get(lock.room_id)
            k = lock.rooms or (min_rooms(room, party.adults, party.children) if room else None) or 1
            why = check_hotels([Stay(stay.stay_id, lock.hotel_id, lock.room_id, stay.city, stay.check_in,
                                     stay.check_out, k)], party, cat)
            raise _Reject([_lock_violation(f"The chosen hotel {lock.hotel_id} / room {lock.room_id} cannot "
                                           f"host the travelers in {stay.city} for these nights.", stay.stay_id)] + why)
        hotels.append(opts[0])
        changed.append(ChangedItem(stay.stay_id, USER_CHOICE, "REPLACED", _desc_hotel(h), _desc_hotel(opts[0]),
                                   opts[0].total_price - h.total_price,
                                   f"Traveler chose hotel {lock.hotel_id}, room {lock.room_id}."))

    # ---- 3. transfers: lock, else keep, else repair inside the dependency scope
    def pick_transfer(leg_id, current, finder, why_fn, label):
        """finder(locked) -> options for this leg; why_fn(sel) -> precise Phase 2 violations."""
        lock = con.locked_transfers.get(leg_id)
        if lock:
            # the traveler's service; keep the current time if it is the same service and still valid
            keep_time = lock.pickup or (current.pickup if lock.catalog_id == current.transfer_id else None)
            opts = finder(TransferLock(lock.catalog_id, keep_time)) if keep_time else []
            if not opts and not lock.pickup:
                opts = finder(TransferLock(lock.catalog_id))
            if not opts:
                why = why_fn(TransferSel(leg_id, lock.catalog_id, lock.pickup or current.pickup))
                raise _Reject([_lock_violation(f"The chosen {label} {lock.catalog_id} cannot be used here; "
                                               "it was not replaced.", leg_id)] + why)
            new, source, reason = opts[0], USER_CHOICE, f"Traveler chose {label} {lock.catalog_id}."
        else:
            opts = finder(TransferLock(current.transfer_id, current.pickup))
            if opts:
                return current if opts[0] == current else opts[0]
            same = finder(TransferLock(current.transfer_id))
            if same:
                new, reason = same[0], f"The {label} keeps the same service at a new time."
            else:
                every = finder(None)
                if not every:
                    raise _Reject([Violation("NO_" + label.upper().replace(" ", "_"),
                                             f"After this change no {label} works, so the change is refused.", leg_id)]
                                  + why_fn(TransferSel(leg_id, current.transfer_id, current.pickup)))
                new = min(every, key=lambda t: (abs((t.pickup - current.pickup).total_seconds()),
                                                t.price, t.transfer_id))
                reason = f"The previous {label} no longer fits, so the closest valid service replaces it."
            source = AUTOMATIC_REPAIR
            if leg_id not in scope:
                raise _Reject([Violation(REPAIR_OUT_OF_SCOPE,
                                         f"The {label} would have to change, which this edit does not allow.", leg_id)])
        if new != current:
            action = "RESCHEDULED" if new.transfer_id == current.transfer_id else "REPLACED"
            changed.append(ChangedItem(leg_id, source, action, _desc_transfer(current), _desc_transfer(new),
                                       new.price - current.price, reason))
        return new

    first_h, last_h = hotels[0], hotels[-1]
    first_rec, last_rec = ix.hotels_by_id[first_h.hotel_id], ix.hotels_by_id[last_h.hotel_id]
    arr_rec, ret_rec = ix.flights_by_id[arr.flight_id], ix.flights_by_id[ret.flight_id]
    only = lambda vs: [v for v in vs if v.rule != "R-ATR-1"]   # one leg is checked at a time

    t_arr = pick_transfer(
        ARRIVAL_LEG, old.arrival_transfer,
        lambda lk: find_arrival_transfers(arr, first_h, party, cat, locked=lk),
        lambda sel: only(check_airport_transfers([sel], [], arr_rec, None, first_rec, None, cat)),
        "arrival transfer")
    t_dep = pick_transfer(
        DEPARTURE_LEG, old.departure_transfer,
        lambda lk: find_return_transfers(ret, last_h, party, cat, locked=lk),
        lambda sel: only(check_airport_transfers([], [sel], None, ret_rec, None, last_rec, cat)),
        "departure transfer")
    stays_sel = [Stay(None, h.hotel_id, h.room_id, h.city, h.check_in, h.check_out, h.rooms) for h in hotels]
    legs = []
    for (a, b, day), cur in zip(plan.legs(), old.intercity):
        legs.append(pick_transfer(
            cur.leg_id, cur,
            lambda lk, a=a, b=b, day=day, cur=cur: find_intercity_transfers(
                a, b, day, party, cat, locked=lk, prefer=cur.pickup.strftime("%H:%M")),
            lambda sel: check_intercity([sel], stays_sel, cat),
            "intercity transfer"))

    # ---- 4. attractions: remove exclusions, place required ones, keep or minimally move the rest
    A = ix.attractions_by_id
    blocks = transfer_blocks(plan, t_arr, legs, t_dep)
    days = {s.day: s for s in classify_days(plan)}
    required = {r.attraction_id: r for r in con.required_attractions}
    if len(required) != len(con.required_attractions):
        raise _Reject([_lock_violation("An attraction is required more than once.")])

    def explain_visit(aid, day, start):
        """Precise Phase 2 violations for one visit that cannot be placed."""
        a = A.get(aid)
        if a is None:
            return [Violation("R-ATT-1", f"Unknown attraction {aid}.")]
        st = start or find_start(a, day, []) or at(day, a["open_from"])
        v = make_visit(a, st, party)
        ready = {plan.start_date: t_arr.arrive, **{d: t.arrive for (_, _, d), t in zip(plan.legs(), legs)}}
        return check_attractions([Visit(f"visit:{aid}", aid, v.start, v.end)], stays_sel, plan.start_date,
                                 plan.end_date, ready, [], EDITED, cat)

    placed = []                                    # visits fixed so far
    for r in con.required_attractions:
        a, slot = A.get(r.attraction_id), days.get(r.day)
        taken = blocks + [(p.start, p.end) for p in placed]
        ok_place = a is not None and slot is not None and slot.kind != "DEPARTURE" and a["city"] == slot.city
        cur = next((v for v in old.visits if v.attraction_id == r.attraction_id), None)
        if ok_place and cur and cur.start.date() == r.day and (r.start in (None, cur.start)) \
                and fits(a, r.day, cur.start, taken):
            placed.append(cur)                     # already there and still fine: untouched
            continue
        start = None
        if ok_place:
            if r.start:
                start = r.start if fits(a, r.day, r.start, taken) else None
            else:
                # prefer a time that does not disturb the other existing visits that day
                others = [(v.start, v.end) for v in old.visits
                          if v.start.date() == r.day and v.attraction_id not in required
                          and v.attraction_id not in con.excluded_attraction_ids]
                start = find_start(a, r.day, taken + others) or find_start(a, r.day, taken)
        if start is None:
            raise _Reject([_lock_violation(f"Attraction {r.attraction_id} cannot be visited on "
                                           f"{r.day.isoformat()}" + (f" at {r.start:%H:%M}" if r.start else "")
                                           + ".", f"visit:{r.attraction_id}")] + explain_visit(r.attraction_id, r.day, r.start))
        new = make_visit(a, start, party)
        placed.append(new)
        changed.append(ChangedItem(f"visit:{r.attraction_id}", USER_CHOICE,
                                   "RESCHEDULED" if cur else "ADDED", _desc_visit(cur) if cur else None,
                                   _desc_visit(new), new.price - (cur.price if cur else 0),
                                   f"Traveler asked for {r.attraction_id} on {r.day.isoformat()}."))

    required_ids = set(required)
    for v in sorted(old.visits, key=lambda v: (v.start, v.attraction_id)):
        if v.attraction_id in required_ids:
            continue
        if v.attraction_id in con.excluded_attraction_ids:
            changed.append(ChangedItem(f"visit:{v.attraction_id}", USER_CHOICE, "REMOVED", _desc_visit(v), None,
                                       -v.price, f"Traveler removed {v.attraction_id}."))
            continue
        a, day = A[v.attraction_id], v.start.date()
        taken = blocks + [(p.start, p.end) for p in placed]
        if fits(a, day, v.start, taken):
            placed.append(v)
            continue
        # the visit no longer fits: move it within its day, otherwise it has to go
        hit_required = any(overlaps((v.start, v.end), (p.start, p.end)) for p in placed
                           if p.attraction_id in required_ids)
        start = find_start(a, day, taken, prefer=v.start)
        scope_id = dep.visits_scope(day)
        if scope_id not in scope:
            raise _Reject([Violation(REPAIR_OUT_OF_SCOPE, f"Visit {v.attraction_id} on {day.isoformat()} "
                                                          "would have to change, which this edit does not allow.",
                                     f"visit:{v.attraction_id}")])
        if start is not None:
            new = make_visit(a, start, party)
            placed.append(new)
            changed.append(ChangedItem(f"visit:{v.attraction_id}", AUTOMATIC_REPAIR, "RESCHEDULED",
                                       _desc_visit(v), _desc_visit(new), 0,
                                       f"{v.attraction_id} moved to keep the day free of conflicts."))
        elif hit_required:
            raise _Reject([_lock_violation(f"The requested attraction overlaps {v.attraction_id} on "
                                           f"{day.isoformat()} and that visit cannot be moved.", f"visit:{v.attraction_id}"),
                           Violation("R-ATT-8", f"Visits overlap on {day.isoformat()}.", f"visit:{v.attraction_id}")])
        else:
            changed.append(ChangedItem(f"visit:{v.attraction_id}", AUTOMATIC_REPAIR, "REMOVED", _desc_visit(v),
                                       None, -v.price,
                                       f"{v.attraction_id} no longer fits on {day.isoformat()} after this change."))

    # ---- 5. assemble, reprice (all prices come from the candidate functions), validate everything
    new_pkg = old.with_(arrival_flight=arr, return_flight=ret, hotels=tuple(hotels), arrival_transfer=t_arr,
                        departure_transfer=t_dep, intercity=tuple(legs),
                        visits=tuple(sorted(placed, key=lambda v: (v.start, v.attraction_id))))
    trip = to_trip_json(new_pkg, cat)
    violations = validate_trip(trip, cat, EDITED)
    if violations:
        ids = component_ids(trip, new_pkg)
        raise _Reject([replace(v, item_id=ids.get(v.item_id, v.item_id)) for v in violations])

    warnings = []
    if new_pkg.total > new_pkg.budget:
        warnings.append(f"The package now costs {rupees(new_pkg.total)}, which is "
                        f"{rupees(new_pkg.total - new_pkg.budget)} over the budget of {rupees(new_pkg.budget)}.")
    for c in changed:
        if c.source == AUTOMATIC_REPAIR:
            warnings.append(c.reason)
    return ChangeProposal(True, new_pkg, [], changed, [c for c in changed if c.source == AUTOMATIC_REPAIR],
                          old.total, new_pkg.total, new_pkg.total - old.total, new_pkg.budget - new_pkg.total,
                          warnings)
