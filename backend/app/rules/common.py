"""Shared types for every rule module. Rule functions are pure: (inputs, catalog) -> list[Violation].

The validator parses a trip JSON into these selections; the Phase 3 planner can build them directly.
"""
from dataclasses import dataclass, field
from datetime import date, datetime

INITIAL = "INITIAL"
EDITED = "EDITED"


@dataclass(frozen=True)
class Violation:
    rule: str
    message: str
    item_id: str | None = None


@dataclass(frozen=True)
class Party:
    adults: int
    child_ages: tuple[int, ...] = ()

    @property
    def children(self) -> int:
        return len(self.child_ages)

    @property
    def travelers(self) -> int:
        return self.adults + self.children


@dataclass(frozen=True)
class FlightSel:
    item_id: str | None
    flight_id: str
    start: str | None = None   # exported local departure "YYYY-MM-DDTHH:MM" (checked against catalog)
    end: str | None = None     # exported local arrival


@dataclass(frozen=True)
class Stay:
    item_id: str | None
    hotel_id: str
    room_id: str
    city: str                  # city the trip claims for this stay
    check_in: date
    check_out: date            # exclusive: not a night
    rooms: int

    @property
    def nights(self) -> int:
        return (self.check_out - self.check_in).days


@dataclass(frozen=True)
class TransferSel:
    item_id: str | None
    transfer_id: str
    pickup: datetime           # local pickup / departure time


@dataclass(frozen=True)
class Visit:
    item_id: str | None
    attraction_id: str
    start: datetime
    end: datetime


@dataclass
class Busy:
    """A time block the traveler is occupied (a transfer in progress)."""
    start: datetime
    end: datetime
    item_id: str | None = None
    label: str = field(default="transfer")
