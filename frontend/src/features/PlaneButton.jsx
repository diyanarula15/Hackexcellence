/**
 * features/PlaneButton.jsx - the subtle "box" action button with a small plane on the right.
 * Used for the primary "Plan trip" submit and for "Export JSON".
 *
 *   hover  → the plane nudges 4px right; plane and border tint to the accent (pure CSS)
 *   click  → a copy of the plane detaches and swishes horizontally to the right with a fading
 *            accent contrail, while the label morphs to `busyLabel`; the button's own plane then
 *            settles back into place
 *
 * The flying plane is portalled to <body> so no scroll container can clip it.
 */

import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

/** Length of the swish (keep equal to `swish-life` in features.css). */
const SWISH_MS = 750;

/** Minimal airliner silhouette, nose pointing right. */
function PlaneIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M22 12c0 .8-1.2 1.4-2.6 1.4h-4.8l-4.2 6.6H8.2l2-6.6h-4l-1.7 2.2H3l.9-3.6L3 8.4h1.5l1.7 2.2h4l-2-6.6h2.2l4.2 6.6h4.8c1.4 0 2.6.6 2.6 1.4z" />
    </svg>
  );
}

/**
 * @param {{
 *   label: string,
 *   busyLabel: string,
 *   busy?: boolean,
 *   disabled?: boolean,
 *   type?: 'button' | 'submit',
 *   className?: string,
 *   onClick?: (event: React.MouseEvent) => void,
 * }} props
 *   busy - the action is in flight (the button is disabled and shows `busyLabel`).
 * @returns {JSX.Element}
 */
export default function PlaneButton({ label, busyLabel, busy = false, disabled = false, type = 'button', className = '', onClick }) {
  const iconRef = useRef(null);
  const timer = useRef(0);
  const [swish, setSwish] = useState(null); // { key, x, y } - where the flying plane starts
  const flying = swish !== null;
  const showBusy = busy || flying;

  useEffect(() => () => clearTimeout(timer.current), []);

  function handleClick(event) {
    if (showBusy || disabled) return;
    onClick?.(event);
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const rect = iconRef.current.getBoundingClientRect();
    setSwish({ key: Date.now(), x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 });
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setSwish(null), SWISH_MS);
  }

  return (
    <>
      <button
        type={type}
        className={`box-btn${flying ? ' box-btn--flying' : ''} ${className}`}
        disabled={busy || disabled}
        onClick={handleClick}
      >
        <span className="box-btn__labels">
          <span className={`box-btn__label${showBusy ? '' : ' box-btn__label--on'}`} aria-hidden={showBusy}>
            <span>{label}</span>
          </span>
          <span className={`box-btn__label${showBusy ? ' box-btn__label--on' : ''}`} aria-hidden={!showBusy}>
            <span>{busyLabel}</span>
          </span>
        </span>
        <span className="box-btn__icon" ref={iconRef}>
          <PlaneIcon className="box-btn__plane" />
        </span>
      </button>

      {swish &&
        createPortal(
          <span key={swish.key} className="swish" style={{ left: swish.x, top: swish.y }} aria-hidden="true">
            <span className="swish__contrail" />
            <PlaneIcon className="swish__plane" />
          </span>,
          document.body,
        )}
    </>
  );
}
