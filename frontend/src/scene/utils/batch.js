/**
 * scene/utils/batch.js - tiny geometry-merging helper.
 *
 * Low-poly models are built from many primitives. Rendering each primitive
 * as its own mesh wastes draw calls, so `GeoBatch` collects primitives per
 * material key and merges each bucket into ONE mesh (1 draw call / material).
 */

import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';

const _matrix = new THREE.Matrix4();
const _position = new THREE.Vector3();
const _quaternion = new THREE.Quaternion();
const _scale = new THREE.Vector3();
const _euler = new THREE.Euler();

/**
 * Collects transformed primitives and merges them per material.
 *
 * @example
 *   const batch = new GeoBatch();
 *   batch.add('paper', new THREE.BoxGeometry(1, 2, 1), { position: [0, 1, 0] });
 *   const group = batch.build({ paper: paperMaterial }, { castShadow: true });
 */
export class GeoBatch {
  constructor() {
    /** @type {Map<string, THREE.BufferGeometry[]>} */
    this.buckets = new Map();
  }

  /**
   * Add a primitive to a material bucket. The source geometry is consumed.
   * @param {string} key  Material key (resolved in `build`).
   * @param {THREE.BufferGeometry} geometry
   * @param {{ position?: number[], rotation?: number[], scale?: number | number[] }} [transform]
   * @returns {this}
   */
  add(key, geometry, { position = [0, 0, 0], rotation = [0, 0, 0], scale = 1 } = {}) {
    const geo = geometry.index ? geometry.toNonIndexed() : geometry;
    if (geo !== geometry) geometry.dispose();

    _position.fromArray(position);
    _quaternion.setFromEuler(_euler.set(rotation[0], rotation[1], rotation[2]));
    if (typeof scale === 'number') _scale.setScalar(scale);
    else _scale.fromArray(scale);
    geo.applyMatrix4(_matrix.compose(_position, _quaternion, _scale));

    if (!this.buckets.has(key)) this.buckets.set(key, []);
    this.buckets.get(key).push(geo);
    return this;
  }

  /**
   * Merge every bucket into a mesh and return them grouped.
   * @param {Record<string, THREE.Material>} materials  key → material.
   * @param {{ castShadow?: boolean, receiveShadow?: boolean }} [options]
   * @returns {THREE.Group}
   */
  build(materials, { castShadow = false, receiveShadow = false } = {}) {
    const group = new THREE.Group();
    for (const [key, geometries] of this.buckets) {
      const merged = mergeGeometries(geometries, false);
      geometries.forEach((g) => g.dispose());
      const mesh = new THREE.Mesh(merged, materials[key]);
      mesh.castShadow = castShadow;
      mesh.receiveShadow = receiveShadow;
      group.add(mesh);
    }
    this.buckets.clear();
    return group;
  }
}
