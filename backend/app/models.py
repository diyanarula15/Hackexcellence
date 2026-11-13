"""Pydantic models. TripRequest is validated against the loaded catalog."""
from datetime import date

from pydantic import BaseModel, Field, model_validator

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

        violations = check_request({
            "departure_airport": self.departure_airport,
            "destination_country": self.destination_country,
            "start_date": self.start_date,
            "nights": self.nights,
            "adults": self.adults,
            "children_ages": self.children_ages,
            "budget": self.budget,
        }, data)
        if violations:
            raise ValueError("; ".join(v.message for v in violations))

        cap = max_travelers()
        if self.adults + len(self.children_ages) > cap:
            raise ValueError(f"at most {cap} travelers (every traveler needs a flight seat)")
        return self
