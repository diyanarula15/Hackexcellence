"""FastAPI entrypoint. Run: uvicorn app.main:app --app-dir backend --reload --port 8000"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.catalog.load import load_catalog
from app.db import create_tables
from app.routes import date_prices, health, meta, packages, validate


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
app.include_router(date_prices.router, prefix="/api")  # Phase 7A Price Landscape (read-only)
