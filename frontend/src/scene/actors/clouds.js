/**
 * scene/actors/clouds.js — drifting low-poly clouds for ambient depth.
 *
 * A few soft, high-key "puff" clusters drift left→right through a world-space box
 * behind the hotel cluster, wrapping around at the edges. Scene fog fades
 * the far ones into the canvas colour, which produces the depth layering.
 */

import * as THREE from 'three';
import { GeoBatch } from '../utils/batch.js';
import { seededRandom } from '../utils/random.js';
import { createRampMaterial } from '../utils/materials.js';
import { CLOUDS } from '../config.js';

/**
 * Build one cloud shape from 4–6 squashed, smooth-shaded spheres.
 * @param {() => number} rand  Seeded RNG.
 * @returns {THREE.BufferGeometry}
 */
export function buildCloudGeometry(rand) {
  const batch = new GeoBatch();
  const puffs = 4 + Math.floor(rand() * 3);
  for (let i = 0; i < puffs; i++) {
    const radius = 0.45 + rand() * 0.5;
    batch.add('cloud', new THREE.IcosahedronGeometry(radius, 2), {
      position: [(i - (puffs - 1) / 2) * 0.62, (rand() - 0.5) * 0.3, (rand() - 0.5) * 0.5],
      scale: [1, 0.62, 0.9],
    });
  }
  // Pull the merged geometry out of the batch's wrapper mesh.
  return batch.build({ cloud: null }).children[0].geometry;
}

/**
 * Soft, high-key cloud material: smooth shading, white highlights and a
 * shadow tone only a whisper darker than the canvas.
 * @param {Record<string, THREE.Color>} palette
 * @returns {THREE.Material}
 */
export function createCloudMaterial(palette) {
  return createRampMaterial({
    shadow: palette.cloudShade, light: palette.white, range: [0.35, 0.95], flatShading: false,
  });
}

/**
 * Create the cloud field.
 *
 * @param {{ palette: Record<string, THREE.Color> }} ctx
 * @returns {{ object: THREE.Group, update: (elapsed: number, delta: number) => void }}
 */
export function createClouds({ palette }) {
  const rand = seededRandom(7);
  const { bounds, speed, count } = CLOUDS;

  const material = createCloudMaterial(palette);
  const variants = [buildCloudGeometry(rand), buildCloudGeometry(rand), buildCloudGeometry(rand)];

  const group = new THREE.Group();
  const clouds = Array.from({ length: count }, (_, i) => {
    const mesh = new THREE.Mesh(variants[i % variants.length], material);
    const baseY = THREE.MathUtils.lerp(bounds.yMin, bounds.yMax, rand());
    mesh.position.set(
      THREE.MathUtils.lerp(-bounds.x, bounds.x, rand()),
      baseY,
      THREE.MathUtils.lerp(bounds.zNear, bounds.zFar, rand()),
    );
    mesh.scale.setScalar(0.8 + rand() * 1.1);
    group.add(mesh);
    return {
      mesh,
      baseY,
      speed: THREE.MathUtils.lerp(speed[0], speed[1], rand()),
      phase: rand() * Math.PI * 2,
    };
  });

  /**
   * Drift + gentle vertical bob; wrap to the left edge when leaving the box.
   * @param {number} elapsed  Seconds since scene start.
   * @param {number} delta    Seconds since last frame.
   */
  function update(elapsed, delta) {
    for (const cloud of clouds) {
      cloud.mesh.position.x += cloud.speed * delta;
      if (cloud.mesh.position.x > bounds.x) cloud.mesh.position.x = -bounds.x;
      cloud.mesh.position.y = cloud.baseY + Math.sin(elapsed * 0.35 + cloud.phase) * 0.18;
    }
  }

  return { object: group, update };
}
