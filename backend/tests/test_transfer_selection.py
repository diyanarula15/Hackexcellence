"""Phase 3 transfer candidates (app/engine/transfers.py). Real catalog records where the data has the
case; hand-made flights, hotels and edited catalog copies for edge cases the data lacks."""
import copy
from datetime import date, datetime, timedelta

import pytest

from app.catalog.load import build_loaded, load_catalog, load_raw
from app.engine.constraints import TransferLock
from app.engine.model import ARRIVAL_LEG, DEPARTURE_LEG, FlightOption, HotelOption, intercity_leg_id
from app.engine.transfers import find_arrival_transfers, find_intercity_transfers, find_return_transfers
from app.lib.time import parse_dt
from app.rules import pricing
from app.rules.common import Party, Stay, TransferSel
from app.rules.intercity import check_intercity
from app.rules.transfers import check_airport_transfers

PARTY = Party(adults=2, child_ages=(6,))          # 3 travelers
DAY = date(2027, 4, 13)                           # intercity day used below


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


def dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def ids(options) -> set[str]:
    return {o.transfer_id for o in options}


def by_id(options) -> dict:
    return {o.transfer_id: o for o in options}


def flight(cat, fid: str) -> FlightOption:
    rec = cat.indexes.flights_by_id[fid]
    q, p = pricing.flight_price(rec, PARTY)
    return FlightOption(fid, rec["from"], rec["to"], parse_dt(rec["departure_local"]),
                        parse_dt(rec["arrival_local"]), q, p)


def hotel(cat, hid: str) -> HotelOption:
    h = cat.indexes.hotels_by_id[hid]
    return HotelOption(stay_id="stay:test", hotel_id=hid, room_id="", city=h["city"], area=h["area"],
                       check_in=date(2027, 4, 1), check_out=date(2027, 4, 3), rooms=1, total_price=0)


def landing(airport: str, when: str) -> FlightOption:
    """Hand-made arrival at `airport` (not in the catalog)."""
    arr = dt(when)
    return FlightOption("FL-TEST-IN", "BOM", airport, arr - timedelta(hours=10), arr, 3, 0)


def departure(airport: str, when: str) -> FlightOption:
    """Hand-made return leaving `airport` (not in the catalog)."""
    dep = dt(when)
    return FlightOption("FL-TEST-OUT", airport, "BOM", dep, dep + timedelta(hours=10), 3, 0)


def edited_catalog(transfer_id: str, **fields):
    """A modified catalog: one transfer record's fields replaced. The shared catalog is never touched."""
    raw = copy.deepcopy(load_raw())
    rec = next(t for t in raw["transfers"] if t["transfer_id"] == transfer_id)
    rec.update(fields)
    return build_loaded(copy.deepcopy(raw))


def _room(cat, hid: str) -> str:
    return cat.indexes.rooms_by_hotel[hid][0]["room_id"]


def check_arrival(cat, opt, flight_id: str, hotel_id: str):
    """Phase 2 check of one arrival option. The return leg is not part of this option, so the only
    R-ATR-1 expected is the missing departure transfer."""
    sel = TransferSel(None, opt.transfer_id, opt.pickup)
    vs = check_airport_transfers([sel], [], cat.indexes.flights_by_id[flight_id], None,
                                 cat.indexes.hotels_by_id[hotel_id], None, cat)
    assert len([v for v in vs if v.rule == "R-ATR-1"]) == 1
    assert [v for v in vs if v.rule != "R-ATR-1"] == []


def check_return(cat, opt, flight_id: str, hotel_id: str):
    """Phase 2 check of one return option (the arrival leg is absent, so only its R-ATR-1 is ignored)."""
    sel = TransferSel(None, opt.transfer_id, opt.pickup)
    vs = check_airport_transfers([], [sel], None, cat.indexes.flights_by_id[flight_id], None,
                                 cat.indexes.hotels_by_id[hotel_id], cat)
    assert len([v for v in vs if v.rule == "R-ATR-1"]) == 1
    assert [v for v in vs if v.rule != "R-ATR-1"] == []


# --- arrival -------------------------------------------------------------------------------------

def test_arrival_serves_airport_city_and_area(cat):
    fl = flight(cat, "FL-1002")                    # lands KIX 2027-04-01 09:50
    namba = find_arrival_transfers(fl, hotel(cat, "HTL-OSA-001"), PARTY, cat)   # Osaka / Namba
    assert ids(namba) == {"TR-KIX-NMB-TAXI", "TR-KIX-NMB-SHUTTLE"}
    kyoto = find_arrival_transfers(fl, hotel(cat, "HTL-KYO-004"), PARTY, cat)   # area null serves all
    assert ids(kyoto) == {"TR-KIX-KYO-TAXI", "TR-KIX-KYO-BUS"}


def test_arrival_pickup_exactly_60_minutes_after_landing_when_open(cat):
    fl = flight(cat, "FL-1002")                    # earliest pickup 10:50, taxi open 06:00-23:00
    opt = by_id(find_arrival_transfers(fl, hotel(cat, "HTL-OSA-001"), PARTY, cat))["TR-KIX-NMB-TAXI"]
    assert opt.pickup == dt("2027-04-01T10:50")
    assert opt.arrive == dt("2027-04-01T11:40")
    assert opt.leg_id == ARRIVAL_LEG


def test_arrival_waits_for_service_to_open_next_day(cat):
    fl = landing("KIX", "2027-04-01T23:30")         # earliest 00:30 on 2 Apr; Umeda buses open 06:00/06:30
    opts = by_id(find_arrival_transfers(fl, hotel(cat, "HTL-OSA-003"), PARTY, cat))
    assert opts["TR-KIX-UMD-TAXI"].pickup == dt("2027-04-02T06:00")
    assert opts["TR-KIX-UMD-BUS"].pickup == dt("2027-04-02T06:30")
    for o in opts.values():
        assert o.pickup - fl.arrival <= timedelta(hours=24)


def test_arrival_overnight_window_and_24h_boundaries(cat):
    # 06:00-00:30 shuttle: a landing at 23:30 is picked up exactly at 00:30 (window end inclusive).
    fl = landing("KIX", "2027-04-01T23:30")
    shuttle = by_id(find_arrival_transfers(fl, hotel(cat, "HTL-OSA-001"), PARTY, cat))["TR-KIX-NMB-SHUTTLE"]
    assert shuttle.pickup == dt("2027-04-02T00:30")
    # 05:00-24:00 taxi: a landing at 23:00 is picked up at 00:00 (the 24:00 boundary is included).
    fl = landing("HND", "2027-04-01T23:00")
    taxi = by_id(find_arrival_transfers(fl, hotel(cat, "HTL-TYO-001"), PARTY, cat))["TR-HND-GNZ-TAXI"]
    assert taxi.pickup == dt("2027-04-02T00:00")


def test_arrival_drops_record_that_never_opens_within_24h(cat):
    # Edited copy: the Umeda bus only runs 12:00-12:30. Landing 11:50 -> earliest 12:50, and the next
    # opening (12:00 on 2 Apr) is after the 24 h limit (11:50 on 2 Apr).
    ecat = edited_catalog("TR-KIX-UMD-BUS", service_from="12:00", service_until="12:30")
    opts = find_arrival_transfers(landing("KIX", "2027-04-01T11:50"), hotel(ecat, "HTL-OSA-003"), PARTY, ecat)
    assert ids(opts) == {"TR-KIX-UMD-TAXI"}


def test_arrival_price_uses_vehicles_rounded_up(cat):
    fl = flight(cat, "FL-1002")
    five = Party(adults=4, child_ages=(5,))        # 5 travelers, taxi carries 4 -> 2 vehicles
    opt = by_id(find_arrival_transfers(fl, hotel(cat, "HTL-OSA-001"), five, cat))["TR-KIX-NMB-TAXI"]
    assert (opt.quantity, opt.price) == (2, 2 * 9520)
    opt = by_id(find_arrival_transfers(fl, hotel(cat, "HTL-OSA-001"), PARTY, cat))["TR-KIX-NMB-TAXI"]
    assert (opt.quantity, opt.price) == (1, 9520)


@pytest.mark.parametrize("flight_id, hotel_id", [("FL-1002", "HTL-OSA-001"), ("FL-1002", "HTL-KYO-004"),
                                                 ("FL-401", "HTL-TYO-004")])
def test_arrival_options_pass_phase2(cat, flight_id, hotel_id):
    opts = find_arrival_transfers(flight(cat, flight_id), hotel(cat, hotel_id), PARTY, cat)
    assert opts
    for o in opts:
        check_arrival(cat, o, flight_id, hotel_id)


# --- return --------------------------------------------------------------------------------------

def test_return_pickup_equality_when_service_open(cat):
    fl = flight(cat, "FL-411")                     # leaves KIX 2027-04-16 12:00; latest arrival 09:00
    opts = by_id(find_return_transfers(fl, hotel(cat, "HTL-KYO-004"), PARTY, cat))
    bus = opts["TR-KIX-KYO-BUS"]                   # 100 min -> pickup 07:20 ends 09:00 exactly
    assert bus.pickup == dt("2027-04-16T07:20")
    assert bus.arrive == dt("2027-04-16T09:00")
    assert opts["TR-KIX-KYO-TAXI"].pickup == dt("2027-04-16T07:30")   # 90 min
    assert bus.leg_id == DEPARTURE_LEG
    for o in opts.values():
        assert o.pickup.date() == fl.departure.date()


def test_return_drops_record_when_service_opens_too_late(cat):
    fl = departure("KIX", "2027-04-16T08:00")      # latest arrival 05:00: buses open at 06:30
    assert find_return_transfers(fl, hotel(cat, "HTL-KYO-004"), PARTY, cat) == []


def test_return_overnight_window_allows_pickup_after_midnight(cat):
    fl = departure("KIX", "2027-04-16T05:00")      # latest arrival 02:00 on 16 Apr
    opts = find_return_transfers(fl, hotel(cat, "HTL-OSA-001"), PARTY, cat)
    assert ids(opts) == {"TR-KIX-NMB-SHUTTLE"}     # the taxi (06:00 start) cannot make the deadline
    assert opts[0].pickup == dt("2027-04-16T00:30")
    assert opts[0].pickup.date() == fl.departure.date()


@pytest.mark.parametrize("flight_id, hotel_id", [("FL-411", "HTL-KYO-004"), ("FL-411", "HTL-KYO-001")])
def test_return_options_pass_phase2(cat, flight_id, hotel_id):
    opts = find_return_transfers(flight(cat, flight_id), hotel(cat, hotel_id), PARTY, cat)
    assert opts
    for o in opts:
        check_return(cat, o, flight_id, hotel_id)


# --- intercity -----------------------------------------------------------------------------------

def test_intercity_valid_directed_transfer(cat):
    opts = find_intercity_transfers("Tokyo", "Kyoto", DAY, PARTY, cat)
    assert len(opts) == 1
    o = opts[0]
    assert o.transfer_id == "TR-TYO-KYO-01"
    assert o.pickup == dt("2027-04-13T10:00")      # default prefer, on the 30-minute slot grid
    assert o.arrive == dt("2027-04-13T12:15")
    assert o.leg_id == intercity_leg_id("Tokyo", "Kyoto", DAY)


def test_intercity_direction_and_unlinked_pairs(cat):
    back = find_intercity_transfers("Kyoto", "Tokyo", DAY, PARTY, cat)
    assert ids(back) == {"TR-KYO-TYO-01"}          # reverse pair uses the other record
    assert find_intercity_transfers("Tokyo", "Dubai", DAY, PARTY, cat) == []


@pytest.mark.parametrize("prefer, expected", [
    ("10:20", "2027-04-13T10:30"),                 # between slots: nearest slot wins
    ("10:10", "2027-04-13T10:00"),
    ("10:00", "2027-04-13T10:00"),
    ("23:50", "2027-04-13T21:30"),                 # after the last slot: fall back to a valid slot
    ("04:00", "2027-04-13T06:00"),                 # before the first slot
])
def test_intercity_snaps_preferred_time_to_slot(cat, prefer, expected):
    opt = find_intercity_transfers("Tokyo", "Kyoto", DAY, PARTY, cat, prefer=prefer)[0]
    assert opt.pickup == dt(expected)
    assert (opt.pickup.minute % 30) == 0


def test_intercity_locked_pickup_between_slots_is_rejected(cat):
    lock = TransferLock("TR-TYO-KYO-01", pickup=dt("2027-04-13T10:15"))
    assert find_intercity_transfers("Tokyo", "Kyoto", DAY, PARTY, cat, locked=lock) == []
    ok = TransferLock("TR-TYO-KYO-01", pickup=dt("2027-04-13T10:30"))
    assert [o.pickup for o in find_intercity_transfers("Tokyo", "Kyoto", DAY, PARTY, cat, locked=ok)] == [
        dt("2027-04-13T10:30")]


def test_intercity_late_slot_crossing_midnight(cat):
    opts = by_id(find_intercity_transfers("Dubai", "Abu Dhabi", DAY, PARTY, cat, prefer="23:30"))
    bus = opts["TR-DXB-AUH-BUS"]                   # 05:30-23:30 every 30 min, 150 min trip
    assert bus.pickup == dt("2027-04-13T23:30")
    assert bus.arrive == dt("2027-04-14T02:00")
    assert bus.arrive.date() == DAY + timedelta(days=1)


def test_intercity_taxi_without_frequency_accepts_preferred_time(cat):
    opts = by_id(find_intercity_transfers("Dubai", "Abu Dhabi", DAY, PARTY, cat, prefer="12:34"))
    assert opts["TR-DXB-AUH-TAXI"].pickup == dt("2027-04-13T12:34")
    assert opts["TR-DXB-AUH-BUS"].pickup == dt("2027-04-13T12:30")   # the bus snaps to its slot


STAY_HOTELS = {"Tokyo": "HTL-TYO-004", "Kyoto": "HTL-KYO-004", "Dubai": "HTL-DXB-001", "Abu Dhabi": "HTL-AUH-001"}


@pytest.mark.parametrize("from_city, to_city, prefer", [("Tokyo", "Kyoto", "10:00"),
                                                        ("Tokyo", "Kyoto", "23:50"),
                                                        ("Dubai", "Abu Dhabi", "23:30"),
                                                        ("Dubai", "Abu Dhabi", "12:34")])
def test_intercity_options_pass_phase2(cat, from_city, to_city, prefer):
    opts = find_intercity_transfers(from_city, to_city, DAY, PARTY, cat, prefer=prefer)
    assert opts
    stays = [Stay(None, STAY_HOTELS[from_city], _room(cat, STAY_HOTELS[from_city]), from_city,
                  DAY - timedelta(days=3), DAY, 1),
             Stay(None, STAY_HOTELS[to_city], _room(cat, STAY_HOTELS[to_city]), to_city,
                  DAY, DAY + timedelta(days=3), 1)]
    for o in opts:
        assert check_intercity([TransferSel(None, o.transfer_id, o.pickup)], stays, cat) == []


# --- locks ---------------------------------------------------------------------------------------

def test_locked_arrival_returns_only_that_record(cat):
    fl, hot = flight(cat, "FL-1002"), hotel(cat, "HTL-OSA-001")
    assert ids(find_arrival_transfers(fl, hot, PARTY, cat, locked=TransferLock("TR-KIX-NMB-TAXI"))) == {
        "TR-KIX-NMB-TAXI"}
    assert find_arrival_transfers(fl, hot, PARTY, cat, locked=TransferLock("TR-KIX-KYO-TAXI")) == []
    early = TransferLock("TR-KIX-NMB-TAXI", pickup=dt("2027-04-01T10:00"))   # before landing + 60
    assert find_arrival_transfers(fl, hot, PARTY, cat, locked=early) == []


def test_locked_return_returns_only_that_record(cat):
    fl, hot = flight(cat, "FL-411"), hotel(cat, "HTL-KYO-004")
    assert ids(find_return_transfers(fl, hot, PARTY, cat, locked=TransferLock("TR-KIX-KYO-BUS"))) == {
        "TR-KIX-KYO-BUS"}
    assert find_return_transfers(fl, hot, PARTY, cat, locked=TransferLock("TR-KIX-NMB-TAXI")) == []


def test_locked_intercity_returns_only_that_record(cat):
    assert ids(find_intercity_transfers("Tokyo", "Kyoto", DAY, PARTY, cat,
                                        locked=TransferLock("TR-TYO-KYO-01"))) == {"TR-TYO-KYO-01"}
    assert find_intercity_transfers("Tokyo", "Kyoto", DAY, PARTY, cat,
                                    locked=TransferLock("TR-KYO-TYO-01")) == []
