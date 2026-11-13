/**
 * scene/actors/planeWindow.js — `PlaneWindow`: the Stage-1 airplane cabin.
 *
 * Two sub-groups, both positioned at CABIN.position (centre of the main
 * window on the interior wall; the camera sits at +Z, outside is -Z):
 *
 *   interior — matte off-white cabin wall with ONE rounded-rectangle window
 *              opening, ink trim rings (clearcoat), window shades with a
 *              coral pull-tab, exit-hatch seams and an "EMERGENCY EXIT"
 *              instruction placard (so it unmistakably reads as an aircraft).
 *              Fades + scales out as the camera flies through.
 *   exterior — what you see THROUGH the glass: the aircraft's own wing with
 *              a pulsing coral wingtip beacon, a distant banking airliner and
 *              a few near clouds. The wing banks away during Stage 2.
 *
 * Driven by the choreography state (see `update`).
 */

import * as THREE from 'three';
import { GeoBatch } from '../utils/batch.js';
import { plate, roundedRect } from '../utils/geometry.js';
import { CABIN } from '../config.js';
import { buildPlaneModel } from './airplanes.js';
import { buildCloudGeometry, createCloudMaterial } from './clouds.js';
import { seededRandom } from '../utils/random.js';

/**
 * Ring-shaped plate: rounded rectangle with a rounded-rectangle hole.
 * @param {number} cx  Centre X.
 * @param {number} outerPad  How far the ring extends beyond the window.
 * @param {number} innerPad  Inner edge offset from the window (0 = flush).
 * @param {number} depth  Extrusion depth.
 * @returns {THREE.ExtrudeGeometry}
 */
function windowRing(cx, outerPad, innerPad, depth) {
  const { width, height, radius } = CABIN.window;
  const shape = roundedRect(new THREE.Shape(), cx, 0, width + outerPad * 2, height + outerPad * 2, radius + outerPad);
  shape.holes.push(roundedRect(new THREE.Path(), cx, 0, width + innerPad * 2, height + innerPad * 2, radius + innerPad));
  return new THREE.ExtrudeGeometry(shape, { depth, bevelEnabled: false, curveSegments: 12 });
}

/**
 * Build the cabin interior: wall, window surrounds, trim, shades.
 * @param {Record<string, THREE.Material>} materials
 * @returns {THREE.Group}
 */
function buildInterior(materials) {
  const { width, height } = CABIN.window;
  const b = new GeoBatch();
  // A single window at x = 0; `shade` = closed fraction. (Add entries to
  // this list, spaced by CABIN.windowSpacing, for a row of windows.)
  const windows = [{ x: 0, shade: 0.16 }];

  // Wall slab with the window openings cut out (interior face at z = 0).
  const wall = new THREE.Shape([
    new THREE.Vector2(-10, -6), new THREE.Vector2(10, -6), new THREE.Vector2(10, 6), new THREE.Vector2(-10, 6),
  ]);
  for (const w of windows) wall.holes.push(roundedRect(new THREE.Path(), w.x, 0, width, height, CABIN.window.radius));
  b.add('wall', new THREE.ExtrudeGeometry(wall, { depth: CABIN.wallThickness, bevelEnabled: false, curveSegments: 12 }), {
    position: [0, 0, -CABIN.wallThickness],
  });

  for (const w of windows) {
    // Soft raised surround + crisp ink trim ring around the opening.
    b.add('wall', windowRing(w.x, 0.3, 0.05, 0.025), {});
    b.add('trim', windowRing(w.x, 0.055, 0, 0.05), {});

    // Shade: slides down from the top of the opening; coral pull-tab.
    const shadeHeight = height * w.shade;
    const shadeBottom = height / 2 - shadeHeight;
    b.add('wall', new THREE.BoxGeometry(width, shadeHeight, 0.02), { position: [w.x, height / 2 - shadeHeight / 2, -0.06] });
    b.add('trim', new THREE.BoxGeometry(width, 0.025, 0.03), { position: [w.x, shadeBottom, -0.055] });
    b.add('accent', new THREE.BoxGeometry(0.16, 0.04, 0.035), { position: [w.x, shadeBottom - 0.008, -0.04] });
  }

  // Vertical seams either side of the window: the edges of the exit hatch.
  for (const x of [-0.95, 0.95]) {
    b.add('seam', new THREE.BoxGeometry(0.012, 12, 0.004), { position: [x, 0, 0.002] });
  }

  return b.build(materials);
}

/**
 * Paint the emergency-exit instruction placard onto a 2D canvas.
 * Uses only the three theme colours: coral header band, ink pictograms and
 * text on the off-white card. Corners outside the rounded card stay
 * transparent (the material alpha-tests them away).
 *
 * @param {HTMLCanvasElement} canvas  560 × 720 canvas to draw into.
 * @param {{ canvas: string, ink: string, accent: string }} colors  CSS colours.
 */
function paintPlacard(canvas, colors) {
  const g = canvas.getContext('2d');
  const W = canvas.width;
  const H = canvas.height;
  const font = (weight, size) => `${weight} ${size}px Inter, "Helvetica Neue", Arial, sans-serif`;
  g.clearRect(0, 0, W, H);

  // Card with ink keyline.
  g.beginPath();
  g.roundRect(6, 6, W - 12, H - 12, 44);
  g.fillStyle = colors.canvas;
  g.fill();
  g.lineWidth = 8;
  g.strokeStyle = colors.ink;
  g.stroke();

  // Header band.
  g.save();
  g.clip();
  g.fillStyle = colors.accent;
  g.fillRect(0, 0, W, 132);
  g.restore();
  g.fillStyle = colors.canvas;
  g.textAlign = 'center';
  g.textBaseline = 'middle';
  g.font = font(800, 46);
  g.fillText('EMERGENCY EXIT', W / 2, 72);

  // Pictogram: hatch with window, pull handle, "push out" arrow.
  g.strokeStyle = colors.ink;
  g.fillStyle = colors.ink;
  g.lineWidth = 9;
  g.lineJoin = 'round';
  g.lineCap = 'round';
  g.beginPath();
  g.roundRect(96, 184, 168, 220, 26); // hatch
  g.stroke();
  g.beginPath();
  g.roundRect(144, 262, 72, 100, 26); // its window
  g.stroke();
  g.beginPath();
  g.roundRect(132, 208, 96, 24, 12); // handle recess
  g.fill();
  // Handle arrow (pull down) in accent.
  g.strokeStyle = colors.accent;
  g.fillStyle = colors.accent;
  g.beginPath();
  g.moveTo(180, 220);
  g.lineTo(180, 252);
  g.stroke();
  // Push-out arrow.
  g.lineWidth = 14;
  g.beginPath();
  g.moveTo(300, 294);
  g.lineTo(420, 294);
  g.stroke();
  g.beginPath();
  g.moveTo(470, 294);
  g.lineTo(414, 258);
  g.lineTo(414, 330);
  g.closePath();
  g.fill();

  // Numbered steps.
  const steps = ['PULL HANDLE DOWN', 'PUSH HATCH OUT', 'EXIT OVER WING'];
  g.textAlign = 'left';
  steps.forEach((label, i) => {
    const y = 468 + i * 62;
    g.fillStyle = colors.ink;
    g.beginPath();
    g.arc(118, y, 22, 0, Math.PI * 2);
    g.fill();
    g.fillStyle = colors.canvas;
    g.textAlign = 'center';
    g.font = font(800, 26);
    g.fillText(String(i + 1), 118, y + 1);
    g.fillStyle = colors.ink;
    g.textAlign = 'left';
    g.font = font(700, 30);
    g.fillText(label, 160, y + 1);
  });

  // Footer rule + caption.
  g.fillStyle = colors.ink;
  g.globalAlpha = 0.55;
  g.textAlign = 'center';
  g.font = font(600, 20);
  g.fillText('ROW 14  ·  OVERWING EXIT', W / 2, 672);
  g.globalAlpha = 1;
}

/**
 * Create the placard mesh (canvas texture on a small wall-mounted plane).
 * Repaints once web fonts finish loading so the lettering uses the UI font.
 *
 * @param {Record<string, THREE.Color>} palette
 * @returns {{ mesh: THREE.Mesh, material: THREE.MeshBasicMaterial }}
 */
function createPlacard(palette) {
  const canvas = document.createElement('canvas');
  canvas.width = 560;
  canvas.height = 720;
  const css = (color) => `#${color.getHexString()}`;
  const colors = { canvas: css(palette.canvas), ink: css(palette.ink), accent: css(palette.accent) };

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 8;
  const repaint = () => {
    paintPlacard(canvas, colors);
    texture.needsUpdate = true;
  };
  repaint();
  document.fonts?.ready.then(repaint);

  // Unlit, so the card shows the exact theme colours it was printed with.
  const material = new THREE.MeshBasicMaterial({ map: texture, alphaTest: 0.5, transparent: true });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(0.7, 0.9), material);
  mesh.position.set(-1.62, 0, 0.012); // on the wall, left of the window
  return { mesh, material };
}

/**
 * Build the aircraft's own wing as seen from the window (flying toward -X,
 * wing extends outward along -Z), plus winglet and beacon.
 * @param {Record<string, THREE.Material>} materials
 * @returns {{ wing: THREE.Group, beacon: THREE.Mesh, halo: THREE.Mesh }}
 */
function buildWing(materials) {
  const b = new GeoBatch();
  const flat = [-Math.PI / 2, 0, 0]; // outline [x, outward] → XZ plane, outward = -Z

  // Swept, tapered wing surface + darker flap panel along the trailing edge.
  b.add('paper', plate([[-2.6, 0.4], [0.4, 11.5], [1.5, 11.5], [2.5, 0.4]], 0.08), { rotation: flat });
  b.add('seam', plate([[1.95, 0.9], [1.2, 10.6], [1.42, 10.6], [2.3, 0.9]], 0.01), { rotation: flat, position: [0, 0.081, 0] });
  // Winglet: outline [chord, height], stood upright at the tip.
  b.add('trim', plate([[0.7, 0], [1.5, 0], [1.72, 0.5], [1.42, 0.5]], 0.05), { position: [0, 0.04, -11.5] });

  const wing = b.build(materials);
  wing.position.set(0, -1.15, 0);
  wing.rotation.x = 0.035; // slight dihedral — tip rides higher than the root

  const beacon = new THREE.Mesh(new THREE.SphereGeometry(0.07, 12, 8), materials.accent);
  const halo = new THREE.Mesh(new THREE.SphereGeometry(0.24, 16, 12), materials.halo);
  beacon.position.set(1.57, 0.62, -11.5);
  halo.position.copy(beacon.position);
  wing.add(beacon, halo);

  return { wing, beacon, halo };
}

/**
 * Create the cabin + its outside view.
 *
 * @param {{ palette: Record<string, THREE.Color> }} ctx
 * @returns {{
 *   object: THREE.Group,
 *   update: (elapsed: number, delta: number, state: import('../choreography.js').ChoreographyState) => void,
 * }}
 */
export function createPlaneWindow({ palette }) {
  const materials = {
    wall: new THREE.MeshPhysicalMaterial({ color: palette.ground, roughness: 0.62 }),
    trim: new THREE.MeshPhysicalMaterial({ color: palette.ink, roughness: 0.4, clearcoat: 1, clearcoatRoughness: 0.2 }),
    seam: new THREE.MeshStandardMaterial({ color: palette.stone, roughness: 0.6 }),
    paper: new THREE.MeshPhysicalMaterial({ color: palette.paper, roughness: 0.45, clearcoat: 0.6, clearcoatRoughness: 0.3 }),
    accent: new THREE.MeshBasicMaterial({ color: palette.accent }),
    halo: new THREE.MeshBasicMaterial({
      color: palette.accent, transparent: true, opacity: 0.3, depthWrite: false, blending: THREE.AdditiveBlending,
    }),
  };
  const interiorMaterials = [materials.wall, materials.trim, materials.seam];
  // The shade's coral tab must fade with the wall, so it gets its own instance.
  const tabMaterial = materials.accent.clone();
  interiorMaterials.push(tabMaterial);

  const root = new THREE.Group();
  root.position.fromArray(CABIN.position);

  const interior = buildInterior({ ...materials, accent: tabMaterial });
  root.add(interior);

  // Emergency-exit placard: rides (and fades) with the interior.
  const placard = createPlacard(palette);
  interior.add(placard.mesh);

  // ── Exterior: wing, distant airliner, near clouds ──────────────────────
  const exterior = new THREE.Group();
  root.add(exterior);

  // Exterior parts get their OWN ink/seam materials: the interior ones fade
  // out with the cabin, and the wing + airliner must stay solid.
  const outerInk = materials.trim.clone();
  const outerSeam = materials.seam.clone();
  const { wing, beacon, halo } = buildWing({ ...materials, trim: outerInk, seam: outerSeam });
  exterior.add(wing);

  const airliner = buildPlaneModel({ paper: materials.paper, ink: outerInk });
  airliner.scale.setScalar(1.3);
  exterior.add(airliner);

  const rand = seededRandom(21);
  const cloudMaterial = createCloudMaterial(palette);
  const cloudGeometry = buildCloudGeometry(rand);
  const clouds = [[4.5, -2.6, -20, 1.5], [9, 0.6, -27, 2.0], [2.5, 3.4, -24, 1.2], [7.5, -4.2, -33, 2.4], [13, 3.2, -36, 2.2]].map(
    ([x, y, z, scale]) => {
      const mesh = new THREE.Mesh(cloudGeometry, cloudMaterial);
      mesh.position.set(x, y, z);
      mesh.scale.setScalar(scale);
      exterior.add(mesh);
      return { mesh, baseY: y, speed: 0.25 + rand() * 0.3, phase: rand() * 6 };
    },
  );

  /**
   * Per-frame update.
   *   • interior: opacity + scale from the choreography (Stage 2 fade-out)
   *   • wing: banks (rolls + drops) off-screen with `state.wingBank`
   *   • beacon: 1.2 s strobe pulse · airliner: slow banked drift · clouds: slip past
   *
   * @param {number} elapsed
   * @param {number} delta
   * @param {import('../choreography.js').ChoreographyState} state
   */
  function update(elapsed, delta, state) {
    // Whole cabin is behind the camera (and irrelevant) once the hero is reached.
    root.visible = state.flight < 0.999;
    if (!root.visible) return;

    const opacity = state.cabinOpacity;
    interior.visible = opacity > 0.002;
    interior.scale.setScalar(state.cabinScale);
    for (const material of interiorMaterials) {
      material.transparent = opacity < 1;
      material.opacity = opacity;
    }
    placard.material.opacity = opacity;
    placard.material.alphaTest = 0.5 * opacity; // keep the card visible while fading

    const bank = state.wingBank;
    wing.position.set(bank * 3.5, -1.15 - bank * 6, 0);
    wing.rotation.z = bank * 0.55;

    const pulse = Math.pow(Math.max(0, Math.sin(elapsed * 5.2)), 6); // sharp strobe
    beacon.scale.setScalar(0.8 + pulse * 0.6);
    halo.scale.setScalar(0.6 + pulse * 1.2);
    materials.halo.opacity = 0.12 + pulse * 0.4;

    // Distant airliner: flying our way (-X), holding a gentle banked turn.
    airliner.position.set(5.4 + Math.sin(elapsed * 0.22) * 0.9, 2.7 + Math.sin(elapsed * 0.35) * 0.25, -30);
    airliner.rotation.set(0, -Math.PI / 2 - 0.3, 0);
    airliner.rotateZ(0.5 + Math.sin(elapsed * 0.3) * 0.08);

    for (const cloud of clouds) {
      cloud.mesh.position.x += cloud.speed * delta;
      if (cloud.mesh.position.x > 16) cloud.mesh.position.x = -3;
      cloud.mesh.position.y = cloud.baseY + Math.sin(elapsed * 0.3 + cloud.phase) * 0.12;
    }
  }

  return { object: root, update };
}
