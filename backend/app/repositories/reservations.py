"""Read-only retrieval of independently persisted, confirmed trip snapshots."""
import json
from dataclasses import dataclass

from app.db import connect


@dataclass(frozen=True)
class Reservation:
    reference: str
    package_id: str
    trip_json: dict
    created_at: str

    def response(self) -> dict:
        return {
            "status": "BOOKED", "package_id": self.package_id,
            "reference": self.reference, "total_inr": self.trip_json["total_inr"],
            "confirmed_at": self.created_at, "trip": self.trip_json,
        }


def from_row(row) -> Reservation:
    return Reservation(row["reference"], row["package_id"], json.loads(row["trip_json"]), row["created_at"])


def get_reservation(reference: str) -> Reservation | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM reservations WHERE reference = ?", (reference,)).fetchone()
    return None if row is None else from_row(row)
