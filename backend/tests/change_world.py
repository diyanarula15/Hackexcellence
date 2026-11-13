"""Synthetic same-schema worlds for the Phase 5 change tests (the supplied catalog is never touched).

Every world goes through the production loader (synth.World.loaded -> build_loaded), and every base
package is built by the real planner, so the tests change real packages with real rules.

two_city(): home HOM, cities X -> Y, 6 nights, X 2027-04-10..13 then Y 2027-04-13..16, party of 2
adults + 1 child (age 8). The planner's cheapest package uses hotels HX-A / HY-A (area A), flights
F-IN-1 (lands AX 08:00) and F-OUT-LATE (leaves AY 18:00), transfers T-AX-A, TR-XY-1, T-AY-A.
Everything else exists to be chosen in a test:

  flights in   F-IN-LATE lands 14:00 · F-IN-FULL 2 seats · F-IN-AX2 lands at AX2 (also serves X)
               F-IN-AX3 lands at AX3 (serves X, but no transfer from it) · F-IN-WRONGDAY lands 04-11
  flights out  F-OUT-MID 15:00 · F-OUT-EARLY 07:00 (no transfer meets the 180-minute buffer)
               F-OUT-FULL 2 seats
  hotels X     HX-B area B · RX-A-SINGLE (1 adult, needs 2 rooms) · HX-SOLD (no room on 04-11)
               HX-TINY (1 adult, no children: cannot host 2 adults + 1 child at all)
  transfers    T-AX-ANY (any area) · T-AX-B / T-AX2-A / T-AX2-B (areas, airports)
               T-AY-A-EVE (16:00-23:00 only)
               TR-XY-2 · TR-XY-FREQ (every 120 min) · TR-XY-SLOW (arrives 10 h later)
  attractions  ATT-X-1..4, ATT-Y-1..4 (cheap, any time) · ATT-X-CLOSED (closed 04-11)
               ATT-X-MORNING (09:00-12:00) · ATT-X-LONG (9 h, 09:00-19:00) · ATT-Y-DAY (09:00-18:00)
"""

from datetime import date

from app.engine.build import FOUND, MINIMUM_COST, build_package
from synth import World, request

D10, D11, D12, D13, D14, D15, D16 = (date(2027, 4, d) for d in range(10, 17))
PARTY = {"adults": 2, "children": (8,)}


def _airport(w: World, code: str, city: str) -> None:
    w.airports.append(
        {
            "code": code,
            "name": f"{code} Airport",
            "city": city,
            "country": "ZZ",
            "timezone": "Asia/Tokyo",
            "lat": 0,
            "lng": 0,
            "serves_cities": [city],
        }
    )
    w.cities[city].append(code)


def two_city() -> World:
    w = World(cities=("X", "Y"), links=(("X", "Y"),), per_city=3)
    _airport(w, "AX2", "X")
    _airport(w, "AX3", "X")
    w.flight("F-IN-1", "HOM", "AX", "2027-04-09T22:00:00", "2027-04-10T08:00:00", 1000)
    w.flight("F-IN-LATE", "HOM", "AX", "2027-04-10T04:00:00", "2027-04-10T14:00:00", 1500)
    w.flight("F-IN-FULL", "HOM", "AX", "2027-04-09T21:00:00", "2027-04-10T07:00:00", 900, seats=2)
    w.flight("F-IN-AX2", "HOM", "AX2", "2027-04-09T22:30:00", "2027-04-10T08:30:00", 1100)
    w.flight("F-IN-AX3", "HOM", "AX3", "2027-04-09T22:30:00", "2027-04-10T08:30:00", 1050)
    w.flight("F-IN-WRONGDAY", "HOM", "AX", "2027-04-10T22:00:00", "2027-04-11T08:00:00", 950)
    w.flight("F-OUT-LATE", "AY", "HOM", "2027-04-16T18:00:00", "2027-04-16T23:00:00", 1000)
    w.flight("F-OUT-MID", "AY", "HOM", "2027-04-16T15:00:00", "2027-04-16T20:00:00", 1100)
    w.flight("F-OUT-EARLY", "AY", "HOM", "2027-04-16T07:00:00", "2027-04-16T12:00:00", 1050)
    w.flight("F-OUT-FULL", "AY", "HOM", "2027-04-16T17:00:00", "2027-04-16T22:00:00", 900, seats=2)

    w.hotel("HX-A", "X", area="A")
    w.room("RX-A", "HX-A", 500)
    w.room("RX-A-SINGLE", "HX-A", 450, max_adults=1, max_children=1)
    w.hotel("HX-B", "X", area="B")
    w.room("RX-B", "HX-B", 600)
    w.hotel("HX-SOLD", "X", area="A")
    w.room("RX-SOLD", "HX-SOLD", 520)
    w.set_rooms_left("RX-SOLD", "2027-04-11", 0)
    w.hotel("HX-TINY", "X", area="A")
    w.room("RX-TINY", "HX-TINY", 300, max_adults=1, max_children=0)
    w.hotel("HY-A", "Y", area="A")
    w.room("RY-A", "HY-A", 500)
    w.hotel("HY-B", "Y", area="B")
    w.room("RY-B", "HY-B", 600)

    w.airport_transfer("T-AX-A", "AX", "X", 100, area="A")
    w.airport_transfer("T-AX-B", "AX", "X", 150, area="B")
    w.airport_transfer("T-AX2-A", "AX2", "X", 110, area="A")
    w.airport_transfer("T-AX2-B", "AX2", "X", 120, area="B")
    w.airport_transfer("T-AX-ANY", "AX", "X", 180, duration=45)   # every area, dearer: a valid swap
    w.airport_transfer("T-AY-A", "AY", "Y", 100, area="A", window=("05:00", "22:00"))
    w.airport_transfer("T-AY-B", "AY", "Y", 150, area="B", window=("05:00", "22:00"))
    w.airport_transfer("T-AY-A-EVE", "AY", "Y", 90, area="A", window=("16:00", "23:00"))

    w.intercity("TR-XY-1", "X", "Y", 200)
    w.intercity("TR-XY-2", "X", "Y", 260)
    w.intercity("TR-XY-FREQ", "X", "Y", 300, frequency=120)
    w.intercity("TR-XY-SLOW", "X", "Y", 350, duration=600)

    for i, price in enumerate([100, 120, 140, 160], 1):
        w.attraction(f"ATT-X-{i}", "X", price)
        w.attraction(f"ATT-Y-{i}", "Y", price)
    w.attraction("ATT-X-CLOSED", "X", 500, closed_dates=["2027-04-11"])
    w.attraction("ATT-X-MORNING", "X", 700, hours=("09:00", "12:00"))
    w.attraction("ATT-X-LONG", "X", 800, hours=("09:00", "19:00"), minutes=540)
    w.attraction("ATT-Y-DAY", "Y", 900, hours=("09:00", "18:00"), minutes=120)
    return w


def single_city() -> World:
    """One city S, 4 nights: both airport transfers depend on the only hotel."""
    w = World(cities=("S",), links=(), per_city=3)
    w.flight("F-S-IN", "HOM", "AS", "2027-04-09T22:00:00", "2027-04-10T08:00:00", 1000)
    w.flight("F-S-OUT", "AS", "HOM", "2027-04-14T18:00:00", "2027-04-14T23:00:00", 1000)
    w.hotel("HS-A", "S", area="A")
    w.room("RS-A", "HS-A", 500)
    w.hotel("HS-B", "S", area="B")
    w.room("RS-B", "HS-B", 650)
    w.airport_transfer("T-AS-A", "AS", "S", 100, area="A")
    w.airport_transfer("T-AS-B", "AS", "S", 140, area="B")
    for i, price in enumerate([100, 120, 140], 1):
        w.attraction(f"ATT-S-{i}", "S", price)
    return w


def three_city() -> World:
    """X -> Y -> Z, 9 nights (3 each): the Y hotel is a middle hotel."""
    w = World(cities=("X", "Y", "Z"), links=(("X", "Y"), ("Y", "Z")), per_city=3)
    w.flight("F-3-IN", "HOM", "AX", "2027-04-09T22:00:00", "2027-04-10T08:00:00", 1000)
    w.flight("F-3-OUT", "AZ", "HOM", "2027-04-19T18:00:00", "2027-04-19T23:00:00", 1000)
    for city in ("X", "Y", "Z"):
        w.hotel(f"H{city}-A", city, area="A")
        w.room(f"R{city}-A", f"H{city}-A", 500)
        w.hotel(f"H{city}-B", city, area="B")
        w.room(f"R{city}-B", f"H{city}-B", 700)
        for i, price in enumerate([100, 120], 1):
            w.attraction(f"ATT-{city}-{i}", city, price)
    w.airport_transfer("T-AX-A", "AX", "X", 100, area="A")
    w.airport_transfer("T-AZ-A", "AZ", "Z", 100, area="A")
    w.intercity("TR-XY", "X", "Y", 200)
    w.intercity("TR-YZ", "Y", "Z", 200)
    return w


def base(world: World, nights: int = 6, budget: int = 10**9, **party):
    """(the planner's package for this world, the loaded catalog)."""
    data = world.loaded()
    p = {**PARTY, **party}
    res = build_package(
        request(nights=nights, adults=p["adults"], children=p["children"], budget=budget),
        data,
        MINIMUM_COST,
    )
    assert res.status == FOUND, res.reasons
    return res.package, data
