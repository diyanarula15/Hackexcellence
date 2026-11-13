from datetime import date, datetime
from types import SimpleNamespace

from app.catalog.load import load_catalog
from app.engine.flights import (compatible_arrivals, compatible_returns, find_arrival_flights,
                                find_return_flights)
from app.engine.model import CityPlan, CityStay

ARRIVAL_DAY = date(2027, 4, 10)


def request(**overrides):
    base = dict(departure_airport="BLR", destination_country="JP", start_date=ARRIVAL_DAY,
                nights=6, adults=2, children_ages=[6], budget=0)
    base.update(overrides)
    return SimpleNamespace(**base)


def ids(options):
    return [f.flight_id for f in options]


def test_arrival_flights_land_on_start_date_from_home_with_enough_seats():
    catalog = load_catalog()
    flights = find_arrival_flights(request(), catalog)
    assert flights, "BLR to Japan on the start date should have candidates"
    for f in flights:
        rec = catalog.indexes.flights_by_id[f.flight_id]
        assert f.from_airport == "BLR"
        assert f.arrival.date() == ARRIVAL_DAY
        assert rec["seats_left"] >= 3
        assert f.quantity == 3  # 2 adults + 1 child
        assert f.price == 3 * int(rec["price_per_seat"]["amount"])


def test_flight_with_too_few_seats_is_excluded_unless_ignore_seats():
    catalog = load_catalog()
    assert catalog.indexes.flights_by_id["FL-403"]["seats_left"] == 2
    assert "FL-403" not in ids(find_arrival_flights(request(), catalog))
    assert "FL-403" in ids(find_arrival_flights(request(), catalog, ignore_seats=True))


def test_overnight_flight_departing_previous_day_is_included():
    catalog = load_catalog()
    fl = next(f for f in find_arrival_flights(request(), catalog) if f.flight_id == "FL-401")
    assert fl.departure.date() == date(2027, 4, 9)
    assert fl.arrival.date() == ARRIVAL_DAY


def test_return_flights_depart_on_end_date_and_land_at_home_airport():
    catalog = load_catalog()
    flights = find_return_flights(request(), catalog)  # end = 2027-04-16
    assert "FL-411" in ids(flights)  # KIX -> BLR
    for f in flights:
        assert f.departure.date() == date(2027, 4, 16)
        assert f.to_airport == "BLR"
        assert f.from_airport in {a["code"] for a in catalog.catalog.airports if a["country"] == "JP"}


def test_compatible_arrivals_for_kyoto_keep_kix_and_drop_tokyo_airports():
    catalog = load_catalog()
    start = date(2027, 4, 1)  # BLR -> KIX (FL-702) and BLR -> NRT (FL-701) both land here
    flights = find_arrival_flights(request(start_date=start), catalog, ignore_seats=True)
    assert {"FL-702", "FL-701"} <= set(ids(flights))
    plan = CityPlan("JP", (CityStay("Kyoto", start, date(2027, 4, 4)),))
    kept = ids(compatible_arrivals(plan, flights, catalog))
    assert "FL-702" in kept
    assert "FL-701" not in kept
    assert all(catalog.indexes.flights_by_id[i]["to"] == "KIX" for i in kept)


def test_arrival_and_return_airports_may_differ():
    catalog = load_catalog()
    arrivals = find_arrival_flights(request(), catalog)
    returns = find_return_flights(request(), catalog)
    tokyo_plan = CityPlan("JP", (CityStay("Tokyo", ARRIVAL_DAY, date(2027, 4, 13)),
                                 CityStay("Kyoto", date(2027, 4, 13), date(2027, 4, 16))))
    arrival = next(f for f in compatible_arrivals(tokyo_plan, arrivals, catalog) if f.flight_id == "FL-401")
    ret = next(f for f in compatible_returns(tokyo_plan, returns, catalog) if f.flight_id == "FL-411")
    assert arrival.to_airport == "NRT"
    assert ret.from_airport == "KIX"
    assert arrival.to_airport != ret.from_airport


def test_candidates_are_sorted_by_price_then_flight_id():
    catalog = load_catalog()
    for flights in (find_arrival_flights(request(), catalog, ignore_seats=True),
                    find_return_flights(request(), catalog, ignore_seats=True)):
        keys = [(f.price, f.flight_id) for f in flights]
        assert keys == sorted(keys)
