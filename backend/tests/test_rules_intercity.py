from datetime import date, datetime, time, timedelta

import pytest

from app.catalog.load import load_catalog
from app.rules.attractions import check_attractions
from app.rules.common import EDITED, Busy, Stay, TransferSel, Visit
from app.rules.intercity import check_intercity


@pytest.fixture(scope="module")
def data():
    return load_catalog()


def rule_set(violations):
    return {v.rule for v in violations}


TYO = Stay(None, "HTL-TYO-001", "RM-TYO-001-A", "Tokyo", date(2027, 4, 1), date(2027, 4, 3), 1)
KYO = Stay(None, "HTL-KYO-002", "RM-KYO-002-A", "Kyoto", date(2027, 4, 3), date(2027, 4, 5), 1)
STAYS = [TYO, KYO]
TYO_TO_KYO = "TR-TYO-KYO-01"   # 06:00-21:30, every 30 minutes, 135 minutes
DAY = date(2027, 4, 3)


def move(tid, clock, day=DAY):
    return TransferSel(None, tid, datetime.combine(day, time.fromisoformat(clock)))


# --- R-ICT: city-to-city moves ---

def test_valid_move_on_a_departure_slot(data):
    assert check_intercity([move(TYO_TO_KYO, "10:00")], STAYS, data) == []


def test_move_between_slots_gives_ict_6(data):
    assert rule_set(check_intercity([move(TYO_TO_KYO, "10:15")], STAYS, data)) == {"R-ICT-6"}


def test_wrong_direction_gives_ict_3(data):
    # Kyoto -> Tokyo matches no city change (the change is Tokyo -> Kyoto), so the Tokyo -> Kyoto change has no move.
    v = check_intercity([move("TR-KYO-TYO-01", "10:00")], STAYS, data)
    assert rule_set(v) == {"R-ICT-1", "R-ICT-3"}


def test_missing_move_gives_ict_1(data):
    assert rule_set(check_intercity([], STAYS, data)) == {"R-ICT-1"}


# --- R-ATT-9: an attraction visit overlapping an intercity Busy block ---

def test_attraction_overlapping_intercity_move_gives_att_9(data):
    rec = data.indexes.transfers_by_id[TYO_TO_KYO]
    pickup = datetime.combine(DAY, time(10, 0))
    busy = Busy(pickup, pickup + timedelta(minutes=rec["duration_minutes"]), None, "transfer")

    kyo_att = next(a["attraction_id"] for a in data.catalog.attractions
                   if a["city"] == "Kyoto" and len(a["open_days"]) == 7 and a["visit_minutes"] == 60
                   and a["open_from"] <= "10:30" and a["open_until"] >= "11:30"
                   and not a.get("closed_dates"))
    visit = Visit(None, kyo_att, datetime.combine(DAY, time(10, 30)), datetime.combine(DAY, time(11, 30)))
    ready = {date(2027, 4, 1): datetime(2027, 4, 1, 0, 0), DAY: datetime(2027, 4, 3, 9, 0)}

    # EDITED: the two full days (Apr 2 and Apr 4) have no visits, which is allowed.
    v = check_attractions([visit], STAYS, date(2027, 4, 1), date(2027, 4, 5), ready, [busy], EDITED, data)
    assert rule_set(v) == {"R-ATT-9"}
