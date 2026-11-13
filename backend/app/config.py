"""Paths and constants. Nothing about cities, countries or airports lives here."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG_DIR = ROOT / "data" / "catalog"
# SQLite file for user state (packages, reservations). Never the catalog files.
# The HOLIDAY_DB_PATH environment variable overrides it (tests use a temporary file); see app/db.py.
DB_PATH = ROOT / "backend" / "app.db"
