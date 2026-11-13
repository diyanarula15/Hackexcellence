"""Atomic confirmation of the exact saved version. No planner or change engine is used."""
import json
import sqlite3
from dataclasses import asdict

from app.catalog.load import load_catalog
from app.db import connect
from app.export.to_trip import to_trip_json
from app.lib.catalog_identity import catalog_fingerprint
from app.lib.ref import generate_reference
from app.repositories import packages
from app.repositories.reservations import Reservation, from_row
from app.rules.common import INITIAL, EDITED
from app.validate.validate_trip import validate_trip

MAX_REFERENCE_ATTEMPTS = 20


class ConfirmationError(Exception):
    def __init__(self, code, message, status=422, **details):
        super().__init__(message)
        self.status = status
        self.payload = {"error": code, "message": message, **details}


def confirm_package(package_id: str, base_version: int) -> Reservation:
    # Every read/check/write shares the same reserved write lock as Phase 5 modifications.
    # Returning from this block commits BEFORE the caller receives the result.
    try:
        with connect(immediate=True) as conn:
            existing = conn.execute("SELECT * FROM reservations WHERE package_id = ?", (package_id,)).fetchone()
            if existing is not None:
                return from_row(existing)  # retries ignore stale version and changed/unavailable catalogs
            row = conn.execute("SELECT * FROM packages WHERE id = ?", (package_id,)).fetchone()
            if row is None:
                raise ConfirmationError("PACKAGE_NOT_FOUND", "This holiday package could not be found.", 404)
            if row["version"] != base_version:
                raise ConfirmationError("PACKAGE_VERSION_CONFLICT", "Reload the latest holiday before confirming.", 409,
                                        current_version=row["version"])
            if row["status"] != packages.PLANNED:
                raise ConfirmationError("RESERVATION_CREATION_FAILED", "This holiday cannot be confirmed in its current state.", 409)
            catalog = load_catalog()
            if row["catalog_fingerprint"] != catalog_fingerprint(catalog):
                raise ConfirmationError("PACKAGE_CATALOG_MISMATCH", "The package's source catalog is unavailable or has changed. Plan a new holiday.", 409)
            stored = packages._row_to_stored(row)
            if (stored.package.status != packages.PLANNED
                    or stored.package.booking_reference is not None
                    or stored.package.trip_id != package_id
                    or stored.validation_mode not in (INITIAL, EDITED)):
                raise ConfirmationError("PACKAGE_VALIDATION_FAILED", "The saved holiday has inconsistent booking state.")
            planned_trip = to_trip_json(stored.package, catalog)
            violations = validate_trip(planned_trip, catalog, mode=stored.validation_mode)
            if violations or planned_trip["total_inr"] != stored.total_inr:
                raise ConfirmationError("PACKAGE_VALIDATION_FAILED", "The saved holiday did not pass validation.",
                                        violations=[asdict(v) for v in violations])
            now = packages._now()
            for _ in range(MAX_REFERENCE_ATTEMPTS):
                reference = generate_reference()
                booked = stored.package.with_(status="BOOKED", booking_reference=reference)
                snapshot = to_trip_json(booked, catalog)
                # The adapter must preserve the whole original trip, changing only item booking state.
                violations = validate_trip(snapshot, catalog, mode=stored.validation_mode)
                if violations:
                    raise ConfirmationError("PACKAGE_VALIDATION_FAILED", "The booked holiday did not pass validation.",
                                            violations=[asdict(v) for v in violations])
                try:
                    conn.execute("INSERT INTO reservations (reference, package_id, trip_json, created_at) VALUES (?, ?, ?, ?)",
                                 (reference, package_id, json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")), now))
                except sqlite3.IntegrityError:
                    # Retry ONLY a reference collision, never a foreign-key or other invariant failure.
                    if conn.execute("SELECT 1 FROM reservations WHERE reference = ?", (reference,)).fetchone():
                        continue
                    raise
                conn.execute("UPDATE packages SET status = 'BOOKED', package_json = ?, updated_at = ?, version = version + 1 WHERE id = ?",
                             (packages._package_json(booked), now, package_id))
                return Reservation(reference, package_id, snapshot, now)
            raise ConfirmationError("RESERVATION_CREATION_FAILED", "Could not allocate a reservation reference. Please retry.", 503)
    except packages.PackageIntegrityError as exc:
        raise ConfirmationError("PACKAGE_VALIDATION_FAILED", "The saved holiday cannot be validated.") from exc
    except sqlite3.Error as exc:
        raise ConfirmationError("RESERVATION_CREATION_FAILED", "The holiday could not be confirmed. Please retry.", 503) from exc
