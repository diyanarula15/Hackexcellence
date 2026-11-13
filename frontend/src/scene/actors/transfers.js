/**
 * scene/actors/transfers.js - `Transfers`: ring road + gliding shuttle.
 *
 * The "ground transfer" part of the holiday package:
 *   • a clean, flat ring road circling the plinth just inside its rim
 *   • a minimalist shuttle that glides around it forever (and through the
 *     attraction arch, which straddles the road)
 *
 * Local origin = centre of the plinth top; mount it on `island.mount` so it
 * spins with the plinth. Geometry + speed: PLINTH.road / PLINTH.shuttle in
 * config.js. Angles are measured in the XZ plane: (cos a, sin a) · radius.
 */

import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { GeoBatch } from '../utils/batch.js';
import { PLINTH } from '../config.js';

/**
 * Build the shuttle: rounded ink body, wrap-around window band, four wheels,
 * accent headlights. Nose points +Z, ~0.34 units long.
 * @param {Record<string, THREE.Material>} materials
 * @returns {THREE.Group}
 */
function buildShuttle(materials) {
  const b = new GeoBatch();
  // Ink body for a crisp silhouette on the pale plinth; pale glazing band.
  b.add('ink', new RoundedBoxGeometry(0.14, 0.1, 0.34, 3, 0.035), { position: [0, 0.088, 0] });
  b.add('paper', new THREE.BoxGeometry(0.144, 0.034, 0.25), { position: [0, 0.106, 0.01] }); // side glazing
  b.add('paper', new THREE.BoxGeometry(0.1, 0.034, 0.344), { position: [0, 0.106, 0] }); // front/rear glazing
  for (const x of [-0.066, 0.066]) {
    for (const z of [-0.1, 0.1]) {
      b.add('ink', new THREE.CylinderGeometry(0.03, 0.03, 0.022, 10), { position: [x, 0.03, z], rotation: [0, 0, Math.PI / 2] });
    }
  }
  for (const x of [-0.04, 0.04]) {
    b.add('glow', new THREE.BoxGeometry(0.026, 0.016, 0.01), { position: [x, 0.066, 0.168] });
  }
  return b.build(materials, { castShadow: true });
}

/**
 * Create the road and its shuttle.
 *
 * @param {{ palette: Record<string, THREE.Color> }} ctx
 * @returns {{ object: THREE.Group, shuttle: THREE.Group, update: (elapsed: number) => void }}
 */
export function createTransfers({ palette }) {
  const { radius, width } = PLINTH.road;
  const materials = {
    road: new THREE.MeshStandardMaterial({ color: palette.stone, roughness: 0.7 }),
    paper: new THREE.MeshPhysicalMaterial({ color: palette.paper, roughness: 0.45, clearcoat: 1, clearcoatRoughness: 0.15 }),
    ink: new THREE.MeshPhysicalMaterial({ color: palette.ink, roughness: 0.4, clearcoat: 1, clearcoatRoughness: 0.12 }),
    glow: new THREE.MeshBasicMaterial({ color: palette.accent }),
  };

  const group = new THREE.Group();

  // Roadway: a flat ring, a hair above the plinth surface.
  const road = new THREE.Mesh(new THREE.RingGeometry(radius - width / 2, radius + width / 2, 72), materials.road);
  road.rotation.x = -Math.PI / 2;
  road.position.y = 0.006;
  road.receiveShadow = true;
  group.add(road);

  const shuttle = buildShuttle(materials);
  group.add(shuttle);

  /**
   * Glide the shuttle around the ring. Its +Z nose is kept tangent to the
   * road: for travel along +angle the heading is rotation.y = -angle.
   * @param {number} elapsed  Seconds since scene start.
   */
  function update(elapsed) {
    const angle = PLINTH.shuttle.startAngle + elapsed * PLINTH.shuttle.speed;
    shuttle.position.set(Math.cos(angle) * radius, 0.008, Math.sin(angle) * radius);
    shuttle.rotation.y = -angle + (PLINTH.shuttle.speed < 0 ? Math.PI : 0);
  }

  return { object: group, shuttle, update };
}
