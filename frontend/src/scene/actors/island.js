/**
 * scene/actors/island.js — sculpted floating plinth (terrain).
 *
 * Builds the main low-poly island (light plateau + faceted ink rock keel)
 * and two small satellite islets. The hotel cluster is mounted on top by
 * `createScene.js`; this module owns the terrain and its idle "float".
 *
 * The rock uses a ramp material (see utils/materials.js) so every facet of
 * the dark slate shows a distinct tone under the key / rim / fill lights.
 */

import * as THREE from 'three';
import { GeoBatch } from '../utils/batch.js';
import { jitterVertices } from '../utils/random.js';
import { createRampMaterial } from '../utils/materials.js';
import { ISLAND } from '../config.js';

/**
 * Add one island (plateau + faceted rock keel + hanging shards) to a batch.
 * @param {GeoBatch} batch
 * @param {number} radius  Plateau radius.
 * @param {number} depth   Height of the rock keel below the plateau.
 */
function addIsland(batch, radius, depth) {
  // Plateau: a thin 12-sided slab. Top face stays perfectly flat (y = 0).
  batch.add('ground', new THREE.CylinderGeometry(radius, radius * 1.03, 0.26, 12, 1), {
    position: [0, -0.13, 0],
  });

  // Strata collar: a chunky jittered band right under the plateau.
  const collar = new THREE.CylinderGeometry(radius * 0.99, radius * 0.8, depth * 0.3, 12, 1).toNonIndexed();
  jitterVertices(collar, radius * 0.1, (_x, y) => y < depth * 0.15 - 0.01);
  batch.add('rock', collar, { position: [0, -0.26 - depth * 0.15, 0] });

  // Keel: inverted cone with 4 height bands, heavily jittered → chiselled
  // facets. The top rim is pinned so it tucks inside the collar.
  const keel = new THREE.ConeGeometry(radius * 0.86, depth, 12, 4).toNonIndexed();
  keel.rotateX(Math.PI);
  jitterVertices(keel, radius * 0.2, (_x, y) => y < depth / 2 - 0.01);
  batch.add('rock', keel, { position: [0, -0.26 - depth * 0.2 - depth / 2, 0] });

  // Hanging shards break up the silhouette.
  for (const [angle, reach, size] of [[0.6, 0.55, 0.3], [2.5, 0.5, 0.24], [4.4, 0.6, 0.2]]) {
    const shard = new THREE.ConeGeometry(radius * size * 0.5, depth * size * 2.2, 5, 1).toNonIndexed();
    shard.rotateX(Math.PI);
    jitterVertices(shard, radius * 0.05);
    batch.add('rock', shard, {
      position: [Math.cos(angle) * radius * reach, -0.26 - depth * 0.45, Math.sin(angle) * radius * reach],
    });
  }
}

/**
 * Create the floating terrain.
 *
 * @param {{ palette: Record<string, THREE.Color> }} ctx
 * @returns {{ object: THREE.Group, mount: THREE.Group, update: (elapsed: number) => void }}
 *   `object` — whole terrain group (add to the stage).
 *   `mount`  — the spinning main island; add buildings to it.
 *   `update` — advances the idle spin / bob animation.
 */
export function createIsland({ palette }) {
  const materials = {
    ground: new THREE.MeshStandardMaterial({ color: palette.ground, flatShading: true, roughness: 1 }),
    rock: createRampMaterial({ shadow: palette.ink, light: palette.rockLit, range: [0.6, 1.7] }),
    foliage: createRampMaterial({ shadow: palette.foliage, light: palette.foliageLit, range: [0.7, 2.2] }),
  };

  const root = new THREE.Group();

  // Main island — everything mounted on it spins with it.
  const mainBatch = new GeoBatch();
  addIsland(mainBatch, 3, 1.9);
  const main = mainBatch.build(materials, { castShadow: true, receiveShadow: true });
  root.add(main);

  // Satellite islets — each bobs on its own phase for a "floating physics" feel.
  const islets = [
    { position: [-4.3, -0.9, -2.2], radius: 0.8, depth: 0.9, phase: 1.7 },
    { position: [3.9, 1.5, -3.4], radius: 0.55, depth: 0.7, phase: 3.9 },
  ].map((def) => {
    const batch = new GeoBatch();
    addIsland(batch, def.radius, def.depth);
    batch.add('foliage', new THREE.ConeGeometry(def.radius * 0.3, def.radius * 0.9, 6), {
      position: [def.radius * 0.2, def.radius * 0.45, 0],
    });
    const islet = batch.build(materials, { castShadow: true, receiveShadow: true });
    islet.position.fromArray(def.position);
    root.add(islet);
    return { object: islet, baseY: def.position[1], phase: def.phase };
  });

  /**
   * Idle animation: slow continuous spin, sinusoidal bob, a hint of sway.
   * @param {number} elapsed  Seconds since scene start.
   */
  function update(elapsed) {
    main.rotation.y = elapsed * ISLAND.spin;
    root.position.y = Math.sin(elapsed * ISLAND.bobSpeed) * ISLAND.bobAmplitude;
    root.rotation.z = Math.sin(elapsed * 0.4) * 0.012;
    for (const islet of islets) {
      islet.object.position.y = islet.baseY + Math.sin(elapsed * 0.8 + islet.phase) * 0.18;
      islet.object.rotation.y = elapsed * 0.1 + islet.phase;
    }
  }

  return { object: root, mount: main, update };
}
