# Wanderline - travel booking UI shell

Hackathon-ready foundation for an end-to-end holiday planner. A pinned, scroll-driven Three.js opening sequence - you start **inside a plane cabin**, fly **through the window**, and settle on a **Rule-of-Thirds hero**: a floating mini-world that shows the whole package (**flights**, a boutique **hotel**, a **transfer** shuttle on a ring road, an **attraction** arch, all tied by a glowing itinerary line) over a faint line-art world map - under a frameless 2D HUD. **No forms, cards or boxes yet**: only empty, grid-aligned slots waiting for them.

```bash
npm install
npm run dev        # http://localhost:5173
npm run build      # production bundle in dist/
```

Dev aids:

- **G** key (or `?grid`) - overlay the thirds grid and outline every injection slot.
- `?progress=0.3` - pin the scroll sequence at a fixed progress (0–1) while tuning.
- `?time=9` - start the animation clock N seconds in (inspect a specific flight moment).

## File map

```
src/
├─ main.jsx                 entry - loads tokens, mounts <App/>
├─ App.jsx                  composition root - MOUNT WIDGETS HERE
├─ theme/
│  ├─ tokens.css            ★ the 3 colours, type scale, 8pt spacing, --scroll-track
│  └─ theme.js              reads the colours for Three.js, builds scene tints
├─ hud/                     2D layer (z-index 1)
│  ├─ Hud.jsx               scroll track + sticky 3×3 thirds grid + injection slots
│  ├─ hud.css               grid map, stage-driven visibility, line-mask reveal
│  ├─ NavBar.jsx  Hero.jsx  ScrollCue.jsx  Slot.jsx  GridOverlay.jsx
├─ scene/                   3D layer (z-index 0) - framework-agnostic Three.js
│  ├─ SceneCanvas.jsx       React mount/unmount wrapper
│  ├─ createScene.js        renderer, studio lights, thirds layout, rAF loop
│  ├─ choreography.js       ★ scroll-choreography controller (progress → camera/stage state)
│  ├─ config.js             ★ ALL tunables: stages, camera keyframes, anchors, flight paths
│  ├─ actors/
│  │  ├─ planeWindow.js     PlaneWindow - cabin wall, window, shade, wing + beacon
│  │  ├─ worldMap.js        WorldMap - line-art continents, graticule, dashed route arcs
│  │  ├─ hotelLandmark.js   HotelLandmark (stays) - tower, terrace resort, pavilion
│  │  ├─ airplanes.js       Airplanes (flights) - Bézier flights + contrail ribbons
│  │  ├─ transfers.js       Transfers - ring road + gliding shuttle
│  │  ├─ attraction.js      Attraction - monument arch straddling the road
│  │  ├─ itinerary.js       Itinerary - glowing line hotel → transfer → attraction, pins
│  │  ├─ island.js          floating plinth        clouds.js   ambient clouds
│  ├─ data/worldOutline.json  coastlines (Natural Earth 110m, public domain)
│  └─ utils/                batch.js · geometry.js · materials.js · random.js
├─ services/
│  ├─ apiClient.js          fetch wrapper, base URL, mock switch
│  └─ travelApi.js          ★ searchStays / searchFlights / getDestinations stubs
└─ state/
   ├─ store.js              tiny store + useStore hook
   └─ bookingStore.js       ★ query + results state, runStaySearch action
```

## 1. Scroll distance and camera keyframes

How it works: `.scroll-track` (in `Hud.jsx`) is a tall block; the HUD inside it is sticky and the canvas is fixed, so scrolling the track only advances a 0–1 **progress**. `scene/choreography.js` damps that progress and turns it into camera position/target, cabin fade, wing bank and the current stage, which it mirrors to `<html data-stage="cabin|flight|hero">` for the HUD's CSS.

| To change | Edit |
|---|---|
| Total scroll distance | `--scroll-track` in `theme/tokens.css` (default `280vh`; mirror it in `SCROLL.trackVh`) |
| Scroll inertia | `SCROLL.damping` in `scene/config.js` |
| When each stage starts/ends | `STAGES` (cabin 0–0.10 · flight 0.10–0.55 · hero 0.60–1) |
| Camera path | `CAMERA_KEYFRAMES` - rows of `{ at, position, target }`; the camera follows a smooth spline through them. Add/move/retime rows freely, keep `at` ascending 0 → 1. The **last** row is the settled hero camera. |
| Window fade / wing bank timing | `TRANSITIONS` |
| Where the cabin sits, window size | `CABIN` |
| Hero focal point on screen | `COMPOSITION` (NDC; third lines at ±0.333) |
| Cursor tilt / orbit strength | `PARALLAX` |
| World map depth, opacity, route arcs (`[lon, lat]` pairs) | `WORLD_MAP` |
| Plinth tilt, road radius, shuttle speed, arch position, itinerary path | `PLINTH` |

Tune with `?progress=<value>` to freeze a moment. `prefers-reduced-motion` skips the sequence and shows the static hero.

## 2. Where to mount the preference inputs and the package modifier

The settled hero is a 3×3 grid (`.hud` in `hud.css`). Headline owns the upper-left intersection, the holiday mini-world owns the right third, and the **bottom row is reserved for you**.

| Slot | Where | How to fill |
|---|---|---|
| `HACKATHON_PREFERENCES_BUDGET_SLOT` | lower third of Stage 3, full width, centred (hidden during cabin/flight) | `<Hud preferences={<PreferencesPanel />} />` |
| `HACKATHON_PACKAGE_MODIFIER_SLOT` | immediately below the scroll canvas, 3-column grid matching the thirds | `<Hud packageModifier={<PackageModifier />} />` |
| `HACKATHON_NAV_ACTIONS_SLOT` | right end of the nav | `<Hud navActions={<SignIn />} />` |

Do this in `src/App.jsx`. Empty slots are invisible and click-through; grep for `HACKATHON_` to find them all.

- Need another region? Add a `<Slot>` in `Hud.jsx` and place it with `grid-column` / `grid-row` - avoid column 3 rows 1–2 (the 3D focal point).
- Use only spacing tokens (`--space-*`, multiples of 8px) and type steps (`--step-*`, 1.25 scale).
- Modifier-grid children each take one third; use `grid-column: span 2` for wide cards.
- To show something only in one stage, scope it with `[data-stage="hero"]` (see `.slot--preferences` in `hud.css`).
- The world map is a backdrop at ~10% opacity; if a widget needs a cleaner field, lower `WORLD_MAP.contourOpacity` or move a route in `WORLD_MAP.routes`.

## 3. Where to connect the backend and state

```
widget ──▶ action in state/bookingStore.js ──▶ services/travelApi.js ──▶ services/apiClient.js ──▶ fetch
   ▲                     │
   └── useStore(bookingStore, selector) ◀── setState
```

- **Base URL:** copy `.env.example` to `.env.local`, set `VITE_API_BASE_URL`. While unset, every API function returns mock data (`USE_MOCKS`).
- **Endpoints:** edit paths / response mapping in `services/travelApi.js`. Signatures are final, so UI code won't change.
- **Auth, retries, logging:** one place - `request()` in `services/apiClient.js`.
- **State:** add fields and actions to `state/bookingStore.js`. In components:

```jsx
import { useStore } from './state/store.js';
import { bookingStore, runStaySearch } from './state/bookingStore.js';

const results = useStore(bookingStore, (s) => s.results); // { status, items, error }
<button onClick={() => runStaySearch({ destination: 'Lisbon' })}>Search</button>
```

## 4. How to swap the three theme colours

Edit the first three variables in `src/theme/tokens.css`:

```css
--color-canvas: #F8FAFC; /* 60% - canvas, cabin interior */
--color-ink:    #0F172A; /* 30% - structure, trim, typography */
--color-accent: #FF5A36; /* 10% - contrails, beacon, lit windows, routes, itinerary, hovers */
```

That is the only place. HUD tints are `color-mix()` of these; the 3D scene reads them at boot (`theme.js → buildScenePalette`), so the cabin, map, hotel, road, arch, itinerary line, rock, fog, planes and contrails follow. (The favicon in `index.html` is a static data-URI - update by hand if you rebrand.)

## Regenerating the world map

`src/scene/data/worldOutline.json` is built from the `world-atlas` package: `node scripts/build-world-map.mjs`.

## Extending the 3D scene

Add `scene/actors/yourThing.js` exporting `createYourThing(ctx) → { object, update?(elapsed, delta, state) }` (`state` is the choreography state), then register it in the "Actors" block of `createScene.js`.

Notes: geometry is merged per material, pixel ratio is capped at 2, the loop allocates nothing per frame. Dark slate surfaces use a "ramp" material (`utils/materials.js`) so facets stay readable instead of going flat black.
