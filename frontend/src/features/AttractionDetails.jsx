// The attraction detail drawer. Every fact comes from the catalog (via the backend); viewing never
// changes the itinerary. Reads what it needs from the store, so it can be mounted anywhere.

import { useEffect, useId, useRef, useState } from 'react';
import { getAttraction } from '../services/attractionsApi.js';
import {
  bookingStore,
  closeAttractionDetails,
  previewRemoveAttraction,
  toggleAttractionSelection,
} from '../state/bookingStore.js';
import { useStore } from '../state/store.js';
import { formatDate, formatDay, formatDuration, formatINR, formatTime, humanize, plural } from './format.js';
import './AttractionDetails.css';

const ALL_DAYS = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'];
const DAY_NAMES = { MON: 'Mon', TUE: 'Tue', WED: 'Wed', THU: 'Thu', FRI: 'Fri', SAT: 'Sat', SUN: 'Sun' };

const money = (amount) => (amount === 0 ? 'Free' : formatINR(amount));

/** The package's planned visit to this attraction, or null when it is not scheduled. */
function findVisit(pkg, attractionId) {
  for (const day of pkg?.days ?? []) {
    for (const event of day.events ?? []) {
      if (event.kind === 'ATTRACTION' && event.catalog_id === attractionId) return event;
    }
  }
  return null;
}

/** Opening days in short form: "Every day" or "Mon, Wed, Fri". */
function openDaysText(days) {
  if (ALL_DAYS.every((d) => days.includes(d))) return 'Every day';
  return days.map((d) => DAY_NAMES[d] ?? d).join(', ');
}

export default function AttractionDetails() {
  const details = useStore(bookingStore, (s) => s.attractionDetails);
  const pkg = useStore(bookingStore, (s) => s.result.response?.package ?? null);
  const selection = useStore(bookingStore, (s) => s.attractionSelection);
  const titleId = useId();
  const dialogRef = useRef(null);
  const openerRef = useRef(null);
  const [load, setLoad] = useState({ id: null, status: 'idle', data: null, error: null });
  const [brokenImage, setBrokenImage] = useState(null);

  const { open, attraction_id: id, date } = details;

  // Fetch the attraction; a response for an earlier id is ignored (see `active`).
  useEffect(() => {
    if (!open || !id) return undefined;
    const controller = new AbortController();
    let active = true;
    setLoad({ id, status: 'loading', data: null, error: null });
    getAttraction(id, { signal: controller.signal })
      .then((data) => {
        if (active) setLoad({ id, status: 'ready', data, error: null });
      })
      .catch((error) => {
        if (active && error?.name !== 'AbortError') setLoad({ id, status: 'error', data: null, error: error.message });
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [open, id]);

  // Focus moves into the drawer, Escape closes it, and focus returns to the opener on close.
  useEffect(() => {
    if (!open) return undefined;
    openerRef.current = document.activeElement;
    dialogRef.current?.focus();
    const onKey = (event) => {
      if (event.key === 'Escape') closeAttractionDetails();
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      openerRef.current?.focus?.();
    };
  }, [open]);

  if (!open) return null;

  const current = load.id === id ? load : { status: 'loading', data: null, error: null };
  const a = current.status === 'ready' ? current.data : null;
  const visit = pkg && id ? findVisit(pkg, id) : null;
  const selected = selection.some((e) => e.attraction_id === id);
  const name = a?.name ?? visit?.name ?? selection.find((e) => e.attraction_id === id)?.name ?? 'Attraction';
  const packageStatus = pkg?.status;

  const removeVisit = () => {
    const opener = openerRef.current;
    openerRef.current = null; // focus goes to the change drawer, not back here
    previewRemoveAttraction(visit.item_id, opener, `Remove ${name}`);
    closeAttractionDetails();
  };

  let changeActions = null;
  if (!pkg) {
    changeActions = <p className="attraction-details__note">Open a holiday to add or remove visits.</p>;
  } else if (packageStatus === 'BOOKED') {
    changeActions = <p className="attraction-details__note">This holiday is booked; details only.</p>;
  } else if (packageStatus === 'PLANNED' && visit) {
    changeActions = (
      <div className="attraction-details__actions">
        <button type="button" className="btn btn--small change-trigger" onClick={removeVisit}>
          Remove from holiday
        </button>
      </div>
    );
  } else if (packageStatus === 'PLANNED') {
    changeActions = (
      <div className="attraction-details__actions">
        <button
          type="button"
          className="btn btn--small"
          disabled={!date || !a}
          onClick={() =>
            toggleAttractionSelection({ attraction_id: id, name: a.name, city: a.city, date })
          }
        >
          {selected ? 'Selected ✓' : 'Add to selection'}
        </button>
        {!date && (
          <p className="attraction-details__note">Open this from a day in the itinerary to add it to a day.</p>
        )}
      </div>
    );
  }

  return (
    <>
      <div className="attraction-details__backdrop" aria-hidden="true" onClick={closeAttractionDetails} />
      <aside
        ref={dialogRef}
        className="attraction-details"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <header className="attraction-details__header">
          <div className="attraction-details__titles">
            <h2 id={titleId} className="attraction-details__title">{name}</h2>
            {a?.name_ja && <p className="attraction-details__sub" lang="ja">{a.name_ja}</p>}
            {a && <p className="attraction-details__sub">{a.city} · {a.country}</p>}
          </div>
          <button
            type="button"
            className="attraction-details__close"
            aria-label="Close"
            onClick={closeAttractionDetails}
          >
            ✕
          </button>
        </header>

        <div className="attraction-details__body">
          {current.status === 'loading' && <p className="attraction-details__status" role="status">Loading…</p>}
          {current.status === 'error' && (
            <p className="attraction-details__error" role="alert">{current.error}</p>
          )}

          {a && (
            <>
              {a.image_url && brokenImage !== id ? (
                <figure className="attraction-details__figure">
                  <img
                    className="attraction-details__photo"
                    src={a.image_url}
                    alt={a.name}
                    loading="lazy"
                    onError={() => setBrokenImage(id)}
                  />
                  {a.image_credit && <figcaption className="attraction-details__credit">{a.image_credit}</figcaption>}
                </figure>
              ) : (
                <div className="attraction-details__fallback">
                  <span>{humanize(a.category)}</span>
                  <strong>{a.name}</strong>
                </div>
              )}

              <p className="attraction-details__meta">{humanize(a.category)}</p>

              {visit && (
                <section className="attraction-details__section" aria-label="Your visit">
                  <h3>Your visit</h3>
                  <dl className="attraction-details__list">
                    <dt>Date</dt>
                    <dd>{formatDay(visit.start)}</dd>
                    <dt>Time</dt>
                    <dd>{formatTime(visit.start)}–{formatTime(visit.end)}</dd>
                    <dt>Price</dt>
                    <dd>
                      {money(visit.price_inr)} for your party
                      {visit.quantity ? ` (${plural(visit.quantity, 'ticket')})` : ''}
                    </dd>
                  </dl>
                </section>
              )}

              <section className="attraction-details__section" aria-label="Opening">
                <h3>Opening</h3>
                <dl className="attraction-details__list">
                  <dt>Days</dt>
                  <dd>{openDaysText(a.open_days)}</dd>
                  <dt>Hours</dt>
                  <dd>{a.open_from}–{a.open_until}</dd>
                  {a.closed_dates.length > 0 && (
                    <>
                      <dt>Closed</dt>
                      <dd>{a.closed_dates.map((d) => formatDate(d)).join(', ')}</dd>
                    </>
                  )}
                  <dt>Visit takes</dt>
                  <dd>{formatDuration(a.visit_minutes)}</dd>
                </dl>
              </section>

              <section className="attraction-details__section" aria-label="Prices">
                <h3>Entry prices</h3>
                <dl className="attraction-details__list">
                  <dt>Adult</dt>
                  <dd>{money(a.price_per_person_inr)}</dd>
                  <dt>Child</dt>
                  <dd>{a.child_price_inr == null ? 'Same as adult' : money(a.child_price_inr)}</dd>
                </dl>
              </section>

              <section className="attraction-details__section" aria-label="Map">
                <a
                  className="attraction-details__map"
                  href={a.maps_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  View on Google Maps
                </a>
                <p className="attraction-details__note">A map search for this name and city. Not the attraction's own website.</p>
              </section>

              <section className="attraction-details__section" aria-label="Changes">
                {changeActions}
              </section>
            </>
          )}
        </div>
      </aside>
    </>
  );
}
