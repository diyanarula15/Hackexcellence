/**
 * features/package-options/PackageOptions.jsx - "pick your trip" (Phase 8B).
 *
 * After a search the traveler sees up to three complete holidays as cards. Every price, date and
 * summary is the backend's; this component only formats them. Nothing is saved until one card's
 * "Explore trip" succeeds, and then the store opens that saved package.
 */

import { useEffect, useId, useRef } from 'react';
import { createPortal } from 'react-dom';
import { useStore } from '../../state/store.js';
import { bookingStore, choosePackageOption, previewPackageOption, startNewSearch } from '../../state/bookingStore.js';
import DayTimeline from '../DayTimeline.jsx';
import { formatDate, formatDay, formatINR, formatTime, formatTravelers, plural } from '../format.js';
import './PackageOptions.css';

const PRICE_ROWS = [
  ['flights', 'Flights'],
  ['hotels', 'Hotels'],
  ['airport_transfers', 'Airport transfers'],
  ['intercity_transfers', 'Transfers between cities'],
  ['attractions', 'Attractions'],
];

const SKELETON_COUNT = 3;
const closePreview = () => previewPackageOption(null);

/** Minimal airliner silhouette, nose pointing right (same shape as PlaneButton). */
function PlaneIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M22 12c0 .8-1.2 1.4-2.6 1.4h-4.8l-4.2 6.6H8.2l2-6.6h-4l-1.7 2.2H3l.9-3.6L3 8.4h1.5l1.7 2.2h4l-2-6.6h2.2l4.2 6.6h4.8c1.4 0 2.6.6 2.6 1.4z" />
    </svg>
  );
}

/** Placeholder bars shown while the search runs. They carry no prices. */
function SkeletonCard({ index }) {
  const widths = ['40%', '70%', '55%', '85%', '60%'];
  return (
    <li className="package-options__item">
      <div className="option-card option-card--skeleton" aria-hidden="true" data-skeleton={index}>
        <span className="option-card__bar" style={{ width: '30%' }} />
        <span className="option-card__bar option-card__bar--title" style={{ width: '75%' }} />
        {widths.map((w) => (
          <span key={w} className="option-card__bar" style={{ width: w }} />
        ))}
      </div>
    </li>
  );
}

function Searching() {
  const titleId = useId();
  return (
    <section className="package-options" aria-labelledby={titleId} aria-busy="true">
      <header className="package-options__head">
        <p className="eyebrow">Pick your trip</p>
        <h2 id={titleId} className="package-options__title">Finding holiday options…</h2>
      </header>
      <ul className="package-options__grid package-options__grid--3">
        {Array.from({ length: SKELETON_COUNT }, (_, i) => (
          <SkeletonCard key={i} index={i} />
        ))}
      </ul>
    </section>
  );
}

/** "₹1,16,368 left of ₹3,50,000", or the overspend when the remaining amount is negative. */
function BudgetLine({ remaining, budget }) {
  if (!Number.isFinite(remaining)) return null;
  if (remaining < 0) return <p className="option-card__budget is-over">Over budget by {formatINR(-remaining)}</p>;
  return (
    <p className="option-card__budget">
      {formatINR(remaining)} left of {formatINR(budget)}
    </p>
  );
}

function OptionCard({ option, choosing, selecting }) {
  const titleId = useId();
  const { stats } = option;
  const statItems = [
    plural(stats.cities, 'city', 'cities'),
    plural(stats.city_changes, 'city change'),
    plural(stats.transfers, 'transfer'),
    plural(stats.attractions, 'attraction'),
    Number.isFinite(stats.avg_stars) ? `${stats.avg_stars.toFixed(1)}★ avg stars` : null,
  ].filter(Boolean);

  return (
    <article
      className={`option-card${selecting ? ' option-card--selecting' : ''}`}
      aria-labelledby={titleId}
      aria-busy={selecting || undefined}
    >
      {selecting && (
        <span className="option-card__flight" aria-hidden="true">
          <PlaneIcon className="option-card__plane" />
        </span>
      )}

      <header className="option-card__head">
        <p className="eyebrow">Option {option.rank}</p>
        {option.badges.length > 0 && (
          <ul className="option-card__badges" aria-label="Badges">
            {option.badges.map((badge) => (
              <li key={badge} className="option-card__badge">
                {badge}
              </li>
            ))}
          </ul>
        )}
      </header>

      <div className="option-card__price">
        <p className="eyebrow">Total</p>
        <p className="option-card__total">{formatINR(option.total_inr)}</p>
        <BudgetLine remaining={option.budget_remaining_inr} budget={option.budget_inr} />
      </div>

      <h3 id={titleId} className="option-card__title">
        {option.cities.join(' → ')}
      </h3>
      <p className="option-card__meta">
        {option.country} · {formatDate(option.start_date)} – {formatDate(option.end_date)} ·{' '}
        {plural(option.nights, 'night')}
      </p>
      <ul className="option-card__cities" aria-label="Stays by city">
        {option.city_nights.map((stay) => (
          <li key={`${stay.city}:${stay.nights}`} className="option-card__city">
            {stay.city} · {plural(stay.nights, 'night')}
          </li>
        ))}
      </ul>
      <p className="option-card__travelers">{formatTravelers(option.travelers)}</p>

      <dl className="option-card__facts">
        <dt>Flights</dt>
        <dd>{option.flights.summary}</dd>
        <dt>Stays</dt>
        <dd>{option.hotel_summary}</dd>
        <dt>Experiences</dt>
        <dd>{option.experience_summary}</dd>
      </dl>

      <ul className="option-card__stats" aria-label="Trip at a glance">
        {statItems.map((item) => (
          <li key={item} className="option-card__stat">
            {item}
          </li>
        ))}
      </ul>

      {option.differences.length > 0 && (
        <ul className="option-card__diffs" aria-label="How it differs from option 1">
          {option.differences.map((difference) => (
            <li key={difference} className="option-card__diff">
              {difference}
            </li>
          ))}
        </ul>
      )}

      <div className="option-card__actions">
        <button type="button" className="btn btn--small" onClick={() => previewPackageOption(option.option_id)}>
          View details
        </button>
        <button
          type="button"
          className="btn btn--small btn--primary"
          disabled={choosing}
          onClick={() => choosePackageOption(option.option_id)}
        >
          Explore trip
        </button>
      </div>
      {selecting && (
        <p className="option-card__status" role="status">
          Opening your trip…
        </p>
      )}
    </article>
  );
}

function FlightLine({ label, flight }) {
  if (!flight) return null;
  return (
    <li className="po-flight">
      <p className="po-flight__name">
        <span className="po-flight__label">{label}</span> {flight.airline} · {flight.flight_number}
      </p>
      <p className="po-flight__route">
        {flight.from} → {flight.to}
      </p>
      <p className="po-flight__times">
        Departs {formatDay(flight.depart)} {formatTime(flight.depart)} · arrives {formatDay(flight.arrive)}{' '}
        {formatTime(flight.arrive)}
      </p>
    </li>
  );
}

/** Keeps Tab and Shift+Tab inside the dialog. */
function trapTab(event, dialog) {
  const items = [...dialog.querySelectorAll('button, a[href]')].filter((el) => !el.disabled);
  if (!items.length) return;
  const first = items[0];
  const last = items[items.length - 1];
  const active = document.activeElement;
  if (event.shiftKey && (active === first || active === dialog)) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && active === last) {
    event.preventDefault();
    first.focus();
  }
}

/** The read-only preview of one option. Nothing here is saved until "Explore trip". */
function PreviewDialog({ option, choosing }) {
  const titleId = useId();
  const dialogRef = useRef(null);
  const openerRef = useRef(null);

  // Focus moves into the dialog; Escape closes it; focus returns to the opener on close.
  useEffect(() => {
    openerRef.current = document.activeElement;
    dialogRef.current?.focus();
    const onKey = (event) => {
      if (event.key === 'Escape') closePreview();
      else if (event.key === 'Tab' && dialogRef.current) trapTab(event, dialogRef.current);
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      openerRef.current?.focus?.();
    };
  }, []);

  const { preview } = option;
  const days = preview?.days ?? [];

  return createPortal(
    <>
      <div className="po-dialog__backdrop" aria-hidden="true" onClick={closePreview} />
      <section
        ref={dialogRef}
        className="po-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <header className="po-dialog__head">
          <div className="po-dialog__titles">
            <p className="po-dialog__preview">Preview · Not saved yet</p>
            <h2 id={titleId} className="po-dialog__title">
              Option {option.rank}: {option.cities.join(' → ')}
            </h2>
          </div>
          <button type="button" className="btn btn--small" onClick={closePreview}>
            Close
          </button>
        </header>

        <div className="po-dialog__body">
          {preview?.pricing && (
            <section className="po-section" aria-label="Price breakdown">
              <p className="eyebrow">Price breakdown</p>
              <dl className="po-rows">
                {PRICE_ROWS.map(([key, label]) => (
                  <div key={key} className="po-rows__row">
                    <dt>{label}</dt>
                    <dd>{formatINR(preview.pricing[key])}</dd>
                  </div>
                ))}
                <div className="po-rows__row po-rows__row--total">
                  <dt>Total</dt>
                  <dd>{formatINR(preview.pricing.total_inr)}</dd>
                </div>
              </dl>
            </section>
          )}

          {(option.flights.arrival || option.flights.return) && (
            <section className="po-section" aria-label="Flights">
              <p className="eyebrow">Flights</p>
              <ul className="po-flights">
                <FlightLine label="Out" flight={option.flights.arrival} />
                <FlightLine label="Home" flight={option.flights.return} />
              </ul>
            </section>
          )}

          {option.hotels.length > 0 && (
            <section className="po-section" aria-label="Hotel stays">
              <p className="eyebrow">Stays</p>
              <ul className="po-hotels">
                {option.hotels.map((hotel) => (
                  <li key={`${hotel.city}:${hotel.name}`} className="po-hotel">
                    <p className="po-hotel__name">{hotel.name}</p>
                    <p className="po-hotel__meta">
                      {hotel.city} · {hotel.stars}★ · {plural(hotel.nights, 'night')} · {hotel.room} × {hotel.rooms}
                    </p>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {days.length > 0 && (
            <section className="po-section" aria-label="Day by day">
              <p className="eyebrow">Day by day</p>
              <DayTimeline days={days} preview />
            </section>
          )}
        </div>

        <footer className="po-dialog__foot">
          <p className="po-dialog__note">Nothing is saved until you click “Explore trip”.</p>
          <button
            type="button"
            className="btn btn--primary"
            disabled={choosing}
            onClick={() => choosePackageOption(option.option_id)}
          >
            Explore trip
          </button>
        </footer>
      </section>
    </>,
    document.body,
  );
}

export default function PackageOptions() {
  const result = useStore(bookingStore, (s) => s.result);
  const pick = useStore(bookingStore, (s) => s.optionPick);
  const titleId = useId();

  if (result.status === 'SEARCHING') return <Searching />;
  if (result.status !== 'OPTIONS') return null;

  const { response } = result;
  const options = response.options ?? [];
  const preview = pick.previewId ? options.find((o) => o.option_id === pick.previewId) : null;
  const choosing = Boolean(pick.selectingId);

  return (
    <section className="package-options" aria-labelledby={titleId}>
      <header className="package-options__head">
        <p className="eyebrow">Pick your trip</p>
        <h2 id={titleId} className="package-options__title">
          {response.headline}
        </h2>
        <p className="package-options__subline">{response.subline}</p>
        {response.note && <p className="package-options__note">{response.note}</p>}
      </header>

      {pick.error && (
        <div className="package-options__error" role="alert">
          <p>{pick.error}</p>
          <button type="button" className="btn btn--small" onClick={() => startNewSearch()}>
            Search again
          </button>
        </div>
      )}

      <ul className={`package-options__grid package-options__grid--${Math.min(options.length, 3)}`}>
        {options.map((option) => (
          <li key={option.option_id} className="package-options__item">
            <OptionCard
              option={option}
              choosing={choosing}
              selecting={pick.selectingId === option.option_id}
            />
          </li>
        ))}
      </ul>

      <div className="package-options__footer">
        <button type="button" className="package-options__link" onClick={() => startNewSearch()}>
          Search a new trip
        </button>
      </div>

      {preview && <PreviewDialog key={preview.option_id} option={preview} choosing={choosing} />}
    </section>
  );
}
