// "Photo credits": the dataset's photos come from Wikimedia Commons and must be credited where
// they are shown. A link under the itinerary opens the full list (source, author, license).

import { useEffect, useId, useRef, useState } from 'react';
import { getPhotoCredits } from '../services/hotelsApi.js';
import './AttractionDetails.css';

export default function PhotoCredits() {
  const [open, setOpen] = useState(false);
  const [load, setLoad] = useState({ status: 'idle', credits: [], error: null });
  const titleId = useId();
  const dialogRef = useRef(null);
  const openerRef = useRef(null);

  const loadedRef = useRef(false);

  useEffect(() => {
    if (!open || loadedRef.current) return undefined; // the list never changes: fetch it once
    const controller = new AbortController();
    setLoad({ status: 'loading', credits: [], error: null });
    getPhotoCredits({ signal: controller.signal })
      .then((data) => {
        loadedRef.current = true;
        setLoad({ status: 'ready', credits: data.credits ?? [], error: null });
      })
      .catch((error) => {
        if (error?.name !== 'AbortError') setLoad({ status: 'error', credits: [], error: error.message });
      });
    return () => controller.abort();
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;
    dialogRef.current?.focus();
    const onKey = (event) => {
      if (event.key === 'Escape') setOpen(false);
      if (event.key !== 'Tab') return;

      const dialog = dialogRef.current;
      if (!dialog) return;
      const candidates = [...dialog.querySelectorAll(
        'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
      )];
      const isVisible = (element) => {
        for (let current = element; current && current !== dialog.parentElement; current = current.parentElement) {
          const style = window.getComputedStyle(current);
          if (current.hidden || style.display === 'none' || style.visibility === 'hidden') return false;
        }
        return true;
      };
      const controls = candidates.filter(isVisible);
      if (!controls.length) {
        event.preventDefault();
        dialog.focus();
        return;
      }

      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && (document.activeElement === dialog || document.activeElement === first || !dialog.contains(document.activeElement))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      openerRef.current?.focus?.();
    };
  }, [open]);

  return (
    <>
      <p className="photo-credits__note">
        Photos: Wikimedia Commons. Hotel photos are sample rooms.{' '}
        <button
          type="button"
          className="photo-credits__link"
          aria-haspopup="dialog"
          onClick={(e) => {
            openerRef.current = e.currentTarget;
            setOpen(true);
          }}
        >
          Photo credits
        </button>
      </p>
      {open && (
        <>
          <div className="attraction-details__backdrop" aria-hidden="true" onClick={() => setOpen(false)} />
          <aside
            ref={dialogRef}
            className="attraction-details"
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            tabIndex={-1}
          >
            <header className="attraction-details__header">
              <div className="attraction-details__titles">
                <h2 id={titleId} className="attraction-details__title">Photo credits</h2>
                <p className="attraction-details__sub">Wikimedia Commons, free licenses (CC0, CC BY, CC BY-SA)</p>
              </div>
              <button type="button" className="attraction-details__close" aria-label="Close" onClick={() => setOpen(false)}>
                ✕
              </button>
            </header>
            <div className="attraction-details__body">
              {load.status === 'loading' && <p className="attraction-details__status" role="status">Loading…</p>}
              {load.status === 'error' && <p className="attraction-details__error" role="alert">{load.error}</p>}
              {load.status === 'ready' && (
                <ul className="photo-credits__list">
                  {load.credits.map((c) => (
                    <li key={c.file}>
                      <span className="photo-credits__used">{c.used_for}</span>
                      {c.author} ·{' '}
                      {c.license_url ? (
                        <a href={c.license_url} target="_blank" rel="noopener noreferrer">{c.license}</a>
                      ) : (
                        c.license
                      )}{' '}
                      ·{' '}
                      {c.source_url ? (
                        <a href={c.source_url} target="_blank" rel="noopener noreferrer">source</a>
                      ) : (
                        c.source
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </aside>
        </>
      )}
    </>
  );
}
