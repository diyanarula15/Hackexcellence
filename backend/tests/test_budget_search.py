"""Search-completeness and minimum-cost-proof tests for the holiday planner.

Every positive case compares the planner's MINIMUM_COST total with the independent brute-force
oracle in synth.py. Worlds are tiny and hand-built, so the oracle stays fast. Nothing is random.
"""
import copy
from datetime import date, timedelta

import pytest

from app.engine.build import FOUND, INFEASIBLE, MINIMUM_COST, OVER_BUDGET, WITHIN_BUDGET, build_package
from synth import ALL_DAYS, World, oracle_minimum, request

START = date(2027, 4, 10)          # a Saturday; the arrival date
FULL_DAY_1 = date(2027, 4, 11)     # Sunday
FULL_DAY_2 = date(2027, 4, 12)     # Monday


# ------------------------------------------------------------------ small builders

def arrival(w, fid, to, price, frm="HOM", seats=9):
    w.flight(fid, frm, to, "2027-04-09T22:00:00", "2027-04-10T08:00:00", price, seats)


def departure(w, fid, frm, price, nights=3, seats=9, to="HOM"):
    d = (START + timedelta(days=nights)).isoformat()
    w.flight(fid, frm, to, f"{d}T18:00:00", f"{d}T23:00:00", price, seats)


def add_airport(w, code, city):
    w.airports.append({"code": code, "name": code, "city": city, "country": "ZZ", "timezone": "Asia/Tokyo",
                       "lat": 0, "lng": 0, "serves_cities": [city]})
    w.cities[city].append(code)


def core_single(city="X", nights=3, room_adults=2, room_children=2, seats_out=9, filler=False):
    """One city, one arrival and one return flight, one hotel with one room, one airport taxi.
    The loader requires a non-empty attraction list, so `filler=True` adds two unused attractions
    (two distinct ones are needed to cover the two full days of a 3-night trip)."""
    w = World(cities=(city,), links=())
    arrival(w, "F-IN", f"A{city}", 1000)
    departure(w, "F-OUT", f"A{city}", 1000, nights=nights, seats=seats_out)
    w.hotel("H1", city)
    w.room("R1", "H1", 500, max_adults=room_adults, max_children=room_children)
    w.airport_transfer("T-AIR", f"A{city}", city, 100)
    if filler:
        w.attraction("ATT-FILLER-1", city, 10)
        w.attraction("ATT-FILLER-2", city, 20)
    return w


def two_city_world(nights=4):
    """Cities X and Y. Arrivals into AX, BX (both serve X) and AY, BY; returns from AX, AY, BY."""
    w = World(cities=("X", "Y"), links=())
    add_airport(w, "BX", "X")
    add_airport(w, "BY", "Y")
    arrival(w, "F-IN-AX", "AX", 1000)
    arrival(w, "F-IN-BX", "BX", 900)
    arrival(w, "F-IN-AY", "AY", 1100)
    arrival(w, "F-IN-BY", "BY", 950)
    departure(w, "F-OUT-AX", "AX", 1300, nights=nights)
    departure(w, "F-OUT-AY", "AY", 1000, nights=nights)
    departure(w, "F-OUT-BY", "BY", 950, nights=nights)
    w.hotel("H-X", "X")
    w.room("R-X", "H-X", 400)
    w.hotel("H-Y", "Y")
    w.room("R-Y", "H-Y", 350)
    w.airport_transfer("T-AX", "AX", "X", 100)
    w.airport_transfer("T-BX", "BX", "X", 90)
    w.airport_transfer("T-AY", "AY", "Y", 120)
    w.airport_transfer("T-BY", "BY", "Y", 80)
    w.attraction("ATT-X1", "X", 50)
    w.attraction("ATT-Y1", "Y", 40)
    w.attraction("ATT-Y2", "Y", 70)
    return w


def plan(w, req, objective=MINIMUM_COST):
    """Planner result plus the oracle's (minimum, valid count) for the same world and request."""
    res = build_package(req, w.loaded(), objective)
    minimum, valid = oracle_minimum(w, req)
    return res, minimum, valid


def assert_proven_minimum(res, minimum, valid):
    assert minimum is not None and valid >= 1, "oracle must find at least one valid package"
    assert res.status == FOUND
    assert res.package is not None
    assert res.cheapest_total == minimum
    assert res.package.total == minimum


# ------------------------------------------------------------------ Group C: search completeness

def test_cheapest_hotel_without_transfer_loses_to_second_hotel():
    w = World(cities=("X",), links=())
    arrival(w, "F-IN", "AX", 1000)
    departure(w, "F-OUT", "AX", 1000)
    w.hotel("H-NORTH", "X", area="North")          # cheapest, but no transfer serves North
    w.room("R-NORTH", "H-NORTH", 100)
    w.hotel("H-CENTRE", "X", area="Centre")
    w.room("R-CENTRE", "H-CENTRE", 300)
    w.airport_transfer("T-CENTRE", "AX", "X", 100, area="Centre")
    for i, p in enumerate((10, 20, 30), start=1):
        w.attraction(f"ATT-{i}", "X", p)

    res, minimum, valid = plan(w, request(nights=3, adults=2), MINIMUM_COST)
    assert_proven_minimum(res, minimum, valid)
    assert [h.hotel_id for h in res.package.hotels] == ["H-CENTRE"]


def test_cheapest_arrival_flight_without_airport_transfer_is_skipped():
    w = core_single()
    add_airport(w, "BX", "X")
    arrival(w, "F-CHEAP", "BX", 500)               # cheapest, lands where no transfer runs
    for i, p in enumerate((10, 20, 30), start=1):
        w.attraction(f"ATT-{i}", "X", p)

    res, minimum, valid = plan(w, request(nights=3, adults=2), MINIMUM_COST)
    assert_proven_minimum(res, minimum, valid)
    assert res.package.arrival_flight.flight_id == "F-IN"


def test_cheap_hotel_with_expensive_transfer_loses_to_pricier_hotel_with_cheap_transfer():
    w = World(cities=("X",), links=())
    arrival(w, "F-IN", "AX", 1000)
    departure(w, "F-OUT", "AX", 1000)
    w.hotel("H-CHEAP", "X", area="Centre")
    w.room("R-CHEAP", "H-CHEAP", 500)
    w.hotel("H-PRICEY", "X", area="East")
    w.room("R-PRICEY", "H-PRICEY", 900)
    w.airport_transfer("T-EXP", "AX", "X", 3000, area="Centre")   # per vehicle, expensive
    w.airport_transfer("T-CHEAP", "AX", "X", 100, area="East")    # cheap
    for i, p in enumerate((10, 20, 30), start=1):
        w.attraction(f"ATT-{i}", "X", p)

    res, minimum, valid = plan(w, request(nights=3, adults=2), MINIMUM_COST)
    assert_proven_minimum(res, minimum, valid)
    assert [h.hotel_id for h in res.package.hotels] == ["H-PRICEY"]


def test_greedy_cheapest_attraction_on_day_one_would_fail_so_planner_reorders():
    w = core_single(nights=3)
    sunday = ALL_DAYS[FULL_DAY_1.weekday()]        # day 1 weekday; B is open only that day
    w.attraction("ATT-A", "X", 10)                 # cheapest, open every day
    w.attraction("ATT-B", "X", 500, open_days=[sunday])

    res, minimum, valid = plan(w, request(nights=3, adults=2), MINIMUM_COST)
    assert_proven_minimum(res, minimum, valid)
    visits = {v.start.date(): v.attraction_id for v in res.package.visits}
    assert visits == {FULL_DAY_1: "ATT-B", FULL_DAY_2: "ATT-A"}


# ------------------------------------------------------------------ Group D: minimum-cost proof

def test_multiple_arrival_and_return_airports_across_two_cities():
    w = two_city_world(nights=4)
    w.intercity("TR-XY", "X", "Y", 600)

    res, minimum, valid = plan(w, request(nights=4, adults=2), MINIMUM_COST)
    assert_proven_minimum(res, minimum, valid)
    pkg = res.package
    assert pkg.arrival_transfer.transfer_id in {"T-AX", "T-BX", "T-AY", "T-BY"}
    assert pkg.departure_transfer.transfer_id in {"T-AX", "T-BX", "T-AY", "T-BY"}


def test_alternative_intercity_transfers_with_different_pricing():
    w = two_city_world(nights=4)
    w.intercity("TR-PP", "X", "Y", 800, pricing="PER_PERSON", child_price=300)
    w.intercity("TR-PV", "X", "Y", 2500, pricing="PER_VEHICLE", max_passengers=4)

    res, minimum, valid = plan(w, request(nights=4, adults=2, children=(5,)), MINIMUM_COST)
    assert_proven_minimum(res, minimum, valid)
    assert res.package.intercity[0].transfer_id in {"TR-PP", "TR-PV"}


def test_several_attraction_assignments_including_free_child_price():
    w = core_single(nights=3)
    w.attraction("ATT-1", "X", 100, child_price=0)
    w.attraction("ATT-2", "X", 300)
    w.attraction("ATT-3", "X", 200, child_price=50)

    res, minimum, valid = plan(w, request(nights=3, adults=2, children=(5,)), MINIMUM_COST)
    assert_proven_minimum(res, minimum, valid)
    ids = [v.attraction_id for v in res.package.visits]
    assert len(ids) == len(set(ids)) == 2


def _budget_world():
    w = core_single(nights=3)
    w.attraction("ATT-1", "X", 10)
    w.attraction("ATT-2", "X", 20)
    w.attraction("ATT-3", "X", 30)
    return w


def test_budget_below_every_valid_package_is_over_budget_with_proven_cheapest():
    w = _budget_world()
    _, minimum, valid = plan(w, request(nights=3, adults=2), MINIMUM_COST)   # unbounded oracle
    assert minimum is not None and valid >= 1

    budget = minimum - 1
    res = build_package(request(nights=3, adults=2, budget=budget), w.loaded(), WITHIN_BUDGET)
    assert res.status == OVER_BUDGET
    assert res.package is not None
    assert res.cheapest_total == minimum
    assert res.shortfall == minimum - budget
    assert res.budget_remaining is None


def test_budget_exactly_equal_to_minimum_is_found_with_zero_remaining():
    w = _budget_world()
    _, minimum, valid = plan(w, request(nights=3, adults=2), MINIMUM_COST)
    assert minimum is not None and valid >= 1

    res = build_package(request(nights=3, adults=2, budget=minimum), w.loaded(), MINIMUM_COST)
    assert res.status == FOUND
    assert res.cheapest_total == minimum
    assert res.budget_remaining == 0


def test_no_return_flight_on_end_date_is_infeasible():
    w = core_single(nights=5, filler=True)     # the only return flight leaves on day 5, not day 3
    req = request(nights=3, adults=2)
    res, minimum, valid = plan(w, req, MINIMUM_COST)
    assert minimum is None and valid == 0
    assert res.status == INFEASIBLE
    assert res.package is None
    assert res.reasons
    assert "NO_RETURN_FLIGHT" in res.reason_codes


def test_return_flight_without_enough_seats_is_infeasible():
    w = core_single(nights=3, seats_out=1, filler=True)     # one seat left, party of two
    req = request(nights=3, adults=2)
    res, minimum, valid = plan(w, req, MINIMUM_COST)
    assert minimum is None and valid == 0
    assert res.status == INFEASIBLE
    assert res.package is None
    assert res.reasons
    assert "INSUFFICIENT_FLIGHT_SEATS" in res.reason_codes


def test_only_room_type_too_small_for_party_is_infeasible():
    # Adult-only single rooms, one adult and one child: a second room would need a second adult
    # (every room needs at least one adult), so no room count holds the party.
    w = core_single(nights=3, room_adults=1, room_children=0, filler=True)
    req = request(nights=3, adults=1, children=(5,))
    res, minimum, valid = plan(w, req, MINIMUM_COST)
    assert minimum is None and valid == 0
    assert res.status == INFEASIBLE
    assert res.package is None
    assert res.reasons
    assert "NO_HOTEL_CAPACITY" in res.reason_codes


def test_planning_is_deterministic_and_does_not_mutate_catalog():
    w = _budget_world()
    before = copy.deepcopy(w.raw())
    req = request(nights=3, adults=2)

    first = build_package(req, w.loaded(), MINIMUM_COST)
    second = build_package(req, w.loaded(), MINIMUM_COST)
    assert first.status == second.status == FOUND
    assert first.package == second.package
    assert first.package is not None
    assert w.raw() == before


# ------------------------------------------------------------------ parametrized sweep

def _sweep_single():
    w = core_single(nights=3)
    w.attraction("ATT-1", "X", 40, child_price=10)
    w.attraction("ATT-2", "X", 60)
    return w


def _sweep_two_hotels():
    w = core_single(nights=3)
    w.hotel("H2", "X", area="East")
    w.room("R2", "H2", 900)
    w.airport_transfer("T-EAST", "AX", "X", 80, area="East")
    w.attraction("ATT-1", "X", 25, child_price=0)
    w.attraction("ATT-2", "X", 55)
    return w


def _sweep_two_city():
    w = two_city_world(nights=4)
    w.intercity("TR-XY", "X", "Y", 600, pricing="PER_PERSON", child_price=200)
    return w


SWEEP_WORLDS = [
    pytest.param(_sweep_single, 3, id="single-city"),
    pytest.param(_sweep_two_hotels, 3, id="two-hotels"),
    pytest.param(_sweep_two_city, 4, id="two-cities"),
]
SWEEP_PARTIES = [
    pytest.param(1, (), id="1-adult"),
    pytest.param(2, (), id="2-adults"),
    pytest.param(2, (5, 8), id="2-adults-2-children"),
]


@pytest.mark.parametrize("make_world, nights", SWEEP_WORLDS)
@pytest.mark.parametrize("adults, children", SWEEP_PARTIES)
def test_minimum_cost_matches_oracle_across_worlds_and_parties(make_world, nights, adults, children):
    w = make_world()
    req = request(nights=nights, adults=adults, children=children)
    res, minimum, valid = plan(w, req, MINIMUM_COST)
    if minimum is None:
        assert valid == 0
        assert res.status == INFEASIBLE
        assert res.package is None
    else:
        assert_proven_minimum(res, minimum, valid)
