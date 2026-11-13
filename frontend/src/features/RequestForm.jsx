// Metadata gates incomplete searches; the backend validates every submitted request.

import { useState } from 'react';
import { useStore } from '../state/store.js';
import { applyParsedTrip, bookingStore, generatePackage, loadMeta, setField } from '../state/bookingStore.js';
import { budgetHint } from './format.js';
import PlaneButton from './PlaneButton.jsx';
import DateField from './DateField.jsx';
import ExploreDatesButton from './price-landscape/ExploreDatesButton.jsx';
import QuickRequest, { QuickRequestToggle } from './quick-request/QuickRequest.jsx';
import { formReadiness } from './quick-request/formReadiness.js';

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
 * @param {{ name: string, label: string, describedBy?: string, hint?: string,
 *           children: (props: object) => JSX.Element }} props
 *   hint - optional micro-caption shown under the control (hidden while the field is invalid).
 */
function Field({ name, label, describedBy, hint, children }) {
  const invalid = Boolean(describedBy);
  return (
    <div className={`field field--${name}${invalid ? ' field--invalid' : ''}`}>
      <label className="field__label" htmlFor={`trip-${name}`}>
        {label}
      </label>
      {children({
        id: `trip-${name}`,
        name,
        className: 'field__control',
        'aria-invalid': invalid,
        'aria-describedby': describedBy ?? (hint ? `trip-${name}-hint` : undefined),
      })}
      {hint && !invalid && (
        <p className="field__hint" id={`trip-${name}-hint`}>
          {hint}
        </p>
      )}
    </div>
  );
}

/** @returns {JSX.Element} */
export default function RequestForm() {
  const meta = useStore(bookingStore, (s) => s.meta);
  const form = useStore(bookingStore, (s) => s.form);
  const submit = useStore(bookingStore, (s) => s.submit);
  const naturalLanguage = useStore(bookingStore, (s) => s.naturalLanguage);

  const [quickOpen, setQuickOpen] = useState(false);
  const options = meta.data;
  const countries = options?.countries ?? [];
  const loading = submit.status === 'loading';
  const readiness = formReadiness(form, options, naturalLanguage?.unresolved ?? []);
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
        if (readiness.length) return;
        generatePackage();
      }}
    >
      <div className="planner__head">
        <h2 className="planner__title" id="planner-title">
          Build my holiday
        </h2>
        <div className="planner__head-actions">
          <QuickRequestToggle open={quickOpen} onToggle={() => setQuickOpen((v) => !v)} />
          <ExploreDatesButton />
        </div>
        {meta.status === 'error' && (
          <p className="planner__meta-error" role="alert">
            Could not load cities and countries.{' '}
            <button type="button" className="link-button" onClick={loadMeta}>
              Retry
            </button>
          </p>
        )}
      </div>

      <QuickRequest form={form} onApply={applyParsedTrip} disabled={loading}
        departures={options?.departure_airports ?? []} open={quickOpen} onOpenChange={setQuickOpen} />
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
            <DateField
              {...props}
              value={form.start_date}
              onChange={(value) => setField('start_date', value)}
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
          {(props) => <input {...props} {...bind('child_ages')} type="text" placeholder="Optional (e.g. 6, 9)" />}
        </Field>

        <Field
          name="budget"
          label="Budget (₹)"
          describedBy={describedBy.budget}
          hint={submit.status === 'invalid' ? undefined : budgetHint(form)}
        >
          {(props) => <input {...props} {...bind('budget')} type="text" inputMode="numeric" placeholder="3,50,000" />}
        </Field>

        <PlaneButton
          type="submit"
          className="planner__submit"
          label="Find Holidays"
          disabled={readiness.length > 0}
          busyLabel="Choreographing…"
          busy={loading}
          onClick={() => window.dispatchEvent(new CustomEvent('scene:flyby'))}
        />
      </div>

      <div className="planner__status" aria-live="polite">
        {(naturalLanguage?.active || FIELD_ORDER.filter((name) => name !== 'child_ages').every((name) => form[name] !== '')) && readiness.length > 0 && <div><p>Complete or correct these details before searching:</p><ul>{readiness.map((message) => <li key={message}>{message}</li>)}</ul></div>}
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
