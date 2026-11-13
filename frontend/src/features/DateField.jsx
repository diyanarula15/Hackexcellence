/**
 * features/DateField.jsx - the "First day" control: a field-styled trigger that opens a small
 * calendar popover, so a date is picked with one click instead of typed.
 *
 * The value is an ISO date string ("2027-03-14") or "". Days outside [min, max] are disabled.
 * The popover is portalled to <body> and placed above or below the trigger - whichever has room -
 * and kept inside the viewport. Escape, an outside click or scrolling closes it.
 */

import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const WEEKDAYS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'];
const MARGIN = 12; // minimum gap to the viewport edge
const GAP = 8; // gap between trigger and popover

const pad = (n) => String(n).padStart(2, '0');
const toIso = (year, month, day) => `${year}-${pad(month + 1)}-${pad(day)}`;
/** "2027-03-14" → { year: 2027, month: 2, day: 14 } (month is 0-based), or null. */
function parseIso(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value ?? '');
  return match ? { year: Number(match[1]), month: Number(match[2]) - 1, day: Number(match[3]) } : null;
}
function todayIso() {
  const now = new Date();
  return toIso(now.getFullYear(), now.getMonth(), now.getDate());
}
/** "2027-03-14" → "14 Mar 2027" */
function formatDate(value) {
  const date = parseIso(value);
  return date ? `${date.day} ${MONTHS[date.month].slice(0, 3)} ${date.year}` : '';
}

function CalendarIcon() {
  return (
    <svg className="date-field__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <rect x="3.5" y="5" width="17" height="15.5" rx="2.5" />
      <path d="M3.5 10h17M8 3v4M16 3v4" strokeLinecap="round" />
    </svg>
  );
}

/**
 * @param {{
 *   value: string, onChange: (value: string) => void, min?: string, max?: string,
 *   id: string, name: string, className: string,
 *   'aria-invalid'?: boolean, 'aria-describedby'?: string,
 * }} props
 * @returns {JSX.Element}
 */
export default function DateField({ value, onChange, min, max, id, name, className, ...aria }) {
  const triggerRef = useRef(null);
  const popoverRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [view, setView] = useState({ year: 0, month: 0 }); // month on show
  const [place, setPlace] = useState(null); // { left, top } once measured

  const today = todayIso();
  const monthStart = toIso(view.year, view.month, 1).slice(0, 7);
  const canGoBack = !min || monthStart > min.slice(0, 7);
  const canGoForward = !max || monthStart < max.slice(0, 7);

  /** The month to show first: the chosen date's, else today's pulled into [min, max]. */
  function startMonth() {
    let iso = value || today;
    if (!value && min && iso < min) iso = min;
    if (!value && max && iso > max) iso = max;
    const { year, month } = parseIso(iso) ?? parseIso(today);
    return { year, month };
  }

  function toggle() {
    if (open) return setOpen(false);
    setView(startMonth());
    setPlace(null);
    setOpen(true);
  }

  // The allowed window can arrive (from /api/meta) after the popover opened: re-aim it.
  useEffect(() => {
    if (open && !value) setView(startMonth());
  }, [min, max]); // eslint-disable-line react-hooks/exhaustive-deps

  function step(delta) {
    setView(({ year, month }) => {
      const next = year * 12 + month + delta;
      return { year: Math.floor(next / 12), month: next % 12 };
    });
  }

  function pick(iso) {
    onChange(iso);
    setOpen(false);
    triggerRef.current.focus();
  }

  // Place the popover: below the trigger if it fits, otherwise above; clamp into the viewport.
  useLayoutEffect(() => {
    if (!open) return;
    // Anchor to the whole field (label + control) so the label stays readable.
    const trigger = (triggerRef.current.closest('.field') ?? triggerRef.current).getBoundingClientRect();
    const card = popoverRef.current.getBoundingClientRect();
    const below = window.innerHeight - trigger.bottom - GAP - MARGIN;
    const above = trigger.top - GAP - MARGIN;
    const top = card.height <= below || below >= above ? trigger.bottom + GAP : trigger.top - GAP - card.height;
    setPlace({
      left: Math.max(MARGIN, Math.min(trigger.left, window.innerWidth - card.width - MARGIN)),
      top: Math.max(MARGIN, Math.min(top, window.innerHeight - card.height - MARGIN)),
    });
  }, [open, view]);

  useEffect(() => {
    if (!open) return undefined;
    const close = () => setOpen(false);
    const onPointerDown = (event) => {
      if (!popoverRef.current?.contains(event.target) && !triggerRef.current?.contains(event.target)) close();
    };
    const onKeyDown = (event) => {
      if (event.key !== 'Escape') return;
      close();
      triggerRef.current?.focus();
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    window.addEventListener('scroll', close, { passive: true });
    window.addEventListener('resize', close);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('scroll', close);
      window.removeEventListener('resize', close);
    };
  }, [open]);

  // Leading blanks (weeks start on Monday) + the days of the month.
  const lead = (new Date(view.year, view.month, 1).getDay() + 6) % 7;
  const dayCount = new Date(view.year, view.month + 1, 0).getDate();
  const cells = [...Array(lead).fill(null), ...Array.from({ length: dayCount }, (_, i) => i + 1)];

  return (
    <>
      <button
        {...aria}
        ref={triggerRef}
        type="button"
        id={id}
        name={name}
        className={`${className} date-field${value ? '' : ' date-field--empty'}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={toggle}
      >
        <span>{formatDate(value) || 'Select date'}</span>
        <CalendarIcon />
      </button>

      {open &&
        createPortal(
          <div
            ref={popoverRef}
            className="calendar"
            role="dialog"
            aria-label="Choose the first day"
            style={place ? { left: place.left, top: place.top } : { left: 0, top: 0, visibility: 'hidden' }}
          >
            <div className="calendar__head">
              <button type="button" className="calendar__nav" onClick={() => step(-1)} disabled={!canGoBack} aria-label="Previous month">
                &lt;
              </button>
              <p className="calendar__title" aria-live="polite">
                {MONTHS[view.month]} {view.year}
              </p>
              <button type="button" className="calendar__nav" onClick={() => step(1)} disabled={!canGoForward} aria-label="Next month">
                &gt;
              </button>
            </div>
            <div className="calendar__grid">
              {WEEKDAYS.map((day) => (
                <span key={day} className="calendar__weekday" aria-hidden="true">
                  {day}
                </span>
              ))}
              {cells.map((day, index) => {
                if (day === null) return <span key={`blank-${index}`} />;
                const iso = toIso(view.year, view.month, day);
                const selected = iso === value;
                return (
                  <button
                    key={iso}
                    type="button"
                    className={`calendar__day${selected ? ' calendar__day--selected' : ''}${iso === today ? ' calendar__day--today' : ''}`}
                    disabled={(min && iso < min) || (max && iso > max)}
                    aria-pressed={selected}
                    aria-label={`${day} ${MONTHS[view.month]} ${view.year}${iso === today ? ' (today)' : ''}`}
                    onClick={() => pick(iso)}
                  >
                    {day}
                  </button>
                );
              })}
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}
