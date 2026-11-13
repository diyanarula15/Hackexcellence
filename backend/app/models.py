"""Pydantic models. TripRequest is validated against the loaded catalog."""
from datetime import date, timedelta

from pydantic import BaseModel, Field, model_validator

from app.catalog.load import load_catalog


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
        dest = load_catalog().catalog.destinations
        rules = dest["rules"]

        airports = {d["airport"] for d in dest["departure_cities"]}
        self.departure_airport = self.departure_airport.strip().upper()
        if self.departure_airport not in airports:
            raise ValueError(f"departure_airport must be one of {sorted(airports)}")

        wanted = self.destination_country.strip().lower()
        match = next((c for c in dest["countries"]
                      if wanted in (c["code"].lower(), c["name"].lower())), None)
        if match is None:
            raise ValueError(f"destination_country must be one of {[c['code'] for c in dest['countries']]}")
        self.destination_country = match["code"]

        if not rules["min_nights"] <= self.nights <= rules["max_nights"]:
            raise ValueError(f"nights must be between {rules['min_nights']} and {rules['max_nights']}")

        window = rules["data_window"]
        first = date.fromisoformat(window["first_night"])
        last = date.fromisoformat(window["last_departure"])
        if self.start_date < first:
            raise ValueError(f"start_date cannot be before {first}")
        end = self.start_date + timedelta(days=self.nights)
        if end > last:
            raise ValueError(f"trip would end {end}, after the last available date {last}")

        if any(not 0 <= a <= 17 for a in self.children_ages):
            raise ValueError("each child age must be between 0 and 17")
        cap = max_travelers()
        if self.adults + len(self.children_ages) > cap:
            raise ValueError(f"at most {cap} travelers (every traveler needs a flight seat)")
        return self
