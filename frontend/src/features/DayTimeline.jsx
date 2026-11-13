// The backend returns events in itinerary order; this component only formats them.

import { formatDay, formatDuration, formatINR, formatTime, humanize, plural } from './format.js';

const DAY_TITLE = {
  ARRIVAL: (day) => `Arrive in ${day.city}`,
  FULL_DAY: (day) => day.city,
  CITY_CHANGE: (day) => `${day.from_city} → ${day.city}`,
  DEPARTURE: (day) => `Fly home from ${day.city}`,
};

const TAG = { FLIGHT: 'Flight', TRANSFER: 'Transfer', CHECK_IN: 'Hotel', CHECK_OUT: 'Hotel', ATTRACTION: 'Visit' };

/** Local time, plus the date when it is not the day being shown (e.g. the overnight flight out). */
function LocalTime({ iso, day }) {
  return (
    <>
      {formatTime(iso)}
      {iso.slice(0, 10) !== day && <small>{formatDay(iso)}</small>}
    </>
  );
}

// Returns the time, title, and details shown for an event.
function describe(event, day) {
  const d = event.display_details ?? {};
  switch (event.kind) {
    case 'FLIGHT':
      return [
        <LocalTime iso={event.start} day={day} />,
        `${d.flight_number} · ${d.from.code} → ${d.to.code}`,
        [
          d.airline,
          `departs ${formatDay(event.start)} ${formatTime(event.start)} ${d.from.city} time`,
          `lands ${formatDay(event.end)} ${formatTime(event.end)} ${d.to.city} time`,
          formatDuration(d.duration_minutes),
          plural(event.quantity, 'seat'),
        ]
          .filter(Boolean)
          .join(' · '),
      ];
    case 'TRANSFER':
      return [
        <LocalTime iso={event.start} day={day} />,
        event.name,
        [
          humanize(d.mode),
          `${d.from_point} → ${d.to_point}`,
          `${formatDuration(d.duration_minutes)}, arrives ${formatTime(event.end)}`,
          plural(event.quantity, d.unit === 'vehicles' ? 'vehicle' : 'ticket'),
        ].join(' · '),
      ];
    // Stays are booked by date, so hotel rows carry no clock time: the hotel's check-in/check-out
    // hours are policies, and in the time column they would read as out-of-order times.
    case 'CHECK_IN':
      return [
        '',
        `Check in · ${event.name}`,
        [
          d.check_in_from ? `check-in from ${d.check_in_from}` : null,
          d.stars ? `${d.stars}★` : null,
          d.area,
          `${d.room?.name ?? 'Room'} × ${d.rooms}`,
          `${plural(d.nights, 'night')}, ${formatDay(event.start)} – ${formatDay(event.end)}`,
        ]
          .filter(Boolean)
          .join(' · '),
      ];
    case 'CHECK_OUT':
      return ['', `Check out · ${event.name}`, d.check_out_until ? `check-out by ${d.check_out_until}` : ''];
    case 'ATTRACTION':
      return [
        `${formatTime(event.start)}–${formatTime(event.end)}`,
        event.name,
        [humanize(d.category), formatDuration(d.visit_minutes), plural(event.quantity, 'ticket')]
          .filter(Boolean)
          .join(' · '),
      ];
    default:
      return [formatTime(event.start), event.name, ''];
  }
}

function Event({ event, day }) {
  const [time, title, detail] = describe(event, day);
  const price = event.price_inr == null ? '' : event.price_inr === 0 ? 'Free' : formatINR(event.price_inr);
  return (
    <li className={`event event--${event.kind.toLowerCase()}`}>
      <div className="event__time">{time}</div>
      <div className="event__body">
        <p className="event__name">
          <span className="event__tag">{TAG[event.kind] ?? event.type}</span>
          {title}
        </p>
        {detail && <p className="event__detail">{detail}</p>}
      </div>
      <div className="event__price">{price}</div>
    </li>
  );
}

/**
 * @param {{ days: Array<{ date: string, day_number: number, day_type: string, city: string,
 *   from_city: string|null, overnight: {item_id: string, name: string}|null, events: object[] }> }} props
 * @returns {JSX.Element}
 */
export default function DayTimeline({ days }) {
  return (
    <ol className="days">
      {days.map((day) => (
        <li key={day.date} className="day">
          <header className="day__header">
            <span className="day__number">Day {day.day_number}</span>
            <h4 className="day__title">
              {formatDay(day.date)} · {DAY_TITLE[day.day_type]?.(day) ?? day.city}
            </h4>
            {day.overnight && <span className="day__night">Night at {day.overnight.name}</span>}
          </header>
          <ol className="events">
            {day.events.map((event) => (
              <Event key={`${event.kind}:${event.item_id}`} event={event} day={day.date} />
            ))}
          </ol>
        </li>
      ))}
    </ol>
  );
}
