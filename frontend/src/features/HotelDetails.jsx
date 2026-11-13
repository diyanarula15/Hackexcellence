// The hotel detail drawer: photo (a sample room photo; the hotels are fictional), catalog facts, the
// rooms on offer, your stay, and a map search link. Read-only; reuses the attraction drawer's styles.

import { useEffect, useId, useRef, useState } from 'react';
import { getHotel } from '../services/hotelsApi.js';
import { bookingStore, closeHotelDetails } from '../state/bookingStore.js';
import { useStore } from '../state/store.js';
import { formatDay, formatINR, humanize, plural } from './format.js';
import './AttractionDetails.css';

/** The package's stay at this hotel (the check-in event), or null. */
function findStay(pkg, hotelId, stayId) {
  for (const day of pkg?.days ?? []) {
    for (const event of day.events ?? []) {
      if (event.kind === 'CHECK_IN' && event.catalog_id === hotelId && (!stayId || event.item_id === stayId)) return event;
    }
  }
  return null;
}

export default function HotelDetails() {
  const details = useStore(bookingStore, (s) => s.hotelDetails);
  const pkg = useStore(bookingStore, (s) => s.result.response?.package ?? null);
  const titleId = useId();
  const dialogRef = useRef(null);
  const openerRef = useRef(null);
  const [load, setLoad] = useState({ id: null, status: 'idle', data: null, error: null });
  const [brokenImage, setBrokenImage] = useState(null);
  const { open, hotel_id: id, stay_id: stayId } = details;

  useEffect(() => {
    if (!open || !id) return undefined;
    const controller = new AbortController();
    let active = true;
    setLoad({ id, status: 'loading', data: null, error: null });
    getHotel(id, { signal: controller.signal })
      .then((data) => active && setLoad({ id, status: 'ready', data, error: null }))
      .catch((error) => {
        if (active && error?.name !== 'AbortError') setLoad({ id, status: 'error', data: null, error: error.message });
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [open, id]);

  useEffect(() => {
    if (!open) return undefined;
    openerRef.current = document.activeElement;
    dialogRef.current?.focus();
    const onKey = (event) => {
      if (event.key === 'Escape') closeHotelDetails();
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      openerRef.current?.focus?.();
    };
  }, [open]);

  if (!open) return null;

  const current = load.id === id ? load : { status: 'loading', data: null, error: null };
  const h = current.status === 'ready' ? current.data : null;
  const stay = pkg && id ? findStay(pkg, id, stayId) : null;
  const sd = stay?.display_details ?? {};
  const name = h?.name ?? stay?.name ?? 'Hotel';

  return (
    <>
      <div className="attraction-details__backdrop" aria-hidden="true" onClick={closeHotelDetails} />
      <aside
        ref={dialogRef}
        className="attraction-details hotel-details"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <header className="attraction-details__header">
          <div className="attraction-details__titles">
            <h2 id={titleId} className="attraction-details__title">{name}</h2>
            {h && (
              <p className="attraction-details__sub">
                {[h.area, h.city, h.country].filter(Boolean).join(' · ')}
              </p>
            )}
          </div>
          <button type="button" className="attraction-details__close" aria-label="Close" onClick={closeHotelDetails}>
            ✕
          </button>
        </header>

        <div className="attraction-details__body">
          {current.status === 'loading' && <p className="attraction-details__status" role="status">Loading…</p>}
          {current.status === 'error' && <p className="attraction-details__error" role="alert">{current.error}</p>}

          {h && (
            <>
              {h.image_url && brokenImage !== id ? (
                <figure className="attraction-details__figure">
                  <img
                    className="attraction-details__photo"
                    src={h.image_url}
                    alt={`Sample room photo for ${h.name}`}
                    loading="lazy"
                    onError={() => setBrokenImage(id)}
                  />
                  <figcaption className="attraction-details__credit">
                    {h.image_is_sample && <strong>Sample room photo. </strong>}
                    {h.image_credit}
                  </figcaption>
                </figure>
              ) : (
                <div className="attraction-details__fallback">
                  <span>Hotel</span>
                  <strong>{h.name}</strong>
                </div>
              )}

              <p className="attraction-details__meta">
                {[
                  h.stars ? `${h.stars}★` : null,
                  h.rating ? `rated ${h.rating}/10` : null,
                  h.family_friendly ? 'family-friendly' : null,
                ]
                  .filter(Boolean)
                  .join(' · ')}
              </p>

              {stay && (
                <section className="attraction-details__section" aria-label="Your stay">
                  <h3>Your stay</h3>
                  <dl className="attraction-details__list">
                    <dt>Dates</dt>
                    <dd>
                      {formatDay(stay.start)} – {formatDay(stay.end)}
                      {sd.nights ? ` (${plural(sd.nights, 'night')})` : ''}
                    </dd>
                    <dt>Room</dt>
                    <dd>
                      {sd.room?.name ?? 'Room'} × {sd.rooms}
                    </dd>
                    <dt>Price</dt>
                    <dd>{formatINR(stay.price_inr)} for the stay</dd>
                  </dl>
                </section>
              )}

              <section className="attraction-details__section" aria-label="Hotel policies">
                <h3>Check-in and check-out</h3>
                <dl className="attraction-details__list">
                  <dt>Check-in</dt>
                  <dd>from {h.check_in_from ?? '-'}</dd>
                  <dt>Check-out</dt>
                  <dd>by {h.check_out_until ?? '-'}</dd>
                </dl>
              </section>

              {h.rooms.length > 0 && (
                <section className="attraction-details__section" aria-label="Rooms">
                  <h3>Rooms</h3>
                  <dl className="attraction-details__list">
                    {h.rooms.map((r) => (
                      <div key={r.room_id} className="hotel-details__room">
                        <dt>{r.name ?? humanize(r.room_type)}</dt>
                        <dd>
                          {formatINR(r.price_per_night_inr)} / night · up to {plural(r.max_adults, 'adult')}
                          {r.max_children ? `, ${plural(r.max_children, 'child', 'children')}` : ''}
                          {r.refundable ? ' · refundable' : ''}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </section>
              )}

              <section className="attraction-details__section" aria-label="Map">
                <a className="attraction-details__map" href={h.maps_url} target="_blank" rel="noopener noreferrer">
                  View on Google Maps
                </a>
                <p className="attraction-details__note">A map search for this hotel's name, area and city.</p>
              </section>
            </>
          )}
        </div>
      </aside>
    </>
  );
}
