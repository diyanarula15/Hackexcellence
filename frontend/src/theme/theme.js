/**
 * theme.js — bridge between the CSS design tokens and JavaScript / WebGL.
 *
 * `tokens.css` is the single source of truth. This module only *reads* the
 * three brand colours from the document so that Three.js materials stay in
 * lock-step with the stylesheet. Do not hard-code hex values anywhere else.
 */

import * as THREE from 'three';

/**
 * Read a CSS custom property from `:root`.
 * @param {string} name  Custom property name, e.g. `--color-accent`.
 * @returns {string} Trimmed value (e.g. `#FF5A36`).
 */
function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/**
 * Read the three 60/30/10 brand colours from `tokens.css`.
 * Call after the stylesheet is loaded (it is imported first in `main.jsx`).
 * @returns {{ canvas: string, ink: string, accent: string }}
 */
export function readTheme() {
  return {
    canvas: cssVar('--color-canvas'),
    ink: cssVar('--color-ink'),
    accent: cssVar('--color-accent'),
  };
}

/**
 * Expand the three brand colours into the tints the 3D scene needs.
 * Every entry is a mix of canvas/ink (plus the pure accent) — the scene
 * therefore obeys the same 60-30-10 rule as the HUD.
 *
 * @param {{ canvas: string, ink: string, accent: string }} theme
 * @returns {Record<string, THREE.Color>}
 */
export function buildScenePalette(theme) {
  const canvas = new THREE.Color(theme.canvas);
  const ink = new THREE.Color(theme.ink);
  const accent = new THREE.Color(theme.accent);
  /** Mix canvas → ink by `t` (0 = canvas, 1 = ink). */
  const tint = (t) => canvas.clone().lerp(ink, t);

  return {
    canvas,
    ink,
    accent,
    paper: tint(0.02), // building bodies, plane fuselage, clouds
    ground: tint(0.1), // island top surface
    stone: tint(0.3), // paths, pool deck, mid-tone details
    shade: tint(0.1), // hemisphere ground bounce (keeps undersides airy)
    rockLit: tint(0.56), // brightest facet of the ink rock (shadow side = pure ink)
    foliage: tint(0.94), // tree shadow side — near-ink for crisp silhouettes
    foliageLit: tint(0.6), // tree lit side
    cloudShade: tint(0.09), // darkest cloud tone — barely off the canvas
    white: new THREE.Color(0xffffff), // neutral highlight (clouds), not a brand hue
  };
}
