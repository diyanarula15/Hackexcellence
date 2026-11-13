import { useRef, useState } from 'react';
import { exportReservation, getReservation } from '../../services/reservationsApi.js';
import ReservationDetails from './ReservationDetails.jsx';
import ReservationModal from './ReservationModal.jsx';
import { copyText } from './copyText.js';

const INVALID_REFERENCE = 'Enter a valid 10-digit reservation reference.';

export default function ReservationLookup({ onClose, initialReference = '' }) {
  const [reference, setReference] = useState(initialReference);
  const [reservation, setReservation] = useState(null);
  const [status, setStatus] = useState('idle');
  const [error, setError] = useState('');
  const [downloadStatus, setDownloadStatus] = useState('idle');
  const [copied, setCopied] = useState(false);
  const inFlight = useRef(false);

  const lookup = async (event) => {
    event.preventDefault();
    if (inFlight.current) return;
    const normalized = reference.trim();
    setReservation(null);
    setDownloadStatus('idle');
    setCopied(false);
    if (!/^[0-9]{10}$/.test(normalized)) {
      setStatus('error');
      setError(INVALID_REFERENCE);
      return;
    }
    inFlight.current = true;
    setStatus('loading');
    setError('');
    try {
      setReservation(await getReservation(normalized));
      setStatus('done');
    } catch (err) {
      setStatus('error');
      setError(err.message || 'Could not find this reservation.');
    } finally {
      inFlight.current = false;
    }
  };

  const downloadTrip = async () => {
    if (downloadStatus === 'loading') return;
    setDownloadStatus('loading');
    setError('');
    try {
      await exportReservation(reservation.reference ?? reference);
      setDownloadStatus('done');
    } catch (err) {
      setDownloadStatus('error');
      setError(err.message || 'Could not download the itinerary.');
    }
  };

  const copyReference = async () => setCopied((await copyText(reservation.reference ?? reference)) ? true : 'failed');

  return (
    <ReservationModal titleId="lookup-title" onClose={onClose} className="reservation-dialog--lookup">
        <button className="reservation-dialog__close" type="button" aria-label="Close reservation lookup" onClick={onClose}>×</button>
        <p className="eyebrow">Your booking</p>
        <h2 id="lookup-title">Look up a reservation</h2>
        <form className="reservation-lookup" onSubmit={lookup}>
          <label htmlFor="reservation-reference">Reservation reference</label>
          <div className="reservation-lookup__row">
            <input
              id="reservation-reference"
              value={reference}
              onChange={(event) => {
                setReference(event.target.value);
                setReservation(null);
                setDownloadStatus('idle');
                setCopied(false);
                setStatus('idle');
                setError('');
              }}
              autoComplete="off"
              spellCheck={false}
              required
              disabled={status === 'loading'}
            />
            <button type="submit" className="btn btn--primary" disabled={status === 'loading'}>{status === 'loading' ? 'Searching…' : 'Find booking'}</button>
          </div>
        </form>
        {error && <p className="reservation__error" role="alert">{error}</p>}
        {reservation && (
          <>
            <p className="reservation-lookup__found">Reservation <span className="mono">{reservation.reference}</span> · {reservation.status}</p>
            <button type="button" className="link-button" onClick={copyReference}>{copied === true ? 'Reference copied' : 'Copy reference'}</button>
            {copied === 'failed' && <span className="results__muted" role="status"> This browser blocked copying; select the reference and copy it by hand.</span>}
            <ReservationDetails reservation={reservation} />
            <div className="reservation-dialog__actions">
              <button type="button" className="btn" onClick={downloadTrip} disabled={downloadStatus === 'loading'}>{downloadStatus === 'loading' ? 'Preparing…' : 'Download JSON'}</button>
              {downloadStatus === 'done' && <span role="status">Download started</span>}
            </div>
          </>
        )}
        <p className="reservation__live" aria-live="polite">{status === 'loading' ? 'Looking up your reservation…' : ''}</p>
    </ReservationModal>
  );
}
