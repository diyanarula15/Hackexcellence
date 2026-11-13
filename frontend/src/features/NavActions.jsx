
import { useState } from 'react';
import { openPackage } from '../state/bookingStore.js';
import { scrollToPlanner } from './format.js';
import ReservationLookup from './reservations/ReservationLookup.jsx';


export default function NavActions() {
  const [packageId, setPackageId] = useState('');
  const [lookupOpen, setLookupOpen] = useState(false);
  return (
    <div className="nav-actions">
      {lookupOpen && <ReservationLookup onClose={() => setLookupOpen(false)} />}
      <form
        className="nav-actions__open"
        role="search"
        aria-label="Open a saved package"
        onSubmit={(e) => {
          e.preventDefault();
          openPackage(packageId);
        }}
      >
        <input
          className="nav-actions__input"
          value={packageId}
          onChange={(e) => setPackageId(e.target.value)}
          placeholder="Saved package ID"
          aria-label="Saved package ID"
          autoComplete="off"
          spellCheck={false}
        />
        <button type="submit" className="btn btn--small">
          Open
        </button>
      </form>
      <button type="button" className="btn btn--small" onClick={() => setLookupOpen(true)}>
        Find reservation
      </button>
      <button type="button" className="btn btn--small btn--primary" onClick={scrollToPlanner}>
        Plan a trip
      </button>
    </div>
  );
}
