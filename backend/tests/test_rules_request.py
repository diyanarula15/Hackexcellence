import pytest

from app.catalog.load import load_catalog
from app.rules.request import check_request


@pytest.fixture(scope="module")
def data():
    return load_catalog()


def base(**over):
    req = {"departure_airport": "BOM", "destination_country": "JP", "start_date": "2027-04-01",
           "nights": 3, "adults": 2, "children_ages": [], "budget": 100000}
    req.update(over)
    return req


def rules(req, data):
    return {v.rule for v in check_request(req, data)}


def test_valid_request_has_no_violations(data):
    assert check_request(base(), data) == []


@pytest.mark.parametrize("nights, expected", [(2, {"R-REQ-3"}), (3, set()), (10, set()), (11, {"R-REQ-3"})])
def test_nights_range(data, nights, expected):
    assert rules(base(nights=nights), data) == expected


@pytest.mark.parametrize("airport, expected", [("BOM", set()), ("XYZ", {"R-REQ-1"})])
def test_departure_airport(data, airport, expected):
    assert rules(base(departure_airport=airport), data) == expected


@pytest.mark.parametrize("country, expected", [("JP", set()), ("japan", set()), ("FR", {"R-REQ-2"})])
def test_destination_country(data, country, expected):
    assert rules(base(destination_country=country), data) == expected


@pytest.mark.parametrize("ages, expected", [([0], set()), ([17], set()), ([18], {"R-REQ-7"})])
def test_child_ages(data, ages, expected):
    assert rules(base(children_ages=ages), data) == expected


def test_zero_adults_is_rejected(data):
    assert rules(base(adults=0), data) == {"R-REQ-6"}


@pytest.mark.parametrize("start, expected", [("2027-04-01", set()), ("2027-03-31", {"R-REQ-4"})])
def test_start_date_window_opening(data, start, expected):
    assert rules(base(start_date=start), data) == expected


@pytest.mark.parametrize("start, expected", [("2027-04-17", set()), ("2027-04-18", {"R-REQ-5"})])
def test_return_date_window_closing(data, start, expected):
    # start + 3 nights returns 2027-04-20 (ok) or 2027-04-21 (after the last departure).
    assert rules(base(start_date=start, nights=3), data) == expected
