"""FastAPI entrypoint. Run: uvicorn app.main:app --app-dir backend --reload --port 8000"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.catalog.load import load_catalog
from app.routes import health, meta, validate


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_catalog()  # fail fast with a clear CatalogError if the dataset is invalid
    yield


app = FastAPI(title="Build My Holiday", lifespan=lifespan)
app.include_router(health.router, prefix="/api")
app.include_router(meta.router, prefix="/api")
app.include_router(validate.router, prefix="/api")
