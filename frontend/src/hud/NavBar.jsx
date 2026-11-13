/**
 * hud/NavBar.jsx - frameless top navigation.
 *
 * Wanderline brand mark + wordmark (left); on the right an optional link list
 * (NAV_LINKS, currently empty) and the actions slot, which holds
 * features/NavActions.jsx. No background, border or shadow: it floats directly
 * over the 3D scene. A tiny accent dot glides beneath whichever link is hovered
 * or focused; keyboard focus also shows the standard 2px accent outline.
 */

import { useState } from 'react';
import Slot from './Slot.jsx';

/** The app's real navigation lives in the actions slot (features/NavActions.jsx); this list is empty. */
const NAV_LINKS = [];

/**
 * Wanderline logo mark: ink orbit + accent dot (also the favicon in index.html).
 * Colours come from the theme tokens, so it re-skins automatically.
 * @returns {JSX.Element}
 */
function BrandMark() {
  return (
    <svg className="nav__mark" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="9" stroke="var(--color-ink)" strokeWidth="2.5" />
      <circle cx="18.5" cy="5.5" r="3.5" fill="var(--color-accent)" stroke="var(--color-canvas)" strokeWidth="1.5" />
    </svg>
  );
}

/**
 * Top navigation bar.
 * @param {{ actions?: React.ReactNode }} props
 *   actions - widgets (saved trips, booking lookup, "Plan holiday" button) mounted in
 *   the [HACKATHON_NAV_ACTIONS_SLOT] to the right of the links.
 * @returns {JSX.Element}
 */
export default function NavBar({ actions }) {
  // x = centre of the active link (px from the list's left edge); `glide` is
  // false on first entry so the dot fades in under the link instead of sliding in.
  const [dot, setDot] = useState({ x: 0, on: false, glide: false });
  const moveDot = (event) => {
    const link = event.currentTarget;
    setDot((prev) => ({ x: link.offsetLeft + link.offsetWidth / 2, on: true, glide: prev.on }));
  };
  const hideDot = () => setDot((prev) => ({ ...prev, on: false }));

  return (
    <header className="nav">
      {/* Brand */}
      <a className="nav__brand" href="/" aria-label="Wanderline - home">
        <BrandMark />
        <span className="nav__wordmark">Wanderline</span>
      </a>

      <div className="nav__right">
        {NAV_LINKS.length > 0 && <nav aria-label="Primary">
          <ul className="nav__links" onPointerLeave={hideDot} onBlur={hideDot}>
            {NAV_LINKS.map((link) => (
              <li key={link.label}>
                <a className="nav__link" href={link.href} onPointerEnter={moveDot} onFocus={moveDot}>
                  {link.label}
                </a>
              </li>
            ))}
            <li
              className={`nav__dot${dot.on ? ' nav__dot--on' : ''}${dot.glide ? ' nav__dot--glide' : ''}`}
              style={{ '--dot-x': `${dot.x}px` }}
              aria-hidden="true"
            />
          </ul>
        </nav>}

        {/* [HACKATHON_NAV_ACTIONS_SLOT] - saved trips / find booking / plan */}
        <Slot name="HACKATHON_NAV_ACTIONS_SLOT" className="slot--nav-actions">
          {actions}
        </Slot>
      </div>
    </header>
  );
}
