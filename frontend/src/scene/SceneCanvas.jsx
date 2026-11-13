/**
 * scene/SceneCanvas.jsx — React mount point for the 3D scene.
 *
 * Renders a fixed, full-viewport <canvas> BEHIND the HUD and hands it to
 * `createScene`. All 3D logic lives in `createScene.js` + `actors/`; this
 * component only manages lifecycle (mount → start, unmount → dispose).
 */

import { useEffect, useRef, useState } from 'react';
import { createScene } from './createScene.js';
import './scene.css';

/**
 * Full-viewport animated background.
 * Falls back to the plain canvas colour if WebGL is unavailable.
 * @returns {JSX.Element | null}
 */
export default function SceneCanvas() {
  const canvasRef = useRef(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    try {
      const scene = createScene(canvasRef.current, { reducedMotion });
      return () => scene.dispose();
    } catch (error) {
      console.warn('[scene] WebGL unavailable — rendering HUD only.', error);
      document.documentElement.dataset.stage = 'static'; // collapse the scroll track (hud.css)
      setFailed(true);
      return undefined;
    }
  }, []);

  if (failed) return null;
  return <canvas ref={canvasRef} className="scene-canvas" aria-hidden="true" />;
}
