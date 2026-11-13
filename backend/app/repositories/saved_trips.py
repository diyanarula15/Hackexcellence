"""Saved trips: named bookmarks on existing packages. A bookmark never copies, re-plans or books.

The `saved_trips` table holds only (package_id, name, saved_at, updated_at). Everything shown about
a trip (country, dates, cities, travelers, total, status, booking reference) is read from the
`packages` row and, when confirmed, the `reservations` row, so a bookmark can never disagree with
the package it points to. No write here touches `packages` or `reservations`.

Writes run in one BEGIN IMMEDIATE transaction, so a save or rename cannot interleave with a
confirmation of the same package.
"""

import json
from datetime import datetime, timezone

from app.db import connect
from app.engine.model import Package
from app.repositories.packages import PackageNotFound, package_from_dict

BOOKED_STATUS = "BOOKED"
MAX_NAME_LENGTH = 60


class SavedTripNotFound(LookupError):
    pass


class PackageBooked(Exception):
    """The package is a confirmed reservation, so it cannot be bookmarked or renamed as a plan."""

    def __init__(self, package_id: str):
        super().__init__(f"package {package_id} is already booked")
        self.package_id = package_id


class InvalidTripName(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_name(raw) -> str:
    """The trimmed name, or InvalidTripName: 1 to 60 printable characters."""
    if not isinstance(raw, str):
        raise InvalidTripName("Enter a name for this trip.")
    name = raw.strip()
    if not 1 <= len(name) <= MAX_NAME_LENGTH:
        raise InvalidTripName(f"Trip names must be 1 to {MAX_NAME_LENGTH} characters.")
    if not name.isprintable():
        raise InvalidTripName("Trip names can only contain printable characters.")
    return name


def _month(day) -> str:
    return day.strftime("%b")


def default_name(package: Package) -> str:
    """"<Country> · <d Mon>–<d Mon YYYY>", e.g. "Japan · 10 Apr–16 Apr 2027"."""
    start, end = package.plan.start_date, package.plan.end_date
    return (
        f"{package.country_name} · {start.day} {_month(start)}–{end.day} {_month(end)} {end.year}"
    )


def _package(row) -> Package:
    return package_from_dict(json.loads(row["package_json"]))


def _card(row, saved, reference: str | None) -> dict:
    """The saved-trip card: package facts from the packages row, bookmark facts from saved_trips."""
    package = _package(row)
    start, end = package.plan.start_date, package.plan.end_date
    return {
        "package_id": row["id"],
        "name": saved["name"],
        "country": package.country_name,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "nights": (end - start).days,
        "travelers": {"adults": package.adults, "child_ages": list(package.child_ages)},
        "cities": list(package.plan.cities),
        "total_inr": row["total_inr"],
        "status": row["status"],
        "booking_reference": reference,
        "version": row["version"],
        "saved_at": saved["saved_at"],
        "updated_at": saved["updated_at"],
    }


_CARD_SQL = """
SELECT p.id, p.package_json, p.total_inr, p.version, p.status, s.name, s.saved_at, s.updated_at,
       r.reference AS reference
FROM saved_trips s
JOIN packages p ON p.id = s.package_id
LEFT JOIN reservations r ON r.package_id = s.package_id
"""


def _load_card(conn, package_id: str) -> dict:
    row = conn.execute(_CARD_SQL + " WHERE s.package_id = ?", (package_id,)).fetchone()
    if row is None:
        raise SavedTripNotFound(package_id)
    return _card(row, row, row["reference"])


def save_trip(package_id: str, name: str | None) -> tuple[dict, bool]:
    """Bookmark a PLANNED package. Returns (card, created).

    `name` None keeps the existing name (or the default for a new bookmark). Raises PackageNotFound,
    PackageBooked, or InvalidTripName (checked before anything is written).
    """
    if name is not None:
        name = clean_name(name)
    with connect(immediate=True) as conn:
        row = conn.execute("SELECT * FROM packages WHERE id = ?", (package_id,)).fetchone()
        if row is None:
            raise PackageNotFound(package_id)
        if row["status"] == BOOKED_STATUS:
            raise PackageBooked(package_id)
        existing = conn.execute(
            "SELECT * FROM saved_trips WHERE package_id = ?", (package_id,)
        ).fetchone()
        now = _now()
        if existing is None:
            conn.execute(
                "INSERT INTO saved_trips (package_id, name, saved_at, updated_at) VALUES (?, ?, ?, ?)",
                (package_id, name or default_name(_package(row)), now, now),
            )
            created = True
        else:
            if name is not None:
                conn.execute(
                    "UPDATE saved_trips SET name = ?, updated_at = ? WHERE package_id = ?",
                    (name, now, package_id),
                )
            created = False
        return _load_card(conn, package_id), created


def list_trips() -> list[dict]:
    """Every saved trip, most recently updated first."""
    with connect() as conn:
        rows = conn.execute(
            _CARD_SQL + " ORDER BY s.updated_at DESC, s.rowid DESC"
        ).fetchall()
        return [_card(row, row, row["reference"]) for row in rows]


def rename_trip(package_id: str, name: str) -> dict:
    """Give a saved trip a new name. Raises InvalidTripName, SavedTripNotFound or PackageBooked."""
    name = clean_name(name)
    with connect(immediate=True) as conn:
        row = conn.execute(
            "SELECT status FROM packages WHERE id = ?", (package_id,)
        ).fetchone()
        if row is None:
            raise SavedTripNotFound(package_id)
        if row["status"] == BOOKED_STATUS:
            raise PackageBooked(package_id)
        cur = conn.execute(
            "UPDATE saved_trips SET name = ?, updated_at = ? WHERE package_id = ?",
            (name, _now(), package_id),
        )
        if cur.rowcount == 0:
            raise SavedTripNotFound(package_id)
        return _load_card(conn, package_id)


def remove_trip(package_id: str) -> None:
    """Delete only the bookmark. The package and any reservation are kept."""
    with connect() as conn:
        cur = conn.execute("DELETE FROM saved_trips WHERE package_id = ?", (package_id,))
        if cur.rowcount == 0:
            raise SavedTripNotFound(package_id)
