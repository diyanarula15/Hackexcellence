/**
 * hud/ScrollCue.jsx — the only Stage-1 HUD element besides the nav.
 *
 * A subtle, unboxed "Scroll to take off" prompt near the bottom-left. It is
 * visible only while `<html data-stage="cabin">` and fades out as soon as
 * the flight begins (see `.cue` in hud.css).
 */

/** @returns {JSX.Element} */
export default function ScrollCue() {
  return (
    <p className="cue" aria-hidden="true">
      <span className="cue__line" />
      Scroll to take off
    </p>
  );
}
