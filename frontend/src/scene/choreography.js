/**
 * scene/choreography.js - scroll-choreography controller.
 *
 * Turns raw page scroll into a damped 0–1 `progress` and from it derives
 * everything the opening sequence needs each frame:
 *
 *   Stage 1 "cabin"  (0.00–0.10)  camera seated inside the plane
 *   Stage 2 "flight" (0.10–0.55)  camera dollies through the window; cabin
 *                                 fades/scales out; wing banks away
 *   Stage 3 "hero"   (0.60–1.00)  camera settles on the Rule-of-Thirds hero
 *
 * It owns NO Three.js objects - it only outputs a plain `state` that
 * `createScene.js` applies to the camera, fog and actors. The current stage
 * is mirrored to `<html data-stage="…">` so the HUD can react in pure CSS.
 *
 * All timing lives in `config.js` (SCROLL, STAGES, TRANSITIONS,
 * CAMERA_KEYFRAMES). No scroll library needed: progress is measured from the
 * `[data-scroll-track]` element and eased with an exponential damper.
 *
 * DEBUG: open the page with `?progress=0.3` to pin the sequence at a fixed
 * progress (ignores scrolling) - handy for tuning keyframes and screenshots.
 */

import * as THREE from 'three';
import { CABIN, CAMERA_KEYFRAMES, SCROLL, STAGES, TRANSITIONS } from './config.js';

const clamp01 = (x) => Math.min(1, Math.max(0, x));
/** Smooth 0→1 ramp of `x` across [a, b]. */
const ramp = (a, b, x) => {
  const t = clamp01((x - a) / (b - a));
  return t * t * (3 - 2 * t);
};

/**
 * @typedef {Object} ChoreographyState
 * @property {number} progress      Damped scroll progress, 0–1.
 * @property {'cabin'|'flight'|'hero'} stage  Current stage name.
 * @property {number} flight        0 in the cabin → 1 once the hero is reached (eased).
 * @property {number} cabinOpacity  1 → 0 as the window frame passes the camera.
 * @property {number} cabinScale    1 → 1.5 "scale out" paired with the fade.
 * @property {number} wingBank      0 → 1 as the wing rolls off-screen.
 * @property {THREE.Vector3} position  Camera position for this frame.
 * @property {THREE.Vector3} target    Camera look-at point for this frame.
 */

/**
 * Create the controller.
 *
 * @param {{ reducedMotion?: boolean }} [options]
 *   reducedMotion - skip the sequence: progress is pinned to 1 (hero).
 * @returns {{
 *   state: ChoreographyState,
 *   setAspect: (aspect: number) => void,
 *   update: (delta: number) => ChoreographyState,
 * }}
 */
export function createChoreography({ reducedMotion = false } = {}) {
  const track = document.querySelector('[data-scroll-track]');
  const pinned = new URLSearchParams(window.location.search).get('progress');
  const isPinned = pinned !== null && !Number.isNaN(Number(pinned));
  let target = reducedMotion || !track ? 1 : 0;
  let progress = target;
  let primed = false; // first measurement snaps instead of easing (deep links, reloads)

  let positionCurve;
  let targetCurve;

  /** @type {ChoreographyState} */
  const state = {
    progress,
    stage: 'cabin',
    flight: 0,
    cabinOpacity: 1,
    cabinScale: 1,
    wingBank: 0,
    position: new THREE.Vector3(),
    target: new THREE.Vector3(),
  };

  /**
   * (Re)build the camera splines for a viewport aspect ratio. On portrait
   * screens the cabin keyframes are centred on the window and pulled back
   * so the whole window fits the narrow frame.
   * @param {number} aspect  width / height.
   */
  function setAspect(aspect) {
    const tall = aspect < 1;
    const wallZ = CABIN.position[2];
    const adapt = ([x, y, z], isTarget) => {
      const inCabin = z > wallZ + 1;
      if (!tall || (!inCabin && !isTarget)) return new THREE.Vector3(x, y, z);
      return new THREE.Vector3(inCabin || isTarget ? x * 0.2 : x, y, inCabin ? z + CABIN.tallPullback : z);
    };
    positionCurve = new THREE.CatmullRomCurve3(CAMERA_KEYFRAMES.map((k) => adapt(k.position, false)), false, 'centripetal');
    targetCurve = new THREE.CatmullRomCurve3(CAMERA_KEYFRAMES.map((k) => adapt(k.target, true)), false, 'centripetal');
  }

  /**
   * Map scroll progress to the spline parameter using each keyframe's `at`.
   * @param {number} p  Progress 0–1.
   * @returns {number} Spline parameter 0–1.
   */
  function splineParameter(p) {
    const last = CAMERA_KEYFRAMES.length - 1;
    for (let i = 0; i < last; i++) {
      const a = CAMERA_KEYFRAMES[i].at;
      const b = CAMERA_KEYFRAMES[i + 1].at;
      if (p <= b) return (i + clamp01((p - a) / (b - a))) / last;
    }
    return 1;
  }

  /** Read raw scroll progress from the track element's position. */
  function measure() {
    const rect = track.getBoundingClientRect();
    const distance = rect.height - window.innerHeight;
    target = distance > 0 ? clamp01(-rect.top / distance) : 1;
  }

  /**
   * Advance the damped progress and recompute the frame state.
   * @param {number} delta  Seconds since the previous frame.
   * @returns {ChoreographyState}
   */
  function update(delta) {
    if (isPinned) {
      progress = target = clamp01(Number(pinned));
    } else if (track && !reducedMotion) {
      measure();
      if (!primed) {
        progress = target;
        primed = true;
      } else {
        progress += (target - progress) * (1 - Math.exp(-delta * SCROLL.damping));
        if (Math.abs(target - progress) < 0.0002) progress = target;
      }
    }

    const stage = progress < STAGES.cabin.end ? 'cabin' : progress < STAGES.hero.start ? 'flight' : 'hero';
    if (stage !== state.stage || !document.documentElement.dataset.stage) {
      document.documentElement.dataset.stage = stage; // HUD reacts via CSS
    }

    state.progress = progress;
    state.stage = stage;
    state.flight = ramp(STAGES.flight.start, STAGES.hero.start, progress);
    const fade = ramp(TRANSITIONS.cabinFade[0], TRANSITIONS.cabinFade[1], progress);
    state.cabinOpacity = 1 - fade;
    state.cabinScale = 1 + fade * 0.5;
    state.wingBank = ramp(TRANSITIONS.wingBank[0], TRANSITIONS.wingBank[1], progress);

    const u = splineParameter(progress);
    positionCurve.getPoint(u, state.position);
    targetCurve.getPoint(u, state.target);
    return state;
  }

  setAspect(window.innerWidth / window.innerHeight);
  return { state, setAspect, update };
}
