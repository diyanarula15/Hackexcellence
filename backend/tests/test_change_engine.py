"""propose_change (app/engine/change.py): one typed traveler change -> a validated, repriced proposal.

Synthetic worlds from change_world.py (same schema as the supplied catalog, built through the
production loader); base packages come from the real planner. Numbers in test names refer to the
Phase 5 test list. Dependency repairs (transfers, rescheduled visits) are in test_dependency_repair.py.

Run from backend/: ../.venv/bin/python -m pytest -q tests/test_change_engine.py
"""

import copy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.engine.change import CHANGE_TARGET_NOT_FOUND, NO_CHANGE, propose_change
from app.engine.repair import USER_CHOICE
from app.export.to_trip import to_trip_json
from app.models import CHANGE_COMMAND
from app.rules.common import EDITED, INITIAL
from app.validate.validate_trip import validate_trip
from change_world import D10, D11, D12, D13, base, two_city

STAY_X, STAY_Y = "stay:X:2027-04-10:2027-04-13", "stay:Y:2027-04-13:2027-04-16"
LEG_XY = "leg:X>Y:2027-04-13"


def cmd(**fields):
    return CHANGE_COMMAND.validate_python({"base_version": 1, **fields})


@pytest.fixture(scope="module")
def env():
    pkg, data = base(two_city())
    return SimpleNamespace(pkg=pkg, data=data)


def propose(env, **fields):
    return propose_change(env.pkg, cmd(**fields), env.data)


def rules(r):
    return [v.rule for v in r.violations]


def assert_valid(r, data):
    """Valid, fully EDITED-valid, and every total recomputed from the items."""
    assert r.valid, [(v.rule, v.message) for v in r.violations]
    p = r.proposed_package
    assert validate_trip(to_trip_json(p, data), data, EDITED) == []
    items = to_trip_json(p, data)["items"]
    assert r.new_total == p.total == sum(i["price_inr"] for i in items)
    assert r.price_difference == r.new_total - r.old_total
    assert r.budget_difference == p.budget - p.total
    return p


def assert_refused(r, *expected_rules):
    assert not r.valid and r.proposed_package is None and r.new_total is None
    assert r.violations and all(
        v.item_id for v in r.violations
    )  # every reason names a package item
    for rule in expected_rules:
        assert rule in rules(r), [(v.rule, v.message) for v in r.violations]


def changed(old, new) -> set[str]:
    """Package item ids whose content differs between two packages."""
    out = set()
    if old.arrival_flight != new.arrival_flight:
        out.add("flight:arrival")
    if old.return_flight != new.return_flight:
        out.add("flight:return")
    out |= {a.stay_id for a, b in zip(old.hotels, new.hotels, strict=True) if a != b}
    olegs = {t.leg_id: t for t in (old.arrival_transfer, *old.intercity, old.departure_transfer)}
    nlegs = {t.leg_id: t for t in (new.arrival_transfer, *new.intercity, new.departure_transfer)}
    out |= {k for k in olegs if olegs[k] != nlegs.get(k)}
    ov, nv = {v.attraction_id: v for v in old.visits}, {v.attraction_id: v for v in new.visits}
    out |= {f"visit:{a}" for a in ov.keys() | nv.keys() if ov.get(a) != nv.get(a)}
    return out


# ------------------------------------------------------------------ command contract


@pytest.mark.parametrize(
    "body",
    [
        {"base_version": 1, "kind": "CHANGE_EVERYTHING"},  # unknown kind
        {"base_version": 1, "flight_id": "F-IN-1"},  # no kind
        {
            "base_version": 1,
            "kind": "CHANGE_HOTEL",
            "stay_id": STAY_X,
            "hotel_id": "HX-B",
        },  # no room id
        {"base_version": 1, "kind": "REMOVE_ATTRACTION", "item_id": "   "},  # blank id
        {
            "base_version": 1,
            "kind": "ADD_ATTRACTION",
            "date": "2027-02-30",
            "attraction_id": "ATT-X-3",
        },
        {
            "base_version": 1,
            "kind": "ADD_ATTRACTION",
            "date": "12/04/2027",
            "attraction_id": "ATT-X-3",
        },
        {
            "base_version": 1,
            "kind": "ADD_ATTRACTION",
            "date": "2027-04-12",
            "attraction_id": "ATT-X-3",
            "preferred_start": "25:00",
        },
        {
            "base_version": 1,
            "kind": "CHANGE_ARRIVAL_FLIGHT",
            "flight_id": "F-IN-1",
            "price_inr": 1,
        },  # client price
        {
            "base_version": 1,
            "kind": "CHANGE_HOTEL",
            "stay_id": STAY_X,
            "hotel_id": "HX-B",
            "room_id": "RX-B",
            "rooms_left": 9,
        },  # availability claim
        {
            "base_version": "1",
            "kind": "CHANGE_ARRIVAL_FLIGHT",
            "flight_id": "F-IN-1",
        },  # version as text
        {"base_version": 0, "kind": "CHANGE_ARRIVAL_FLIGHT", "flight_id": "F-IN-1"},
        {"kind": "CHANGE_ARRIVAL_FLIGHT", "flight_id": "F-IN-1"},  # no base_version
        ["CHANGE_ARRIVAL_FLIGHT"],
        None,
        "CHANGE_HOTEL",
    ],
)
def test_malformed_commands_are_refused_before_anything_runs(body):
    with pytest.raises(ValidationError):
        CHANGE_COMMAND.validate_python(body)


def test_unknown_or_unchanged_targets_are_explained(env):
    assert_refused(
        propose(
            env,
            kind="CHANGE_HOTEL",
            stay_id="stay:Q:2027-04-10:2027-04-13",
            hotel_id="HX-B",
            room_id="RX-B",
        ),
        CHANGE_TARGET_NOT_FOUND,
    )
    assert_refused(
        propose(env, kind="CHANGE_AIRPORT_TRANSFER", item_id=LEG_XY, transfer_id="T-AX-ANY"),
        CHANGE_TARGET_NOT_FOUND,
    )
    assert_refused(
        propose(env, kind="REMOVE_ATTRACTION", item_id="visit:ATT-X-4"), CHANGE_TARGET_NOT_FOUND
    )
    assert_refused(
        propose(env, kind="CHANGE_HOTEL", stay_id=STAY_X, hotel_id="HX-A", room_id="RX-A"),
        NO_CHANGE,
    )
    assert_refused(propose(env, kind="CHANGE_ARRIVAL_FLIGHT", flight_id="F-IN-1"), NO_CHANGE)


# ------------------------------------------------------------------ hotel changes (1-4)


def test_01_valid_replacement_hotel_in_the_same_city(env):
    p = assert_valid(
        propose(env, kind="CHANGE_HOTEL", stay_id=STAY_X, hotel_id="HX-B", room_id="RX-B"), env.data
    )
    h = p.hotels[0]
    assert (h.stay_id, h.hotel_id, h.room_id, h.city) == (STAY_X, "HX-B", "RX-B", "X")
    assert (h.check_in, h.check_out) == (D10, D13)  # stay dates never change
    assert h.total_price == 600 * 3 * 1  # catalog price x nights x rooms
    assert p.hotels[1] == env.pkg.hotels[1]  # the other city is untouched
    assert p.plan == env.pkg.plan


def test_02_room_type_that_needs_a_different_room_count(env):
    r = propose(env, kind="CHANGE_HOTEL", stay_id=STAY_X, hotel_id="HX-A", room_id="RX-A-SINGLE")
    h = assert_valid(r, env.data).hotels[0]
    assert (h.room_id, h.rooms) == ("RX-A-SINGLE", 2)  # 1 adult per room -> 2 rooms
    assert h.total_price == 450 * 3 * 2
    assert r.price_difference == 450 * 3 * 2 - 500 * 3


def test_03_hotel_unavailable_on_one_night(env):
    r = propose(env, kind="CHANGE_HOTEL", stay_id=STAY_X, hotel_id="HX-SOLD", room_id="RX-SOLD")
    assert_refused(r, "R-HTL-6")
    assert any("2027-04-11" in v.message for v in r.violations)


def test_04_hotel_with_insufficient_room_capacity(env):
    assert_refused(
        propose(env, kind="CHANGE_HOTEL", stay_id=STAY_X, hotel_id="HX-TINY", room_id="RX-TINY"),
        "R-HTL-5",
    )


def test_hotel_in_another_city_or_room_of_another_hotel_is_refused(env):
    assert not propose(
        env, kind="CHANGE_HOTEL", stay_id=STAY_X, hotel_id="HY-B", room_id="RY-B"
    ).valid
    assert not propose(
        env, kind="CHANGE_HOTEL", stay_id=STAY_X, hotel_id="HX-B", room_id="RX-A"
    ).valid
    assert not propose(
        env, kind="CHANGE_HOTEL", stay_id=STAY_X, hotel_id="HX-NOPE", room_id="RX-B"
    ).valid


# ------------------------------------------------------------------ flight changes (9-12)


def test_09_valid_arrival_flight_change(env):
    r = propose(env, kind="CHANGE_ARRIVAL_FLIGHT", flight_id="F-IN-LATE")
    p = assert_valid(r, env.data)
    assert p.arrival_flight.flight_id == "F-IN-LATE" and p.arrival_flight.price == 1500 * 3
    assert changed(env.pkg, p) == {"flight:arrival", "leg:arrival"}  # nothing else moves
    assert p.return_flight == env.pkg.return_flight and p.hotels == env.pkg.hotels


def test_10_valid_return_flight_change(env):
    p = assert_valid(propose(env, kind="CHANGE_RETURN_FLIGHT", flight_id="F-OUT-MID"), env.data)
    assert p.return_flight.flight_id == "F-OUT-MID"
    assert changed(env.pkg, p) == {"flight:return", "leg:departure"}


def test_11_flight_with_too_few_seats(env):
    r = propose(env, kind="CHANGE_ARRIVAL_FLIGHT", flight_id="F-IN-FULL")
    assert_refused(r, "R-FLT-3")
    assert r.violations[0].item_id == "flight:arrival"


def test_12_arrival_flight_on_another_date(env):
    assert_refused(propose(env, kind="CHANGE_ARRIVAL_FLIGHT", flight_id="F-IN-WRONGDAY"), "R-FLT-4")
    # an inbound flight offered as the return flight is refused too
    assert not propose(env, kind="CHANGE_RETURN_FLIGHT", flight_id="F-IN-LATE").valid


# ------------------------------------------------------------------ transfer changes (17-21)


def test_17_valid_airport_transfer_replacement(env):
    r = propose(env, kind="CHANGE_AIRPORT_TRANSFER", item_id="leg:arrival", transfer_id="T-AX-ANY")
    p = assert_valid(r, env.data)
    t = p.arrival_transfer
    assert (t.leg_id, t.transfer_id, t.price) == ("leg:arrival", "T-AX-ANY", 180)  # 1 vehicle for 3
    assert t.pickup >= env.pkg.arrival_flight.arrival  # a computed valid pickup
    assert changed(env.pkg, p) == {"leg:arrival"}


def test_18_airport_transfer_at_the_wrong_airport_or_for_another_area(env):
    assert_refused(
        propose(env, kind="CHANGE_AIRPORT_TRANSFER", item_id="leg:arrival", transfer_id="T-AX2-A"),
        "R-ATR-3",
    )
    assert_refused(
        propose(env, kind="CHANGE_AIRPORT_TRANSFER", item_id="leg:arrival", transfer_id="T-AX-B"),
        "R-ATR-4",
    )
    assert_refused(
        propose(env, kind="CHANGE_AIRPORT_TRANSFER", item_id="leg:arrival", transfer_id="TR-XY-2"),
        "R-ATR-2",
    )  # a train is not an airport transfer


def test_19_airport_transfer_outside_its_service_window(env):
    assert_refused(
        propose(
            env, kind="CHANGE_AIRPORT_TRANSFER", item_id="leg:departure", transfer_id="T-AY-A-EVE"
        ),
        "R-ATR-6",
    )


def test_20_valid_intercity_transfer_replacement(env):
    r = propose(env, kind="CHANGE_INTERCITY_TRANSFER", item_id=LEG_XY, transfer_id="TR-XY-2")
    p = assert_valid(r, env.data)
    assert p.intercity[0].transfer_id == "TR-XY-2" and p.intercity[0].leg_id == LEG_XY
    assert r.price_difference == (260 - 200) * 3
    assert changed(env.pkg, p) == {LEG_XY}


def test_21_intercity_departure_off_its_frequency_slots(env):
    assert_refused(
        propose(
            env,
            kind="CHANGE_INTERCITY_TRANSFER",
            item_id=LEG_XY,
            transfer_id="TR-XY-FREQ",
            pickup="11:00",
        ),
        "R-ICT-6",
    )
    p = assert_valid(
        propose(
            env,
            kind="CHANGE_INTERCITY_TRANSFER",
            item_id=LEG_XY,
            transfer_id="TR-XY-FREQ",
            pickup="12:00",
        ),
        env.data,
    )  # a real slot (every 120 min)
    assert p.intercity[0].pickup.strftime("%H:%M") == "12:00"


# ------------------------------------------------------------------ attraction changes (23-29)


def test_23_add_a_valid_attraction(env):
    r = propose(
        env,
        kind="ADD_ATTRACTION",
        date="2027-04-12",
        attraction_id="ATT-X-3",
        preferred_start="14:00",
    )
    p = assert_valid(r, env.data)
    new = next(v for v in p.visits if v.attraction_id == "ATT-X-3")
    assert new.start.strftime("%Y-%m-%d %H:%M") == "2027-04-12 14:00" and new.price == 140 * 3
    assert [(c.component, c.source, c.action) for c in r.changed_items] == [
        ("visit:ATT-X-3", USER_CHOICE, "ADDED")
    ]
    assert changed(env.pkg, p) == {"visit:ATT-X-3"} and r.price_difference == 420


def test_24_add_an_attraction_on_its_closed_date(env):
    r = propose(env, kind="ADD_ATTRACTION", date="2027-04-11", attraction_id="ATT-X-CLOSED")
    assert_refused(r, "R-ATT-3")
    assert "closed" in r.violations[0].message
    assert_valid(
        propose(env, kind="ADD_ATTRACTION", date="2027-04-12", attraction_id="ATT-X-CLOSED"),
        env.data,
    )


def test_25_add_an_attraction_that_would_overlap(env):
    # no free interval of 9 hours on 11 Apr without moving ATT-X-1: refused with the conflict named
    r = propose(env, kind="ADD_ATTRACTION", date="2027-04-11", attraction_id="ATT-X-LONG")
    assert_refused(r, "R-ATT-8")
    assert "ATT-X-1 10:00–11:00" in r.violations[0].message
    # a preferred time that overlaps: the new visit moves to free time, the planned one never moves
    r = propose(
        env,
        kind="ADD_ATTRACTION",
        date="2027-04-11",
        attraction_id="ATT-X-3",
        preferred_start="10:30",
    )
    p = assert_valid(r, env.data)
    assert changed(env.pkg, p) == {"visit:ATT-X-3"}
    new = next(v for v in p.visits if v.attraction_id == "ATT-X-3")
    assert new.start.strftime("%H:%M") == "11:00"
    assert any("10:30" in w and "11:00" in w for w in r.warnings)


def test_26_a_duplicate_attraction_is_refused(env):
    r = propose(env, kind="ADD_ATTRACTION", date="2027-04-12", attraction_id="ATT-X-1")
    assert_refused(r, "R-ATT-7")
    assert r.violations[0].item_id == "visit:ATT-X-1"


def test_27_remove_an_existing_attraction(env):
    r = propose(env, kind="REMOVE_ATTRACTION", item_id="visit:ATT-Y-1")
    p = assert_valid(r, env.data)
    assert "ATT-Y-1" not in {v.attraction_id for v in p.visits}
    assert changed(env.pkg, p) == {"visit:ATT-Y-1"}  # removal only: nothing re-inserted
    assert r.price_difference == -300


def test_28_removing_the_only_attraction_of_a_full_day_is_allowed_when_edited(env):
    r = propose(env, kind="REMOVE_ATTRACTION", item_id="visit:ATT-X-1")
    p = assert_valid(r, env.data)  # EDITED: no per-day count
    assert not [v for v in p.visits if v.start.date() == D11]
    assert any("no attraction planned" in w for w in r.warnings)
    initial = validate_trip(to_trip_json(p, env.data), env.data, INITIAL)
    assert {v.rule for v in initial} == {"R-ATT-12"}  # only the initial-population rule differs


def test_29_no_attraction_on_the_departure_day(env):
    r = propose(env, kind="ADD_ATTRACTION", date="2027-04-16", attraction_id="ATT-Y-3")
    assert_refused(r, "R-ATT-11")
    assert rules(r) == ["R-ATT-11", "R-ATT-11"]  # headline + the rule's own finding


def test_attraction_in_another_city_or_outside_the_trip_is_refused(env):
    assert_refused(
        propose(env, kind="ADD_ATTRACTION", date="2027-04-11", attraction_id="ATT-Y-3"), "R-ATT-2"
    )
    assert_refused(
        propose(env, kind="ADD_ATTRACTION", date="2027-04-20", attraction_id="ATT-Y-3"), "R-ATT-2"
    )
    assert_refused(
        propose(env, kind="ADD_ATTRACTION", date="2027-04-11", attraction_id="ATT-NOPE"), "R-ATT-1"
    )


def test_attraction_on_arrival_and_change_days_starts_after_reaching_the_city(env):
    r = propose(
        env,
        kind="ADD_ATTRACTION",
        date="2027-04-10",
        attraction_id="ATT-X-3",
        preferred_start="08:00",
    )
    new = next(v for v in assert_valid(r, env.data).visits if v.attraction_id == "ATT-X-3")
    assert new.start >= env.pkg.arrival_transfer.arrive
    r = propose(
        env,
        kind="ADD_ATTRACTION",
        date="2027-04-13",
        attraction_id="ATT-Y-3",
        preferred_start="09:00",
    )
    new = next(v for v in assert_valid(r, env.data).visits if v.attraction_id == "ATT-Y-3")
    assert new.start >= env.pkg.intercity[0].arrive and new.start.date() == D13


# ------------------------------------------------------------------ purity and determinism


COMMANDS = [
    dict(kind="CHANGE_HOTEL", stay_id=STAY_X, hotel_id="HX-B", room_id="RX-B"),
    dict(kind="CHANGE_HOTEL", stay_id=STAY_X, hotel_id="HX-SOLD", room_id="RX-SOLD"),
    dict(kind="CHANGE_ARRIVAL_FLIGHT", flight_id="F-IN-LATE"),
    dict(kind="CHANGE_RETURN_FLIGHT", flight_id="F-OUT-EARLY"),
    dict(kind="CHANGE_AIRPORT_TRANSFER", item_id="leg:arrival", transfer_id="T-AX-ANY"),
    dict(kind="CHANGE_INTERCITY_TRANSFER", item_id=LEG_XY, transfer_id="TR-XY-SLOW"),
    dict(kind="ADD_ATTRACTION", date="2027-04-12", attraction_id="ATT-X-3"),
    dict(kind="REMOVE_ATTRACTION", item_id="visit:ATT-X-2"),
]


def test_propose_change_never_mutates_the_package_or_the_catalog_and_is_deterministic(env):
    pkg_before, catalog_before = copy.deepcopy(env.pkg), copy.deepcopy(env.data.catalog)
    first = [propose(env, **c) for c in COMMANDS]
    second = [propose(env, **c) for c in COMMANDS]
    assert env.pkg == pkg_before
    assert env.data.catalog == catalog_before
    assert first == second
    assert [r.valid for r in first] == [True, False, True, False, True, True, True, True]
    assert D12 and D13  # dates used above are the X full day and the change day
