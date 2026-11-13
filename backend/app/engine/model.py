"""Internal planning models shared by every engine module. All are immutable value objects, so a
"copy" of a package can never alias mutable state of another one.

Stable identities:
  stay_id = "stay:<city>:<check_in>:<check_out>"   one consecutive city stay
  leg_id  = "leg:arrival" | "leg:departure" | "leg:<from_city>><to_city>:<date>"
"""
from dataclasses import dataclass, field, replace
from datetime import date, datetime

ARRIVAL_LEG = "leg:arrival"
DEPARTURE_LEG = "leg:departure"


def intercity_leg_id(from_city: str, to_city: str, day: date) -> str:
    return f"leg:{from_city}>{to_city}:{day.isoformat()}"


@dataclass(frozen=True)
class CityStay:
    city: str
    check_in: date
    check_out: date            # exclusive

    @property
    def nights(self) -> int:
        return (self.check_out - self.check_in).days

    @property
    def stay_id(self) -> str:
        return f"stay:{self.city}:{self.check_in.isoformat()}:{self.check_out.isoformat()}"


@dataclass(frozen=True)
class CityPlan:
    country_code: str
    stays: tuple[CityStay, ...]

    @property
    def cities(self) -> tuple[str, ...]:
        return tuple(s.city for s in self.stays)

    @property
    def first_city(self) -> str:
        return self.stays[0].city

    @property
    def last_city(self) -> str:
        return self.stays[-1].city

    @property
    def start_date(self) -> date:
        return self.stays[0].check_in

    @property
    def end_date(self) -> date:
        return self.stays[-1].check_out

    def legs(self) -> list[tuple[str, str, date]]:
        """City changes as (from_city, to_city, change_date)."""
        return [(a.city, b.city, a.check_out) for a, b in zip(self.stays, self.stays[1:])]


@dataclass(frozen=True)
class FlightOption:
    flight_id: str
    from_airport: str
    to_airport: str
    departure: datetime        # local at from_airport
    arrival: datetime          # local at to_airport
    quantity: int              # seats
    price: int                 # total INR for the party


@dataclass(frozen=True)
class HotelOption:
    stay_id: str
    hotel_id: str
    room_id: str
    city: str
    area: str | None
    check_in: date
    check_out: date
    rooms: int
    total_price: int


@dataclass(frozen=True)
class TransferOption:
    leg_id: str
    transfer_id: str
    pickup: datetime
    arrive: datetime           # pickup + catalog duration
    quantity: int              # vehicles or tickets
    price: int


@dataclass(frozen=True)
class VisitOption:
    attraction_id: str
    start: datetime
    end: datetime
    quantity: int
    price: int


@dataclass(frozen=True)
class Package:
    """A complete holiday. Immutable: edits produce a new Package via dataclasses.replace."""
    trip_id: str
    traveler_name: str
    home_airport: str
    country_code: str
    country_name: str
    adults: int
    child_ages: tuple[int, ...]
    budget: int
    plan: CityPlan
    arrival_flight: FlightOption
    return_flight: FlightOption
    hotels: tuple[HotelOption, ...]            # aligned with plan.stays
    arrival_transfer: TransferOption
    departure_transfer: TransferOption
    intercity: tuple[TransferOption, ...]      # aligned with plan.legs()
    visits: tuple[VisitOption, ...] = field(default_factory=tuple)
    status: str = "PLANNED"
    booking_reference: str | None = None

    @property
    def total(self) -> int:
        return (self.arrival_flight.price + self.return_flight.price
                + sum(h.total_price for h in self.hotels)
                + self.arrival_transfer.price + self.departure_transfer.price
                + sum(t.price for t in self.intercity) + sum(v.price for v in self.visits))

    @property
    def budget_remaining(self) -> int:
        return self.budget - self.total

    def with_(self, **changes) -> "Package":
        return replace(self, **changes)

    def to_export(self) -> dict:
        """The dict accepted by app.export.to_trip.to_trip_json, items in itinerary order.

        Order is built structurally (flight out, arrival transfer, then each stay with its visits,
        then the move to the next city, ..., departure transfer, flight home) - never by sorting
        timestamp strings, because the outbound flight departs in India-local time.
        """
        items: list[dict] = []

        def flight(f: FlightOption):
            items.append({"type": "flight", "catalog_id": f.flight_id, "start": f.departure,
                          "end": f.arrival, "quantity": f.quantity, "price_inr": f.price})

        def transfer(t: TransferOption):
            items.append({"type": "transfer", "catalog_id": t.transfer_id, "start": t.pickup,
                          "end": t.arrive, "quantity": t.quantity, "price_inr": t.price})

        flight(self.arrival_flight)
        transfer(self.arrival_transfer)
        visits = sorted(self.visits, key=lambda v: (v.start, v.attraction_id))
        for i, (stay, h) in enumerate(zip(self.plan.stays, self.hotels)):
            items.append({"type": "hotel", "catalog_id": h.hotel_id, "room_id": h.room_id,
                          "start": h.check_in, "end": h.check_out, "quantity": h.rooms,
                          "price_inr": h.total_price})
            last = i == len(self.plan.stays) - 1
            for v in visits:
                # a stay owns the visits from its check-in day up to (not including) its check-out
                # day; the final stay also owns anything on the last day.
                if stay.check_in <= v.start.date() and (v.start.date() < stay.check_out or last):
                    items.append({"type": "attraction", "catalog_id": v.attraction_id, "start": v.start,
                                  "end": v.end, "quantity": v.quantity, "price_inr": v.price})
            if not last:
                transfer(self.intercity[i])
        transfer(self.departure_transfer)
        flight(self.return_flight)
        return {
            "trip_id": self.trip_id,
            "traveler": {"name": self.traveler_name, "home_airport": self.home_airport,
                         "adults": self.adults, "child_ages": list(self.child_ages)},
            "country": self.country_name,
            "start_date": self.plan.start_date, "end_date": self.plan.end_date,
            "budget_inr": self.budget,
            "status": self.status, "booking_reference": self.booking_reference,
            "items": items,
        }
