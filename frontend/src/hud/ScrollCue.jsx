/**
 * hud/ScrollCue.jsx - the only Stage-1 HUD element besides the nav.
 *
 * A subtle, unboxed "Scroll to take off" prompt near the bottom-left, with a
 * "Skip to planner" button: the nav (and its "Plan holiday") is hidden during
 * the intro, so this is the way straight to the form. It is visible only while
 * `<html data-stage="cabin">` and fades out as soon as the flight begins
 * (see `.cue` in hud.css).
 */

import { scrollToPlanner } from '../features/format.js';

/** @returns {JSX.Element} */
export default function ScrollCue() {
  return (
    <div className="cue">
      <span className="cue__line" aria-hidden="true" />
      <span aria-hidden="true">Scroll to take off</span>
      <button type="button" className="cue__skip" onClick={scrollToPlanner}>
        Skip to planner →
      </button>
    </div>
  );
}
