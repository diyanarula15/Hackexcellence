# Wanderline — Architecture

Wanderline is a locally runnable, catalog-backed holiday planner. The React interface gathers a travel request; the FastAPI backend builds, validates, prices, modifies, and confirms complete itineraries. SQLite stores planned packages and confirmed reservation snapshots.

## System overview

```text
React + Vite (request form, NLP, results, atlas, trip editor)
                         |
                         v
              FastAPI application
                         |
         +---------------+----------------+
         |               |                |
  Input normalization   Planner       Saved state
  and validation        and search     / reservations
         |               |                |
  Rule-based S1 NLP   Catalog indexes   SQLite
                         |
                  Constraints + pricing
                         |
                 Independent validation
                         |
            Package / preview / booking / export
```

All itinerary logic, prices, availability, and rule checks belong to the backend. The frontend displays returned options and sends explicit traveler choices; it does not manufacture bookings or compute authoritative prices.

## Stack and repository

| Layer | Technology | Responsibility |
| --- | --- | --- |
| Interface | React, Vite, JavaScript/CSS | Search, itinerary cards, comparisons, map, editing |
| API | Python, FastAPI, Pydantic | Request contracts, responses, error handling |
| Planning | Deterministic Python constraint search | Feasible cities, flights, rooms, transport, activities |
| NLP (S1) | Local, rule-based parsing | Extract seven request fields; resolve aliases/conflicts |
| Persistence | SQLite | Package versions, saved trips, confirmed reservations |
| Source data | Eight catalog JSON files in `data/catalog/` | Inventory, schedules, permitted routes and INR prices |
| Geographic display | SVG map and local presentation assets | Monochrome atlas, positioned city pins and route visualization |

The repository is organized around `frontend/`, `backend/`, `data/catalog/`, `images/`, `scripts/`, and `docs/`. These are architectural areas; individual source-file names and API routes should be read from the current codebase rather than assumed here.

## Request → itinerary

1. **Input:** A traveler supplies departure city, destination country, destination-local arrival date, nights, adults, child ages, and total budget in INR. S1 accepts conversational text, applies deterministic lexical/regex/date/number rules, and pre-fills the same editable form. Missing or conflicting details require review.
2. **Catalog lookup:** The backend loads supported cities and directional links, airports, flights, hotels, room types, nightly inventory, transfers, and attractions from the active JSON catalog. It does not invent records or prices.
3. **Search:** The planner explores eligible city sequences and night allocations, then compatible flights, room bookings, transfer schedules, and attractions. It prunes impossible combinations and assembles a *complete* itinerary.
4. **Validation:** The complete result is checked against the same travel constraints used for later edits. Invalid results cannot be offered as valid packages.
5. **Recommendations (G4):** Objective-aware search produces **Cheapest** (lowest entire-package INR total), **Fastest** (arrival + return flight duration plus all intercity-transfer durations), and **Best Rated** (highest night-weighted hotel-star average *within budget*). Hotel guest-review scores do not determine Best Rated. A claim of global optimality requires a completed/proven search; unfinished searches must be labeled honestly.
6. **Selection:** The traveler chooses an itinerary. Its selected components and total become the authoritative planned package.

## Core travel rules

- **Dates:** 3–10 nights; for the original supplied dataset, the first night is no earlier than 1 April 2027 and the return departure no later than 20 April 2027. The start date is the date the inbound flight *lands* at the destination, not necessarily the date it departs India.
- **Cities:** Each selected city belongs to the destination country, appears once, and has at least two consecutive hotel nights. Intercity links are directed; an available A → B route does not imply B → A.
- **Flights:** One inbound flight from the selected Indian origin and one return flight. Airports must serve the first/last destination city and there must be enough seats for every adult and child.
- **Hotels:** Stay dates cover every night; room quantities satisfy adult/child capacity and nightly availability.
- **Transfers:** Required arrival/departure airport transfers serve the correct city/area and service window. Airport pickup is at least **60 minutes after landing**; arrival at the airport for the return flight is at least **180 minutes before departure**. Every intercity move needs a supported directed transfer.
- **Attractions:** Visits belong to the city, fit opening days/hours, avoid conflicts and duplicates. Initial packages schedule 1–2 attractions on each full day; none on the final departure day.
- **Money:** Totals are integer INR from the catalog; flights count every seat, hotels count rooms × nights, and transfers use the applicable per-person or per-vehicle pricing formula. The displayed total equals the sum of included components.

Flight/local-time comparisons must account for the departure and arrival airport timezones; do not subtract naive timestamps from different regions.

## Editing and safe persistence

A hotel/flight/transfer/attraction change—or a city-plan change from the **Explorer's Atlas**—follows a preview/apply pattern:

```text
Current PLANNED package
        |
Traveler selects change
        |
Replan dependent components → reprice → validate
        |
   Non-destructive preview
        |
  Accept / cancel / reject
        |
Atomic apply + package-version check (accept only)
```

- A city-plan edit is a hard constraint on the selected cities, order, and nights. It may require replacing hotels, intercity connections, airport transfers, flights, or attractions.
- Previewing never changes a saved package. Failed or stale applies leave the previous package intact.
- **Delay Rescue** simulates an arrival delay, identifies affected transfers/activities, and proposes feasible repairs; it does not fabricate a replacement flight.
- **Price Landscape** asks the backend for complete-trip minimum prices by eligible date; selecting a date builds the corresponding holiday. Unproven minimums are not represented as exact.
- Saved *PLANNED* trips can be reopened. **Confirm** creates a unique ten-digit reservation reference and persists a read-only **BOOKED** snapshot; this is an in-app reservation, **not** a ticket purchase or payment.

## Failure semantics

| State | Meaning |
| --- | --- |
| Valid / found | At least one complete valid itinerary was constructed |
| Over budget | Complete holidays exist but no valid complete package meets the ceiling; show proven cheapest total and shortfall |
| Infeasible | A completed search shows the constraints cannot be satisfied |
| Search incomplete | Search could not prove a valid result or impossibility within its limits |
| Invalid request | A field violates the accepted input/catalog requirements |

Never substitute an arbitrary city plan for an explicitly requested one or report a partial itinerary as complete.

## Export and verification

The download adapter produces the shared Problem 1 format from `DATA_DICTIONARY.md` §4:

- Trip: `trip_id`, `traveler`, `start_date`, `end_date`, `country`, `budget_inr`, `total_inr`, `items`.
- Item: `item_id`, `type`, `name`, `city`, `status`, `catalog_id`, `start`, `end`, `room_id`, `quantity`, `price_inr`, `booking`, `sources` (empty list); `warnings` is optional.
- Hotel items carry `room_id`; other item types use `null`. After confirmation, items are `BOOKED` and `booking.reference` is the reservation number **as a string**.

The original organizer catalog includes **Japan and UAE**. Other countries in an expanded compatible catalog are useful demonstrations, but judge validation against the original files must use catalog records present in those files.

**Run:** `./setup.sh` followed by `./start.sh` from the repository root. The project includes automated tests and `scripts/check_trip_export.py` for exported-file verification. Use the script's current CLI/help to supply the correct arguments. See [DEMO.md](DEMO.md) for the judging walkthrough.
