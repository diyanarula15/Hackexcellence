import copy
from datetime import date

from app.catalog.load import build_loaded, load_catalog, load_raw
from app.engine.constraints import HotelLock
from app.engine.hotels import (NO_HOTEL_AVAILABILITY, NO_HOTEL_CAPACITY, find_hotel_options,
                               hotel_failure_reason, min_rooms)
from app.lib.money import amount

# Tokyo 13-16 Apr: RM-TYO-001-B (family, 2 adults + 2 children) is available on every night.
CHECK_IN, CHECK_OUT = date(2027, 4, 13), date(2027, 4, 16)
NIGHTS = 3
FAMILY = "RM-TYO-001-B"
TWIN = "RM-TYO-001-A"


def _edited_catalog(edit):
    raw = copy.deepcopy(load_raw())
    edit(raw)
    return build_loaded(raw)


def _by_room(options):
    return {o.room_id: o for o in options}


def test_family_room_fits_two_adults_and_one_child_in_one_room():
    catalog = load_catalog()
    assert min_rooms(catalog.indexes.rooms_by_id[FAMILY], 2, 1) == 1
    opt = _by_room(find_hotel_options("Tokyo", CHECK_IN, CHECK_OUT, 2, 1, catalog)).get(FAMILY)
    assert opt is not None and opt.rooms == 1


def test_room_without_children_needs_two_rooms_for_two_adults_and_a_child():
    catalog = load_catalog()
    assert min_rooms(catalog.indexes.rooms_by_id[TWIN], 2, 1) == 2
    opt = _by_room(find_hotel_options("Tokyo", CHECK_IN, CHECK_OUT, 2, 1, catalog))[TWIN]
    assert opt.rooms == 2


def test_min_rooms_is_none_when_rooms_would_exceed_adults():
    room = {"max_adults": 1, "max_children": 1}
    assert min_rooms(room, 1, 3) is None
    assert min_rooms({"max_adults": 0, "max_children": 2}, 1, 0) is None


def test_insufficient_rooms_on_a_middle_night_excludes_the_option():
    def edit(raw):
        hits = [a for a in raw["availability"] if a["room_id"] == FAMILY and a["date"] == "2027-04-14"]
        assert len(hits) == 1
        hits[0]["rooms_left"] = 0

    options = find_hotel_options("Tokyo", CHECK_IN, CHECK_OUT, 2, 1, _edited_catalog(edit))
    assert FAMILY not in _by_room(options)


def test_missing_nightly_availability_record_excludes_the_option():
    def edit(raw):
        before = len(raw["availability"])
        raw["availability"] = [a for a in raw["availability"]
                               if not (a["room_id"] == FAMILY and a["date"] == "2027-04-14")]
        assert len(raw["availability"]) == before - 1

    options = find_hotel_options("Tokyo", CHECK_IN, CHECK_OUT, 2, 1, _edited_catalog(edit))
    assert FAMILY not in _by_room(options)


def test_hotel_with_two_room_types_gives_two_separate_options():
    catalog = load_catalog()
    options = find_hotel_options("Tokyo", date(2027, 4, 10), date(2027, 4, 13), 2, 1, catalog)
    rooms_by_hotel = {}
    for o in options:
        rooms_by_hotel.setdefault(o.hotel_id, set()).add(o.room_id)
    assert {"RM-TYO-004-A", "RM-TYO-004-B"} <= rooms_by_hotel["HTL-TYO-004"]


def test_locked_room_of_another_hotel_gives_no_options():
    catalog = load_catalog()
    assert find_hotel_options("Tokyo", CHECK_IN, CHECK_OUT, 2, 1, catalog,
                              locked=HotelLock("HTL-TYO-001", "RM-TYO-002-A")) == []


def test_locked_feasible_room_gives_exactly_that_option():
    catalog = load_catalog()
    options = find_hotel_options("Tokyo", CHECK_IN, CHECK_OUT, 2, 1, catalog,
                                 locked=HotelLock("HTL-TYO-001", FAMILY))
    assert [(o.hotel_id, o.room_id, o.rooms) for o in options] == [("HTL-TYO-001", FAMILY, 1)]


def test_total_price_is_nightly_price_times_rooms_times_nights():
    catalog = load_catalog()
    options = find_hotel_options("Tokyo", CHECK_IN, CHECK_OUT, 2, 1, catalog)
    assert options
    for o in options:
        room = catalog.indexes.rooms_by_id[o.room_id]
        assert o.total_price == amount(room["price_per_night"]) * o.rooms * NIGHTS
    keys = [(o.total_price, o.hotel_id, o.room_id) for o in options]
    assert keys == sorted(keys)


def test_failure_reason_is_none_when_an_option_exists():
    assert hotel_failure_reason("Tokyo", CHECK_IN, CHECK_OUT, 2, 1, load_catalog()) is None


def test_failure_reason_capacity_when_no_room_type_can_hold_the_party():
    def edit(raw):
        for r in raw["rooms"]:
            r["max_adults"] = 0
            r["max_children"] = 0

    catalog = _edited_catalog(edit)
    assert hotel_failure_reason("Tokyo", CHECK_IN, CHECK_OUT, 2, 1, catalog) == NO_HOTEL_CAPACITY


def test_failure_reason_availability_when_rooms_fit_but_none_are_free():
    def edit(raw):
        for a in raw["availability"]:
            a["rooms_left"] = 0

    catalog = _edited_catalog(edit)
    assert hotel_failure_reason("Tokyo", CHECK_IN, CHECK_OUT, 2, 1, catalog) == NO_HOTEL_AVAILABILITY
