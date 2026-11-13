/**
 * scene/actors/itinerary.js - `Itinerary`: the glowing trip line.
 *
 * A delicate accent line drawn on the plinth that ties the package
 * together: it leaves the hotel, joins the ring road (the transfer) and
 * follows it to the monument arch (the attraction).
 *
 *   hotel pin ──spur──▶ road ──arc along the transfer path──▶ arch marker
 *
 * Parts: a thin solid ribbon, a wider translucent ribbon underneath (the
 * "glow"), stop markers (pins) at hotel / transfer / attraction, and a small
 * pulse that travels the line. Mount on `island.mount`. Route definition:
 * PLINTH.itinerary in config.js.
 */

import * as THREE from 'three';
import { PLINTH } from '../config.js';

const UP = new THREE.Vector3(0, 1, 0);

/**
 * Flat ribbon lying on the ground along a curve.
 * @param {THREE.Curve<THREE.Vector3>} curve
 * @param {number} width
 * @param {number} y  Height above the plinth (avoids z-fighting).
 * @param {number} [samples]
 * @returns {THREE.BufferGeometry}
 */
function buildRibbon(curve, width, y, samples = 120) {
  const positions = [];
  const indices = [];
  const point = new THREE.Vector3();
  const tangent = new THREE.Vector3();
  const side = new THREE.Vector3();
  for (let i = 0; i <= samples; i++) {
    const t = i / samples;
    curve.getPointAt(t, point);
    curve.getTangentAt(t, tangent);
    side.crossVectors(tangent, UP).normalize().multiplyScalar(width / 2);
    positions.push(point.x + side.x, y, point.z + side.z, point.x - side.x, y, point.z - side.z);
    if (i < samples) {
      const a = i * 2;
      indices.push(a, a + 2, a + 1, a + 1, a + 2, a + 3);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setIndex(indices);
  return geometry;
}

/**
 * Create the itinerary line.
 *
 * @param {{ palette: Record<string, THREE.Color> }} ctx
 * @param {{ attractionTop: THREE.Vector3 }} anchors  Crown of the monument (from `createAttraction`).
 * @returns {{ object: THREE.Group, update: (elapsed: number) => void }}
 */
export function createItinerary({ palette }, { attractionTop }) {
  const { hotel, joinAngle, transferAngle, pulseSeconds } = PLINTH.itinerary;
  const radius = PLINTH.road.radius;
  const onRoad = (angle, r = radius) => new THREE.Vector3(Math.cos(angle) * r, 0, Math.sin(angle) * r);

  // Path: hotel → short spur → along the road from joinAngle to the arch.
  const points = [new THREE.Vector3(hotel[0], 0, hotel[1])];
  const steps = 14;
  for (let i = 0; i <= steps; i++) {
    points.push(onRoad(THREE.MathUtils.lerp(joinAngle, PLINTH.archAngle, i / steps)));
  }
  const curve = new THREE.CatmullRomCurve3(points, false, 'centripetal');

  const lineMaterial = new THREE.MeshBasicMaterial({ color: palette.accent, side: THREE.DoubleSide });
  const glowMaterial = new THREE.MeshBasicMaterial({
    color: palette.accent, transparent: true, opacity: 0.22, depthWrite: false, side: THREE.DoubleSide,
  });
  const inkMaterial = new THREE.MeshStandardMaterial({ color: palette.ink, roughness: 0.5 });

  const group = new THREE.Group();
  group.add(new THREE.Mesh(buildRibbon(curve, 0.11, 0.014), glowMaterial));
  group.add(new THREE.Mesh(buildRibbon(curve, 0.03, 0.018), lineMaterial));

  // ── Stop markers ───────────────────────────────────────────────────────
  const headGeometry = new THREE.SphereGeometry(0.055, 14, 10);
  const stemGeometry = new THREE.CylinderGeometry(0.008, 0.008, 1, 5);
  /**
   * Map-pin style marker: ink stem + accent head.
   * @param {THREE.Vector3} base  Foot of the pin.
   * @param {number} height  Stem height (0 = just the head at `base`).
   * @returns {THREE.Mesh} The head (pulsed in `update`).
   */
  const addPin = (base, height) => {
    if (height > 0) {
      const stem = new THREE.Mesh(stemGeometry, inkMaterial);
      stem.scale.y = height;
      stem.position.copy(base).setY(base.y + height / 2);
      group.add(stem);
    }
    const head = new THREE.Mesh(headGeometry, lineMaterial);
    head.position.copy(base).setY(base.y + height);
    group.add(head);
    return head;
  };

  const pins = [
    addPin(points[0], 0.3), // hotel
    addPin(onRoad(transferAngle, radius - PLINTH.road.width / 2 - 0.1), 0.24), // transfer stop, just inside the road
    addPin(attractionTop, 0), // attraction (sits on the monument's crown)
  ];

  // Travelling pulse: the plan "flowing" from hotel to attraction.
  const pulse = new THREE.Mesh(new THREE.SphereGeometry(0.04, 12, 8), lineMaterial);
  const pulseHalo = new THREE.Mesh(new THREE.SphereGeometry(0.09, 12, 8), glowMaterial);
  group.add(pulse, pulseHalo);

  /**
   * Animate the pulse along the line and breathe the pins in sequence.
   * @param {number} elapsed  Seconds since scene start.
   */
  function update(elapsed) {
    const t = (elapsed / pulseSeconds) % 1;
    curve.getPointAt(t, pulse.position);
    pulse.position.y = 0.05;
    pulseHalo.position.copy(pulse.position);
    // Fade the pulse in/out at the ends so it never pops.
    const fade = Math.sin(t * Math.PI);
    pulse.scale.setScalar(0.4 + fade * 0.6);
    pulseHalo.scale.setScalar(0.4 + fade * 0.8);

    pins.forEach((pin, i) => {
      pin.scale.setScalar(1 + 0.18 * Math.max(0, Math.sin(elapsed * 2.2 - i * 1.3)));
    });
  }

  return { object: group, update };
}
