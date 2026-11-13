"""Paths and constants. Nothing about cities, countries or airports lives here."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG_DIR = ROOT / "data" / "catalog"
# SQLite file for user state (packages, reservations). Never the catalog files.
# The HOLIDAY_DB_PATH environment variable overrides it (tests use a temporary file); see app/db.py.
DB_PATH = ROOT / "backend" / "app.db"

# Airport transfer timing (problem statement section 4). Change a value here and the rules, the
# planner, the change checks, delay resilience and every message that names it follow.
# the arrival pickup is at least this long after the flight lands
PICKUP_AFTER_LANDING_MINUTES = 60
# the traveler reaches the airport at least this long before the return flight departs
AIRPORT_BEFORE_DEPARTURE_MINUTES = 180
