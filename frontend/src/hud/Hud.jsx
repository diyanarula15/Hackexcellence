/**
 * hud/Hud.jsx — the 2D interface layer, laid out on the 3×3 thirds grid.
 *
 * Structure
 *   <div.scroll-track>   tall element (280vh) that provides the scroll
 *     <main.hud>         distance; the HUD inside is sticky, so it stays
 *   </div>               pinned for the whole 3D opening sequence.
 *   <Slot modifier>      normal page flow resumes right below the track.
 *
 * This is THE file to open when adding UI. Each hackathon widget has a
 * pre-positioned slot; pass your component through the matching prop from
 * `App.jsx` (or render it directly inside the <Slot> below).
 *
 *   preferences     → [HACKATHON_PREFERENCES_BUDGET_SLOT]  lower third of Stage 3, cols 1–3
 *   packageModifier → [HACKATHON_PACKAGE_MODIFIER_SLOT]    immediately below the scroll canvas
 *   navActions      → [HACKATHON_NAV_ACTIONS_SLOT]         right end of the nav bar
 *
 * See hud.css for the grid map and the stage-driven visibility rules.
 */

import NavBar from './NavBar.jsx';
import Hero from './Hero.jsx';
import ScrollCue from './ScrollCue.jsx';
import Slot from './Slot.jsx';
import GridOverlay from './GridOverlay.jsx';
import './hud.css';

/**
 * @param {{
 *   preferences?: React.ReactNode,
 *   packageModifier?: React.ReactNode,
 *   navActions?: React.ReactNode,
 * }} props
 * @returns {JSX.Element}
 */
export default function Hud({ preferences, packageModifier, navActions }) {
  return (
    <>
      {/* `data-scroll-track` is what scene/choreography.js measures. */}
      <div className="scroll-track" data-scroll-track>
        <main className="hud">
          <NavBar actions={navActions} />
          <Hero />
          <ScrollCue />

          {/* [HACKATHON_PREFERENCES_BUDGET_SLOT] ─ lower third, full width.
              Shown only in Stage 3 (hero). Mount the traveller-preference
              and budget inputs here. */}
          <Slot name="HACKATHON_PREFERENCES_BUDGET_SLOT" className="slot--preferences">
            {preferences}
          </Slot>
        </main>
      </div>

      {/* [HACKATHON_PACKAGE_MODIFIER_SLOT] ─ immediately below the scroll canvas.
          Mount the itinerary / package modification UI here. Children flow
          into a 3-column grid aligned with the thirds; the section
          collapses to nothing while empty. */}
      <Slot name="HACKATHON_PACKAGE_MODIFIER_SLOT" className="slot--modifier">
        {packageModifier}
      </Slot>

      <GridOverlay />
    </>
  );
}
