"""Itinerary rules (R-PLAN-*): the city sequence and night dates of a multi-city stay.

Pure: (stays, country, start, nights, catalog) -> list[Violation]. Stays are in itinerary order.
"""
from datetime import date, timedelta

from app.rules.common import Stay, Violation


def stay_city(stay: Stay, data) -> str:
    """The catalog city of the stay's hotel; the trip's claimed city if the hotel is unknown."""
    hotel = data.indexes.hotels_by_id.get(stay.hotel_id)
    return hotel["city"] if hotel is not None else stay.city


def check_city_plan(stays: list[Stay], country_code: str, start_date: date,
                    nights: int, data) -> list[Violation]:
    if not stays:
        return [Violation("R-PLAN-8", "The itinerary has no stays.")]

    min_nights = data.catalog.destinations["rules"]["min_nights_per_city"]
    country = data.indexes.countries_by_code.get(country_code)
    cities = {c["name"] for c in country["cities"]} if country else set()
    links = {(ln["from_city"], ln["to_city"]) for ln in country["links"]} if country else set()
    where = f"{country['name']}" if country else f"country {country_code!r}"

    out: list[Violation] = []
    city_of = [stay_city(s, data) for s in stays]

    seen: set[str] = set()
    for stay, city in zip(stays, city_of):
        if city not in cities:
            out.append(Violation("R-PLAN-1", f"{city} is not a city in {where}.", stay.item_id))
        if city in seen:
            out.append(Violation("R-PLAN-2",
                                 f"{city} appears in more than one stay; each city may be visited once.",
                                 stay.item_id))
        seen.add(city)
        if stay.check_out <= stay.check_in:
            out.append(Violation("R-PLAN-3",
                                 f"{city} stay checks out {stay.check_out}, not after check-in {stay.check_in}.",
                                 stay.item_id))
        elif stay.nights < min_nights:
            out.append(Violation("R-PLAN-3",
                                 f"{city} stay is {stay.nights} night(s); at least {min_nights} are required.",
                                 stay.item_id))

    total = sum(s.nights for s in stays)
    if total != nights:
        out.append(Violation("R-PLAN-4", f"Stays add up to {total} night(s) but the trip has {nights}."))

    for k in range(len(stays) - 1):
        a, b = city_of[k], city_of[k + 1]
        if a == b or a not in cities or b not in cities:
            continue  # a repeated city is R-PLAN-2; an unknown city is R-PLAN-1
        if (a, b) not in links:
            out.append(Violation("R-PLAN-5", f"No direct link from {a} to {b} in {where}.",
                                 stays[k + 1].item_id))

    if stays[0].check_in != start_date:
        out.append(Violation("R-PLAN-6",
                             f"First stay checks in {stays[0].check_in}, but the trip starts {start_date}.",
                             stays[0].item_id))
    for k in range(len(stays) - 1):
        if stays[k].check_out != stays[k + 1].check_in:
            out.append(Violation("R-PLAN-6",
                                 f"Stay {k + 1} checks out {stays[k].check_out} but the next stay checks in "
                                 f"{stays[k + 1].check_in}; dates must join with no gap or overlap.",
                                 stays[k + 1].item_id))

    trip_end = start_date + timedelta(days=nights)
    if stays[-1].check_out != trip_end:
        out.append(Violation("R-PLAN-7",
                             f"Last stay checks out {stays[-1].check_out}, but the trip ends {trip_end} "
                             f"(start plus {nights} nights).", stays[-1].item_id))

    return out
