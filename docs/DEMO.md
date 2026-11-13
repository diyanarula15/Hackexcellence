# Wanderline — Judge Demo Guide

**Goal:** Demonstrate a fully connected, constraint-valid holiday from request to booking, and show what happens when the traveler changes the plan.

The original judging slot is **12 minutes**: **4-minute live Menon demo**, **3-minute judge-entered requests**, **4-minute technical questions / small code change**, **1-minute changeover**. Begin with the app running and an **empty search form**.

## Before the judges arrive

- Start the application from the repository root with `./setup.sh` (when needed) and `./start.sh`.
- Verify the homepage opens, the backend responds, and the active catalog is loaded. Keep the **original Japan/UAE catalog** available for judge compatibility.
- Rehearse one *real* valid hotel/flight modification for the Menon request; do not improvise a replacement that might fail inventory checks.
- Keep a **PLANNED** trip for Atlas/Delay Rescue demonstrations; a BOOKED trip is immutable.
- Have the export checker and the location of the downloaded JSON ready. Use a clean/isolated demo database where possible.
- If any optional feature has not been verified in the running build, skip it in the timed flow rather than risking the core booking demonstration.

## Exact primary search — Menon family

| Field | Value |
| --- | --- |
| Departure city | **Bengaluru (BLR)** |
| Destination country | **Japan** |
| Holiday arrival date | **10 April 2027** |
| Nights | **6** |
| Adults | **2** |
| Children's ages | **6** |
| Total budget | **₹3,50,000** |

**Optional S1 query (copy-paste):**

> Plan a 6-night holiday to Japan from Bangalore starting 10 April 2027 for 2 adults and our 6-year-old child, with a maximum budget of 3.5 lakh rupees.

Confirm that S1 extracts the same seven form values. The text parser is **rule-based, not an LLM**. If it needs clarification, correct the form before generating.

## Live four-minute walkthrough

| Time | Action on screen | What to explain |
| --- | --- | --- |
| **0:00–0:25** | Show the empty Wanderline homepage. | “Flights, stays, transfers and activities have dependencies. Wanderline plans them together, not as disconnected recommendations.” |
| **0:25–0:55** | Paste the S1 query **or** complete the seven-field form; click **Find Holidays**. | The request is normalized, validated and passed to a deterministic catalog-backed planner. |
| **0:55–1:25** | Compare available packages; show G4 Cheapest/Fastest/Best Rated if proven/available, then **choose one**. | Explain each metric rather than claiming arbitrary alternatives are optimal. |
| **1:25–2:00** | Open day-by-day plan; point out flights, city nights, hotels, airport/intercity transfers, attractions, total and remaining budget. | Each item is checked against capacity, dates, service windows, activity times and complete pricing. |
| **2:00–2:50** | Change a **pre-tested available hotel** (or flight), inspect the price difference and dependent repairs, **Preview**, then **Apply**. | The backend replans impacted items and revalidates the whole holiday; preview itself does not save. |
| **2:50–3:35** | **Confirm**; copy the 10-digit reference; use **Find Booking** to retrieve the same booking. | SQLite persistence and the immutable BOOKED snapshot. This is an in-app reservation, not a purchase. |
| **3:35–4:00** | **Export JSON**, then point out Atlas, Delay Rescue and Price Landscape as follow-up demos. | The export matches the organizer's `DATA_DICTIONARY.md` §4. Finish: “One journey. Every detail connected.” |

**Do not announce exact package prices in advance.** They depend on the chosen itinerary and active catalog. Read the verified value on screen.

## Extra features — demonstrate only if requested or time permits

### Explorer's Atlas (G3)

1. Open a **PLANNED** Japan holiday and click **Explore & Change Cities**.
2. Show the monochrome geographic map with **filled numbered teardrop pins** for current cities and **hollow pins** for other catalog cities.
3. Click an unselected pin: **Edit Route** opens directly.
4. Choose a structurally valid replacement; adjust city order or nights if needed.
5. Click **Preview New Route** to show changed flights/hotels/transfers/attractions and the new total; then **Apply**.

Pick a city replacement proven feasible in this exact package. Do not assert that a Tokyo/Kyoto/Osaka rearrangement is supported without checking directed links and availability.

### Delay Rescue

Use the Menon request on an unconfirmed package. Open **Delay Rescue**, choose **+120 minutes**, inspect affected arrival pickup/activities, preview any repair, and apply only if feasible. Explain that the simulation does **not** invent a new flight or modify BOOKED records.

### Price Landscape

For **BLR → Japan, 6 nights, 2 adults and child age 6**, open **Explore Flexible Dates**. Select an eligible April 2027 date. Explain that shown exact prices are for *complete* valid holidays, not flight tickets alone. Click a date and demonstrate that the generated minimum-cost package matches the displayed date price.

### G4 — three optimizations

Show the real **Cheapest** (minimum complete INR), **Fastest** (flight + intercity-transfer minutes), and **Best Rated** (night-weighted hotel stars within budget). If one itinerary wins multiple objectives, represent that truthfully. Do not label unproven results globally optimal.

### S1 — rule-based NLP

Use three compact tests:

- **Complete:** Menon query above → seven correct fields.
- **Missing:** “Japan for two adults and two children from Delhi, budget 3 lakh” → request missing ages, date and nights; never invent them.
- **Conflict:** “Japan from Delhi, leaving from Mumbai on 10 April 2027” → ask which departure city is intended.

## Judge-entered requests (3 minutes)

These are rehearsal inputs, **not claims that inventory is available**. Validate results against the active catalog.

| ID | Search / action | Expected rule behavior |
| --- | --- | --- |
| **J1** | **DEL → UAE; 8 Apr 2027; 5 nights; 2 adults; child [6]; ₹5,00,000** | Different origin/country: real complete package or grounded infeasibility |
| **J2** | Menon input, change budget to **₹1** | **OVER_BUDGET**, proven cheapest complete total and exact shortfall; no fake affordable holiday |
| **J3** | **BLR → Japan; 18 Apr 2027; 6 nights; 2 adults; ₹3,50,000** | Return day would be 24 Apr, outside the original permitted window; clear rejection |
| **J4** | Menon input, change nights to **2** | Reject: below 3-night minimum |
| **J5** | Menon input, change nights to **11** | Reject: above 10-night maximum |
| **J6** | **BLR → Japan; 10 Apr 2027; 6 nights; 4 adults; children [6,9]; ₹6,00,000** | Verify seats, rooms and transfers or a justified inventory failure |

**Important:** The judges may swap in the original catalog, which contains Japan and UAE. Avoid proving compliance only with expanded-country records.

## Four-minute technical Q&A — prepared answers

| Question | Key answer |
| --- | --- |
| How are itineraries generated? | Deterministic search over catalog-backed city/night plans, flights, rooms, transfers, activities, with constraints and validation. |
| Why no LLM? | Runtime AI is prohibited; the S1 parser uses deterministic extraction and clarification rules. |
| Why is a valid plan hard? | A flight change can invalidate airport pickup; a city change affects hotels, transfers and activities. |
| How are times handled? | The start day is local destination arrival; flight elapsed time is timezone-aware, and transfer buffers are 60/180 minutes. |
| What does Fastest mean? | Arrival + return flight durations plus intercity transfer durations; not attraction or airport taxi time. |
| What does Best Rated mean? | Hotel stars weighted by hotel nights, within budget; not online guest review scores. |
| What happens when the budget is impossible? | Distinguish proven minimum cost over budget from genuinely infeasible or incomplete search. |
| Does preview edit the trip? | No. Only accepted, valid apply commits a package-version change. |
| Is confirmation a real ticket purchase? | No. It stores an in-app reservation with a ten-digit lookup reference. |
| How do you verify export? | Download the actual JSON, check against `DATA_DICTIONARY.md` §4 and run `scripts/check_trip_export.py` with its current CLI. |

Be ready to locate the corresponding backend logic and make a small controlled change if asked. Both team members should understand frontend and backend integration.

## Final submission check

- [ ] `./setup.sh` and `./start.sh` work from a clean checkout.
- [ ] Homepage loads with the form empty.
- [ ] Menon package generates and a real modification previews/applies.
- [ ] Confirm → ten-digit reference → lookup is successful, including after restart.
- [ ] Actual draft and booked JSON exports pass the checker.
- [ ] Original catalog is unchanged and supported.
- [ ] S1, G3, G4, Delay Rescue, Price Landscape demos use **verified** current results.
- [ ] README, `docs/ARCHITECTURE.md`, `docs/DEMO.md` and any image attributions are included in the source archive.
- [ ] Do not include `node_modules`, virtual environments, build output, secrets, or API keys in the submission ZIP.
