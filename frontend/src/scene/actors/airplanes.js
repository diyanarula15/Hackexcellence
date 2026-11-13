/**
 * scene/actors/airplanes.js - `Airplanes`: stylised airliners + accent-colour contrails.
 *
 * Each plane flies ONE cubic Bézier curve (see FLIGHT_PATHS in config.js),
 * banks into turns, fades in/out at the ends and re-spawns after a gap.
 *
 * Contrails are camera-facing ribbons whose vertices are re-sampled from the
 * same curve every frame (no position history needed → zero allocations,
 * frame-rate independent, perfectly smooth). Each ribbon is three vertices
 * wide - opaque spine, transparent edges - so it has soft feathered sides,
 * tapers to a point and fades out along its length.
 */

import * as THREE from 'three';
import { GeoBatch } from '../utils/batch.js';
import { plate } from '../utils/geometry.js';
import { FLIGHT_PATHS, FLYBY, TRAIL } from '../config.js';

const UP = new THREE.Vector3(0, 1, 0);
const ENGINE_OFFSET = 0.44; // engine distance from the fuselage centre line
const smoothstep = (a, b, x) => {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
};

/**
 * Build one low-poly airliner. Nose points +Z, wings span X, 2 units long.
 * Parts: lathe-turned fuselage (rounded nose, tapered tail), swept tapered
 * wings, tailplane, raked fin, two under-wing engines.
 *
 * @param {Record<string, THREE.Material>} materials  `paper` and `ink`.
 * @returns {THREE.Group}
 */
export function buildPlaneModel(materials) {
  const b = new GeoBatch();
  const half = Math.PI / 2;

  // Fuselage: profile is [radius, station] from tail (-1) to nose (+1).
  const profile = [[0, -1], [0.05, -0.94], [0.12, -0.5], [0.15, -0.1], [0.15, 0.6], [0.12, 0.84], [0.06, 0.96], [0, 1]];
  b.add('paper', new THREE.LatheGeometry(profile.map(([r, y]) => new THREE.Vector2(r, y)), 16), {
    rotation: [half, 0, 0], // lathe axis Y → +Z
  });

  // Wings + tailplane: outline is [span, chord-station]; rotating +90° about
  // X lays the plate flat (chord → +Z). Tips are swept back and narrower.
  for (const side of [1, -1]) {
    const wing = [[0.1, 0.3], [1.1, -0.28], [1.1, -0.44], [0.1, -0.12]].map(([x, y]) => [x * side, y]);
    b.add('ink', plate(wing, 0.03), { rotation: [half, 0, 0], position: [0, -0.02, 0] });
    const tail = [[0.04, -0.68], [0.42, -0.9], [0.42, -0.98], [0.04, -0.88]].map(([x, y]) => [x * side, y]);
    b.add('ink', plate(tail, 0.022), { rotation: [half, 0, 0], position: [0, 0.05, 0] });
    b.add('ink', new THREE.CylinderGeometry(0.06, 0.05, 0.3, 8), {
      rotation: [half, 0, 0], position: [side * ENGINE_OFFSET, -0.12, 0.1],
    });
  }

  // Fin: outline is [station, height]; rotating -90° about Y stands it up
  // along the fuselage (station → +Z).
  b.add('ink', plate([[-0.62, 0.08], [-0.86, 0.48], [-0.99, 0.48], [-0.95, 0.08]], 0.03), {
    rotation: [0, -half, 0], position: [0.015, 0, 0],
  });

  return b.build(materials);
}

/**
 * Allocate a contrail ribbon: (segments + 1) rows × 3 vertices
 * [left edge, spine, right edge]. Alpha is baked per-vertex - edges are fully
 * transparent (feathering) and the spine fades from the engine to the tail.
 * Positions are rewritten each frame by `writeTrail`.
 *
 * @param {THREE.Material} material
 * @returns {THREE.Mesh}
 */
function createTrailMesh(material) {
  const rows = TRAIL.segments + 1;
  const positions = new Float32Array(rows * 3 * 3);
  const colors = new Float32Array(rows * 3 * 4);
  const indices = [];

  for (let i = 0; i < rows; i++) {
    const s = i / TRAIL.segments;
    const alpha = smoothstep(0, 0.03, s) * Math.pow(1 - s, 1.7);
    colors.set([1, 1, 1, 0, 1, 1, 1, alpha, 1, 1, 1, 0], i * 12);
    if (i < TRAIL.segments) {
      const a = i * 3;
      indices.push(a, a + 1, a + 3, a + 1, a + 4, a + 3, a + 1, a + 2, a + 4, a + 2, a + 5, a + 4);
    }
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3).setUsage(THREE.DynamicDrawUsage));
  geometry.setAttribute('color', new THREE.BufferAttribute(colors, 4));
  geometry.setIndex(indices);

  const mesh = new THREE.Mesh(geometry, material);
  mesh.frustumCulled = false; // bounds change every frame; ribbon is tiny
  return mesh;
}

/**
 * Create all planes, their contrails and optional dashed route arcs.
 *
 * @param {{ palette: Record<string, THREE.Color>, camera: THREE.Camera }} ctx
 * @returns {{
 *   object: THREE.Group,
 *   planes: THREE.Group[],
 *   update: (elapsed: number, delta: number) => void,
 *   flyby: () => void,
 * }}
 *   Position `object` at the hotel-cluster anchor; curves are relative to it.
 *   `flyby()` makes the most visible airliner bank and surge past (see FLYBY).
 */
export function createAirplanes({ palette, camera }) {
  const group = new THREE.Group();

  const planeMaterials = {
    // Satin fuselage with a glossy clearcoat highlight; satin ink wings.
    paper: new THREE.MeshPhysicalMaterial({ color: palette.paper, roughness: 0.45, clearcoat: 1, clearcoatRoughness: 0.15 }),
    ink: new THREE.MeshPhysicalMaterial({ color: palette.ink, roughness: 0.5, clearcoat: 0.6, clearcoatRoughness: 0.3 }),
  };
  const arcMaterial = new THREE.LineDashedMaterial({
    color: palette.ink, transparent: true, opacity: 0.16, dashSize: 0.22, gapSize: 0.26,
  });

  const flights = FLIGHT_PATHS.map((def) => {
    const curve = new THREE.CubicBezierCurve3(...def.points.map((p) => new THREE.Vector3().fromArray(p)));

    const plane = buildPlaneModel(planeMaterials);
    group.add(plane);

    // One material per flight so each contrail can fade independently.
    const trailMaterial = new THREE.MeshBasicMaterial({
      color: palette.accent, vertexColors: true, transparent: true, depthWrite: false, side: THREE.DoubleSide,
    });
    const trails = [createTrailMesh(trailMaterial), createTrailMesh(trailMaterial)];
    group.add(...trails);

    if (def.showArc) {
      const arc = new THREE.Line(new THREE.BufferGeometry().setFromPoints(curve.getPoints(80)), arcMaterial);
      arc.computeLineDistances();
      group.add(arc);
    }

    return { def, curve, plane, trails, trailMaterial, fade: 0, boost: 0, flybyAt: null };
  });

  // Scratch vectors - reused every frame, never allocated in the loop.
  const point = new THREE.Vector3();
  const tangent = new THREE.Vector3();
  const ahead = new THREE.Vector3();
  const lateral = new THREE.Vector3();
  const view = new THREE.Vector3();
  const side = new THREE.Vector3();
  const cross = new THREE.Vector3();

  /**
   * Rewrite both engine contrails for one flight. The two ribbons start at
   * the engines, converge toward the flight line and taper to a point.
   * @param {(typeof flights)[number]} flight
   * @param {number} head  Curve parameter (0–1) of the plane.
   */
  function writeTrail(flight, head) {
    const { curve, trails, def } = flight;

    for (let i = 0; i <= TRAIL.segments; i++) {
      const s = i / TRAIL.segments;
      const u = Math.max(0, head - 0.004 - s * TRAIL.span);
      curve.getPoint(u, point);
      curve.getTangent(u, tangent);

      // Engine axis (horizontal, perpendicular to travel); narrows with age.
      lateral.crossVectors(tangent, UP).normalize().multiplyScalar(ENGINE_OFFSET * def.scale * (1 - 0.55 * s));
      // Billboard axis: perpendicular to travel AND to the view direction.
      view.copy(camera.position).sub(group.position).sub(point);
      const halfWidth = TRAIL.width * def.scale * smoothstep(0, 0.04, s) * Math.pow(1 - s, 0.75);
      side.crossVectors(tangent, view).normalize().multiplyScalar(halfWidth);

      for (let t = 0; t < 2; t++) {
        const sign = t === 0 ? 1 : -1;
        const cx = point.x + lateral.x * sign;
        const cy = point.y + lateral.y * sign;
        const cz = point.z + lateral.z * sign;
        const attribute = trails[t].geometry.attributes.position;
        const v = i * 3;
        attribute.setXYZ(v, cx + side.x, cy + side.y, cz + side.z);
        attribute.setXYZ(v + 1, cx, cy, cz);
        attribute.setXYZ(v + 2, cx - side.x, cy - side.y, cz - side.z);
      }
    }
    trails[0].geometry.attributes.position.needsUpdate = true;
    trails[1].geometry.attributes.position.needsUpdate = true;
  }

  let now = 0;

  /** Bank + surge the airliner that is currently most visible (and not about to despawn). */
  function flyby() {
    let best = null;
    for (const flight of flights) {
      if (flight.plane.visible && flight.fade > (best?.fade ?? 0.3)) best = flight;
    }
    if (best) best.flybyAt = now;
  }

  /**
   * Advance every flight along its Bézier curve.
   * @param {number} elapsed  Seconds since scene start.
   * @param {number} [delta]  Seconds since the previous frame.
   */
  function update(elapsed, delta = 0) {
    now = elapsed;
    for (const flight of flights) {
      const { def, curve, plane, trails, trailMaterial } = flight;

      // Fly-by envelope: 0 → 1 → 0 over FLYBY.seconds. `boost` is extra time
      // banked along the curve, so the surge never snaps back afterwards.
      let pulse = 0;
      if (flight.flybyAt !== null) {
        const k = (elapsed - flight.flybyAt) / FLYBY.seconds;
        if (k >= 1) flight.flybyAt = null;
        else pulse = Math.sin(k * Math.PI);
        flight.boost += delta * FLYBY.surge * pulse;
      }

      const raw = ((elapsed + def.offset + flight.boost) % (def.duration + def.gap)) / def.duration;
      const active = raw <= 1;
      plane.visible = active;
      trails[0].visible = trails[1].visible = active;
      flight.fade = 0;
      if (!active) continue;

      // Fade in/out at the curve ends so spawn/despawn is never visible.
      const fade = smoothstep(0, 0.08, raw) * (1 - smoothstep(0.9, 1, raw));

      curve.getPoint(raw, point);
      curve.getTangent(raw, tangent);
      plane.position.copy(point);
      // lookAt() expects a WORLD-space target, but the curve lives in this
      // group's local space → add the group offset, or the nose points astray.
      plane.lookAt(ahead.copy(point).add(tangent).add(group.position)); // +Z (nose) along travel

      // Bank into the turn: compare heading now vs. slightly ahead.
      curve.getTangent(Math.min(1, raw + 0.03), ahead);
      const turn = cross.crossVectors(tangent, ahead).y;
      plane.rotateZ(THREE.MathUtils.clamp(-turn * 9, -0.6, 0.6) + pulse * FLYBY.bank);
      plane.scale.setScalar(def.scale * Math.max(fade, 0.001) * (1 + 0.1 * pulse));
      flight.fade = fade;

      trailMaterial.opacity = fade;
      writeTrail(flight, raw);
    }
  }

  return { object: group, planes: flights.map((flight) => flight.plane), update, flyby };
}
