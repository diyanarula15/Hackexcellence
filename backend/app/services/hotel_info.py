"""Hotel details for the hotel drawer: catalog fields only, its photo and credit, a map search link.

Read-only. Hotels in the dataset are fictional, so their photos are generic sample rooms shared by
hotel type (images/ATTRIBUTIONS.md); the response says so with `image_is_sample`.
"""

from pathlib import Path
from urllib.parse import quote

from app.catalog.load import load_catalog
from app.lib.money import amount
from app.services.attraction_info import MAPS_SEARCH, image_file
from app.services.photos import hotel_photo_url, photo_credit


def _record(hotel_id: str) -> dict | None:
    return load_catalog().indexes.hotels_by_id.get(hotel_id)


def hotel_detail(hotel_id: str) -> dict | None:
    """The drawer's data for one hotel, or None when the id is not in the catalog."""
    h = _record(hotel_id)
    if h is None:
        return None
    ix = load_catalog().indexes
    country = ix.country_by_city.get(h["city"], {})
    rooms = sorted(ix.rooms_by_hotel.get(hotel_id, []), key=lambda r: amount(r["price_per_night"]))
    query = f"{h['name']}, {h.get('area') or ''}, {h['city']}".replace(", ,", ",")
    return {
        "hotel_id": h["hotel_id"],
        "name": h["name"],
        "city": h["city"],
        "country": country.get("name"),
        "area": h.get("area"),
        "stars": h.get("stars"),
        "rating": h.get("rating"),
        "check_in_from": h.get("check_in_from"),
        "check_out_until": h.get("check_out_until"),
        "family_friendly": h.get("family_friendly"),
        "rooms": [
            {
                "room_id": r["room_id"],
                "name": r.get("name"),
                "room_type": r.get("room_type"),
                "max_adults": r.get("max_adults"),
                "max_children": r.get("max_children"),
                "price_per_night_inr": amount(r["price_per_night"]),
                "refundable": r.get("refundable"),
            }
            for r in rooms
        ],
        "image_url": hotel_photo_url(h),
        "image_credit": photo_credit(h),
        "image_is_sample": hotel_photo_url(h) is not None,
        "maps_url": MAPS_SEARCH + quote(query, safe=""),
    }


def hotel_image_path(hotel_id: str) -> Path | None:
    """The JPEG path for a hotel id, or None (unknown id, no image, or path outside images/)."""
    h = _record(hotel_id)
    return image_file(h) if h else None
