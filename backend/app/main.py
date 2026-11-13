"""FastAPI entrypoint. Run: uvicorn app.main:app --app-dir backend --reload --port 8000"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.catalog.load import load_catalog
from app.db import create_tables
from app.routes import (
    natural_language,
    city_plans,
    alternatives,
    attractions,
    date_prices,
    health,
    hotels,
    meta,
    package_options,
    packages,
    reservations,
    saved_trips,
    validate,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_catalog()  # fail fast with a clear CatalogError if the dataset is invalid
    create_tables()  # SQLite file + tables for packages and reservations
    yield


app = FastAPI(title="Build My Holiday", lifespan=lifespan)
app.include_router(health.router, prefix="/api")
app.include_router(meta.router, prefix="/api")
app.include_router(validate.router, prefix="/api")
app.include_router(packages.router, prefix="/api")

app.include_router(reservations.router, prefix="/api")
app.include_router(date_prices.router, prefix="/api")  # Phase 7A Price Landscape (read-only)
app.include_router(alternatives.router, prefix="/api")  # trip alternatives (read-only)
app.include_router(attractions.router, prefix="/api")  # attraction details + images (read-only)
app.include_router(
    hotels.router, prefix="/api"
)  # hotel details + photos, photo credits (read-only)
app.include_router(saved_trips.router, prefix="/api")  # saved trips (bookmarks on saved packages)
app.include_router(
    package_options.router, prefix="/api"
)  # several package options; save only the chosen one

app.include_router(city_plans.router, prefix="/api")
app.include_router(natural_language.router, prefix="/api")
