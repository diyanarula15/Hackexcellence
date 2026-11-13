# Demo script (12 minutes)

Format from the problem statement: 4 min live demo with the Menon request (build, change, confirm,
open the reservation), 3 min of judge requests, 4 min questions, 1 min changeover. **Before the slot:
app running, form empty.**

## Before the slot (2 minutes)

```
./start.sh                         # backend :8000 + frontend :5173
python3 scripts/demo_smoke.py      # rehearses every step below against the backend; must print all ✓
```

Then open <http://localhost:5173>, scroll to the form, make sure it is empty. Use a fresh database if
you want an empty history: `HOLIDAY_DB_PATH=/tmp/demo.db ./start.sh`.

## Live demo — Menon family (4 minutes)

| Time | Do | Say / point at |
|---|---|---|
| 0:00 | Fill **From** Bengaluru, **To** Japan, **First day** 10 Apr 2027, **Nights** 6, **Adults** 2, **Children's ages** 6, **Budget** 350000 → **Plan trip** | The backend chooses the cities, flights, rooms, transfers and attractions; every rule is re-checked by an independent validator before anything is shown. |
| 0:40 | Package view | Route, total vs budget and price breakdown; day by day with flight **departure and landing** in local times, airport bus ≥ 60 min after landing, a train between cities, 1–2 attractions per full day. |
| 1:30 | **Change hotel** on one stay → pick another → preview | Every option shows the whole-trip price difference; the preview lists knock-on repairs (e.g. a different airport bus for the new hotel area) before saving. **Apply** → version 2. |
| 2:15 | **Delay resilience** on the arrival flight → **+2 h** | Simulated only: the trip still works with a later pickup; **Switch to this safer plan** saves the repair, never the delay. (Optional if short on time.) |
| 3:00 | **Confirm Holiday** → review → **Confirm Holiday** | 10-digit reservation number; the package is now read-only. **Copy reference**. |
| 3:30 | **Find reservation** (nav) → paste → **Find booking**; then try a wrong number | Same itinerary and total; it survives a backend restart; a wrong number shows "not found". **Download JSON** = the judge export. |

## Judge requests (3 minutes)

Use **Search a new trip** in the package header to go back to the form.

- **Another departure / the other country** (e.g. Delhi → United Arab Emirates, 8 Apr 2027, 4 nights,
  2 adults + 1 child, budget 200000) — new package in seconds.
- **Budget too small** (Menon with budget 100000) — "over budget", proven cheapest total and the
  shortfall (M8).
- **No package possible** (e.g. Bengaluru → Japan, 1 Apr 2027, 6 nights, 4 adults + children 3, 9) —
  the reasons, then **Nearest trips that work** with proven prices; **Search this trip** plans one.
- **Invalid value** (nights 2) — field message (M1).
- **Flexible dates** — **Explore flexible dates**: cheapest complete holiday per start date; pick a
  date → **Generate holiday** at exactly that price.

## If something goes wrong

- Backend not reachable → the UI shows an error with **Retry**; run `./start.sh` again.
- Port in use → `BACKEND_PORT=8001 FRONTEND_PORT=5174 ./start.sh`.
- Check an export file: `.venv/bin/python scripts/check_trip_export.py holiday-package.json`.
