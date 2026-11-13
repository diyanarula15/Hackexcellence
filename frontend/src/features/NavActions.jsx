// Top navigation: every button opens a real feature. Overlays are tracked in the store (`panel`),
// so other parts of the page (e.g. "View saved trips" after saving) can open the same ones.
// Flexible dates live next to the request form ("Explore flexible dates"), not here.

import { useState } from 'react';
import { useStore } from '../state/store.js';
import { bookingStore, closePanel, openPackage, openPanel } from '../state/bookingStore.js';
import { scrollToPlanner } from './format.js';
import ReservationLookup from './reservations/ReservationLookup.jsx';
import SavedTrips from './saved-trips/SavedTrips.jsx';

export default function NavActions() {
  const panel = useStore(bookingStore, (s) => s.panel);
  const [packageId, setPackageId] = useState('');

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
        <button type="submit" className="nav-actions__go" disabled={!packageId.trim()} aria-label="Open package">
          Open →
        </button>
      </form>
      <div className="nav-actions__links">
        <button type="button" className="nav-actions__link" onClick={() => openPanel('saved')}>
          Saved trips
        </button>
        <button type="button" className="nav-actions__link" onClick={() => openPanel('lookup')}>
          Find booking
        </button>
      </div>
      <button type="button" className="btn btn--small btn--primary" onClick={scrollToPlanner}>
        Plan holiday
      </button>
    </div>
  );
}
