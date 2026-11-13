"""Package storage: the engine `Package` <-> one row of the `packages` table.

The full internal package is stored as JSON (`package_json`) together with the traveler's original
request (`request_json`) and the authoritative integer total (`total_inr`). Reading a package back
rebuilds the exact same `Package` value (same ids, dates, times, quantities and prices); the planner
is never called again, so opening a saved package can never swap its flights or hotels.

Serialization is driven by the dataclass type hints of app.engine.model, so dates come back as
`date`, times as `datetime`, tuples as tuples and ints as ints. Any type mismatch raises instead of
guessing.
"""

import json
import logging
import uuid
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime, timezone
from types import NoneType, UnionType
from typing import Union, get_args, get_origin, get_type_hints

from app.db import connect
from app.engine.model import Package
from app.rules.common import INITIAL

log = logging.getLogger(__name__)

PLANNED = "PLANNED"
SCHEMA_VERSION = 1  # version of the package_json layout


class PackageNotFound(LookupError):
    pass


class VersionConflict(Exception):
    """The package changed since the caller read it (optimistic concurrency check failed)."""

    def __init__(self, package_id: str, expected: int, current: int):
        super().__init__(f"package {package_id} is at version {current}, not {expected}")
        self.package_id, self.expected, self.current = package_id, expected, current


class PackageIntegrityError(Exception):
    """A stored row cannot be turned back into the package it claims to be."""


@dataclass(frozen=True)
class StoredPackage:
    id: str
    package: Package
    request: dict
    total_inr: int
    version: int
    status: str
    validation_mode: str
    created_at: str
    updated_at: str


# ------------------------------------------------------------------ serialization


def _encode(value):
    if is_dataclass(value):
        return {f.name: _encode(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, (list, tuple)):
        return [_encode(v) for v in value]
    if isinstance(value, (date, datetime)):  # datetime first-class: isoformat keeps the time part
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float)):
        return value
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _decode(tp, value):
    """Rebuild a value of type `tp` (a model type hint) from its JSON form."""
    origin = get_origin(tp)
    if origin in (Union, UnionType):  # only "X | None" is used in the model
        if value is None:
            return None
        (inner,) = [a for a in get_args(tp) if a is not NoneType]
        return _decode(inner, value)
    if origin is tuple:
        item_tp = get_args(tp)[0]  # tuple[X, ...]
        if not isinstance(value, list):
            raise TypeError(f"expected a list for {tp}, got {type(value).__name__}")
        return tuple(_decode(item_tp, v) for v in value)
    if is_dataclass(tp):
        if not isinstance(value, dict):
            raise TypeError(f"expected an object for {tp.__name__}")
        hints = get_type_hints(tp)
        kwargs = {
            f.name: _decode(hints[f.name], value[f.name]) for f in fields(tp) if f.name in value
        }
        return tp(**kwargs)  # a missing required field raises TypeError
    if tp is datetime:
        return datetime.fromisoformat(value)
    if tp is date:
        return date.fromisoformat(value)
    if tp is int:
        if type(value) is not int:
            raise TypeError(f"expected an int, got {value!r}")
        return value
    if tp is str:
        if not isinstance(value, str):
            raise TypeError(f"expected a string, got {value!r}")
        return value
    raise TypeError(f"unsupported type {tp!r}")


def package_to_dict(package: Package) -> dict:
    """JSON-ready dict of the complete internal package."""
    return {"schema_version": SCHEMA_VERSION, **_encode(package)}


def package_from_dict(data: dict) -> Package:
    """Inverse of package_to_dict. Raises TypeError / ValueError on a malformed document."""
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unsupported package schema_version {data.get('schema_version')!r}")
    body = {k: v for k, v in data.items() if k != "schema_version"}
    return _decode(Package, body)


def _package_json(package: Package) -> str:
    """Serialize fully and prove the round trip before anything touches the database."""
    text = json.dumps(package_to_dict(package), ensure_ascii=False, separators=(",", ":"))
    if package_from_dict(json.loads(text)) != package:
        raise PackageIntegrityError("package does not survive serialization unchanged")
    return text


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row_to_stored(row) -> StoredPackage:
    try:
        package = package_from_dict(json.loads(row["package_json"]))
        request = json.loads(row["request_json"])
    except (TypeError, ValueError, KeyError) as e:
        raise PackageIntegrityError(f"package {row['id']} cannot be read: {e}") from e
    if package.total != row["total_inr"]:
        raise PackageIntegrityError(
            f"package {row['id']}: stored total {row['total_inr']} != items total {package.total}"
        )
    return StoredPackage(
        id=row["id"],
        package=package,
        request=request,
        total_inr=row["total_inr"],
        version=row["version"],
        status=row["status"],
        validation_mode=row["validation_mode"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ------------------------------------------------------------------ repository


def save_package(package: Package, *, request: dict) -> str:
    """Store a new, already validated package and return its id (a UUID).

    The package's trip_id is set to that id, so the export's trip identity matches the saved package.
    New packages always start PLANNED, at version 1, in INITIAL validation mode.
    """
    if package.status != PLANNED:
        raise ValueError(f"a new package must be {PLANNED}, got {package.status!r}")
    package_id = str(uuid.uuid4())
    package = package.with_(trip_id=package_id)
    package_json = _package_json(package)
    request_json = json.dumps(request, ensure_ascii=False, default=str)
    now = _now()
    with connect() as conn:
        conn.execute(
            "INSERT INTO packages (id, request_json, package_json, total_inr, version, status,"
            " validation_mode, created_at, updated_at) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)",
            (package_id, request_json, package_json, package.total, PLANNED, INITIAL, now, now),
        )
    log.info("saved package %s (total INR %s)", package_id, package.total)
    return package_id


def get_package(package_id: str) -> StoredPackage | None:
    """The stored package exactly as saved, or None when no package has this id."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM packages WHERE id = ?", (package_id,)).fetchone()
    return None if row is None else _row_to_stored(row)


def update_package(
    package_id: str, package: Package, *, expected_version: int, validation_mode: str
) -> int:
    """Replace a stored package if it is still at `expected_version`; return the new version.

    Raises PackageNotFound for an unknown id and VersionConflict when another change got there first.
    (Used by Phase 5 package changes.)
    """
    if package.trip_id != package_id:
        raise ValueError("package.trip_id must equal the id it is stored under")
    package_json = _package_json(package)
    with connect() as conn:
        cur = conn.execute(
            "UPDATE packages SET package_json = ?, total_inr = ?, status = ?, validation_mode = ?,"
            " version = version + 1, updated_at = ? WHERE id = ? AND version = ?",
            (
                package_json,
                package.total,
                package.status,
                validation_mode,
                _now(),
                package_id,
                expected_version,
            ),
        )
        if cur.rowcount == 0:
            row = conn.execute(
                "SELECT version FROM packages WHERE id = ?", (package_id,)
            ).fetchone()
            if row is None:
                raise PackageNotFound(package_id)
            raise VersionConflict(package_id, expected_version, row["version"])
    return expected_version + 1
