import { useState } from 'react';
import { formatINR } from '../format.js';
import ReservationLookup from './ReservationLookup.jsx';
import { copyText } from './copyText.js';

export default function BookingConfirmation({ reference, total, confirmedAt, onExport, busy = false }) {
  const [copied, setCopied] = useState(null); // null | 'ok' | 'failed'
  const [lookupOpen, setLookupOpen] = useState(false);
  const copy = async () => setCopied((await copyText(reference)) ? 'ok' : 'failed');

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
        <button type="button" className="btn btn--small" onClick={copy}>{copied === 'ok' ? 'Copied' : 'Copy reference'}</button>
        <button type="button" className="btn btn--small" onClick={() => setLookupOpen(true)}>View reservation</button>
        <button type="button" className="btn btn--small" onClick={onExport} disabled={busy}>{busy ? 'Preparing…' : 'Download itinerary'}</button>
      </div>
      {copied === 'failed' && (
        <p className="results__muted" role="status">This browser blocked copying. Select the reference above and copy it by hand.</p>
      )}
    </section>
  );
}
