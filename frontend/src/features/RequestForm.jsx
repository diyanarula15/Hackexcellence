// Validation is handled by the backend; this form displays its field-specific errors.

import { useStore } from '../state/store.js';
import { bookingStore, generatePackage, loadMeta, setField } from '../state/bookingStore.js';

const FIELD_ORDER = ['departure', 'country', 'start_date', 'nights', 'adults', 'child_ages', 'budget'];

/** The <select> value for a stored country (name or code, any case) → the option's value (name). */
function countryValue(countries, value) {
  const wanted = String(value ?? '').trim().toLowerCase();
  if (!wanted) return '';
  const hit = countries.find((c) => c.name.toLowerCase() === wanted || c.code.toLowerCase() === wanted);
  return hit ? hit.name : value;
}

/**
 * Backend field errors → one list of unique messages, plus which messages describe which field
 * (one message, e.g. "start date plus nights…", can belong to two fields).
 * @param {Record<string, string[]>} fieldErrors
 */
function collectMessages(fieldErrors) {
  const names = [...FIELD_ORDER, ...Object.keys(fieldErrors).filter((n) => !FIELD_ORDER.includes(n))];
  const messages = [];
  const describedBy = {};
  for (const name of names) {
    for (const text of fieldErrors[name] ?? []) {
      let message = messages.find((m) => m.text === text);
      if (!message) {
        message = { id: `trip-error-${messages.length}`, text };
        messages.push(message);
      }
      describedBy[name] = [describedBy[name], message.id].filter(Boolean).join(' ');
    }
  }
  return { messages, describedBy };
}

/**
 * @param {{ name: string, label: string, describedBy?: string,
 *           children: (props: object) => JSX.Element }} props
 */
function Field({ name, label, describedBy, children }) {
  const invalid = Boolean(describedBy);
  return (
    <div className={`field${invalid ? ' field--invalid' : ''}`}>
      <label className="field__label" htmlFor={`trip-${name}`}>
        {label}
      </label>
      {children({
        id: `trip-${name}`,
        name,
        className: 'field__control',
        'aria-invalid': invalid,
        'aria-describedby': describedBy,
      })}
    </div>
  );
}

/** @returns {JSX.Element} */
export default function RequestForm() {
  const meta = useStore(bookingStore, (s) => s.meta);
  const form = useStore(bookingStore, (s) => s.form);
  const submit = useStore(bookingStore, (s) => s.submit);

  const options = meta.data;
  const countries = options?.countries ?? [];
  const loading = submit.status === 'loading';
  const bind = (name) => ({ value: form[name], onChange: (e) => setField(name, e.target.value) });
  const { messages, describedBy } = collectMessages(submit.fieldErrors ?? {});

  return (
    <form
      className="planner"
      id="planner"
      noValidate
      aria-labelledby="planner-title"
      aria-busy={loading}
      onSubmit={(e) => {
        e.preventDefault();
        generatePackage();
      }}
    >
      <div className="planner__head">
        <h2 className="eyebrow" id="planner-title">
          Build my holiday
        </h2>
        {meta.status === 'error' && (
          <p className="planner__meta-error" role="alert">
            Could not load cities and countries.{' '}
            <button type="button" className="link-button" onClick={loadMeta}>
              Retry
            </button>
          </p>
        )}
      </div>

      <div className="planner__fields">
        <Field name="departure" label="From" describedBy={describedBy.departure}>
          {(props) => (
            <select {...props} {...bind('departure')}>
              <option value="">Departure city</option>
              {(options?.departure_airports ?? []).map((d) => (
                <option key={d.airport} value={d.airport}>
                  {d.city} ({d.airport})
                </option>
              ))}
            </select>
          )}
        </Field>

        <Field name="country" label="To" describedBy={describedBy.country}>
          {(props) => (
            <select
              {...props}
              value={countryValue(countries, form.country)}
              onChange={(e) => setField('country', e.target.value)}
            >
              <option value="">Country</option>
              {countries.map((c) => (
                <option key={c.code} value={c.name}>
                  {c.name}
                </option>
              ))}
            </select>
          )}
        </Field>

        <Field name="start_date" label="First day" describedBy={describedBy.start_date}>
          {(props) => (
            <input
              {...props}
              {...bind('start_date')}
              type="date"
              min={options?.allowed_dates.first_night}
              max={options?.allowed_dates.last_departure}
            />
          )}
        </Field>

        <Field name="nights" label="Nights" describedBy={describedBy.nights}>
          {(props) => (
            <input
              {...props}
              {...bind('nights')}
              type="number"
              inputMode="numeric"
              min={options?.nights.min}
              max={options?.nights.max}
              placeholder={options ? `${options.nights.min}–${options.nights.max}` : ''}
            />
          )}
        </Field>

        <Field name="adults" label="Adults" describedBy={describedBy.adults}>
          {(props) => <input {...props} {...bind('adults')} type="number" inputMode="numeric" min={1} placeholder="2" />}
        </Field>

        <Field name="child_ages" label="Children's ages" describedBy={describedBy.child_ages}>
          {(props) => <input {...props} {...bind('child_ages')} type="text" placeholder="e.g. 6, 9 · blank if none" />}
        </Field>

        <Field name="budget" label="Budget (₹)" describedBy={describedBy.budget}>
          {(props) => <input {...props} {...bind('budget')} type="text" inputMode="numeric" placeholder="3,50,000" />}
        </Field>

        <button type="submit" className="btn btn--primary planner__submit" disabled={loading}>
          {loading && <span className="spinner" aria-hidden="true" />}
          {loading ? 'Building…' : 'Build my holiday'}
        </button>
      </div>

      <div className="planner__status" aria-live="polite">
        {loading && <p>Choosing cities, flights, hotels, transfers and attractions…</p>}
        {submit.status === 'invalid' && (
          <>
            <p className="planner__alert">{submit.message}</p>
            <ul className="planner__errors">
              {messages.map(({ id, text }) => (
                <li key={id} id={id}>
                  {text}
                </li>
              ))}
            </ul>
          </>
        )}
        {submit.status === 'error' && (
          <p className="planner__alert" role="alert">
            {submit.message}{' '}
            <button type="button" className="link-button" onClick={generatePackage}>
              Try again
            </button>
          </p>
        )}
      </div>
    </form>
  );
}
