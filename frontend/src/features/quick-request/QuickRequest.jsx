import { useEffect, useRef, useState } from 'react';
import { parseQuickRequest } from '../../services/quickRequestApi.js';
import { QUICK_FIELDS, applyableFields, isFieldBlocked } from './applyableFields.js';
import './QuickRequest.css';

const FIELDS = QUICK_FIELDS;
const EMPTY_FIELDS = Object.fromEntries(FIELDS.map(([key]) => [key, null]));
const COUNT_SHOWN_AFTER = 1600;

function displayValue(field, value, departures) {
  if (value == null) return 'Not understood yet';
  if (field === 'child_ages') return value.length ? `${value.join(', ')} years` : 'No children';
  if (field === 'budget') return `₹${Number(value).toLocaleString('en-IN')}`;
  if (field === 'start_date') return new Date(`${value}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
  if (field === 'departure') {
    const hit = departures.find((d) => d.airport === value);
    return hit ? `${hit.city} (${hit.airport})` : value;
  }
  if (field === 'nights') return `${value} ${Number(value) === 1 ? 'night' : 'nights'}`;
  if (field === 'adults') return `${value} ${Number(value) === 1 ? 'adult' : 'adults'}`;
  return String(value);
}

/** Quiet pill that opens the describe-your-trip section. */
export function QuickRequestToggle({ open, onToggle }) {
  return (
    <button type="button" className="btn quick-request__toggle" aria-expanded={open}
      aria-controls="quick-request-body" onClick={onToggle}>
      <span aria-hidden="true">✎</span> Describe your trip
    </button>
  );
}

/** Controlled when `open`/`onOpenChange` are passed (the form puts the toggle in its header row);
 *  otherwise it renders its own toggle. */
export default function QuickRequest({ form, onApply, disabled = false, departures = [], open: openProp, onOpenChange }) {
  const [ownOpen, setOwnOpen] = useState(false);
  const controlled = openProp !== undefined;
  const open = controlled ? openProp : ownOpen;
  const setOpen = controlled ? onOpenChange : setOwnOpen;
  const [text, setText] = useState('');
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [replaceExisting, setReplaceExisting] = useState(false);
  const [applyMessage, setApplyMessage] = useState('');
  const requestRef = useRef(null);
  const baseFormRef = useRef(null);
  const sequence = useRef(0);
  const mounted = useRef(true);
  const busyRef = useRef(false);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      sequence.current += 1;
      requestRef.current?.abort();
    };
  }, []);

  function changeText(value) {
    setText(value);
    sequence.current += 1;
    requestRef.current?.abort();
    requestRef.current = null;
    busyRef.current = false;
    setLoading(false);
    setResult(null);
    setError('');
    setApplyMessage('');
  }

  async function readRequest() {
    if (busyRef.current || disabled || !text.trim() || text.length > 2000) return;
    busyRef.current = true;
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    baseFormRef.current = { ...EMPTY_FIELDS, ...form };
    const requestId = ++sequence.current;
    setLoading(true);
    setError('');
    setResult(null);
    setApplyMessage('');
    try {
      const parsed = await parseQuickRequest(text.trim(), { signal: controller.signal });
      if (mounted.current && sequence.current === requestId) setResult(parsed);
    } catch (err) {
      if (mounted.current && sequence.current === requestId && err?.name !== 'AbortError') {
        setError(err?.message || 'Could not read that request. Please try again.');
      }
    } finally {
      if (mounted.current && sequence.current === requestId) {
        busyRef.current = false;
        setLoading(false);
      }
    }
  }

  const values = result ? applyableFields(result) : {};
  const missing = result?.missing_fields ?? [];
  const issues = result?.issues ?? [];
  const canApply = Object.keys(values).length > 0;
  const blockedIntent = result?.status === 'UNSUPPORTED_INTENT';

  function applyDetails() {
    const outcome = onApply(values, baseFormRef.current ?? { ...EMPTY_FIELDS, ...form }, result, { replaceExisting });
    const acknowledge = (summary) => {
      if (summary?.applied?.length) {
        setApplyMessage(summary.skipped?.length
          ? 'Details added to the form. Values you edited while reading were kept. Review the form, then choose Find Holidays.'
          : 'Details added to the form. Review them, then choose Find Holidays.');
      } else {
        setApplyMessage('Your existing form values were kept. No extracted details were added.');
      }
    };
    if (outcome && typeof outcome.then === 'function') outcome.then(acknowledge).catch(() => setApplyMessage('Could not apply the extracted details. Please try again.'));
    else acknowledge(outcome);
  }

  const onKeyDown = (event) => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      readRequest();
    }
  };

  return (
    <section className="quick-request" aria-label="Describe your holiday">
      {!controlled && <QuickRequestToggle open={open} onToggle={() => setOpen((value) => !value)} />}
      {open && <div className="quick-request__body" id="quick-request-body">
        <label className="eyebrow quick-request__label" htmlFor="quick-request-text">What do you have in mind?</label>
        <textarea id="quick-request-text" value={text} maxLength={2000} rows={3}
          placeholder="6 nights in Japan from Bengaluru, arriving 10 April 2027, for two adults and a six-year-old, under ₹3.5 lakh."
          disabled={disabled} onKeyDown={onKeyDown}
          onChange={(event) => changeText(event.target.value)} />
        <div className="quick-request__actions">
          <span className="quick-request__count">{text.length > COUNT_SHOWN_AFTER ? `${text.length}/2000` : null}</span>
          <button type="button" className="btn btn--primary btn--small" disabled={disabled || loading || !text.trim()}
            onClick={readRequest}>{loading ? 'Understanding…' : error ? 'Try again' : 'Understand My Trip'}</button>
        </div>
        {loading && <p className="quick-request__status" role="status">Reading the details you shared…</p>}
        {error && !loading && <p className="quick-request__error" role="alert">{error}</p>}
        {result && !applyMessage && <div className="quick-request__review" aria-live="polite">
          <h3>Review the details</h3>
          <p className="quick-request__summary">
            {result.status === 'READY' ? 'These details are ready to review.' :
              result.status === 'UNSUPPORTED_INTENT' ? 'This request is outside the trip details this form can read.' :
              result.status === 'NEEDS_CORRECTION' ? 'Some details need a correction.' : 'A few details are still missing.'}
            {' '}No trip has been planned.
          </p>
          <dl className="quick-request__list">
            {FIELDS.map(([field, label]) => {
              const ambiguous = isFieldBlocked(field, result);
              return <div key={field} className={`quick-request__item${ambiguous ? ' is-ambiguous' : ''}`}>
                <dt className="eyebrow">{label}</dt>
                <dd>{displayValue(field, result.fields?.[field], departures)}{ambiguous && <small> · Needs your choice</small>}</dd>
              </div>;
            })}
          </dl>
          {(missing.length > 0 || issues.length > 0) && <div className="quick-request__notes">
            {missing.length > 0 && <p><strong>Still needed:</strong> {missing.map((field) => FIELDS.find(([key]) => key === field)?.[1] ?? field).join(', ')}.</p>}
            {issues.map((issue, index) => <p key={`${issue.field}-${issue.code}-${index}`} className={issue.severity === 'error' ? 'is-error' : ''}>
              {issue.message}{issue.candidates?.length ? ` Options: ${issue.candidates.join(', ')}.` : ''}
            </p>)}
          </div>}
          {(result.assumptions ?? []).length > 0 && <details className="quick-request__assumptions">
            <summary>Assumptions to check</summary>
            {result.assumptions.map((item, index) => <p key={`${item.field}-${index}`}>{item.message}</p>)}
          </details>}
          {Object.entries(result.interpretations ?? {}).some(([, item]) => item?.source_text || item?.spans?.length) && <details className="quick-request__assumptions">
            <summary>Where these details came from</summary>
            {FIELDS.map(([field, label]) => {
              const source = result.interpretations?.[field];
              if (!source?.source_text && !source?.spans?.length) return null;
              return <p key={field}><strong>{label}:</strong> {source.source_text ?? source.spans.map((span) => typeof span === 'string' ? span : span.text).filter(Boolean).join(', ')}</p>;
            })}
          </details>}
          {canApply && !blockedIntent && !applyMessage && <>
            <label className="quick-request__replace"><input type="checkbox" checked={replaceExisting}
              onChange={(event) => setReplaceExisting(event.target.checked)} />Replace existing form values</label>
            <button type="button" className="btn btn--primary quick-request__apply" disabled={disabled}
              onClick={applyDetails}>
              Use Extracted Details
            </button>
          </>}
          {blockedIntent && <p className="quick-request__notes">No form details were applied.</p>}
        </div>}
        {applyMessage && <p className="quick-request__applied" role="status">{applyMessage}</p>}
      </div>}
    </section>
  );
}
