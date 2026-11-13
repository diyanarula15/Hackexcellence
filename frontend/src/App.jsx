/**
 * App.jsx — composition root: 3D scene (back) + 2D HUD (front).
 *
 * Layers
 *   z 0  <SceneCanvas />  fixed full-viewport WebGL scene   (src/scene)
 *   z 1  <Hud />          nav, hero, injection slots        (src/hud)
 *
 * ── HACKATHON: MOUNT WIDGETS HERE ────────────────────────────────────────
 * Import your component and pass it to the matching slot prop. Example:
 *
 *   import PreferencesPanel from './features/PreferencesPanel.jsx';
 *   import PackageModifier from './features/PackageModifier.jsx';
 *
 *   <Hud preferences={<PreferencesPanel />} packageModifier={<PackageModifier />} />
 *
 * State + API calls: src/state/bookingStore.js → src/services/travelApi.js
 * ─────────────────────────────────────────────────────────────────────────
 */

import SceneCanvas from './scene/SceneCanvas.jsx';
import Hud from './hud/Hud.jsx';

/** @returns {JSX.Element} */
export default function App() {
  return (
    <>
      <SceneCanvas />
      <Hud
        preferences={null /* [HACKATHON_PREFERENCES_BUDGET_SLOT] */}
        packageModifier={null /* [HACKATHON_PACKAGE_MODIFIER_SLOT] */}
        navActions={null /* [HACKATHON_NAV_ACTIONS_SLOT] */}
      />
    </>
  );
}
