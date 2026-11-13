/**
 * features/saved-trips/SavedTrips.jsx — "My saved trips": a modal listing the bookmarks.
 *
 * Open reopens the holiday (bookingStore.openPackage). Rename and Remove change only the bookmark;
 * Remove says so, because the holiday itself is kept.
 */

import { useCallback, useEffect, useId, useState } from 'react';
import ReservationModal from '../reservations/ReservationModal.jsx';
import { listSavedTrips, removeSavedTrip, renameSavedTrip } from '../../services/savedTripsApi.js';
import { openPackage } from '../../state/bookingStore.js';
import { formatDate, formatDay, formatINR, formatTravelers, plural } from '../format.js';
import './SavedTrips.css';

const MAX_NAME = 60;

const STATUS_LABEL = { PLANNED: 'Planned', BOOKED: 'Booked' };

function errorText(error) {
  return error?.message ?? 'Something went wrong. Please try again.';
}

/** @returns {string | null} an inline validation message, or null when the name is usable */
function nameProblem(value) {
  const name = value.trim();
  if (!name) return 'Enter a name for this trip.';
  if (name.length > MAX_NAME) return `Trip names must be 1 to ${MAX_NAME} characters.`;
  return null;
}

function TripCard({ trip, onChanged, onRemoved, onOpen }) {
  const id = trip.package_id;
  const [mode, setMode] = useState('view'); // view | rename | confirm-remove
  const [value, setValue] = useState(trip.name);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const renameId = useId();
  const headingId = `${renameId}-name`;

  const startRename = () => {
    setValue(trip.name);
    setError(null);
    setMode('rename');
  };

  const stop = () => {
    setError(null);
    setMode('view');
  };

  const submitRename = async (event) => {
    event.preventDefault();
    const problem = nameProblem(value);
    if (problem) {
      setError({ message: problem });
      return;
    }
    setBusy(true);
    setError(null);
    try {
      onChanged(await renameSavedTrip(id, value.trim()));
      setMode('view');
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  const confirmRemove = async () => {
    setBusy(true);
    setError(null);
    try {
      await removeSavedTrip(id);
      onRemoved(id);
    } catch (err) {
      setError(err);
      setMode('view');
    } finally {
      setBusy(false);
    }
  };

  const isBooked = trip.status === 'BOOKED';
  const dates = `${formatDay(trip.start_date)} – ${formatDate(trip.end_date)}`;

  return (
    <li className="saved-card" aria-labelledby={headingId}>
      <div className="saved-card__head">
        <div className="saved-card__title">
          <h3 id={headingId} className="saved-card__name">{trip.name}</h3>
          <p className="saved-card__country">{trip.country}</p>
        </div>
        <span className={`saved-badge saved-badge--${isBooked ? 'booked' : 'planned'}`}>
          {STATUS_LABEL[trip.status] ?? trip.status}
          {isBooked && trip.booking_reference ? ` · ${trip.booking_reference}` : ''}
        </span>
      </div>

      <dl className="saved-card__facts">
        <div>
          <dt>Dates</dt>
          <dd>{dates} · {plural(trip.nights, 'night')}</dd>
        </div>
        <div>
          <dt>Travelers</dt>
          <dd>{formatTravelers(trip.travelers)}</dd>
        </div>
        <div>
          <dt>Route</dt>
          <dd>{trip.cities.join(' → ')}</dd>
        </div>
        <div>
          <dt>Total</dt>
          <dd>{formatINR(trip.total_inr)}</dd>
        </div>
      </dl>
      <p className="saved-card__meta">
        Saved {formatDate(trip.saved_at)}
        {trip.updated_at !== trip.saved_at && ` · Updated ${formatDate(trip.updated_at)}`}
      </p>

      {mode === 'rename' && (
        <form className="saved-card__rename" onSubmit={submitRename} noValidate>
          <label htmlFor={renameId} className="saved-trip-form__label">Rename trip</label>
          <input
            id={renameId}
            className="saved-trip-form__input"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            disabled={busy}
            autoFocus
            aria-invalid={error ? 'true' : undefined}
          />
          {error && <p className="saved-trip-form__error" role="alert">{errorText(error)}</p>}
          <div className="saved-trip-actions">
            <button type="submit" className="saved-trip-btn saved-trip-btn--primary" disabled={busy}>
              {busy ? 'Saving…' : 'Save name'}
            </button>
            <button type="button" className="saved-trip-btn" onClick={stop} disabled={busy}>Cancel</button>
          </div>
        </form>
      )}

      {mode === 'confirm-remove' && (
        <div className="saved-card__confirm" role="group" aria-label="Confirm removal">
          <p>Remove from saved trips? The holiday itself is kept.</p>
          <div className="saved-trip-actions">
            <button type="button" className="saved-trip-btn saved-trip-btn--danger" onClick={confirmRemove} disabled={busy}>
              {busy ? 'Removing…' : 'Remove from saved'}
            </button>
            <button type="button" className="saved-trip-btn" onClick={stop} disabled={busy}>Cancel</button>
          </div>
        </div>
      )}

      {mode !== 'rename' && error && <p className="saved-trip-form__error" role="alert">{errorText(error)}</p>}

      {mode === 'view' && (
        <div className="saved-trip-actions">
          <button type="button" className="saved-trip-btn saved-trip-btn--primary" onClick={() => onOpen(id)}>
            Open
          </button>
          <button type="button" className="saved-trip-btn" onClick={startRename}>Rename</button>
          <button type="button" className="saved-trip-btn" onClick={() => setMode('confirm-remove')}>
            Remove from saved
          </button>
        </div>
      )}
    </li>
  );
}

/** @param {{ onClose: () => void }} props */
export default function SavedTrips({ onClose }) {
  const titleId = useId();
  const [status, setStatus] = useState('loading'); // loading | ready | error
  const [trips, setTrips] = useState([]);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    setStatus('loading');
    setError(null);
    listSavedTrips()
      .then((list) => {
        setTrips(list);
        setStatus('ready');
      })
      .catch((err) => {
        setError(err);
        setStatus('error');
      });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const replace = (card) => setTrips((list) => list.map((t) => (t.package_id === card.package_id ? card : t)));
  const remove = (id) => setTrips((list) => list.filter((t) => t.package_id !== id));
  const open = (id) => {
    openPackage(id);
    onClose();
  };

  return (
    <ReservationModal titleId={titleId} onClose={onClose} className="saved-trips-dialog">
      <div className="saved-trips">
        <header className="saved-trips__header">
          <h2 id={titleId} className="saved-trips__title">My saved trips</h2>
          <button type="button" className="saved-trip-btn" onClick={onClose}>Close</button>
        </header>

        {status === 'loading' && <p className="saved-trips__status" role="status">Loading your saved trips…</p>}

        {status === 'error' && (
          <div className="saved-trips__status" role="alert">
            <p>{errorText(error)}</p>
            <button type="button" className="saved-trip-btn saved-trip-btn--primary" onClick={load}>Try again</button>
          </div>
        )}

        {status === 'ready' && trips.length === 0 && (
          <div className="saved-trips__status">
            <p>No saved trips yet.</p>
            <p>
              Open a planned holiday and choose “Save trip” to keep it here under a name you pick.
              Saving never books the holiday.
            </p>
          </div>
        )}

        {status === 'ready' && trips.length > 0 && (
          <ul className="saved-trips__list">
            {trips.map((trip) => (
              <TripCard
                key={trip.package_id}
                trip={trip}
                onChanged={replace}
                onRemoved={remove}
                onOpen={open}
              />
            ))}
          </ul>
        )}
      </div>
    </ReservationModal>
  );
}
