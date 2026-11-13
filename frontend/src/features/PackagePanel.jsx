
import { Fragment, Suspense, lazy, useEffect, useRef, useState } from 'react';
import { useStore } from '../state/store.js';
import { exportReservation } from '../services/reservationsApi.js';
import PlaneButton from './PlaneButton.jsx';
import {
  backToOptions,
  bookingStore,
  canGoBackToOptions,
  acceptCityPlan,
  dismissChangeNotice,
  exportCurrentPackage,
  generatePackage,
  openPackage,
  openPanel,
  retryResult,
  searchAlternative,
  startNewSearch,
} from '../state/bookingStore.js';
import ChangeDrawer from './ChangeDrawer.jsx';
import DelayRescue from './DelayRescue.jsx';
import AttractionDetails from './AttractionDetails.jsx';
import HotelDetails from './HotelDetails.jsx';
import PhotoCredits from './PhotoCredits.jsx';
import DayTimeline from './DayTimeline.jsx';
import SaveTripButton from './saved-trips/SaveTripButton.jsx';
import PackageOptions from './package-options/PackageOptions.jsx';
import ConfirmHoliday from './reservations/ConfirmHoliday.jsx';
import BookingConfirmation from './reservations/BookingConfirmation.jsx';
import { formatDate, formatINR, formatTravelers, humanize, plural, scrollToPlanner } from './format.js';
const ExplorerAtlas = lazy(() => import('./atlas/ExplorerAtlas.jsx'));
const PRICE_ROWS = [
  ['flights', 'Flights'],
  ['hotels', 'Hotels'],
  ['airport_transfers', 'Airport transfers'],
  ['intercity_transfers', 'Transfers between cities'],
  ['attractions', 'Attractions'],
];

function Notice({ eyebrow, title, children }) {
  return (
    <div className="results__notice">
      <p className="eyebrow">{eyebrow}</p>
      <h2 className="results__title" id="results-title">
        {title}
      </h2>
      {children}
    </div>
  );
}

function Reasons({ reasons }) {
  if (!reasons?.length) return null;
  return (
    <ul className="results__reasons">
      {reasons.map((reason) => (
        <li key={reason}>{reason}</li>
      ))}
    </ul>
  );
}

function EditTrip({ label = 'Edit the trip' }) {
  return (
    <button type="button" className="btn" onClick={scrollToPlanner}>
      {label}
    </button>
  );
}

/** Back to the options list this package was chosen from (only shown when there is one). */
function BackToOptions() {
  const canGoBack = useStore(bookingStore, canGoBackToOptions);
  const count = useStore(bookingStore, (s) => s.optionsBack?.response?.options?.length ?? 0);
  if (!canGoBack) return null;
  return (
    <button type="button" className="btn back-to-options" onClick={backToOptions}>
      <span aria-hidden="true">←</span> Back to all {count > 1 ? `${count} ` : ''}options
    </button>
  );
}

/** Leave this package (it stays saved, reopen it with its id) and start a fresh search. */
function NewSearch({ label = 'Search a new trip' }) {
  return (
    <button
      type="button"
      className="btn new-search"
      onClick={() => {
        startNewSearch();
        scrollToPlanner();
      }}
    >
      {label}
    </button>
  );
}

const KIND_LABEL = { START_DATE: 'Different start date', DEPARTURE: 'Different departure city', NIGHTS: 'Different length' };

/**
 * Why no (affordable) holiday was found: the backend's explanation. A reason is worded as the
 * cause only when it blocked every option (scope ALL / REQUEST); partial ones are listed apart.
 */
function Explanation({ explanation, fallbackReasons }) {
  if (!explanation) return <Reasons reasons={fallbackReasons} />;
  // A reason the summary already states word for word is not listed again.
  const summary = explanation.summary ?? '';
  const main = explanation.reasons.filter((r) => r.scope !== 'SOME' && !summary.includes(r.message));
  const partial = explanation.reasons.filter((r) => r.scope === 'SOME');
  return (
    <div className="explanation">
      {explanation.summary && <p className="explanation__summary">{explanation.summary}</p>}
      {main.length > 0 && (
        <ul className="results__reasons">
          {main.map((r) => (
            <li key={`${r.code}:${r.message}`}>{r.message}</li>
          ))}
        </ul>
      )}
      {partial.length > 0 && (
        <details className="explanation__partial">
          <summary>What else ruled out some options</summary>
          <ul>
            {partial.map((r) => (
              <li key={`${r.code}:${r.message}`}>{r.message}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

/** "If you change X you'll find one": the nearest one-field changes that do have a holiday. */
function Alternatives({ maxTotal = null, title = 'Nearest trips that work' }) {
  const alternatives = useStore(bookingStore, (s) => s.alternatives);
  const submit = useStore(bookingStore, (s) => s.submit);
  const busy = submit.status === 'loading';
  if (alternatives.status === 'idle') return null;
  if (alternatives.status === 'loading') {
    return <p className="alternatives__status" aria-live="polite">Looking for the nearest trip that works…</p>;
  }
  if (alternatives.status === 'error') {
    return <p className="alternatives__status">Could not look for nearby trips: {alternatives.error}</p>;
  }
  // over budget: only show changes that actually cost less than the cheapest trip for this search
  const suggestions = (alternatives.data?.suggestions ?? []).filter(
    (s) => maxTotal == null || s.min_total_inr < maxTotal,
  );
  if (!suggestions.length && maxTotal != null) return null;
  if (!suggestions.length) {
    return (
      <p className="alternatives__status">
        No trip works within a week of this date, from another departure city, or with a few nights more or less.
        Try another country or fewer travelers.
      </p>
    );
  }
  return (
    <section className="alternatives" aria-labelledby="alternatives-title">
      <h3 className="eyebrow" id="alternatives-title">{title}</h3>
      <ul className="alternatives__list">
        {suggestions.map((s) => (
          <li key={`${s.kind}:${s.change.to}`} className="alternatives__item">
            <span className="alternatives__kind">{KIND_LABEL[s.kind] ?? humanize(s.kind)}</span>
            <span className="alternatives__label">{s.label}</span>
            <span className="alternatives__price">
              <span className="alternatives__from">from</span> <strong>{formatINR(s.min_total_inr)}</strong>
              {!s.within_budget && <span className="is-over"> · over budget</span>}
            </span>
            <button
              type="button"
              className="btn btn--small btn--primary"
              disabled={busy}
              onClick={() => searchAlternative(s)}
            >
              Search this trip
            </button>
          </li>
        ))}
      </ul>
      <p className="alternatives__note">Prices are the cheapest complete holiday for that search, already checked by the planner.</p>
    </section>
  );
}

function Route({ pkg }) {
  return (
    <ol className="route" aria-label="Route">
      <li className="route__stop route__stop--home">{pkg.departure.city}</li>
      {pkg.city_plan.map((stay) => (
        <li key={stay.stay_id} className="route__stop">
          <strong>{stay.city}</strong> · {plural(stay.nights, 'night')}
        </li>
      ))}
      <li className="route__stop route__stop--home">{pkg.departure.city}</li>
    </ol>
  );
}

function OverBudget({ response }) {
  const explanation = response.explanation;
  return (
    <div className="notice" role="status">
      <p className="notice__eyebrow">Over budget</p>
      {explanation ? (
        <>
          <p className="notice__title">{explanation.headline}.</p>
          <p>{explanation.summary} It is shown below.</p>
        </>
      ) : response.cheapest_total_inr != null ? (
        <>
          <p className="notice__title">No package fits your budget.</p>
          <p>
            The cheapest package that follows every travel rule costs{' '}
            <strong>{formatINR(response.cheapest_total_inr)}</strong>,{' '}
            <strong>{formatINR(response.shortfall_inr)}</strong> over your budget. It is shown below.
          </p>
        </>
      ) : (
        <>
          <p className="notice__title">This package is over your budget.</p>
          <p>
            It costs <strong>{formatINR(response.package.total_inr)}</strong>,{' '}
            <strong>{formatINR(response.shortfall_inr)}</strong> more than your budget.
          </p>
        </>
      )}
      <Reasons reasons={response.suggestions} />
      <Alternatives maxTotal={response.cheapest_total_inr ?? response.package?.total_inr} title="Cheaper searches nearby" />
      <div className="notice__actions">
        <EditTrip />
      </div>
    </div>
  );
}

function Budget({ budget }) {
  const share = Math.min(budget.total_inr / Math.max(budget.budget_inr, 1), 1);
  return (
    <section aria-labelledby="budget-title">
      <h3 className="eyebrow" id="budget-title">
        Total
      </h3>
      <p className="budget__total">{formatINR(budget.total_inr)}</p>
      <div className="meter" aria-hidden="true">
        <div className={`meter__fill${budget.within_budget ? '' : ' meter__fill--over'}`} style={{ width: `${share * 100}%` }} />
      </div>
      <dl className="rows">
        <dt>Budget</dt>
        <dd>{formatINR(budget.budget_inr)}</dd>
        {budget.within_budget ? (
          <>
            <dt>Left</dt>
            <dd>{formatINR(budget.remaining_inr)}</dd>
          </>
        ) : (
          <>
            <dt className="is-over">Over budget by</dt>
            <dd className="is-over">{formatINR(budget.over_budget_inr)}</dd>
          </>
        )}
      </dl>
    </section>
  );
}

function Prices({ pricing }) {
  return (
    <section aria-labelledby="prices-title">
      <h3 className="eyebrow" id="prices-title">
        Price breakdown
      </h3>
      <dl className="rows">
        {PRICE_ROWS.map(([key, label]) => (
          <Fragment key={key}>
            <dt>{label}</dt>
            <dd>{formatINR(pricing[key])}</dd>
          </Fragment>
        ))}
        <dt className="rows__total">Total</dt>
        <dd className="rows__total">{formatINR(pricing.total_inr)}</dd>
      </dl>
    </section>
  );
}

function ExportButton() {
  const exporting = useStore(bookingStore, (s) => s.exporting);
  const busy = exporting.status === 'loading';
  return (
    <div className="export">
      <PlaneButton label="Export JSON" busyLabel="Preparing…" busy={busy} onClick={exportCurrentPackage} />
      <p className="export__status" aria-live="polite">
        {exporting.status === 'done' && `Downloaded ${exporting.name}`}
        {exporting.status === 'error' && <span className="is-over">{exporting.error}</span>}
      </p>
    </div>
  );
}

function SavedAs({ pkg }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(pkg.id);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };
  return (
    <section aria-labelledby="saved-title">
      <h3 className="eyebrow" id="saved-title">
        Package ID
      </h3>
      <p className="mono">{pkg.id}</p>
      <p className="results__muted">
        {humanize(pkg.status)} · version {pkg.version} ·{' '}
        <button type="button" className="link-button" onClick={copy}>
          {copied ? 'Copied' : 'Copy ID'}
        </button>
      </p>
      <p className="results__muted">
        Every plan gets an ID automatically, so you can reopen it from “Package ID” in the top bar. To keep it in
        your list, use Save trip.
      </p>
    </section>
  );
}

function ChangeNotice() {
  const notice = useStore(bookingStore, (s) => s.change.notice);
  if (!notice) return null;
  return (
    <p className="change-notice" role="status">
      {notice}{' '}
      <button type="button" className="link-button" onClick={dismissChangeNotice}>
        Dismiss
      </button>
    </p>
  );
}

function PackageView({ response, receipt, onConfirmed }) {
  const pkg = response.package;
  const [reviewOpen, setReviewOpen] = useState(false);
  const [atlasOpen, setAtlasOpen] = useState(false);
  const [exportingReservation, setExportingReservation] = useState(false);
  const [exportError, setExportError] = useState('');
  const reference = pkg.booking_reference ?? receipt?.reference;
  const exportBooked = async () => {
    if (!reference || exportingReservation) return;
    setExportingReservation(true);
    setExportError('');
    try {
      await exportReservation(reference);
    } catch (error) {
      setExportError(error.message);
    } finally {
      setExportingReservation(false);
    }
  };
  return (
    <div className="pkg">
      <ChangeNotice />
      <ChangeDrawer />
      <DelayRescue />
      <AttractionDetails />
      <HotelDetails />
      {atlasOpen && <Suspense fallback={<p role="status">Opening your atlas…</p>}><ExplorerAtlas key={`${pkg.id}:${pkg.version}`} pkg={pkg}
        onClose={() => setAtlasOpen(false)}
        onReload={() => { setAtlasOpen(false); openPackage(pkg.id); }}
        onApplied={(updated) => { acceptCityPlan(updated); setAtlasOpen(false); }} /></Suspense>}
      {reviewOpen && <ConfirmHoliday pkg={pkg} onClose={() => setReviewOpen(false)} onConfirmed={onConfirmed} />}
      <header className="pkg__header">
        <p className="eyebrow">Your holiday package</p>
        <h2 className="pkg__title" id="results-title">
          {plural(pkg.nights, 'night')} in {pkg.country}
        </h2>
        <p className="pkg__facts">
          <span>
            {formatDate(pkg.start_date)} – {formatDate(pkg.end_date)}
          </span>
          <span>{formatTravelers(pkg.travelers)}</span>
          <span>
            From {pkg.departure.city} ({pkg.departure.airport})
          </span>
        </p>
        <Route pkg={pkg} />
        <div className="pkg__header-actions">
          <BackToOptions />
          {pkg.status === 'PLANNED' && <button type="button" className="btn" onClick={() => setAtlasOpen(true)}>Explore &amp; Change Cities</button>}
          <NewSearch />
        </div>
      </header>

      {response.status === 'OVER_BUDGET' && <OverBudget response={response} />}

      {reference && (
        <BookingConfirmation
          reference={reference}
          total={receipt?.total_inr ?? pkg.total_inr}
          confirmedAt={receipt?.confirmed_at ?? (pkg.status === 'BOOKED' ? pkg.updated_at : undefined)}
          onExport={exportBooked}
          busy={exportingReservation}
        />
      )}

      <div className="pkg__grid">
        <aside className="pkg__aside" aria-label="Price and budget">
          <Budget budget={pkg.budget} />
          <Prices pricing={pkg.pricing} />
          {pkg.status === 'PLANNED' && (
            <div className="confirm-booking">
              <button type="button" className="btn btn--primary" onClick={() => setReviewOpen(true)}>Confirm Holiday</button>
              <p>Confirm this saved itinerary when you are ready to book.</p>
            </div>
          )}
          <SaveTripButton key={pkg.id ?? pkg.package_id} pkg={pkg} onViewSaved={() => openPanel('saved')} />
          {reference && (
            <p className="export__status" aria-live="polite">
              {exportingReservation && 'Preparing itinerary…'}
              {exportError && <span className="is-over">{exportError}</span>}
            </p>
          )}
          <ExportButton />
          <SavedAs pkg={pkg} />
        </aside>
        <section className="pkg__main" aria-labelledby="days-title">
          <h3 className="eyebrow" id="days-title">
            Day by day · all times local
          </h3>
          <DayTimeline days={pkg.days} editable={pkg.status === 'PLANNED'} />
          <PhotoCredits />
        </section>
      </div>
    </div>
  );
}

function Content({ result, receipt, onConfirmed }) {
  const { status, response } = result;
  switch (status) {
    case 'SEARCHING':
    case 'OPTIONS':
      return <PackageOptions />; // pick your trip: several complete options, nothing saved yet
    case 'LOADING':
      return (
        <Notice eyebrow="Your package" title="Loading your holiday…">
          <p className="mono results__muted">{result.packageId}</p>
        </Notice>
      );
    case 'NOT_FOUND':
      return (
        <Notice eyebrow="Your package" title="Package not found">
          <p>{result.error}</p>
          <p className="mono results__muted">{result.packageId}</p>
          <div className="results__actions">
            <EditTrip label="Plan a new trip" />
          </div>
        </Notice>
      );
    case 'ERROR':
      return (
        <Notice eyebrow="Your package" title="Could not load this package">
          <p>{result.error}</p>
          <div className="results__actions">
            <button type="button" className="btn btn--primary" onClick={retryResult}>
              Try again
            </button>
            <EditTrip label="Plan a new trip" />
          </div>
        </Notice>
      );
    case 'INFEASIBLE':
      return (
        <Notice
          eyebrow="No package possible"
          title={response.explanation?.headline ?? 'No holiday package can be built for this trip'}
        >
          {!response.explanation && <p>Every package must follow all travel rules. This request cannot, because:</p>}
          <Explanation explanation={response.explanation} fallbackReasons={response.reasons} />
          <Alternatives />
          <div className="results__actions">
            <EditTrip />
            <NewSearch label="Start a new search" />
          </div>
        </Notice>
      );
    case 'SEARCH_INCOMPLETE':
      return (
        <Notice
          eyebrow="Search incomplete"
          title={response.explanation?.headline ?? 'The search stopped before it could finish'}
        >
          <p>{response.explanation?.summary ?? 'This is not a proof that no package exists.'}</p>
          <Reasons reasons={response.reasons} />
          <div className="results__actions">
            <button type="button" className="btn btn--primary" onClick={generatePackage}>
              Try again
            </button>
            <EditTrip />
          </div>
        </Notice>
      );
    default:
      return response?.package ? <PackageView response={response} receipt={receipt} onConfirmed={onConfirmed} /> : null;
  }
}

/** @returns {JSX.Element | null} */
export default function PackagePanel() {
  const result = useStore(bookingStore, (s) => s.result);
  const ref = useRef(null);
  const [receipt, setReceipt] = useState(null);

  useEffect(() => {
    if (result.focus > 0) ref.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [result.focus]);

  if (result.status === 'EMPTY') return null; // the slot collapses
  return (
    <section
      ref={ref}
      className="results"
      id="holiday"
      aria-labelledby="results-title"
      aria-busy={result.status === 'LOADING'}
    >
      <Content
        result={result}
        receipt={receipt?.package_id === result.packageId ? receipt : null}
        onConfirmed={(confirmation) => {
          setReceipt(confirmation);
          openPackage(result.packageId);
        }}
      />
    </section>
  );
}
