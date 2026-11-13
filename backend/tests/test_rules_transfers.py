from datetime import datetime, timedelta

import pytest

from app.catalog.load import load_catalog
from app.lib.time import in_window
from app.rules.common import TransferSel
from app.rules.transfers import check_airport_transfers

DEP_DAY = datetime(2027, 4, 2, 13, 0)   # KIX -> BOM departure (FL-1021)


@pytest.fixture(scope="module")
def data():
    return load_catalog()


def dt(s):
    return datetime.fromisoformat(s)


def rule_set(violations):
    return {v.rule for v in violations}


def run(data, arr_tid="TR-KIX-NMB-TAXI", arr_at="2027-04-01T10:50", dep_tid="TR-KIX-NMB-TAXI",
        dep_at="2027-04-02T07:30", hotel="HTL-OSA-001", dep_hotel=None):
    ix = data.indexes
    arrival = [TransferSel(None, arr_tid, dt(arr_at))]
    departure = [TransferSel(None, dep_tid, dt(dep_at))]
    return check_airport_transfers(
        arrival, departure,
        ix.flights_by_id["FL-1002"], ix.flights_by_id["FL-1021"],
        ix.hotels_by_id[hotel], ix.hotels_by_id[dep_hotel or hotel], data)


# --- R-ATR-5: arrival pickup timing (FL-1002 lands KIX 2027-04-01 09:50) ---

@pytest.mark.parametrize("pickup, expected", [("2027-04-01T10:49", {"R-ATR-5"}), ("2027-04-01T10:50", set())])
def test_arrival_pickup_at_least_60_minutes_after_landing(data, pickup, expected):
    assert rule_set(run(data, arr_at=pickup)) == expected


# --- R-ATR-7: departure transfer must end 180 minutes before the flight ---

@pytest.mark.parametrize("minutes_before, expected", [(181, set()), (180, set()), (179, {"R-ATR-7"})])
def test_departure_transfer_ends_180_minutes_before_flight(data, minutes_before, expected):
    duration = data.indexes.transfers_by_id["TR-KIX-NMB-TAXI"]["duration_minutes"]
    pickup = DEP_DAY - timedelta(minutes=minutes_before + duration)
    assert rule_set(run(data, dep_at=pickup.isoformat())) == expected


# --- R-ATR-6: service window, including overnight and 24:00 ---

@pytest.mark.parametrize("start, until, when, expected", [
    ("06:00", "00:30", datetime(2027, 4, 2, 0, 30), True),
    ("06:00", "00:30", datetime(2027, 4, 2, 0, 31), False),
    ("06:00", "00:30", datetime(2027, 4, 2, 5, 59), False),
    ("00:00", "24:00", datetime(2027, 4, 2, 23, 59), True),
    ("00:00", "24:00", datetime(2027, 4, 2, 0, 0), True),
])
def test_in_window(start, until, when, expected):
    assert in_window(when, start, until) is expected


# --- R-ATR-4: transfer must serve the hotel's city and area ---

def test_transfer_area_differs_from_hotel_area_gives_atr_4(data):
    # TR-KIX-NMB-TAXI serves Namba; HTL-OSA-003 is in Umeda. Departure uses the Umeda taxi.
    v = run(data, arr_at="2027-04-01T10:50", hotel="HTL-OSA-003", dep_tid="TR-KIX-UMD-TAXI")
    assert rule_set(v) == {"R-ATR-4"}


def test_transfer_with_null_area_does_not_check_area(data):
    # TR-KIX-KYO-TAXI has area null, so any Kyoto hotel area is accepted.
    v = run(data, arr_tid="TR-KIX-KYO-TAXI", dep_tid="TR-KIX-KYO-TAXI", hotel="HTL-KYO-001")
    assert v == []
