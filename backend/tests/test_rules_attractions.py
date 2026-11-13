from datetime import date, datetime, time, timedelta

import pytest

from app.catalog.load import load_catalog
from app.lib.time import weekday_code
from app.rules.attractions import check_attractions, day_count_violations
from app.rules.common import EDITED, INITIAL, Stay, Visit

D0 = date(2027, 4, 10)


@pytest.fixture(scope="module")
def data():
    return load_catalog()


def dt(s):
    return datetime.fromisoformat(s)


def visit(aid, start, end):
    return Visit(None, aid, dt(start), dt(end))


def rule_set(violations):
    return {v.rule for v in violations}


def check(data, visits, day=D0, nights=1, mode=INITIAL, ready=None):
    end = day + timedelta(days=nights)
    stays = [Stay(None, "HTL-TYO-001", "RM-TYO-001-A", "Tokyo", day, end, 1)]
    if ready is None:
        ready = {day: datetime.combine(day, time(0, 0))}
    return check_attractions(visits, stays, day, end, ready, [], mode, data)


def test_closed_date_gives_att_3(data):
    d = date(2027, 4, 12)   # ATT-TYO-002 Tokyo Disneyland is closed on this date
    v = check(data, [visit("ATT-TYO-002", "2027-04-12T09:00", "2027-04-12T17:00")], day=d)
    assert rule_set(v) == {"R-ATT-3"}


def test_closed_weekday_gives_att_4(data):
    # ATT-TYO-003 has no THU in open_days; pick the first date that falls on a closed weekday.
    rec = data.indexes.attractions_by_id["ATT-TYO-003"]
    d = next(date(2027, 4, 1) + timedelta(days=i) for i in range(7)
             if weekday_code(date(2027, 4, 1) + timedelta(days=i)) not in rec["open_days"])
    v = check(data, [visit("ATT-TYO-003", f"{d}T10:00", f"{d}T11:30")], day=d)
    assert rule_set(v) == {"R-ATT-4"}


def test_visit_ending_after_open_until_gives_att_5(data):
    # ATT-TYO-001 is open 09:00-22:00; a 120-minute visit from 21:00 ends at 23:00.
    v = check(data, [visit("ATT-TYO-001", "2027-04-10T21:00", "2027-04-10T23:00")])
    assert rule_set(v) == {"R-ATT-5"}


def test_duplicate_attraction_gives_att_7(data):
    v = check(data, [visit("ATT-TYO-001", "2027-04-10T09:00", "2027-04-10T11:00"),
                     visit("ATT-TYO-001", "2027-04-10T13:00", "2027-04-10T15:00")])
    assert rule_set(v) == {"R-ATT-7"}


@pytest.mark.parametrize("second_start, second_end, expected", [
    ("2027-04-10T10:59", "2027-04-10T11:59", {"R-ATT-8"}),   # one minute overlap
    ("2027-04-10T11:00", "2027-04-10T12:00", set()),         # touching is fine
])
def test_visit_overlap(data, second_start, second_end, expected):
    v = check(data, [visit("ATT-TYO-004", "2027-04-10T10:00", "2027-04-10T11:00"),
                     visit("ATT-TYO-010", second_start, second_end)])
    assert rule_set(v) == expected


def test_visit_on_start_date_before_ready_gives_att_10(data):
    ready = {D0: datetime(2027, 4, 10, 10, 0)}
    v = check(data, [visit("ATT-TYO-004", "2027-04-10T09:00", "2027-04-10T10:00")], ready=ready)
    assert rule_set(v) == {"R-ATT-10"}


def test_empty_full_day_is_att_12_under_initial_only(data):
    # 3 nights: Apr 11 and Apr 12 are full days with no visits.
    kwargs = dict(nights=3)
    assert rule_set(check(data, [], mode=INITIAL, **kwargs)) == {"R-ATT-12"}
    assert len(check(data, [], mode=INITIAL, **kwargs)) == 2
    assert check(data, [], mode=EDITED, **kwargs) == []


def test_visit_on_end_date_gives_att_11(data):
    # One night from Apr 10: the end date is Apr 11. A visit on Apr 11 is outside the package nights.
    v = check(data, [visit("ATT-TYO-004", "2027-04-11T09:00", "2027-04-11T10:00")])
    assert rule_set(v) == {"R-ATT-2", "R-ATT-11"}


@pytest.mark.parametrize("n, mode, violates", [
    (0, INITIAL, True),
    (1, INITIAL, False),
    (2, INITIAL, False),
    (3, INITIAL, True),
    (0, EDITED, False),
    (3, EDITED, False),
])
def test_day_count_violations(n, mode, violates):
    v = visit("ATT-TYO-004", "2027-04-10T09:00", "2027-04-10T10:00")
    out = day_count_violations({D0: [v] * n}, [D0], mode)
    assert (len(out) == 1) is violates
    assert all(x.rule == "R-ATT-12" for x in out)


def test_day_count_unknown_mode_raises():
    with pytest.raises(ValueError):
        day_count_violations({}, [], "BOGUS")
