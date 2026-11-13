"""Delay Rescue orchestration: preview one simulated arrival delay, sweep all four, apply a repair.

The engine (app.engine.scenario) decides; this module only loads, words and stores. Hypothetical vs
saved data:
  * a preview or sweep never writes anything (no package row, version, flight or catalog change)
  * apply recomputes the scenario on the stored package inside the write transaction, refuses it
    unless the result is REPAIRED and identical to the preview the traveler accepted, and then saves
    ONLY the real schedule repairs (airport pickup / transfer service, moved or removed visits).
    The arrival flight item is asserted unchanged; the delay itself is never stored.
No cache: four simulations take a few milliseconds (measured), so caching would add risk for nothing.
"""

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError

from app.engine.model import Package
from app.engine.scenario import (ABSORBED, REPAIRED, SUPPORTED_DELAYS, UNRECOVERABLE,
                                 exact_absorbed_tolerance, simulate_arrival_delay)
from app.repositories import packages as repo
from app.rules.common import EDITED
from app.services.change_view import changed_item_view, violation_view
from app.services.itinerary import present_package
from app.services.modifications import ChangeInvalid, InvalidChange, PreviewOutdated


class DelayScenariosRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    base_version: StrictInt = Field(ge=1)


def parse_scenarios_request(body) -> DelayScenariosRequest:
    if not isinstance(body, dict):
        raise InvalidChange([{"field": "request", "rule": "R-CHG-0", "message": "Send a JSON object with base_version."}])
    try:
        return DelayScenariosRequest.model_validate(body)
    except ValidationError as e:
        errors = []
        for err in e.errors():
            field = ".".join(str(p) for p in err["loc"]) or "request"
            msg = ("base_version is required." if err["type"] == "missing" else
                   f"{field} is not accepted." if err["type"] == "extra_forbidden" else
                   f"{field}: {err['msg'][:1].lower()}{err['msg'][1:]}")
            errors.append({"field": field, "rule": "R-CHG-REQ", "message": msg})
        raise InvalidChange(errors) from None


def delay_token(base_version: int, delay_minutes: int, package: Package) -> str:
    """Deterministic identity of one accepted repair: same version + delay + resulting package."""
    text = json.dumps({"base_version": base_version, "delay_minutes": delay_minutes,
                       "package": repo.package_to_dict(package)},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()


# ------------------------------------------------------------------ timeline for the before/after UI

def _hhmm(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M")


def arrival_timeline(pkg: Package, landing: datetime, catalog) -> list[dict]:
    """Ordered arrival events with real times: landing, pickup, hotel arrival, and the visits on the
    arrival day and the day after (the only visits a later arrival can touch)."""
    ix = catalog.indexes
    t = pkg.arrival_transfer
    hotel = pkg.hotels[0]
    events = [
        {"kind": "landing", "time": _hhmm(landing), "label": f"Flight lands at {pkg.arrival_flight.to_airport}"},
        {"kind": "pickup", "time": _hhmm(t.pickup), "end": _hhmm(t.arrive), "catalog_id": t.transfer_id,
         "label": ix.transfers_by_id[t.transfer_id]["name"]},
        {"kind": "hotel_arrival", "time": _hhmm(t.arrive), "catalog_id": hotel.hotel_id,
         "label": f"Arrive at {ix.hotels_by_id[hotel.hotel_id]['name']}"},
    ]
    first_days = {pkg.plan.start_date, pkg.plan.start_date + timedelta(days=1)}
    for v in sorted(pkg.visits, key=lambda v: (v.start, v.attraction_id)):
        if v.start.date() in first_days:
            events.append({"kind": "visit", "item_id": f"visit:{v.attraction_id}", "time": _hhmm(v.start),
                           "end": _hhmm(v.end), "catalog_id": v.attraction_id,
                           "label": ix.attractions_by_id[v.attraction_id]["name"]})
    return events


# ------------------------------------------------------------------ views

def scenario_view(result, stored, catalog, base_version: int) -> dict:
    pkg = stored.package
    can_apply = result.outcome == REPAIRED and stored.status == repo.PLANNED
    proposed = result.proposed_package
    view = {
        "package_id": stored.id,
        "base_version": base_version,
        "kind": "ARRIVAL_DELAY",
        "target_item_id": "flight:arrival",
        "hypothetical": True,
        "delay_minutes": result.delay_minutes,
        "scheduled_landing": result.scheduled_landing,
        "simulated_landing": result.simulated_landing,
        "outcome": result.outcome,
        "valid": result.outcome != UNRECOVERABLE,
        "explanation": result.explanation,
        "original_pickup": result.original_pickup,
        "proposed_pickup": result.proposed_pickup,
        "original_total_inr": result.original_total_inr,
        "proposed_total_inr": result.proposed_total_inr,
        "price_difference_inr": result.price_difference_inr,
        "budget_inr": pkg.budget,
        "budget_remaining_inr": result.budget_remaining_inr,
        "over_budget_inr": result.over_budget_inr,
        "changed_items": [changed_item_view(c, catalog) for c in result.changed_items],
        "automatic_repairs": [changed_item_view(c, catalog) for c in result.automatic_repairs],
        "removed_activities": [changed_item_view(c, catalog) for c in result.removed_activities],
        "violations": [violation_view(v, catalog) for v in result.violations],
        "warnings": list(result.warnings),
        "timeline": {
            "original": arrival_timeline(pkg, pkg.arrival_flight.arrival, catalog),
            "simulated": (arrival_timeline(proposed, datetime.fromisoformat(result.simulated_landing), catalog)
                          if proposed is not None else None),
        },
        "can_apply": can_apply,
        "apply_blocked_reason": (None if can_apply else
                                 "This holiday is booked; a simulation cannot change it." if stored.status != repo.PLANNED
                                 else "Nothing needs to change for this delay." if result.outcome == ABSORBED
                                 else "No valid repair exists for this delay."),
        # the whole proposed itinerary only when there is something new to show
        "proposed_package": (present_package(replace(stored, package=proposed, total_inr=proposed.total,
                                                     validation_mode=EDITED), catalog)
                             if result.outcome == REPAIRED else None),
        "preview_token": delay_token(base_version, result.delay_minutes, proposed) if can_apply else None,
    }
    return view


def preview(stored, command, catalog) -> dict:
    result = simulate_arrival_delay(stored.package, command.delay_minutes, catalog)
    return scenario_view(result, stored, catalog, command.base_version)


def sweep(stored, base_version: int, catalog) -> dict:
    """All four supported delays, computed by the same function as an individual preview."""
    results = [simulate_arrival_delay(stored.package, m, catalog) for m in SUPPORTED_DELAYS]
    views = [scenario_view(r, stored, catalog, base_version) for r in results]
    absorbed = [r.delay_minutes for r in results if r.outcome == ABSORBED]
    repairable = [r.delay_minutes for r in results if r.outcome in (ABSORBED, REPAIRED)]
    # a tested level counts towards a continuous claim only if every smaller tested level also works
    def prefix(ok):
        best = 0
        for m in SUPPORTED_DELAYS:
            if m not in ok:
                break
            best = m
        return best
    exact = exact_absorbed_tolerance(stored.package, catalog)
    return {
        "package_id": stored.id,
        "base_version": base_version,
        "package_status": stored.status,
        "hypothetical": True,
        "scheduled_landing": results[0].scheduled_landing,
        "arrival_airport": stored.package.arrival_flight.to_airport,
        "original_pickup": results[0].original_pickup,
        "scenarios": views,
        "tested_absorbed_minutes": max(absorbed) if absorbed else 0,
        "tested_repairable_minutes": max(repairable) if repairable else 0,
        "tested_absorbed_continuous_minutes": prefix(set(absorbed)),
        "tested_repairable_continuous_minutes": prefix(set(repairable)),
        # verified at the boundary and one minute past it (absorption depends only on the pickup slack)
        "exact_absorbed_tolerance_minutes": exact,
    }


def apply(package_id: str, command, token: str | None, catalog):
    """Recompute and save the repair inside one write transaction; (saved, change summary)."""
    outcome = {}

    def change_fn(stored):
        result = simulate_arrival_delay(stored.package, command.delay_minutes, catalog)
        if result.outcome != REPAIRED:
            raise ChangeInvalid(
                "Nothing needs to change for this delay." if result.outcome == ABSORBED else result.explanation,
                [violation_view(v, catalog) for v in result.violations])
        proposed = result.proposed_package
        if token is not None and token != delay_token(command.base_version, command.delay_minutes, proposed):
            raise PreviewOutdated()
        # the hypothetical delay is never saved: the flights stay the catalog flights
        assert proposed.arrival_flight == stored.package.arrival_flight
        assert proposed.return_flight == stored.package.return_flight
        outcome["result"] = result
        return proposed

    saved = repo.modify_package(package_id, command.base_version, change_fn)
    r = outcome["result"]
    change = {
        "kind": command.kind,
        "delay_minutes": command.delay_minutes,
        "hypothetical_delay_saved": False,
        "target_item_id": "flight:arrival",
        "previous_version": command.base_version,
        "version": saved.version,
        "old_total_inr": r.original_total_inr,
        "new_total_inr": r.proposed_total_inr,
        "price_difference_inr": r.price_difference_inr,
        "changed_items": [changed_item_view(c, catalog) for c in r.changed_items],
        "automatic_repairs": [changed_item_view(c, catalog) for c in r.automatic_repairs],
        "removed_activities": [changed_item_view(c, catalog) for c in r.removed_activities],
        "warnings": list(r.warnings),
    }
    return saved, change
