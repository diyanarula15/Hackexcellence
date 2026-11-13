/**
 * scene/utils/materials.js — "ramp" material for controlled low-poly shading.
 *
 * Problem: a physically-lit surface as dark as the ink colour (#0F172A)
 * reflects almost nothing, so every facet renders as the same flat black.
 *
 * Solution: light the surface as if it were white, then use the resulting
 * brightness to blend between two theme tints (`shadow` → `light`). Each
 * facet gets a distinct tone, shadows/fog still work, and the output never
 * leaves the brand palette.
 */

import * as THREE from 'three';

/**
 * Create a two-tone ramp material driven by real scene lighting.
 *
 * @param {{
 *   shadow: THREE.Color,
 *   light: THREE.Color,
 *   range?: [number, number],
 *   flatShading?: boolean,
 * }} options
 *   shadow / light — colours of the darkest and brightest facets.
 *   range — incoming brightness mapped to shadow (range[0]) … light (range[1]).
 *           Narrow it for more contrast between facets.
 *   flatShading — true for crisp low-poly facets, false for soft forms.
 * @returns {THREE.MeshStandardMaterial}
 */
export function createRampMaterial({ shadow, light, range = [0.4, 1.2], flatShading = true }) {
  const material = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 1, metalness: 0, flatShading });
  const uniforms = {
    uRampShadow: { value: shadow },
    uRampLight: { value: light },
    uRampRange: { value: new THREE.Vector2(range[0], range[1]) },
  };

  material.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, uniforms);
    shader.fragmentShader = shader.fragmentShader
      .replace(
        '#include <common>',
        '#include <common>\nuniform vec3 uRampShadow;\nuniform vec3 uRampLight;\nuniform vec2 uRampRange;',
      )
      .replace(
        '#include <opaque_fragment>',
        `float rampLuma = dot(outgoingLight, vec3(0.2126, 0.7152, 0.0722));
        outgoingLight = mix(uRampShadow, uRampLight, smoothstep(uRampRange.x, uRampRange.y, rampLuma));
        #include <opaque_fragment>`,
      );
  };
  material.customProgramCacheKey = () => 'ramp-material';
  return material;
}
