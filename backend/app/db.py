"""SQLite persistence with the built-in sqlite3 module.

One short-lived connection per operation: `connect()` opens it, turns on foreign keys, commits when
the block succeeds, rolls back when it raises, and always closes it. All SQL is parameterized.

The database file is created on backend start (`create_tables()` in the FastAPI lifespan). It holds
user state only; the catalog files under data/catalog are never written.
"""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS packages (
    id TEXT PRIMARY KEY,
    request_json TEXT NOT NULL,
    package_json TEXT NOT NULL,
    total_inr INTEGER NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL
        CHECK (status IN ('PLANNED', 'BOOKED')),
    catalog_fingerprint TEXT,
    validation_mode TEXT NOT NULL DEFAULT 'INITIAL',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reservations (
    reference TEXT PRIMARY KEY,
    package_id TEXT NOT NULL UNIQUE,
    trip_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (package_id) REFERENCES packages(id)
);
"""


def db_path() -> Path:
    """The database file: $HOLIDAY_DB_PATH when set, else backend/app.db. Read on every call so a
    test can point the app at a temporary file."""
    return Path(os.environ.get("HOLIDAY_DB_PATH") or DB_PATH)


@contextmanager
def connect(immediate: bool = False):
    """Yield a connection inside one transaction: commit on success, roll back on error, always close.

    `immediate=True` takes SQLite's write lock up front (BEGIN IMMEDIATE), so a read-check-write
    sequence inside the block cannot interleave with another writer.
    """
    conn = sqlite3.connect(
        db_path(), timeout=5.0, isolation_level=None if immediate else "DEFERRED"
    )
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        if immediate:
            conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def create_tables() -> None:
    """Create the database file and both tables if they do not exist. Safe to call repeatedly."""
    db_path().parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)
        # Additive migration: legacy packages retain NULL identity and must be replanned.
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(packages)")}
        if "catalog_fingerprint" not in columns:
            conn.execute("ALTER TABLE packages ADD COLUMN catalog_fingerprint TEXT")
        conn.executescript("""
        CREATE TRIGGER IF NOT EXISTS reservations_no_update
        BEFORE UPDATE ON reservations BEGIN
            SELECT RAISE(ABORT, 'confirmed reservations are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS reservations_no_delete
        BEFORE DELETE ON reservations BEGIN
            SELECT RAISE(ABORT, 'confirmed reservations are retained');
        END;
        CREATE TRIGGER IF NOT EXISTS reservations_valid_reference
        BEFORE INSERT ON reservations
        WHEN NEW.reference IS NULL OR length(NEW.reference) != 10 OR NEW.reference GLOB '*[^0-9]*'
        BEGIN SELECT RAISE(ABORT, 'invalid reservation reference'); END;
        CREATE TRIGGER IF NOT EXISTS booked_package_no_update
        BEFORE UPDATE ON packages WHEN OLD.status = 'BOOKED'
        BEGIN SELECT RAISE(ABORT, 'booked packages are immutable'); END;
        """)
