"""Pydantic models. TripRequest is validated against the loaded catalog; package change commands
(Phase 5) are a strict discriminated union on `kind`."""

import re
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictInt,
    StringConstraints,
    TypeAdapter,
    model_validator,
)

from app.catalog.load import load_catalog
from app.rules.request import check_request, resolve_country


def max_travelers() -> int:
    """Largest party any flight can seat (children need seats)."""
    return max(f["seats_left"] for f in load_catalog().catalog.flights)


class TripRequest(BaseModel):
    departure_airport: str
    destination_country: str
    start_date: date
    nights: int
    adults: int = Field(ge=1)
    children_ages: list[int] = []
    budget: int = Field(gt=0)

    @model_validator(mode="after")
    def check_against_catalog(self):
        data = load_catalog()
        self.departure_airport = self.departure_airport.strip().upper()
        country = resolve_country(self.destination_country, data)
        if country is not None:
            self.destination_country = country["code"]

        violations = check_request(
            {
                "departure_airport": self.departure_airport,
                "destination_country": self.destination_country,
                "start_date": self.start_date,
                "nights": self.nights,
                "adults": self.adults,
                "children_ages": self.children_ages,
                "budget": self.budget,
            },
            data,
        )
        if violations:
            raise ValueError("; ".join(v.message for v in violations))

        cap = max_travelers()
        if self.adults + len(self.children_ages) > cap:
            raise ValueError(f"at most {cap} travelers (every traveler needs a flight seat)")
        return self


# ------------------------------------------------------------------ package change commands (Phase 5)
#
# One strict model per kind. Every command names its target by a stable id (stay id, leg id, item
# id, or the logical flight slot implied by the kind), never by a position in a list. Unknown fields
# are refused, so a client cannot send prices, totals or availability claims: the server computes
# all of them from the catalog.

CHANGE_ARRIVAL_FLIGHT = "CHANGE_ARRIVAL_FLIGHT"
CHANGE_RETURN_FLIGHT = "CHANGE_RETURN_FLIGHT"
CHANGE_HOTEL = "CHANGE_HOTEL"
CHANGE_AIRPORT_TRANSFER = "CHANGE_AIRPORT_TRANSFER"
CHANGE_INTERCITY_TRANSFER = "CHANGE_INTERCITY_TRANSFER"
ADD_ATTRACTION = "ADD_ATTRACTION"
REMOVE_ATTRACTION = "REMOVE_ATTRACTION"
CHANGE_KINDS = (CHANGE_ARRIVAL_FLIGHT, CHANGE_RETURN_FLIGHT, CHANGE_HOTEL, CHANGE_AIRPORT_TRANSFER,
                CHANGE_INTERCITY_TRANSFER, ADD_ATTRACTION, REMOVE_ATTRACTION)

_HHMM = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")
_YMD = re.compile(r"\d{4}-\d{2}-\d{2}")


def _clock(value):
    if not isinstance(value, str) or not _HHMM.fullmatch(value.strip()):
        raise ValueError("must be a local time as HH:MM, for example 10:00")
    return value.strip()


def _calendar_day(value):
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not _YMD.fullmatch(value.strip()):
        raise ValueError("must be a date as YYYY-MM-DD")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise ValueError("is not a real calendar date") from None


Id = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=200)]
Clock = Annotated[str, BeforeValidator(_clock)]
CalendarDay = Annotated[date, BeforeValidator(_calendar_day)]


class _Change(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    base_version: StrictInt = Field(ge=1)   # the package version the traveler is looking at


class ChangeArrivalFlight(_Change):
    kind: Literal["CHANGE_ARRIVAL_FLIGHT"]
    flight_id: Id                           # target: the arrival flight slot (flight:arrival)


class ChangeReturnFlight(_Change):
    kind: Literal["CHANGE_RETURN_FLIGHT"]
    flight_id: Id                           # target: the return flight slot (flight:return)


class ChangeHotel(_Change):
    kind: Literal["CHANGE_HOTEL"]
    stay_id: Id                             # target: stay:<city>:<check-in>:<check-out>
    hotel_id: Id
    room_id: Id


class ChangeAirportTransfer(_Change):
    kind: Literal["CHANGE_AIRPORT_TRANSFER"]
    item_id: Id                             # target: leg:arrival | leg:departure
    transfer_id: Id


class ChangeIntercityTransfer(_Change):
    kind: Literal["CHANGE_INTERCITY_TRANSFER"]
    item_id: Id                             # target: leg:<from>><to>:<date>
    transfer_id: Id
    pickup: Clock | None = None             # optional departure time; else the engine finds a slot


class AddAttraction(_Change):
    kind: Literal["ADD_ATTRACTION"]
    date: CalendarDay
    attraction_id: Id
    preferred_start: Clock | None = None    # a preference: the visit never displaces another one


class RemoveAttraction(_Change):
    kind: Literal["REMOVE_ATTRACTION"]
    item_id: Id                             # target: visit:<attraction id>


ChangeCommand = Annotated[
    ChangeArrivalFlight | ChangeReturnFlight | ChangeHotel | ChangeAirportTransfer
    | ChangeIntercityTransfer | AddAttraction | RemoveAttraction,
    Field(discriminator="kind"),
]
CHANGE_COMMAND = TypeAdapter(ChangeCommand)
