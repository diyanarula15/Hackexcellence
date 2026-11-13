"""Alternatives: every replacement for one package item, each evaluated as a complete modified package.

Every candidate goes through the same change engine as a real preview (app.engine.change.propose_change),
so an option is offered as valid only when the whole modified package passes the EDITED rules, and its
price difference is the whole-package difference of that validated proposal. Invalid candidates are
returned with their reasons (and are never applicable); nothing here writes anywhere.

Public API (frozen; see the Phase 5 contract):
  OPTION_KINDS, OptionsRequestError, Alternative,
  get_alternatives(package, kind, target_id, catalog, date=None) -> list[Alternative]
  options_response(package, kind, target_id, catalog, date=None) -> dict
"""

from dataclasses import asdict, dataclass, field
from datetime import date as Date
from datetime import datetime, timedelta

from app.engine.change import propose_change
from app.engine.flights import (
    compatible_arrivals,
    compatible_returns,
    find_arrival_flights,
    find_return_flights,
)
from app.engine.hotels import min_rooms
from app.engine.model import ARRIVAL_LEG, DEPARTURE_LEG, Package, intercity_leg_id
from app.engine.repair import ChangeProposal, request_of
from app.lib.money import amount
from app.services.itinerary import transfer_route
from app.lib.time import at, in_window, on_slot, window_on
from app.models import (
    ADD_ATTRACTION,
    CHANGE_AIRPORT_TRANSFER,
    CHANGE_ARRIVAL_FLIGHT,
    CHANGE_COMMAND,
    CHANGE_HOTEL,
    CHANGE_INTERCITY_TRANSFER,
    CHANGE_RETURN_FLIGHT,
)
from app.rules import pricing
from app.rules.common import Party
from app.services.change_view import changed_item_view, headline, name_ids, violation_view
from app.services.photos import attraction_photo_url, hotel_photo_url

OPTION_KINDS = (
    "hotel",
    "arrival_flight",
    "return_flight",
    "airport_transfer",
    "intercity_transfer",
    "attraction",
)
CONTINUOUS_SLOT_MINUTES = 60  # display grid for transfers that run at any time inside their window


class OptionsRequestError(ValueError):
    """The options query names an unknown kind, target or date."""

    def __init__(self, field_name: str, message: str):
        super().__init__(message)
        self.field = field_name
        self.message = message


@dataclass(frozen=True)
class Alternative:
    catalog_id: str
    name: str
    valid: bool
    item_price_inr: int | None
    proposed_total_inr: int | None
    package_price_difference_inr: int | None
    budget_remaining_inr: int | None
    affected_items: list = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    room_id: str | None = None
    room_name: str | None = None
    current: bool = False
    over_budget_inr: int | None = None
    changed_items: list = field(default_factory=list)
    violations: list = field(default_factory=list)
    details: dict = field(default_factory=dict)
    command: dict | None = None


# --- evaluation ------------------------------------------------------------------------------------


def _party(pkg: Package) -> Party:
    return Party(pkg.adults, tuple(pkg.child_ages))


def _propose(pkg: Package, command: dict, catalog) -> ChangeProposal:
    # base_version is checked by the service layer; the engine ignores it
    return propose_change(
        pkg, CHANGE_COMMAND.validate_python({"base_version": 1, **command}), catalog
    )


def _target_after(proposal: ChangeProposal, item_id: str) -> dict | None:
    return next((c.after for c in proposal.changed_items if c.component == item_id), None)


def _reasons(proposal: ChangeProposal, catalog) -> list[str]:
    lines = [headline(proposal.violations, catalog)]
    lines += [name_ids(v.message, catalog) for v in proposal.violations]
    return list(dict.fromkeys(x for x in lines if x))


def _budget(pkg: Package, total: int) -> tuple[int, int]:
    return max(pkg.budget - total, 0), max(total - pkg.budget, 0)


def _alternative(
    pkg: Package,
    catalog,
    proposal: ChangeProposal,
    command: dict,
    *,
    catalog_id: str,
    name: str,
    target: str,
    fallback_price: int | None,
    details: dict,
    room_id: str | None = None,
    room_name: str | None = None,
) -> Alternative:
    if not proposal.valid:
        return Alternative(
            catalog_id=catalog_id,
            name=name,
            valid=False,
            item_price_inr=fallback_price,
            proposed_total_inr=None,
            package_price_difference_inr=None,
            budget_remaining_inr=None,
            reasons=_reasons(proposal, catalog),
            room_id=room_id,
            room_name=room_name,
            violations=[violation_view(v, catalog) for v in proposal.violations],
            details=details,
            command=command,  # previewable so the traveler sees why; apply stays impossible
        )
    after = _target_after(proposal, target)
    remaining, over = _budget(pkg, proposal.new_total)
    return Alternative(
        catalog_id=catalog_id,
        name=name,
        valid=True,
        item_price_inr=after["price_inr"] if after else fallback_price,
        proposed_total_inr=proposal.new_total,
        package_price_difference_inr=proposal.price_difference,
        budget_remaining_inr=remaining,
        over_budget_inr=over,
        affected_items=[changed_item_view(c, catalog) for c in proposal.automatic_repairs],
        changed_items=[changed_item_view(c, catalog) for c in proposal.changed_items],
        warnings=list(proposal.warnings),
        room_id=room_id,
        room_name=room_name,
        details=details,
        command=command,
    )


def _current(pkg: Package, *, catalog_id, name, price, details, room_id=None, room_name=None):
    remaining, over = _budget(pkg, pkg.total)
    return Alternative(
        catalog_id=catalog_id,
        name=name,
        valid=True,
        current=True,
        item_price_inr=price,
        proposed_total_inr=pkg.total,
        package_price_difference_inr=0,
        budget_remaining_inr=remaining,
        over_budget_inr=over,
        room_id=room_id,
        room_name=room_name,
        details=details,
    )


def _sort_key(a: Alternative):
    diff = a.package_price_difference_inr
    return (
        not a.valid,
        diff if diff is not None else float("inf"),
        len(a.affected_items),
        a.catalog_id,
        a.room_id or "",
    )


# --- hotels ----------------------------------------------------------------------------------------


def _hotels(pkg: Package, stay_id, catalog) -> list[Alternative]:
    ix = catalog.indexes
    idx = next((i for i, s in enumerate(pkg.plan.stays) if s.stay_id == stay_id), None)
    if idx is None:
        raise OptionsRequestError("stay_id", "Choose a hotel stay that is part of this holiday.")
    stay, now = pkg.plan.stays[idx], pkg.hotels[idx]
    out = []
    for hotel in sorted(ix.hotels_by_city.get(stay.city, []), key=lambda h: h["hotel_id"]):
        for room in sorted(
            ix.rooms_by_hotel.get(hotel["hotel_id"], []), key=lambda r: r["room_id"]
        ):
            k = min_rooms(room, pkg.adults, len(pkg.child_ages))
            details = {
                "hotel_name": hotel.get("name"),
                "room_name": room.get("name"),
                "area": hotel.get("area"),
                "stars": hotel.get("stars"),
                "rating": hotel.get("rating"),
                "image_url": hotel_photo_url(hotel),
                "rooms": k,
                "nights": stay.nights,
                "check_in": stay.check_in.isoformat(),
                "check_out": stay.check_out.isoformat(),
                "price_per_night_inr": amount(room["price_per_night"]),
            }
            ids = {
                "catalog_id": hotel["hotel_id"],
                "name": hotel.get("name") or hotel["hotel_id"],
                "room_id": room["room_id"],
                "room_name": room.get("name"),
            }
            if (hotel["hotel_id"], room["room_id"]) == (now.hotel_id, now.room_id):
                out.append(
                    _current(
                        pkg, price=now.total_price, details={**details, "rooms": now.rooms}, **ids
                    )
                )
                continue
            command = {
                "kind": CHANGE_HOTEL,
                "stay_id": stay_id,
                "hotel_id": hotel["hotel_id"],
                "room_id": room["room_id"],
            }
            proposal = _propose(pkg, command, catalog)
            if proposal.valid:
                after = _target_after(proposal, stay_id)
                details["rooms"] = after.get("rooms", k) if after else k
            fallback = pricing.hotel_price(room, k, stay.nights)[1] if k else None
            out.append(
                _alternative(
                    pkg,
                    catalog,
                    proposal,
                    command,
                    target=stay_id,
                    fallback_price=fallback,
                    details=details,
                    **ids,
                )
            )
    return out


# --- flights ---------------------------------------------------------------------------------------


def _flight_details(rec: dict) -> dict:
    return {
        "flight_number": rec.get("flight_number"),
        "airline": rec.get("airline"),
        "from": rec.get("from"),
        "to": rec.get("to"),
        "departure_local": rec.get("departure_local"),
        "arrival_local": rec.get("arrival_local"),
        "duration_minutes": rec.get("duration_minutes"),
        "stops": rec.get("stops"),
        "cabin": rec.get("cabin"),
        "seats_left": rec.get("seats_left"),
    }


def _flights(pkg: Package, arrival: bool, catalog) -> list[Alternative]:
    ix = catalog.indexes
    req = request_of(pkg)
    if arrival:
        found = compatible_arrivals(
            pkg.plan, find_arrival_flights(req, catalog, ignore_seats=True), catalog
        )
        now, kind, target = pkg.arrival_flight, CHANGE_ARRIVAL_FLIGHT, "flight:arrival"
    else:
        found = compatible_returns(
            pkg.plan, find_return_flights(req, catalog, ignore_seats=True), catalog
        )
        now, kind, target = pkg.return_flight, CHANGE_RETURN_FLIGHT, "flight:return"
    ids = list(dict.fromkeys([now.flight_id] + [f.flight_id for f in found]))
    party = _party(pkg)
    out = []
    for fid in ids:
        rec = ix.flights_by_id[fid]
        name = " ".join(x for x in (rec.get("airline"), rec.get("flight_number")) if x) or fid
        details = _flight_details(rec)
        if fid == now.flight_id:
            out.append(_current(pkg, catalog_id=fid, name=name, price=now.price, details=details))
            continue
        command = {"kind": kind, "flight_id": fid}
        proposal = _propose(pkg, command, catalog)
        out.append(
            _alternative(
                pkg,
                catalog,
                proposal,
                command,
                catalog_id=fid,
                name=name,
                target=target,
                fallback_price=pricing.flight_price(rec, party)[1],
                details=details,
            )
        )
    return out


# --- transfers -------------------------------------------------------------------------------------


def _transfer_details(rec: dict, pickup: str | None, dropoff: str | None) -> dict:
    return {
        "transfer_type": rec.get("type"),
        "airport": rec.get("airport"),
        "area": rec.get("area"),
        "pickup": pickup,
        "dropoff": dropoff,
        "duration_minutes": rec.get("duration_minutes"),
        "pricing": rec.get("pricing"),
        "max_passengers": rec.get("max_passengers"),
    }


def _airport_transfers(pkg: Package, item_id, catalog) -> list[Alternative]:
    ix = catalog.indexes
    if item_id == ARRIVAL_LEG:
        airport, city, now = (
            pkg.arrival_flight.to_airport,
            pkg.plan.first_city,
            pkg.arrival_transfer,
        )
    elif item_id == DEPARTURE_LEG:
        airport, city, now = (
            pkg.return_flight.from_airport,
            pkg.plan.last_city,
            pkg.departure_transfer,
        )
    else:
        raise OptionsRequestError(
            "item_id",
            "Choose the arrival or departure airport transfer (leg:arrival or leg:departure).",
        )
    pool = {r["transfer_id"]: r for r in ix.transfers_by_airport_city.get((airport, city), [])}
    pool.setdefault(now.transfer_id, ix.transfers_by_id[now.transfer_id])
    party = _party(pkg)
    out = []
    for tid in sorted(pool):
        rec = pool[tid]
        name = transfer_route(rec, item_id == DEPARTURE_LEG)[0] or tid
        if tid == now.transfer_id:
            details = _transfer_details(rec, now.pickup.isoformat(), now.arrive.isoformat())
            out.append(_current(pkg, catalog_id=tid, name=name, price=now.price, details=details))
            continue
        command = {"kind": CHANGE_AIRPORT_TRANSFER, "item_id": item_id, "transfer_id": tid}
        proposal = _propose(pkg, command, catalog)
        after = _target_after(proposal, item_id) if proposal.valid else None
        details = _transfer_details(rec, after and after["start"], after and after["end"])
        out.append(
            _alternative(
                pkg,
                catalog,
                proposal,
                command,
                catalog_id=tid,
                name=name,
                target=item_id,
                fallback_price=pricing.transfer_price(rec, party)[1],
                details=details,
            )
        )
    return out


def departure_slots(rec: dict, day: Date) -> list[datetime]:
    """Every departure of this city-to-city service on `day`: each frequency slot inside the service
    window, or (for a service that runs at any time) the window start and every full hour after it."""
    sf, su, freq = rec["service_from"], rec["service_until"], rec.get("frequency_minutes")
    day_start, day_end = (
        at(day, "00:00"),
        at(day + timedelta(days=1), "00:00") - timedelta(minutes=1),
    )
    out: set[datetime] = set()
    for opened in (day - timedelta(days=1), day):
        s, e = window_on(opened, sf, su)
        lo, hi = max(s, day_start), min(e, day_end)
        if freq:
            t = s
            while t <= hi:
                if t >= lo:
                    out.add(t)
                t += timedelta(minutes=freq)
        elif lo <= hi:
            out.add(lo)
            t = lo.replace(minute=0) + timedelta(hours=1) if lo.minute else lo + timedelta(hours=1)
            while t <= hi:
                out.add(t)
                t += timedelta(minutes=CONTINUOUS_SLOT_MINUTES)
    return sorted(
        t
        for t in out
        if t.date() == day and in_window(t, sf, su) and (not freq or on_slot(t, sf, su, freq))
    )


def _intercity(pkg: Package, item_id, catalog) -> list[Alternative]:
    ix = catalog.indexes
    legs = pkg.plan.legs()
    idx = next(
        (i for i, (a, b, d) in enumerate(legs) if intercity_leg_id(a, b, d) == item_id), None
    )
    if idx is None:
        raise OptionsRequestError(
            "item_id", "Choose a city-to-city transfer that is part of this holiday."
        )
    from_city, to_city, day = legs[idx]
    now = pkg.intercity[idx]
    link = next(
        (ln for ln in ix.city_links_by_origin.get(from_city, []) if ln["to_city"] == to_city), None
    )
    tids = list(dict.fromkeys([now.transfer_id] + list(link["transfer_ids"] if link else [])))
    party = _party(pkg)
    out = []
    for tid in tids:
        rec = ix.transfers_by_id.get(tid)
        if rec is None:
            continue
        name = rec.get("name") or tid
        slots = []
        for t in departure_slots(rec, day):
            hhmm = f"{t:%H:%M}"
            arrives = f"{t + timedelta(minutes=rec['duration_minutes']):%H:%M}"
            if tid == now.transfer_id and t == now.pickup:
                slots.append(
                    {"pickup": hhmm, "arrives": arrives, "valid": True, "current": True,
                     "package_price_difference_inr": 0, "reasons": [], "command": None}
                )  # fmt: skip
                continue
            command = {
                "kind": CHANGE_INTERCITY_TRANSFER,
                "item_id": item_id,
                "transfer_id": tid,
                "pickup": hhmm,
            }
            p = _propose(pkg, command, catalog)
            slots.append(
                {"pickup": hhmm, "arrives": arrives, "valid": p.valid, "current": False,
                 "package_price_difference_inr": p.price_difference if p.valid else None,
                 "reasons": [] if p.valid else _reasons(p, catalog),
                 "command": command if p.valid else None}
            )  # fmt: skip
        base = {
            "transfer_type": rec.get("type"),
            "from_point": rec.get("from_point"),
            "to_point": rec.get("to_point"),
            "duration_minutes": rec.get("duration_minutes"),
            "frequency_minutes": rec.get("frequency_minutes"),
            "departure_slots": slots,
        }
        if tid == now.transfer_id:
            details = {**base, "pickup": now.pickup.isoformat(), "dropoff": now.arrive.isoformat()}
            out.append(_current(pkg, catalog_id=tid, name=name, price=now.price, details=details))
            continue
        command = {"kind": CHANGE_INTERCITY_TRANSFER, "item_id": item_id, "transfer_id": tid}
        proposal = _propose(pkg, command, catalog)
        after = _target_after(proposal, item_id) if proposal.valid else None
        if after:  # pin the engine's chosen departure so the preview reproduces this exact option
            command = {**command, "pickup": after["start"][11:16]}
        details = {**base, "pickup": after and after["start"], "dropoff": after and after["end"]}
        out.append(
            _alternative(
                pkg,
                catalog,
                proposal,
                command,
                catalog_id=tid,
                name=name,
                target=item_id,
                fallback_price=pricing.transfer_price(rec, party)[1],
                details=details,
            )
        )
    return out


# --- attractions -----------------------------------------------------------------------------------


def _visit_day(pkg: Package, value) -> Date:
    if not value:
        raise OptionsRequestError("date", "Choose the day to add an attraction to, as YYYY-MM-DD.")
    try:
        day = value if isinstance(value, Date) else Date.fromisoformat(str(value))
    except ValueError:
        raise OptionsRequestError("date", f"{value} is not a date as YYYY-MM-DD.") from None
    start, end = pkg.plan.start_date, pkg.plan.end_date
    if not start <= day <= end:
        raise OptionsRequestError(
            "date",
            f"{day.isoformat()} is not a day of this holiday ({start.isoformat()} to {end.isoformat()}).",
        )
    return day


def _attractions(pkg: Package, day: Date, catalog) -> list[Alternative]:
    if day == pkg.plan.end_date:
        return []
    city = next(s.city for s in pkg.plan.stays if s.check_in <= day < s.check_out)
    party = _party(pkg)
    out = []
    for rec in sorted(
        catalog.indexes.attractions_by_city.get(city, []), key=lambda a: a["attraction_id"]
    ):
        aid = rec["attraction_id"]
        command = {"kind": ADD_ATTRACTION, "date": day.isoformat(), "attraction_id": aid}
        proposal = _propose(pkg, command, catalog)
        after = _target_after(proposal, f"visit:{aid}") if proposal.valid else None
        if after:  # pin the proposed start so the preview reproduces this exact option
            command = {**command, "preferred_start": after["start"][11:16]}
        details = {
            "city": city,
            "date": day.isoformat(),
            "start": after and after["start"],
            "end": after and after["end"],
            "visit_minutes": rec.get("visit_minutes"),
            "open_from": rec.get("open_from"),
            "open_until": rec.get("open_until"),
            "category": rec.get("category"),
            "child_friendly": rec.get("child_friendly"),
            "image_url": attraction_photo_url(rec),
        }
        out.append(
            _alternative(
                pkg,
                catalog,
                proposal,
                command,
                catalog_id=aid,
                name=rec.get("name") or aid,
                target=f"visit:{aid}",
                fallback_price=pricing.attraction_price(rec, party)[1],
                details=details,
            )
        )
    return out


# --- public ----------------------------------------------------------------------------------------


def _require_kind(kind) -> None:
    if kind not in OPTION_KINDS:
        shown = f"'{kind}'" if kind else "missing"
        raise OptionsRequestError(
            "kind", f"Option kind {shown} is not supported. Use one of: {', '.join(OPTION_KINDS)}."
        )


def get_alternatives(
    package: Package, kind: str, target_id, catalog, date=None
) -> list[Alternative]:
    """Every replacement for one item, each evaluated as a complete modified package, in the stable
    order: valid first, lower whole-package difference, fewer automatic repairs, catalog id."""
    _require_kind(kind)
    if kind == "hotel":
        found = _hotels(package, target_id, catalog)
    elif kind in ("arrival_flight", "return_flight"):
        found = _flights(package, kind == "arrival_flight", catalog)
    elif kind == "airport_transfer":
        found = _airport_transfers(package, target_id, catalog)
    elif kind == "intercity_transfer":
        found = _intercity(package, target_id, catalog)
    else:
        found = _attractions(package, _visit_day(package, date), catalog)
    return sorted(found, key=_sort_key)


def _target(kind: str, target_id) -> str | None:
    return {
        "arrival_flight": "flight:arrival",
        "return_flight": "flight:return",
        "attraction": None,
    }.get(kind, target_id)


def options_response(package: Package, kind: str, target_id, catalog, date=None) -> dict:
    alternatives = get_alternatives(package, kind, target_id, catalog, date)
    day = _visit_day(package, date).isoformat() if kind == "attraction" else None
    usable = [a for a in alternatives if a.valid and not a.current]
    if kind == "attraction" and day == package.plan.end_date.isoformat():
        message = "Attractions cannot be added on your departure day."
    elif not alternatives:
        message = "The catalog has no options for this item."
    elif all(a.current for a in alternatives):
        message = "Your current choice is the only option in the catalog for this item."
    elif not usable:
        message = "No other option fits the rest of your holiday. Each option shows why."
    else:
        message = None
    return {
        "kind": kind,
        "target_item_id": _target(kind, target_id),
        "date": day,
        "message": message,
        "alternatives": [asdict(a) for a in alternatives],
    }
