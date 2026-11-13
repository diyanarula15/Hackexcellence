/**
 * price-landscape/PriceLandscape.jsx — "Explore flexible dates": a calendar of PROVEN cheapest
 * complete-holiday prices per start date (Phase 7A, POST /api/date-prices), drawn as a gentle
 * price terrain, with a comparison against the traveler's original date and a way to generate a
 * new holiday for a chosen date.
 *
 * Nothing here computes a holiday price. Tiles show only what the backend proved; incomplete or
 * impossible dates show no price. Choosing a date never changes a saved package — it starts a new
 * generation through `onGenerate` (the normal package flow).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { getDatePrices } from '../../services/datePricesApi.js';
import { addMonths, formatLongDate, formatMonth, MONTH_NAMES, monthKeyOf, monthsBetween, parseIso } from './dateUtils.js';
import { bestDateNote, formatINR, isProven, isSelectable, nearestProvenDate, provenRange, viewState } from './landscapeModel.js';
import { useMonthPrices, useReferenceCell } from './useMonthPrices.js';
import PriceCalendar from './PriceCalendar.jsx';
import PriceComparison from './PriceComparison.jsx';
import PriceLegend from './PriceLegend.jsx';
import './PriceLandscape.css';

/**
 * True when generation sends `objective: "MINIMUM_COST"` to POST /api/packages, so the new holiday
 * is the proven cheapest one for that date and its total equals the price shown here. Requires the
 * backend's objective support (routes/packages.py) and bookingStore.generatePackage({ objective }).
 */
export const EXACT_MINIMUM_GENERATION = true;

function tripLineOf(trip, countryName) {
  const kids = Array.isArray(trip.child_ages) ? trip.child_ages.length : 0;
  const parts = [`${trip.nights} nights · ${countryName ?? trip.country}`,
    `${trip.adults} ${Number(trip.adults) === 1 ? 'adult' : 'adults'}${kids ? ` · ${kids} ${kids === 1 ? 'child' : 'children'}` : ''}`];
  return parts.join(' — ');
}

/** "2027-04-12" → "12 Apr" */
function shortDayMonth(iso) {
  const d = parseIso(iso);
  return d ? `${d.day} ${MONTH_NAMES[d.month - 1].slice(0, 3)}` : '';
}

function errorMessages(error) {
  const fieldErrors = error?.body?.field_errors;
  if (fieldErrors) return [...new Set(Object.values(fieldErrors).flat())];
  return [error?.message ?? 'Prices could not be loaded.'];
}

/**
 * @param {{ trip: object, window: { first_night: string, last_departure: string } | null,
 *   countryName?: string, onClose: () => void, onSelectDate?: (iso: string) => void,
 *   onGenerate?: (iso: string) => Promise<void>, fetcher?: typeof getDatePrices,
 *   exactGeneration?: boolean }} props
 */
export default function PriceLandscape({ trip, window: travelWindow, countryName, onClose, onSelectDate,
  onGenerate, fetcher = getDatePrices, exactGeneration = EXACT_MINIMUM_GENERATION }) {
  const referenceDate = parseIso(trip.start_date) ? trip.start_date : null;
  const months = useMemo(
    () => (travelWindow ? monthsBetween(travelWindow.first_night, travelWindow.last_departure) : []),
    [travelWindow]);
  const [monthKey, setMonthKey] = useState(
    () => (referenceDate ? monthKeyOf(referenceDate) : months[0] ?? monthKeyOf(new Date().toISOString())));
  const [selected, setSelected] = useState(referenceDate);
  const [focusDate, setFocusDate] = useState(referenceDate);
  const [inspected, setInspected] = useState(null);   // an INFEASIBLE date the user asked about
  const [generating, setGenerating] = useState({ status: 'idle', error: null });
  const headingRef = useRef(null);

  const month = useMonthPrices(trip, monthKey, travelWindow, fetcher);
  const response = month.status === 'ready' ? month.response : null;
  const reference = useReferenceCell(trip, referenceDate, monthKey, month, fetcher);
  const view = month.status === 'outside' ? 'EMPTY' : viewState(month);
  const range = provenRange(response?.dates);
  const note = bestDateNote(response, reference.cell);
  const tripLine = tripLineOf(trip, countryName);

  const selectedCell = response?.dates.find((c) => c.date === selected) ?? (selected === referenceDate ? reference.cell : null);
  const canGenerate = Boolean(selected && selectedCell && isSelectable(selectedCell) && onGenerate)
    && generating.status !== 'loading';

  const atFirst = months.length > 0 && monthKey <= months[0];
  const atLast = months.length > 0 && monthKey >= months[months.length - 1];
  const stepMonth = useCallback((step, focusIso) => {
    setMonthKey((k) => {
      const next = addMonths(k, step);
      if (months.length && (next < months[0] || next > months[months.length - 1])) return k;
      if (focusIso) setFocusDate(focusIso);
      return next;
    });
  }, [months]);

  const select = useCallback((iso) => {
    setSelected(iso);
    setFocusDate(iso);
    setInspected(null);
    setGenerating({ status: 'idle', error: null });
    onSelectDate?.(iso);
  }, [onSelectDate]);

  const inspect = useCallback((iso) => {
    setInspected(iso);
    setFocusDate(iso);
  }, []);
  // the note belongs to the month it was asked in; it is not shown on any other month
  const inspectedHere = inspected && monthKeyOf(inspected) === monthKey ? inspected : null;
  const nearest = inspectedHere ? nearestProvenDate(response?.dates, inspectedHere) : null;

  useEffect(() => {
    headingRef.current?.focus();
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    const { overflow } = document.body.style;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = overflow;
    };
  }, [onClose]);

  async function generate() {
    if (!canGenerate) return;
    setGenerating({ status: 'loading', error: null });
    try {
      await onGenerate(selected);
      setGenerating({ status: 'idle', error: null });
    } catch (error) {
      setGenerating({ status: 'error', error: error?.message ?? 'The holiday could not be generated.' });
    }
  }

  return createPortal(
    <div className="pl-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <section className="pl-dialog" role="dialog" aria-modal="true" aria-labelledby="pl-title"
        aria-describedby="pl-subtitle">
        <header className="pl-head">
          <div>
            <p className="eyebrow">Price landscape</p>
            <h2 className="pl-title" id="pl-title" tabIndex={-1} ref={headingRef}>Explore flexible dates</h2>
            <p className="pl-subtitle" id="pl-subtitle">
              The cheapest complete holiday for each start date — flights, hotels, transfers and attractions,
              proven by the planner. {tripLine}.
            </p>
          </div>
          <button type="button" className="btn btn--small pl-close" onClick={onClose}>Close</button>
        </header>

        <div className="pl-body">
          <div className="pl-main">
            <div className="pl-monthbar">
              <button type="button" className="pl-nav" onClick={() => stepMonth(-1)} disabled={atFirst}
                aria-label="Previous month">‹</button>
              <h3 className="pl-month" aria-live="polite">{formatMonth(monthKey)}</h3>
              <button type="button" className="pl-nav" onClick={() => stepMonth(1)} disabled={atLast}
                aria-label="Next month">›</button>
            </div>

            <PriceCalendar
              monthKey={monthKey}
              fetchState={month}
              window={travelWindow}
              selected={selected}
              referenceDate={referenceDate}
              bestDate={note?.date ?? null}
              focusDate={focusDate}
              onFocusDate={setFocusDate}
              onSelect={select}
              onInspect={inspect}
              onMonthStep={stepMonth}
              tripLine={tripLine}
            />

            <div className="pl-status" aria-live="polite">
              {view === 'LOADING' && <p>Proving the cheapest holiday for each date…</p>}
              {view === 'PARTIALLY_EVALUATED' && (
                <p>Some dates could not be verified yet. <button type="button" className="link-button"
                  onClick={month.retry}>Check again</button></p>
              )}
              {view === 'EMPTY' && <p>No start dates in {formatMonth(monthKey)} fit this trip.</p>}
              {view === 'ERROR' && (
                <div className="pl-error" role="alert">
                  {errorMessages(month.error).map((m) => <p key={m}>{m}</p>)}
                  <button type="button" className="btn btn--small" onClick={month.retry}>Retry</button>
                </div>
              )}
            </div>
          </div>

          <aside className="pl-side">
            {note && (
              <div className="pl-best" key={`${monthKey}-${note.date}`}>
                <p className="eyebrow">{note.title}</p>
                <button type="button" className="pl-best__date" onClick={() => select(note.date)}>
                  {formatLongDate(note.date)} · {formatINR(note.total)}
                </button>
                {note.detail && <p className="pl-best__detail">{note.detail}</p>}
              </div>
            )}

            {inspectedHere && (
              <div className="pl-inspect" role="status" aria-live="polite" key={`inspect-${inspectedHere}`}>
                <p>No complete trip starts on {formatLongDate(inspectedHere)}.</p>
                {nearest ? (
                  <>
                    <p>Nearest possible start: {formatLongDate(nearest.date)} · {formatINR(nearest.min_total_inr)}</p>
                    <button type="button" className="btn btn--small" onClick={() => select(nearest.date)}>
                      Show {shortDayMonth(nearest.date)}
                    </button>
                  </>
                ) : (
                  <>
                    <p>No proven trip this month — try the next month.</p>
                    {!atLast && (
                      <button type="button" className="btn btn--small" onClick={() => stepMonth(1)}>
                        Show {formatMonth(addMonths(monthKey, 1))}
                      </button>
                    )}
                  </>
                )}
              </div>
            )}

            <PriceComparison
              reference={{ date: referenceDate, cell: reference.cell, loading: reference.status === 'loading' }}
              selected={{ date: selected, cell: selectedCell }}
            />

            <PriceLegend range={range} />

            <div className="pl-generate">
              <p className="pl-generate__note">
                Creates a new holiday starting {selected ? formatLongDate(selected) : 'on the chosen date'}.
                Your saved holidays are not changed.
                {exactGeneration && isProven(selectedCell) && (
                  <> It is planned at this date's proven minimum, {formatINR(selectedCell.min_total_inr)}.</>
                )}
                {!exactGeneration && isProven(selectedCell) && (
                  <> The planner keeps to your budget rules, so the new package can cost more than the proven
                    minimum shown here.</>
                )}
              </p>
              <button type="button" className="btn btn--primary pl-generate__btn" onClick={generate}
                disabled={!canGenerate} aria-busy={generating.status === 'loading'}>
                {generating.status === 'loading' ? 'Generating…' : 'Generate holiday'}
              </button>
              {generating.status === 'error' && <p className="pl-error" role="alert">{generating.error}</p>}
            </div>
          </aside>
        </div>
      </section>
    </div>,
    document.body,
  );
}
