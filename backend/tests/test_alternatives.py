"""Phase 5 alternatives: every option is evaluated as a complete modified package (spec sections 4-5)."""

import pytest
from change_world import base, two_city

from app.engine.change import propose_change
from app.models import CHANGE_COMMAND
from app.rules.common import EDITED
from app.validate.validate_trip import validate_trip
from app.services.alternatives import (
    OptionsRequestError,
    departure_slots,
    get_alternatives,
    options_response,
)
from app.export.to_trip import to_trip_json

STAY_X = "stay:X:2027-04-10:2027-04-13"
LEG_XY = "leg:X>Y:2027-04-13"


@pytest.fixture(scope="module")
def env():
    return base(two_city())


def by_id(alts):
    return {(a.catalog_id, a.room_id): a for a in alts}


def preview(pkg, data, command):
    return propose_change(pkg, CHANGE_COMMAND.validate_python({"base_version": 1, **command}), data)


ALL = [
    ("hotel", STAY_X, None),
    ("arrival_flight", None, None),
    ("return_flight", None, None),
    ("airport_transfer", "leg:arrival", None),
    ("airport_transfer", "leg:departure", None),
    ("intercity_transfer", LEG_XY, None),
    ("attraction", None, "2027-04-12"),
]


@pytest.mark.parametrize("kind,target,day", ALL)
def test_every_valid_option_reproduces_as_a_valid_preview_with_the_same_price(
    env, kind, target, day
):
    pkg, data = env
    alts = get_alternatives(pkg, kind, target, data, day)
    usable = [a for a in alts if a.valid and not a.current]
    # two_city has no valid alternative departure transfer (T-AY-B wrong area, T-AY-A-EVE window)
    assert usable or target == "leg:departure", kind
    for a in usable:
        p = preview(pkg, data, a.command)
        assert p.valid, (a.catalog_id, p.violations)
        assert p.new_total == a.proposed_total_inr
        assert (
            p.price_difference == a.package_price_difference_inr == a.proposed_total_inr - pkg.total
        )
        assert validate_trip(to_trip_json(p.proposed_package, data), data, EDITED) == []
        assert len(a.affected_items) == len(p.automatic_repairs)


@pytest.mark.parametrize("kind,target,day", ALL)
def test_invalid_options_carry_reasons_and_no_price_or_command(env, kind, target, day):
    pkg, data = env
    for a in get_alternatives(pkg, kind, target, data, day):
        if a.valid:
            assert a.reasons == [] and a.package_price_difference_inr is not None
        else:
            assert a.reasons and a.violations
            assert a.proposed_total_inr is None
            assert not preview(pkg, data, a.command).valid  # previewing it shows the same refusal
            assert a.package_price_difference_inr is None


@pytest.mark.parametrize("kind,target,day", ALL)
def test_stable_order_valid_first_then_cheaper(env, kind, target, day):
    pkg, data = env
    alts = get_alternatives(pkg, kind, target, data, day)
    flags = [a.valid for a in alts]
    assert flags == sorted(flags, reverse=True)
    diffs = [a.package_price_difference_inr for a in alts if a.valid]
    assert diffs == sorted(diffs)
    assert alts == get_alternatives(pkg, kind, target, data, day)  # deterministic


def test_hotel_options_show_whole_package_difference_including_transfer_repair(env):
    pkg, data = env
    alts = by_id(get_alternatives(pkg, "hotel", STAY_X, data))
    assert (
        alts[("HX-A", "RX-A")].current and alts[("HX-A", "RX-A")].package_price_difference_inr == 0
    )
    hx_b = alts[("HX-B", "RX-B")]
    assert hx_b.valid and hx_b.package_price_difference_inr == 350  # hotel +300, transfer +50
    assert [i["item_id"] for i in hx_b.affected_items] == ["leg:arrival"]
    assert alts[("HX-A", "RX-A-SINGLE")].details["rooms"] == 2
    sold = alts[("HX-SOLD", "RX-SOLD")]
    assert not sold.valid and {v["rule"] for v in sold.violations} >= {"R-HTL-6"}
    tiny = alts[("HX-TINY", "RX-TINY")]
    assert not tiny.valid and tiny.item_price_inr is None  # no room count can hold the group


def test_hotel_options_stay_in_the_city_of_the_stay(env):
    pkg, data = env
    hotels = {a.catalog_id for a in get_alternatives(pkg, "hotel", STAY_X, data)}
    assert hotels == {"HX-A", "HX-B", "HX-SOLD", "HX-TINY"}


def test_flight_options_include_other_airport_of_same_city_and_reject_full_flights(env):
    pkg, data = env
    alts = by_id(get_alternatives(pkg, "arrival_flight", None, data))
    assert alts[("F-IN-AX2", None)].valid
    assert {v["rule"] for v in alts[("F-IN-FULL", None)].violations} >= {"R-FLT-3"}
    assert not alts[("F-IN-AX3", None)].valid  # no transfer from AX3
    assert ("F-IN-WRONGDAY", None) not in alts  # lands on another day: not an option for this trip
    ret = by_id(get_alternatives(pkg, "return_flight", None, data))
    assert not ret[("F-OUT-EARLY", None)].valid and ret[("F-OUT-MID", None)].valid


def test_airport_transfer_options_use_the_flight_airport(env):
    pkg, data = env
    alts = by_id(get_alternatives(pkg, "airport_transfer", "leg:arrival", data))
    assert set(k[0] for k in alts) == {"T-AX-A", "T-AX-B", "T-AX-ANY"}
    assert alts[("T-AX-ANY", None)].valid
    assert {v["rule"] for v in alts[("T-AX-B", None)].violations} >= {"R-ATR-4"}


def test_intercity_slots_respect_frequency_and_each_valid_slot_previews(env):
    pkg, data = env
    rec = data.indexes.transfers_by_id["TR-XY-FREQ"]
    slots = departure_slots(rec, pkg.plan.stays[0].check_out)
    assert all(
        (t.hour * 60 + t.minute - slots[0].hour * 60 - slots[0].minute) % 120 == 0 for t in slots
    )
    alt = by_id(get_alternatives(pkg, "intercity_transfer", LEG_XY, data))[("TR-XY-FREQ", None)]
    for s in alt.details["departure_slots"]:
        if s["valid"]:
            p = preview(pkg, data, s["command"])
            assert p.valid and p.price_difference == s["package_price_difference_inr"]
    odd = preview(pkg, data, {"kind": "CHANGE_INTERCITY_TRANSFER", "item_id": LEG_XY,
                               "transfer_id": "TR-XY-FREQ", "pickup": "11:00"})  # fmt: skip
    assert not odd.valid  # 11:00 is not a slot of a service every 120 minutes from its window start


def test_attraction_options_are_the_day_city_and_planned_ones_are_refused(env):
    pkg, data = env
    alts = by_id(get_alternatives(pkg, "attraction", None, data, "2027-04-12"))
    assert all(k[0].startswith("ATT-X-") for k in alts)
    assert {v["rule"] for v in alts[("ATT-X-1", None)].violations} == {"R-ATT-7"}
    assert not alts[("ATT-X-LONG", None)].valid
    added = alts[("ATT-X-3", None)]
    assert added.valid and added.command["preferred_start"] == added.details["start"][11:16]


def test_departure_day_offers_nothing_with_a_message(env):
    pkg, data = env
    r = options_response(pkg, "attraction", None, data, "2027-04-16")
    assert r["alternatives"] == [] and "departure day" in r["message"]


def test_loading_options_never_changes_the_package(env):
    pkg, data = env
    before = repr(pkg)
    for kind, target, day in ALL:
        get_alternatives(pkg, kind, target, data, day)
    assert repr(pkg) == before


@pytest.mark.parametrize(
    "kind,target,day,field",
    [
        ("boat", None, None, "kind"),
        (None, None, None, "kind"),
        ("hotel", "stay:Q:2027-04-10:2027-04-13", None, "stay_id"),
        ("hotel", None, None, "stay_id"),
        ("airport_transfer", LEG_XY, None, "item_id"),
        ("intercity_transfer", "leg:arrival", None, "item_id"),
        ("attraction", None, None, "date"),
        ("attraction", None, "2027-13-01", "date"),
        ("attraction", None, "2027-05-01", "date"),
    ],
)
def test_bad_queries_raise_with_the_field(env, kind, target, day, field):
    pkg, data = env
    with pytest.raises(OptionsRequestError) as e:
        options_response(pkg, kind, target, data, day)
    assert e.value.field == field and e.value.message


def test_options_response_json_shape(env):
    pkg, data = env
    r = options_response(pkg, "arrival_flight", None, data)
    assert r["target_item_id"] == "flight:arrival" and r["date"] is None
    keys = {"catalog_id", "room_id", "name", "room_name", "valid", "current", "item_price_inr",
            "proposed_total_inr", "package_price_difference_inr", "budget_remaining_inr",
            "over_budget_inr", "affected_items", "changed_items", "reasons", "violations",
            "warnings", "details", "command"}  # fmt: skip
    assert all(set(a) == keys for a in r["alternatives"])


def test_real_catalog_tokyo_arrival_options_span_both_airports():
    """Real data: a Mumbai -> Japan package can switch between NRT and HND (spec 4.2)."""
    from datetime import date
    from types import SimpleNamespace

    from app.catalog.load import load_catalog
    from app.engine.build import FOUND, MINIMUM_COST, build_package

    data = load_catalog()
    found = None
    for day in range(1, 29):
        req = SimpleNamespace(departure_airport="BOM", destination_country="JP", start_date=date(2027, 4, day),
                              nights=6, adults=2, children_ages=[], budget=10**9)  # fmt: skip
        res = build_package(req, data, MINIMUM_COST)
        if res.status == FOUND and res.package.plan.first_city == "Tokyo":
            found = res.package
            break
    if found is None:
        pytest.skip("no Tokyo-first package in this catalog")
    alts = get_alternatives(found, "arrival_flight", None, data)
    airports = {a.details["to"] for a in alts}
    assert airports <= {"NRT", "HND"}
    for a in alts:
        if a.valid and not a.current:
            assert preview(found, data, a.command).new_total == a.proposed_total_inr
