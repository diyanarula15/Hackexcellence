"""Multi-itinerary search: several complete valid packages for one request; only the chosen one is saved.
Registered in app/main.py under /api.

  POST /api/package-options                    200 OPTIONS (nothing saved) | the POST /api/packages answer
                                               for any non-FOUND planner result | 422 INVALID_REQUEST
  POST /api/package-options/{search_id}/select 201 saved (200 when that option was already chosen) |
                                               404 SEARCH_EXPIRED | 404 OPTION_NOT_FOUND | 422 | 500
"""
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.catalog.load import load_catalog
from app.engine.build import FOUND, MINIMUM_COST, WITHIN_BUDGET
from app.engine.options import find_package_options
from app.routes.packages import (InvalidRequest, _load, GENERAL, package_envelope, parse_trip_request,
                                 respond_to_planning)
from app.services import package_options as store

router = APIRouter()
OPTION_COUNT = 3


class SelectBody(BaseModel):
    option_id: str


@router.post("/package-options")
def search_package_options(body: Annotated[Any, Body()] = None):
    catalog = load_catalog()
    try:
        trip, original = parse_trip_request(body, catalog)
    except InvalidRequest as e:
        return JSONResponse(status_code=422, content=e.payload())
    objective = body.get("objective", WITHIN_BUDGET) if isinstance(body, dict) else WITHIN_BUDGET
    if objective not in (WITHIN_BUDGET, MINIMUM_COST):
        return JSONResponse(status_code=422, content=InvalidRequest([{
            "field": GENERAL, "rule": "R-REQ-OBJECTIVE",
            "message": "objective must be WITHIN_BUDGET or MINIMUM_COST."}]).payload())

    found = find_package_options(trip, catalog, objective, count=OPTION_COUNT)
    if found.primary.status != FOUND or not found.packages:
        return respond_to_planning(trip, original, found.primary, catalog)
    return JSONResponse(status_code=200,
                        content=store.open_search(trip, original, objective, found, catalog))


@router.post("/package-options/{search_id}/select")
def select_package_option(search_id: str, body: SelectBody):
    catalog = load_catalog()
    try:
        package_id, created = store.choose(search_id, body.option_id, catalog)
    except store.SearchExpired:
        return JSONResponse(status_code=404, content={
            "error": "SEARCH_EXPIRED",
            "message": "These options have expired. Search again to see fresh ones."})
    except store.OptionNotFound:
        return JSONResponse(status_code=404, content={
            "error": "OPTION_NOT_FOUND",
            "message": "That option is not one of these holiday options."})
    except store.PlanInvalid as e:
        return JSONResponse(status_code=500, content={
            "error": "PACKAGE_INVALID",
            "message": "The planner built a package that breaks a travel rule, so it was not saved.",
            "violations": [asdict(v) for v in e.violations]})
    stored, error = _load(package_id)
    if error is not None:
        return error
    return JSONResponse(status_code=201 if created else 200,
                        content=package_envelope(stored, catalog))
