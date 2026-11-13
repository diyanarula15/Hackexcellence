/**
 * price-landscape/PriceComparison.jsx — selected date vs the traveler's original date.
 * A difference is shown only when BOTH are proven minima for the same trip.
 */

import { formatLongDate } from './dateUtils.js';
import { comparePrices, formatINR, isProven } from './landscapeModel.js';
import { usePriceCounter } from './usePriceCounter.js';

function PriceLine({ label, date, cell, loading, animate }) {
  const counted = usePriceCounter(isProven(cell) ? cell.min_total_inr : null);
  const value = animate ? counted : (isProven(cell) ? cell.min_total_inr : null);
  let text;
  if (loading) text = 'Checking…';
  else if (isProven(cell)) text = formatINR(value);
  else if (cell?.status === 'INFEASIBLE') text = 'No valid trip';
  else if (cell) text = 'Not verified';
  else text = '—';
  return (
    <div className="pl-compare__line">
      <span className="pl-compare__label">{label}</span>
      <span className="pl-compare__date">{date ? formatLongDate(date) : 'Pick a date'}</span>
      <span className="pl-compare__price" data-testid={`${label.toLowerCase().replace(/\W+/g, '-')}-price`}>{text}</span>
    </div>
  );
}

/**
 * @param {{ reference: { date: string, cell: object | null, loading: boolean },
 *           selected: { date: string | null, cell: object | null } }} props
 */
export default function PriceComparison({ reference, selected }) {
  const cmp = comparePrices(reference.cell, selected.cell);
  let message;
  let tone = 'neutral';
  if (!selected.date) message = 'Choose a start date to compare.';
  else if (cmp.kind === 'ORIGINAL') message = 'This is your original start date.';
  else if (cmp.kind === 'SAVE') {
    message = `Save ${formatINR(cmp.amount)} by starting on ${formatLongDate(selected.date)}.`;
    tone = 'save';
  } else if (cmp.kind === 'MORE') message = `${formatINR(cmp.amount)} more than your original date.`;
  else if (cmp.kind === 'SAME') message = 'Same minimum price as your original date.';
  else message = 'Price comparison unavailable.';

  return (
    <section className="pl-compare" aria-labelledby="pl-compare-title">
      <h3 className="eyebrow" id="pl-compare-title">Compare dates</h3>
      <PriceLine label="Original start" date={reference.date} cell={reference.cell} loading={reference.loading} />
      <PriceLine label="Selected start" date={selected.date} cell={selected.cell} loading={false} animate />
      <p className={`pl-compare__verdict pl-compare__verdict--${tone}`} key={`${selected.date}-${cmp.kind}`}
        role="status" aria-live="polite">
        {tone === 'save' && <PlaneGlyph />}
        {message}
      </p>
    </section>
  );
}

function PlaneGlyph() {
  return (
    <svg className="pl-plane" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M2.5 13.5 21 6.8c.9-.3 1.6.7 1 1.4l-5.3 6.1.6 6.2c.1.7-.8 1.1-1.3.6l-3.1-3.6-3.6 1.8-.4-2.6 2.1-2.9-8.5-.3z"
        fill="currentColor" />
    </svg>
  );
}
