/**
 * scene/actors/attraction.js — `Attraction`: a stylised monument arch.
 *
 * The "local landmark" part of the holiday package: a classical gateway
 * arch (two piers, round-headed opening, cornice and attic) standing on the
 * rim of the plinth, straddling the ring road so the shuttle drives through.
 *
 * Static geometry; mount it on `island.mount`. Position: PLINTH.archAngle +
 * PLINTH.road.radius in config.js.
 */

import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { GeoBatch } from '../utils/batch.js';
import { PLINTH } from '../config.js';

/** Arch proportions (local units; X = across the road, Y = up, Z = along it). */
const ARCH = { width: 0.9, height: 0.92, depth: 0.3, opening: 0.42, springing: 0.42 };

/**
 * Arch body: a slab with a round-headed opening, drawn as ONE concave
 * outline (no hole → robust triangulation), extruded with a fine bevel.
 * @returns {THREE.ExtrudeGeometry} Centred on Z.
 */
function buildArchBody() {
  const half = ARCH.width / 2;
  const r = ARCH.opening / 2;
  const shape = new THREE.Shape();
  shape.moveTo(-half, 0);
  shape.lineTo(-r, 0);
  shape.lineTo(-r, ARCH.springing);
  shape.absarc(0, ARCH.springing, r, Math.PI, 0, true); // over the top, left → right
  shape.lineTo(r, 0);
  shape.lineTo(half, 0);
  shape.lineTo(half, ARCH.height);
  shape.lineTo(-half, ARCH.height);
  shape.closePath();

  const geometry = new THREE.ExtrudeGeometry(shape, {
    depth: ARCH.depth, curveSegments: 18, bevelEnabled: true, bevelSize: 0.012, bevelThickness: 0.012, bevelSegments: 2,
  });
  geometry.translate(0, 0, -ARCH.depth / 2);
  return geometry;
}

/**
 * Create the monument arch.
 *
 * @param {{ palette: Record<string, THREE.Color> }} ctx
 * @returns {{ object: THREE.Group, top: THREE.Vector3 }}
 *   `top` — crown of the monument in plinth-local space (the itinerary line
 *   ends its marker there).
 */
export function createAttraction({ palette }) {
  const materials = {
    paper: new THREE.MeshPhysicalMaterial({ color: palette.paper, roughness: 0.6 }),
    ink: new THREE.MeshPhysicalMaterial({ color: palette.ink, roughness: 0.4, clearcoat: 1, clearcoatRoughness: 0.12 }),
    glow: new THREE.MeshBasicMaterial({ color: palette.accent }),
  };

  const b = new GeoBatch();
  b.add('paper', buildArchBody());
  // Pier bases, cornice, attic block, and a slim ink reveal under the attic.
  for (const side of [-1, 1]) {
    b.add('ink', new THREE.BoxGeometry(0.28, 0.05, ARCH.depth + 0.07), { position: [side * 0.33, 0.025, 0] });
  }
  b.add('paper', new RoundedBoxGeometry(ARCH.width + 0.1, 0.06, ARCH.depth + 0.1, 2, 0.02), { position: [0, ARCH.height + 0.03, 0] });
  b.add('ink', new THREE.BoxGeometry(ARCH.width - 0.14, 0.03, ARCH.depth - 0.06), { position: [0, ARCH.height + 0.075, 0] });
  b.add('paper', new RoundedBoxGeometry(ARCH.width - 0.1, 0.13, ARCH.depth - 0.02, 2, 0.02), { position: [0, ARCH.height + 0.155, 0] });
  // Keystones glow softly on both faces.
  for (const side of [-1, 1]) {
    b.add('glow', new THREE.BoxGeometry(0.06, 0.08, 0.012), { position: [0, ARCH.springing + ARCH.opening / 2 + 0.06, side * (ARCH.depth / 2 + 0.014)] });
  }

  const object = b.build(materials, { castShadow: true, receiveShadow: true });
  const angle = PLINTH.archAngle;
  object.position.set(Math.cos(angle) * PLINTH.road.radius, 0, Math.sin(angle) * PLINTH.road.radius);
  object.rotation.y = -angle; // local X → radial, local Z → along the road

  const top = object.position.clone().setY(ARCH.height + 0.22);
  return { object, top };
}
