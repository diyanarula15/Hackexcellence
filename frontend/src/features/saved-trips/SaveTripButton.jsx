/**
 * features/saved-trips/SaveTripButton.jsx - bookmark a PLANNED holiday under a friendly name.
 *
 * Saving never books, re-plans or copies the package; the backend keeps only the name. A BOOKED
 * package renders nothing (it is already a confirmed reservation).
 */

import { useEffect, useId, useState } from 'react';
import { listSavedTrips, renameSavedTrip, saveTrip } from '../../services/savedTripsApi.js';
import { formatDate } from '../format.js';
import './SavedTrips.css';

const MAX_NAME = 60;

/** The same default the backend uses: "Japan · 10 Apr–16 Apr 2027". */
export function defaultTripName(pkg) {
  const start = formatDate(pkg.start_date).replace(/\s\d{4}$/, '');
  return `${pkg.country} · ${start}–${formatDate(pkg.end_date)}`;
}

/** @returns {string | null} an inline validation message, or null when the name is usable */
function nameProblem(value) {
  const name = value.trim();
  if (!name) return 'Enter a name for this trip.';
  if (name.length > MAX_NAME) return `Trip names must be 1 to ${MAX_NAME} characters.`;
  return null;
}

function errorText(error) {
  return error?.message ?? 'Something went wrong. Please try again.';
}

/**
 * @param {{ pkg: { id?: string, package_id?: string, status: string, country: string,
 *                  start_date: string, end_date: string },
 *           onViewSaved?: () => void }} props
 */
export default function SaveTripButton({ pkg, onViewSaved }) {
  const packageId = pkg.id ?? pkg.package_id;
  const inputId = useId();
  const [saved, setSaved] = useState(null); // the saved-trip card once this holiday is bookmarked
  const [justSaved, setJustSaved] = useState(false);
  const [mode, setMode] = useState('idle'); // idle | form | rename
  const [value, setValue] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  // Show the true state when the holiday was already bookmarked. A failed lookup is not an error
  // here: the save button still works.
  useEffect(() => {
    let active = true;
    if (pkg.status !== 'PLANNED') return undefined;
    listSavedTrips()
      .then((trips) => {
        const found = trips.find((t) => t.package_id === packageId);
        if (active && found) setSaved(found);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [packageId, pkg.status]);

  if (pkg.status !== 'PLANNED') return null;

  const open = (nextMode) => {
    setError(null);
    setValue(nextMode === 'rename' ? saved.name : defaultTripName(pkg));
    setMode(nextMode);
  };

  const close = () => {
    setMode('idle');
    setError(null);
  };

  const submit = async (event) => {
    event.preventDefault();
    const problem = nameProblem(value);
    if (problem) {
      setError({ message: problem });
      return;
    }
    const name = value.trim();
    setBusy(true);
    setError(null);
    try {
      if (mode === 'rename') {
        setSaved(await renameSavedTrip(packageId, name));
        setJustSaved(false);
      } else {
        setSaved(await saveTrip(packageId, name));
        setJustSaved(true);
      }
      setMode('idle');
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  if (mode !== 'idle') {
    const isRename = mode === 'rename';
    return (
      <form className="saved-trip-form" onSubmit={submit} noValidate>
        <label htmlFor={inputId} className="saved-trip-form__label">
          {isRename ? 'Rename trip' : 'Name this trip'}
        </label>
        <input
          id={inputId}
          className="saved-trip-form__input"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          disabled={busy}
          autoFocus
          aria-invalid={error ? 'true' : undefined}
          aria-describedby={error ? `${inputId}-error` : undefined}
        />
        {error && (
          <p id={`${inputId}-error`} className="saved-trip-form__error" role="alert">
            {errorText(error)}
          </p>
        )}
        <div className="saved-trip-actions">
          <button type="submit" className="btn btn--primary saved-trip-btn saved-trip-btn--primary" disabled={busy}>
            {busy ? 'Saving…' : isRename ? 'Save name' : 'Save'}
          </button>
          <button type="button" className="btn saved-trip-btn" onClick={close} disabled={busy}>
            Cancel
          </button>
        </div>
      </form>
    );
  }

  if (saved) {
    return (
      <div className="saved-trip-state">
        <p className="saved-trip-state__text" role="status">
          {justSaved ? `Saved as “${saved.name}”` : 'Saved ✓'}
        </p>
        {error && (
          <p className="saved-trip-form__error" role="alert">
            {errorText(error)}
          </p>
        )}
        <div className="saved-trip-actions">
          {justSaved && onViewSaved && (
            <button type="button" className="btn saved-trip-btn" onClick={onViewSaved}>
              View saved trips
            </button>
          )}
          <button type="button" className="btn saved-trip-btn" onClick={() => open('rename')}>
            Rename
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="saved-trip-state">
      <button type="button" className="btn saved-trip-btn saved-trip-btn--secondary" onClick={() => open('form')}>
        Save trip
      </button>
      {error && (
        <p className="saved-trip-form__error" role="alert">
          {errorText(error)}
        </p>
      )}
    </div>
  );
}
