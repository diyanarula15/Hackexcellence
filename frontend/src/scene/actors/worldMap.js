/**
 * scene/actors/worldMap.js — `WorldMap`: line-art world map backdrop.
 *
 * A flat, very faint drawing far behind the hero scene:
 *   • continent contours (thin ink lines)
 *   • latitude / longitude graticule (even fainter)
 *   • a few curved, dashed accent route arcs with endpoint dots and a small
 *     dot travelling along each route
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

    const traveller = new THREE.Mesh(dotGeometry, dotMaterial);
    traveller.scale.setScalar(WORLD_MAP.dotRadius * 0.7);
    group.add(traveller);

    return { curve, traveller, phase: index / WORLD_MAP.routes.length };
  });

  const direction = new THREE.Vector3();

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

    for (const route of routes) {
      const t = (elapsed / WORLD_MAP.routeSeconds + route.phase) % 1;
      route.curve.getPoint(t, route.traveller.position);
      route.traveller.position.z = 0.01;
    }
  }

  return { object: group, layout, update };
}
