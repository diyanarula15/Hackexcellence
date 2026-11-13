"""Delay Rescue engine (Phase 5B): simulate_arrival_delay on tiny synthetic worlds.

Starting packages come from the real planner (build_package, MINIMUM_COST) on synth worlds. Exact
times are then set with the catalog's own price formulas (app.rules.pricing, app.engine.schedule), and
every starting package is asserted valid first. Run from backend/:
    ../.venv/bin/python -m pytest -q tests/test_delay_scenario.py
"""

from copy import deepcopy
from datetime import date, datetime, timedelta

import pytest

from app.engine.build import FOUND, MINIMUM_COST, build_package
from app.engine.model import ARRIVAL_LEG, TransferOption
from app.engine.scenario import (ABSORBED, REPAIRED, UNRECOVERABLE, VISIT_CANNOT_MOVE,
                                 exact_absorbed_tolerance, normal_violations, scenario_violations,
                                 simulate_arrival_delay)
from app.engine.schedule import make_visit
from app.export.to_trip import to_trip_json
from app.rules import pricing
from app.rules.common import Party
from synth import World, request

PARTY = Party(adults=2, child_ages=(6,))
DAY = date(2027, 4, 10)
DEFAULT_ATTRACTIONS = [("ATT-1", 10, {}), ("ATT-2", 20, {}), ("ATT-3", 30, {})]


def _world(landing="2027-04-10T08:00:00", transfers=None, attractions=None):
    """One city X with hotel H1, airport AX. The outbound flight F-IN lands at `landing` (departs ten
    hours earlier); return flights leave every evening of a 3-6 night holiday."""
    landing_dt = datetime.fromisoformat(landing)
    w = World(cities=("X",), links=())
    w.flight("F-IN", "HOM", "AX", (landing_dt - timedelta(hours=10)).isoformat(), landing, 1000)
    for n in range(3, 7):
        d = DAY + timedelta(days=n)
        w.flight(f"F-OUT-{n}", "AX", "HOM", f"{d.isoformat()}T18:00:00", f"{d.isoformat()}T23:00:00", 1000)
    w.hotel("H1", "X")
    w.room("R1", "H1", 500)
    for spec in transfers or [{"tid": "T-AIR", "price": 100}]:
        spec = dict(spec)
        w.airport_transfer(spec.pop("tid"), "AX", "X", spec.pop("price"), **spec)
    for aid, price, kw in attractions or DEFAULT_ATTRACTIONS:
        w.attraction(aid, "X", price, **kw)
    return w


def _start(world, cat, nights=3):
    """The planner's cheapest valid package on this world, validated as a starting point."""
    result = build_package(request(nights=nights, children=(6,)), cat, MINIMUM_COST)
    assert result.status == FOUND, result.reasons
    pkg = result.package
    _assert_valid(pkg, cat)
    return pkg


def _assert_valid(pkg, cat):
    assert normal_violations(pkg, cat) == []
    assert scenario_violations(pkg, pkg.arrival_flight.arrival, cat) == []


def _with_pickup(pkg, cat, when: datetime):
    """The same arrival service, picking up at `when` (price and duration from the catalog)."""
    rec = cat.indexes.transfers_by_id[pkg.arrival_transfer.transfer_id]
    qty, price = pricing.transfer_price(rec, PARTY)
    t = TransferOption(ARRIVAL_LEG, rec["transfer_id"], when,
                       when + timedelta(minutes=rec["duration_minutes"]), qty, price)
    return pkg.with_(arrival_transfer=t)


def _add_visit(pkg, cat, attraction_id: str, start: datetime):
    v = make_visit(cat.indexes.attractions_by_id[attraction_id], start, PARTY)
    return pkg.with_(visits=tuple(sorted((*pkg.visits, v), key=lambda x: (x.start, x.attraction_id))))


def _visit(pkg, attraction_id):
    return next(v for v in pkg.visits if v.attraction_id == attraction_id)


def _landing(pkg, minutes):
    return pkg.arrival_flight.arrival + timedelta(minutes=minutes)


# ------------------------------------------------------------------ absorbed


def _absorbed_case(delay):
    """Pickup at landing + 180 minutes: far enough for both 60 and 120 minute delays."""
    w = _world()
    cat = w.loaded()
    pkg = _with_pickup(_start(w, cat), cat, datetime(2027, 4, 10, 11, 0))
    _assert_valid(pkg, cat)
    return pkg, cat, simulate_arrival_delay(pkg, delay, cat)


@pytest.mark.parametrize("delay", [60, 120])
def test_absorbed_delay_changes_nothing(delay):
    pkg, cat, r = _absorbed_case(delay)
    assert r.outcome == ABSORBED
    assert r.changed_items == [] and r.automatic_repairs == [] and r.removed_activities == []
    assert r.price_difference_inr == 0
    assert r.proposed_package == pkg
    assert r.violations == []
    assert r.proposed_pickup == "2027-04-10T11:00"


# ------------------------------------------------------------------ repaired, same service


def _same_service_case(delay=60):
    """Planner pickup at landing + 60 (09:00) on the one all-day service; a 60 minute delay moves it."""
    w = _world()
    cat = w.loaded()
    pkg = _start(w, cat)
    assert pkg.arrival_transfer.pickup == datetime(2027, 4, 10, 9, 0)
    return pkg, cat, simulate_arrival_delay(pkg, delay, cat)


def test_later_pickup_on_the_same_service_is_rescheduled():
    pkg, cat, r = _same_service_case(60)
    assert r.outcome == REPAIRED
    assert r.proposed_pickup == "2027-04-10T10:00"          # simulated 09:00 + 60
    assert r.proposed_package.arrival_transfer.transfer_id == pkg.arrival_transfer.transfer_id
    [change] = r.changed_items
    assert (change.component, change.action) == (ARRIVAL_LEG, "RESCHEDULED")


# ------------------------------------------------------------------ repaired, different service


def _replaced_case(delay=60):
    """Cheap service T-A only collects between 09:10 and 09:30, so after a 60 minute delay it cannot
    collect at all (its next-day window opens after the simulated landing + 24 h). T-B always can."""
    w = _world(transfers=[{"tid": "T-A", "price": 50, "window": ("09:10", "09:30"), "duration": 30},
                          {"tid": "T-B", "price": 100}])
    cat = w.loaded()
    pkg = _start(w, cat)
    assert pkg.arrival_transfer.transfer_id == "T-A"
    return pkg, cat, simulate_arrival_delay(pkg, delay, cat)


def test_a_different_service_replaces_the_one_that_closes():
    pkg, cat, r = _replaced_case(60)
    assert r.outcome == REPAIRED
    assert r.proposed_package.arrival_transfer.transfer_id == "T-B"
    assert r.proposed_pickup == "2027-04-10T10:00"
    assert [(c.component, c.action) for c in r.changed_items] == [(ARRIVAL_LEG, "REPLACED")]
    assert r.proposed_package.hotels == pkg.hotels
    assert r.proposed_package.arrival_flight == pkg.arrival_flight
    assert r.proposed_package.return_flight == pkg.return_flight


# ------------------------------------------------------------------ unrecoverable


def _unrecoverable_case():
    """Services always reopen daily, so "every service has ended" cannot be built under the 24 h rule.
    Instead: landing 23:00, the only transfer takes 10 hours and the only attraction open on the Sunday
    (2027-04-11) is 10:00-11:00. A 60 minute delay arrives at the hotel at 11:00, colliding with that
    full-day visit, which has no other start, so the repair fails and nothing else can replace it."""
    w = _world(landing="2027-04-10T23:00:00", transfers=[{"tid": "T-AIR", "price": 100, "duration": 600}],
               attractions=[("ATT-SUN", 10, {"open_days": ["SUN"], "hours": ("10:00", "11:00"), "minutes": 60}),
                            ("ATT-2", 20, {}), ("ATT-3", 30, {})])
    cat = w.loaded()
    pkg = _start(w, cat)
    assert pkg.arrival_transfer.pickup == datetime(2027, 4, 11, 0, 0)
    assert _visit(pkg, "ATT-SUN").start == datetime(2027, 4, 11, 10, 0)
    return pkg, cat, simulate_arrival_delay(pkg, 60, cat)


def test_collision_with_an_unmovable_full_day_visit_is_unrecoverable():
    pkg, cat, r = _unrecoverable_case()
    assert r.outcome == UNRECOVERABLE
    assert r.proposed_package is None
    assert r.changed_items == [] and r.price_difference_inr is None
    assert r.violations, "an unrecoverable delay must say why"
    fails = [v for v in r.violations if v.rule == VISIT_CANNOT_MOVE]
    assert len(fails) == 1
    assert "ATT-SUN" in fails[0].message and "2027-04-11" in fails[0].message
    assert "Your saved holiday stays unchanged" in r.explanation


# ------------------------------------------------------------------ midnight


def test_delay_crossing_midnight_moves_the_pickup_to_the_next_date():
    w = _world(landing="2027-04-10T23:00:00")
    cat = w.loaded()
    pkg = _start(w, cat)
    assert pkg.arrival_transfer.pickup == datetime(2027, 4, 11, 0, 0)
    r = simulate_arrival_delay(pkg, 120, cat)
    assert r.outcome == REPAIRED
    assert r.scheduled_landing == "2027-04-10T23:00" and r.simulated_landing == "2027-04-11T01:00"
    assert r.proposed_pickup == "2027-04-11T02:00"
    proposed = r.proposed_package
    assert proposed.plan == pkg.plan
    assert proposed.hotels == pkg.hotels
    assert proposed.intercity == pkg.intercity
    assert proposed.departure_transfer == pkg.departure_transfer
    assert proposed.return_flight == pkg.return_flight
    assert proposed.arrival_transfer.pickup.date() == date(2027, 4, 11)


def test_transfer_window_that_crosses_midnight_is_used_after_midnight():
    w = _world(landing="2027-04-10T23:00:00",
               transfers=[{"tid": "T-NIGHT", "price": 100, "window": ("06:00", "00:30")}])
    cat = w.loaded()
    pkg = _start(w, cat)
    assert pkg.arrival_transfer.pickup == datetime(2027, 4, 11, 0, 0)   # inside the window opened on the 10th
    r = simulate_arrival_delay(pkg, 60, cat)
    assert r.outcome == REPAIRED
    assert r.proposed_pickup == "2027-04-11T06:00"                       # the 00:30 close is too early


# ------------------------------------------------------------------ the 60 minute boundary


def test_pickup_exactly_sixty_minutes_after_the_simulated_landing_is_accepted():
    w = _world()
    cat = w.loaded()
    pkg = _with_pickup(_start(w, cat), cat, datetime(2027, 4, 10, 10, 0))
    assert scenario_violations(pkg, datetime(2027, 4, 10, 9, 0), cat) == []     # simulated 09:00 + 60


def test_pickup_fifty_nine_minutes_after_the_simulated_landing_is_rejected():
    w = _world()
    cat = w.loaded()
    pkg = _with_pickup(_start(w, cat), cat, datetime(2027, 4, 10, 9, 59))
    rules = [v.rule for v in scenario_violations(pkg, datetime(2027, 4, 10, 9, 0), cat)]
    assert "R-ATR-5" in rules


# ------------------------------------------------------------------ visits on the arrival day


ARRIVAL_DAY_ATTRACTION = ("ATT-EARLY", 5000, {"hours": ("09:00", "18:00")})


def _moved_visit_case():
    """A 09:30-10:30 arrival-day visit collides with the hotel arrival after a 60 minute delay
    (pickup 10:00, arrive 10:30). Nothing else changes."""
    w = _world(attractions=DEFAULT_ATTRACTIONS + [ARRIVAL_DAY_ATTRACTION])
    cat = w.loaded()
    pkg = _add_visit(_start(w, cat), cat, "ATT-EARLY", datetime(2027, 4, 10, 9, 30))
    _assert_valid(pkg, cat)
    return pkg, cat, simulate_arrival_delay(pkg, 60, cat)


def test_arrival_day_attraction_is_shifted_later_within_opening_hours():
    pkg, cat, r = _moved_visit_case()
    assert r.outcome == REPAIRED
    assert [(c.component, c.action) for c in r.changed_items if c.component == "visit:ATT-EARLY"] == \
        [("visit:ATT-EARLY", "RESCHEDULED")]
    assert _visit(r.proposed_package, "ATT-EARLY").start == datetime(2027, 4, 10, 10, 30)
    _assert_valid(r.proposed_package, cat)


def test_arrival_day_attraction_with_no_later_time_is_removed_and_disclosed():
    w = _world(attractions=DEFAULT_ATTRACTIONS + [("ATT-EARLY", 5000, {"hours": ("09:00", "10:30")})])
    cat = w.loaded()
    pkg = _add_visit(_start(w, cat), cat, "ATT-EARLY", datetime(2027, 4, 10, 9, 30))
    early = _visit(pkg, "ATT-EARLY")
    r = simulate_arrival_delay(pkg, 60, cat)
    assert r.outcome == REPAIRED
    assert [c.component for c in r.removed_activities] == ["visit:ATT-EARLY"]
    assert all(v.attraction_id != "ATT-EARLY" for v in r.proposed_package.visits)
    assert r.proposed_package.total == pkg.total - early.price
    assert r.price_difference_inr == -early.price
    _assert_valid(r.proposed_package, cat)


# ------------------------------------------------------------------ untouched components


def test_everything_outside_the_arrival_scope_is_unchanged():
    pkg, cat, r = _moved_visit_case()
    p = r.proposed_package
    assert p.plan == pkg.plan
    assert p.hotels == pkg.hotels
    assert p.intercity == pkg.intercity
    assert p.departure_transfer == pkg.departure_transfer
    assert p.return_flight == pkg.return_flight
    later = (lambda pk: [v for v in pk.visits if v.start.date() > DAY + timedelta(days=1)])
    assert later(p) == later(pkg) and later(pkg)


def _repaired_cases():
    return [
        ("same-service", *_same_service_case(60)),
        ("different-service", *_replaced_case(60)),
        ("midnight", *_midnight_case()),
        ("moved-visit", *_moved_visit_case()),
        ("removed-visit", *_removed_visit_case()),
    ]


def _midnight_case():
    w = _world(landing="2027-04-10T23:00:00")
    cat = w.loaded()
    pkg = _start(w, cat)
    return pkg, cat, simulate_arrival_delay(pkg, 120, cat)


def _removed_visit_case():
    w = _world(attractions=DEFAULT_ATTRACTIONS + [("ATT-EARLY", 5000, {"hours": ("09:00", "10:30")})])
    cat = w.loaded()
    pkg = _add_visit(_start(w, cat), cat, "ATT-EARLY", datetime(2027, 4, 10, 9, 30))
    return pkg, cat, simulate_arrival_delay(pkg, 60, cat)


@pytest.mark.parametrize("label, pkg, cat, r", _repaired_cases(), ids=lambda x: x if isinstance(x, str) else None)
def test_every_repair_passes_both_checks(label, pkg, cat, r):
    assert r.outcome == REPAIRED, label
    p = r.proposed_package
    assert normal_violations(p, cat) == []
    assert scenario_violations(p, datetime.fromisoformat(r.simulated_landing), cat) == []
    assert p.arrival_flight == pkg.arrival_flight          # no synthetic delay written into the flight
    assert p.return_flight == pkg.return_flight


def test_repair_price_difference_is_transfer_change_minus_removed_visits():
    _, _, r = _replaced_case(60)
    pkg, cat, _ = _replaced_case(60)
    assert r.price_difference_inr == r.proposed_package.arrival_transfer.price - pkg.arrival_transfer.price == 50

    pkg, cat, r = _removed_visit_case()
    removed = _visit(pkg, "ATT-EARLY").price
    assert r.price_difference_inr == (r.proposed_package.arrival_transfer.price - pkg.arrival_transfer.price
                                      - removed) == -removed
    assert r.proposed_total_inr - r.original_total_inr == r.price_difference_inr


def test_exported_arrival_flight_keeps_the_catalog_times():
    pkg, cat, r = _moved_visit_case()
    rec = cat.indexes.flights_by_id["F-IN"]
    items = to_trip_json(r.proposed_package, cat)["items"]
    [flight] = [i for i in items if i["type"] == "flight" and i["catalog_id"] == "F-IN"]
    assert flight["start"] == rec["departure_local"][:16]
    assert flight["end"] == rec["arrival_local"][:16] == "2027-04-10T08:00"


def test_simulation_never_mutates_the_package_or_the_catalog():
    w = _world(attractions=DEFAULT_ATTRACTIONS + [ARRIVAL_DAY_ATTRACTION])
    cat = w.loaded()
    pkg = _add_visit(_start(w, cat), cat, "ATT-EARLY", datetime(2027, 4, 10, 9, 30))
    pkg_before, cat_before = deepcopy(pkg), deepcopy(cat.catalog)
    for minutes in (60, 120, 240):
        simulate_arrival_delay(pkg, minutes, cat)
    assert pkg == pkg_before
    assert cat.catalog == cat_before


# ------------------------------------------------------------------ tolerance and validation


def test_exact_absorbed_tolerance_is_pickup_slack_and_verified_at_the_boundary():
    w = _world()
    cat = w.loaded()
    pkg = _with_pickup(_start(w, cat), cat, datetime(2027, 4, 10, 10, 0))   # 120 minutes after landing
    assert exact_absorbed_tolerance(pkg, cat) == 60
    assert simulate_arrival_delay(pkg, 60, cat).outcome == ABSORBED
    assert simulate_arrival_delay(pkg, 61, cat).outcome != ABSORBED


@pytest.mark.parametrize("bad", [0, -5, True, False, 60.0, "60"])
def test_invalid_delay_minutes_are_rejected(bad):
    pkg, cat, _ = _same_service_case(60)
    with pytest.raises(ValueError):
        simulate_arrival_delay(pkg, bad, cat)
