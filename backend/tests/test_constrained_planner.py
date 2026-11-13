"""Table-driven tests of the in-memory edit/repair core (app/engine/repair.py).

Synthetic world: home HOM, country ZZ, cities X and Y linked X -> Y (and Y -> X, used only as a
wrong-direction lock). Every trip is 6 nights with at least 3 nights per city, so the city plan is
forced to X (2027-04-10..13) then Y (2027-04-13..16). Airport transfers carry an area, so a hotel in
another area forces an airport transfer change. Arrival flights only land in X, return flights only
leave Y, so the planner has exactly one city plan.

Run from backend/: ../.venv/bin/python -m pytest -q tests/test_constrained_planner.py
"""
import copy
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.catalog.load import load_catalog
from app.engine.build import FOUND, MINIMUM_COST, build_package
from app.engine.constraints import (LOCKED_CHOICE_INCOMPATIBLE, HotelLock, PlanningConstraints,
                                    RequiredAttraction, TransferLock)
from app.engine.model import ARRIVAL_LEG, DEPARTURE_LEG, intercity_leg_id
from app.engine.repair import AUTOMATIC_REPAIR, USER_CHOICE, ChangeProposal, propose_repair
from app.export.to_trip import to_trip_json
from app.rules.common import EDITED
from app.validate.validate_trip import validate_trip
from synth import World, request

D10, D11, D12, D13 = date(2027, 4, 10), date(2027, 4, 11), date(2027, 4, 12), date(2027, 4, 13)
D16 = date(2027, 4, 16)
MENON = SimpleNamespace(departure_airport="BLR", destination_country="JP", start_date=date(2027, 4, 10),
                        nights=6, adults=2, children_ages=[6], budget=350000)


def two_city_world():
    w = World(cities=("X", "Y"), links=(("X", "Y"), ("Y", "X")), per_city=3)
    w.airports.append({"code": "AX2", "name": "X Airport 2", "city": "X", "country": "ZZ",
                       "timezone": "Asia/Tokyo", "lat": 0, "lng": 0, "serves_cities": ["X"]})
    # inbound, all landing 2027-04-10 in X ("F-IN-FULL" has one seat for a party of two)
    w.flight("F-IN-1", "HOM", "AX", "2027-04-09T22:00:00", "2027-04-10T08:00:00", 1000)
    w.flight("F-IN-LATE", "HOM", "AX", "2027-04-09T23:00:00", "2027-04-10T10:00:00", 1500)
    w.flight("F-IN-FULL", "HOM", "AX", "2027-04-09T22:00:00", "2027-04-10T08:00:00", 900, seats=1)
    w.flight("F-IN-AX2", "HOM", "AX2", "2027-04-09T22:00:00", "2027-04-10T08:00:00", 1100)
    # outbound, all leaving 2027-04-16 from Y
    w.flight("F-OUT-LATE", "AY", "HOM", "2027-04-16T18:00:00", "2027-04-16T23:00:00", 1000)
    w.flight("F-OUT-MID", "AY", "HOM", "2027-04-16T15:00:00", "2027-04-16T20:00:00", 1100)
    w.flight("F-OUT-EARLY", "AY", "HOM", "2027-04-16T11:00:00", "2027-04-16T16:00:00", 1200)
    # hotels: area A is the cheaper one in each city
    w.hotel("HX-A", "X", area="A")
    w.room("RX-A", "HX-A", 500)
    w.hotel("HX-B", "X", area="B")
    w.room("RX-B", "HX-B", 600)
    w.hotel("HY-A", "Y", area="A")
    w.room("RY-A", "HY-A", 500)
    w.hotel("HY-B", "Y", area="B")
    w.room("RY-B", "HY-B", 600)
    # airport transfers: area specific; the Y departure window never reaches midnight
    w.airport_transfer("T-AX-A", "AX", "X", 100, area="A")
    w.airport_transfer("T-AX-B", "AX", "X", 150, area="B")
    w.airport_transfer("T-AX2-A", "AX2", "X", 110, area="A")
    w.airport_transfer("T-AX2-B", "AX2", "X", 120, area="B")
    w.airport_transfer("T-AY-A", "AY", "Y", 100, area="A", window=("10:00", "22:00"))
    w.airport_transfer("T-AY-B", "AY", "Y", 150, area="B", window=("10:00", "22:00"))
    # city-to-city services X -> Y (plus one Y -> X service)
    w.intercity("TR-XY-1", "X", "Y", 200)
    w.intercity("TR-XY-2", "X", "Y", 260)
    w.intercity("TR-XY-FREQ", "X", "Y", 300, frequency=120)      # departures every 2 h from 00:00
    w.intercity("TR-YX-1", "Y", "X", 200)
    # attractions: four per city, plus one closed on 2027-04-11
    for i, price in enumerate([100, 120, 140, 160], 1):
        w.attraction(f"ATT-X-{i}", "X", price)
        w.attraction(f"ATT-Y-{i}", "Y", price)
    w.attraction("ATT-X-CLOSED", "X", 500, closed_dates=["2027-04-11"])
    return w


def start(w, budget=10 ** 9):
    data = w.loaded()
    res = build_package(request(nights=6, budget=budget), data, MINIMUM_COST)
    assert res.status == FOUND, res.reasons
    return res.package, data


@pytest.fixture
def base():
    w = two_city_world()
    pkg, data = start(w)
    assert [h.area for h in pkg.hotels] == ["A", "A"]
    return SimpleNamespace(world=w, pkg=pkg, data=data)


def repair(pkg, data, con):
    return propose_repair(pkg, con, data)


def assert_valid(p, data):
    assert p.valid, [(v.rule, v.message) for v in p.violations]
    new = p.proposed_package
    assert validate_trip(to_trip_json(new, data), data, EDITED) == []
    assert p.new_total == new.total
    assert p.price_difference == p.new_total - p.old_total
    assert p.budget_difference == new.budget - p.new_total


def rules_of(p):
    return {v.rule for v in p.violations}


def visit_keys(pkg):
    return sorted((v.attraction_id, v.start, v.end) for v in pkg.visits)


def visits_on(pkg, day):
    return sorted((v for v in pkg.visits if v.start.date() == day), key=lambda v: v.start)


def ids(pkg):
    return {v.attraction_id for v in pkg.visits}


def no_overlap(pkg):
    vs = sorted(pkg.visits, key=lambda v: v.start)
    return all(a.end <= b.start for a, b in zip(vs, vs[1:]))


# ------------------------------------------------------------------ hotels

def test_locking_the_current_hotel_is_a_no_op(base):
    pkg = base.pkg
    h, s0 = pkg.hotels[0], pkg.plan.stays[0].stay_id
    p = repair(pkg, base.data, PlanningConstraints(locked_hotels={s0: HotelLock(h.hotel_id, h.room_id)}))
    assert_valid(p, base.data)
    assert p.changed_items == []
    assert p.proposed_package == pkg


@pytest.mark.parametrize("stay_index, hotel, room, new_transfer", [
    (0, "HX-B", "RX-B", "T-AX-B"),      # first hotel -> arrival transfer repaired
    (1, "HY-B", "RY-B", "T-AY-B"),      # last hotel -> departure transfer repaired
])
def test_hotel_in_another_area_repairs_only_its_airport_transfer(base, stay_index, hotel, room, new_transfer):
    pkg = base.pkg
    first = stay_index == 0
    repaired_attr = "arrival_transfer" if first else "departure_transfer"
    untouched_attr = "departure_transfer" if first else "arrival_transfer"
    repaired_leg = ARRIVAL_LEG if first else DEPARTURE_LEG
    stay = pkg.plan.stays[stay_index].stay_id
    con = PlanningConstraints(locked_hotels={stay: HotelLock(hotel, room)})
    p = repair(pkg, base.data, con)
    assert_valid(p, base.data)
    new = p.proposed_package
    assert (new.hotels[stay_index].hotel_id, new.hotels[stay_index].room_id) == (hotel, room)
    assert new.hotels[1 - stay_index] == pkg.hotels[1 - stay_index]
    assert getattr(new, repaired_attr).transfer_id == new_transfer
    assert getattr(new, untouched_attr) == getattr(pkg, untouched_attr)
    assert new.arrival_flight == pkg.arrival_flight and new.return_flight == pkg.return_flight
    assert new.plan == pkg.plan
    assert new.intercity == pkg.intercity
    assert visit_keys(new) == visit_keys(pkg)
    assert {c.component: c.source for c in p.changed_items} == {stay: USER_CHOICE, repaired_leg: AUTOMATIC_REPAIR}


def test_locked_hotel_with_no_rooms_on_one_night_is_rejected(base):
    base.world.set_rooms_left("RX-B", "2027-04-12", 0)
    data = base.world.loaded()
    s0 = base.pkg.plan.stays[0].stay_id
    p = repair(base.pkg, data, PlanningConstraints(locked_hotels={s0: HotelLock("HX-B", "RX-B")}))
    assert not p.valid
    assert p.proposed_package is None
    assert {LOCKED_CHOICE_INCOMPATIBLE, "R-HTL-6"} <= rules_of(p)


# ------------------------------------------------------------------ flights and airport transfers

def test_later_arrival_flight_moves_the_airport_pickup(base):
    pkg = base.pkg
    p = repair(pkg, base.data, PlanningConstraints(arrival_flight_id="F-IN-LATE"))
    assert_valid(p, base.data)
    new = p.proposed_package
    assert new.arrival_transfer.transfer_id == pkg.arrival_transfer.transfer_id
    assert new.arrival_transfer.pickup > pkg.arrival_transfer.pickup
    assert new.arrival_transfer.pickup >= new.arrival_flight.arrival + timedelta(minutes=60)
    assert {c.component for c in p.changed_items} == {"flight:arrival", ARRIVAL_LEG}
    assert new.hotels == pkg.hotels and new.departure_transfer == pkg.departure_transfer


def test_arrival_flight_to_another_airport_replaces_the_airport_transfer(base):
    pkg, data = base.pkg, base.data
    p = repair(pkg, data, PlanningConstraints(arrival_flight_id="F-IN-AX2"))
    assert_valid(p, data)
    new = p.proposed_package
    assert new.arrival_flight.to_airport == "AX2"
    assert new.arrival_transfer.transfer_id == "T-AX2-A"          # first hotel is still in area A
    assert data.indexes.transfers_by_id[new.arrival_transfer.transfer_id]["airport"] == "AX2"
    assert {c.component for c in p.changed_items} == {"flight:arrival", ARRIVAL_LEG}


def test_arrival_flight_without_enough_seats_is_rejected(base):
    p = repair(base.pkg, base.data, PlanningConstraints(arrival_flight_id="F-IN-FULL"))
    assert not p.valid
    assert p.proposed_package is None
    assert {LOCKED_CHOICE_INCOMPATIBLE, "R-FLT-3"} <= rules_of(p)


def test_earlier_return_flight_moves_the_departure_pickup(base):
    pkg, data = base.pkg, base.data
    p = repair(pkg, data, PlanningConstraints(return_flight_id="F-OUT-MID"))
    assert_valid(p, data)
    new = p.proposed_package
    dep = new.departure_transfer
    assert dep.transfer_id == pkg.departure_transfer.transfer_id
    assert dep.pickup < pkg.departure_transfer.pickup
    assert dep.pickup.date() == D16
    assert dep.arrive <= new.return_flight.departure - timedelta(minutes=180)
    assert {c.component for c in p.changed_items} == {"flight:return", DEPARTURE_LEG}


def test_return_flight_too_early_for_the_buffer_is_rejected(base):
    p = repair(base.pkg, base.data, PlanningConstraints(return_flight_id="F-OUT-EARLY"))
    assert not p.valid
    assert p.proposed_package is None
    assert p.violations
    assert "NO_DEPARTURE_TRANSFER" in rules_of(p)


# ------------------------------------------------------------------ attractions

def test_added_attraction_with_flexible_time_leaves_other_visits_alone(base):
    pkg, data = base.pkg, base.data
    assert "ATT-X-3" not in ids(pkg)
    p = repair(pkg, data, PlanningConstraints(required_attractions=[RequiredAttraction("ATT-X-3", D11)]))
    assert_valid(p, data)
    new = p.proposed_package
    added = [v for v in new.visits if v.attraction_id == "ATT-X-3"]
    assert len(added) == 1 and added[0].start.date() == D11
    assert set(visit_keys(pkg)) <= set(visit_keys(new))
    assert no_overlap(new)
    assert {c.component for c in p.changed_items} == {"visit:ATT-X-3"}


def test_pinned_attraction_over_an_existing_visit_never_overlaps(base):
    pkg, data = base.pkg, base.data
    v = visits_on(pkg, D11)[0]
    p = repair(pkg, data, PlanningConstraints(
        required_attractions=[RequiredAttraction("ATT-X-3", D11, start=v.start)]))
    if p.valid:
        assert_valid(p, data)
        new = p.proposed_package
        assert no_overlap(new)
        added = [x for x in new.visits if x.attraction_id == "ATT-X-3"]
        assert len(added) == 1 and added[0].start == v.start
        assert any(c.source == AUTOMATIC_REPAIR for c in p.changed_items)
    else:
        assert p.proposed_package is None
        assert p.violations


def test_attraction_in_the_wrong_city_is_rejected(base):
    p = repair(base.pkg, base.data, PlanningConstraints(required_attractions=[RequiredAttraction("ATT-Y-1", D11)]))
    assert not p.valid
    assert p.proposed_package is None
    assert "R-ATT-2" in rules_of(p)


def test_attraction_on_a_closed_day_is_rejected(base):
    p = repair(base.pkg, base.data,
               PlanningConstraints(required_attractions=[RequiredAttraction("ATT-X-CLOSED", D11)]))
    assert not p.valid
    assert p.proposed_package is None
    assert "R-ATT-3" in rules_of(p)


def test_attraction_moved_to_another_day_is_listed_once(base):
    pkg, data = base.pkg, base.data
    v = visits_on(pkg, D11)[0]
    p = repair(pkg, data, PlanningConstraints(required_attractions=[RequiredAttraction(v.attraction_id, D12)]))
    assert_valid(p, data)
    new = p.proposed_package
    moved = [x for x in new.visits if x.attraction_id == v.attraction_id]
    assert len(moved) == 1 and moved[0].start.date() == D12
    assert no_overlap(new)


def test_removed_attraction_is_gone_and_the_total_drops_by_its_price(base):
    pkg, data = base.pkg, base.data
    v = visits_on(pkg, D11)[0]
    p = repair(pkg, data, PlanningConstraints(excluded_attraction_ids={v.attraction_id}))
    assert_valid(p, data)
    new = p.proposed_package
    assert v.attraction_id not in ids(new)
    assert visits_on(new, D11) == []                 # the full day is now empty, which EDITED allows
    assert new.total == pkg.total - v.price
    assert p.price_difference == -v.price
    assert [(c.component, c.source, c.action) for c in p.changed_items] == \
        [(f"visit:{v.attraction_id}", USER_CHOICE, "REMOVED")]


# ------------------------------------------------------------------ intercity transfers

def test_locked_intercity_service_is_used(base):
    pkg, data = base.pkg, base.data
    leg = intercity_leg_id(*pkg.plan.legs()[0])
    assert pkg.intercity[0].transfer_id == "TR-XY-1"
    p = repair(pkg, data, PlanningConstraints(locked_transfers={leg: TransferLock("TR-XY-2")}))
    assert_valid(p, data)
    assert p.proposed_package.intercity[0].transfer_id == "TR-XY-2"
    assert [(c.component, c.source) for c in p.changed_items] == [(leg, USER_CHOICE)]


def test_locked_intercity_pickup_off_frequency_is_rejected(base):
    pkg = base.pkg
    leg = intercity_leg_id(*pkg.plan.legs()[0])
    lock = TransferLock("TR-XY-FREQ", datetime(2027, 4, 13, 10, 30))      # 10:30 is not on a 2-hour slot
    p = repair(pkg, base.data, PlanningConstraints(locked_transfers={leg: lock}))
    assert not p.valid
    assert p.proposed_package is None
    assert LOCKED_CHOICE_INCOMPATIBLE in rules_of(p)


def test_locked_intercity_service_in_the_wrong_direction_is_rejected(base):
    leg = intercity_leg_id(*base.pkg.plan.legs()[0])
    p = repair(base.pkg, base.data, PlanningConstraints(locked_transfers={leg: TransferLock("TR-YX-1")}))
    assert not p.valid
    assert p.proposed_package is None
    assert LOCKED_CHOICE_INCOMPATIBLE in rules_of(p)


# ------------------------------------------------------------------ budget, multi-city, failure, combined

def test_over_budget_edit_is_valid_with_a_budget_warning():
    w = two_city_world()
    total = start(w)[0].total
    pkg, data = start(w, budget=total + 50)
    s0 = pkg.plan.stays[0].stay_id
    p = repair(pkg, data, PlanningConstraints(locked_hotels={s0: HotelLock("HX-B", "RX-B")}))
    assert_valid(p, data)
    assert p.budget_difference < 0
    assert p.price_difference > 0
    assert any("budget" in msg.lower() for msg in p.warnings)


@pytest.mark.parametrize("edit", ["first_hotel", "last_hotel", "arrival_flight"])
def test_single_edit_leaves_other_stay_and_intercity_identical(base, edit):
    pkg, data = base.pkg, base.data
    s0, s1 = pkg.plan.stays[0].stay_id, pkg.plan.stays[1].stay_id
    con = {
        "first_hotel": PlanningConstraints(locked_hotels={s0: HotelLock("HX-B", "RX-B")}),
        "last_hotel": PlanningConstraints(locked_hotels={s1: HotelLock("HY-B", "RY-B")}),
        "arrival_flight": PlanningConstraints(arrival_flight_id="F-IN-LATE"),
    }[edit]
    p = repair(pkg, data, con)
    assert_valid(p, data)
    new = p.proposed_package
    assert new.plan == pkg.plan
    assert new.intercity == pkg.intercity
    if edit == "first_hotel":
        assert new.hotels[1] == pkg.hotels[1]
    elif edit == "last_hotel":
        assert new.hotels[0] == pkg.hotels[0]
    else:
        assert new.hotels == pkg.hotels


@pytest.mark.parametrize("edit", ["no_rooms_on_a_night", "return_flight_too_early"])
def test_failed_proposal_leaves_package_and_catalog_untouched(base, edit):
    w = base.world
    s0 = base.pkg.plan.stays[0].stay_id
    if edit == "no_rooms_on_a_night":
        w.set_rooms_left("RX-B", "2027-04-12", 0)
        con = PlanningConstraints(locked_hotels={s0: HotelLock("HX-B", "RX-B")})
    else:
        con = PlanningConstraints(return_flight_id="F-OUT-EARLY")
    data = w.loaded()
    pkg_before, raw_before = copy.deepcopy(base.pkg), copy.deepcopy(w.raw())
    p = repair(base.pkg, data, con)
    assert not p.valid and p.proposed_package is None
    assert base.pkg == pkg_before
    assert w.raw() == raw_before


def test_combined_arrival_flight_and_first_hotel_lock_are_both_applied(base):
    pkg, data = base.pkg, base.data
    s0 = pkg.plan.stays[0].stay_id
    con = PlanningConstraints(arrival_flight_id="F-IN-AX2", locked_hotels={s0: HotelLock("HX-B", "RX-B")})
    p = repair(pkg, data, con)
    assert_valid(p, data)
    new = p.proposed_package
    assert new.arrival_flight.flight_id == "F-IN-AX2"
    assert (new.hotels[0].hotel_id, new.hotels[0].room_id) == ("HX-B", "RX-B")
    rec = data.indexes.transfers_by_id[new.arrival_transfer.transfer_id]
    assert rec["airport"] == "AX2"
    assert rec["area"] == data.indexes.hotels_by_id["HX-B"]["area"] == "B"
    assert new.arrival_transfer.transfer_id == "T-AX2-B"


def test_build_package_with_existing_package_returns_the_proposal(base):
    s0 = base.pkg.plan.stays[0].stay_id
    con = PlanningConstraints(locked_hotels={s0: HotelLock("HX-B", "RX-B")})
    res = build_package(request(nights=6), base.data, MINIMUM_COST, constraints=con,
                        existing_package=base.pkg)
    assert isinstance(res.proposal, ChangeProposal)
    assert res.proposal.valid
    assert res.package == res.proposal.proposed_package
    assert res.status == FOUND


# ------------------------------------------------------------------ real catalog (Menon request)

@pytest.fixture(scope="module")
def menon():
    data = load_catalog()
    res = build_package(MENON, data, MINIMUM_COST)
    assert res.status == FOUND, res.reasons
    return res.package, data


def test_menon_locking_the_current_hotel_is_a_no_op(menon):
    pkg, data = menon
    h, s0 = pkg.hotels[0], pkg.plan.stays[0].stay_id
    p = repair(pkg, data, PlanningConstraints(locked_hotels={s0: HotelLock(h.hotel_id, h.room_id)}))
    assert_valid(p, data)
    assert p.changed_items == []
    assert p.proposed_package == pkg


def test_menon_removing_a_visit_drops_its_price(menon):
    pkg, data = menon
    assert pkg.visits
    v = pkg.visits[0]
    p = repair(pkg, data, PlanningConstraints(excluded_attraction_ids={v.attraction_id}))
    assert_valid(p, data)
    assert v.attraction_id not in ids(p.proposed_package)
    assert p.proposed_package.total == pkg.total - v.price
