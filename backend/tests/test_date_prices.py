"""Price Landscape (Phase 7A) service: date enumeration, interpretation, savings, calendar payload.

Mocked planners are used for everything except the one real-planner check at the end. Every test
passes an explicit cache (a fresh DatePriceCache or None), never the module-level CACHE.
"""

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.engine.build import (FOUND as PLAN_FOUND, INFEASIBLE as PLAN_INFEASIBLE, MINIMUM_COST,
                              OVER_BUDGET as PLAN_OVER_BUDGET, SEARCH_INCOMPLETE as PLAN_INCOMPLETE,
                              build_package)
from app.services.date_price_cache import DatePriceCache, requirements_key
from app.services.date_prices import (FOUND, INFEASIBLE, MAX_RANGE_DAYS, PLANNER_ERROR,
                                      SEARCH_INCOMPLETE, SEARCH_LIMIT, TIME_BUDGET, DatePriceResult,
                                      DateRangeError, build_calendar, calculate_date_price,
                                      calculate_proven_savings, calendar_payload, check_range,
                                      default_range, enumerate_valid_start_dates, interpret)
from synth import request, simple_world

REQS = requirements_key("HOM", "ZZ", 3, 2, [])


def catalog_with_window(first_night: str, last_departure: str):
    w = simple_world()
    w.rules["data_window"] = {"first_night": first_night, "last_departure": last_departure}
    return w.loaded()


def planned(total, *, status=PLAN_FOUND, complete=True, codes=(), package_total="same"):
    """A PlanningResult-shaped object. package_total='same' gives a package agreeing with the total."""
    package = None
    if package_total is not None:
        package = SimpleNamespace(total=total if package_total == "same" else package_total)
    return SimpleNamespace(status=status, package=package, cheapest_total=total, budget_remaining=None,
                           shortfall=None, reasons=[], search_complete=complete, reason_codes=list(codes),
                           stats=SimpleNamespace(combinations_evaluated=1))


class FakePlanner:
    """Records every call; answers with fn(request) -> PlanningResult-shaped object."""

    def __init__(self, fn):
        self.fn = fn
        self.calls = []

    def __call__(self, req, catalog, objective):
        self.calls.append({"start_date": req.start_date, "objective": objective, "request": req})
        return self.fn(req)


def proven(d, total, fp="fp", reqs=REQS):
    return DatePriceResult(d, FOUND, total, True, fp, reqs)


# ------------------------------------------------------------------ date enumeration

def test_single_valid_date_inside_window():
    cat = catalog_with_window("2027-04-01", "2027-04-20")
    req = request(nights=3)
    assert enumerate_valid_start_dates(req, cat, date(2027, 4, 10), date(2027, 4, 10)) == [date(2027, 4, 10)]


def test_range_starting_before_window_is_clipped_to_first_night():
    cat = catalog_with_window("2027-04-01", "2027-04-20")
    out = enumerate_valid_start_dates(request(nights=3), cat, date(2027, 3, 28), date(2027, 4, 3))
    assert out[0] == date(2027, 4, 1)
    assert out == [date(2027, 4, d) for d in range(1, 4)]


def test_range_ending_after_window_is_clipped():
    cat = catalog_with_window("2027-04-01", "2027-04-20")
    out = enumerate_valid_start_dates(request(nights=3), cat, date(2027, 4, 15), date(2027, 4, 30))
    # last departure 04-20, three nights: the latest valid start is 04-17
    assert out == [date(2027, 4, d) for d in range(15, 18)]


def test_trip_must_end_on_or_before_last_departure():
    cat = catalog_with_window("2027-04-01", "2027-04-20")
    out = enumerate_valid_start_dates(request(nights=3), cat, date(2027, 4, 17), date(2027, 4, 18))
    assert date(2027, 4, 17) in out            # 17 + 3 == 20 == last departure: included
    assert date(2027, 4, 18) not in out        # 18 + 3 == 21 > 20: excluded


@pytest.mark.parametrize("nights, expected_last_start", [(3, date(2027, 4, 17)), (10, date(2027, 4, 10))])
def test_last_valid_start_depends_on_nights(nights, expected_last_start):
    cat = catalog_with_window("2027-04-01", "2027-04-20")
    out = enumerate_valid_start_dates(request(nights=nights), cat, date(2027, 4, 1), date(2027, 4, 30))
    assert out[-1] == expected_last_start


def test_ten_nights_window_count():
    cat = catalog_with_window("2027-04-01", "2027-04-20")
    out = enumerate_valid_start_dates(request(nights=10), cat, date(2027, 4, 1), date(2027, 4, 30))
    assert len(out) == 10 and out[0] == date(2027, 4, 1) and out[-1] == date(2027, 4, 10)


def test_range_crossing_month_boundary():
    cat = catalog_with_window("2027-03-25", "2027-04-10")
    out = enumerate_valid_start_dates(request(nights=3), cat, date(2027, 3, 30), date(2027, 4, 3))
    assert out == [date(2027, 3, 30), date(2027, 3, 31), date(2027, 4, 1), date(2027, 4, 2), date(2027, 4, 3)]


def test_leap_year_day_is_enumerated():
    cat = catalog_with_window("2028-02-25", "2028-03-05")
    out = enumerate_valid_start_dates(request(nights=3), cat, date(2028, 2, 25), date(2028, 3, 5))
    assert date(2028, 2, 29) in out
    assert out[-1] == date(2028, 3, 2)


def test_year_boundary_is_enumerated():
    cat = catalog_with_window("2027-12-28", "2028-01-04")
    out = enumerate_valid_start_dates(request(nights=3), cat, date(2027, 12, 28), date(2028, 1, 4))
    # last departure 2028-01-04, three nights: the latest valid start is 2028-01-01
    assert out == [date(2027, 12, 28), date(2027, 12, 29), date(2027, 12, 30), date(2027, 12, 31),
                   date(2028, 1, 1)]


def test_reversed_range_raises():
    cat = catalog_with_window("2027-04-01", "2027-04-20")
    with pytest.raises(DateRangeError):
        enumerate_valid_start_dates(request(), cat, date(2027, 4, 10), date(2027, 4, 1))
    with pytest.raises(DateRangeError):
        check_range(date(2027, 4, 10), date(2027, 4, 1))


def test_check_range_rejects_more_than_max_days():
    start = date(2027, 4, 1)
    check_range(start, start + timedelta(days=MAX_RANGE_DAYS - 1))          # exactly the maximum: fine
    with pytest.raises(DateRangeError):
        check_range(start, start + timedelta(days=MAX_RANGE_DAYS))


def test_default_range_is_calendar_month_of_start():
    assert default_range(date(2027, 4, 10)) == (date(2027, 4, 1), date(2027, 4, 30))


def test_default_range_february_2028_has_29_days():
    assert default_range(date(2028, 2, 15)) == (date(2028, 2, 1), date(2028, 2, 29))


# ------------------------------------------------------------------ interpretation

def _interpret(result, d=date(2027, 4, 10)):
    return interpret(result, d, "fp", REQS)


def test_found_and_complete_is_proven_found():
    out = _interpret(planned(241500, status=PLAN_FOUND, complete=True))
    assert (out.status, out.min_total_inr, out.proven_minimum) == (FOUND, 241500, True)


def test_over_budget_and_complete_is_found_with_cheapest_total():
    out = _interpret(planned(300000, status=PLAN_OVER_BUDGET, complete=True))
    assert (out.status, out.min_total_inr, out.proven_minimum) == (FOUND, 300000, True)


def test_infeasible_and_complete_is_infeasible():
    out = _interpret(planned(None, status=PLAN_INFEASIBLE, complete=True, package_total=None))
    assert out.status == INFEASIBLE
    assert out.min_total_inr is None and out.proven_minimum is False


def test_search_incomplete_is_incomplete_with_no_price():
    out = _interpret(planned(None, status=PLAN_INCOMPLETE, complete=False, package_total=None))
    assert out.status == SEARCH_INCOMPLETE
    assert out.min_total_inr is None
    assert out.incomplete_reason == SEARCH_LIMIT


@pytest.mark.parametrize("mutate", [
    lambda r: setattr(r, "search_complete", None),
    lambda r: delattr(r, "search_complete"),
    lambda r: setattr(r, "search_complete", False),
    lambda r: setattr(r, "package", None),
    lambda r: setattr(r, "cheapest_total", None),
    lambda r: setattr(r, "cheapest_total", "241500"),
    lambda r: setattr(r, "cheapest_total", 241500.0),
    lambda r: setattr(r, "package", SimpleNamespace(total=999)),
], ids=["complete-None", "complete-missing", "complete-False", "package-None", "total-None",
        "total-str", "total-float", "package-total-differs"])
def test_found_looking_result_without_proof_is_never_proven(mutate):
    result = planned(241500, status=PLAN_FOUND, complete=True)
    mutate(result)
    out = _interpret(result)
    assert out.status == SEARCH_INCOMPLETE
    assert out.proven_minimum is False
    assert out.min_total_inr is None


@pytest.mark.parametrize("result", [
    planned(None, status=PLAN_INCOMPLETE, complete=False, package_total=None),
    planned(None, status=PLAN_INFEASIBLE, complete=True, package_total=None, codes=("INVALID_REQUEST",)),
], ids=["incomplete", "invalid-request"])
def test_incomplete_or_invalid_cell_has_null_total_not_zero(result):
    out = _interpret(result)
    assert out.status == SEARCH_INCOMPLETE
    assert out.min_total_inr is None


def test_infeasible_with_invalid_request_code_is_search_incomplete():
    out = _interpret(planned(None, status=PLAN_INFEASIBLE, complete=True, package_total=None,
                             codes=("INVALID_REQUEST", "R1")))
    assert out.status == SEARCH_INCOMPLETE


def test_planner_exception_is_search_incomplete_planner_error():
    def boom(req):
        raise RuntimeError("planner exploded")

    cache = DatePriceCache()
    out = calculate_date_price(request(), date(2027, 4, 10), simple_world().loaded(),
                               cache=cache, planner=boom)
    assert out.status == SEARCH_INCOMPLETE
    assert out.incomplete_reason == PLANNER_ERROR
    assert out.min_total_inr is None
    assert len(cache) == 0


def test_planner_always_gets_minimum_cost_and_a_copy_of_the_request():
    cat = simple_world().loaded()
    req = request(start=date(2027, 4, 10))
    before = dict(vars(req))
    fake = FakePlanner(lambda r: planned(1500))

    out = calculate_date_price(req, date(2027, 4, 5), cat, cache=None, planner=fake)

    assert out.status == FOUND
    assert len(fake.calls) == 1
    assert fake.calls[0]["objective"] == MINIMUM_COST
    assert fake.calls[0]["start_date"] == date(2027, 4, 5)
    assert fake.calls[0]["request"] is not req
    assert dict(vars(req)) == before
    assert req.start_date == date(2027, 4, 10)


# ------------------------------------------------------------------ savings

def test_positive_saving():
    ref = proven(date(2027, 4, 10), 241500)
    alt = proven(date(2027, 4, 2), 218700)
    assert calculate_proven_savings(ref, alt) == 22800


def test_zero_saving_when_equal():
    assert calculate_proven_savings(proven(date(2027, 4, 10), 1000), proven(date(2027, 4, 2), 1000)) == 0


def test_alternative_dearer_is_negative():
    assert calculate_proven_savings(proven(date(2027, 4, 10), 1000), proven(date(2027, 4, 2), 1300)) == -300


def test_reference_infeasible_gives_none():
    ref = DatePriceResult(date(2027, 4, 10), INFEASIBLE, None, False, "fp", REQS)
    assert calculate_proven_savings(ref, proven(date(2027, 4, 2), 1000)) is None


def test_alternative_search_incomplete_gives_none():
    alt = DatePriceResult(date(2027, 4, 2), SEARCH_INCOMPLETE, None, False, "fp", REQS, SEARCH_LIMIT)
    assert calculate_proven_savings(proven(date(2027, 4, 10), 1000), alt) is None


def test_different_requirements_or_fingerprint_gives_none():
    ref = proven(date(2027, 4, 10), 1000)
    other_reqs = requirements_key("HOM", "ZZ", 3, 3, [])
    assert calculate_proven_savings(ref, proven(date(2027, 4, 2), 900, reqs=other_reqs)) is None
    assert calculate_proven_savings(ref, proven(date(2027, 4, 2), 900, fp="other")) is None


# ------------------------------------------------------------------ calendar

def _calendar_world():
    w = simple_world()
    w.rules["data_window"] = {"first_night": "2027-04-01", "last_departure": "2027-04-30"}
    return w.loaded()


def test_calendar_with_some_incomplete_dates_is_not_fully_evaluated():
    cat = _calendar_world()

    def fn(req):
        day = req.start_date.day
        if day % 5 == 0:
            return planned(None, status=PLAN_INCOMPLETE, complete=False, package_total=None)
        return planned(1000 + day)

    cal = build_calendar(request(start=date(2027, 4, 10)), cat, cache=DatePriceCache(),
                         planner=FakePlanner(fn))
    payload = calendar_payload(cal, cat)

    assert payload["range_fully_evaluated"] is False
    assert payload["cheapest_date"] is None and payload["cheapest_total_inr"] is None
    assert payload["lowest_proven_date"] == "2027-04-01"
    assert payload["lowest_proven_total_inr"] == 1001
    assert payload["status_counts"][SEARCH_INCOMPLETE] == 5
    incomplete = [c for c in payload["dates"] if c["status"] == SEARCH_INCOMPLETE]
    assert all(c["min_total_inr"] is None and c["incomplete_reason"] == SEARCH_LIMIT for c in incomplete)


def test_equal_minimum_on_several_dates_picks_earliest():
    cat = _calendar_world()
    cal = build_calendar(request(start=date(2027, 4, 10)), cat, cache=DatePriceCache(),
                         planner=FakePlanner(lambda r: planned(1500)))
    payload = calendar_payload(cal, cat)
    assert payload["range_fully_evaluated"] is True
    assert payload["lowest_proven_date"] == "2027-04-01"
    assert payload["cheapest_date"] == "2027-04-01"


def test_calendar_payload_shape_is_chronological_with_int_or_null_prices():
    cat = _calendar_world()
    cal = build_calendar(request(start=date(2027, 4, 10)), cat, cache=DatePriceCache(),
                         planner=FakePlanner(lambda r: planned(1000 + r.start_date.day)))
    payload = calendar_payload(cal, cat)
    dates = [c["date"] for c in payload["dates"]]
    assert dates == sorted(dates)
    assert dates[0] == "2027-04-01" and dates[-1] == "2027-04-27"
    assert all(c["min_total_inr"] is None or isinstance(c["min_total_inr"], int) for c in payload["dates"])


def test_comparison_uses_only_proven_minima():
    cat = _calendar_world()

    def fn(req):
        if req.start_date.day == 10:              # the reference date: FOUND but without proof
            return planned(1500, complete=False)
        return planned(1200)

    cal = build_calendar(request(start=date(2027, 4, 10)), cat, cache=DatePriceCache(),
                         planner=FakePlanner(fn))
    payload = calendar_payload(cal, cat)
    assert payload["comparison"]["reference_min_total_inr"] is None
    assert payload["comparison"]["max_proven_savings_inr"] is None
    assert all(c["proven_savings_inr"] is None for c in payload["dates"])


def test_zero_time_budget_marks_uncomputed_dates_time_budget():
    cat = _calendar_world()
    fake = FakePlanner(lambda r: planned(1500))
    cal = build_calendar(request(start=date(2027, 4, 10)), cat, cache=DatePriceCache(),
                         planner=fake, time_budget_s=0)
    payload = calendar_payload(cal, cat)
    assert fake.calls == []
    assert payload["status_counts"][SEARCH_INCOMPLETE] == len(payload["dates"])
    assert all(c["incomplete_reason"] == TIME_BUDGET for c in payload["dates"])
    assert payload["range_fully_evaluated"] is False


# ------------------------------------------------------------------ real planner, no mocks

def test_real_planner_on_simple_world_matches_minimum_cost_search():
    cat = simple_world().loaded()
    req = request(nights=3, start=date(2027, 4, 10))
    out = calculate_date_price(req, date(2027, 4, 10), cat, cache=None, planner=build_package)
    assert out.status == FOUND and out.proven_minimum is True
    expected = build_package(req, cat, objective=MINIMUM_COST)
    assert expected.status == PLAN_FOUND
    assert out.min_total_inr == expected.cheapest_total
