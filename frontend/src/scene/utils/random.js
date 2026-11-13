/**
 * scene/utils/random.js - deterministic randomness.
 *
 * The scene must look identical on every load (the composition is designed,
 * not accidental), so actors use a seeded generator instead of Math.random.
 */

/**
 * Mulberry32 seeded PRNG.
 * @param {number} seed
 * @returns {() => number} Function returning floats in [0, 1).
 */
export function seededRandom(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Position-hashed vertex jitter. Because the offset depends only on the
 * vertex position, duplicated vertices (non-indexed / seam vertices) move
 * together and the mesh never cracks.
 *
 * @param {import('three').BufferGeometry} geometry  Mutated in place.
 * @param {number} amount  Max displacement in world units.
 * @param {(x: number, y: number, z: number) => boolean} [filter]  Return false to pin a vertex.
 */
export function jitterVertices(geometry, amount, filter) {
  const pos = geometry.attributes.position;
  const hash = (x, y, z, k) => {
    const s = Math.sin(Math.round(x * 50) * 12.9898 + Math.round(y * 50) * 78.233 + Math.round(z * 50) * 37.719 + k) * 43758.5453;
    return s - Math.floor(s) - 0.5;
  };
  for (let i = 0; i < pos.count; i++) {
    const x = pos.getX(i);
    const y = pos.getY(i);
    const z = pos.getZ(i);
    if (filter && !filter(x, y, z)) continue;
    pos.setXYZ(i, x + hash(x, y, z, 1) * amount, y + hash(x, y, z, 2) * amount, z + hash(x, y, z, 3) * amount);
  }
  pos.needsUpdate = true;
  geometry.computeVertexNormals();
}
