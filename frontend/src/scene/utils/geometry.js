/**
 * scene/utils/geometry.js — small 2D-outline → 3D helpers shared by actors.
 */

import * as THREE from 'three';

/**
 * Thin extruded plate from a 2D outline (wings, fins, panels).
 * @param {number[][]} outline  [x, y] points.
 * @param {number} thickness
 * @returns {THREE.ExtrudeGeometry} Plate in the XY plane, extruded along +Z.
 */
export function plate(outline, thickness) {
  const shape = new THREE.Shape(outline.map(([x, y]) => new THREE.Vector2(x, y)));
  return new THREE.ExtrudeGeometry(shape, { depth: thickness, bevelEnabled: false });
}

/**
 * Trace a rounded rectangle centred on (cx, cy) into a Shape or Path.
 * Works for outlines and for holes (`shape.holes.push(roundedRect(new THREE.Path(), …))`).
 *
 * @template {THREE.Path} T
 * @param {T} path  Shape/Path to draw into.
 * @param {number} cx
 * @param {number} cy
 * @param {number} width
 * @param {number} height
 * @param {number} radius  Corner radius.
 * @returns {T} The same path, for chaining.
 */
export function roundedRect(path, cx, cy, width, height, radius) {
  const x = cx - width / 2;
  const y = cy - height / 2;
  const r = Math.min(radius, width / 2, height / 2);
  path.moveTo(x + r, y);
  path.lineTo(x + width - r, y);
  path.quadraticCurveTo(x + width, y, x + width, y + r);
  path.lineTo(x + width, y + height - r);
  path.quadraticCurveTo(x + width, y + height, x + width - r, y + height);
  path.lineTo(x + r, y + height);
  path.quadraticCurveTo(x, y + height, x, y + height - r);
  path.lineTo(x, y + r);
  path.quadraticCurveTo(x, y, x + r, y);
  return path;
}
