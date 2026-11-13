"""Saved trips: named bookmarks on existing packages (never a booking, re-plan or copy).

  POST   /api/packages/{id}/save      201 first save | 200 already saved (name only if given)
                                      | 404 PACKAGE_NOT_FOUND | 409 PACKAGE_ALREADY_BOOKED | 422 INVALID_TRIP_NAME
  GET    /api/saved-trips             200 {"trips": [card, ...]}, newest updated first
  PATCH  /api/saved-trips/{id}        200 card | 404 SAVED_TRIP_NOT_FOUND | 409 PACKAGE_ALREADY_BOOKED | 422
  DELETE /api/saved-trips/{id}        204 (removes the bookmark only) | 404 SAVED_TRIP_NOT_FOUND

The routes only map repository results to HTTP. Storage and the card shape live in
repositories.saved_trips; no package or reservation row is written here.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse, Response

from app.repositories import saved_trips as repo
from app.repositories.packages import PackageNotFound

router = APIRouter()

BOOKED_MESSAGE = "This holiday is already booked. Its saved name can no longer be changed."


def _invalid(exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": "INVALID_TRIP_NAME", "message": str(exc)})


def _not_saved() -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": "SAVED_TRIP_NOT_FOUND", "message": "This trip is not in your saved trips."})


def _booked() -> JSONResponse:
    return JSONResponse(status_code=409, content={"error": "PACKAGE_ALREADY_BOOKED", "message": BOOKED_MESSAGE})


def _name_from(body) -> str | None:
    """The optional "name" of a JSON object body. Raises ValueError for a body that is not an object."""
    if body is None:
        return None
    if not isinstance(body, dict):
        raise ValueError("Send a JSON object.")
    return body.get("name")


@router.post("/packages/{package_id}/save")
def save(package_id: str, body: Annotated[Any, Body()] = None):
    try:
        name = _name_from(body)
    except ValueError:
        return JSONResponse(status_code=422, content={"error": "INVALID_TRIP_NAME", "message": "Send a JSON object with an optional name."})
    if name is not None and not isinstance(name, str):
        return _invalid(repo.InvalidTripName("Enter a name for this trip."))
    try:
        card, created = repo.save_trip(package_id, name)
    except repo.InvalidTripName as exc:
        return _invalid(exc)
    except PackageNotFound:
        return JSONResponse(status_code=404, content={"error": "PACKAGE_NOT_FOUND", "message": "This holiday package could not be found."})
    except repo.PackageBooked:
        return _booked()
    return JSONResponse(status_code=201 if created else 200, content=card)


@router.get("/saved-trips")
def list_saved():
    return {"trips": repo.list_trips()}


@router.patch("/saved-trips/{package_id}")
def rename(package_id: str, body: Annotated[Any, Body()] = None):
    try:
        name = _name_from(body)
    except ValueError:
        return _invalid(repo.InvalidTripName("Send a JSON object with a name."))
    try:
        return repo.rename_trip(package_id, name)
    except repo.InvalidTripName as exc:
        return _invalid(exc)
    except repo.SavedTripNotFound:
        return _not_saved()
    except repo.PackageBooked:
        return _booked()


@router.delete("/saved-trips/{package_id}")
def remove(package_id: str):
    try:
        repo.remove_trip(package_id)
    except repo.SavedTripNotFound:
        return _not_saved()
    return Response(status_code=204)
