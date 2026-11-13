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

/** Meter and outcome styling. The text label and glyph carry the meaning; colour only reinforces it. */
const OUTCOMES = {
  ABSORBED: { key: 'absorbed', label: 'Absorbed', glyph: '✓' },
  REPAIRED: { key: 'repaired', label: 'Repaired', glyph: '↻' },
  UNRECOVERABLE: { key: 'unrecoverable', label: 'Unrecoverable', glyph: '✕' },
};
const NOT_EVALUATED = { key: 'unknown', label: 'Not evaluated', glyph: '–' };

const PLANE_PATH = 'M21 16v-2l-8-5V3.5a1.5 1.5 0 0 0-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5z';

const ROW_PX = 30;
const TICK_STEPS = [60, 120, 360, 720]; // minutes

const scenarioFor = (batch, minutes) => batch?.scenarios?.find((s) => s.delay_minutes === minutes) ?? null;

/** "2027-04-10T10:30" → minutes since the epoch, read as wall-clock time (no time-zone shifts). */
function minutesOf(iso) {
  if (!iso) return null;
  const [day, time = '00:00'] = iso.split('T');
  const [y, mo, d] = day.split('-').map(Number);
  const [h, mi] = time.split(':').map(Number);
  return Date.UTC(y, mo - 1, d, h, mi) / 60000;
}

/** Inverse of minutesOf, to the minute. */
const isoOf = (minutes) => new Date(minutes * 60000).toISOString().slice(0, 16);

/** The timeline key: visits carry an item_id; landing, pickup and hotel arrival are unique by kind. */
const keyOf = (event) => event.item_id ?? event.kind;

const estimateWidth = (text) => text.length * 1.3 + 2;

function hoursText(minutes) {
  return plural(minutes / 60, 'hour');
}

/** A date is only shown when it differs from the day of the scheduled landing. */
function when(iso, dayRef) {
  if (!iso) return '-';
  const time = formatTime(iso);
  return iso.slice(0, 10) === dayRef?.slice(0, 10) ? time : `${formatDay(iso)} ${time}`;
}

/** Repair items the backend changed, excluding the removals listed separately. */
function changedOf(scenario) {
  const seen = new Set();
  return [...(scenario.changed_items ?? []), ...(scenario.automatic_repairs ?? [])].filter((item) => {
    if (item.action === 'REMOVED' || seen.has(item.item_id)) return false;
    seen.add(item.item_id);
    return true;
  });
}

function removedOf(scenario) {
  const seen = new Set();
  return [...(scenario.removed_activities ?? []), ...(scenario.changed_items ?? [])].filter((item) => {
    if (item.action !== 'REMOVED' || seen.has(item.item_id)) return false;
    seen.add(item.item_id);
    return true;
  });
}

/** One changed item as "name: old → new". Names and times come from the item's before/after. */
function describeChange(item, dayRef) {
  const { before, after } = item;
  const name = item.label || before?.name || after?.name || '';
  if (item.action === 'REPLACED' && before?.name && after?.name) {
    return `${name ? `${name}: ` : ''}${before.name} → ${after.name}`;
  }
  if (before?.start && after?.start) {
    return `${name ? `${name}: ` : ''}${when(before.start, dayRef)} → ${when(after.start, dayRef)}`;
  }
  return item.summary ?? name;
}

function ToleranceSummary({ batch }) {
  const hours = batch.tested_absorbed_continuous_minutes;
  const exact = batch.exact_absorbed_tolerance_minutes;
  return (
    <div className="delay-summary">
      <p>
        {hours > 0
          ? `Your current itinerary absorbs tested delays of up to ${hoursText(hours)}.`
          : 'Your current pickup needs a change for any tested delay.'}
      </p>
      {exact != null && <p className="delay-summary__exact">Verified at the boundary: exactly up to {exact} min.</p>}
    </div>
  );
}

function Meter({ batch, selected }) {
  return (
    <div className="delay-meter-wrap">
      <p className="eyebrow" id="delay-meter-title">
        Delay resilience meter
      </p>
      <ol className="delay-meter" aria-labelledby="delay-meter-title">
        {DELAY_LEVELS.map((minutes) => {
          const tone = OUTCOMES[scenarioFor(batch, minutes)?.outcome] ?? NOT_EVALUATED;
          return (
            <li
              key={minutes}
              className={`delay-meter__seg is-${tone.key}${minutes === selected ? ' is-selected' : ''}`}
            >
              <span className="delay-meter__delay">+{minutes / 60} h</span>
              <span className="delay-meter__status">
                <span className="delay-meter__glyph" aria-hidden="true">
                  {tone.glyph}
                </span>
                {tone.label}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function PlaneIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
      <path d={PLANE_PATH} fill="currentColor" />
    </svg>
  );
}

/** Lays items into the fewest rows that do not overlap, so the lane stays readable. */
function packRows(items) {
  const sorted = [...items].sort((a, b) => a.left - b.left);
  const ends = [];
  for (const item of sorted) {
    const span = Math.max(item.width ?? 0, estimateWidth(item.text));
    let row = ends.findIndex((end) => item.left >= end);
    if (row === -1) {
      row = ends.length;
      ends.push(0);
    }
    ends[row] = item.left + span;
    item.row = row;
  }
  return { items: sorted, rows: Math.max(ends.length, 1) };
}

function toItem(event, pct, state) {
  const start = minutesOf(event.time);
  const stop = minutesOf(event.end);
  const left = pct(start);
  const width = stop == null ? null : Math.max(pct(stop) - left, 1.5);
  const clock = formatTime(event.time);
  const label = event.label ?? '';
  return {
    key: keyOf(event),
    kind: event.kind,
    state,
    left,
    width,
    label,
    clock,
    text: `${state === 'removed' ? 'Removed ' : ''}${clock} ${label}`,
    title: `${clock}${event.end ? `–${formatTime(event.end)}` : ''} ${label}`,
  };
}

/**
 * Positions for the arrival timeline. Original events keep their times; the proposed lane uses
 * the same keys, so a moved visit or pickup keeps its element and slides, a removed one stays at
 * its original time labelled "Removed", and a new one appears.
 */
function buildTimeline(scenario) {
  const { timeline } = scenario;
  if (!timeline?.original) return null;
  const original = timeline.original.filter((e) => e.kind !== 'landing');
  const simulated = timeline.simulated ? timeline.simulated.filter((e) => e.kind !== 'landing') : null;
  const origByKey = new Map(original.map((e) => [keyOf(e), e]));
  const simByKey = new Map((simulated ?? []).map((e) => [keyOf(e), e]));

  const moments = [
    scenario.scheduled_landing,
    scenario.simulated_landing,
    scenario.original_pickup,
    scenario.proposed_pickup,
    ...[...original, ...(simulated ?? [])].flatMap((e) => [e.time, e.end]),
  ]
    .map(minutesOf)
    .filter((v) => v != null);
  if (!moments.length) return null;

  let lo = Math.min(...moments) - 30;
  let hi = Math.max(...moments) + 30;
  if (hi - lo < 180) {
    const mid = (lo + hi) / 2;
    lo = mid - 90;
    hi = mid + 90;
  }
  const span = hi - lo;
  const pct = (m) => ((m - lo) / span) * 100;

  const pickupMoved = Boolean(scenario.proposed_pickup) && scenario.proposed_pickup !== scenario.original_pickup;
  const current = packRows(original.map((e) => toItem(e, pct, e.kind === 'pickup' && pickupMoved ? 'struck' : 'static')));

  let proposed = null;
  if (simulated) {
    const keys = [...origByKey.keys(), ...[...simByKey.keys()].filter((k) => !origByKey.has(k))];
    proposed = packRows(
      keys.map((key) => {
        const sim = simByKey.get(key);
        const orig = origByKey.get(key);
        if (!sim) return toItem(orig, pct, 'removed');
        if (!orig) return toItem(sim, pct, 'new');
        const moved = sim.time !== orig.time || sim.end !== orig.end;
        return toItem(sim, pct, moved ? 'moved' : 'same');
      }),
    );
  }

  const step = TICK_STEPS.find((s) => span / s <= 8) ?? TICK_STEPS[TICK_STEPS.length - 1];
  const ticks = [];
  for (let t = Math.ceil(lo / step) * step; t <= hi; t += step) {
    const iso = isoOf(t);
    ticks.push({ key: t, left: pct(t), clock: formatTime(iso), day: ticks.length === 0 || t % 1440 === 0 ? formatDay(iso) : '' });
  }

  return {
    landing: {
      ghost: pct(minutesOf(scenario.scheduled_landing)),
      plane: pct(minutesOf(scenario.simulated_landing)),
      scheduledClock: formatTime(scenario.scheduled_landing),
      simulatedClock: formatTime(scenario.simulated_landing),
    },
    current,
    proposed,
    ticks,
  };
}

function TimelineLane({ label, lane }) {
  return (
    <div className="delay-tl__group">
      <p className="delay-tl__label">{label}</p>
      <div className="delay-tl__lane" style={{ height: `${lane.rows * ROW_PX}px` }}>
        {lane.items.map((item) => (
          <span
            key={item.key}
            className={`delay-tl__event delay-tl__event--${item.kind} is-${item.state}`}
            style={{
              // chips in the right half grow leftwards from their end so their label stays visible
              ...(item.left > 50
                ? { right: `${Math.max(0, 100 - item.left - (item.width ?? 0))}%` }
                : { left: `${item.left}%` }),
              top: `${item.row * ROW_PX}px`,
              width: item.width == null ? undefined : `${item.width}%`,
            }}
            title={item.title}
          >
            {item.state === 'removed' && <em className="delay-tl__tag">Removed</em>}
            <span className="delay-tl__text">{item.label}</span>
            <span className="delay-tl__clock">{item.clock}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

/** Before/after arrival timeline. Positions slide, removals fade with a label; no data is changed. */
function DelayTimeline({ layout, delayMinutes }) {
  return (
    <section className="delay-tl" aria-label="Arrival timeline, local times">
      <div className="delay-tl__group">
        <p className="delay-tl__label">Flight landing</p>
        <div className="delay-tl__lane delay-tl__lane--landing" style={{ height: `${ROW_PX}px` }}>
          <span className="delay-tl__ghost" style={{ left: `${layout.landing.ghost}%` }} title={`Scheduled landing ${layout.landing.scheduledClock}`} />
          <span className="delay-tl__plane" style={{ left: `${layout.landing.plane}%` }}>
            <PlaneIcon />
          </span>
          <span
            className={`delay-tl__plane-label${layout.landing.plane > 80 ? ' is-flip' : ''}`}
            style={{ left: `${layout.landing.plane}%` }}
          >
            Lands {layout.landing.simulatedClock}
          </span>
        </div>
      </div>
      <TimelineLane label="Current plan" lane={layout.current} />
      {layout.proposed && <TimelineLane label={`With a +${delayMinutes / 60} h delay`} lane={layout.proposed} />}
      <div className="delay-tl__axis" aria-hidden="true">
        {layout.ticks.map((tick) => (
          <span key={tick.key} className="delay-tl__tick" style={{ left: `${tick.left}%` }}>
            {tick.day && <small>{tick.day}</small>}
            {tick.clock}
          </span>
        ))}
      </div>
    </section>
  );
}

function Repair({ scenario, batch, applying }) {
  const { outcome } = scenario;
  const dayRef = batch.scheduled_landing;
  const note = !scenario.can_apply && scenario.apply_blocked_reason;

  if (outcome === 'ABSORBED') {
    return (
      <section className="delay-repair">
        <h4 className="delay-repair__title">No changes needed.</h4>
        {note && <p className="delay-note">{scenario.apply_blocked_reason}</p>}
      </section>
    );
  }

  if (outcome === 'UNRECOVERABLE') {
    return (
      <section className="delay-repair">
        <h4 className="delay-repair__title">No valid repair found.</h4>
        {scenario.violations?.length > 0 && (
          <ul className="delay-list">
            {scenario.violations.map((v, i) => (
              <li key={`${v.rule}-${i}`}>{v.message}</li>
            ))}
          </ul>
        )}
        <p className="delay-note">Your original holiday remains unchanged.</p>
        {note && <p className="delay-note">{scenario.apply_blocked_reason}</p>}
      </section>
    );
  }

  if (outcome !== 'REPAIRED') return null;

  const changed = changedOf(scenario);
  const removed = removedOf(scenario);
  const difference = scenario.price_difference_inr ?? 0;
  const over = scenario.over_budget_inr > 0;
  return (
    <section className="delay-repair">
      <h4 className="delay-repair__title">Your holiday can still work.</h4>
      {changed.length > 0 && (
        <ul className="delay-list">
          {changed.map((item) => (
            <li key={item.item_id}>{describeChange(item, dayRef)}</li>
          ))}
        </ul>
      )}
      {removed.map((item) => (
        <p key={item.item_id} className="delay-removed">
          This repair removes {item.before?.name ?? item.label}. {item.reason}
        </p>
      ))}
      <dl className="delay-figures">
        <div>
          <dt>Current total</dt>
          <dd>{formatINR(scenario.original_total_inr)}</dd>
        </div>
        <div>
          <dt>Repaired total</dt>
          <dd>{formatINR(scenario.proposed_total_inr)}</dd>
        </div>
        <div>
          <dt>{difference > 0 ? 'Extra cost' : difference < 0 ? 'Saving' : 'Price change'}</dt>
          <dd key={`${scenario.delay_minutes}-${applying}`} className="delay-price__value">
            {difference === 0 ? formatINR(0) : formatINR(Math.abs(difference))}
          </dd>
        </div>
      </dl>
      {over && (
        <p className="delay-budget is-over" role="status">
          Over budget by {formatINR(scenario.over_budget_inr)}.
        </p>
      )}
      {note && <p className="delay-note">{scenario.apply_blocked_reason}</p>}
    </section>
  );
}

function ScenarioBody({ batch, scenario, applying }) {
  const tone = OUTCOMES[scenario.outcome] ?? NOT_EVALUATED;
  const layout = useMemo(() => buildTimeline(scenario), [scenario]);
  return (
    <>
      <dl className="delay-facts">
        <div>
          <dt>Scheduled landing</dt>
          <dd>
            {formatDay(batch.scheduled_landing)} {formatTime(batch.scheduled_landing)} · {batch.arrival_airport}
          </dd>
        </div>
        <div>
          <dt>Current pickup</dt>
          <dd>{batch.original_pickup ? `${formatDay(batch.original_pickup)} ${formatTime(batch.original_pickup)}` : '-'}</dd>
        </div>
      </dl>

      <section className="delay-outcome" aria-live="polite" aria-atomic="true">
        <p className="delay-outcome__landing">
          Simulated landing{' '}
          <strong>
            {formatDay(scenario.simulated_landing)} {formatTime(scenario.simulated_landing)}
          </strong>
        </p>
        <p className={`delay-badge is-${tone.key}`}>
          <span aria-hidden="true">{tone.glyph}</span> {tone.label}
        </p>
        <p className="delay-outcome__explanation">{scenario.explanation}</p>
      </section>

      {layout && <DelayTimeline layout={layout} delayMinutes={scenario.delay_minutes} />}

      <Repair scenario={scenario} batch={batch} applying={applying} />

      {scenario.warnings?.length > 0 && (
        <ul className="delay-list delay-list--warnings">
          {scenario.warnings.map((text) => (
            <li key={text}>{text}</li>
          ))}
        </ul>
      )}
    </>
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
          <p className="delay-note">These delays are simulated. Nothing changes until you switch to a plan.</p>
        </header>

        <div className="change-drawer__body delay-body">
          <div className="delay-levels" role="group" aria-label="Simulated arrival delay">
            {DELAY_LEVELS.map((minutes) => (
              <button
                key={minutes}
                type="button"
                className="btn btn--small delay-levels__btn"
                aria-pressed={minutes === selected}
                disabled={status === 'applying'}
                onClick={() => selectDelay(minutes)}
              >
                +{minutes / 60} h
              </button>
            ))}
          </div>

          <Meter batch={ready ? batch : null} selected={selected} />

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
              <ToleranceSummary batch={batch} />
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
