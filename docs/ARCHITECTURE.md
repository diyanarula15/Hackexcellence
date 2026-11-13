# Architecture

One rule shapes everything: **the backend holds all planning, pricing and rule logic; the frontend
only displays what the API returns.** The catalog files in `data/catalog` are read-only; our own state
(packages, versions, reservations) lives in SQLite.

```
Browser ─ React (Vite) ─ /api ─▶ FastAPI routes            backend/app/routes
                                   │
                                   ▼
                                 services                  backend/app/services
                                   │  options / preview / apply, itinerary view, delay rescue,
                                   │  reservations, date prices (+cache), trip alternatives
                                   ▼
                                 engine                    backend/app/engine
                                   │  city plans → candidates → exact search (build.py),
                                   │  constrained repair (repair.py, change.py), delay scenarios
                                   ▼
          rules + independent validator + pricing           backend/app/rules, validate, rules/pricing.py
                                   │
                                   ▼
          catalog loader + indexes (data/catalog, 8 files)  backend/app/catalog/load.py
          SQLite: packages (with version), reservations       backend/app/db.py, repositories/
```

## Request → package

1. **Validation** - `models.TripRequest` + `rules/request.py`: 7 fields checked against
   `destinations.json` (departure cities, countries, nights 3–10, 1–20 April window, ages 0–17).
   Errors are returned per form field (422).
2. **City plans** - `engine/city_plans.py`: every ordered set of distinct cities in the country joined
   by directed links, each ≥ 2 nights, nights summing to the request. Nothing is hardcoded; new
   same-schema countries work automatically.
3. **Candidates** - `engine/flights.py`, `hotels.py`, `transfers.py`, `schedule.py`: arrival/return
   flights whose airport serves the first/last city and has the seats; every hotel/room type with
   capacity and every-night availability; airport transfers that cover the hotel's area and meet the
   +60 min / −180 min buffers inside dated service windows (overnight windows and `24:00` handled);
   intercity departures on real timetable slots; an exact minimum-cost assignment of distinct,
   open attractions to every full day.
4. **Search** - `engine/build.py`: best-first branch-and-bound over (city plan × arrival × return),
   then over every slot combination in rising cost, with a lower bound that can never overestimate.
   No "top-N" cut-offs. Outcomes: `FOUND`, `OVER_BUDGET` (proven cheapest + shortfall), `INFEASIBLE`
   (reasons), `SEARCH_INCOMPLETE` (never reported as a proof).
5. **Validation again** - every candidate package is exported to the shared trip format and checked by
   the independent validator (`validate/validate_trip.py`) before it can be returned or saved.

## Changing a saved trip

`services/modifications.py` + `engine/repair.py`: the traveler's choice is a hard lock; the engine
keeps every unrelated item, repairs only what the change invalidates (dependency map in
`engine/dependencies.py`), reprices from the catalog and re-runs the validator in `EDITED` mode.
Preview saves nothing; apply recomputes the same result, checks `base_version` (409 if stale) and saves
a new version atomically.

## Changing the city plan (G3)

The Explorer's Atlas is a lazy-loaded overlay on the active PLANNED package. Its local draft uses
catalog city names as identifiers (the supplied schema has no separate city IDs), directed links,
and minimum/total night rules from `GET /packages/{id}/city-plan-options`. Pin clicks never plan or save.
`CHANGE_CITY_PLAN` uses the existing preview-change/apply-change endpoints. `services/city_plans.py`
validates structure, calls the existing planner with `PlanningConstraints.locked_city_plan`, and
prefers retaining compatible flights, unchanged hotel stays, transfers and visits through planner
locks. It never relaxes the selected sequence or nights. The full result is independently validated
in EDITED mode, compared with the original, and bound to the existing preview token.

Apply recomputes under `repositories.packages.modify_package`'s write transaction, verifies the
accepted token/version, then updates the same package once. Saved-trip bookmarks retain their
identity/name. Client installation clears old delay scenarios, attraction selection and previews.
Country geometry and coordinate assets are local presentation data, excluded from judge exports.

## Delay Rescue

`engine/scenario.py` + `services/delay_rescue.py`: for +60/120/180/240 min it replays the arrival
with the delayed landing and classifies **ABSORBED** (nothing changes), **REPAIRED** (smallest valid
fix: later pickup or another transfer, moved visits) or **UNRECOVERABLE**. The sweep is read-only;
applying a repair saves only real schedule changes, never the hypothetical delay.

## Booking

`services/reservations.py`: one `BEGIN IMMEDIATE` transaction re-validates the saved version, allocates
a random 10-digit reference (string, leading zeros kept, collision-safe), stores an immutable booked
snapshot and marks the package `BOOKED`. Confirming again returns the same reference. Lookups and
exports read the snapshot only - no planner, no repricing.

## Flexible dates and "nearest trip"

`services/date_prices.py`: for each eligible start date of a month (from the catalog's data window) it
runs the planner with `MINIMUM_COST`; a price is shown only when the search completed and proved it.
Results are cached in memory keyed by catalog fingerprint + traveler requirements (not budget).
`services/trip_alternatives.py` reuses the same proven prices to find the nearest one-field changes
(start date ±7 days, another departure city, ±1–3 nights) that do have a holiday.

## Frontend

`frontend/src`: `state/bookingStore.js` (the only module that calls the API, via
`services/*.js`), `features/` (form, package view, day timeline, change drawer, Delay Rescue,
reservations, Price Landscape). The page URL keeps only `?package=<id>`, so refresh/back reopen the
saved package from the backend.

## Data and export

- Catalog: 8 JSON files, schema per `DATA_DICTIONARY.md`; loaded once, validated (keys and
  cross-file references), indexed.
- Export: `export/to_trip.py` produces exactly the shared trip format (section 4): 8 top-level fields,
  14 fields per item, `PLANNED` or `BOOKED` + `booking.reference`. `scripts/check_trip_export.py`
  checks a file against it.
