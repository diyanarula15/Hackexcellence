"""Paths and constants. Nothing about cities, countries or airports lives here."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG_DIR = ROOT / "data" / "catalog"
DB_PATH = ROOT / "backend" / "holiday.db"
