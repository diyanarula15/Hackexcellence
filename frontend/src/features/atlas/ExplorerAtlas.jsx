import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { applyCityPlan, getCityPlanOptions, previewCityPlan } from '../../services/cityPlansApi.js';
import CountryMap from './CountryMap.jsx';
import EditRoute from './EditRoute.jsx';
import RouteComparison from './RouteComparison.jsx';
import { routeErrors } from './routeDraft.js';
import './ExplorerAtlas.css';

const sameRoute = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const FOCUSABLE = 'button:not(:disabled), input:not(:disabled), select:not(:disabled), a[href], [tabindex="0"]';

/** A dedicated overlay on the active saved package. Drafts and previews never touch its itinerary. */
export default function ExplorerAtlas({ pkg, onClose, onApplied, onReload }) {
  const [options, setOptions] = useState(null);
  const [draft, setDraft] = useState([]);
  const [focusedCity, setFocusedCity] = useState(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [state, setState] = useState('LOADING');
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const dialogRef = useRef(null);
  const requestRef = useRef(null);
  const sequence = useRef(0);
  const inFlight = useRef(false);
  const applying = useRef(false);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const busy = state === 'PREVIEW_LOADING' || state === 'APPLYING';

  async function load() {
    const mine = ++sequence.current;
    requestRef.current?.abort();
    requestRef.current = new AbortController();
    setState('LOADING'); setError(null); setPreview(null);
    try {
      const result = await getCityPlanOptions(pkg.id, { signal: requestRef.current.signal });
      if (mine !== sequence.current) return;
      if (result.base_version !== pkg.version) {
        setError({ code: 'PACKAGE_VERSION_CONFLICT', message: 'This holiday has changed. Reload the latest version before editing its route.' });
        setState('ERROR'); return;
      }
      setOptions(result); setDraft(result.current_city_plan.map((s) => ({ ...s })));
      setFocusedCity(null); setState('IDLE');
    } catch (err) {
      if (mine !== sequence.current || err.name === 'AbortError') return;
      setError({ message: err.message, code: err.body?.error }); setState('ERROR');
    }
  }

  useEffect(() => {
    load();
    const previous = document.activeElement;
    const oldOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    dialogRef.current?.querySelector(FOCUSABLE)?.focus();
    const onKeyDown = (event) => {
      if (event.key === 'Escape' && !applying.current) { event.preventDefault(); onCloseRef.current(); }
      if (event.key !== 'Tab') return;
      const controls = [...(dialogRef.current?.querySelectorAll(FOCUSABLE) ?? [])].filter((el) => el.getClientRects().length);
      if (!controls.length) { event.preventDefault(); dialogRef.current?.focus(); return; }
      const first = controls[0]; const last = controls[controls.length - 1];
      if (event.shiftKey && (document.activeElement === first || !dialogRef.current.contains(document.activeElement))) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !dialogRef.current.contains(document.activeElement))) {
        event.preventDefault(); first.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      sequence.current += 1; requestRef.current?.abort();
      document.removeEventListener('keydown', onKeyDown); document.body.style.overflow = oldOverflow;
      if (previous?.isConnected) previous.focus();
    };
  }, [pkg.id]);

  const changeDraft = (next) => {
    if (inFlight.current) return;
    sequence.current += 1;
    setDraft(next.map((s) => ({ ...s }))); setPreview(null); setAcknowledged(false); setError(null); setState('EDITING_DRAFT');
  };
  const focusCity = (city) => { setFocusedCity(city); setSheetOpen(true); };
  const errors = options ? routeErrors(draft, options) : [];
  const unchanged = options && sameRoute(draft, options.current_city_plan);

  async function requestPreview() {
    if (inFlight.current || errors.length || unchanged) return;
    const mine = ++sequence.current;
    inFlight.current = true; setState('PREVIEW_LOADING'); setError(null); setPreview(null); setAcknowledged(false);
    requestRef.current?.abort(); requestRef.current = new AbortController();
    try {
      const result = await previewCityPlan(pkg.id, options.base_version, draft, { signal: requestRef.current.signal });
      if (mine !== sequence.current) return;
      setPreview(result);
      setState(result.valid ? (result.status === 'OVER_BUDGET' ? 'PREVIEW_OVER_BUDGET' : 'PREVIEW_VALID')
        : result.status === 'SEARCH_INCOMPLETE' ? 'PREVIEW_INCOMPLETE' : 'PREVIEW_INFEASIBLE');
    } catch (err) {
      if (mine !== sequence.current || err.name === 'AbortError') return;
      setError({ message: err.message, code: err.body?.error, details: err.body?.errors }); setState('ERROR');
    } finally { if (mine === sequence.current) inFlight.current = false; }
  }

  async function apply() {
    if (inFlight.current || !preview?.valid || !preview.preview_token || (preview.status === 'OVER_BUDGET' && !acknowledged)) return;
    inFlight.current = true; applying.current = true;
    const mine = ++sequence.current;
    setState('APPLYING'); setError(null);
    try {
      const response = await applyCityPlan(pkg.id, options.base_version, draft, preview.preview_token);
      if (mine !== sequence.current) return;
      setState('APPLIED'); onApplied(response);
    } catch (err) {
      if (mine !== sequence.current) return;
      setError({ message: err.message, code: err.body?.error }); setPreview(null); setState('ERROR');
    } finally { inFlight.current = false; applying.current = false; }
  }
  const stale = ['PACKAGE_VERSION_CONFLICT', 'PREVIEW_OUTDATED'].includes(error?.code);
  // A preview that cannot be booked: say why next to the buttons, where the traveler is looking.
  const rejected = preview && !preview.valid;
  const firstReason = [...(preview?.violations ?? []), ...(preview?.warnings ?? [])]
    .map((item) => (typeof item === 'string' ? item : item?.message)).find(Boolean) ?? '';
  const rejectedReason = firstReason.replace(/^Every one of the \d+ possible city plan\(s\) fails for this reason:\s*/i, '');

  // The comparison renders below the route editor: bring it into view inside the side column.
  useEffect(() => {
    if (!preview) return;
    const editor = dialogRef.current?.querySelector('.atlas-editor');
    const comparison = editor?.querySelector('.atlas-comparison');
    if (!editor || !comparison) return;
    const top = editor.scrollTop + comparison.getBoundingClientRect().top - editor.getBoundingClientRect().top - 12;
    editor.scrollTo?.({ top, behavior: 'smooth' });
  }, [preview]);

  return createPortal(
    <div className="atlas-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !applying.current) onClose(); }}>
      <section className="atlas-shell" role="dialog" aria-modal="true" aria-labelledby="atlas-title" data-state={state} ref={dialogRef} tabIndex={-1}>
        <header className="atlas-header">
          <div><p className="atlas-kicker eyebrow">A new perspective on your holiday</p><h2 id="atlas-title">The Explorer’s Atlas</h2><p>Redesign your route · {pkg.country} · {pkg.nights} nights</p></div>
          <button type="button" className="atlas-close" aria-label="Close Explorer's Atlas" onClick={onClose} disabled={state === 'APPLYING'}>✕</button>
        </header>
        {state === 'LOADING' && <p className="atlas-loading" role="status">Opening your atlas…</p>}
        {options && <div className="atlas-layout">
          <div className="atlas-map-column">
            <div className="atlas-map-heading"><span>{options.country}</span><span>Field notes / {options.country_code}</span></div>
            <CountryMap countryCode={options.country_code} countryName={options.country} cities={options.cities}
              currentRoute={options.current_city_plan} draftRoute={draft} focusedCity={focusedCity}
              onSelectCity={focusCity} connections={options.connections} />
            <p className="atlas-map-caption">Select a city pin to edit your route. Connections are schematic, following catalog links.</p>
            <button type="button" className="btn atlas-mobile-edit" onClick={() => setSheetOpen(true)}>Edit Route · {draft.length} stops</button>
          </div>
          <aside className={`atlas-editor${sheetOpen ? ' is-open' : ''}`} aria-label="Edit your route">
            <button type="button" className="atlas-sheet-close" onClick={() => setSheetOpen(false)}>Return to map ↓</button>
            <EditRoute options={options} draft={draft} focusedCity={focusedCity} onFocusCity={focusCity} onDraftChange={changeDraft} disabled={busy} />
            <p className="atlas-structure-note">A connected route still needs compatible flights, rooms and schedules. Preview checks the complete holiday.</p>
            {preview && <RouteComparison preview={preview} currentPackage={pkg} />}
            {preview?.status === 'OVER_BUDGET' && preview.valid && <label className="atlas-acknowledge"><input type="checkbox" checked={acknowledged} onChange={(e) => setAcknowledged(e.target.checked)} disabled={busy} /> I accept the final total above my original budget.</label>}
          </aside>
        </div>}
        {error && <div className="atlas-error" role="alert"><p>{error.message}</p>
          {error.details?.map((e, i) => <p key={i}>{e.message}</p>)}
          {stale ? <button type="button" className="btn" onClick={onReload}>Reload latest holiday</button>
            : !options ? <button type="button" className="btn" onClick={load}>Try again</button> : null}
        </div>}
        <footer className="atlas-footer">
          <div><p role="status" aria-live="polite" className={rejected ? 'atlas-footer__rejected' : undefined}>{state === 'PREVIEW_LOADING' ? 'Checking flights, hotels, transfers and activities…' : state === 'APPLYING' ? 'Saving your new route…'
            : rejected ? `This route can't be booked${rejectedReason ? `: ${rejectedReason}` : '.'} Change the route, then preview again.`
            : preview?.valid ? (preview.status === 'OVER_BUDGET' && !acknowledged ? 'This route is above your budget. Tick the box under the comparison to accept the new total, then apply.' : 'Preview ready. Check the new total, then apply.')
            : unchanged ? 'Choose a city or change its nights to begin.' : errors.length ? 'Resolve the route issues before previewing.' : 'Your saved holiday stays unchanged until you apply.'}</p></div>
          <div className="atlas-footer-actions"><button type="button" className="btn" disabled={state === 'APPLYING'} onClick={onClose}>Keep Current Trip</button>
            {preview?.valid ? <button type="button" className="btn btn--primary" disabled={busy || stale || (preview.status === 'OVER_BUDGET' && !acknowledged)} onClick={apply}>{state === 'APPLYING' ? 'Applying…' : 'Apply New Route'}</button>
              : <button type="button" className="btn btn--primary" disabled={!options || busy || Boolean(errors.length) || unchanged || stale || rejected} onClick={requestPreview}>{state === 'PREVIEW_LOADING' ? 'Building preview…' : 'Preview New Route'}</button>}
          </div>
        </footer>
      </section>
    </div>, document.body,
  );
}
