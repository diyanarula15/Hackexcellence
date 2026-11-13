"""Dependency mapping: which parts of a holiday package one traveler change makes stale.

Pure and deterministic. Given a change and the current package, this reports the areas that must be
re-verified (`recheck`), the component ids that may be repaired automatically (`repair_scope`), and
whether the change requires broad replanning (`replan`). It performs no I/O and changes nothing.

Component ids used in repair_scope: ARRIVAL_LEG, DEPARTURE_LEG, an intercity leg_id, a stay_id,
and visits_scope(day).
"""

from dataclasses import dataclass
from datetime import date, timedelta

from app.config import AIRPORT_BEFORE_DEPARTURE_MINUTES
from app.engine.model import ARRIVAL_LEG, DEPARTURE_LEG, Package, intercity_leg_id

ARRIVAL_FLIGHT = "ARRIVAL_FLIGHT"
RETURN_FLIGHT = "RETURN_FLIGHT"
HOTEL = "HOTEL"
AIRPORT_TRANSFER = "AIRPORT_TRANSFER"
INTERCITY_TRANSFER = "INTERCITY_TRANSFER"
ADD_ATTRACTION = "ADD_ATTRACTION"
REMOVE_ATTRACTION = "REMOVE_ATTRACTION"
REQUEST = "REQUEST"
BUDGET = "BUDGET"


@dataclass(frozen=True)
class Change:
    kind: str  # one of the constants above
    target: str | None = (
        None  # HOTEL: stay_id; AIRPORT_TRANSFER/INTERCITY_TRANSFER: leg_id; ADD/REMOVE_ATTRACTION: attraction catalog id
    )
    day: date | None = None  # ADD_ATTRACTION: the visit day


@dataclass(frozen=True)
class DependencyImpact:
    change: Change
    recheck: tuple[str, ...]  # human-readable areas to re-verify, in a fixed order
    repair_scope: frozenset[str]  # component ids that may be changed automatically
    replan: bool = (
        False  # True only for REQUEST (broad replanning needs an explicit traveler request)
    )


def visits_scope(day: date) -> str:
    return f"visits:{day.isoformat()}"


def _visits_scopes(start: date) -> set[str]:
    return {visits_scope(start), visits_scope(start + timedelta(days=1))}


def _impact(
    change: Change, recheck: tuple[str, ...], scope: set[str], replan: bool = False
) -> DependencyImpact:
    return DependencyImpact(
        change=change, recheck=recheck, repair_scope=frozenset(scope), replan=replan
    )


def affected_components(change: Change, existing_package: Package) -> DependencyImpact:
    plan = existing_package.plan
    kind = change.kind

    if kind == ARRIVAL_FLIGHT:
        return _impact(
            change,
            (
                "served first city",
                "seats",
                "arrival date",
                "arrival airport",
                "arrival pickup",
                "arrival-day visit timing",
            ),
            {ARRIVAL_LEG} | _visits_scopes(plan.start_date),
        )

    if kind == RETURN_FLIGHT:
        return _impact(
            change,
            (
                "served final city",
                "seats",
                "departure date",
                "departure airport",
                "departure pickup",
                f"{AIRPORT_BEFORE_DEPARTURE_MINUTES}-minute buffer",
            ),
            {DEPARTURE_LEG},
        )

    if kind == HOTEL:
        stays = plan.stays
        idx = next((i for i, s in enumerate(stays) if s.stay_id == change.target), None)
        if idx is None:
            raise ValueError(f"unknown stay_id for HOTEL change: {change.target!r}")
        # first hotel -> arrival transfer; last hotel -> departure transfer; single city -> both;
        # a middle hotel touches neither (city-to-city transfers do not depend on the hotel area)
        scope: set[str] = {change.target}
        recheck = ["room capacity", "every-night availability", "hotel price"]
        if idx == 0:
            scope.add(ARRIVAL_LEG)
            recheck.append("arrival airport transfer (airport, hotel area, timing)")
        if idx == len(stays) - 1:
            scope.add(DEPARTURE_LEG)
            recheck.append(f"departure airport transfer (airport, hotel area, {AIRPORT_BEFORE_DEPARTURE_MINUTES}-minute buffer)")
        return _impact(change, tuple(recheck), scope)

    if kind == AIRPORT_TRANSFER:
        if change.target not in (ARRIVAL_LEG, DEPARTURE_LEG):
            raise ValueError(
                f"AIRPORT_TRANSFER target must be ARRIVAL_LEG or DEPARTURE_LEG: {change.target!r}"
            )
        scope = {change.target}
        if change.target == ARRIVAL_LEG:
            scope |= _visits_scopes(plan.start_date)
        return _impact(
            change,
            (
                "direction",
                "airport",
                "hotel area",
                "service window",
                "time buffers",
                "pickup and end time",
            ),
            scope,
        )

    if kind == INTERCITY_TRANSFER:
        match = next(
            ((a, b, d) for a, b, d in plan.legs() if intercity_leg_id(a, b, d) == change.target),
            None,
        )
        if match is None:
            raise ValueError(f"unknown intercity leg for INTERCITY_TRANSFER: {change.target!r}")
        _, _, d = match
        return _impact(
            change,
            ("city link", "change-day slot", "arrival time", "change-day visits"),
            {change.target} | _visits_scopes(d),
        )

    if kind == ADD_ATTRACTION:
        if change.day is None:
            raise ValueError("ADD_ATTRACTION requires the visit day")
        return _impact(
            change,
            ("city", "date", "opening hours", "uniqueness", "overlaps"),
            {visits_scope(change.day)},
        )

    if kind == REMOVE_ATTRACTION:
        scope = set()
        for v in existing_package.visits:
            if v.attraction_id == change.target:
                scope.add(visits_scope(v.start.date()))
        return _impact(
            change,
            ("remove item", "keep exclusion", "reprice", "edited-attraction policy"),
            scope,
        )

    if kind == REQUEST:
        return _impact(change, ("whole package",), set(), replan=True)

    if kind == BUDGET:
        return _impact(change, ("total versus budget",), set())

    raise ValueError(f"unknown change kind: {kind!r}")


def combined_scope(changes: list[Change], existing_package: Package) -> frozenset[str]:
    scope: set[str] = set()
    for change in changes:
        scope |= affected_components(change, existing_package).repair_scope
    return frozenset(scope)
