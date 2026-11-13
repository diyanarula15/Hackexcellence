from dataclasses import replace
from datetime import date

import pytest

from app.catalog.load import load_catalog
from app.rules.common import Party, Stay
from app.rules.hotels import check_hotels
from app.rules.plan import check_city_plan


@pytest.fixture(scope="module")
def data():
    return load_catalog()


def stay(hotel, room, city, ci, co, rooms=1):
    return Stay(None, hotel, room, city, date.fromisoformat(ci), date.fromisoformat(co), rooms)


def rule_set(violations):
    return {v.rule for v in violations}


START = date(2027, 4, 1)
TYO = stay("HTL-TYO-001", "RM-TYO-001-B", "Tokyo", "2027-04-01", "2027-04-03")
KYO = stay("HTL-KYO-002", "RM-KYO-002-B", "Kyoto", "2027-04-03", "2027-04-05")


# --- R-PLAN: itinerary ---

def test_valid_two_city_plan(data):
    assert check_city_plan([TYO, KYO], "JP", START, 4, data) == []


def test_repeated_city_gives_plan_2(data):
    back = stay("HTL-TYO-001", "RM-TYO-001-B", "Tokyo", "2027-04-05", "2027-04-07")
    assert rule_set(check_city_plan([TYO, KYO, back], "JP", START, 6, data)) == {"R-PLAN-2"}


def test_one_night_city_gives_plan_3(data):
    one = stay("HTL-TYO-001", "RM-TYO-001-B", "Tokyo", "2027-04-01", "2027-04-02")
    kyo4 = stay("HTL-KYO-002", "RM-KYO-002-B", "Kyoto", "2027-04-02", "2027-04-06")
    assert rule_set(check_city_plan([one, kyo4], "JP", START, 5, data)) == {"R-PLAN-3"}


def test_missing_link_gives_plan_5(data):
    # Drop Tokyo -> Kyoto but keep Kyoto -> Tokyo: the outbound direction has no link.
    country = data.indexes.countries_by_code["JP"]
    links = [ln for ln in country["links"] if (ln["from_city"], ln["to_city"]) != ("Tokyo", "Kyoto")]
    countries = {**data.indexes.countries_by_code, "JP": {**country, "links": links}}
    patched = replace(data, indexes=replace(data.indexes, countries_by_code=countries))
    assert rule_set(check_city_plan([TYO, KYO], "JP", START, 4, patched)) == {"R-PLAN-5"}


def test_gap_between_stays_gives_plan_6(data):
    late_kyo = stay("HTL-KYO-002", "RM-KYO-002-B", "Kyoto", "2027-04-04", "2027-04-06")
    assert rule_set(check_city_plan([TYO, late_kyo], "JP", START, 5, data)) == {"R-PLAN-4", "R-PLAN-6"}


def test_hotel_night_on_departure_day_gives_plan_7(data):
    long_kyo = stay("HTL-KYO-002", "RM-KYO-002-B", "Kyoto", "2027-04-03", "2027-04-06")
    assert rule_set(check_city_plan([TYO, long_kyo], "JP", START, 4, data)) == {"R-PLAN-4", "R-PLAN-7"}


# --- R-HTL: hotels, rooms, capacity, availability ---

def test_family_room_fits_two_adults_and_a_child_in_one_room(data):
    assert check_hotels([TYO], Party(2, (5,)), data) == []


@pytest.mark.parametrize("rooms, expected", [(1, {"R-HTL-5"}), (2, set())])
def test_two_twin_rooms_needed_for_two_adults_and_a_child(data, rooms, expected):
    s = stay("HTL-TYO-001", "RM-TYO-001-A", "Tokyo", "2027-04-01", "2027-04-03", rooms)
    assert rule_set(check_hotels([s], Party(2, (5,)), data)) == expected


def test_adults_must_be_at_least_rooms(data):
    s = stay("HTL-TYO-001", "RM-TYO-001-A", "Tokyo", "2027-04-01", "2027-04-03", 3)
    assert rule_set(check_hotels([s], Party(2), data)) == {"R-HTL-5"}


def test_zero_availability_on_middle_night_gives_htl_6(data):
    # RM-TYO-001-A has rooms_left 0 on 2027-04-12 in the real data.
    s = stay("HTL-TYO-001", "RM-TYO-001-A", "Tokyo", "2027-04-11", "2027-04-13")
    v = check_hotels([s], Party(2), data)
    assert rule_set(v) == {"R-HTL-6"}
    assert len(v) == 1 and "2027-04-12" in v[0].message


def test_missing_availability_record_on_middle_night_gives_htl_6(data):
    s = stay("HTL-TYO-001", "RM-TYO-001-A", "Tokyo", "2027-04-11", "2027-04-13")
    avail = {k: v for k, v in data.indexes.availability_by_room_date.items()
             if k != ("RM-TYO-001-A", "2027-04-12")}
    patched = replace(data, indexes=replace(data.indexes, availability_by_room_date=avail))
    v = check_hotels([s], Party(2), patched)
    assert rule_set(v) == {"R-HTL-6"}
    assert len(v) == 1 and "2027-04-12" in v[0].message


def test_hotel_city_mismatch_gives_htl_2(data):
    s = stay("HTL-TYO-001", "RM-TYO-001-A", "Kyoto", "2027-04-01", "2027-04-03")
    assert rule_set(check_hotels([s], Party(2), data)) == {"R-HTL-2"}
