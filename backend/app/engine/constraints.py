"""Typed traveler locks for constrained planning and repair.

Hard constraints are never silently overridden: an incompatible lock yields a rejection
(LOCKED_CHOICE_INCOMPATIBLE or a specific rule violation), never a substituted choice.
"""
from dataclasses import dataclass, field
from datetime import date, datetime

LOCKED_CHOICE_INCOMPATIBLE = "LOCKED_CHOICE_INCOMPATIBLE"


@dataclass(frozen=True)
class HotelLock:
    hotel_id: str
    room_id: str
    rooms: int | None = None       # None = the minimum room count that fits the party


@dataclass(frozen=True)
class TransferLock:
    catalog_id: str
    pickup: datetime | None = None  # None = the planner picks a valid pickup for this service


@dataclass(frozen=True)
class RequiredAttraction:
    attraction_id: str
    day: date
    start: datetime | None = None   # None = any valid time that day


@dataclass
class PlanningConstraints:
    arrival_flight_id: str | None = None
    return_flight_id: str | None = None
    locked_city_plan: list[tuple[str, int]] | None = None        # ordered (city, nights)
    locked_hotels: dict[str, HotelLock] = field(default_factory=dict)        # stay_id -> lock
    locked_transfers: dict[str, TransferLock] = field(default_factory=dict)  # leg_id -> lock
    required_attractions: list[RequiredAttraction] = field(default_factory=list)
    excluded_attraction_ids: set[str] = field(default_factory=set)
    preserve_existing: bool = False
