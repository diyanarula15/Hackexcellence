/**
 * hud/GridOverlay.jsx - developer aid: Rule-of-Thirds + slot outlines.
 *
 * Press "G" (or open the page with `?grid`) to toggle. Shows the 3×3
 * compositional grid and outlines every injection slot so new widgets can be
 * placed without breaking the layout. Ships in production but is inert
 * until toggled; delete the <GridOverlay /> line in Hud.jsx to remove it.
 */

import { useEffect, useState } from 'react';

/**
 * @returns {JSX.Element | null} Thirds overlay, or null when hidden.
 */
export default function GridOverlay() {
  const [visible, setVisible] = useState(() => new URLSearchParams(window.location.search).has('grid'));

  useEffect(() => {
    /** @param {KeyboardEvent} event */
    const onKeyDown = (event) => {
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName) || event.target.isContentEditable;
      if (!typing && event.key.toLowerCase() === 'g' && !event.metaKey && !event.ctrlKey) {
        setVisible((value) => !value);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  // Slot outlines are driven by this attribute (see hud.css).
  useEffect(() => {
    document.documentElement.toggleAttribute('data-debug-grid', visible);
  }, [visible]);

  return visible ? <div className="grid-overlay" aria-hidden="true" /> : null;
}
