"""Attraction visit rules (R-ATT-*). Pure: (visits, stays, dates, busy, mode, catalog) -> violations."""
from datetime import date, datetime, timedelta

from app.lib.time import date_range, overlaps, parse_date, weekday_code, window_on
from app.rules.common import EDITED, INITIAL, Busy, Stay, Violation, Visit


def _city_of_stay(stay: Stay, data) -> str:
    hotel = data.indexes.hotels_by_id.get(stay.hotel_id)
    return hotel["city"] if hotel else stay.city


def day_count_violations(visits_by_date: dict[date, list[Visit]], full_days: list[date], mode: str) -> list[Violation]:
    """R-ATT-12: INITIAL packages need 1 or 2 visits on every full day. EDITED has no per-day limit."""
    if mode not in (INITIAL, EDITED):
        raise ValueError(f"Unknown mode {mode!r}; expected {INITIAL!r} or {EDITED!r}")
    if mode == EDITED:
        return []
    out: list[Violation] = []
    for d in full_days:
        n = len(visits_by_date.get(d, []))
        if n == 0 or n > 2:
            out.append(Violation(
                "R-ATT-12",
                f"Full day {d.isoformat()} has {n} attraction visits; an initial package needs 1 or 2.",
            ))
    return out


def check_attractions(visits: list[Visit], stays: list[Stay], start_date: date, end_date: date,
                      ready_at: dict[date, datetime], busy: list[Busy], mode: str, data) -> list[Violation]:
    A = data.indexes.attractions_by_id
    out: list[Violation] = []

    # City of each night's date, from the catalog hotel of the stay that covers it.
    city_of: dict[date, str] = {}
    for s in stays:
        city = _city_of_stay(s, data)
        for d in date_range(s.check_in, s.nights):
            city_of[d] = city
    change_dates = {s.check_in for s in stays[1:]}
    last_night = end_date - timedelta(days=1)

    visits_by_date: dict[date, list[Visit]] = {}
    for v in visits:
        visits_by_date.setdefault(v.start.date(), []).append(v)

    seen_ids: set[str] = set()
    for v in visits:
        a = A.get(v.attraction_id)
        if a is None:
            out.append(Violation("R-ATT-1", f"Unknown attraction {v.attraction_id}.", v.item_id))
            continue

        d = v.start.date()
        dup = v.attraction_id in seen_ids
        seen_ids.add(v.attraction_id)

        # R-ATT-2: the attraction must be in the city of that night and the visit inside the package dates.
        city_here = city_of.get(d)
        if not (start_date <= d <= last_night) or city_here is None or a["city"] != city_here:
            out.append(Violation(
                "R-ATT-2",
                f"Attraction {v.attraction_id} is in {a['city']}, but {d.isoformat()} is in "
                f"{city_here or 'no city of the package'}.",
                v.item_id,
            ))

        # R-ATT-3: closed on this date.
        closed = {parse_date(x) for x in a.get("closed_dates") or []}
        if d in closed:
            out.append(Violation(
                "R-ATT-3", f"Attraction {v.attraction_id} is closed on {d.isoformat()}.", v.item_id))

        # R-ATT-4: weekday must be an open day.
        if weekday_code(d) not in a["open_days"]:
            out.append(Violation(
                "R-ATT-4",
                f"Attraction {v.attraction_id} is not open on {weekday_code(d)} ({d.isoformat()}).",
                v.item_id))

        # R-ATT-5: the whole visit inside the opening hours of that date.
        open_s, open_e = window_on(d, a["open_from"], a["open_until"])
        if not (open_s <= v.start and v.end <= open_e):
            out.append(Violation(
                "R-ATT-5",
                f"Visit to {v.attraction_id} {v.start:%Y-%m-%dT%H:%M}-{v.end:%H:%M} is outside opening hours "
                f"{a['open_from']}-{a['open_until']}.",
                v.item_id))

        # R-ATT-6: the visit length must match the catalog.
        minutes = (v.end - v.start).total_seconds() / 60
        if v.end <= v.start or minutes != a["visit_minutes"]:
            out.append(Violation(
                "R-ATT-6",
                f"Visit to {v.attraction_id} lasts {minutes:g} minutes; it must be "
                f"{a['visit_minutes']} minutes and end after it starts.",
                v.item_id))

        # R-ATT-7: each attraction at most once in the package.
        if dup:
            out.append(Violation(
                "R-ATT-7", f"Attraction {v.attraction_id} appears more than once in the package.", v.item_id))

        # R-ATT-9: no visit during a busy block (for example a transfer).
        for b in busy:
            if overlaps((v.start, v.end), (b.start, b.end)):
                out.append(Violation(
                    "R-ATT-9",
                    f"Visit to {v.attraction_id} {v.start:%Y-%m-%dT%H:%M} overlaps {b.label} "
                    f"{b.start:%Y-%m-%dT%H:%M}-{b.end:%Y-%m-%dT%H:%M}.",
                    v.item_id))

        # R-ATT-10: on the start date or a change date, the visit starts after the traveler is ready.
        if d == start_date or d in change_dates:
            ready = ready_at.get(d)
            if ready is None:
                out.append(Violation(
                    "R-ATT-10", f"No ready time is known for {d.isoformat()}; visit {v.attraction_id} cannot be checked.",
                    v.item_id))
            elif v.start < ready:
                out.append(Violation(
                    "R-ATT-10",
                    f"Visit to {v.attraction_id} starts {v.start:%Y-%m-%dT%H:%M}, before the traveler is ready "
                    f"at {ready:%Y-%m-%dT%H:%M}.",
                    v.item_id))

        # R-ATT-11: no visits on the end date (the day of departure).
        if d == end_date:
            out.append(Violation(
                "R-ATT-11", f"Visit to {v.attraction_id} is on the end date {end_date.isoformat()}.", v.item_id))

    # R-ATT-8: two visits must not overlap (touching is fine).
    for i, x in enumerate(visits):
        if x.attraction_id not in A:
            continue
        for y in visits[i + 1:]:
            if y.attraction_id not in A:
                continue
            if overlaps((x.start, x.end), (y.start, y.end)):
                out.append(Violation(
                    "R-ATT-8",
                    f"Visits to {x.attraction_id} and {y.attraction_id} overlap on {x.start.date().isoformat()}.",
                    y.item_id))

    # R-ATT-12: per-day visit counts on full days (policy depends on mode).
    full_days = [start_date + timedelta(days=i) for i in range(1, (end_date - start_date).days)
                 if start_date + timedelta(days=i) not in change_dates]
    out.extend(day_count_violations(visits_by_date, full_days, mode))

    return out
