"""Package API: plan + save a package, read it back, export it in the shared trip format.

The routes only orchestrate. Request checks are the existing TripRequest model and R-REQ rules,
planning is engine.build.build_package, display formatting is services.itinerary, storage is
repositories.packages. No planning, pricing or travel-rule logic lives here.

  POST /api/packages                   201 FOUND | 201 OVER_BUDGET | 200 INFEASIBLE |
                                       200 SEARCH_INCOMPLETE | 422 INVALID_REQUEST
  GET  /api/packages/{id}              200 (the saved package, never re-planned) | 404
  GET  /api/packages/{id}/export       200 trip JSON file (DATA_DICTIONARY section 4) | 404
  GET  /api/packages/{id}/options      200 alternatives | 404 | 409 BOOKED | 422
  POST /api/packages/{id}/preview-change  200 (valid or not, never saved) | 404 | 409 | 422
  POST /api/packages/{id}/apply-change    200 saved | 404 | 409 | 422
  POST /api/packages/{id}/delay-scenarios 200 four simulated arrival delays (read-only) | 404 | 409 | 422
       preview-change / apply-change also take {"kind": "ARRIVAL_DELAY", "delay_minutes": 60|120|180|240,
       "base_version": n}: preview is read-only (also on a BOOKED package); apply saves only the real
       schedule repairs of a REPAIRED scenario, never the hypothetical delay.
"""

import json
import logging
import re
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from app.catalog.load import load_catalog
from app.engine.build import FOUND, MINIMUM_COST, OVER_BUDGET, WITHIN_BUDGET, build_package
from app.export.to_trip import to_trip_json
from app.lib.money import rupees
from app.models import ARRIVAL_DELAY, TripRequest
from app.repositories import packages as repo
from app.rules.common import INITIAL
from app.rules.request import check_request
from app.services import delay_rescue
from app.services import modifications as mods
from app.services.alternatives import OptionsRequestError
from app.services.itinerary import present_package
from app.validate.validate_trip import validate_trip

log = logging.getLogger(__name__)
router = APIRouter()

# API field -> TripRequest field
REQUEST_FIELDS = {
    "departure": "departure_airport",
    "country": "destination_country",
    "start_date": "start_date",
    "nights": "nights",
    "adults": "adults",
    "child_ages": "children_ages",
    "budget": "budget",
}
_API_FIELD = {v: k for k, v in REQUEST_FIELDS.items()}
# request rule -> the form field(s) it is about
RULE_FIELDS = {
    "R-REQ-1": ("departure",),
    "R-REQ-2": ("country",),
    "R-REQ-3": ("nights",),
    "R-REQ-4": ("start_date",),
    "R-REQ-5": ("start_date", "nights"),
    "R-REQ-6": ("adults",),
    "R-REQ-7": ("child_ages",),
    "R-REQ-8": ("budget",),
}
GENERAL = "request"  # field key for an error that is not about a single field

NOT_FOUND = {
    "error": "PACKAGE_NOT_FOUND",
    "message": "This holiday package could not be found.",
}
UNREADABLE = {
    "error": "PACKAGE_UNREADABLE",
    "message": "This holiday package is stored but cannot be read.",
}
BOOKED = {
    "error": "PACKAGE_ALREADY_BOOKED",
    "message": "This holiday is already booked, so it can no longer be changed.",
}
EXPORT_FILENAME = "holiday-package.json"


class InvalidRequest(Exception):
    def __init__(self, errors: list[dict]):
        super().__init__("invalid trip request")
        self.errors = errors  # [{"field", "rule", "message"}]

    def payload(self) -> dict:
        field_errors: dict[str, list[str]] = {}
        for e in self.errors:
            field_errors.setdefault(e["field"], []).append(e["message"])
        return {
            "status": "INVALID_REQUEST",
            "error": "INVALID_REQUEST",
            "message": "Some trip details are not valid.",
            "field_errors": field_errors,
            "errors": self.errors,
            "reasons": list(dict.fromkeys(e["message"] for e in self.errors)),
        }


def parse_trip_request(body: Any, catalog) -> tuple[TripRequest, dict]:
    """(TripRequest for the planner, the request as the traveler sent it). Raises InvalidRequest
    with one entry per problem, each tied to a form field."""
    if not isinstance(body, dict):
        raise InvalidRequest(
            [
                {
                    "field": GENERAL,
                    "rule": "R-REQ-0",
                    "message": "Send the trip as a JSON object with the 7 trip fields.",
                }
            ]
        )
    original = {name: body.get(name) for name in REQUEST_FIELDS}
    if original["child_ages"] is None:
        original["child_ages"] = []  # no children
    raw = {REQUEST_FIELDS[name]: value for name, value in original.items()}

    errors = [
        {"field": field, "rule": v.rule, "message": _in_form_words(v.message)}
        for v in check_request(raw, catalog)
        for field in RULE_FIELDS.get(v.rule, (GENERAL,))
    ]
    if errors:
        raise InvalidRequest(errors)
    try:
        return TripRequest(**raw), original
    except (
        ValidationError
    ) as e:  # e.g. budget 0, or more travelers than any flight seats
        raise InvalidRequest([_model_error(err) for err in e.errors()]) from None


# Rule messages name the planner's fields; the traveler sees the form's labels instead.
_LABELS = {
    "departure_airport": "Departure city",
    "destination_country": "Country",
    "start_date": "Start date",
    "children_ages": "Child ages",
    "nights": "Nights",
    "adults": "Adults",
    "budget": "Budget",
}
_CHILD_AGE = re.compile(r"children_ages\[(\d+)\]")


def _in_form_words(message: str) -> str:
    """'children_ages[1] 'six' must be ...' -> 'Child 2's age 'six' must be ...' (same rule text)."""
    m = _CHILD_AGE.match(message)
    if m:
        return f"Child {int(m.group(1)) + 1}'s age{message[m.end() :]}"
    for name, label in _LABELS.items():
        if message.startswith(name):
            return label + message[len(name) :]
    return message[:1].upper() + message[1:]


def _model_error(err: dict) -> dict:
    """One pydantic error of TripRequest as a field error."""
    message = err["msg"].removeprefix("Value error, ")
    if not err[
        "loc"
    ]:  # a whole-request check, e.g. more travelers than any flight can seat
        return {
            "field": GENERAL,
            "rule": "R-REQ-MODEL",
            "message": _in_form_words(message),
        }
    name = str(err["loc"][0])
    return {
        "field": _API_FIELD.get(name, GENERAL),
        "rule": "R-REQ-MODEL",
        "message": f"{_LABELS.get(name, name)}: {message[:1].lower()}{message[1:]}.",
    }


def package_envelope(stored, catalog, planning=None) -> dict:
    """The response for one saved package: planning status, the package view and its explanation.

    `planning` is the PlanningResult when the package was just built; on a later read the status is
    derived from the saved total and budget (a package is never re-planned to answer a read).
    """
    view = present_package(stored, catalog)
    budget = view["budget"]
    over = not budget["within_budget"]
    straight_from_planner = stored.version == 1 and stored.validation_mode == INITIAL
    total, shortfall, limit = (
        budget["total_inr"],
        budget["over_budget_inr"],
        budget["budget_inr"],
    )

    if planning is not None:
        reasons, codes = list(planning.reasons), list(planning.reason_codes)
    elif (
        over and straight_from_planner
    ):  # the planner only returns an over-budget package when it is the proven cheapest
        reasons = [
            f"The cheapest valid package costs INR {total}, which is INR {shortfall} over the budget of INR {limit}."
        ]
        codes = ["OVER_BUDGET"]
    elif over:
        reasons = [
            f"This package costs INR {total}, which is INR {shortfall} over the budget of INR {limit}."
        ]
        codes = ["OVER_BUDGET"]
    else:
        reasons, codes = [], []

    suggestions = []
    if over:
        suggestions = [
            f"Raise the budget to at least {rupees(total)}.",
            "Or edit the trip: fewer nights, fewer travelers or other dates can cost less.",
        ]
    return {
        "status": OVER_BUDGET if over else FOUND,
        "package": view,
        "reasons": reasons,
        "reason_codes": codes,
        "suggestions": suggestions,
        "cheapest_total_inr": total if over and straight_from_planner else None,
        "shortfall_inr": shortfall if over else None,
    }


def _load(package_id: str):
    """(stored package, None) or (None, error response)."""
    try:
        stored = repo.get_package(package_id)
    except repo.PackageIntegrityError:
        log.exception("stored package %s is unreadable", package_id)
        return None, JSONResponse(status_code=500, content=UNREADABLE)
    if stored is None:
        return None, JSONResponse(status_code=404, content=NOT_FOUND)
    return stored, None


@router.post("/packages")
def create_package(body: Annotated[Any, Body()] = None):
    catalog = load_catalog()
    try:
        trip, original = parse_trip_request(body, catalog)
    except InvalidRequest as e:
        return JSONResponse(status_code=422, content=e.payload())

    # Optional planning objective. WITHIN_BUDGET (default) = a valid package within budget if one exists;
    # MINIMUM_COST = the proven cheapest package (the Price Landscape sends it so the generated holiday
    # matches the proven minimum shown for that date).
    objective = body.get("objective", WITHIN_BUDGET) if isinstance(body, dict) else WITHIN_BUDGET
    if objective not in (WITHIN_BUDGET, MINIMUM_COST):
        return JSONResponse(status_code=422, content=InvalidRequest([{
            "field": GENERAL, "rule": "R-REQ-OBJECTIVE",
            "message": "objective must be WITHIN_BUDGET or MINIMUM_COST."}]).payload())
    result = build_package(trip, catalog, objective)
    if (
        "INVALID_REQUEST" in result.reason_codes
    ):  # the planner's own request check (already passed above)
        return JSONResponse(
            status_code=422,
            content=InvalidRequest(
                [
                    {"field": GENERAL, "rule": "R-REQ", "message": m}
                    for m in result.reasons
                ]
            ).payload(),
        )
    if result.status not in (FOUND, OVER_BUDGET) or result.package is None:
        # INFEASIBLE (no package exists, with reasons) or SEARCH_INCOMPLETE (no proof either way)
        return JSONResponse(
            status_code=200,
            content={
                "status": result.status,
                "package": None,
                "reasons": result.reasons,
                "reason_codes": result.reason_codes,
                "suggestions": [],
                "search_complete": result.search_complete,
            },
        )

    violations = validate_trip(to_trip_json(result.package, catalog), catalog, INITIAL)
    if violations:  # never save a package that breaks a rule
        log.error(
            "planner returned an invalid package: %s",
            sorted({v.rule for v in violations}),
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "PACKAGE_INVALID",
                "message": "The planner built a package that breaks a travel rule, so it was not saved.",
                "violations": [asdict(v) for v in violations],
            },
        )

    package_id = repo.save_package(result.package, request=original)
    stored, error = _load(package_id)  # answer with what was persisted
    if error is not None:
        return error
    return JSONResponse(
        status_code=201, content=package_envelope(stored, catalog, planning=result)
    )


@router.get("/packages/{package_id}")
def read_package(package_id: str):
    stored, error = _load(package_id)
    if error is not None:
        return error
    return package_envelope(stored, load_catalog())


@router.get("/packages/{package_id}/export")
def export_package(package_id: str):
    """The saved package in the shared trip format, as a file download. Never re-planned."""
    stored, error = _load(package_id)
    if error is not None:
        return error
    if stored.status == "BOOKED":
        # Confirmed exports are served from the immutable snapshot, independent of catalog changes.
        from app.repositories.reservations import get_reservation
        reservation = get_reservation(stored.package.booking_reference) if stored.package.booking_reference else None
        if reservation is not None:
            return Response(
                content=json.dumps(reservation.trip_json, indent=2, ensure_ascii=False),
                media_type="application/json",
                headers={"Content-Disposition": f'attachment; filename="holiday-reservation-{reservation.reference}.json"'},
            )
        return JSONResponse(status_code=500, content=UNREADABLE)
    catalog = load_catalog()
    trip = to_trip_json(stored.package, catalog)
    violations = validate_trip(trip, catalog, stored.validation_mode)
    if violations:
        log.warning(
            "export of %s has rule violations: %s",
            package_id,
            sorted({v.rule for v in violations}),
        )
    return Response(
        content=json.dumps(trip, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{EXPORT_FILENAME}"',
            "X-Validation-Mode": stored.validation_mode,
            "X-Trip-Valid": "false" if violations else "true",
        },
    )


def _editable(package_id: str):
    """(stored, None) for a PLANNED package, else (None, the 404 / 409 BOOKED / 500 response)."""
    stored, error = _load(package_id)
    if error is not None:
        return None, error
    if stored.status != repo.PLANNED:
        return None, JSONResponse(status_code=409, content=BOOKED)
    return stored, None


def _conflict(message: str, current: int) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "error": "PACKAGE_VERSION_CONFLICT",
            "message": message,
            "current_version": current,
        },
    )


PREVIEW_STALE = "This holiday was updated after you opened it. Reload the latest package before previewing a change."
APPLY_STALE = "This holiday was updated after your preview. Reload the latest package before applying another change."


@router.get("/packages/{package_id}/options")
def package_options(package_id: str, request: Request):
    stored, error = _editable(package_id)
    if error is not None:
        return error
    try:
        return mods.options(stored, dict(request.query_params), load_catalog())
    except OptionsRequestError as e:
        return JSONResponse(
            status_code=422,
            content={
                "error": "INVALID_OPTIONS_REQUEST",
                "message": e.message,
                "field": e.field,
            },
        )


def _is_delay(body) -> bool:
    return isinstance(body, dict) and body.get("kind") == ARRIVAL_DELAY


def _delay_preview(package_id: str, body):
    """ARRIVAL_DELAY preview: a hypothetical scenario, so it is also allowed (read-only) on a BOOKED
    package; the response then has can_apply false."""
    stored, error = _load(package_id)
    if error is not None:
        return error
    try:
        command = mods.parse_change(body)
    except mods.InvalidChange as e:
        return JSONResponse(status_code=422, content=e.payload())
    if command.base_version != stored.version:
        return _conflict(PREVIEW_STALE, stored.version)
    return delay_rescue.preview(stored, command, load_catalog())


@router.post("/packages/{package_id}/delay-scenarios")
def delay_scenarios(package_id: str, body: Annotated[Any, Body()] = None):
    """All four simulated arrival delays (60/120/180/240 min) in one read-only response."""
    stored, error = _load(package_id)
    if error is not None:
        return error
    try:
        req = delay_rescue.parse_scenarios_request(body)
    except mods.InvalidChange as e:
        return JSONResponse(status_code=422, content=e.payload())
    if req.base_version != stored.version:
        return _conflict(PREVIEW_STALE, stored.version)
    return delay_rescue.sweep(stored, req.base_version, load_catalog())


@router.post("/packages/{package_id}/preview-change")
def preview_change(package_id: str, body: Annotated[Any, Body()] = None):
    if _is_delay(body):
        return _delay_preview(package_id, body)
    stored, error = _editable(package_id)
    if error is not None:
        return error
    try:
        command = mods.parse_change(body)
    except mods.InvalidChange as e:
        return JSONResponse(status_code=422, content=e.payload())
    if command.base_version != stored.version:
        return _conflict(PREVIEW_STALE, stored.version)
    return mods.preview(stored, command, load_catalog())


@router.post("/packages/{package_id}/apply-change")
def apply_change(package_id: str, body: Annotated[Any, Body()] = None):
    stored, error = _editable(package_id)
    if error is not None:
        return error
    rest, token = mods.split_token(body)
    if token is not None and not isinstance(token, str):
        return JSONResponse(
            status_code=422,
            content=mods.InvalidChange(
                [
                    {
                        "field": "preview_token",
                        "rule": "R-CHG-REQ",
                        "message": "preview_token must be the text returned by the preview.",
                    }
                ]
            ).payload(),
        )
    try:
        command = mods.parse_change(rest)
    except mods.InvalidChange as e:
        return JSONResponse(status_code=422, content=e.payload())
    if command.base_version != stored.version:
        return _conflict(APPLY_STALE, stored.version)
    catalog = load_catalog()
    try:
        if command.kind == ARRIVAL_DELAY:   # saves only the real schedule repairs, never the delay
            saved, change = delay_rescue.apply(package_id, command, token, catalog)
        else:
            saved, change = mods.apply(package_id, command, token, catalog)
    except repo.PackageNotFound:
        return JSONResponse(status_code=404, content=NOT_FOUND)
    except repo.PackageLocked:
        return JSONResponse(status_code=409, content=BOOKED)
    except repo.VersionConflict as e:
        return _conflict(APPLY_STALE, e.current)
    except mods.PreviewOutdated:
        return JSONResponse(
            status_code=409,
            content={
                "error": "PREVIEW_OUTDATED",
                "message": "This change would now have a different result than the preview you saw. Preview it again before applying.",
            },
        )
    except mods.ChangeInvalid as e:
        return JSONResponse(
            status_code=422,
            content={
                "error": "CHANGE_INVALID",
                "message": e.message,
                "violations": e.violations,
            },
        )
    return JSONResponse(
        status_code=200,
        content={**package_envelope(saved, catalog), "applied": True, "change": change},
    )
