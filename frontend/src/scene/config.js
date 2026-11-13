/**
 * scene/config.js - every tunable number of the 3D scene in one place.
 *
 * Tweak the scroll sequence, camera keyframes, composition, flight paths and
 * motion here; the actor modules (`actors/*.js`) contain construction logic
 * only and `choreography.js` only interprets these values.
 *
 * ── SCROLL SEQUENCE AT A GLANCE ──────────────────────────────────────────
 *   progress 0.00 ─ 0.10   Stage 1 "cabin"   inside the plane, looking out
 *   progress 0.10 ─ 0.55   Stage 2 "flight"  dolly through the window
 *   progress 0.60 ─ 1.00   Stage 3 "hero"    holiday mini-world + world map + headline
 *   (0.55–0.60 is the settle gap between flight and hero.)
 * ─────────────────────────────────────────────────────────────────────────
 */

/**
 * Scroll track.
 * `trackVh` - total scroll distance in viewport heights. Documentation of
 *             the value that actually sizes the element: `--scroll-track`
 *             in theme/tokens.css. Change it THERE (keep this in sync).
 * `damping` - inertia of the progress interpolator (higher = snappier).
 */
export const SCROLL = { trackVh: 280, damping: 4.5 };

/** Stage boundaries in scroll progress (0–1). Also drives `data-stage` on <html>. */
export const STAGES = {
  cabin: { start: 0.0, end: 0.1 },
  flight: { start: 0.1, end: 0.55 },
  hero: { start: 0.6, end: 1.0 },
};

/** Progress windows of the individual transition effects. */
export const TRANSITIONS = {
  cabinFade: [0.17, 0.29], // window frame fades + scales out as the camera passes it
  wingBank: [0.1, 0.5], // wing rolls and drops off-screen
};

/**
 * Cabin placement. `position` = centre of the main window on the interior
 * wall (world space). The hero world sits around the origin, so the cabin is
 * ~60 units "behind" it and hidden by fog until the camera flies through.
 */
export const CABIN = {
  position: [0, 1.2, 60],
  window: { width: 1.0, height: 1.4, radius: 0.36 },
  windowSpacing: 2.3, // neighbouring windows left/right of the main one
  wallThickness: 0.3,
  tallPullback: 1.8, // portrait screens: start further back so the window fits
};

/**
 * Camera keyframes. The camera follows a smooth spline through `position`
 * while looking at a spline through `target`; `at` is the scroll progress at
 * which each keyframe is reached. Add, move or retime rows freely - only
 * keep `at` ascending from 0 to 1.
 *
 * The LAST keyframe is the settled hero camera; the Rule-of-Thirds anchor
 * (COMPOSITION) is computed from it.
 */
export const CAMERA_KEYFRAMES = [
  // Stage 1 - seated in the cabin; window framed on the right third.
  { at: 0.0, position: [-0.75, 1.2, 64.0], target: [-0.75, 1.2, 40] },
  { at: 0.1, position: [-0.7, 1.2, 63.8], target: [-0.6, 1.2, 40] },
  // Stage 2 - lean in, pass through the window opening, climb into open sky.
  { at: 0.3, position: [0, 1.2, 60.3], target: [0, 1.25, 34] },
  { at: 0.45, position: [0.5, 2.0, 40], target: [0.2, 1.2, 8] },
  // Stage 3 - settle on the hero composition, then a slow final push-in.
  { at: 0.6, position: [0, 1.3, 18.4], target: [0, 0.6, 0] },
  { at: 1.0, position: [0, 1.2, 17], target: [0, 0.6, 0] },
];

/** Lens. */
export const CAMERA = { fov: 32, near: 0.1, far: 140 };

/**
 * Damped cursor parallax. Max camera travel (world units) at the screen
 * edge, blended from `cabin` (a gentle head-tilt) to `hero`; `orbit` is the
 * extra yaw (radians) applied to the hotel sculpture in the hero stage.
 */
export const PARALLAX = {
  damping: 3.2,
  cabin: { x: 0.22, y: 0.12 },
  hero: { x: 0.8, y: 0.45 },
  orbit: 0.32,
};

/**
 * Scene fog (canvas-coloured), blended over the flight. The tight cabin fog
 * hides the destination world; the hero fog is pushed back so the sky stays
 * crisp.
 */
export const FOG = {
  cabin: { near: 30, far: 60 },
  hero: { near: 26, far: 72 },
};

/**
 * Rule-of-Thirds anchors for the hero stage, in Normalised Device Coordinates
 * (x: -1 left … +1 right, y: -1 bottom … +1 top).
 * The vertical third lines sit at x = ±0.333, horizontal at y = ±0.333.
 *
 * `wide`  - landscape: hotel landmark rides the RIGHT vertical third, pulled
 *           toward the upper-right intersection; lower third stays empty.
 * `tall`  - portrait/mobile: landmark drops to the centre band under the title.
 */
export const COMPOSITION = {
  wide: { x: 0.35, y: 0.14, scale: 0.8 },
  tall: { x: 0.0, y: -0.24, scale: 0.5 },
};

/**
 * Line-art world map backdrop (see actors/worldMap.js). Coordinates are
 * [longitude, latitude] in degrees.
 *
 * z - depth of the backdrop plane (behind the cloud field).
 * fill - fraction of the view width the 360° map spans (>1 = bleeds off).
 * contourOpacity / gridOpacity - keep these around 10% so it stays a whisper.
 * routes - dashed accent arcs: `lift` bends the arc north (× its length).
 */
export const WORLD_MAP = {
  z: -32,
  offsetY: 0.6,
  fill: 1.08,
  latRange: [-58, 84],
  latCenter: 13,
  gridStep: 30,
  contourOpacity: 0.14,
  gridOpacity: 0.06,
  routeOpacity: 0.6,
  routeSeconds: 9, // time for the travelling dot to fly one route
  dotRadius: 1.0, // degrees
  pulse: { glow: 4, tail: 0.2, opacity: 0.45 }, // halo size (× dotRadius), comet tail (fraction of route), strength
  routes: [
    { from: [-74.0, 40.7], to: [-0.1, 51.5], lift: 0.22 }, // New York → London
    { from: [-0.1, 51.5], to: [55.3, 25.2], lift: 0.2 }, // London → Dubai
    { from: [-77.0, -12.0], to: [13.2, -8.8], lift: 0.1 }, // Lima → Luanda (stays above the lower third)
  ],
};

/**
 * Mini-world layout on top of the plinth (plinth-local units, origin at the
 * centre of the top face). Angles are in the XZ plane: (cos a, sin a) · r.
 *
 * tilt      - forward lean of the whole plinth
 * road      - ring road the shuttle glides on (transfers.js)
 * shuttle   - speed in rad/s (negative reverses direction)
 * archAngle - where the monument arch straddles the road (attraction.js)
 * itinerary - glowing line: starts at `hotel` [x, z], joins the road at
 *             `joinAngle`, follows it to the arch; `transferAngle` places
 *             the mid-route stop marker (itinerary.js)
 */
export const PLINTH = {
  tilt: 0.25, // radians the plinth leans toward the camera so its top (road, itinerary) reads
  road: { radius: 2.43, width: 0.26 },
  shuttle: { speed: -0.32, startAngle: 2.6 },
  archAngle: Math.PI * 0.25,
  itinerary: {
    hotel: [-1.6, -0.5],
    joinAngle: Math.PI * 0.97,
    transferAngle: Math.PI * 0.58,
    pulseSeconds: 7,
  },
};

/** Floating-plinth idle motion. */
export const ISLAND = {
  spin: 0.06, // rad/s
  bobAmplitude: 0.12,
  bobSpeed: 0.6,
};

/**
 * Flight paths - each is ONE cubic Bézier (P0, C1, C2, P3) expressed relative
 * to the hotel landmark, so the arcs keep framing the right-third focal point
 * at any viewport size. Start/end points sit off-screen or deep in fog.
 *
 * duration: seconds to fly the curve · gap: pause before re-spawning
 * offset:   phase shift so planes are staggered · showArc: draw dashed route
 */
export const FLIGHT_PATHS = [
  {
    // Descends from the top edge toward the right foreground - routed to
    // stay clear of the headline block on the left.
    points: [[-8, 9.5, -16], [-2.5, 7.4, -8], [3, 3.9, 2.5], [11, 2.2, 5]],
    duration: 20, gap: 3, offset: 6, scale: 0.66, showArc: false,
  },
  {
    points: [[10, 7, -9], [3, 5.5, -12], [-5, 8.5, -10], [-18, 6, -18]],
    duration: 26, gap: 5, offset: 15, scale: 0.6, showArc: false,
  },
  {
    // Right-hand climb-out: enters low from the right foreground, climbs
    // ABOVE the hotel spire (never through it) and fades into the far top-left.
    points: [[9, -0.5, 6], [5, 2.5, 3], [0, 5.2, -6], [-10, 7.5, -20]],
    duration: 23, gap: 8, offset: 0, scale: 0.48, showArc: false,
  },
];

/**
 * Fly-by played by one airliner when the "Plan trip" button is pressed:
 * it rolls into a bank and surges ahead along its curve, then levels out.
 * seconds - length · bank - peak extra roll (rad) · surge - peak extra speed (× normal)
 */
export const FLYBY = { seconds: 1.8, bank: 0.75, surge: 1.6 };

/**
 * Contrail ribbon. `span` = fraction of the curve the trail covers;
 * `width` = half-width at the engine (feathered edges, tapers to a point).
 */
export const TRAIL = {
  segments: 72,
  span: 0.3,
  width: 0.075,
};

/** Ambient cloud field (world-space box the clouds drift through). */
export const CLOUDS = {
  count: 10,
  bounds: { x: 26, yMin: -1.5, yMax: 6.5, zNear: -9, zFar: -24 },
  speed: [0.12, 0.38],
};
