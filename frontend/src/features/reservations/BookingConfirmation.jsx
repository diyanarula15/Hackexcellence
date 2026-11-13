import { useState } from 'react';
import { formatINR } from '../format.js';
import ReservationLookup from './ReservationLookup.jsx';

export default function BookingConfirmation({ reference, total, confirmedAt, onExport, busy = false }) {
  const [copied, setCopied] = useState(false);
  const [lookupOpen, setLookupOpen] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(reference);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  return (
    <section className="booking-confirmation" aria-labelledby="booking-confirmation-title">
      {lookupOpen && <ReservationLookup initialReference={reference} onClose={() => setLookupOpen(false)} />}
      <p className="eyebrow">Reservation confirmed</p>
      <h3 id="booking-confirmation-title">Your holiday is booked</h3>
      <p className="booking-confirmation__reference mono">{reference}</p>
      <p className="results__muted">
        {total != null && `${formatINR(total)} · `}{confirmedAt ? `Confirmed ${confirmedAt}` : 'Keep this reference to look up your itinerary.'}
      </p>
      <div className="booking-confirmation__actions">
        <button type="button" className="btn btn--small" onClick={copy}>{copied ? 'Copied' : 'Copy reference'}</button>
        <button type="button" className="btn btn--small" onClick={() => setLookupOpen(true)}>View reservation</button>
        <button type="button" className="btn btn--small" onClick={onExport} disabled={busy}>{busy ? 'Preparing…' : 'Download itinerary'}</button>
      </div>
    </section>
  );
}
