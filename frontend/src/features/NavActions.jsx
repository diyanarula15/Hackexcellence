// Top navigation: every button opens a real feature. Overlays are tracked in the store (`panel`),
// so other parts of the page (e.g. "View saved trips" after saving) can open the same ones.

import { useState } from 'react';
import { useStore } from '../state/store.js';
import { bookingStore, closePanel, openPackage, openPanel } from '../state/bookingStore.js';
import { scrollToPlanner } from './format.js';
import ReservationLookup from './reservations/ReservationLookup.jsx';
import SavedTrips from './saved-trips/SavedTrips.jsx';

const isReady = (form) => Boolean(form.departure && form.country && form.start_date && form.nights && form.adults);

export default function NavActions() {
  const panel = useStore(bookingStore, (s) => s.panel);
  const form = useStore(bookingStore, (s) => s.form);
  const [packageId, setPackageId] = useState('');
  const [hint, setHint] = useState('');

  const exploreDates = () => {
    if (isReady(form)) {
      setHint('');
      openPanel('landscape');
      return;
    }
    scrollToPlanner();
    setHint('Fill in from, to, first day, nights and adults, then choose Explore dates.');
  };

  return (
    <div className="nav-actions">
      {panel === 'lookup' && <ReservationLookup onClose={closePanel} />}
      {panel === 'saved' && <SavedTrips onClose={closePanel} />}
      <form
        className="nav-actions__open"
        role="search"
        aria-label="Open a saved package by ID"
        onSubmit={(e) => {
          e.preventDefault();
          openPackage(packageId);
        }}
      >
        <input
          className="nav-actions__input"
          value={packageId}
          onChange={(e) => setPackageId(e.target.value)}
          placeholder="Package ID"
          aria-label="Package ID"
          autoComplete="off"
          spellCheck={false}
        />
        <button type="submit" className="btn btn--small" disabled={!packageId.trim()}>
          Open
        </button>
      </form>
      <button type="button" className="btn btn--small" onClick={exploreDates}>
        Explore dates
      </button>
      <button type="button" className="btn btn--small" onClick={() => openPanel('saved')}>
        Saved trips
      </button>
      <button type="button" className="btn btn--small" onClick={() => openPanel('lookup')}>
        Find booking
      </button>
      <button
        type="button"
        className="btn btn--small btn--primary"
        onClick={() => {
          setHint('');
          scrollToPlanner();
        }}
      >
        Plan holiday
      </button>
      <p className="nav-actions__hint" role="status" aria-live="polite">{hint}</p>
    </div>
  );
}
