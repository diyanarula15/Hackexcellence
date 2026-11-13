import pytest

from app.catalog.load import load_catalog
from app.rules.common import Party
from app.rules.pricing import attraction_price, check_item_price, check_total, hotel_price, transfer_price


@pytest.fixture(scope="module")
def data():
    return load_catalog()


def rule_set(violations):
    return {v.rule for v in violations}


def test_child_price_zero_stays_zero():
    rec = {"price_per_person": {"amount": 1000, "currency": "INR"},
           "child_price": {"amount": 0, "currency": "INR"}}
    assert attraction_price(rec, Party(2, (5,))) == (3, 2000)


def test_missing_child_price_falls_back_to_adult_price():
    rec = {"price_per_person": {"amount": 1000, "currency": "INR"}}
    assert attraction_price(rec, Party(2, (5,))) == (3, 3000)


def test_hotel_price_two_rooms_three_nights(data):
    room = data.indexes.rooms_by_id["RM-TYO-001-A"]   # 6440 per night
    assert hotel_price(room, 2, 3) == (2, 6440 * 2 * 3)


def test_per_vehicle_five_travelers_max_four_gives_two_vehicles(data):
    transfer = data.indexes.transfers_by_id["TR-KIX-NMB-TAXI"]   # PER_VEHICLE, max 4, 9520
    assert transfer["pricing"] == "PER_VEHICLE" and transfer["max_passengers"] == 4
    assert transfer_price(transfer, Party(5)) == (2, 9520 * 2)


def test_wrong_item_price_gives_price_2():
    assert rule_set(check_item_price("ITEM-1", (3, 9000), 3, 8000)) == {"R-PRICE-2"}


def test_total_mismatch_gives_price_3():
    assert rule_set(check_total(100, 101)) == {"R-PRICE-3"}
