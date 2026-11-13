"""Attraction details for the detail drawer: catalog fields only, the photo's credit, a map search link.

Read-only. Nothing here invents text: every value comes from data/catalog/attractions.json, the
photo credits come from images/ATTRIBUTIONS.md, and the map link is a plain Google Maps search.
"""
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from app.catalog.load import load_catalog
from app.config import ROOT
from app.lib.money import amount

IMAGES_DIR = (ROOT / "images").resolve()
ATTRIBUTIONS = IMAGES_DIR / "ATTRIBUTIONS.md"
MAPS_SEARCH = "https://www.google.com/maps/search/?api=1&query="

# A credit row: | `images/attractions/ATT-KYO-001.jpg` | Used for | [Source](url) | Author | [License](url) |
_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|(.*)\|\s*$")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")


@lru_cache(maxsize=1)
def load_credits() -> dict[str, str]:
    """Image path (as the catalog writes it) -> credit line, parsed from images/ATTRIBUTIONS.md."""
    if not ATTRIBUTIONS.is_file():
        return {}
    credits: dict[str, str] = {}
    for line in ATTRIBUTIONS.read_text(encoding="utf-8").splitlines():
        m = _ROW.match(line)
        if not m:
            continue
        cells = [c.strip() for c in m.group(2).split("|")]
        if len(cells) < 4:
            continue  # not an attribution row (e.g. the header or separator)
        author = _LINK.sub(r"\1", cells[2]).strip()
        license_name = _LINK.sub(r"\1", cells[3]).strip()
        if author and license_name:
            credits[m.group(1)] = f"Photo: {author}, {license_name} (Wikimedia Commons)"
    return credits


def _record(attraction_id: str) -> dict | None:
    return load_catalog().indexes.attractions_by_id.get(attraction_id)


def image_file(record: dict) -> Path | None:
    """The photo file for a catalog record, only when it resolves inside images/ and exists."""
    rel = record.get("image")
    if not rel:
        return None
    path = (ROOT / rel).resolve()
    if not path.is_relative_to(IMAGES_DIR) or not path.is_file():
        return None
    return path


def attraction_detail(attraction_id: str) -> dict | None:
    """The drawer's data for one attraction, or None when the id is not in the catalog."""
    a = _record(attraction_id)
    if a is None:
        return None
    country = load_catalog().indexes.country_by_city.get(a["city"], {})
    has_image = image_file(a) is not None
    child = a.get("child_price")
    query = f"{a['name']}, {a['city']}, {country.get('name', '')}".rstrip(", ")
    return {
        "attraction_id": a["attraction_id"],
        "name": a["name"],
        "name_ja": a.get("name_ja"),
        "city": a["city"],
        "country": country.get("name"),
        "category": a["category"],
        "open_days": list(a["open_days"]),
        "open_from": a["open_from"],
        "open_until": a["open_until"],
        "closed_dates": list(a.get("closed_dates") or []),
        "visit_minutes": a["visit_minutes"],
        "child_friendly": a.get("child_friendly"),
        "accessible": a.get("accessible"),
        "price_per_person_inr": amount(a["price_per_person"]),
        "child_price_inr": amount(child) if child is not None else None,
        "image_url": f"/api/attractions/{a['attraction_id']}/image" if has_image else None,
        "image_credit": load_credits().get(a["image"]) if has_image else None,
        "maps_url": MAPS_SEARCH + quote(query, safe=""),
    }


def attraction_image_path(attraction_id: str) -> Path | None:
    """The JPEG path for an attraction id, or None (unknown id, no image, or path outside images/)."""
    a = _record(attraction_id)
    return image_file(a) if a else None
