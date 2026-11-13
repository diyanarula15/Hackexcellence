/**
 * price-landscape/PriceTile.jsx — one day of the Price Landscape.
 *
 * Height (--elev) and shade (--level) encode the proven price; the exact amount is always printed
 * as text too, so nothing relies on colour or depth alone. Tiles that cannot be chosen use
 * aria-disabled (not `disabled`) so keyboard users can still move across them and hear why.
 */

import { memo } from 'react';
import { parseIso } from './dateUtils.js';
import { DARK_TEXT_LEVEL, describeTile, elevationFor, formatINR } from './landscapeModel.js';
import { ERROR, FOUND, INFEASIBLE, LOADING, NOT_ELIGIBLE, OUTSIDE_WINDOW, SEARCH_INCOMPLETE } from './types.js';

const SELECTABLE = new Set([FOUND, SEARCH_INCOMPLETE]);

/**
 * @param {{ iso: string, state: import('./types.js').TileState, cell: object | null, level: number | null,
 *   selected: boolean, isReference: boolean, isBest: boolean, tabIndex: number, tripLine: string,
 *   onSelect: (iso: string) => void, onInspect: (iso: string) => void,
 *   onKeyDown: (e: KeyboardEvent, iso: string) => void }} props
 */
function PriceTile({ iso, state, cell, level, selected, isReference, isBest, tabIndex, tripLine, onSelect, onInspect,
  onKeyDown }) {
  const day = parseIso(iso).day;
  const selectable = SELECTABLE.has(state);
  const tipId = `pl-tip-${iso}`;
  const classes = [
    'pl-tile',
    `pl-tile--${state.toLowerCase().replace('_', '-')}`,
    selected && 'is-selected',
    isReference && 'is-reference',
    isBest && 'is-best',
    level !== null && level >= DARK_TEXT_LEVEL && 'is-dark',
  ].filter(Boolean).join(' ');

  let price = null;
  if (state === FOUND) price = formatINR(cell.min_total_inr);
  else if (state === INFEASIBLE) price = 'No trip';
  else if (state === SEARCH_INCOMPLETE) price = '—';

  return (
    <button
      type="button"
      className={classes}
      data-date={iso}
      data-state={state}
      style={{ '--elev': elevationFor(level), '--level': level ?? 0 }}
      tabIndex={tabIndex}
      aria-pressed={selectable ? selected : undefined}
      aria-disabled={!selectable}
      aria-label={`${describeTile(iso, state, cell)}${isReference ? ' (your original date)' : ''}`}
      aria-describedby={tipId}
      onClick={() => {
        if (selectable) onSelect(iso);
        else if (state === INFEASIBLE) onInspect(iso);   // "no trip" tiles explain themselves, never select
      }}
      onKeyDown={(e) => onKeyDown(e, iso)}
    >
      <span className="pl-tile__face">
        <span className="pl-tile__day">{day}</span>
        {price && <span className="pl-tile__price">{price}</span>}
        {state === SEARCH_INCOMPLETE && <span className="pl-tile__note">Not verified</span>}
        {isReference && <span className="pl-tile__badge" aria-hidden="true" />}
        {state === LOADING && <span className="pl-tile__skeleton" aria-hidden="true" />}
      </span>
      <span className="pl-tooltip" id={tipId} role="tooltip">
        <TooltipBody iso={iso} state={state} cell={cell} tripLine={tripLine} />
      </span>
    </button>
  );
}

function TooltipBody({ iso, state, cell, tripLine }) {
  const [y, m, d] = iso.split('-');
  const title = new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', day: 'numeric', month: 'long', year: 'numeric' })
    .format(new Date(Date.UTC(Number(y), Number(m) - 1, Number(d))));
  return (
    <>
      <strong className="pl-tooltip__date">{title}</strong>
      {state === FOUND && (
        <>
          <span className="pl-tooltip__label">Minimum valid holiday</span>
          <span className="pl-tooltip__price">{formatINR(cell.min_total_inr)}</span>
        </>
      )}
      {state === INFEASIBLE && <span>No complete valid trip available for this date.</span>}
      {state === SEARCH_INCOMPLETE && <span>Minimum price not verified.</span>}
      {state === LOADING && <span>Checking flights, hotels and transfers…</span>}
      {state === ERROR && <span>Price could not be loaded.</span>}
      {state === NOT_ELIGIBLE && <span>The trip would end after the last travel date.</span>}
      {state === OUTSIDE_WINDOW && <span>Outside the travel window.</span>}
      {(state === FOUND || state === INFEASIBLE || state === SEARCH_INCOMPLETE) && (
        <span className="pl-tooltip__trip">{tripLine}</span>
      )}
    </>
  );
}

export default memo(PriceTile);
