// Delay resilience: what the saved holiday does if the arrival flight lands late.
// Every outcome, time, price and message comes from the backend. The timeline only moves elements
// that already hold backend data, and a proposed plan is shown here but never replaces the page's
// itinerary until the traveler saves it with "Switch to this safer plan".

import { useEffect, useMemo, useRef } from 'react';
import { useStore } from '../state/store.js';
import {
  DELAY_LEVELS,
  applyDelayRescue,
  bookingStore,
  closeDelayRescue,
  openDelayRescue,
  retryDelayRescue,
  selectDelay,
} from '../state/bookingStore.js';
import { formatDay, formatINR, formatTime, plural } from './format.js';

const FOCUSABLE = 'button:not(:disabled), [href], [tabindex]:not([tabindex="-1"])';

/** Outcome styling. The text label and glyph carry the meaning; colour only reinforces it. */
const OUTCOMES = {
  ABSORBED: { key: 'absorbed', label: 'No change', glyph: '✓', title: 'No changes needed' },
  REPAIRED: { key: 'repaired', label: 'Repaired', glyph: '↻', title: 'Your holiday can still work' },
  UNRECOVERABLE: { key: 'unrecoverable', label: 'Breaks', glyph: '✕', title: 'No valid repair found' },
};
const NOT_EVALUATED = { key: 'unknown', label: '…', glyph: '–', title: '' };

const KIND_LABEL = { landing: 'Flight lands', pickup: 'Airport pickup', hotel_arrival: 'Hotel arrival', visit: 'Visit' };

const scenarioFor = (batch, minutes) => batch?.scenarios?.find((s) => s.delay_minutes === minutes) ?? null;

/** The row key: visits carry an item_id; landing, pickup and hotel arrival are unique by kind. */
const keyOf = (event) => event.item_id ?? event.kind;

function hoursText(minutes) {
  return plural(minutes / 60, 'hour');
}

/** A date is only shown when it differs from the day of the scheduled landing. */
function when(iso, dayRef) {
  if (!iso) return '-';
  const time = formatTime(iso);
  return iso.slice(0, 10) === dayRef?.slice(0, 10) ? time : `${formatDay(iso)} ${time}`;
}

function removedOf(scenario) {
  const seen = new Set();
  return [...(scenario.removed_activities ?? []), ...(scenario.changed_items ?? [])].filter((item) => {
    if (item.action !== 'REMOVED' || seen.has(item.item_id)) return false;
    seen.add(item.item_id);
    return true;
  });
}

/**
 * Before/after rows for the arrival: every event of the current plan with its time, and its time
 * under the simulated delay (moved, unchanged, removed or new). Times come from the backend timeline.
 */
function buildRows(scenario) {
  const { timeline } = scenario;
  if (!timeline?.original) return [];
  const original = timeline.original;
  const simulated = timeline.simulated ?? null;
  const simByKey = new Map((simulated ?? []).map((e) => [keyOf(e), e]));
  const origKeys = new Set(original.map(keyOf));
  const rows = original.map((orig) => {
    const key = keyOf(orig);
    const sim = simulated ? simByKey.get(key) : orig;
    const state = !sim ? 'removed' : sim.time !== orig.time ? 'moved' : 'same';
    return { key, kind: orig.kind, label: orig.label, before: orig.time, after: sim?.time ?? null, state };
  });
  for (const sim of simulated ?? []) {
    if (!origKeys.has(keyOf(sim))) {
      rows.push({ key: keyOf(sim), kind: sim.kind, label: sim.label, before: null, after: sim.time, state: 'new' });
    }
  }
  // the landing always moves by the delay, even when the backend has no simulated lane
  const landing = rows.find((r) => r.kind === 'landing');
  if (landing) {
    landing.after = scenario.simulated_landing;
    landing.state = 'moved';
  }
  return rows;
}

/** One tab per tested delay; each tab carries its own outcome, so it doubles as the resilience meter. */
function DelayTabs({ batch, selected, disabled }) {
  return (
    <div className="delay-tabs" role="group" aria-label="Simulated arrival delay">
      {DELAY_LEVELS.map((minutes) => {
        const tone = OUTCOMES[scenarioFor(batch, minutes)?.outcome] ?? NOT_EVALUATED;
        return (
          <button
            key={minutes}
            type="button"
            className={`delay-tab is-${tone.key}`}
            aria-pressed={minutes === selected}
            disabled={disabled}
            onClick={() => selectDelay(minutes)}
          >
            <span className="delay-tab__delay">+{minutes / 60} h late</span>
            <span className="delay-tab__status">
              <span className="delay-tab__dot" aria-hidden="true">
                {tone.glyph}
              </span>
              {tone.label}
            </span>
          </button>
        );
      })}
    </div>
  );
}

function toleranceText(batch) {
  const minutes = batch.tested_absorbed_continuous_minutes;
  const exact = batch.exact_absorbed_tolerance_minutes;
  if (exact != null && exact > 0) return `Your plan as booked copes with a delay of up to ${exact} min.`;
  if (minutes > 0) return `Your plan as booked copes with a delay of up to ${hoursText(minutes)}.`;
  return 'Any of these delays means changing your airport pickup. Pick one to see the fix.';
}

function ChangeTable({ rows, dayRef }) {
  if (rows.length === 0) return null;
  return (
    <table className="delay-table">
      <caption className="sr-only">Your arrival, before and after the delay (local times)</caption>
      <thead>
        <tr>
          <th scope="col">What</th>
          <th scope="col">Planned</th>
          <th scope="col">With delay</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.key} className={`is-${row.state}`}>
            <th scope="row">
              <span className="delay-table__kind">{KIND_LABEL[row.kind] ?? row.kind}</span>
              {row.kind !== 'landing' && row.label && <span className="delay-table__name">{row.label}</span>}
            </th>
            <td className="delay-table__before">{row.before ? when(row.before, dayRef) : '-'}</td>
            <td className="delay-table__after">
              {row.state === 'removed' ? (
                <span className="delay-table__flag">Dropped</span>
              ) : row.state === 'same' ? (
                <span className="delay-table__same">No change</span>
              ) : (
                <>
                  <strong>{when(row.after, dayRef)}</strong>
                  {row.state === 'new' && <span className="delay-table__flag">New</span>}
                </>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ScenarioBody({ batch, scenario, applying }) {
  const tone = OUTCOMES[scenario.outcome] ?? NOT_EVALUATED;
  const rows = useMemo(() => buildRows(scenario), [scenario]);
  const dayRef = batch.scheduled_landing;
  const removed = removedOf(scenario);
  const difference = scenario.price_difference_inr ?? 0;
  const note = !scenario.can_apply && scenario.apply_blocked_reason;
  // the backend explanation can open with the same words as the title; show only the detail after it
  const why = (scenario.explanation ?? '').replace(/^your holiday can still work[^:]*:\s*/i, '');
  const explanation = why ? why.charAt(0).toUpperCase() + why.slice(1) : '';
  const warnings = (scenario.warnings ?? []).filter((text) => !explanation.toLowerCase().includes(text.toLowerCase()));
  return (
    <section className={`delay-result is-${tone.key}`} aria-live="polite" aria-atomic="true">
      <header className="delay-result__head">
        <span className="delay-badge">
          <span aria-hidden="true">{tone.glyph}</span> {tone.label}
        </span>
        <p className="delay-result__landing">
          Lands <strong>{when(scenario.simulated_landing, dayRef)}</strong> instead of {formatTime(batch.scheduled_landing)} at{' '}
          {batch.arrival_airport}
        </p>
      </header>
      <h4 className="delay-result__title">{tone.title}</h4>
      {explanation && <p className="delay-result__why">{explanation}</p>}

      <ChangeTable rows={rows} dayRef={dayRef} />

      {removed.map((item) => (
        <p key={item.item_id} className="delay-removed">
          Drops {item.before?.name ?? item.label}. {item.reason}
        </p>
      ))}
      {scenario.outcome === 'UNRECOVERABLE' && scenario.violations?.length > 0 && (
        <ul className="delay-list">
          {scenario.violations.map((v, i) => (
            <li key={`${v.rule}-${i}`}>{v.message}</li>
          ))}
        </ul>
      )}
      {scenario.outcome === 'UNRECOVERABLE' && <p className="delay-note">Your original holiday stays as it is.</p>}

      {scenario.outcome === 'REPAIRED' && (
        <p className="delay-price">
          <span>
            Price change:{' '}
            <strong key={`${scenario.delay_minutes}-${applying}`} className="delay-price__value">
              {difference === 0 ? 'none' : `${difference > 0 ? '+' : '−'}${formatINR(Math.abs(difference))}`}
            </strong>
          </span>
          <span className="delay-price__total">New total {formatINR(scenario.proposed_total_inr)}</span>
        </p>
      )}
      {scenario.over_budget_inr > 0 && (
        <p className="delay-budget is-over" role="status">
          Over budget by {formatINR(scenario.over_budget_inr)}.
        </p>
      )}
      {warnings.length > 0 && (
        <ul className="delay-list delay-list--warnings">
          {warnings.map((text) => (
            <li key={text}>{text}</li>
          ))}
        </ul>
      )}
      {note && <p className="delay-note">{scenario.apply_blocked_reason}</p>}
    </section>
  );
}

/** @returns {JSX.Element | null} */
export default function DelayRescue() {
  const delay = useStore(bookingStore, (s) => s.delay);
  const ref = useRef(null);
  const open = delay.status !== 'idle';
  const { status, batch, selected, error, message } = delay;

  useEffect(() => {
    if (open) ref.current?.focus();
  }, [open]);

  if (!open) return null;

  const ready = (status === 'ready' || status === 'applying') && Boolean(batch);
  const scenario = ready ? scenarioFor(batch, selected) : null;
  const busy = status === 'loading' || status === 'applying';
  const canSwitch = Boolean(scenario?.can_apply) && status === 'ready';

  const onKeyDown = (event) => {
    if (event.key === 'Escape' && status !== 'applying') {
      event.stopPropagation();
      closeDelayRescue();
    } else if (event.key === 'Tab') {
      const nodes = [...ref.current.querySelectorAll(FOCUSABLE)];
      if (nodes.length === 0) return;
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      if (event.shiftKey && (document.activeElement === first || document.activeElement === ref.current)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
  };

  return (
    <div className="change-backdrop delay-backdrop" onMouseDown={(e) => e.target === e.currentTarget && status !== 'applying' && closeDelayRescue()}>
      <div
        ref={ref}
        className="change-drawer delay-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="delay-title"
        aria-busy={busy}
        data-state={status}
        tabIndex={-1}
        onKeyDown={onKeyDown}
      >
        <header className="change-drawer__header">
          <p className="eyebrow">Delay resilience</p>
          <h3 id="delay-title" className="change-drawer__title">
            If your flight lands late
          </h3>
          <p className="delay-note">A what-if check. Nothing changes unless you switch to the safer plan.</p>
        </header>

        <div className="change-drawer__body delay-body">
          <DelayTabs batch={ready ? batch : null} selected={selected} disabled={status === 'applying'} />
          {ready && <p className="delay-note delay-tolerance">{toleranceText(batch)}</p>}

          {status === 'loading' && <p className="results__muted">Checking the four delays…</p>}

          {status === 'error' && (
            <div className="change-error delay-error" role="alert">
              <p>{error?.message ?? 'The delay check could not be loaded.'}</p>
              <button type="button" className="btn btn--small" onClick={retryDelayRescue}>
                Try again
              </button>
            </div>
          )}

          {status === 'version_conflict' && (
            <div className="delay-notice" role="status">
              <p>{message}</p>
              <button type="button" className="btn btn--small" onClick={() => openDelayRescue()}>
                Run the check again
              </button>
            </div>
          )}

          {ready && scenario && (
            <>
              <ScenarioBody batch={batch} scenario={scenario} applying={status === 'applying'} />
            </>
          )}

          {status === 'applying' && (
            <p className="results__muted" role="status">
              Saving this repair…
            </p>
          )}
        </div>

        <footer className="change-drawer__footer">
          <button type="button" className="btn change-cancel" disabled={status === 'applying'} onClick={closeDelayRescue}>
            {ready ? 'Keep original itinerary' : 'Close'}
          </button>
          {ready && (
            <button
              type="button"
              className="btn btn--primary delay-switch"
              disabled={!canSwitch}
              onClick={applyDelayRescue}
            >
              {status === 'applying' ? 'Saving…' : 'Switch to this safer plan'}
            </button>
          )}
        </footer>
      </div>
    </div>
  );
}
