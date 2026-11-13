/**
 * scene/actors/hotelLandmark.js — `HotelLandmark`: boutique hotel sculpture.
 *
 * Three buildings + landscaping, all merged into a handful of meshes:
 *   • a boutique hotel tower: glazed core, recessed balconies between floor
 *     slabs and bay fins, lobby podium, rooftop terrace, glowing accent windows
 *   • a stepped terrace resort
 *   • a low pavilion with a cantilevered roof, pool and parasols
 *
 * Transfers (road + shuttle), the attraction arch and the itinerary line
 * live in their own modules and share this plinth; the layout here keeps
 * clear of the ring road defined by PLINTH in config.js.
 *
 * Static geometry — it inherits motion from the island it is mounted on.
 * Local origin = centre of the island plateau, +Y up.
 */

import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { GeoBatch } from '../utils/batch.js';
import { createRampMaterial } from '../utils/materials.js';

const box = (w, h, d) => new THREE.BoxGeometry(w, h, d);
/** Box with softly bevelled edges — catches a highlight along every tier. */
const bevelBox = (w, h, d, r = 0.03) => new RoundedBoxGeometry(w, h, d, 2, r);

/** Lit-window positions as [bay 0–3, floor 0–8] on the two long façades. */
const LIT_WINDOWS = {
  front: [[0, 1], [2, 2], [3, 4], [1, 5], [2, 7], [0, 7]],
  back: [[1, 1], [3, 2], [0, 4], [2, 5], [3, 7]],
};

/**
 * Boutique hotel tower.
 *
 * Anatomy (bottom → top): glazed lobby podium with canopy → dark glazed core
 * wrapped by solid end walls → one floor slab per storey; the slabs and
 * vertical bay fins overhang the glazing, which reads as rows of recessed
 * balconies with slim railings → roof slab with pergola terrace, plunge
 * pool, service core and beacon mast.
 *
 * @param {GeoBatch} b
 * @param {number} x
 * @param {number} z
 */
function addTower(b, x, z) {
  const width = 0.95; // long façade (X)
  const depth = 0.7; // short side (Z)
  const floors = 9;
  const pitch = 0.27; // storey height
  const base = 0.3; // podium height
  const height = base + floors * pitch;
  const shaft = height - base;
  const midY = base + shaft / 2;
  const glassDepth = depth - 0.16; // glazing is recessed 0.08 behind slab edges

  // Lobby podium + canopy.
  b.add('ink', box(width + 0.3, base - 0.04, depth + 0.3), { position: [x, (base - 0.04) / 2, z] });
  b.add('paper', bevelBox(width + 0.44, 0.05, depth + 0.44, 0.02), { position: [x, base - 0.02, z] });

  // Glazed core, solid end walls, vertical bay fins.
  b.add('ink', box(width - 0.12, shaft, glassDepth), { position: [x, midY, z] });
  for (const side of [-1, 1]) {
    b.add('paper', box(0.07, shaft, depth), { position: [x + side * (width / 2 - 0.035), midY, z] });
  }
  for (const dx of [-0.2, 0, 0.2]) {
    b.add('paper', box(0.018, shaft, depth - 0.03), { position: [x + dx, midY, z] });
  }

  // Floor slabs (balcony decks) + railings on both long façades.
  for (let floor = 0; floor < floors; floor++) {
    const y = base + floor * pitch;
    b.add('paper', box(width, 0.035, depth), { position: [x, y + pitch - 0.0175, z] });
    for (const side of [-1, 1]) {
      b.add('stone', box(width - 0.14, 0.06, 0.012), { position: [x, y + 0.03, z + side * (depth / 2 - 0.006)] });
    }
  }

  // Glowing accent windows — warm rooms behind the balconies.
  const bayX = (bay) => x - 0.3 + bay * 0.2;
  for (const [face, side] of [['front', 1], ['back', -1]]) {
    for (const [bay, floor] of LIT_WINDOWS[face]) {
      b.add('glow', box(0.15, 0.17, 0.01), {
        position: [bayX(bay), base + floor * pitch + 0.115, z + side * (glassDepth / 2 + 0.006)],
      });
    }
  }

  // Rooftop terrace: roof slab, pergola, plunge pool, service core, beacon.
  const roof = height + 0.05;
  b.add('paper', bevelBox(width + 0.1, 0.06, depth + 0.1, 0.025), { position: [x, height + 0.025, z] });
  for (const px of [-0.4, -0.02]) {
    for (const pz of [-0.2, 0.2]) {
      b.add('ink', new THREE.CylinderGeometry(0.01, 0.01, 0.2, 5), { position: [x + px, roof + 0.1, z + pz] });
    }
  }
  b.add('paper', box(0.46, 0.022, 0.48), { position: [x - 0.21, roof + 0.21, z] });
  b.add('stone', box(0.26, 0.012, 0.16), { position: [x + 0.27, roof + 0.006, z + 0.2] });
  b.add('ink', box(0.22, 0.16, 0.2), { position: [x + 0.29, roof + 0.08, z - 0.16] });
  b.add('ink', new THREE.CylinderGeometry(0.01, 0.01, 0.36, 5), { position: [x + 0.29, roof + 0.34, z - 0.16] });
  b.add('glow', box(0.06, 0.06, 0.06), { position: [x + 0.29, roof + 0.55, z - 0.16] });
}

/**
 * Stepped terrace resort: stacked slabs receding upward, shadow-gap bands,
 * and a couple of lit suites.
 * @param {GeoBatch} b
 * @param {number} x
 * @param {number} z
 */
function addTerraces(b, x, z) {
  const levels = 4;
  for (let i = 0; i < levels; i++) {
    const depth = 1.5 - i * 0.3;
    const y = i * 0.34;
    const zOffset = z - i * 0.15;
    b.add('ink', box(1.86, 0.08, depth - 0.06), { position: [x, y + 0.04, zOffset] });
    b.add('paper', bevelBox(1.9, 0.26, depth), { position: [x, y + 0.21, zOffset] });
    if (i % 2 === 0) {
      b.add('glow', box(0.16, 0.05, 0.01), {
        position: [x - 0.5 + i * 0.45, y + 0.04, zOffset + (depth - 0.06) / 2 + 0.006],
      });
    }
  }
}

/**
 * Low pavilion with a cantilevered roof slab, a pool and two parasols.
 * @param {GeoBatch} b
 * @param {number} x
 * @param {number} z
 */
function addPavilion(b, x, z) {
  b.add('paper', bevelBox(1.1, 0.36, 0.7), { position: [x, 0.18, z] });
  b.add('ink', box(0.7, 0.2, 0.72), { position: [x + 0.1, 0.16, z] });
  b.add('ink', box(1.4, 0.05, 1.0), { position: [x, 0.385, z] });

  // Pool deck + water plane (kept in the neutral family — accent is reserved).
  b.add('paper', box(1.2, 0.03, 0.66), { position: [x + 1.35, 0.015, z + 0.1] });
  b.add('stone', box(1.0, 0.03, 0.46), { position: [x + 1.35, 0.022, z + 0.1] });

  // Parasols: the smallest accent "micro-states" in the composition.
  for (const dx of [0.95, 1.75]) {
    b.add('ink', new THREE.CylinderGeometry(0.01, 0.01, 0.26, 5), { position: [x + dx, 0.13, z + 0.62] });
    b.add('glow', new THREE.ConeGeometry(0.14, 0.08, 8), { position: [x + dx, 0.29, z + 0.62] });
  }
}

/**
 * Stylised conifer (two stacked cones for a crisper silhouette).
 * @param {GeoBatch} b
 * @param {number} x
 * @param {number} z
 * @param {number} size
 */
function addTree(b, x, z, size) {
  b.add('ink', new THREE.CylinderGeometry(0.02, 0.02, 0.16 * size, 5), { position: [x, 0.08 * size, z] });
  b.add('foliage', new THREE.ConeGeometry(0.17 * size, 0.4 * size, 6), { position: [x, 0.34 * size, z] });
  b.add('foliage', new THREE.ConeGeometry(0.12 * size, 0.34 * size, 6), { position: [x, 0.56 * size, z] });
}

/**
 * Create the hotel landmark (tower + terrace resort + pavilion).
 *
 * @param {{ palette: Record<string, THREE.Color> }} ctx
 * @returns {{ object: THREE.Group }} Static group; mount it on the island.
 */
export function createHotelLandmark({ palette }) {
  const materials = {
    // Satin plaster, glossy clear-coated glass, satin stone — studio-model finishes.
    paper: new THREE.MeshPhysicalMaterial({ color: palette.paper, roughness: 0.6 }),
    ink: new THREE.MeshPhysicalMaterial({ color: palette.ink, roughness: 0.4, clearcoat: 1, clearcoatRoughness: 0.12 }),
    stone: new THREE.MeshPhysicalMaterial({ color: palette.stone, roughness: 0.45, clearcoat: 0.4 }),
    foliage: createRampMaterial({ shadow: palette.foliage, light: palette.foliageLit, range: [0.7, 2.2] }),
    // Unlit → always full-strength accent, i.e. it "glows" against the ink glazing.
    glow: new THREE.MeshBasicMaterial({ color: palette.accent }),
  };

  const batch = new GeoBatch();
  addTower(batch, -0.7, -0.6);
  addTerraces(batch, 0.9, -0.5);
  addPavilion(batch, -0.95, 0.95);

  // Trees: an outer row on the rim (outside the ring road, as [angle°, size])
  // plus a few inside it. Everything stays clear of the road (PLINTH.road)
  // and of the monument arch at PLINTH.archAngle.
  const rimTrees = [[20, 0.8], [72, 0.75], [100, 0.9], [126, 0.7], [160, 1.0], [205, 0.8], [250, 1.0], [276, 0.75], [320, 0.9], [350, 0.7]];
  for (const [degrees, size] of rimTrees) {
    const angle = THREE.MathUtils.degToRad(degrees);
    addTree(batch, Math.cos(angle) * 2.8, Math.sin(angle) * 2.8, size);
  }
  const innerTrees = [[-1.3, -1.6, 0.8], [1.6, 0.9, 0.8], [0.2, -1.9, 0.9]];
  for (const [x, z, size] of innerTrees) addTree(batch, x, z, size);

  const object = batch.build(materials, { castShadow: true, receiveShadow: true });
  return { object };
}
