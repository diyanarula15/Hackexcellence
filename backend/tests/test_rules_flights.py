from datetime import date

import pytest

from app.catalog.load import load_catalog
from app.rules.common import FlightSel, Party
from app.rules.flights import check_flights

PARTY = Party(2, (5,))          # 3 travelers
OUT_KIX = FlightSel(None, "FL-1002")   # BOM -> KIX, lands 2027-04-01 (5 seats)
IN_NRT = FlightSel(None, "FL-1041")    # NRT -> BOM, departs 2027-04-03 (4 seats)
START = date(2027, 4, 1)
END = date(2027, 4, 3)


@pytest.fixture(scope="module")
def data():
    return load_catalog()


def rule_set(violations):
    return {v.rule for v in violations}


def test_kix_serves_kyoto_and_different_return_airport_are_valid(data):
    # KIX serves Kyoto only through serves_cities; the return leaves NRT (not KIX) for Tokyo.
    v = check_flights([OUT_KIX, IN_NRT], "BOM", "JP", "Kyoto", "Tokyo", START, END, PARTY, data)
    assert v == []


@pytest.mark.parametrize("first_city, expected", [("Kyoto", set()), ("Tokyo", {"R-FLT-5"})])
def test_arrival_airport_must_serve_first_city(data, first_city, expected):
    v = check_flights([OUT_KIX, IN_NRT], "BOM", "JP", first_city, "Tokyo", START, END, PARTY, data)
    assert rule_set(v) == expected


def test_seat_shortage_for_three_travelers_gives_flt_3(data):
    # FL-403 has 2 seats; the party has 3 travelers.
    v = check_flights([FlightSel(None, "FL-403"), IN_NRT], "BLR", "JP", "Tokyo", "Tokyo",
                      date(2027, 4, 10), END, PARTY, data)
    assert "R-FLT-3" in rule_set(v)


def test_outbound_arrival_date_must_match_start_gives_flt_4(data):
    v = check_flights([OUT_KIX, IN_NRT], "BOM", "JP", "Kyoto", "Tokyo", date(2027, 4, 2), END, PARTY, data)
    assert rule_set(v) == {"R-FLT-4"}


def test_outbound_from_wrong_airport_gives_flt_2(data):
    # FL-1001 flies DEL -> HND (arrives 2027-04-01); the home airport is BOM.
    v = check_flights([FlightSel(None, "FL-1001"), IN_NRT], "BOM", "JP", "Tokyo", "Tokyo", START, END, PARTY, data)
    assert rule_set(v) == {"R-FLT-2"}
