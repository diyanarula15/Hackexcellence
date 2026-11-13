"""Transfer candidates for the planner: airport transfers (arrival and return) and city-to-city moves.

Each function returns one option per feasible transfer record. Every option satisfies the Phase 2
rules in app/rules/transfers.py and app/rules/intercity.py. Pure: reads only the Loaded catalog.
"""
from datetime import date, datetime, timedelta

from app.engine.constraints import TransferLock
from app.engine.model import ARRIVAL_LEG, DEPARTURE_LEG, FlightOption, HotelOption, TransferOption, intercity_leg_id
from app.lib.time import at, in_window, on_slot, window_on
from app.rules import pricing
from app.rules.common import Party
from app.rules.transfers import ARRIVAL_MAX_AFTER_LANDING, ARRIVAL_MIN_AFTER_LANDING, DEPARTURE_BUFFER_BEFORE_FLIGHT

ONE_MINUTE = timedelta(minutes=1)


def find_arrival_transfers(arrival_flight: FlightOption, hotel: HotelOption, party: Party, catalog,
                           locked: TransferLock | None = None) -> list[TransferOption]:
    """Airport -> hotel transfers. Pickup is the earliest service time >= landing + 60 min and <= landing + 24 h."""
    earliest = arrival_flight.arrival + ARRIVAL_MIN_AFTER_LANDING
    latest = arrival_flight.arrival + ARRIVAL_MAX_AFTER_LANDING
    out: list[TransferOption] = []
    for rec in _airport_candidates(arrival_flight.to_airport, hotel, catalog, locked):
        sf, su = rec["service_from"], rec["service_until"]
        if locked is not None and locked.pickup is not None:
            pickup = locked.pickup if earliest <= locked.pickup <= latest and in_window(locked.pickup, sf, su) else None
        else:
            pickup = None
            for s, e in _windows(earliest.date(), latest.date(), sf, su):   # ascending in time
                lo, hi = max(s, earliest), min(e, latest)
                if lo <= hi:
                    pickup = lo
                    break
        if pickup is not None:
            out.append(_transfer_option(ARRIVAL_LEG, rec, pickup, party))
    return _sorted(out)


def find_return_transfers(return_flight: FlightOption, hotel: HotelOption, party: Party, catalog,
                          locked: TransferLock | None = None) -> list[TransferOption]:
    """Hotel -> airport transfers. Pickup is the latest service time on the departure date such that
    pickup + duration <= departure - 180 min."""
    departs = return_flight.departure
    day = departs.date()
    day_start, day_end = _day_bounds(day)
    out: list[TransferOption] = []
    for rec in _airport_candidates(return_flight.from_airport, hotel, catalog, locked):
        sf, su = rec["service_from"], rec["service_until"]
        deadline = departs - DEPARTURE_BUFFER_BEFORE_FLIGHT - timedelta(minutes=rec["duration_minutes"])
        if locked is not None and locked.pickup is not None:
            t = locked.pickup
            pickup = t if t <= deadline and t.date() == day and in_window(t, sf, su) else None
        else:
            pickup = None
            for s, e in _windows(day, day, sf, su):
                lo, hi = max(s, day_start), min(e, deadline, day_end)
                if lo <= hi and (pickup is None or hi > pickup):
                    pickup = hi
        if pickup is not None:
            out.append(_transfer_option(DEPARTURE_LEG, rec, pickup, party))
    return _sorted(out)


def find_intercity_transfers(from_city: str, to_city: str, day: date, party: Party, catalog,
                             locked: TransferLock | None = None, prefer: str = "10:00") -> list[TransferOption]:
    """City-to-city moves on `day` along the directed link from_city -> to_city. The departure is the
    valid time closest to `prefer` (ties go earlier); `prefer` is a preference, never a requirement."""
    link = next((ln for ln in catalog.indexes.city_links_by_origin.get(from_city, [])
                 if ln["to_city"] == to_city), None)
    if link is None:
        return []
    ids = link["transfer_ids"]
    if locked is not None:
        ids = [tid for tid in ids if tid == locked.catalog_id]
    prefer_dt = at(day, prefer)
    exact = locked.pickup if locked is not None else None
    out: list[TransferOption] = []
    for tid in ids:
        rec = catalog.indexes.transfers_by_id.get(tid)
        if rec is None or rec.get("from_city") != from_city or rec.get("to_city") != to_city:
            continue
        pickup = _intercity_pickup(rec, day, prefer_dt, exact)
        if pickup is not None:
            out.append(_transfer_option(intercity_leg_id(from_city, to_city, day), rec, pickup, party))
    return _sorted(out)


# --- helpers -----------------------------------------------------------------------------------

def _airport_candidates(airport: str, hotel: HotelOption, catalog, locked: TransferLock | None) -> list[dict]:
    """Records at this airport serving the hotel's city; area null serves every area of the city."""
    recs = catalog.indexes.transfers_by_airport_city.get((airport, hotel.city), [])
    out = [r for r in recs if r.get("area") is None or r["area"] == hotel.area]
    if locked is not None:
        out = [r for r in out if r["transfer_id"] == locked.catalog_id]
    return out


def _windows(first: date, last: date, start: str, until: str) -> list[tuple[datetime, datetime]]:
    """Dated service windows opened on days first-1 .. last, ascending. A window opened the day
    before may run into `first`."""
    out = []
    d = first - timedelta(days=1)
    while d <= last:
        out.append(window_on(d, start, until))
        d += timedelta(days=1)
    return out


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    """First and last minute of a calendar day (pickups must carry that date)."""
    return at(day, "00:00"), at(day + timedelta(days=1), "00:00") - ONE_MINUTE


def _intercity_pickup(rec: dict, day: date, prefer_dt: datetime, exact: datetime | None) -> datetime | None:
    sf, su, freq = rec["service_from"], rec["service_until"], rec.get("frequency_minutes")

    def valid(t: datetime) -> bool:
        return t.date() == day and in_window(t, sf, su) and (freq is None or on_slot(t, sf, su, freq))

    if exact is not None:
        return exact if valid(exact) else None
    day_start, day_end = _day_bounds(day)
    best: datetime | None = None
    for s, e in _windows(day, day, sf, su):
        lo, hi = max(s, day_start), min(e, day_end)
        if lo > hi:
            continue
        cand = min(max(prefer_dt, lo), hi) if freq is None else _nearest_slot(s, freq, lo, hi, prefer_dt)
        if cand is not None and (best is None or (abs(cand - prefer_dt), cand) < (abs(best - prefer_dt), best)):
            best = cand
    return best


def _nearest_slot(s: datetime, freq: int, lo: datetime, hi: datetime, prefer: datetime) -> datetime | None:
    """The departure s + n * freq within [lo, hi] closest to `prefer` (ties earlier)."""
    step = timedelta(minutes=freq)
    n_lo = -((s - lo) // step)          # ceil((lo - s) / step)
    n_hi = (hi - s) // step             # floor((hi - s) / step)
    if n_lo > n_hi:
        return None
    n_pref = (prefer - s) // step
    cands = {min(max(n_pref, n_lo), n_hi), min(max(n_pref + 1, n_lo), n_hi)}
    return min((s + n * step for n in cands), key=lambda t: (abs(t - prefer), t))


def _transfer_option(leg_id: str, rec: dict, pickup: datetime, party: Party) -> TransferOption:
    quantity, price = pricing.transfer_price(rec, party)
    return TransferOption(leg_id=leg_id, transfer_id=rec["transfer_id"], pickup=pickup,
                          arrive=pickup + timedelta(minutes=rec["duration_minutes"]),
                          quantity=quantity, price=price)


def _sorted(options: list[TransferOption]) -> list[TransferOption]:
    return sorted(options, key=lambda o: (o.price, o.pickup, o.transfer_id))
