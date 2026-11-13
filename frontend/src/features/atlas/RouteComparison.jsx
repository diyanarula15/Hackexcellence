import { formatDay, formatINR, formatSignedINR, formatTime } from '../format.js';
import DayTimeline from '../DayTimeline.jsx';
import './RouteComparison.css';

const SECTIONS = [
  ['flight', 'Flights'],
  ['hotel', 'Hotels'],
  ['transfer', 'Transfers'],
  ['attraction', 'Attractions'],
];

function money(value) {
  return value == null ? null : formatINR(value);
}

function routeText(packageData) {
  const plan = packageData?.city_plan ?? [];
  if (!plan.length) return 'Route unavailable';
  return plan.map((stop) => `${stop.city} · ${stop.nights} ${stop.nights === 1 ? 'night' : 'nights'}`).join(' → ');
}

const STATUS_TEXT = {
  FOUND: 'Fits your budget',
  VALID: 'Fits your budget',
  OVER_BUDGET: 'Over budget',
  INFEASIBLE: 'Not possible',
  SEARCH_INCOMPLETE: 'Search incomplete',
};

function valueName(side) {
  if (!side) return null;
  const stamp = (value) => {
    if (!value) return null;
    const day = formatDay(value);
    const time = formatTime(value);
    return [day, time || null].filter(Boolean).join(' ');
  };
  const period = side.start || side.end
    ? [stamp(side.start), stamp(side.end)].filter(Boolean).join(' to ')
    : null;
  const roomParts = [side.room_name, side.room_id].filter((value, index, values) => value && values.indexOf(value) === index);
  const roomDetails = roomParts.length
    ? `${roomParts[0]}${roomParts[1] ? ` (${roomParts[1]})` : ''}${side.rooms != null ? ` × ${side.rooms}` : ''}`
    : null;
  return [side.name, side.city, roomDetails, period]
    .filter(Boolean).join(' · ');
}

/** "Added: X", "Removed: X" or "X → Y"; never a bare "None" for the missing side. */
function ChangeDetail({ before, after }) {
  if (!before && !after) return null;
  if (!before) return <>Added: {after}</>;
  if (!after) return <>Removed: {before}</>;
  return <>{before} <span aria-hidden="true">→</span><span className="atlas-sr-only"> changed to </span> {after}</>;
}

function ChangeList({ items }) {
  if (!items?.length) return <p className="atlas-comparison__empty">No changes</p>;
  return (
    <ul className="atlas-comparison__item-list">
      {items.map((item, index) => (
        <li key={`${item.item_id}-${index}`}>
          <span className="atlas-comparison__item-title">{item.label ?? item.item_id}</span>
          <span className="atlas-comparison__item-action">
            {item.source === 'AUTOMATIC_REPAIR' ? 'Automatic repair · ' : ''}{item.action?.toLowerCase() ?? 'changed'}
          </span>
          <span className="atlas-comparison__item-detail">
            <ChangeDetail before={valueName(item.before)} after={valueName(item.after)} />
          </span>
          {item.reason && <span className="atlas-comparison__item-reason">{item.reason}</span>}
          {item.price_difference_inr != null && <span className="atlas-comparison__item-price">{formatSignedINR(item.price_difference_inr)}</span>}
        </li>
      ))}
    </ul>
  );
}

function ProposalItems({ items = [] }) {
  return (
    <div className="atlas-comparison__categories">
      {SECTIONS.map(([type, label]) => {
        const group = items.filter((item) => item.type === type);
        return (
          <section key={type} className="atlas-comparison__category" aria-label={label}>
            <h4>{label}</h4>
            {group.length ? (
              <ul>
                {group.map((item) => (
                  <li key={item.item_id}>
                    <span>{item.name}{item.city ? ` · ${item.city}` : ''}</span>
                    {item.price_inr != null && <strong>{money(item.price_inr)}</strong>}
                  </li>
                ))}
              </ul>
            ) : <p className="atlas-comparison__empty">No items</p>}
          </section>
        );
      })}
    </div>
  );
}

function TextList({ items }) {
  if (!items?.length) return null;
  return <ul>{items.map((item, i) => <li key={i}>{typeof item === 'string' ? item : item?.message ?? String(item)}</li>)}</ul>;
}

/** Displays the server's proposed package and change disclosures without estimating missing data. */
export default function RouteComparison({ preview, currentPackage }) {
  if (!preview) return null;
  const proposed = preview.proposed_package;
  const changed = preview.changed_items ?? [];
  const changedKeys = new Set(changed.map((item) => `${item.item_id}\u0000${item.action}`));
  const repairs = (preview.automatic_repairs ?? []).filter(
    (item) => !changedKeys.has(`${item.item_id}\u0000${item.action}`),
  );
  const budget = preview.budget_inr ?? proposed?.budget_inr ?? currentPackage?.budget_inr;
  const difference = preview.price_difference_inr;
  const hasTotals = preview.old_total_inr != null || preview.new_total_inr != null;
  const cityChanges = preview.city_changes;

  return (
    <section className="atlas-comparison" aria-label="Route proposal" data-valid={String(Boolean(preview.valid))}>
      <header className="atlas-comparison__header">
        <div>
          <p className="eyebrow">Route proposal</p>
          <h2>{preview.valid ? 'Review your changes' : 'Route needs changes'}</h2>
        </div>
        <span className="atlas-comparison__status">{STATUS_TEXT[preview.status] ?? preview.status ?? (preview.valid ? 'Valid proposal' : 'Incomplete proposal')}</span>
      </header>

      <dl className="atlas-comparison__figures">
        {preview.old_total_inr != null && <div><dt>Current total</dt><dd>{money(preview.old_total_inr)}</dd></div>}
        {preview.new_total_inr != null && <div><dt>Proposed total</dt><dd>{money(preview.new_total_inr)}</dd></div>}
        {difference != null && <div><dt>Price difference</dt><dd>{formatSignedINR(difference)}</dd></div>}
        {budget != null && <div><dt>Budget</dt><dd>{money(budget)}</dd></div>}
        {preview.over_budget_inr != null && preview.over_budget_inr > 0 && <div><dt>Over budget</dt><dd>{money(preview.over_budget_inr)}</dd></div>}
        {!hasTotals && <div className="atlas-comparison__unknown" role="status">A complete price is not available for this proposal.</div>}
      </dl>

      <div className="atlas-comparison__routes">
        <p><span>Current route</span><strong>{routeText(currentPackage)}</strong></p>
        <p><span>Proposed route</span><strong>{routeText(proposed)}</strong></p>
      </div>

      {cityChanges && (
        <section className="atlas-comparison__city-changes" aria-label="Route changes">
          <h3>Route changes</h3>
          {!cityChanges.added?.length && !cityChanges.removed?.length && !cityChanges.reordered && !cityChanges.nights_changed?.length
            ? <p>No city changes</p>
            : <ul>
              {cityChanges.added?.map((city) => <li key={`add-${city}`}>Added {city}</li>)}
              {cityChanges.removed?.map((city) => <li key={`remove-${city}`}>Removed {city}</li>)}
              {cityChanges.reordered && <li>City order changed</li>}
              {cityChanges.nights_changed?.map((entry) => <li key={`night-${entry.city}`}>{entry.city}: {entry.old_nights} → {entry.new_nights} nights</li>)}
            </ul>}
        </section>
      )}

      {proposed && <section className="atlas-comparison__proposal-items" aria-label="Proposed package items">
        <h3>Proposed package</h3>
        <ProposalItems items={proposed.items ?? []} />
      </section>}

      {proposed?.days?.length > 0 && <details className="atlas-comparison__itinerary">
        <summary>Proposed itinerary</summary>
        <DayTimeline days={proposed.days} preview />
      </details>}

      <section className="atlas-comparison__disclosures" aria-label="What changes">
        <h3>Changed items</h3>
        {SECTIONS.map(([type, label]) => {
          const group = changed.filter((item) => item.type === type);
          if (!group.length) return null;
          return <section key={type} aria-label={`${label} changes`}><h4>{label}</h4><ChangeList items={group} /></section>;
        })}
        {!changed.length && <p className="atlas-comparison__empty">No changed items</p>}
      </section>

      {repairs.length > 0 && <section className="atlas-comparison__repairs">
        <h3>Automatic repairs</h3>
        {SECTIONS.map(([type, label]) => {
          const group = repairs.filter((item) => item.type === type);
          return group.length ? <section key={type} aria-label={`${label} repairs`}><h4>{label}</h4><ChangeList items={group} /></section> : null;
        })}
      </section>}

      {currentPackage?.items?.length > 0 && <details className="atlas-comparison__current-items">
        <summary>Current package items ({currentPackage.items.length})</summary>
        <ProposalItems items={currentPackage.items} />
      </details>}

      {preview.preserved_items?.length > 0 && <details className="atlas-comparison__preserved">
        <summary>Preserved items ({preview.preserved_items.length})</summary>
        <ul>{preview.preserved_items.map((item) => <li key={item.item_id}>{item.name ?? item.item_id} <span>{item.type}</span></li>)}</ul>
      </details>}

      {preview.warnings?.length > 0 && <section className="atlas-comparison__messages"><h3>Warnings</h3><TextList items={preview.warnings} /></section>}
      {preview.violations?.length > 0 && <section className="atlas-comparison__messages"><h3>Why this route cannot be used</h3><TextList items={preview.violations} /></section>}
    </section>
  );
}
