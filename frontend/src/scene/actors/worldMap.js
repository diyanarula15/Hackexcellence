/**
 * scene/actors/worldMap.js — `WorldMap`: line-art world map backdrop.
 *
 * A flat, very faint drawing far behind the hero scene:
 *   • continent contours (thin ink lines)
 *   • latitude / longitude graticule (even fainter)
 *   • a few curved, dashed accent route arcs with endpoint dots and a soft
 *     glowing pulse (halo + short comet tail) travelling gently along each
 *
 * It ignores fog and never writes depth, so it reads as a printed backdrop:
 * clouds, planes and the plinth always sit in front of it. It fades in as
 * the camera leaves the cabin (it must not be visible through the window).
 *
 * Coastline data: `data/worldOutline.json` (Natural Earth 110m, public
 * domain) — regenerate with `node scripts/build-world-map.mjs`.
 * Projection: plain equirectangular (x = longitude, y = latitude), in
 * degrees; the group is then scaled to fill the view (see `layout`).
 * All tunables: WORLD_MAP in config.js.
 */

import * as THREE from 'three';
import outline from '../data/worldOutline.json';
import { CAMERA, WORLD_MAP } from '../config.js';

const smoothstep = (a, b, x) => {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
};

/**
 * Coastline rings → one LineSegments geometry (a single draw call).
 * Segments lying on, or jumping across, the ±180° seam (artefacts of the
 * source data) are skipped.
 * @returns {THREE.BufferGeometry}
 */
function buildContours() {
  const vertices = [];
  for (const ring of outline) {
    for (let i = 0; i + 3 < ring.length; i += 2) {
      const [lonA, latA, lonB, latB] = [ring[i], ring[i + 1], ring[i + 2], ring[i + 3]];
      if (Math.abs(lonA) > 179.9 && Math.abs(lonB) > 179.9) continue; // seam edge
      if (Math.abs(lonA - lonB) > 180) continue; // ring wraps the antimeridian
      vertices.push(lonA, latA - WORLD_MAP.latCenter, 0, lonB, latB - WORLD_MAP.latCenter, 0);
    }
  }
  return new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
}

/**
 * Latitude / longitude grid lines every `gridStep` degrees.
 * @returns {THREE.BufferGeometry}
 */
function buildGraticule() {
  const { gridStep, latRange, latCenter } = WORLD_MAP;
  const [south, north] = latRange;
  const vertices = [];
  for (let lon = -180; lon <= 180; lon += gridStep) {
    vertices.push(lon, south - latCenter, 0, lon, north - latCenter, 0);
  }
  for (let lat = Math.ceil(south / gridStep) * gridStep; lat <= north; lat += gridStep) {
    vertices.push(-180, lat - latCenter, 0, 180, lat - latCenter, 0);
  }
  return new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
}

/** Points in each pulse's comet tail. */
const TAIL_POINTS = 20;

/**
 * Soft radial alpha mask for the pulse halo (white; the material tints it
 * with the accent colour, so no colour is hard-coded here).
 * @returns {THREE.CanvasTexture}
 */
function buildGlowTexture() {
  const size = 64;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const context = canvas.getContext('2d');
  const gradient = context.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  gradient.addColorStop(0, 'rgba(255,255,255,1)');
  gradient.addColorStop(0.3, 'rgba(255,255,255,0.45)');
  gradient.addColorStop(1, 'rgba(255,255,255,0)');
  context.fillStyle = gradient;
  context.fillRect(0, 0, size, size);
  return new THREE.CanvasTexture(canvas);
}

/**
 * Comet-tail line: TAIL_POINTS vertices, alpha baked from 0 (tail end) to 1
 * (head). Positions are rewritten every frame.
 * @param {THREE.Material} material
 * @returns {THREE.Line}
 */
function createTail(material) {
  const colors = new Float32Array(TAIL_POINTS * 4);
  for (let i = 0; i < TAIL_POINTS; i++) colors.set([1, 1, 1, (i / (TAIL_POINTS - 1)) ** 2], i * 4);
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute(
    'position',
    new THREE.BufferAttribute(new Float32Array(TAIL_POINTS * 3), 3).setUsage(THREE.DynamicDrawUsage),
  );
  geometry.setAttribute('color', new THREE.BufferAttribute(colors, 4));
  const tail = new THREE.Line(geometry, material);
  tail.frustumCulled = false;
  return tail;
}

/**
 * Create the map backdrop.
 *
 * @param {{ palette: Record<string, THREE.Color> }} ctx
 * @returns {{
 *   object: THREE.Group,
 *   layout: (camera: THREE.PerspectiveCamera) => void,
 *   update: (elapsed: number, delta: number, state: import('../choreography.js').ChoreographyState) => void,
 * }}
 */
export function createWorldMap({ palette }) {
  const group = new THREE.Group();
  group.renderOrder = -1;

  /** Backdrop material: no fog, no depth write, starts invisible. */
  const backdrop = (Material, options) =>
    new Material({ transparent: true, opacity: 0, depthWrite: false, fog: false, ...options });

  const contourMaterial = backdrop(THREE.LineBasicMaterial, { color: palette.ink });
  const gridMaterial = backdrop(THREE.LineBasicMaterial, { color: palette.ink });
  const routeMaterial = backdrop(THREE.LineDashedMaterial, { color: palette.accent, dashSize: 2.4, gapSize: 1.8 });
  const dotMaterial = backdrop(THREE.MeshBasicMaterial, { color: palette.accent });

  group.add(new THREE.LineSegments(buildGraticule(), gridMaterial));
  group.add(new THREE.LineSegments(buildContours(), contourMaterial));

  // ── Route arcs ─────────────────────────────────────────────────────────
  const dotGeometry = new THREE.CircleGeometry(1, 20);
  const glowGeometry = new THREE.PlaneGeometry(2, 2);
  const glowTexture = buildGlowTexture();
  const routes = WORLD_MAP.routes.map((route, index) => {
    const from = new THREE.Vector3(route.from[0], route.from[1] - WORLD_MAP.latCenter, 0);
    const to = new THREE.Vector3(route.to[0], route.to[1] - WORLD_MAP.latCenter, 0);
    // Control point: midpoint lifted "north" in proportion to the distance.
    const control = from.clone().lerp(to, 0.5);
    control.y += from.distanceTo(to) * route.lift;
    const curve = new THREE.QuadraticBezierCurve3(from, control, to);

    const arc = new THREE.Line(new THREE.BufferGeometry().setFromPoints(curve.getPoints(64)), routeMaterial);
    arc.computeLineDistances(); // required for dashes
    group.add(arc);

    for (const end of [from, to]) {
      const dot = new THREE.Mesh(dotGeometry, dotMaterial);
      dot.position.copy(end).setZ(0.01);
      dot.scale.setScalar(WORLD_MAP.dotRadius);
      group.add(dot);
    }

    // Travelling pulse: bright core dot + soft halo + short fading tail. Each
    // route gets its own materials so its pulse can fade at the route ends.
    const glowMaterial = backdrop(THREE.MeshBasicMaterial, { color: palette.accent, map: glowTexture });
    const tailMaterial = backdrop(THREE.LineBasicMaterial, { color: palette.accent, vertexColors: true });
    const coreMaterial = backdrop(THREE.MeshBasicMaterial, { color: palette.accent });
    const traveller = new THREE.Mesh(dotGeometry, coreMaterial);
    traveller.scale.setScalar(WORLD_MAP.dotRadius * 0.7);
    const glow = new THREE.Mesh(glowGeometry, glowMaterial);
    const tail = createTail(tailMaterial);
    group.add(tail, glow, traveller);

    return { curve, traveller, glow, tail, glowMaterial, tailMaterial, coreMaterial, phase: index / WORLD_MAP.routes.length };
  });

  const direction = new THREE.Vector3();
  const sample = new THREE.Vector3();

  /**
   * Scale + place the map so it fills the hero view at any aspect ratio.
   * Call with the SETTLED hero camera (createScene.layout does).
   * @param {THREE.PerspectiveCamera} camera
   */
  function layout(camera) {
    camera.getWorldDirection(direction);
    const distance = (WORLD_MAP.z - camera.position.z) / direction.z;
    group.position.copy(camera.position).addScaledVector(direction, distance);
    group.position.y += WORLD_MAP.offsetY;

    const viewHeight = 2 * distance * Math.tan(THREE.MathUtils.degToRad(CAMERA.fov / 2));
    const viewWidth = viewHeight * camera.aspect;
    const [south, north] = WORLD_MAP.latRange;
    // Cover the width on landscape screens, the height on portrait ones.
    group.scale.setScalar(Math.max((viewWidth * WORLD_MAP.fill) / 360, (viewHeight * 0.8) / (north - south)));
  }

  /**
   * Fade in with the flight; move the travelling dots along their routes.
   * @param {number} elapsed
   * @param {number} _delta
   * @param {import('../choreography.js').ChoreographyState} state
   */
  function update(elapsed, _delta, state) {
    const reveal = smoothstep(0.55, 1, state.flight);
    group.visible = reveal > 0.001;
    if (!group.visible) return;

    contourMaterial.opacity = WORLD_MAP.contourOpacity * reveal;
    gridMaterial.opacity = WORLD_MAP.gridOpacity * reveal;
    routeMaterial.opacity = WORLD_MAP.routeOpacity * reveal;
    dotMaterial.opacity = WORLD_MAP.routeOpacity * reveal;

    const { pulse } = WORLD_MAP;
    for (const route of routes) {
      const raw = (elapsed / WORLD_MAP.routeSeconds + route.phase) % 1;
      const t = smoothstep(0, 1, raw); // eases out of one city and into the next
      const envelope = Math.sin(Math.PI * raw) ** 0.5 * reveal; // fades at both ends
      const breathe = 1 + 0.14 * Math.sin(elapsed * 2.2 + route.phase * 6.28);

      route.curve.getPoint(t, route.traveller.position);
      route.traveller.position.z = 0.03;
      route.glow.position.copy(route.traveller.position).setZ(0.02);
      route.glow.scale.setScalar(WORLD_MAP.dotRadius * pulse.glow * breathe);

      const positions = route.tail.geometry.attributes.position;
      for (let i = 0; i < TAIL_POINTS; i++) {
        route.curve.getPoint(Math.max(0, t - (1 - i / (TAIL_POINTS - 1)) * pulse.tail), sample);
        positions.setXYZ(i, sample.x, sample.y, 0.015);
      }
      positions.needsUpdate = true;

      route.coreMaterial.opacity = envelope;
      route.glowMaterial.opacity = pulse.opacity * envelope * (0.8 + 0.2 * breathe);
      route.tailMaterial.opacity = envelope;
    }
  }

  return { object: group, layout, update };
}
