# Price Landscape (Phase 7B)

Flexible-date price calendar: for each start date, the **proven cheapest complete holiday** from
Phase 7A (`POST /api/date-prices`), drawn as a gently tilted terrain of tiles.

| File | Role |
|---|---|
| `ExploreDatesButton.jsx` | Entry point beside the request form; snapshots the form's 7-field request (`toRequestBody`) and opens the dialog. Generating sets the form's start date and runs the normal `generatePackage()` (a NEW saved package). |
| `PriceLandscape.jsx` | Dialog container: month, selection, reference date, loading/error/partial states, Generate. |
| `useMonthPrices.js` | One fetch per month: identical in-flight requests are shared (no duplicate search in React dev mode), a sequence guard drops stale responses, finished months are kept; separate fetch for the original date when it is in another month. |
| `PriceCalendar.jsx` / `PriceTile.jsx` / `PriceTerrain.jsx` | Monday-first grid, roving-tabindex keyboard navigation, tile states, CSS 3D terrain. |
| `PriceComparison.jsx` / `usePriceCounter.js` | Original vs selected date; tweens only between two proven prices. |
| `PriceLegend.jsx` | Ramp with the month's proven low/high and the state keys. |
| `landscapeModel.js` | Pure honesty rules (proof, normalisation, comparisons, best-date note). |
| `dateUtils.js` | Date-only arithmetic on `YYYY-MM-DD` strings (no timezone shifts). |
| `../../services/datePricesApi.js` | The API client (no mock fallback). |

## Rules the UI follows
- A price is shown only for `status === "FOUND"` **and** `proven_minimum === true`. Anything else shows
  "No trip" (INFEASIBLE) or "—" / "Not verified" (SEARCH_INCOMPLETE). No interpolation, no zeros.
- Height and shade are normalised over the proven prices of the month on screen; the exact INR amount is
  always printed as text.
- Savings appear only when the original date and the selected date are both proven minima.
- "Lowest proven price this month" only when `range_fully_evaluated` is true; otherwise
  "Lowest verified price among evaluated dates".
- Only dates the backend lists (eligible start dates) are selectable; INFEASIBLE ones are not.

## Integration status / required follow-ups
1. **Backend endpoint** — `POST /api/date-prices` lives on `feature/phase7a-price-calendar`. Until that
   branch is merged, the dialog shows the error state with Retry (it never falls back to mock data).
2. **Exact-minimum generation** — Generate sends `objective: "MINIMUM_COST"`
   (`generatePackage({ objective })` in `state/bookingStore.js`, accepted by `POST /api/packages` in
   `backend/app/routes/packages.py`; default stays `WITHIN_BUDGET`). The generated package is therefore the
   proven cheapest holiday for the chosen date and its total equals the calendar price
   (`EXACT_MINIMUM_GENERATION = true`). Those two shared files must be merged together with this branch.
3. **Mounting** — one line in `features/RequestForm.jsx` renders `<ExploreDatesButton />` (separate commit).
