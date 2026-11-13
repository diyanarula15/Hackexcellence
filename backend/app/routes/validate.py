from dataclasses import asdict

from fastapi import APIRouter, Body, Query
from fastapi.responses import JSONResponse

from app.catalog.load import load_catalog
from app.rules.common import EDITED, INITIAL
from app.validate.validate_trip import validate_trip

router = APIRouter()


@router.post("/validate")
def validate(trip: dict = Body(...), mode: str = Query(INITIAL, pattern=f"^({INITIAL}|{EDITED})$")):
    """Validate a trip JSON. Malformed JSON -> 422 (FastAPI). Schema errors -> 422 with violations.
    Rule failures in a well-formed trip -> 200 with valid=false and the violations."""
    violations = [asdict(x) for x in validate_trip(trip, load_catalog(), mode)]
    body = {"valid": not violations, "violations": violations}
    if any(x["rule"].startswith("R-SCHEMA") for x in violations):
        return JSONResponse(status_code=422, content=body)
    return body
