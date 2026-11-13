"""Dependency repair in propose_change: what a change makes stale is repaired, nothing else.

Synthetic worlds from change_world.py; base packages come from the real planner. Numbers in test
names refer to the Phase 5 test list (spec section 17). Single-item changes are in test_change_engine.py.

Run from backend/: ../.venv/bin/python -m pytest -q tests/test_dependency_repair.py
"""

from datetime import date, datetime, timedelta

import pytest

from app.engine.change import dependency_impact, propose_change
from app.engine.repair import AUTOMATIC_REPAIR, USER_CHOICE
from app.export.to_trip import to_trip_json
from app.models import CHANGE_COMMAND
from app.rules.common import EDITED
from app.validate.validate_trip import validate_trip
from change_world import D10, D13, base, single_city, three_city, two_city

STAY_X, STAY_Y = "stay:X:2027-04-10:2027-04-13", "stay:Y:2027-04-13:2027-04-16"
LEG_XY = "leg:X>Y:2027-04-13"

TWO = base(two_city())
SINGLE = base(single_city(), nights=4)
THREE = base(three_city(), nights=9)
SINGLE_STAY = SINGLE[0].hotels[0].stay_id
THREE_Y = THREE[0].hotels[1].stay_id


def cmd(**fields):
    return CHANGE_COMMAND.validate_python({"base_version": 1, **fields})


def assert_valid(r, data):
    assert r.valid, [(v.rule, v.message) for v in r.violations]
    p = r.proposed_package
    assert validate_trip(to_trip_json(p, data), data, EDITED) == []
    assert (
        r.new_total
        == p.total
        == sum(i["price_inr"] for i in to_trip_json(p, data)["items"])
    )
    return p


def changed(old, new) -> set[str]:
    out = set()
    if old.arrival_flight != new.arrival_flight:
        out.add("flight:arrival")
    if old.return_flight != new.return_flight:
        out.add("flight:return")
    out |= {a.stay_id for a, b in zip(old.hotels, new.hotels, strict=True) if a != b}
    olegs = {
        t.leg_id: t
        for t in (old.arrival_transfer, *old.intercity, old.departure_transfer)
    }
    nlegs = {
        t.leg_id: t
        for t in (new.arrival_transfer, *new.intercity, new.departure_transfer)
    }
    out |= {k for k in olegs if olegs[k] != nlegs.get(k)}
    ov, nv = (
        {v.attraction_id: v for v in old.visits},
        {v.attraction_id: v for v in new.visits},
    )
    out |= {f"visit:{a}" for a in ov.keys() | nv.keys() if ov.get(a) != nv.get(a)}
    return out


def by_id(r):
    return {i.component: i for i in r.changed_items}


def visit(p, attraction_id):
    return next((v for v in p.visits if v.attraction_id == attraction_id), None)


def with_visit(attraction_id, day, **after):
    """TWO's package with one extra visit added first (then optionally the next change on top)."""
    pkg, data = TWO
    r = propose_change(
        pkg, cmd(kind="ADD_ATTRACTION", date=day, attraction_id=attraction_id), data
    )
    assert_valid(r, data)
    return r.proposed_package


# ------------------------------------------------------------------ cases for tests 36, 40, invariant

HOTEL_X_B = dict(kind="CHANGE_HOTEL", stay_id=STAY_X, hotel_id="HX-B", room_id="RX-B")
HOTEL_Y_B = dict(kind="CHANGE_HOTEL", stay_id=STAY_Y, hotel_id="HY-B", room_id="RY-B")
IN_LATE = dict(kind="CHANGE_ARRIVAL_FLIGHT", flight_id="F-IN-LATE")
IN_AX2 = dict(kind="CHANGE_ARRIVAL_FLIGHT", flight_id="F-IN-AX2")
OUT_MID = dict(kind="CHANGE_RETURN_FLIGHT", flight_id="F-OUT-MID")
XY_SLOW = dict(
    kind="CHANGE_INTERCITY_TRANSFER", item_id=LEG_XY, transfer_id="TR-XY-SLOW"
)


def _cases():
    """(name, package, catalog, command) for every dependency-repairing change, some composed."""
    pkg, data = TWO
    yield "hotel-first", pkg, data, HOTEL_X_B
    yield "hotel-last", pkg, data, HOTEL_Y_B
    yield "arrival-ax2", pkg, data, IN_AX2
    yield "arrival-late", pkg, data, IN_LATE
    yield "return-mid", pkg, data, OUT_MID
    yield "intercity-slow", pkg, data, XY_SLOW
    yield (
        "airport-any",
        pkg,
        data,
        dict(
            kind="CHANGE_AIRPORT_TRANSFER",
            item_id="leg:arrival",
            transfer_id="T-AX-ANY",
        ),
    )
    spkg, sdata = SINGLE
    yield (
        "hotel-single",
        spkg,
        sdata,
        dict(kind="CHANGE_HOTEL", stay_id=SINGLE_STAY, hotel_id="HS-B", room_id="RS-B"),
    )
    tpkg, tdata = THREE
    yield (
        "hotel-middle",
        tpkg,
        tdata,
        dict(kind="CHANGE_HOTEL", stay_id=THREE_Y, hotel_id="HY-B", room_id="RY-B"),
    )
    yield (
        "arrival-late+morning-visit",
        with_visit("ATT-X-MORNING", "2027-04-10"),
        data,
        IN_LATE,
    )
    yield "arrival-late+visit", with_visit("ATT-X-3", "2027-04-10"), data, IN_LATE
    yield (
        "intercity-slow+day-visit",
        with_visit("ATT-Y-DAY", "2027-04-13"),
        data,
        XY_SLOW,
    )
    yield (
        "intercity-slow+evening-visit",
        with_visit("ATT-Y-3", "2027-04-13"),
        data,
        XY_SLOW,
    )


CASES = list(_cases())
VALID = []
for _name, _pkg, _data, _fields in CASES:
    _r = propose_change(_pkg, cmd(**_fields), _data)
    assert _r.valid, (_name, [(v.rule, v.message) for v in _r.violations])
    VALID.append((_name, _pkg, _data, _fields, _r))
IDS = [c[0] for c in VALID]


# ------------------------------------------------------------------ hotel changes (5-8)


def test_5_first_hotel_change_repairs_arrival_transfer():
    pkg, data = TWO
    r = propose_change(pkg, cmd(**HOTEL_X_B), data)
    p = assert_valid(r, data)
    assert (p.arrival_transfer.transfer_id, pkg.arrival_transfer.transfer_id) == (
        "T-AX-B",
        "T-AX-A",
    )
    assert r.price_difference == 350
    items = by_id(r)
    assert set(items) == {STAY_X, "leg:arrival"}
    assert items[STAY_X].source == USER_CHOICE and items[STAY_X].price_delta == 300
    assert (
        items["leg:arrival"].source == AUTOMATIC_REPAIR
        and items["leg:arrival"].price_delta == 50
    )
    assert [i.component for i in r.automatic_repairs] == ["leg:arrival"]
    assert changed(pkg, p) == {STAY_X, "leg:arrival"}  # the departure side is untouched
    assert p.departure_transfer == pkg.departure_transfer


def test_6_last_hotel_change_repairs_departure_transfer():
    pkg, data = TWO
    r = propose_change(pkg, cmd(**HOTEL_Y_B), data)
    p = assert_valid(r, data)
    assert (p.departure_transfer.transfer_id, pkg.departure_transfer.transfer_id) == (
        "T-AY-B",
        "T-AY-A",
    )
    assert r.price_difference == 350
    assert [i.component for i in r.automatic_repairs] == ["leg:departure"]
    assert changed(pkg, p) == {STAY_Y, "leg:departure"}
    assert p.arrival_transfer == pkg.arrival_transfer


def test_7_single_city_hotel_change_rechecks_both_transfers():
    pkg, data = SINGLE
    r = propose_change(
        pkg,
        cmd(kind="CHANGE_HOTEL", stay_id=SINGLE_STAY, hotel_id="HS-B", room_id="RS-B"),
        data,
    )
    p = assert_valid(r, data)
    assert p.arrival_transfer.transfer_id == "T-AS-B"
    assert p.departure_transfer.transfer_id == "T-AS-B"
    assert {i.component for i in r.automatic_repairs} == {
        "leg:arrival",
        "leg:departure",
    }
    assert changed(pkg, p) == {SINGLE_STAY, "leg:arrival", "leg:departure"}
    assert r.price_difference == 600 + 40 + 40


def test_8_middle_hotel_change_touches_only_the_stay():
    pkg, data = THREE
    r = propose_change(
        pkg,
        cmd(kind="CHANGE_HOTEL", stay_id=THREE_Y, hotel_id="HY-B", room_id="RY-B"),
        data,
    )
    p = assert_valid(r, data)
    assert changed(pkg, p) == {THREE_Y}
    assert r.automatic_repairs == []
    assert [h.hotel_id for h in p.hotels] == ["HX-A", "HY-B", "HZ-A"]
    assert (p.arrival_flight, p.return_flight) == (
        pkg.arrival_flight,
        pkg.return_flight,
    )
    assert p.visits == pkg.visits


# ------------------------------------------------------------------ flight changes (13-16)


def test_13_arrival_airport_change_replaces_the_transfer():
    pkg, data = TWO
    r = propose_change(pkg, cmd(**IN_AX2), data)
    p = assert_valid(r, data)
    assert p.arrival_flight.to_airport == "AX2"
    assert p.arrival_transfer.transfer_id == "T-AX2-A"  # same hotel area, new airport
    assert by_id(r)["leg:arrival"].source == AUTOMATIC_REPAIR
    assert p.arrival_transfer.pickup >= p.arrival_flight.arrival
    assert changed(pkg, p) == {"flight:arrival", "leg:arrival"}


def test_14_later_arrival_reschedules_the_pickup():
    pkg, data = TWO
    r = propose_change(pkg, cmd(**IN_LATE), data)
    p = assert_valid(r, data)
    assert p.arrival_flight.arrival.hour == 14
    assert pkg.arrival_transfer.pickup.hour == 9  # was before the new landing
    assert p.arrival_transfer.pickup >= p.arrival_flight.arrival
    assert (
        p.arrival_transfer.transfer_id == "T-AX-A"
    )  # same transfer, only the time moves
    assert by_id(r)["leg:arrival"].source == AUTOMATIC_REPAIR
    assert changed(pkg, p) == {"flight:arrival", "leg:arrival"}


def test_14_arrival_day_visit_is_rescheduled_when_it_still_fits():
    pkg, data = TWO
    before = with_visit("ATT-X-3", "2027-04-10")
    old = visit(before, "ATT-X-3")
    r = propose_change(before, cmd(**IN_LATE), data)
    p = assert_valid(r, data)
    new = visit(p, "ATT-X-3")
    assert new is not None and new.start != old.start and new.start.date() == D10
    assert new.start >= p.arrival_transfer.arrive  # after the guest reaches the hotel
    assert new.price == old.price
    assert by_id(r)["visit:ATT-X-3"].source == AUTOMATIC_REPAIR
    assert not [w for w in r.warnings if "ATT-X-3" in w]


def test_14_arrival_day_visit_that_cannot_fit_is_removed_with_disclosure():
    pkg, data = TWO
    before = with_visit("ATT-X-MORNING", "2027-04-10")  # open 09:00-12:00 only
    r = propose_change(before, cmd(**IN_LATE), data)
    p = assert_valid(r, data)
    assert visit(p, "ATT-X-MORNING") is None
    item = by_id(r)["visit:ATT-X-MORNING"]
    assert (
        item.source == AUTOMATIC_REPAIR
        and item.price_delta == -visit(before, "ATT-X-MORNING").price
    )
    assert any("ATT-X-MORNING" in w for w in r.warnings)  # never silent
    assert r.new_total == before.total + r.price_difference
    assert {v.attraction_id for v in p.visits} == {
        v.attraction_id for v in before.visits
    } - {"ATT-X-MORNING"}


def test_15_return_flight_reschedules_pickup_and_keeps_the_buffer():
    pkg, data = TWO
    r = propose_change(pkg, cmd(**OUT_MID), data)
    p = assert_valid(r, data)
    assert pkg.departure_transfer.pickup == datetime(2027, 4, 16, 14, 30)
    assert p.departure_transfer.pickup == datetime(2027, 4, 16, 11, 30)
    assert p.departure_transfer.transfer_id == "T-AY-A"
    assert (
        p.departure_transfer.arrive + timedelta(minutes=180)
        <= p.return_flight.departure
    )
    assert by_id(r)["leg:departure"].source == AUTOMATIC_REPAIR
    assert changed(pkg, p) == {"flight:return", "leg:departure"}


def test_16_return_flight_with_no_compatible_transfer_is_refused():
    pkg, data = TWO
    snapshot = repr(pkg)
    r = propose_change(
        pkg, cmd(kind="CHANGE_RETURN_FLIGHT", flight_id="F-OUT-EARLY"), data
    )
    assert not r.valid and r.proposed_package is None and r.new_total is None
    got = {v.rule for v in r.violations}
    assert {"NO_DEPARTURE_TRANSFER", "R-ATR-7"} <= got
    assert all(v.item_id for v in r.violations)
    assert repr(pkg) == snapshot  # the saved package is untouched


# ------------------------------------------------------------------ intercity change (22)


def test_22_slow_intercity_removes_a_change_day_visit_that_no_longer_fits():
    pkg, data = TWO
    before = with_visit("ATT-Y-DAY", "2027-04-13")  # open 09:00-18:00
    assert visit(before, "ATT-Y-DAY").start.date() == D13
    r = propose_change(before, cmd(**XY_SLOW), data)
    p = assert_valid(r, data)
    assert p.intercity[0].transfer_id == "TR-XY-SLOW"
    assert visit(p, "ATT-Y-DAY") is None
    assert any("ATT-Y-DAY" in w for w in r.warnings)
    assert by_id(r)["visit:ATT-Y-DAY"].source == AUTOMATIC_REPAIR
    assert visit(p, "ATT-Y-1") == visit(before, "ATT-Y-1")  # later days untouched


def test_22_slow_intercity_reschedules_a_change_day_visit_when_it_can():
    pkg, data = TWO
    before = with_visit("ATT-Y-3", "2027-04-13")  # any time of day
    r = propose_change(before, cmd(**XY_SLOW), data)
    p = assert_valid(r, data)
    new = visit(p, "ATT-Y-3")
    assert new is not None and new.start >= p.intercity[0].arrive
    assert new.start != visit(before, "ATT-Y-3").start
    assert not [w for w in r.warnings if "ATT-Y-3" in w]
    assert by_id(r)["visit:ATT-Y-3"].source == AUTOMATIC_REPAIR


# ------------------------------------------------------------------ totals (36), choice (40), scope


@pytest.mark.parametrize("name,pkg,data,fields,r", VALID, ids=IDS)
def test_36_total_reflects_every_dependent_change(name, pkg, data, fields, r):
    delta = sum(i.price_delta for i in r.changed_items)
    assert r.new_total == r.old_total + delta == r.old_total + r.price_difference
    assert r.old_total == pkg.total
    assert r.new_total == sum(
        i["price_inr"] for i in to_trip_json(r.proposed_package, data)["items"]
    )


def test_36_repairs_are_priced_in_the_total():
    pkg, data = TWO
    r = propose_change(pkg, cmd(**HOTEL_X_B), data)
    assert r.price_difference == 300 + 50  # the stay and the dearer transfer
    assert r.new_total == 11120 + 350


def _holds_request(p, fields) -> bool:
    kind = fields["kind"]
    if kind == "CHANGE_ARRIVAL_FLIGHT":
        return p.arrival_flight.flight_id == fields["flight_id"]
    if kind == "CHANGE_RETURN_FLIGHT":
        return p.return_flight.flight_id == fields["flight_id"]
    if kind == "CHANGE_HOTEL":
        h = next(h for h in p.hotels if h.stay_id == fields["stay_id"])
        return (h.hotel_id, h.room_id) == (fields["hotel_id"], fields["room_id"])
    if kind == "CHANGE_AIRPORT_TRANSFER":
        leg = (
            p.arrival_transfer
            if fields["item_id"] == "leg:arrival"
            else p.departure_transfer
        )
        return leg.transfer_id == fields["transfer_id"]
    if kind == "CHANGE_INTERCITY_TRANSFER":
        leg = next(t for t in p.intercity if t.leg_id == fields["item_id"])
        return leg.transfer_id == fields["transfer_id"]
    raise AssertionError(kind)


@pytest.mark.parametrize("name,pkg,data,fields,r", VALID, ids=IDS)
def test_40_the_chosen_item_is_never_silently_replaced(name, pkg, data, fields, r):
    assert _holds_request(r.proposed_package, fields)
    assert by_id(r)[_target(fields)].source == USER_CHOICE


def _target(fields) -> str:
    return (
        fields.get("stay_id")
        or fields.get("item_id")
        or (
            "flight:arrival"
            if fields["kind"] == "CHANGE_ARRIVAL_FLIGHT"
            else "flight:return"
        )
    )


def _allowed(pkg, fields) -> set[str]:
    impact = dependency_impact(pkg, cmd(**fields))
    assert impact is not None
    allowed = {_target(fields)}
    for scope in impact.repair_scope:
        if scope.startswith("visits:"):
            day = date.fromisoformat(scope.removeprefix("visits:"))
            allowed |= {
                f"visit:{v.attraction_id}" for v in pkg.visits if v.start.date() == day
            }
        else:
            allowed.add(scope)
    return allowed


@pytest.mark.parametrize("name,pkg,data,fields,r", VALID, ids=IDS)
def test_changed_items_stay_inside_the_dependency_scope(name, pkg, data, fields, r):
    p = r.proposed_package
    assert changed(pkg, p) <= _allowed(pkg, fields), (
        changed(pkg, p),
        _allowed(pkg, fields),
    )
    assert {i.component for i in r.changed_items} == changed(pkg, p)


def test_the_input_package_is_never_mutated_by_a_repair():
    for _name, pkg, _data, fields, _r in VALID:
        again = propose_change(pkg, cmd(**fields), _data)
        assert again == _r  # deterministic
