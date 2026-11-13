"""Attraction scheduling: exact minimum-cost assignment of distinct attractions to full days.

Not greedy. For each city the required days and the attractions form a bipartite graph (an edge
exists when a valid visit interval exists that day). A dynamic programme over "set of days already
covered" finds the cheapest set of distinct attractions that covers every required day - or proves
that none exists. Preferences (child friendly, 10:00 start) only break ties, never validity.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.engine.model import CityPlan, TransferOption, VisitOption
from app.lib.time import at, overlaps, parse_date, weekday_code, window_on
from app.rules.common import Party
from app.rules.pricing import attraction_price

ARRIVAL, FULL, CHANGE, DEPARTURE = "ARRIVAL", "FULL", "CHANGE", "DEPARTURE"
PREFERRED_START = "10:00"       # a preference only
GAP_MINUTES = 60                # preferred pause between two visits on a day (preference only)

Block = tuple[datetime, datetime]


@dataclass(frozen=True)
class DaySlot:
    day: date
    city: str
    kind: str


@dataclass(frozen=True)
class AttractionScheduleResult:
    feasible: bool
    visits: tuple[VisitOption, ...]
    total_price: int
    reason: str | None = None
    failed_day: date | None = None


def classify_days(plan: CityPlan) -> list[DaySlot]:
    """Every day of the holiday with the city of that night's hotel and its kind."""
    change = {s.check_in: s.city for s in plan.stays[1:]}
    out: list[DaySlot] = []
    d = plan.start_date
    while d <= plan.end_date:
        if d == plan.end_date:
            out.append(DaySlot(d, plan.last_city, DEPARTURE))
        else:
            city = next(s.city for s in plan.stays if s.check_in <= d < s.check_out)
            kind = ARRIVAL if d == plan.start_date else CHANGE if d in change else FULL
            out.append(DaySlot(d, city, kind))
        d += timedelta(days=1)
    return out


def transfer_blocks(plan: CityPlan, arrival: TransferOption | None, intercity,
                    departure: TransferOption | None) -> list[Block]:
    """Times when the traveler cannot visit anything: before reaching the first hotel, from the
    start of a city-change day until arriving in the new city, and from the airport pickup on."""
    blocks: list[Block] = []
    if arrival is not None:
        blocks.append((datetime.min, arrival.arrive))
    for (_, _, day), t in zip(plan.legs(), intercity):
        blocks.append((at(day, "00:00"), t.arrive))
    if departure is not None:
        blocks.append((departure.pickup, datetime.max))
    return blocks


def open_on(attraction: dict, day: date) -> bool:
    if weekday_code(day) not in attraction["open_days"]:
        return False
    return day not in {parse_date(x) for x in attraction.get("closed_dates") or []}


def fits(attraction: dict, day: date, start: datetime, blocks: list[Block]) -> bool:
    """True if a visit starting at `start` is entirely valid on `day` and clear of `blocks`."""
    if start.date() != day or not open_on(attraction, day):
        return False
    o_s, o_e = window_on(day, attraction["open_from"], attraction["open_until"])
    end = start + timedelta(minutes=attraction["visit_minutes"])
    if start < o_s or end > o_e:
        return False
    return not any(overlaps((start, end), b) for b in blocks)


def find_start(attraction: dict, day: date, blocks: list[Block],
               prefer: datetime | None = None) -> datetime | None:
    """A valid start time that day, or None. The earliest feasible start is always the opening time
    or the end of a block, so testing those (plus the preferred time) is complete."""
    if not open_on(attraction, day):
        return None
    o_s, _ = window_on(day, attraction["open_from"], attraction["open_until"])
    prefer = prefer or at(day, PREFERRED_START)
    cands = sorted({o_s, prefer, *(b[1] for b in blocks if b[1] != datetime.max)})
    ok = [t for t in cands if t >= o_s and fits(attraction, day, t, blocks)]
    late = [t for t in ok if t >= prefer]
    return late[0] if late else (ok[0] if ok else None)


def make_visit(attraction: dict, start: datetime, party: Party) -> VisitOption:
    q, p = attraction_price(attraction, party)
    return VisitOption(attraction["attraction_id"], start,
                       start + timedelta(minutes=attraction["visit_minutes"]), q, p)


def _rank(attraction: dict, party: Party) -> tuple:
    """Deterministic preference among equal prices."""
    child_ok = 0 if (party.children == 0 or attraction.get("child_friendly")) else 1
    return (child_ok, attraction["attraction_id"])


def _party(request) -> Party:
    return Party(request.adults, tuple(request.children_ages))


def schedule_attractions(plan: CityPlan, transfers, request, catalog, *,
                         excluded=frozenset(), pinned: tuple[VisitOption, ...] = (),
                         second: str = "NONE", budget_left: int | None = None
                         ) -> AttractionScheduleResult:
    """Cheapest valid set of visits giving every full day at least one attraction.

    transfers = (arrival_transfer, [intercity...], departure_transfer); any may be None/empty.
    pinned    = visits that must stay exactly as they are (they count for their day).
    excluded  = attraction ids that must not be used.
    second    = "NONE" | "FREE" (add zero-price second visits) | "BUDGET" (add second visits
                while they fit budget_left). Second visits never affect feasibility.
    """
    party = _party(request)
    arrival, intercity, departure = transfers
    static = transfer_blocks(plan, arrival, intercity, departure)
    A = catalog.indexes.attractions_by_city
    used = {v.attraction_id for v in pinned}
    pinned_blocks: dict[date, list[Block]] = {}
    for v in pinned:
        pinned_blocks.setdefault(v.start.date(), []).append((v.start, v.end))

    days = classify_days(plan)
    visits: list[VisitOption] = list(pinned)
    total = 0

    for city in dict.fromkeys(plan.cities):
        need = [s.day for s in days if s.city == city and s.kind == FULL and s.day not in pinned_blocks]
        if not need:
            continue
        cands = sorted((a for a in A.get(city, [])
                        if a["attraction_id"] not in excluded and a["attraction_id"] not in used),
                       key=lambda a: (attraction_price(a, party)[1], _rank(a, party)))
        starts = [[find_start(a, d, static) for d in need] for a in cands]
        # the most constrained day first makes the failure message point at the real blocker
        for j, d in enumerate(need):
            if not any(row[j] is not None for row in starts):
                return AttractionScheduleResult(
                    False, (), 0, f"No attraction in {city} can be visited on {d.isoformat()}.", d)

        full = (1 << len(need)) - 1
        # dp[mask] = (cost, chosen (attraction index, day index) pairs); attractions in rank order,
        # so among equal costs the earliest-ranked choice set wins deterministically.
        dp: dict[int, tuple[int, tuple]] = {0: (0, ())}
        for i, a in enumerate(cands):
            price = attraction_price(a, party)[1]
            nxt = dict(dp)
            for mask, (cost, chosen) in dp.items():
                for j in range(len(need)):
                    if mask & (1 << j) or starts[i][j] is None:
                        continue
                    m2, val = mask | (1 << j), (cost + price, chosen + ((i, j),))
                    if m2 not in nxt or val[0] < nxt[m2][0]:
                        nxt[m2] = val
            dp = nxt
        if full not in dp:
            return AttractionScheduleResult(
                False, (), 0, f"{city} does not have enough distinct open attractions for its "
                              f"{len(need)} full day(s).", need[0])
        cost, chosen = dp[full]
        total += cost
        for i, j in chosen:
            visits.append(make_visit(cands[i], starts[i][j], party))
            used.add(cands[i]["attraction_id"])

    if second in ("FREE", "BUDGET"):
        left = budget_left if second == "BUDGET" else 0
        for s in days:
            if s.kind != FULL:
                continue
            todays = sorted((v for v in visits if v.start.date() == s.day), key=lambda v: v.start)
            if len(todays) != 1:
                continue
            first = todays[0]
            gap = timedelta(minutes=GAP_MINUTES)
            blocks = static + [(first.start - gap, first.end + gap)]
            options = sorted((a for a in A.get(s.city, [])
                              if a["attraction_id"] not in excluded and a["attraction_id"] not in used),
                             key=lambda a: (_rank(a, party)[0], attraction_price(a, party)[1],
                                            a["attraction_id"]))
            for a in options:
                price = attraction_price(a, party)[1]
                if price > (left or 0):
                    continue
                st = find_start(a, s.day, blocks, prefer=first.end + gap)
                if st is None:
                    continue
                visits.append(make_visit(a, st, party))
                used.add(a["attraction_id"])
                total += price
                if second == "BUDGET":
                    left -= price
                break

    visits.sort(key=lambda v: (v.start, v.attraction_id))
    return AttractionScheduleResult(True, tuple(visits), total)
