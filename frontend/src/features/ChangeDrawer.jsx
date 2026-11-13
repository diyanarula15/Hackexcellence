// Every price, total and message here comes from the backend; this component only displays it.

import { useEffect, useRef } from 'react';
import { useStore } from '../state/store.js';
import {
  applyChange,
  bookingStore,
  closeChange,
  optionKey,
  reloadLatest,
  repreviewChange,
  selectChangeOption,
  selectChangeSlot,
  previewSelectedAttractions,
} from '../state/bookingStore.js';
import { formatDay, formatDuration, formatINR, formatSignedINR, formatTime, humanize, plural } from './format.js';
import AttractionPicker from './AttractionPicker.jsx';

const BATCH_KINDS = new Set(['ADD_ATTRACTIONS', 'REMOVE_ATTRACTIONS']);
const BATCH_VERB = { ADDED: 'Added', RESCHEDULED: 'Moves', REMOVED: 'Removed' };

/** How many attractions a batch command names (null for every other change). */
function batchCount(command) {
  if (!BATCH_KINDS.has(command?.kind)) return null;
  return command.kind === 'ADD_ATTRACTIONS' ? command.additions.length : command.item_ids.length;
}

const FOCUSABLE = 'button:not(:disabled), select:not(:disabled), [href], [tabindex]:not([tabindex="-1"])';

function clock(iso) {
  return iso ? `${formatDay(iso)} ${formatTime(iso)}` : '';
}

/** Short, kind-specific facts for an option; null values are skipped. */
function optionFacts(kind, d = {}) {
  switch (kind) {
    case 'hotel':
      return [
        d.area,
        d.stars ? `${d.stars}★` : null,
        d.rating ? `rating ${d.rating}` : null,
        d.rooms ? plural(d.rooms, 'room') : null,
        d.nights ? plural(d.nights, 'night') : null,
        d.price_per_night_inr != null ? `${formatINR(d.price_per_night_inr)} per night` : null,
      ];
    case 'arrival_flight':
    case 'return_flight':
      return [
        d.airline,
        d.flight_number,
        d.from && d.to ? `${d.from} → ${d.to}` : null,
        d.departure_local ? `departs ${clock(d.departure_local)}` : null,
        d.arrival_local ? `lands ${clock(d.arrival_local)}` : null,
        d.duration_minutes ? formatDuration(d.duration_minutes) : null,
        d.stops != null ? (d.stops === 0 ? 'non-stop' : plural(d.stops, 'stop')) : null,
        d.cabin ? humanize(d.cabin) : null,
        d.seats_left != null ? `${plural(d.seats_left, 'seat')} left` : null,
      ];
    case 'airport_transfer':
    case 'intercity_transfer':
      return [
        d.transfer_type ? humanize(d.transfer_type) : null,
        d.from_point && d.to_point ? `${d.from_point} → ${d.to_point}` : null,
        d.pickup && d.pickup.length > 5 ? `pickup ${clock(d.pickup)}` : null,
        d.dropoff && d.dropoff.length > 5 ? `arrives ${clock(d.dropoff)}` : null,
        d.duration_minutes ? formatDuration(d.duration_minutes) : null,
        d.frequency_minutes ? `every ${d.frequency_minutes} min` : null,
        d.max_passengers ? `up to ${plural(d.max_passengers, 'passenger')}` : null,
      ];
    case 'attraction':
      return [
        d.category ? humanize(d.category) : null,
        d.start && d.end ? `${formatTime(d.start)}–${formatTime(d.end)}` : null,
        d.visit_minutes ? formatDuration(d.visit_minutes) : null,
        d.open_from && d.open_until ? `open ${d.open_from}–${d.open_until}` : null,
        d.child_friendly ? 'child-friendly' : null,
      ];
    default:
      return [];
  }
}

function Option({ option, kind, selected, busy }) {
  const slots = option.details?.departure_slots ?? [];
  const facts = optionFacts(kind, option.details).filter(Boolean).join(' · ');
  const disabled = busy || option.current || !option.command;
  const title = option.room_name ? `${option.name} · ${option.room_name}` : option.name;
  return (
    <li
      className={`change-option${selected ? ' is-selected' : ''}${option.valid ? '' : ' is-invalid'}`}
      data-catalog-id={option.catalog_id}
      data-room-id={option.room_id ?? ''}
      data-valid={String(option.valid)}
      data-current={String(option.current)}
    >
      {option.details?.image_url && (
        <img className="option-thumb" src={option.details.image_url} alt="" loading="lazy" />
      )}
      <div className="change-option__main">
        <p className="change-option__name">
          {title}
          {option.current && <span className="change-badge">Current</span>}
        </p>
        {facts && <p className="change-option__detail">{facts}</p>}
        {option.valid && !option.current && option.package_price_difference_inr != null && (
          <p className="change-option__price">
            <strong>{formatSignedINR(option.package_price_difference_inr)}</strong> on the package · new total{' '}
            {formatINR(option.proposed_total_inr)}
            {option.over_budget_inr > 0 && <span className="is-over"> · over budget by {formatINR(option.over_budget_inr)}</span>}
          </p>
        )}
        {option.valid && option.affected_items?.length > 0 && (
          <ul className="change-option__also">
            {option.affected_items.map((item) => (
              <li key={item.item_id}>also changes: {item.summary}</li>
            ))}
          </ul>
        )}
        {!option.valid && (
          <ul className="change-option__reasons">
            {option.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        )}
        {kind === 'intercity_transfer' && slots.length > 0 && (
          <label className="change-time-label">
            Departure time
            <select
              className="change-time"
              value={selected ? selected.slot : ''}
              disabled={busy || !option.valid}
              onChange={(e) => {
                const slot = slots.find((s) => s.pickup === e.target.value);
                if (slot) selectChangeSlot(option, slot);
              }}
            >
              <option value="" disabled>
                Choose a time
              </option>
              {slots.map((slot) => (
                <option key={slot.pickup} value={slot.pickup} disabled={!slot.valid}>
                  {slot.pickup} → {slot.arrives}
                  {slot.valid
                    ? slot.package_price_difference_inr != null
                      ? ` (${formatSignedINR(slot.package_price_difference_inr)})`
                      : ''
                    : ` (unavailable: ${slot.reasons?.[0] ?? 'not possible'})`}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      <button
        type="button"
        className="btn btn--small change-option-select"
        disabled={disabled}
        aria-pressed={Boolean(selected)}
        onClick={() => selectChangeOption(option)}
      >
        {option.current ? 'Current' : selected ? 'Selected' : option.valid ? 'Choose' : 'Why not?'}
      </button>
    </li>
  );
}

function List({ items, className }) {
  if (!items?.length) return null;
  return (
    <ul className={className}>
      {items.map((item, i) => (
        <li key={i}>{item}</li>
      ))}
    </ul>
  );
}

function Preview({ preview }) {
  const valid = preview.valid;
  const batch = BATCH_KINDS.has(preview.kind);
  const over = preview.over_budget_inr > 0;
  // The preview renders below a long option list: bring it into view when it arrives.
  const sectionRef = useRef(null);
  useEffect(() => {
    sectionRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
  }, [preview]);
  return (
    <section ref={sectionRef} className="change-preview" data-valid={String(valid)} aria-label="Change preview" aria-live="polite">
      <p className="change-headline">{preview.message}</p>
      {valid && (
        <dl className="change-figures">
          <div>
            <dt>Current total</dt>
            <dd className="change-old-total">{formatINR(preview.old_total_inr)}</dd>
          </div>
          <div>
            <dt>New total</dt>
            <dd className="change-new-total">{formatINR(preview.new_total_inr)}</dd>
          </div>
          <div>
            <dt>Difference</dt>
            <dd className="change-diff">{formatSignedINR(preview.price_difference_inr)}</dd>
          </div>
          <div>
            <dt>Budget</dt>
            <dd className={`change-budget${over ? ' is-over' : ''}`}>
              {over
                ? `Over budget by ${formatINR(preview.over_budget_inr)}`
                : `${formatINR(preview.budget_remaining_inr)} left of ${formatINR(preview.budget_inr)}`}
            </dd>
          </div>
        </dl>
      )}
      {batch && valid && (
        <div>
          <h4 className="eyebrow">Attractions</h4>
          <ul className="change-items change-batch">
            {preview.changed_items
              .filter((item) => item.source === 'USER_CHOICE')
              .map((item) => {
                const side = item.after ?? item.before;
                const span = item.start
                  ? `${formatDay(item.start)} ${formatTime(item.start)}${item.end ? `–${formatTime(item.end)}` : ''}`
                  : '';
                return (
                  <li key={item.item_id} data-action={item.action}>
                    <strong>{BATCH_VERB[item.action] ?? 'Changed'}</strong> {side?.name ?? item.label} · {span}
                    {item.price_difference_inr
                      ? ` · ${formatSignedINR(item.price_difference_inr)}`
                      : item.action === 'ADDED'
                        ? ' · free entry'
                        : ''}
                  </li>
                );
              })}
          </ul>
        </div>
      )}
      {preview.changed_items?.length > 0 && valid && !batch && (
        <div>
          <h4 className="eyebrow">Changes</h4>
          <ul className="change-items">
            {preview.changed_items
              .filter((item) => item.source !== 'AUTOMATIC_REPAIR')
              .map((item) => (
                <li key={item.item_id}>
                  {item.summary}
                  {item.price_difference_inr ? ` (${formatSignedINR(item.price_difference_inr)})` : ''}
                </li>
              ))}
          </ul>
        </div>
      )}
      {preview.automatic_repairs?.length > 0 && (
        <div>
          <h4 className="eyebrow">Also changed automatically</h4>
          <ul className="change-repairs">
            {preview.automatic_repairs.map((item) => (
              <li key={item.item_id}>
                {item.summary}
                {item.reason ? ` ${item.reason}` : ''}
              </li>
            ))}
          </ul>
        </div>
      )}
      {preview.warnings?.length > 0 && (
        <div>
          <h4 className="eyebrow">Warnings</h4>
          <List className="change-warnings" items={preview.warnings} />
        </div>
      )}
      {preview.violations?.length > 0 && (
        <div>
          <h4 className="eyebrow">Why this cannot be saved</h4>
          <List className="change-violations" items={preview.violations.map((v) => v.message)} />
        </div>
      )}
    </section>
  );
}

function ErrorBox({ error }) {
  const conflict = error.status === 409 && error.code === 'PACKAGE_VERSION_CONFLICT';
  const outdated = error.status === 409 && error.code === 'PREVIEW_OUTDATED';
  return (
    <div className="change-error" role="alert">
      <p>{error.message}</p>
      <List items={error.details} />
      {conflict && (
        <button type="button" className="btn btn--small change-reload" onClick={reloadLatest}>
          Reload latest
        </button>
      )}
      {outdated && (
        <button type="button" className="btn btn--small change-repreview" onClick={repreviewChange}>
          Preview again
        </button>
      )}
    </div>
  );
}

/** @returns {JSX.Element | null} */
export default function ChangeDrawer() {
  const change = useStore(bookingStore, (s) => s.change);
  const ticked = useStore(bookingStore, (s) => s.attractionSelection?.length ?? 0);
  const ref = useRef(null);
  const open = change.status !== 'closed';
  const { status } = change;

  useEffect(() => {
    if (open) ref.current?.focus();
  }, [open]);

  if (!open) return null;

  const busy = status === 'applying' || status === 'previewing' || status === 'loading';
  const kind = change.options?.kind;
  const selected = change.selectedKey ? { key: change.selectedKey, slot: change.slot } : null;
  const canApply = status === 'preview' && change.preview?.valid && Boolean(change.preview.preview_token);
  // Ticked attractions with nothing to apply yet: the main button runs the preview, so it is never a dead end.
  const picking = change.target?.kind === 'attraction';
  const needsPreview = picking && ticked > 0 && !canApply && !busy;

  const onKeyDown = (event) => {
    if (event.key === 'Escape' && status !== 'applying') {
      event.stopPropagation();
      closeChange();
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
    <div className="change-backdrop" onMouseDown={(e) => e.target === e.currentTarget && closeChange()}>
      <div
        ref={ref}
        className="change-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="change-title"
        aria-busy={busy}
        data-state={status}
        tabIndex={-1}
        onKeyDown={onKeyDown}
      >
        <header className="change-drawer__header">
          <h3 id="change-title" className="change-drawer__title">
            {change.target?.label ?? 'Change your holiday'}
          </h3>
        </header>

        <div className="change-drawer__body">
          {status === 'loading' && <p className="results__muted">Loading options…</p>}
          {change.options?.message && change.options.alternatives.length === 0 && (
            <p className="change-empty">{change.options.message}</p>
          )}
          {change.options?.alternatives.length > 0 && change.target?.kind === 'attraction' && (
            <AttractionPicker options={change.options} date={change.target.date} busy={busy} />
          )}
          {change.options?.alternatives.length > 0 && change.target?.kind !== 'attraction' && (
            <ul className="change-options">
              {change.options.alternatives.map((option) => (
                <Option
                  key={optionKey(option)}
                  option={option}
                  kind={kind}
                  selected={selected && selected.key === optionKey(option) ? selected : null}
                  busy={busy}
                />
              ))}
            </ul>
          )}
          {status === 'previewing' && <p className="results__muted">Checking this change…</p>}
          {change.preview && status !== 'previewing' && <Preview preview={change.preview} />}
          {status === 'applying' && <p className="results__muted">Saving…</p>}
          {status === 'error' && change.error && <ErrorBox error={change.error} />}
        </div>

        <footer className="change-drawer__footer">
          {picking && !canApply && !needsPreview && status === 'options' && (
            <p className="change-drawer__hint">Tick attractions (or press Choose on one) to see the price before applying.</p>
          )}
          <button type="button" className="btn change-cancel" disabled={status === 'applying'} onClick={closeChange}>
            Cancel
          </button>
          {needsPreview ? (
            <button type="button" className="btn btn--primary change-apply" onClick={(e) => previewSelectedAttractions(e.currentTarget)}>
              {`Preview ${ticked} attraction${ticked === 1 ? '' : 's'}`}
            </button>
          ) : (
            <button type="button" className="btn btn--primary change-apply" disabled={!canApply} onClick={applyChange}>
              {status === 'applying' ? 'Saving…' : batchCount(change.command) ? `Apply all ${batchCount(change.command)}` : 'Apply change'}
            </button>
          )}
        </footer>
      </div>
    </div>
  );
}
