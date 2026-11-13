# Hackathon data pack: Problem 1: Holiday Package → Build My Holiday

Everything your team needs for this problem.

## Start here

| Step | Read | Why |
|---|---|---|
| 1 | `problem-1-holiday-package.md` | The problem statement: what to build, the rules, and how we judge |
| 2 | `DATA_DICTIONARY.md` | What each data file is, how the files link, every field, a worked example, and a data FAQ |
| 3 | `data/` | The mock data (below) |

## The data in this pack

| File | One record is | Your app uses it to |
|---|---|---|
| `data/catalog/destinations.json` | The list of departure cities, destination countries, their cities, and the links between cities | Fill the request form (M1). Choose cities and the order to visit them (M2). |
| `data/catalog/airports.json` | One airport | Find the airports that serve a city. Get the time zone. |
| `data/catalog/flights.json` | One flight on one date | Choose the arrival flight and the return flight |
| `data/catalog/hotels.json` | One hotel | Choose a hotel in each city |
| `data/catalog/rooms.json` | One room type in one hotel | Choose the room type, check who fits, get the price per night |
| `data/catalog/availability.json` | One room type on one night | Check that enough rooms are free on every night |
| `data/catalog/transfers.json` | One transfer service (taxi, bus, train) | Airport to hotel, hotel to airport, and city to city |
| `data/catalog/attractions.json` | One attraction | Plan visits on each day |
| `data/trip_format_example.json` | A short example of an exported package | See the JSON shape of the export (section 4) |
| `images/` | One photo (JPG) | Show hotel and attraction photos (optional). Credits: `images/ATTRIBUTIONS.md`. |

All data is synthetic, except the photos (real photos with free licenses; see `images/ATTRIBUTIONS.md`). All times are local times. All prices are in INR. The data files are read-only: keep your own data in your own database.

## Rules (short version)

1. Any language, framework, and database. AI tools to help you write code are allowed. **Your app must not call an AI or LLM model.**
2. Build a **backend** and a **frontend** that work together. The frontend gets data from your backend, not from the files.
3. Do not change the data files. Judges use the same files.
4. Write feature code during the event. Push to Git every hour.
5. Your app must start with 1–2 commands. Write them in your README.
6. At code freeze, upload a zip to HackerEarth (no `node_modules`, no virtual environments, no API keys).

## Questions

Read the FAQ at the end of `DATA_DICTIONARY.md` first. Then ask at the help desk or in the event chat channel. We send every answer to all teams.

## Run the app

```
./setup.sh   # creates .venv and installs backend/requirements.txt
./start.sh   # backend on http://localhost:8000 (Swagger at /docs)
cd frontend && npm install && npm run dev   # UI on http://localhost:5173 (proxies /api to :8000)
```

Saved packages live in SQLite at `backend/app.db` (created on startup, git-ignored; `HOLIDAY_DB_PATH` overrides the location).

Endpoints so far: `GET /api/health`, `GET /api/meta`, `POST /api/validate`, `POST /api/packages` (plan and save a package), `GET /api/packages/{id}` (saved package, never re-planned), `GET /api/packages/{id}/export` (trip JSON download).
