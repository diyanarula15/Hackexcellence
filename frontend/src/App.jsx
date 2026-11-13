/**
 * App.jsx — composition root: 3D scene (back) + 2D HUD (front).
 *
 * Layers
 *   z 0  <SceneCanvas />  fixed full-viewport WebGL scene   (src/scene)
 *   z 1  <Hud />          nav, hero, injection slots        (src/hud)
 *
 * Widgets in the HUD slots (src/features):
 *   [HACKATHON_PREFERENCES_BUDGET_SLOT]  <RequestForm />   the 7-field trip request
 *   [HACKATHON_PACKAGE_MODIFIER_SLOT]    <PackagePanel />  the package / result below the intro
 *   [HACKATHON_NAV_ACTIONS_SLOT]         <NavActions />    open a saved package, plan a trip
 *
 * State + API calls: src/state/bookingStore.js → src/services/travelApi.js → /api (FastAPI)
 */

import { useEffect } from 'react';
import SceneCanvas from './scene/SceneCanvas.jsx';
import Hud from './hud/Hud.jsx';
import RequestForm from './features/RequestForm.jsx';
import PackagePanel from './features/PackagePanel.jsx';
import NavActions from './features/NavActions.jsx';
import { loadMeta, startUrlSync } from './state/bookingStore.js';
import './features/features.css';

/** @returns {JSX.Element} */
export default function App() {
  useEffect(() => {
    loadMeta(); // departure cities + countries for the form
    return startUrlSync(); // reopen ?package=<id> on load, refresh and back/forward
  }, []);

  return (
    <>
      <SceneCanvas />
      <Hud preferences={<RequestForm />} packageModifier={<PackagePanel />} navActions={<NavActions />} />
    </>
  );
}
