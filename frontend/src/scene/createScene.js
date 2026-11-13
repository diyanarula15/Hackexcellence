/**
 * scene/createScene.js — the 3D world: renderer, camera, lights, loop.
 *
 * Framework-agnostic (plain Three.js). React only mounts it through
 * `SceneCanvas.jsx`; you can equally call `createScene(canvas)` from vanilla
 * JS, Vue, Svelte…
 *
 * Responsibilities
 *   1. Build the world from the actor modules in `./actors`
 *      (PlaneWindow, WorldMap, HotelLandmark, Transfers, Attraction,
 *      Itinerary, Airplanes, island plinth, clouds).
 *   2. Each frame, ask `choreography.js` where the scroll sequence is and
 *      apply its state to the camera, fog and actors.
 *   3. Keep the Rule-of-Thirds hero framing at every viewport size (`layout`).
 *   4. Damped cursor parallax: tilts the cabin view, orbits the hotel.
 *
 * To add a new 3D element: write `actors/yourThing.js` exporting
 * `createYourThing(ctx) → { object, update?(elapsed, delta, state) }`, then
 * register it in the "Actors" block below. Nothing else needs to change.
 */

import * as THREE from 'three';
import { buildScenePalette, readTheme } from '../theme/theme.js';
import { CAMERA, CAMERA_KEYFRAMES, COMPOSITION, FOG, PARALLAX, PLINTH } from './config.js';
import { createChoreography } from './choreography.js';
import { createIsland } from './actors/island.js';
import { createHotelLandmark } from './actors/hotelLandmark.js';
import { createAirplanes } from './actors/airplanes.js';
import { createClouds } from './actors/clouds.js';
import { createPlaneWindow } from './actors/planeWindow.js';
import { createWorldMap } from './actors/worldMap.js';
import { createTransfers } from './actors/transfers.js';
import { createAttraction } from './actors/attraction.js';
import { createItinerary } from './actors/itinerary.js';

/**
 * Create and start the animated scene on a canvas.
 *
 * @param {HTMLCanvasElement} canvas  Canvas to render into (sized by CSS).
 * @param {{ reducedMotion?: boolean }} [options]
 *   reducedMotion — skip the scroll sequence; render one static hero frame.
 * @returns {{ dispose: () => void }} Call `dispose()` on unmount.
 */
export function createScene(canvas, { reducedMotion = false } = {}) {
  const palette = buildScenePalette(readTheme());
  const choreography = createChoreography({ reducedMotion });

  // ── Renderer ───────────────────────────────────────────────────────────
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2)); // cap for 60fps on hi-dpi
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  const scene = new THREE.Scene();
  scene.background = palette.canvas; // identical to the CSS canvas colour
  const fog = new THREE.Fog(palette.canvas, FOG.cabin.near, FOG.cabin.far);
  scene.fog = fog;

  // ── Camera ─────────────────────────────────────────────────────────────
  const camera = new THREE.PerspectiveCamera(CAMERA.fov, 1, CAMERA.near, CAMERA.far);
  const heroKeyframe = CAMERA_KEYFRAMES[CAMERA_KEYFRAMES.length - 1];

  // ── Studio lighting ────────────────────────────────────────────────────
  // Dome + overhead-left shadow-casting key + cool fill (so ink facets never
  // go flat black) + crisp rim (separates silhouettes from the sky).
  scene.add(new THREE.HemisphereLight(0xffffff, palette.shade, 1.7));
  const sun = new THREE.DirectionalLight(0xffffff, 2.4);
  sun.castShadow = true;
  sun.shadow.mapSize.set(1024, 1024);
  sun.shadow.camera.left = sun.shadow.camera.bottom = -6;
  sun.shadow.camera.right = sun.shadow.camera.top = 6;
  sun.shadow.camera.near = 1;
  sun.shadow.camera.far = 30;
  sun.shadow.bias = -0.0015;
  sun.shadow.radius = 4;
  const fill = new THREE.DirectionalLight(palette.canvas, 0.7);
  const rim = new THREE.DirectionalLight(0xffffff, 1.5);
  scene.add(sun, sun.target, fill, fill.target, rim, rim.target);

  // ── Actors ─────────────────────────────────────────────────────────────
  const ctx = { palette, camera };
  const island = createIsland(ctx); // sculpted floating plinth
  const hotel = createHotelLandmark(ctx);
  const airplanes = createAirplanes(ctx);
  const clouds = createClouds(ctx);
  const planeWindow = createPlaneWindow(ctx);
  const worldMap = createWorldMap(ctx); // line-art backdrop
  const transfers = createTransfers(ctx); // ring road + shuttle
  const attraction = createAttraction(ctx); // monument arch
  const itinerary = createItinerary(ctx, { attractionTop: attraction.top });

  // The whole holiday package rides (and spins with) the plinth:
  // hotel + transfers + attraction, tied together by the itinerary line.
  island.mount.add(hotel.object, transfers.object, attraction.object, itinerary.object);

  // `stage` is the right-third focal anchor; the plinth floats inside it.
  const stage = new THREE.Group();
  stage.rotation.x = PLINTH.tilt; // lean the plinth's top toward the camera
  stage.add(island.object);
  scene.add(worldMap.object, stage, airplanes.object, clouds.object, planeWindow.object);

  /** Actors with per-frame behaviour. Add yours here. */
  const animated = [island, airplanes, clouds, planeWindow, worldMap, transfers, itinerary];

  // ── Rule-of-Thirds layout ──────────────────────────────────────────────
  const ray = new THREE.Vector3();
  const offset = new THREE.Vector3();

  /**
   * Resize the renderer and re-anchor the hero focal point so it projects
   * onto the configured NDC point (see COMPOSITION) at ANY aspect ratio.
   * Uses the settled hero camera (last keyframe), not the live one.
   */
  function layout() {
    const width = canvas.clientWidth || window.innerWidth;
    const height = canvas.clientHeight || window.innerHeight;
    renderer.setSize(width, height, false);

    camera.aspect = width / height;
    camera.position.fromArray(heroKeyframe.position);
    camera.lookAt(offset.fromArray(heroKeyframe.target));
    camera.updateProjectionMatrix();
    camera.updateMatrixWorld();
    choreography.setAspect(camera.aspect);

    const anchor = camera.aspect >= 1 ? COMPOSITION.wide : COMPOSITION.tall;
    // Un-project the NDC anchor and intersect the ray with the z = 0 plane.
    ray.set(anchor.x, anchor.y, 0.5).unproject(camera).sub(camera.position).normalize();
    stage.position.copy(camera.position).addScaledVector(ray, -camera.position.z / ray.z);
    stage.scale.setScalar(anchor.scale);

    worldMap.layout(camera);
    airplanes.object.position.copy(stage.position);
    sun.position.copy(stage.position).add(offset.set(-5, 9, 7));
    sun.target.position.copy(stage.position);
    fill.position.copy(stage.position).add(offset.set(-5, -7, 6));
    fill.target.position.copy(stage.position);
    rim.position.copy(stage.position).add(offset.set(9, 1.5, -4));
    rim.target.position.copy(stage.position);

    if (reducedMotion) renderFrame(8, 0);
  }

  // ── Cursor parallax ────────────────────────────────────────────────────
  const pointer = new THREE.Vector2(); // -1…1, target
  const eased = new THREE.Vector2(); // damped value actually applied

  /** @param {PointerEvent} event */
  function onPointerMove(event) {
    pointer.set((event.clientX / window.innerWidth) * 2 - 1, (event.clientY / window.innerHeight) * 2 - 1);
  }

  /**
   * Apply the scroll choreography + parallax, update actors, draw one frame.
   * @param {number} elapsed  Seconds since start.
   * @param {number} delta    Seconds since previous frame.
   */
  function renderFrame(elapsed, delta) {
    const state = choreography.update(delta);
    const t = state.flight; // 0 = cabin … 1 = hero

    // Fog opens up as we leave the cabin and the destination emerges.
    fog.near = THREE.MathUtils.lerp(FOG.cabin.near, FOG.hero.near, t);
    fog.far = THREE.MathUtils.lerp(FOG.cabin.far, FOG.hero.far, t);

    // Exponential damping → frame-rate independent inertia. In the cabin the
    // offset reads as a head-tilt; in the hero it slides the camera while the
    // sculpture counter-rotates, which reads as orbiting it. The look-at
    // target never moves, so the Rule-of-Thirds framing is preserved.
    eased.lerp(pointer, 1 - Math.exp(-delta * PARALLAX.damping));
    const ampX = THREE.MathUtils.lerp(PARALLAX.cabin.x, PARALLAX.hero.x, t);
    const ampY = THREE.MathUtils.lerp(PARALLAX.cabin.y, PARALLAX.hero.y, t);
    camera.position.set(state.position.x + eased.x * ampX, state.position.y - eased.y * ampY, state.position.z);
    camera.lookAt(state.target);
    stage.rotation.y = eased.x * PARALLAX.orbit * t;

    for (const actor of animated) actor.update(elapsed, delta, state);
    renderer.render(scene, camera);
  }

  // ── Animation loop ─────────────────────────────────────────────────────
  const clock = new THREE.Clock();
  // DEBUG: `?time=12` starts the animation clock 12 s in (to inspect a flight moment).
  let elapsed = Number(new URLSearchParams(window.location.search).get('time')) || 0;
  let frameId = 0;

  /** rAF tick. Delta is clamped so a background tab never causes a jump. */
  function tick() {
    frameId = requestAnimationFrame(tick);
    const delta = Math.min(clock.getDelta(), 0.05);
    elapsed += delta;
    renderFrame(elapsed, delta);
  }

  const resizeObserver = new ResizeObserver(layout);
  resizeObserver.observe(canvas);
  layout();

  if (!reducedMotion) {
    window.addEventListener('pointermove', onPointerMove, { passive: true });
    tick();
  }

  /** Stop the loop and free every GPU resource. */
  function dispose() {
    cancelAnimationFrame(frameId);
    resizeObserver.disconnect();
    window.removeEventListener('pointermove', onPointerMove);
    scene.traverse((node) => {
      node.geometry?.dispose();
      const materials = Array.isArray(node.material) ? node.material : [node.material];
      materials.forEach((material) => material?.dispose());
    });
    renderer.dispose();
  }

  return { dispose };
}
