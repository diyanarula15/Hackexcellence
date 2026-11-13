// The backend returns events in itinerary order; this component only formats them.

import { openChange, openDelayRescue, previewRemoveAttraction } from '../state/bookingStore.js';
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

/** The change/remove buttons for one event, or null when the event cannot be changed. */
function EventActions({ event }) {
  const id = event.item_id;
  const open = (target) => (e) => openChange(target, e.currentTarget);
  const button = (label, kind, extra, target) => (
    <button
      type="button"
      className="btn btn--small change-trigger"
      data-change-kind={kind}
      {...extra}
      aria-label={`${label}: ${event.name}`}
      onClick={open({ kind, label: `${label}: ${event.name}`, ...target })}
    >
      {label}
    </button>
  );
  switch (event.kind) {
    case 'FLIGHT':
      return id === 'flight:return'
        ? button('Change flight', 'return_flight', {}, {})
        : button('Change flight', 'arrival_flight', {}, {});
    case 'CHECK_IN':
      return button('Change hotel', 'hotel', { 'data-stay-id': id }, { stay_id: id });
    case 'TRANSFER': {
      const kind = id === 'leg:arrival' || id === 'leg:departure' ? 'airport_transfer' : 'intercity_transfer';
      return button('Change transfer', kind, { 'data-item-id': id }, { item_id: id });
    }
    case 'ATTRACTION':
      return (
        <button
          type="button"
          className="btn btn--small change-trigger"
          data-remove-item={id}
          aria-label={`Remove: ${event.name}`}
          onClick={(e) => previewRemoveAttraction(id, e.currentTarget, `Remove: ${event.name}`)}
        >
          Remove
        </button>
      );
    default:
      return null;
  }
}

/** Opens the delay-resilience panel for the arrival flight. Read-only for booked packages. */
function DelayButton({ event }) {
  return (
    <button
      type="button"
      className="btn btn--small change-trigger delay-trigger"
      aria-label={`Delay resilience: ${event.name}`}
      onClick={(e) => openDelayRescue(e.currentTarget)}
    >
      Delay resilience
    </button>
  );
}

function Event({ event, day, editable }) {
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
        {editable && <EventActions event={event} />}
        {event.item_id === 'flight:arrival' && <DelayButton event={event} />}
      </div>
      <div className="event__price">{price}</div>
    </li>
  );
}

/**
 * @param {{ editable?: boolean, days: Array<{ date: string, day_number: number, day_type: string, city: string,
 *   from_city: string|null, overnight: {item_id: string, name: string}|null, events: object[] }> }} props
 * @returns {JSX.Element}
 */
export default function DayTimeline({ days, editable = false }) {
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
              <Event key={`${event.kind}:${event.item_id}`} event={event} day={day.date} editable={editable} />
            ))}
          </ol>
          {editable && day.day_type !== 'DEPARTURE' && (
            <button
              type="button"
              className="btn btn--small change-trigger change-trigger--add"
              data-change-kind="attraction"
              data-date={day.date}
              onClick={(e) =>
                openChange({ kind: 'attraction', date: day.date, label: `Add attraction on ${formatDay(day.date)}` }, e.currentTarget)
              }
            >
              Add attraction
            </button>
          )}
        </li>
      ))}
    </ol>
  );
}
