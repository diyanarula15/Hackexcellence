/**
 * hud/NavBar.jsx — frameless top navigation.
 *
 * Brand placeholder (left) + three placeholder links (right). No background,
 * border or shadow: it floats directly over the 3D scene. A tiny accent dot
 * glides beneath whichever link is hovered or focused.
 */

import { useState } from 'react';
import Slot from './Slot.jsx';

/** The app's real navigation lives in the actions slot (features/NavActions.jsx); no placeholder links. */
const NAV_LINKS = [];

/**
 * Placeholder logo mark: ink orbit + accent dot. Swap for the real SVG.
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
 *   actions — optional widgets (sign-in button, currency picker…) mounted in
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
      {/* Brand logo placeholder */}
      <a className="nav__brand" href="/" aria-label="Wanderline — home">
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

        {/* [HACKATHON_NAV_ACTIONS_SLOT] — sign-in / profile / currency */}
        <Slot name="HACKATHON_NAV_ACTIONS_SLOT" className="slot--nav-actions">
          {actions}
        </Slot>
      </div>
    </header>
  );
}
