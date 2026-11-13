"""Simulated holiday confirmation, reference lookup and immutable judge export."""
import json
import logging
import re
from typing import Annotated, Any

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError

from app.repositories.reservations import get_reservation
from app.services.reservations import ConfirmationError, confirm_package

router = APIRouter()
log = logging.getLogger(__name__)


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_version: StrictInt = Field(ge=1)


@router.post("/packages/{package_id}/confirm")
def confirm(package_id: str, body: Annotated[Any, Body()] = None):
    try:
        request = ConfirmRequest.model_validate(body)
    except ValidationError:
        return JSONResponse(status_code=422, content={"error": "INVALID_CONFIRMATION_REQUEST", "message": "Send a positive integer base_version."})
    try:
        return confirm_package(package_id, request.base_version).response()
    except ConfirmationError as exc:
        return JSONResponse(status_code=exc.status, content=exc.payload)
    except Exception:
        log.exception("reservation confirmation failed for %s", package_id)
        return JSONResponse(status_code=500, content={"error": "RESERVATION_CREATION_FAILED", "message": "The holiday could not be confirmed. Please retry."})


def _lookup(reference):
    if re.fullmatch(r"[0-9]{10}", reference) is None:
        return None, JSONResponse(status_code=422, content={"error": "INVALID_RESERVATION_REFERENCE", "message": "Enter a valid 10-digit reservation reference."})
    reservation = get_reservation(reference)
    if reservation is None:
        return None, JSONResponse(status_code=404, content={"error": "RESERVATION_NOT_FOUND", "message": "No reservation found for this reference."})
    return reservation, None


@router.get("/reservations/{reference}")
def lookup(reference: str):
    reservation, error = _lookup(reference)
    return error if error is not None else reservation.response()


@router.get("/reservations/{reference}/export")
def export(reference: str):
    reservation, error = _lookup(reference)
    if error is not None:
        return error
    return Response(content=json.dumps(reservation.trip_json, indent=2, ensure_ascii=False), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="holiday-reservation-{reference}.json"'})
