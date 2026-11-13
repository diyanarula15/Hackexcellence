// Multi-select for "Add attraction" on one day. Ticks build the selection in bookingStore; Preview sends it
// as ONE change and Apply saves it as ONE change. Every price, time and validity comes from the backend
// options; this component only displays them and edits the selection.

import { useStore } from '../state/store.js';
import {
  bookingStore,
  clearAttractionSelection,
  openAttractionDetails,
  previewSelectedAttractions,
  selectChangeOption,
  toggleAttractionSelection,
  updateAttractionSelection,
} from '../state/bookingStore.js';
import { formatDay, formatDuration, formatINR, formatTime, humanize } from './format.js';
import './AttractionPicker.css';

/** Mirrors the store's MAX_SELECTION: the backend accepts at most 8 additions in one change. */
const MAX_SELECTION = 8;
const TIMES = ['09:00', '10:00', '11:00', '12:00', '13:00', '14:00', '15:00', '16:00', '17:00', '18:00'];
const NO_DAYS = Object.freeze([]);
const NO_SELECTION = Object.freeze([]);

function facts(d = {}) {
  return [
    d.category ? humanize(d.category) : null,
    d.start && d.end ? `suggested ${formatTime(d.start)}–${formatTime(d.end)}` : null,
    d.visit_minutes ? formatDuration(d.visit_minutes) : null,
    d.open_from && d.open_until ? `open ${d.open_from}–${d.open_until}` : null,
    d.child_friendly ? 'child-friendly' : null,
  ].filter(Boolean).join(' · ');
}

function AttractionRow({ option, date, ticked, disabled, busy }) {
  const addable = option.valid && !option.current;
  const reason = addable ? null : option.reasons?.[0] ?? 'Not possible on this day';
  const city = option.details?.city ?? '';
  return (
    <li
      className={`attraction-picker__item${addable ? '' : ' is-invalid'}`}
      data-catalog-id={option.catalog_id}
      data-valid={String(addable)}
    >
      <label className="attraction-picker__check">
        <input
          type="checkbox"
          checked={ticked}
          disabled={disabled}
          onChange={() => toggleAttractionSelection({ attraction_id: option.catalog_id, name: option.name, city, date })}
        />
        <span className="attraction-picker__name">{option.name}</span>
      </label>
      {facts(option.details) && <p className="attraction-picker__facts">{facts(option.details)}</p>}
      {addable && (
        <p className="attraction-picker__price">
          {option.item_price_inr ? formatINR(option.item_price_inr) : 'Free entry'}
        </p>
      )}
      {reason && <p className="attraction-picker__reason">{reason}</p>}
      <div className="attraction-picker__actions">
        <button
          type="button"
          className="btn btn--small"
          onClick={() => openAttractionDetails({ attraction_id: option.catalog_id, date })}
        >
          Details
        </button>
        <button
          type="button"
          className="btn btn--small change-option-select"
          disabled={busy || option.current || !option.command}
          onClick={() => selectChangeOption(option)}
        >
          {addable ? 'Choose' : 'Why not?'}
        </button>
      </div>
    </li>
  );
}

/** @returns {JSX.Element} */
export default function AttractionPicker({ options, date, busy = false }) {
  const selection = useStore(bookingStore, (s) => s.attractionSelection ?? NO_SELECTION);
  const days = useStore(bookingStore, (s) => s.result?.response?.package?.days ?? NO_DAYS);
  const alternatives = options?.alternatives ?? [];
  const ticked = new Set(selection.map((entry) => entry.attraction_id));
  const full = selection.length >= MAX_SELECTION;
  const count = selection.length;
  // the departure day (last) takes no attractions; otherwise a day is a choice only in the attraction's city
  const dayChoicesFor = (city) => days.slice(0, -1).filter((d) => d.city === city);

  return (
    <div className="attraction-picker" data-count={count}>
      <ul className="attraction-picker__list">
        {alternatives.map((option) => {
          const isTicked = ticked.has(option.catalog_id);
          const addable = option.valid && !option.current;
          return (
            <AttractionRow
              key={option.catalog_id}
              option={option}
              date={date}
              ticked={isTicked}
              disabled={busy || !addable || (!isTicked && full)}
              busy={busy}
            />
          );
        })}
      </ul>

      <footer className="attraction-picker__footer" aria-label="Selected attractions">
        <p className="attraction-picker__count">
          <strong>{`${count} attraction${count === 1 ? '' : 's'} selected`}</strong>
          {full && <span> · the most you can add in one change is {MAX_SELECTION}</span>}
        </p>
        {count > 0 && (
          <ul className="attraction-picker__selected">
            {selection.map((entry) => {
              const choices = dayChoicesFor(entry.city);
              if (!choices.some((d) => d.date === entry.date)) choices.unshift({ date: entry.date });
              return (
                <li key={entry.attraction_id} className="attraction-picker__selected-item">
                  <span className="attraction-picker__selected-name">{entry.name}</span>
                  <label className="attraction-picker__field">
                    <span>Day</span>
                    <select
                      aria-label={`Day for ${entry.name}`}
                      value={entry.date}
                      disabled={busy}
                      onChange={(e) => updateAttractionSelection(entry.attraction_id, { date: e.target.value })}
                    >
                      {choices.map((d) => (
                        <option key={d.date} value={d.date}>
                          {formatDay(d.date)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="attraction-picker__field">
                    <span>Time</span>
                    <select
                      aria-label={`Time for ${entry.name}`}
                      value={entry.preferred_start ?? ''}
                      disabled={busy}
                      onChange={(e) =>
                        updateAttractionSelection(entry.attraction_id, { preferred_start: e.target.value || null })
                      }
                    >
                      <option value="">Let planner decide</option>
                      {TIMES.map((t) => (
                        <option key={t} value={t}>
                          {t}
                        </option>
                      ))}
                    </select>
                  </label>
                </li>
              );
            })}
          </ul>
        )}
        <div className="attraction-picker__actions attraction-picker__actions--footer">
          <button
            type="button"
            className="btn btn--small attraction-picker__clear"
            disabled={busy || count === 0}
            onClick={() => clearAttractionSelection()}
          >
            Clear
          </button>
          <button
            type="button"
            className="btn btn--primary btn--small attraction-picker__preview"
            disabled={busy || count === 0}
            onClick={(event) => previewSelectedAttractions(event.currentTarget)}
          >
            {`Preview ${count} attraction${count === 1 ? '' : 's'}`}
          </button>
        </div>
      </footer>
    </div>
  );
}
