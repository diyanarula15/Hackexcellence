
import { Fragment, useEffect, useRef, useState } from 'react';
import { useStore } from '../state/store.js';
import { exportReservation } from '../services/reservationsApi.js';
import PlaneButton from './PlaneButton.jsx';
import {
  bookingStore,
  dismissChangeNotice,
  exportCurrentPackage,
  generatePackage,
  openPackage,
  retryResult,
} from '../state/bookingStore.js';
import ChangeDrawer from './ChangeDrawer.jsx';
import DelayRescue from './DelayRescue.jsx';
import DayTimeline from './DayTimeline.jsx';
import ConfirmHoliday from './reservations/ConfirmHoliday.jsx';
import BookingConfirmation from './reservations/BookingConfirmation.jsx';
import { formatDate, formatINR, formatTravelers, humanize, plural, scrollToPlanner } from './format.js';
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
  return (
    <div className="notice" role="status">
      {response.cheapest_total_inr != null ? (
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
      <EditTrip />
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
        Saved package
      </h3>
      <p className="mono">{pkg.id}</p>
      <p className="results__muted">
        {humanize(pkg.status)} · version {pkg.version} ·{' '}
        <button type="button" className="link-button" onClick={copy}>
          {copied ? 'Copied' : 'Copy ID'}
        </button>
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
        </section>
      </div>
    </div>
  );
}

function Content({ result, receipt, onConfirmed }) {
  const { status, response } = result;
  switch (status) {
    case 'LOADING':
      return (
        <Notice eyebrow="Saved package" title="Loading your holiday…">
          <p className="mono results__muted">{result.packageId}</p>
        </Notice>
      );
    case 'NOT_FOUND':
      return (
        <Notice eyebrow="Saved package" title="Package not found">
          <p>{result.error}</p>
          <p className="mono results__muted">{result.packageId}</p>
          <div className="results__actions">
            <EditTrip label="Plan a new trip" />
          </div>
        </Notice>
      );
    case 'ERROR':
      return (
        <Notice eyebrow="Saved package" title="Could not load this package">
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
        <Notice eyebrow="No package possible" title="No holiday package can be built for this trip">
          <p>Every package must follow all travel rules. This request cannot, because:</p>
          <Reasons reasons={response.reasons} />
          <div className="results__actions">
            <EditTrip />
          </div>
        </Notice>
      );
    case 'SEARCH_INCOMPLETE':
      return (
        <Notice eyebrow="Search incomplete" title="The search stopped before it could finish">
          <p>This is not a proof that no package exists.</p>
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
