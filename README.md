# Build My Holiday

Our entry for Hackathon Problem 1 (holiday packages).

You pick where you're flying from, the country, dates, how many people and a budget, and the app puts together a full trip from the catalog: flights, hotels, airport pickups/drops, trains or buses between cities, and things to do each day. The trip gets saved, so you can come back to it, and you can change bits of it later (swap the hotel, pick another flight, add or remove a place to visit etc.).

Problem statement: `problem-1-holiday-package.md`. Data notes: `DATA_DICTIONARY.md`.

## Running it

```
./setup.sh      # first time only, makes .venv and installs backend deps
./start.sh      # backend on localhost:8000 (API docs at /docs)
cd frontend && npm install && npm run dev    # frontend on localhost:5173
```

Trips are stored in SQLite (`backend/app.db`, gets created on startup). You can point it somewhere else with `HOLIDAY_DB_PATH`.

## How it works

The backend does all the real work. The frontend only shows what the API sends back, it never reads the data files or calculates prices itself.

- **Planning**: `POST /api/packages` takes the trip request, finds cities, flights, rooms, transfers and visits that actually fit together, and saves the package as version 1. If nothing fits (no seats, no rooms, over budget...) it tells you why.
- **Rules**: every trip, new or edited, goes through the same checks (`backend/app/rules`, `backend/app/validate`). Wrong airport, room too small, transfer outside its timings, attraction closed that day, that kind of thing.
- **Changing a trip**: from the day-by-day view you can hit Change flight / Change hotel / Change transfer / Add attraction / Remove. The flow is:
  1. `GET /options` shows the other choices, each already checked against the rest of your trip, with the price difference for the whole trip (or why it won't work).
  2. `POST /preview-change` shows exactly what would change before anything is saved. Sometimes other things have to move too, like a different hotel area needs a different airport bus, and those are listed.
  3. `POST /apply-change` saves it. The server works the change out again (doesn't trust the browser) and bumps the version. If someone changed the trip in between, you get a 409 and have to reload.

## API

| | |
|---|---|
| `GET /api/health` | is it up |
| `GET /api/meta` | values for the form (airports, countries, dates, nights) |
| `POST /api/validate` | check a trip JSON against the rules |
| `POST /api/packages` | plan + save a trip |
| `GET /api/packages/{id}` | get a saved trip |
| `GET /api/packages/{id}/export` | download the trip JSON |
| `GET /api/packages/{id}/options?kind=...` | other choices for one part of the trip (`hotel&stay_id=`, `arrival_flight`, `return_flight`, `airport_transfer&item_id=`, `intercity_transfer&item_id=`, `attraction&date=`) |
| `POST /api/packages/{id}/preview-change` | what a change would do, nothing saved |
| `POST /api/packages/{id}/apply-change` | save a change |

Example change:

```json
{ "base_version": 1, "kind": "CHANGE_HOTEL", "stay_id": "stay:Tokyo:2027-04-10:2027-04-12",
  "hotel_id": "HTL-TYO-004", "room_id": "RM-TYO-004-B" }
```

Other kinds: `CHANGE_ARRIVAL_FLIGHT`, `CHANGE_RETURN_FLIGHT`, `CHANGE_AIRPORT_TRANSFER`, `CHANGE_INTERCITY_TRANSFER`, `ADD_ATTRACTION`, `REMOVE_ATTRACTION`.

## Where things are

- `backend/app/routes` – the endpoints
- `backend/app/engine` – planner (`build.py`) and the change/repair logic (`change.py`, `dependencies.py`, `repair.py`)
- `backend/app/rules`, `backend/app/validate` – the checks
- `backend/app/services` – options, preview/apply, the itinerary view
- `backend/app/repositories` – SQLite stuff
- `frontend/src/features` – form, trip view, timeline, the change drawer
- `frontend/src/services` – API calls

## Tests

```
cd backend && ../.venv/bin/python -m pytest -q
```

## Rules we followed

No AI/LLM calls inside the app. The frontend only talks to our backend. The app starts with the commands above.
