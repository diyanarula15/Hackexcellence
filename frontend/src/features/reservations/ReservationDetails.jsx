import { formatDate, formatINR, humanize, plural } from '../format.js';

function date(value) {
  if (!value) return 'Date not provided';
  return value.length > 10 ? `${formatDate(value.slice(0, 10))} · ${value.slice(11)}` : formatDate(value);
}

function BookingInfo({ booking }) {
  if (!booking || typeof booking !== 'object') return null;
  return (
    <dl className="reservation-item__booking">
      {Object.entries(booking).map(([key, value]) => (
        <div key={key}>
          <dt>{humanize(key)}</dt>
          <dd>{typeof value === 'object' ? JSON.stringify(value) : String(value ?? '-')}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Displays the exact stored trip document; it does not enrich items from the current catalog. */
export default function ReservationDetails({ reservation }) {
  const trip = reservation?.trip;
  if (!trip) return <p className="reservation__error">The reservation response did not include its itinerary.</p>;
  const items = Array.isArray(trip.items) ? trip.items : [];
  const travelers = trip.traveler;
  const travelerSummary = travelers
    ? [travelers.name, travelers.adults != null && plural(travelers.adults, 'adult'), travelers.children != null && plural(travelers.children, 'child', 'children'), travelers.child_ages?.length && `ages ${travelers.child_ages.join(', ')}`]
        .filter(Boolean).join(' · ')
    : 'Traveler details unavailable';

  return (
    <section className="reservation-details" aria-labelledby="reservation-trip-title">
      <header className="reservation-details__head">
        <div>
          <p className="eyebrow">Confirmed itinerary</p>
          <h3 id="reservation-trip-title">{trip.country ? `Trip to ${trip.country}` : 'Your trip'}</h3>
          <p>{formatDate(trip.start_date)} – {formatDate(trip.end_date)}</p>
        </div>
        <p className="reservation-details__total">{formatINR(trip.total_inr)}</p>
      </header>
      <dl className="reservation-details__facts">
        <div><dt>Status</dt><dd>{trip.status ?? reservation.status ?? 'BOOKED'}</dd></div>
        <div><dt>Trip ID</dt><dd className="mono">{trip.trip_id ?? reservation.package_id}</dd></div>
        <div><dt>Travelers</dt><dd>{travelerSummary}</dd></div>
        {travelers?.home_airport && <div><dt>Home airport</dt><dd>{travelers.home_airport}</dd></div>}
        {trip.booking?.reference && <div><dt>Reference</dt><dd className="mono">{trip.booking.reference}</dd></div>}
        {reservation.confirmed_at && <div><dt>Confirmed</dt><dd>{reservation.confirmed_at}</dd></div>}
      </dl>
      <ol className="reservation-items">
        {items.map((item, index) => (
          <li className="reservation-item" key={item.item_id ?? `${item.type}-${index}`}>
            <div className="reservation-item__top">
              <span className="reservation-item__type">{humanize(item.type ?? 'item')}</span>
              <span>{formatINR(item.price_inr)}</span>
            </div>
            <h4>{item.name ?? humanize(item.type ?? 'Trip item')}</h4>
            <p className="reservation-item__meta">
              {[item.city, item.start && date(item.start), item.end && `until ${date(item.end)}`, item.quantity != null && `× ${item.quantity}`, item.status].filter(Boolean).join(' · ')}
            </p>
            {item.catalog_id && <p className="mono reservation-item__id">{item.catalog_id}{item.room_id ? ` · ${item.room_id}` : ''}</p>}
            <BookingInfo booking={item.booking} />
          </li>
        ))}
      </ol>
      {!items.length && <p>This reservation contains no itinerary items.</p>}
    </section>
  );
}
