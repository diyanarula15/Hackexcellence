import { useRef, useState } from 'react';
import { confirmHoliday } from '../../services/reservationsApi.js';
import { formatDate, formatINR, formatTravelers, plural } from '../format.js';
import ReservationModal from './ReservationModal.jsx';

export default function ConfirmHoliday({ pkg, onClose, onConfirmed }) {
  const [acknowledged, setAcknowledged] = useState(false);
  const [status, setStatus] = useState('idle');
  const [error, setError] = useState('');
  const inFlight = useRef(false);
  const overBudget = !pkg.budget?.within_budget;
  const busy = status === 'loading';

  const confirm = async () => {
    if (inFlight.current || (overBudget && !acknowledged)) return;
    inFlight.current = true;
    setStatus('loading');
    setError('');
    try {
      const response = await confirmHoliday(pkg.id, pkg.version);
      setStatus('done');
      onConfirmed(response);
    } catch (err) {
      setStatus('error');
      setError(err.message || 'Could not confirm this reservation. Please try again.');
    } finally {
      inFlight.current = false;
    }
  };

  return (
    <ReservationModal titleId="confirm-title" onClose={onClose} closeDisabled={busy}>
        <button className="reservation-dialog__close" type="button" aria-label="Close review" onClick={onClose} disabled={busy}>×</button>
        <p className="eyebrow">Final review</p>
        <h2 id="confirm-title">Confirm this holiday?</h2>
        <p>{plural(pkg.nights, 'night')} in {pkg.country}, {formatDate(pkg.start_date)} – {formatDate(pkg.end_date)}</p>
        <p className="reservation-review__route" aria-label="Route">
          {[pkg.departure?.city, ...(pkg.city_plan ?? []).map((stay) => stay.city), pkg.departure?.city].filter(Boolean).join(' → ')}
        </p>
        <dl className="reservation-review__facts">
          <div><dt>Travelers</dt><dd>{formatTravelers(pkg.travelers)}</dd></div>
          <div><dt>Total price</dt><dd>{formatINR(pkg.total_inr)}</dd></div>
          <div><dt>Budget</dt><dd>{formatINR(pkg.budget?.budget_inr)}</dd></div>
          {overBudget && <div className="is-over"><dt>Over budget by</dt><dd>{formatINR(pkg.budget?.over_budget_inr)}</dd></div>}
        </dl>
        <section className="reservation-review__included" aria-label="What's included">
          <h3>Included in this holiday</h3>
          <dl className="rows">
            <dt>Flights</dt><dd>{formatINR(pkg.pricing?.flights)}</dd>
            <dt>Hotels</dt><dd>{formatINR(pkg.pricing?.hotels)}</dd>
            <dt>Transfers</dt><dd>{formatINR((pkg.pricing?.airport_transfers ?? 0) + (pkg.pricing?.intercity_transfers ?? 0))}</dd>
            <dt>Activities</dt><dd>{formatINR(pkg.pricing?.attractions)}</dd>
          </dl>
        </section>
        <p>Review the itinerary and price above. Confirming will book this saved package, and it can no longer be edited.</p>
        <p className="reservation-dialog__note">Simulated reservation · confirmation is immediate.</p>
        {overBudget && (
          <label className="reservation-review__ack">
            <input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} />
            I understand this package is over my budget and want to proceed.
          </label>
        )}
        {error && <p className="reservation__error" role="alert">{error}</p>}
        <div className="reservation-dialog__actions">
          <button type="button" className="btn" onClick={onClose} disabled={busy}>Go back</button>
          <button type="button" className="btn btn--primary" onClick={confirm} disabled={busy || (overBudget && !acknowledged)}>
            {busy ? 'Confirming…' : 'Confirm Holiday'}
          </button>
        </div>
        <p className="reservation__live" aria-live="polite">{busy ? 'Sending your confirmation…' : ''}</p>
    </ReservationModal>
  );
}
