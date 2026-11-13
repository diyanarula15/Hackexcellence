/**
 * price-landscape/landscapeModel.js — pure presentation logic (no React, no fetch).
 *
 * The honesty rules live here so they are easy to test:
 *   - only FOUND cells with proven_minimum have a price; nothing is ever interpolated or guessed;
 *   - visual height/colour is normalised over PROVEN prices of the evaluated range only;
 *   - comparisons and savings need both dates proven; otherwise "comparison unavailable";
 *   - "cheapest date" is only claimed when the backend says the whole range was evaluated.
 */

import { formatLongDate, isWithin, parseIso } from './dateUtils.js';
import { ERROR, FOUND, INFEASIBLE, LOADING, NOT_ELIGIBLE, OUTSIDE_WINDOW, SEARCH_INCOMPLETE } from './types.js';

export const MIN_ELEVATION = 4;     // px; even the cheapest date stands slightly off the board
export const ELEVATION_RANGE = 20;  // px; a restrained terrain, not towers
export const DARK_TEXT_LEVEL = 0.55;

/** A cell has a price only when the backend proved it. */
export const isProven = (cell) =>
  Boolean(cell && cell.status === FOUND && cell.proven_minimum === true && Number.isInteger(cell.min_total_inr));

/** Only eligible dates the backend listed are selectable; a proven-impossible date is not. */
export const isSelectable = (cell) => Boolean(cell && cell.status !== INFEASIBLE);

/**
 * The visual state of one calendar day.
 * @param {string} iso
 * @param {Map<string, import('./types.js').DatePriceCell> | null} cellsByDate  null while loading
 * @param {{ first_night: string, last_departure: string } | null} window
 * @param {{ loading?: boolean, failed?: boolean }} [flags]
 * @returns {import('./types.js').TileState}
 */
export function tileState(iso, cellsByDate, window, { loading = false, failed = false } = {}) {
  if (window && !isWithin(iso, window.first_night, window.last_departure)) return OUTSIDE_WINDOW;
  if (loading || (!cellsByDate && !failed)) return LOADING;
  if (failed) return ERROR;
  const cell = cellsByDate.get(iso);
  if (!cell) return NOT_ELIGIBLE;
  if (cell.status === FOUND) return isProven(cell) ? FOUND : SEARCH_INCOMPLETE; // unproven = unverified
  if (cell.status === INFEASIBLE) return INFEASIBLE;
  return SEARCH_INCOMPLETE;
}

/** Whole days since 1970-01-01 for a valid ISO date (no timezone involved). */
const dayNumber = (iso) => {
  const d = parseIso(iso);
  return d ? Date.UTC(d.year, d.month - 1, d.day) / 86400000 : null;
};

/**
 * The proven date nearest to `iso` (smallest distance in days, either side); a tie goes to the
 * earlier date. Only proven cells count. Returns the cell, or null when no date is proven.
 * @param {import('./types.js').DatePriceCell[] | null} cells
 * @param {string} iso
 * @returns {import('./types.js').DatePriceCell | null}
 */
export function nearestProvenDate(cells, iso) {
  const target = dayNumber(iso);
  if (target === null) return null;
  let best = null;
  let bestDistance = Infinity;
  for (const cell of cells ?? []) {
    const day = isProven(cell) ? dayNumber(cell.date) : null;
    if (day === null) continue;
    const distance = Math.abs(day - target);
    if (distance < bestDistance || (distance === bestDistance && cell.date < best.date)) {
      best = cell;
      bestDistance = distance;
    }
  }
  return best;
}

/** Lowest and highest proven price in a list of cells (null when none is proven). */
export function provenRange(cells) {
  const prices = (cells ?? []).filter(isProven).map((c) => c.min_total_inr);
  return prices.length ? { min: Math.min(...prices), max: Math.max(...prices) } : null;
}

/** 0 (cheapest proven) … 1 (dearest proven); null for a cell without a proven price. */
export function normalizedLevel(cell, range) {
  if (!isProven(cell) || !range) return null;
  return (cell.min_total_inr - range.min) / Math.max(range.max - range.min, 1);
}

/** Cheaper dates sit lower; height only encodes price, never desirability. */
export const elevationFor = (level) => (level === null ? 0 : MIN_ELEVATION + level * ELEVATION_RANGE);

/**
 * Compare a selected date with the traveler's original date. Both must be proven minima for the
 * same trip; otherwise the comparison is unavailable (never a guess).
 * @returns {{ kind: 'SAVE'|'MORE'|'SAME'|'UNAVAILABLE'|'ORIGINAL', amount: number | null }}
 */
export function comparePrices(reference, selected) {
  if (!reference || !selected) return { kind: 'UNAVAILABLE', amount: null };
  if (reference.date === selected.date) return { kind: 'ORIGINAL', amount: null };
  if (!isProven(reference) || !isProven(selected)) return { kind: 'UNAVAILABLE', amount: null };
  const diff = reference.min_total_inr - selected.min_total_inr;
  if (diff > 0) return { kind: 'SAVE', amount: diff };
  if (diff < 0) return { kind: 'MORE', amount: -diff };
  return { kind: 'SAME', amount: 0 };
}

/**
 * The small "best date" note for a month.
 * @param {import('./types.js').DatePricesResponse | null} response
 * @param {import('./types.js').DatePriceCell | null} reference  the original date (proven or not)
 * @returns {{ title: string, detail: string | null, date: string | null } | null}
 */
export function bestDateNote(response, reference) {
  if (!response) return null;
  const proven = (response.dates ?? []).filter(isProven);
  if (!proven.length) return null;
  const min = Math.min(...proven.map((c) => c.min_total_inr));
  const ties = proven.filter((c) => c.min_total_inr === min).map((c) => c.date).sort();
  const best = ties[0];
  const full = response.range_fully_evaluated === true;
  const title = full ? 'Lowest proven price this month' : 'Lowest verified price among evaluated dates';
  let detail = null;
  const cmp = comparePrices(reference, proven.find((c) => c.date === best));
  if (cmp.kind === 'SAVE') detail = `Start ${formatLongDate(best)} and save ${formatINR(cmp.amount)}.`;
  else if (ties.length > 1) detail = `${ties.length} dates share the same minimum price.`;
  else if (cmp.kind === 'ORIGINAL') detail = 'Your chosen date already has the lowest price.';
  return { title, detail, date: best, total: min, ties: ties.length, fullyEvaluated: full };
}

/** The panel-level state for a month's fetch. */
export function viewState({ status, response }) {
  if (status === 'idle') return 'IDLE';
  if (status === 'loading') return 'LOADING';
  if (status === 'error') return 'ERROR';
  if (!response || !(response.dates ?? []).length) return 'EMPTY';
  return response.range_fully_evaluated === false ? 'PARTIALLY_EVALUATED' : 'READY';
}

const INR = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 });
/** 218700 → "₹2,18,700"; anything that is not a number → "—" (never "₹0"). */
export const formatINR = (amount) => (Number.isFinite(amount) ? INR.format(amount) : '—');

/** Screen-reader / tooltip sentence for a tile. */
export function describeTile(iso, state, cell) {
  const day = formatLongDate(iso);
  switch (state) {
    case FOUND:
      return `${day}: minimum valid holiday ${formatINR(cell.min_total_inr)}`;
    case INFEASIBLE:
      return `${day}: no complete valid trip available for this date`;
    case SEARCH_INCOMPLETE:
      return `${day}: minimum price not verified`;
    case LOADING:
      return `${day}: loading price`;
    case ERROR:
      return `${day}: price could not be loaded`;
    case NOT_ELIGIBLE:
      return `${day}: the trip would not fit in the travel window from this date`;
    default:
      return `${day}: outside the travel window`;
  }
}
