"""Photo links and credits for catalog records (attractions and hotels). Read-only.

The photos are the dataset's own files in images/ (Wikimedia Commons, credits in
images/ATTRIBUTIONS.md). Only a record whose `image` resolves to an existing file inside images/
gets a URL; nothing is fetched from anywhere else, and the frontend loads photos only from our API.
"""

import re
from functools import lru_cache

from app.services.attraction_info import ATTRIBUTIONS, image_file, load_credits

# A credit row: | `images/...jpg` | Used for | [Source](url) | Author | [License](url) |
_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|(.*)\|\s*$")
_LINK = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")


def attraction_photo_url(record: dict | None) -> str | None:
    """API URL of an attraction's photo, or None when the dataset has no photo for it."""
    if not record or image_file(record) is None:
        return None
    return f"/api/attractions/{record['attraction_id']}/image"


def hotel_photo_url(record: dict | None) -> str | None:
    """API URL of a hotel's photo (a shared sample room photo), or None when there is none."""
    if not record or image_file(record) is None:
        return None
    return f"/api/hotels/{record['hotel_id']}/image"


def photo_credit(record: dict | None) -> str | None:
    """The credit line for a record's photo, or None when it has no photo."""
    if not record or image_file(record) is None:
        return None
    return load_credits().get(record["image"])


def _link(cell: str) -> tuple[str, str | None]:
    m = _LINK.search(cell)
    return (m.group(1).strip(), m.group(2).strip()) if m else (cell.strip(), None)


@lru_cache(maxsize=1)
def credit_rows() -> tuple[dict, ...]:
    """Every row of images/ATTRIBUTIONS.md, for the photo credits list."""
    if not ATTRIBUTIONS.is_file():
        return ()
    rows = []
    for line in ATTRIBUTIONS.read_text(encoding="utf-8").splitlines():
        m = _ROW.match(line)
        if not m:
            continue
        cells = [c.strip() for c in m.group(2).split("|")]
        if len(cells) < 4:
            continue
        source, source_url = _link(cells[1])
        author, _ = _link(cells[2])
        license_name, license_url = _link(cells[3])
        if not (author and license_name):
            continue
        rows.append(
            {
                "file": m.group(1),
                "kind": "hotel" if "/hotels/" in m.group(1) else "attraction",
                "used_for": cells[0],
                "source": source,
                "source_url": source_url,
                "author": author,
                "license": license_name,
                "license_url": license_url,
            }
        )
    return tuple(rows)
