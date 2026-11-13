"""Attraction scheduling on controlled tiny worlds (tests/synth.py).

Run from backend/: ../.venv/bin/python -m pytest -q tests/test_attraction_scheduler.py
"""
from datetime import date, datetime, timedelta

from app.engine.model import CityPlan, CityStay
from app.engine.schedule import FULL, classify_days, make_visit, schedule_attractions
from app.lib.time import weekday_code
from app.rules.common import Party
from synth import World, request

START = date(2027, 4, 10)          # Saturday
D_ARR, D_FULL1, D_FULL2, D_DEP = (START + timedelta(days=i) for i in range(4))   # 3-night plan
SUN, MON = weekday_code(D_FULL1), weekday_code(D_FULL2)   # full days of a 3-night plan


def city_plan(legs, start=START):
    """legs = [(city, nights), ...] starting on START."""
    stays, d = [], start
    for city, n in legs:
        stays.append(CityStay(city, d, d + timedelta(days=n)))
        d += timedelta(days=n)
    return CityPlan("ZZ", tuple(stays))


def run(w, legs, req=None, **kw):
    nights = sum(n for _, n in legs)
    return schedule_attractions(city_plan(legs), (None, [], None), req or request(nights=nights, adults=1),
                                w.loaded(), **kw)


def visits_by_day(res):
    out = {}
    for v in res.visits:
        out.setdefault(v.start.date(), []).append(v)
    return out


def name_on(res, day):
    return {v.attraction_id for v in visits_by_day(res).get(day, [])}


def base(cities=("X",), links=()):
    """A valid synthetic catalog: the schedule only reads attractions, but the loader needs one
    record of every other kind too."""
    w = World(cities=cities, links=links)
    c = cities[0]
    w.flight("F-IN", "HOM", f"A{c}", "2027-04-09T22:00:00", "2027-04-10T08:00:00", 1000)
    w.hotel("H1", c)
    w.room("R1", "H1", 500)
    w.airport_transfer("T-AIR", f"A{c}", c, 100)
    return w


def test_single_city_three_nights_one_attraction_per_full_day():
    w = base()
    for i, p in enumerate((10, 20, 30), start=1):
        w.attraction(f"A{i}", "X", p)
    res = run(w, [("X", 3)])
    assert res.feasible
    by_day = visits_by_day(res)
    assert set(by_day) == {D_FULL1, D_FULL2}            # arrival and departure days have none
    assert all(len(v) == 1 for v in by_day.values())    # each full day: exactly one attraction


def test_two_full_days_use_distinct_attractions_at_cheapest_total():
    w = base()
    for aid, p in (("A", 10), ("B", 20), ("C", 30)):
        w.attraction(aid, "X", p)
    res = run(w, [("X", 3)])
    assert res.feasible
    ids = [v.attraction_id for v in res.visits]
    assert len(set(ids)) == len(ids) == 2
    assert res.total_price == 30 and set(ids) == {"A", "B"}


def test_greedy_trap_is_solved_exactly():
    # A is open on both full days; B only on day 1 (SUN). Greedy giving A to day 1 would strand day 2.
    w = base()
    w.attraction("A", "X", 10)
    w.attraction("B", "X", 20, open_days=[SUN])
    res = run(w, [("X", 3)])
    assert res.feasible
    assert name_on(res, D_FULL1) == {"B"}
    assert name_on(res, D_FULL2) == {"A"}
    assert res.total_price == 30


def test_closed_weekday_is_respected():
    w = base()
    w.attraction("X1", "X", 1, open_days=[MON])      # closed on SUN (day 1)
    w.attraction("Y1", "X", 2)
    res = run(w, [("X", 3)])
    assert res.feasible
    assert name_on(res, D_FULL1) == {"Y1"}
    assert name_on(res, D_FULL2) == {"X1"}


def test_explicit_closed_date_is_respected():
    w = base()
    w.attraction("X1", "X", 1, closed_dates=[D_FULL1.isoformat()])
    w.attraction("Y1", "X", 2)
    res = run(w, [("X", 3)])
    assert res.feasible
    assert "X1" not in name_on(res, D_FULL1)
    assert name_on(res, D_FULL2) == {"X1"}
    assert all(v.attraction_id != "X1" for v in visits_by_day(res).get(D_FULL1, []))


def test_visit_never_runs_past_closing_time():
    # two nights -> exactly one full day (START+1)
    day = START + timedelta(days=1)
    w = base()
    w.attraction("LATE", "X", 10, hours=("09:00", "10:30"), minutes=120)
    res = run(w, [("X", 2)])
    assert not res.feasible and res.failed_day == day

    w = base()
    w.attraction("OK", "X", 10, hours=("09:00", "11:00"), minutes=120)
    res = run(w, [("X", 2)])
    assert res.feasible
    (v,) = res.visits
    assert v.start == datetime(day.year, day.month, day.day, 9, 0)
    assert v.end == datetime(day.year, day.month, day.day, 11, 0)


def test_required_full_day_without_any_attraction_is_infeasible():
    w = base()
    w.attraction("A", "X", 10, open_days=[MON])     # nothing open on day 1 (SUN)
    res = run(w, [("X", 3)])
    assert res.feasible is False
    assert res.reason
    assert res.failed_day == D_FULL1


def test_each_city_full_days_use_only_that_citys_attractions():
    w = base(("X", "Y"), (("X", "Y"),))
    w.attraction("AX", "X", 1)
    w.attraction("AY", "Y", 1)
    w.attraction("AX2", "X", 2)
    w.attraction("AY2", "Y", 2)
    res = run(w, [("X", 2), ("Y", 2)])
    assert res.feasible
    by_day = visits_by_day(res)
    x_day, y_day = START + timedelta(days=1), START + timedelta(days=3)
    assert {v.attraction_id for v in by_day[x_day]} <= {"AX", "AX2"}
    assert {v.attraction_id for v in by_day[y_day]} <= {"AY", "AY2"}
    assert set(by_day) == {x_day, y_day}


def test_free_attraction_is_preferred_for_minimum_cost():
    w = base()
    w.attraction("FREE", "X", 0)
    w.attraction("P", "X", 30)
    w.attraction("Q", "X", 40)
    res = run(w, [("X", 3)])
    assert res.feasible
    assert "FREE" in {v.attraction_id for v in res.visits}
    assert res.total_price == 30
    assert sum(v.price for v in res.visits) == res.total_price


def test_child_price_zero_counts_as_zero():
    w = base()
    w.attraction("K", "X", 50, child_price=0)
    res = run(w, [("X", 2)], req=request(nights=2, adults=1, children=(6,)))
    assert res.feasible
    (v,) = res.visits
    assert v.attraction_id == "K"
    assert v.quantity == 2
    assert v.price == 50 and res.total_price == 50


def test_excluded_attractions_are_never_used():
    w = base()
    w.attraction("E", "X", 1)
    w.attraction("G", "X", 5)
    w.attraction("H", "X", 6)
    res = run(w, [("X", 3)], excluded=frozenset({"E"}))
    assert res.feasible
    assert "E" not in {v.attraction_id for v in res.visits}
    assert res.total_price == 11


def test_pinned_visit_is_kept_exactly_and_its_attraction_is_not_reused():
    w = base()
    w.attraction("P", "X", 1)
    w.attraction("Q", "X", 2)
    data = w.loaded()
    pinned = make_visit(data.catalog.attractions[0], datetime(2027, 4, 11, 10, 0), Party(1, ()))
    res = schedule_attractions(city_plan([("X", 3)]), (None, [], None), request(nights=3, adults=1), data,
                               pinned=(pinned,))
    assert res.feasible
    assert pinned in res.visits
    assert [v.attraction_id for v in res.visits].count("P") == 1
    assert name_on(res, D_FULL2) == {"Q"}
    assert res.total_price == 2


def test_free_second_visits_are_zero_price_and_do_not_overlap_the_first():
    w = base()
    w.attraction("A", "X", 0)           # the required visit (cheapest, id order)
    w.attraction("B", "X", 20)          # paid: must not be added as a free second visit
    w.attraction("C", "X", 0)           # free second visit
    res = run(w, [("X", 2)], second="FREE")
    assert res.feasible
    day = START + timedelta(days=1)
    visits = sorted(visits_by_day(res)[day], key=lambda v: v.start)
    assert [v.attraction_id for v in visits] == ["A", "C"]
    assert all(v.price == 0 for v in visits)
    assert res.total_price == 0
    assert visits[0].end <= visits[1].start or visits[1].end <= visits[0].start
