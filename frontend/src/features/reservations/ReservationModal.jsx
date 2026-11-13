import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';

const FOCUSABLE = 'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])';

export default function ReservationModal({ titleId, onClose, closeDisabled = false, children, className = '' }) {
  const dialogRef = useRef(null);
  const onCloseRef = useRef(onClose);
  const closeDisabledRef = useRef(closeDisabled);
  onCloseRef.current = onClose;
  closeDisabledRef.current = closeDisabled;

  useEffect(() => {
    const previous = document.activeElement;
    const dialog = dialogRef.current;
    dialog?.querySelector(FOCUSABLE)?.focus();

    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        if (!closeDisabledRef.current) {
          event.preventDefault();
          onCloseRef.current();
        }
        return;
      }
      if (event.key !== 'Tab' || !dialog) return;
      const controls = [...dialog.querySelectorAll(FOCUSABLE)];
      if (!controls.length) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      if (previous?.isConnected) previous.focus();
    };
  }, []);

  return createPortal(
    <div className="reservation-modal" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !closeDisabled) onClose(); }}>
      <section ref={dialogRef} className={`reservation-dialog ${className}`} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
        {children}
      </section>
    </div>,
    document.body,
  );
}
