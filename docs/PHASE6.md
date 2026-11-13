# Phase 6 delivery and integration

This branch extends the existing Phase 1–5 planner, independent validator, SQLite package persistence,
judge export, versioned modifications, dependency repair, and React itinerary UI. The original checkout
also contained uncommitted delay-rescue work, and a separate Phase 7A worktree existed. Neither is
included or overwritten here. No branch was merged into main.

## Backend contract

- `POST /api/packages/{id}/confirm`, JSON `{ "base_version": 1 }`: returns 200 with `status`,
  `package_id`, `reference` (string), `total_inr`, `confirmed_at`, and `trip` (complete booked snapshot).
- `GET /api/reservations/{reference}`: returns the same envelope from SQLite, without catalog loading,
  planning, modification or repricing.
- `GET /api/reservations/{reference}/export`: attachment `holiday-reservation-{reference}.json`,
  containing only the saved judge-format trip.
- The existing package detail response now includes `booking_reference`; its status becomes `BOOKED`
  and its version increases by one on first confirmation. Booked package exports also serve the saved
  reservation snapshot.

Errors have `{ "error": "CODE", "message": "..." }`: missing packages/references return 404;
malformed references and confirmation bodies return 422; stale new confirmations and unavailable or
changed source catalogs return 409; validation failures return 422; allocation/storage failures return
503 (unexpected internal failures return a generic 500). No SQLite exception text reaches clients.
References must match ASCII `[0-9]{10}`. `base_version` is a strict positive integer; extra fields are refused.

## Transactions and immutability

Confirmation uses `BEGIN IMMEDIATE` on the same database as Phase 5 writes. It first returns any existing
reservation, even if a retry has a stale version or the catalog later changes. New confirmations check
version, planned state, catalog identity, authoritative saved total, and the full independent validator
using the saved INITIAL/EDITED mode. The existing export adapter creates all BOOKED item statuses and
item-level booking references, without adding invented top-level judge fields.

References use `secrets.randbelow(10**10)` formatted to ten digits. SQLite's primary key is authoritative;
only actual reference collisions are retried, at most 20 times. `UNIQUE(package_id)` permits exactly one
reservation per package. Snapshot insertion and package status/reference/version update share one commit;
errors roll both back. Success is returned only after commit.

SQLite stores independent `trip_json`; reads never regenerate or reprice it. Database triggers reject
reservation updates/deletions and booked-package updates. The existing foreign key retains the parent
package while a reservation exists when foreign keys are enabled. Both modification repository entry
points reject BOOKED packages. Phase 5's change engine and modification service are unchanged.

## Additive migration and shared integration

`create_tables()` reuses the existing reservations table and constraints. It adds nullable
`packages.catalog_fingerprint` only if missing and installs idempotent immutability/reference triggers.
New package saves record a SHA-256 digest of the complete loaded catalog. Legacy packages without a
recorded identity must be replanned before confirmation: assigning them the current fingerprint would
make an unsupported claim about their original source catalog. No existing rows are deleted.

Shared integration is limited to API router registration (`main.py`), database initialization (`db.py`),
package creation/legacy write protection (`repositories/packages.py`), `booking_reference` in the package
presenter, and a small booked-export delegation in `routes/packages.py`. Frontend integration mounts
confirmation in `PackagePanel.jsx` and reference lookup in `NavActions.jsx`; `App.jsx`, the shared API
service, the booking store and Phase 5 change logic are untouched.

## Validation

Run only Phase 6 tests:

```sh
PYTHONPATH=backend .venv/bin/python -m pytest -q -p no:cacheprovider \
  backend/tests/test_reservation_transactions.py backend/tests/test_reservation_api.py
cd frontend && npm run build
```

Focused tests exercise valid confirmation, exact exports and room preservation, modified/EDITED and
over-budget packages, malformed inputs, stale versions, duplicate/concurrent confirmations, collision
retry/exhaustion, rollback after insertion, immutable state, modification/confirmation races, catalog
changes, repeated schema initialization and restart persistence. API reads/confirmation are exercised
with planning disabled; reservation reads also run with catalog access disabled.

## Limits

This is a simulated reservation system with reference lookup, not production authentication, payment,
ticketing, inventory depletion or external supplier booking. Budget overspend is allowed after explicit
final-price review. The source catalog is read-only. No Phase 7 functionality is included. Existing
legacy packages must be regenerated once to record a trustworthy catalog identity. Browser interaction
coverage and exact verification outcomes are recorded in the final delivery report.

## Executed verification and changed files

Final focused backend suite: **41 passed**. Production frontend build: **passed** (80 modules).
The test environment reports a Starlette/httpx deprecation warning and Vite reports the existing
large JavaScript chunk advisory; neither failed verification.

Executed a real Chromium journey against local Vite and Uvicorn servers with a throwaway SQLite file:
create an over-budget package, review final total, require acknowledgment, dispatch two immediate
confirmation clicks (one HTTP request), display/copy the server reference, verify BOOKED state and
refresh persistence, open reservation details, and compare the downloaded JSON to the saved snapshot.
The browser reported no JavaScript errors. Mobile malformed-reference validation and full itinerary
lookup passed. After terminating Uvicorn and starting a new process against the same database, lookup,
export and stale-version idempotent confirmation returned identical data. Mobile layout measured
390px document width at a 390px viewport; Escape closed the dialog.

Created:

- `backend/app/lib/catalog_identity.py`, `backend/app/lib/ref.py`
- `backend/app/repositories/reservations.py`
- `backend/app/services/reservations.py`
- `backend/app/routes/reservations.py`
- `backend/tests/test_reservation_api.py`, `backend/tests/test_reservation_transactions.py`
- `frontend/src/services/reservationsApi.js`
- `frontend/src/features/reservations/ConfirmHoliday.jsx`
- `frontend/src/features/reservations/BookingConfirmation.jsx`
- `frontend/src/features/reservations/ReservationLookup.jsx`
- `frontend/src/features/reservations/ReservationDetails.jsx`
- `frontend/src/features/reservations/ReservationModal.jsx`
- `docs/PHASE6.md`

Modified:

- `backend/app/db.py`, `backend/app/main.py`
- `backend/app/repositories/packages.py`, `backend/app/routes/packages.py`
- `backend/app/services/itinerary.py`
- `frontend/src/features/PackagePanel.jsx`, `frontend/src/features/NavActions.jsx`
- `frontend/src/features/features.css` (reservation styling and phone navigation sizing)
- `README.md`

Implementation was isolated on `feature/phase6-reservations` from `main` at `f886547`. The final
commit hash is supplied in the delivery message. Core transaction, validation, identity and storage
logic were implemented by the primary agent; supporting UI and API tests were delegated to a lower
model. The original working directory and Phase 7 worktree were preserved.
