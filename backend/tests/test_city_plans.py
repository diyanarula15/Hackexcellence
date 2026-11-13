import copy
from datetime import date, timedelta

import pytest

from app.catalog.load import build_loaded, load_catalog, load_raw
from app.engine.city_plans import generate_city_plans

START = date(2027, 4, 1)
JAPAN_CITIES = {"Tokyo", "Kyoto", "Osaka"}


@pytest.fixture(scope="module")
def data():
    return load_catalog()


def _country(raw, code):
    return next(c for c in raw["destinations"]["countries"] if c["code"] == code)


def _links(raw_or_loaded_country):
    return {(ln["from_city"], ln["to_city"]) for ln in raw_or_loaded_country["links"]}


def _nights(plan):
    return tuple(s.nights for s in plan.stays)


def _plans_for(plans, cities):
    return [p for p in plans if p.cities == tuple(cities)]


@pytest.mark.parametrize("country", ["JP", "Japan", "jp", "JAPAN"])
def test_three_nights_gives_only_single_city_plans(data, country):
    plans = generate_city_plans(country, 3, data, START)
    assert plans
    assert all(len(p.cities) == 1 for p in plans)
    assert {p.cities[0] for p in plans} == JAPAN_CITIES


@pytest.mark.parametrize("pair", sorted(_links(_country(load_raw(), "JP"))))
def test_four_nights_has_two_city_plan_for_each_link(data, pair):
    plans = generate_city_plans("JP", 4, data, START)
    matches = _plans_for(plans, pair)
    assert len(matches) == 1
    assert _nights(matches[0]) == (2, 2)


def test_six_nights_has_connected_three_city_plan(data):
    plans = generate_city_plans("JP", 6, data, START)
    three = [p for p in plans if len(p.cities) == 3]
    assert three
    assert all(_nights(p) == (2, 2, 2) for p in three)
    assert {frozenset(p.cities) for p in three} == {frozenset(JAPAN_CITIES)}


@pytest.mark.parametrize("pair", [("Tokyo", "Kyoto"), ("Kyoto", "Tokyo"), ("Osaka", "Tokyo")])
def test_six_nights_uneven_allocations_for_a_pair(data, pair):
    plans = _plans_for(generate_city_plans("JP", 6, data, START), pair)
    assert sorted(_nights(p) for p in plans) == [(2, 4), (3, 3), (4, 2)]


def test_no_plan_repeats_a_city_and_every_hop_is_a_link(data):
    country = next(c for c in data.catalog.destinations["countries"] if c["code"] == "JP")
    links = _links(country)
    plans = generate_city_plans("JP", 10, data, START)
    assert plans
    for p in plans:
        assert len(set(p.cities)) == len(p.cities)
        for a, b in zip(p.cities, p.cities[1:]):
            assert (a, b) in links


def test_removed_one_way_link_disappears_but_reverse_stays():
    raw = copy.deepcopy(load_raw())
    jp = _country(raw, "JP")
    jp["links"] = [ln for ln in jp["links"] if (ln["from_city"], ln["to_city"]) != ("Tokyo", "Kyoto")]
    loaded = build_loaded(raw)
    plans = generate_city_plans("JP", 6, loaded, START)
    assert not any(
        a == "Tokyo" and b == "Kyoto" for p in plans for a, b in zip(p.cities, p.cities[1:])
    )
    assert _plans_for(plans, ("Kyoto", "Tokyo"))
    assert _plans_for(plans, ("Tokyo", "Osaka"))


@pytest.mark.parametrize("country", ["XX", "", "Atlantis", "Japa"])
def test_unknown_country_gives_no_plans(data, country):
    assert generate_city_plans(country, 6, data, START) == []


@pytest.mark.parametrize("nights", [0, 1, -3])
def test_nights_below_minimum_gives_no_plans(data, nights):
    assert generate_city_plans("JP", nights, data, START) == []


@pytest.mark.parametrize("start", [
    date(2027, 4, 1),
    date(2027, 4, 28),   # crosses a month end
    date(2027, 12, 29),  # crosses a year end
])
@pytest.mark.parametrize("nights", [3, 6, 10])
def test_stays_are_consecutive_and_span_the_trip(data, start, nights):
    plans = generate_city_plans("JP", nights, data, start)
    assert plans
    for p in plans:
        assert p.stays[0].check_in == start
        assert p.stays[-1].check_out == start + timedelta(days=nights)
        for a, b in zip(p.stays, p.stays[1:]):
            assert a.check_out == b.check_in
        assert sum(s.nights for s in p.stays) == nights
        assert all(s.nights >= 2 for s in p.stays)


def test_extended_catalog_with_extra_city_needs_no_code_change():
    raw = copy.deepcopy(load_raw())
    jp = _country(raw, "JP")
    jp["cities"].append({"name": "Nara", "airports": ["KIX"]})
    jp["links"].append({"from_city": "Tokyo", "to_city": "Nara", "transfer_ids": ["TR-TYO-KYO-01"]})
    jp["links"].append({"from_city": "Nara", "to_city": "Tokyo", "transfer_ids": ["TR-KYO-TYO-01"]})
    loaded = build_loaded(raw)

    four = generate_city_plans("JP", 4, loaded, START)
    assert _plans_for(four, ("Nara",))
    assert _nights(_plans_for(four, ("Tokyo", "Nara"))[0]) == (2, 2)
    assert any("Nara" in p.cities for p in four)

    six = generate_city_plans("JP", 6, loaded, START)
    assert any("Nara" in p.cities and len(p.cities) == 3 for p in six)
