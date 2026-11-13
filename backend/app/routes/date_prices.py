"""Price Landscape API (Phase 7A): proven cheapest complete holiday per start date. Read-only.

  POST /api/date-prices

Request: the 7 trip fields used by POST /api/packages (departure, country, start_date, nights,
adults, child_ages, budget), plus optional range_start / range_end (YYYY-MM-DD, both or neither;
default = the calendar month of start_date; at most MAX_RANGE_DAYS days).

  200  {dates: [{date, status, min_total_inr, proven_minimum, within_budget,
                 difference_vs_reference_inr, proven_savings_inr, incomplete_reason?}, ...],
        range_fully_evaluated, lowest_proven_date, lowest_proven_total_inr,
        highest_proven_total_inr, cheapest_date, cheapest_total_inr, comparison, diagnostics, ...}
  422  INVALID_REQUEST (same shape as /api/packages) or INVALID_RANGE
  503  CALENDAR_BUSY (too many calendars are being computed at once; retry)

status is FOUND | INFEASIBLE | SEARCH_INCOMPLETE. Only FOUND cells have a price, and it is always a
proven minimum. Cells with SEARCH_INCOMPLETE / incomplete_reason TIME_BUDGET can be fetched by
repeating the same request: finished dates are cached, so it continues where it stopped.
cheapest_date is only set when range_fully_evaluated is true; lowest_proven_* is always the lowest
among proven dates. Budget does not change any price; it only fills within_budget.

Nothing here writes to the database: no package, version or reservation is created or changed.

Mount with `app.include_router(date_prices.router, prefix="/api")` (see app/main.py).
"""

import threading
from datetime import date
from typing import Any

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from app.catalog.load import load_catalog
from app.routes.packages import InvalidRequest, parse_trip_request
from app.services.date_prices import MAX_RANGE_DAYS, DateRangeError, build_calendar, calendar_payload

router = APIRouter()

MAX_CONCURRENT_CALENDARS = 2           # the planner is CPU-bound; more in parallel only queues
WAIT_FOR_SLOT_S = 30.0
_slots = threading.BoundedSemaphore(MAX_CONCURRENT_CALENDARS)


def _range_error(message: str) -> JSONResponse:
    return JSONResponse(status_code=422, content={
        "status": "INVALID_RANGE", "error": "INVALID_RANGE", "message": message,
        "field_errors": {"range": [message]}, "reasons": [message]})


def _parse_day(body: dict, name: str) -> date | None:
    value = body.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise DateRangeError(f"{name} must be a date written YYYY-MM-DD.")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise DateRangeError(f"{name} '{value}' is not a valid date (YYYY-MM-DD).") from None


# A sync handler: FastAPI runs it in a worker thread, so the CPU-bound planner never blocks the
# event loop; the semaphore keeps at most MAX_CONCURRENT_CALENDARS of them busy at once.
@router.post("/date-prices")
def date_prices(body: Any = Body(...)):
    catalog = load_catalog()
    try:
        request, _original = parse_trip_request(body, catalog)
    except InvalidRequest as e:
        return JSONResponse(status_code=422, content=e.payload())
    try:
        range_start, range_end = _parse_day(body, "range_start"), _parse_day(body, "range_end")
    except DateRangeError as e:
        return _range_error(str(e))
    if not _slots.acquire(timeout=WAIT_FOR_SLOT_S):
        return JSONResponse(status_code=503, content={
            "status": "CALENDAR_BUSY", "error": "CALENDAR_BUSY",
            "message": "Prices are being calculated for other travelers. Please try again shortly."})
    try:
        cal = build_calendar(request, catalog, range_start, range_end)
    except DateRangeError as e:
        return _range_error(str(e))
    finally:
        _slots.release()
    payload = calendar_payload(cal, catalog)
    payload["max_range_days"] = MAX_RANGE_DAYS
    return payload
