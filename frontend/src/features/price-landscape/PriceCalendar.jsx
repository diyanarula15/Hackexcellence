/**
 * price-landscape/PriceCalendar.jsx — the month grid (Monday first) with arrow-key navigation.
 *
 * Roving tabindex: one tile is tabbable; arrows move by a day/week, Home/End to the week's ends,
 * PageUp/PageDown change month, Enter/Space select (handled by the button itself).
 */

import { useCallback, useEffect, useMemo, useRef } from 'react';
import { WEEKDAY_SHORT, addDays, monthGrid, monthKeyOf, weekdayIndex } from './dateUtils.js';
import { normalizedLevel, provenRange, tileState } from './landscapeModel.js';
import PriceTerrain from './PriceTerrain.jsx';
import PriceTile from './PriceTile.jsx';

/**
 * @param {{ monthKey: string, fetchState: { status: string, response: object | null },
 *   window: object | null, selected: string | null, referenceDate: string | null,
 *   bestDate: string | null, focusDate: string | null, onFocusDate: (iso: string) => void,
 *   onSelect: (iso: string) => void, onMonthStep: (step: number, focus?: string) => void,
 *   tripLine: string }} props
 */
export default function PriceCalendar({ monthKey, fetchState, window, selected, referenceDate, bestDate,
  focusDate, onFocusDate, onSelect, onMonthStep, tripLine }) {
  const gridRef = useRef(null);
  const weeks = useMemo(() => monthGrid(monthKey), [monthKey]);
  const response = fetchState.status === 'ready' ? fetchState.response : null;
  const cellsByDate = useMemo(
    () => (response ? new Map(response.dates.map((c) => [c.date, c])) : null), [response]);
  const range = useMemo(() => provenRange(response?.dates), [response]);
  const flags = { loading: fetchState.status === 'loading', failed: fetchState.status === 'error' };
  const outsideOnly = fetchState.status === 'outside';

  const days = weeks.flat().filter(Boolean);
  const tabbable = days.includes(focusDate) ? focusDate : (days.includes(selected) ? selected : days[0]);

  const moveFocus = useCallback((iso) => {
    if (monthKeyOf(iso) !== monthKey) {
      onMonthStep(iso > monthKey ? 1 : -1, iso);
      return;
    }
    onFocusDate(iso);
  }, [monthKey, onFocusDate, onMonthStep]);

  // keep DOM focus on the roving tile after keyboard moves
  useEffect(() => {
    const el = gridRef.current?.querySelector(`[data-date="${focusDate}"]`);
    if (el && gridRef.current.contains(document.activeElement) && document.activeElement !== el) el.focus();
  }, [focusDate, monthKey]);

  const onKeyDown = useCallback((e, iso) => {
    const step = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[e.key];
    if (step) {
      e.preventDefault();
      moveFocus(addDays(iso, step));
    } else if (e.key === 'Home') {
      e.preventDefault();
      moveFocus(addDays(iso, -weekdayIndex(iso)));
    } else if (e.key === 'End') {
      e.preventDefault();
      moveFocus(addDays(iso, 6 - weekdayIndex(iso)));
    } else if (e.key === 'PageUp' || e.key === 'PageDown') {
      e.preventDefault();
      onMonthStep(e.key === 'PageUp' ? -1 : 1);
    }
  }, [moveFocus, onMonthStep]);

  return (
    <div className="pl-calendar" ref={gridRef}>
      <div className="pl-weekdays" aria-hidden="true">
        {WEEKDAY_SHORT.map((d) => <span key={d}>{d}</span>)}
      </div>
      <PriceTerrain settling={Boolean(response)} monthKey={monthKey}>
        <div className="pl-grid" role="group" aria-label="Start dates and their minimum holiday prices">
          {weeks.map((week, w) => week.map((iso, i) => {
            if (!iso) return <span key={`pad-${w}-${i}`} className="pl-pad" aria-hidden="true" />;
            const state = outsideOnly ? 'OUTSIDE_WINDOW' : tileState(iso, cellsByDate, window, flags);
            const cell = cellsByDate?.get(iso) ?? null;
            return (
              <PriceTile
                key={iso}
                iso={iso}
                state={state}
                cell={cell}
                level={normalizedLevel(cell, range)}
                selected={iso === selected}
                isReference={iso === referenceDate}
                isBest={iso === bestDate}
                tabIndex={iso === tabbable ? 0 : -1}
                tripLine={tripLine}
                onSelect={onSelect}
                onKeyDown={onKeyDown}
              />
            );
          }))}
        </div>
      </PriceTerrain>
    </div>
  );
}
