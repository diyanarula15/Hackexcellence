
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
