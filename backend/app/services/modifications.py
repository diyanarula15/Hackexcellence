"""Orchestration of package changes: parse a change body, preview it, apply it, list options.

No rule or pricing logic lives here: the engine (app.engine.change.propose_change) decides what a change
does, app.services.change_view words it, app.services.itinerary shows the proposed package and
app.repositories.packages stores it. The client's proposal is never trusted: apply recomputes the change
on the stored package inside the write transaction.
"""

import hashlib
import json
from dataclasses import replace
from typing import Any

from pydantic import ValidationError

from app.engine.change import dependency_impact, propose_change, target_item_id
from app.lib.money import rupees
from app.models import CHANGE_COMMAND
from app.repositories import packages as repo
from app.rules.common import EDITED
from app.services import alternatives as alt
from app.services.change_view import batch_headline, changed_item_view, headline, violation_view
from app.services.itinerary import present_package

GENERAL = "request"
INVALID_MESSAGE = "This change request is not valid."
EXTRA_FIELD = "{name} is not accepted: prices, availability and schedules are always computed by the server."


class InvalidChange(Exception):
    def __init__(self, errors: list[dict]):
        super().__init__("invalid change request")
        self.errors = errors  # [{"field", "rule", "message"}]

    def payload(self) -> dict:
        field_errors: dict[str, list[str]] = {}
        for e in self.errors:
            field_errors.setdefault(e["field"], []).append(e["message"])
        return {
            "status": "INVALID_CHANGE_REQUEST",
            "error": "INVALID_CHANGE_REQUEST",
            "message": INVALID_MESSAGE,
            "field_errors": field_errors,
            "errors": self.errors,
            "reasons": list(dict.fromkeys(e["message"] for e in self.errors)),
        }


class PreviewOutdated(Exception):
    """The recomputed change differs from the preview the client saw."""


class InvalidCityPlan(InvalidChange):
    def payload(self):
        body = super().payload()
        return {**body, "status": "INVALID_CITY_PLAN", "error": "INVALID_CITY_PLAN",
                "message": "The selected city plan is not valid."}


def _propose(stored, command, catalog):
    if command.kind == "CHANGE_CITY_PLAN":
        from app.services.city_plans import propose_city_plan
        return propose_city_plan(stored, command, catalog)
    return propose_change(stored.package, command, catalog)


def _target(command):
    return "city-plan" if command.kind == "CHANGE_CITY_PLAN" else target_item_id(command)


def _route_metadata(proposal):
    if not hasattr(proposal, "city_changes"):
        return {}
    return {"status": proposal.status, "search_complete": proposal.search_complete,
            "city_changes": proposal.city_changes, "preserved_items": proposal.preserved_items}


class ChangeInvalid(Exception):
    def __init__(self, message: str, violations: list[dict]):
        super().__init__(message)
        self.message, self.violations = message, violations


def parse_change(body: Any):
    """The validated command for a request body, or InvalidChange with one entry per problem."""
    if not isinstance(body, dict):
        raise InvalidChange(
            [
                {
                    "field": GENERAL,
                    "rule": "R-CHG-0",
                    "message": "Send the change as a JSON object.",
                }
            ]
        )
    try:
        return CHANGE_COMMAND.validate_python(body)
    except ValidationError as e:
        errors = []
        for err in e.errors():
            loc = [str(p) for p in err["loc"]]
            if len(loc) > 1 or (loc and loc[0].isupper() and "_" in loc[0]):
                loc = loc[1:]  # the first element is the union tag
            field = ".".join(loc) or "kind"
            if err["type"] == "model_attributes_type":
                field, message = GENERAL, "Send the change as a JSON object."
            elif err["type"] == "extra_forbidden":
                message = EXTRA_FIELD.format(name=field)
            elif err["type"] in ("union_tag_invalid", "union_tag_not_found"):
                field, message = (
                    "kind",
                    "kind must be one of the supported change kinds.",
                )
            elif err["type"] == "missing":
                message = f"{field} is required."
            else:
                message = err["msg"].removeprefix("Value error, ")
                message = f"{field}: {message[:1].lower()}{message[1:]}"
            errors.append({"field": field, "rule": "R-CHG-REQ", "message": message})
        raise InvalidChange(errors) from None


def preview_token(base_version: int, package) -> str:
    text = json.dumps(
        {"base_version": base_version, "package": repo.package_to_dict(package)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(text.encode()).hexdigest()


def _valid_message(proposal, catalog, lead: str | None = None) -> str:
    diff = proposal.price_difference or 0
    if diff > 0:
        text = f"This change adds {rupees(diff)} to the package total."
    elif diff < 0:
        text = f"This change saves {rupees(-diff)} on the package total."
    else:
        text = "This change does not change the package total."
    n = len(proposal.automatic_repairs)
    if n:
        text += f" It also changes {n} other item{'s' if n != 1 else ''} automatically."
    return f"{lead} {text}" if lead else text


def _views(items, catalog) -> list[dict]:
    return [changed_item_view(c, catalog) for c in items]


def preview(stored, command, catalog) -> dict:
    """The full, never-saved result of `command` on the stored package (valid or not)."""
    proposal = _propose(stored, command, catalog)
    target = _target(command)
    base = {
        "package_id": stored.id,
        "base_version": command.base_version,
        "kind": command.kind,
        "target_item_id": target,
        **_route_metadata(proposal),
    }
    budget = stored.package.budget
    violations = [violation_view(v, catalog) for v in proposal.violations]
    if not proposal.valid or proposal.proposed_package is None:
        return {
            "valid": False,
            **base,
            "message": headline(proposal.violations, catalog),
            "proposed_package": None,
            "old_total_inr": proposal.old_total,
            "new_total_inr": None,
            "price_difference_inr": None,
            "budget_inr": budget,
            "budget_remaining_inr": None,
            "over_budget_inr": None,
            "changed_items": [],
            "automatic_repairs": [],
            "warnings": list(proposal.warnings),
            "violations": violations,
            "rechecked": [],
            "preview_token": None,
        }
    proposed = proposal.proposed_package
    shown = replace(
        stored,
        package=proposed,
        total_inr=proposed.total,
        validation_mode=EDITED,
    )
    remaining = budget - proposed.total
    return {
        "valid": True,
        **base,
        "message": _valid_message(proposal, catalog, batch_headline(command)),
        "proposed_package": present_package(shown, catalog),
        "old_total_inr": proposal.old_total,
        "new_total_inr": proposal.new_total,
        "price_difference_inr": proposal.price_difference,
        "budget_inr": budget,
        "budget_remaining_inr": max(remaining, 0),
        "over_budget_inr": max(-remaining, 0),
        "changed_items": _views(proposal.changed_items, catalog),
        "automatic_repairs": _views(proposal.automatic_repairs, catalog),
        "warnings": list(proposal.warnings),
        "violations": violations,
        "rechecked": _rechecked(stored.package, command),
        "preview_token": preview_token(command.base_version, proposed),
    }


def _rechecked(package, command) -> list[str]:
    if command.kind == "CHANGE_CITY_PLAN":
        return ["city sequence", "night allocation", "flights", "hotels", "transfers", "attractions", "pricing"]
    impact = dependency_impact(package, command)
    return list(impact.recheck) if impact is not None else []


def split_token(body: Any) -> tuple[Any, Any]:
    """(body without preview_token, the token or None)."""
    if isinstance(body, dict) and "preview_token" in body:
        rest = {k: v for k, v in body.items() if k != "preview_token"}
        return rest, body["preview_token"]
    return body, None


def apply(package_id: str, command, token: str | None, catalog):
    """Recompute and save inside one transaction. Returns (saved StoredPackage, change summary).

    Raises PackageNotFound / PackageLocked / VersionConflict (from the repository), PreviewOutdated
    when `token` is given and differs, ChangeInvalid when the change breaks a rule.
    """
    outcome: dict = {}

    def change_fn(stored):
        if command.kind == "CHANGE_CITY_PLAN" and not token:
            raise PreviewOutdated()
        proposal = _propose(stored, command, catalog)
        if not proposal.valid or proposal.proposed_package is None:
            raise ChangeInvalid(
                headline(proposal.violations, catalog),
                [violation_view(v, catalog) for v in proposal.violations],
            )
        if token is not None and token != preview_token(
            command.base_version, proposal.proposed_package
        ):
            raise PreviewOutdated()
        outcome["proposal"] = proposal
        return proposal.proposed_package

    saved = repo.modify_package(package_id, command.base_version, change_fn)
    proposal = outcome["proposal"]
    change = {
        "kind": command.kind,
        "target_item_id": _target(command),
        "previous_version": command.base_version,
        "version": saved.version,
        "old_total_inr": proposal.old_total,
        "new_total_inr": proposal.new_total,
        "price_difference_inr": proposal.price_difference,
        "changed_items": _views(proposal.changed_items, catalog),
        "automatic_repairs": _views(proposal.automatic_repairs, catalog),
        "warnings": list(proposal.warnings),
        **_route_metadata(proposal),
    }
    return saved, change


def options(stored, query: dict, catalog) -> dict:
    """The alternatives body for a GET /options query. Raises alt.OptionsRequestError."""
    kind = query.get("kind")
    if kind not in alt.OPTION_KINDS:
        raise alt.OptionsRequestError(
            "kind", "kind must be one of: " + ", ".join(alt.OPTION_KINDS) + "."
        )
    target = query.get("stay_id") if kind == "hotel" else query.get("item_id")
    body = alt.options_response(
        stored.package, kind, target, catalog, query.get("date")
    )
    return {"package_id": stored.id, "version": stored.version, **body}
