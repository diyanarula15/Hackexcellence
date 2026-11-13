"""Trip alternatives API: POST /api/trip-alternatives. Read-only.

Request: the 7 trip fields used by POST /api/packages.
  200  {original, original_status, suggestions: [{kind, label, change, request, min_total_inr,
        within_budget}], planner_searches}
  422  INVALID_REQUEST (same shape as /api/packages)
  503  SEARCH_BUSY (too many searches are running at once; retry)

Nothing here writes to the database.
Mount with `app.include_router(alternatives.router, prefix="/api")` (see app/main.py).
"""

import threading
from typing import Any

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from app.catalog.load import load_catalog
from app.routes.packages import InvalidRequest, parse_trip_request
from app.services.trip_alternatives import find_alternatives

router = APIRouter()

MAX_CONCURRENT_SEARCHES = 2
WAIT_FOR_SLOT_S = 30.0
_slots = threading.BoundedSemaphore(MAX_CONCURRENT_SEARCHES)


# A sync handler: FastAPI runs it in a worker thread, so the CPU-bound planner never blocks the event loop.
@router.post("/trip-alternatives")
def trip_alternatives(body: Any = Body(...)):
    catalog = load_catalog()
    try:
        request, _original = parse_trip_request(body, catalog)
    except InvalidRequest as e:
        return JSONResponse(status_code=422, content=e.payload())
    if not _slots.acquire(timeout=WAIT_FOR_SLOT_S):
        return JSONResponse(status_code=503, content={
            "status": "SEARCH_BUSY", "error": "SEARCH_BUSY",
            "message": "Alternatives are being searched for other travelers. Please try again shortly."})
    try:
        return find_alternatives(request, catalog)
    finally:
        _slots.release()
