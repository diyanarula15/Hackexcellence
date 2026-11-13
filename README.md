# Build My Holiday

Our entry for Hackathon Problem 1 (holiday packages).

You pick where you're flying from, the country, the first day, nights, travelers and a budget. The
backend builds one complete, rule-checked holiday from the catalog - flights, hotels, airport
transfers, trains/buses between cities and attractions for each day - saves it, lets you change it,
and books it with a 10-digit reservation number.

Problem statement: `problem-1-holiday-package.md` · data notes: `DATA_DICTIONARY.md` ·
architecture: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · demo script: [`docs/DEMO.md`](docs/DEMO.md)

## Start the app (2 commands)

Needs Python 3.11+ and Node 18+.

```
./setup.sh      # first time: makes .venv, installs backend + frontend dependencies
./start.sh      # backend on :8000 and frontend on :5173 - open http://localhost:5173
```

`Ctrl+C` stops both. Ports: `BACKEND_PORT` / `FRONTEND_PORT`. Trips and reservations live in SQLite
(`backend/app.db`, created on startup, survives restarts); `HOLIDAY_DB_PATH` moves it. API docs: <http://localhost:8000/docs>.

## What you can do

| Feature | Where |
|---|---|
| **Plan a holiday** (M1–M3) - the form's options come from `destinations.json`; invalid values get a message on the field | form → **Plan trip** |
| **Three packages** (G4) - **Cheapest** (proven lowest total), **Fastest** (least time on both flights + transfers between cities; airport transfers and visits don't count) and **Best rated** (highest hotel stars per night, weighted by nights, within budget; guest rating doesn't count). One package that wins two goes on one card with both labels, and each card says why it won. If the fastest costs more than the budget, its card says so, you must accept the price to pick it, and a **Fastest within budget** card is added. Pick one to save it; nothing else is saved | the options screen after **Plan trip** |
| **Day-by-day plan** (M4) - flights (departure *and* landing, local times), transfers, check-in/out, visits | the package view |
| **Total and budget, JSON export** (M5) | price panel → **Export JSON** |
| **Change the package** (M6, G1, G2) - hotel, flights, transfers, add/remove attractions; every option shows the whole-trip price difference; a preview lists the knock-on repairs (e.g. a new airport bus for a new hotel area) before saving | **Change …** buttons in the timeline |
| **Change city plan (G3)** - open a monochrome country atlas, choose exact cities/order/nights, preview the rebuilt holiday and all price changes, then apply to the same saved package | **Explore & Change Cities** beside the route |
| **Confirm and reservation summary** (M7) - unique 10-digit number, works after a backend restart, wrong number → "not found" | **Confirm Holiday**, **Find reservation** (nav) |
| **Budget too small** (M8) - says so, shows the proven cheapest total and the shortfall, suggests a change | result panel |
| **No trip possible** - explains why, then offers the nearest searches that *do* work (another start date, departure city or length) with their proven price, one click to search it | result panel |
| **Flexible dates (Price Landscape)** - the proven cheapest complete holiday for every start date of a month as a 3D-style price calendar; pick a date and generate the holiday at exactly that price | **Explore flexible dates** next to the form |
| **Delay Rescue** - "what if my flight lands 1–4 h late?": shows whether the trip still works and a safer pickup plan you can switch to; the delay itself is never saved | **Delay resilience** on the arrival flight |
| **Search a new trip** | package header |

## The city rule

The app chooses the cities itself. It enumerates every valid city plan of the country (cities linked
by a directed transfer, each ≥ 2 nights, nights adding up), then searches flights, rooms, transfers
and attractions for all of them with an exact branch-and-bound search. The **Plan trip** screen
picks each of Cheapest, Fastest and Best rated across every city plan, so the cities are whatever wins
that measure. `POST /api/packages` (one package) prefers **about one city per three nights**
(6 nights → 2 cities), then the cheapest valid package within the budget, and an airport pickup on the
landing day. If nothing fits the budget, both return the proven cheapest valid package (M8). Flexible
dates and "nearest trip" prices use the proven minimum. The traveler can then pick exact cities,
order and nights in the Atlas (G3).

## What we finished

| Item | Status |
|---|---|
| M1–M8 (form, valid holiday, rules, day plan, total + JSON, change, confirm + reservation, budget too small) | done |
| G1 change hotel/flights/transfers/attractions with price differences | done |
| G2 knock-on repairs shown before saving | done |
| G3 change the city plan (Atlas) | done |
| G4 Cheapest / Fastest / Best rated | done |
| S1 quick text request | not built |
| S2 bookings use up seats and rooms | not built |
| S3 own ideas | done: flexible dates price calendar, nearest working trip, Delay Rescue, attraction photos and details |

## Rule thresholds

The airport timing rules (section 4) live in one place, `backend/app/config.py`:
`PICKUP_AFTER_LANDING_MINUTES` (60) and `AIRPORT_BEFORE_DEPARTURE_MINUTES` (180). Change a value and
restart: the validator, the planner, the change checks, Delay Rescue and every message that names the
rule use the new value.

## Architecture (short)

```
frontend (React, Vite)  ──/api──▶  FastAPI routes ──▶ services ──▶ engine (planner, repair, delay scenarios)
  only displays what the API              │                          │
  returns; no prices or rules             ▼                          ▼
                                SQLite (packages, versions,   rules + independent validator
                                reservations)                  + pricing, catalog loader (data/catalog)
```

Every package - new, changed, delay-repaired or booked - is exported and re-checked by the same
independent validator before it is saved or shown. Details: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## API

| | |
|---|---|
| `GET /api/health`, `GET /api/meta` | status; form values (airports, countries, dates, nights) |
| `POST /api/packages` | plan + save (`objective`: `WITHIN_BUDGET` default, or `MINIMUM_COST`) |
| `POST /api/package-options` · `/{search_id}/select` | Cheapest / Fastest / Best rated (nothing saved) · save the one picked |
| `GET /api/packages/{id}` · `/export` | saved trip · trip JSON (shared format, section 4 of the data dictionary) |
| `GET /api/packages/{id}/options?kind=…` | valid replacements for one part, with price differences |
| `GET /api/packages/{id}/city-plan-options` | Atlas cities, directed connections, night rules and current route/version |
| `POST /api/packages/{id}/preview-change` · `/apply-change` | what a change would do (nothing saved) · save it (version check, 409 if outdated) |
| `POST /api/packages/{id}/delay-scenarios` | +1…+4 h arrival-delay simulation (read-only) |
| `POST /api/packages/{id}/confirm` | book (`{"base_version": n}`) → 10-digit reference; booked trips are read-only |
| `GET /api/reservations/{ref}` · `/export` | look up a booking · booked trip JSON |
| `POST /api/date-prices` | proven cheapest holiday per start date (7 trip fields + `range_start`, `range_end`) |
| `POST /api/trip-alternatives` | nearest one-field changes that have a holiday, with proven prices |
| `POST /api/validate` | check any trip JSON against the rules |

## Checks

```
cd backend && ../.venv/bin/python -m pytest -q          # backend tests
cd frontend && npm test                                  # frontend tests
python3 scripts/demo_smoke.py                            # rehearse the demo against a running backend
.venv/bin/python scripts/check_trip_export.py trip.json  # check an exported JSON against the shared format
```

## Known limitations

- **Expanded catalog.** `data/catalog` contains the supplied Japan/UAE records **plus five added
  countries** (Thailand, Singapore, Malaysia, Indonesia, Vietnam) generated by
  `scripts/expand_catalog.py` with the identical schema; every original record is unchanged. The
  supplied files are kept byte-for-byte in `backups/catalog_original/`;
  `python3 scripts/expand_catalog.py --restore` puts them back (and re-running it re-expands).
  The added countries only show the planner is not tied to Japan/UAE: Japan and UAE packages
  planned with the expanded catalog pass the validator run against the original files.
- Not built: S1 (quick text request), S2 (bookings using up seats/rooms - confirmation saves a
  snapshot only).
- G4 ties: Fastest and Best rated prefer the lower total, then catalog order. A hotel without a
  star value is never used for Best rated (its stars are not guessed); every hotel in the catalog has one.
  Checked against a brute-force oracle that enumerates all 9,472 combinations of a small request
  (`backend/tests/test_g4_recommendations.py`).
- Fastest and Best rated are exact searches with a work cap. If the cap is hit the label is left
  off rather than given to a package that was not proven best, and the screen says so.
- Two attractions have no free-licence photo (ATT-HKT-007, ATT-DAD-010); the rest are credited in
  [`images/ATTRIBUTIONS.md`](images/ATTRIBUTIONS.md).
- Delay Rescue's "cannot be repaired" outcome is covered by tests but rare in this catalog.
- The planner's "proven minimum" is exact within its timing model (earliest airport pickup after
  landing, latest one before the return flight, train/bus departure nearest 10:00).

The Explorer’s Atlas renders local Natural Earth country outlines and GeoNames presentation anchors;
[map provenance and licenses](frontend/src/features/atlas/data/ATTRIBUTION.md). No map tiles or paid APIs
are required. G3 uses `CHANGE_CITY_PLAN` in the existing preview/apply endpoints; apply requires the
accepted preview token and package version. Booked packages remain immutable.

No AI/LLM calls inside the app. The frontend only talks to our backend.
