import { routeActions, routeErrors } from './routeDraft.js';
import './EditRoute.css';

const cityId = (stop) => typeof stop === 'string' ? stop : stop?.city_id;
const nightsOf = (stop) => typeof stop === 'object' ? stop.nights : undefined;

function cityName(id, options) {
  return options?.cities?.find((city) => city.city_id === id)?.name ?? id;
}

/** Local route editor. All structural choices and feasibility explanations come from routeDraft. */
export default function EditRoute({ options, draft = [], focusedCity, onFocusCity, onDraftChange, disabled = false }) {
  const stops = Array.isArray(draft) ? draft : [];
  const errors = routeErrors(stops, options) ?? [];
  const actions = routeActions(stops, focusedCity, options) ?? [];
  const totalNights = stops.reduce((sum, stop) => sum + (Number(nightsOf(stop)) || 0), 0);
  const expectedNights = options?.total_nights;
  const active = stops.find((stop) => cityId(stop) === focusedCity);
  const minNights = Number(options?.min_nights_per_city) || 1;

  const setNights = (index, value) => {
    const nights = Number(value);
    if (!Number.isInteger(nights) || nights < minNights) return;
    onDraftChange(stops.map((stop, i) => i === index ? { ...stop, nights } : stop));
  };

  return (
    <section className="atlas-edit-route" aria-labelledby="atlas-edit-route-title">
      <header className="atlas-edit-route__header">
        <div>
          <p className="eyebrow">Your route</p>
          <h2 id="atlas-edit-route-title">Edit Route</h2>
          <p className="atlas-edit-route__focus" aria-live="polite">
            {focusedCity ? cityName(focusedCity, options) : 'Select a city on the map'}
          </p>
        </div>
        <p className="atlas-edit-route__current">
          {active
            ? `Current stop · ${nightsOf(active) ?? '-'} ${Number(nightsOf(active)) === 1 ? 'night' : 'nights'}`
            : focusedCity ? 'Not in holiday' : 'Current route'}
        </p>
      </header>

      <ol className="atlas-edit-route__stops" aria-label="Draft route stops">
        {stops.map((stop, index) => {
          const id = cityId(stop);
          const name = cityName(id, options);
          const nights = nightsOf(stop);
          return (
            <li key={`${id}-${index}`} className={`atlas-edit-route__stop${id === focusedCity ? ' is-focused' : ''}`}>
              <button
                type="button"
                className="atlas-edit-route__city"
                aria-pressed={id === focusedCity}
                disabled={disabled}
                onClick={() => onFocusCity?.(id)}
              >
                <span className="atlas-edit-route__index">{index + 1}</span>
                <span>{name}</span>
              </button>
              <div className="atlas-edit-route__nights" aria-label={`${name} nights`}>
                <button type="button" className="btn btn--small atlas-edit-route__step" aria-label={`Decrease nights in ${name}`} disabled={disabled || Number(nights) <= minNights} onClick={() => setNights(index, Number(nights) - 1)}>−</button>
                <label>
                  <span className="atlas-sr-only">Nights in {name}</span>
                  <input type="number" min={minNights} step="1" value={nights ?? ''} disabled={disabled} onChange={(event) => setNights(index, event.target.value)} />
                </label>
                <button type="button" className="btn btn--small atlas-edit-route__step" aria-label={`Increase nights in ${name}`} disabled={disabled} onClick={() => setNights(index, Number(nights) + 1)}>+</button>
              </div>
            </li>
          );
        })}
      </ol>

      <p className="atlas-edit-route__total" aria-live="polite">
        Total nights <strong>{totalNights}/{expectedNights ?? '-'}</strong>
      </p>

      {errors.length > 0 && (
        <ul className="atlas-edit-route__errors" aria-label="Route issues">
          {errors.map((error, index) => <li key={`${error}-${index}`}>{error}</li>)}
        </ul>
      )}

      {actions.length > 0 && (
        <ul className="atlas-edit-route__actions" aria-label="Route actions">
          {actions.map((action, index) => (
            <li key={`${action.id}-${index}`}>
              <button
                type="button"
                className="btn btn--small"
                disabled={disabled || !action.route}
                title={action.reason || undefined}
                onClick={() => action.route && onDraftChange(action.route)}
              >
                {action.label}
              </button>
              {action.reason && <span className="atlas-edit-route__reason">{action.reason}</span>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
