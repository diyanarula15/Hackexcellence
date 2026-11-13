// Metadata gates incomplete searches; the backend validates every submitted request.

import { useState } from 'react';
import { useStore } from '../state/store.js';
import { applyParsedTrip, bookingStore, generatePackage, loadMeta, setField } from '../state/bookingStore.js';
import { budgetHint } from './format.js';
import PlaneButton from './PlaneButton.jsx';
import DateField from './DateField.jsx';
import ExploreDatesButton from './price-landscape/ExploreDatesButton.jsx';
import QuickRequest, { QuickRequestToggle } from './quick-request/QuickRequest.jsx';
import { fieldIssues, latestStartDate } from './quick-request/formReadiness.js';

const FIELD_ORDER = ['departure', 'country', 'start_date', 'nights', 'adults', 'child_ages', 'budget'];

/** The <select> value for a stored country (name or code, any case) → the option's value (name). */
function countryValue(countries, value) {
  const wanted = String(value ?? '').trim().toLowerCase();
  if (!wanted) return '';
  const hit = countries.find((c) => c.name.toLowerCase() === wanted || c.code.toLowerCase() === wanted);
  return hit ? hit.name : value;
}

/**
 * The message to show on each field: the backend's (after a search) wins, else the form's own
 * check. Backend errors for names that are not form fields are returned as `other`.
 * @param {Record<string, string[]>} fieldErrors   from the last search (422)
 * @param {{ field: string | null, text: string }[]} clientIssues   shown only when `showClient`
 */
function errorsByField(fieldErrors, clientIssues, showClient) {
  const errors = {};
  const other = [];
  for (const [name, texts] of Object.entries(fieldErrors)) {
    if (!texts?.length) continue;
    if (FIELD_ORDER.includes(name)) errors[name] = texts[0];
    else other.push(...texts);
  }
  if (showClient) {
    for (const { field, text } of clientIssues) {
      if (field && !errors[field]) errors[field] = text;
    }
  }
  return { errors, other: [...new Set(other)] };
}

/**
 * @param {{ name: string, label: string, error?: string, hint?: string,
 *           children: (props: object) => JSX.Element }} props
 *   error - what is wrong with this field, shown right under it.
 *   hint - optional micro-caption shown under the control (hidden while the field is invalid).
 */
function Field({ name, label, error, hint, children }) {
  const invalid = Boolean(error);
  const errorId = `trip-${name}-error`;
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
        'aria-describedby': invalid ? errorId : hint ? `trip-${name}-hint` : undefined,
      })}
      {invalid ? (
        <p className="field__error" id={errorId}>
          {error}
        </p>
      ) : (
        hint && (
          <p className="field__hint" id={`trip-${name}-hint`}>
            {hint}
          </p>
        )
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
  const issues = fieldIssues(form, options, naturalLanguage?.unresolved ?? []);
  const blocked = issues.length > 0;
  // The form's own checks show once every required field has a value (or after a quick request),
  // so nobody is told off while still typing.
  const showClient =
    Boolean(naturalLanguage?.active) || FIELD_ORDER.filter((name) => name !== 'child_ages').every((name) => form[name] !== '');
  const bind = (name) => ({ value: form[name], onChange: (e) => setField(name, e.target.value) });
  const { errors, other } = errorsByField(submit.status === 'invalid' ? (submit.fieldErrors ?? {}) : {}, issues, showClient);
  const unplaced = showClient ? issues.filter((issue) => !issue.field).map((issue) => issue.text) : [];

  return (
    <form
      className="planner"
      id="planner"
      noValidate
      aria-labelledby="planner-title"
      aria-busy={loading}
      onSubmit={(e) => {
        e.preventDefault();
        if (blocked) return;
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
      <div className={`planner__fields${Object.keys(errors).length ? ' planner__fields--errors' : ''}`}>
        <Field name="departure" label="From" error={errors.departure}>
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

        <Field name="country" label="To" error={errors.country}>
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

        <Field name="start_date" label="First day" error={errors.start_date}>
          {(props) => (
            <DateField
              {...props}
              value={form.start_date}
              onChange={(value) => setField('start_date', value)}
              min={options?.allowed_dates.first_night}
              max={latestStartDate(options, form.nights)}
            />
          )}
        </Field>

        <Field name="nights" label="Nights" error={errors.nights}>
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

        <Field name="adults" label="Adults" error={errors.adults}>
          {(props) => <input {...props} {...bind('adults')} type="number" inputMode="numeric" min={1} placeholder="2" />}
        </Field>

        <Field name="child_ages" label="Children's ages" error={errors.child_ages}>
          {(props) => <input {...props} {...bind('child_ages')} type="text" placeholder="Optional (e.g. 6, 9)" />}
        </Field>

        <Field
          name="budget"
          label="Budget (₹)"
          error={errors.budget}
          hint={submit.status === 'invalid' ? undefined : budgetHint(form)}
        >
          {(props) => <input {...props} {...bind('budget')} type="text" inputMode="numeric" placeholder="3,50,000" />}
        </Field>

        <PlaneButton
          type="submit"
          className="planner__submit"
          label="Find Holidays"
          disabled={blocked}
          busyLabel="Choreographing…"
          busy={loading}
          onClick={() => window.dispatchEvent(new CustomEvent('scene:flyby'))}
        />
      </div>

      <div className="planner__status" aria-live="polite">
        {submit.status !== 'invalid' && showClient && blocked && (
          <p>{unplaced.length ? unplaced.join(' ') : 'Fix the highlighted fields to search.'}</p>
        )}
        {loading && <p>Choosing cities, flights, hotels, transfers and attractions…</p>}
        {submit.status === 'invalid' && (
          <>
            <p className="planner__alert">{submit.message}</p>
            {other.length > 0 && (
              <ul className="planner__errors">
                {other.map((text) => (
                  <li key={text}>{text}</li>
                ))}
              </ul>
            )}
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
