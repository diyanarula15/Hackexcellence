/**
 * price-landscape/ExploreDatesButton.jsx — the entry point next to the request form.
 *
 * Uses the SAME request the form would send (bookingStore.toRequestBody); there is no second
 * traveler model. Generating for a chosen date sets the form's start date and runs the normal
 * package generation, which saves a NEW package and opens it — an existing package is never
 * modified here.
 */

import { useRef, useState } from 'react';
import { useStore } from '../../state/store.js';
import { bookingStore, generatePackage, setField, toRequestBody } from '../../state/bookingStore.js';
import PriceLandscape from './PriceLandscape.jsx';

export default function ExploreDatesButton() {
  const form = useStore(bookingStore, (s) => s.form);
  const meta = useStore(bookingStore, (s) => s.meta);
  const [open, setOpen] = useState(false);
  const [trip, setTrip] = useState(null);
  const triggerRef = useRef(null);

  const ready = Boolean(form.departure && form.country && form.start_date && form.nights && form.adults);
  const country = meta.data?.countries?.find(
    (c) => c.name.toLowerCase() === String(form.country).toLowerCase() || c.code === form.country);

  function close() {
    setOpen(false);
    setTimeout(() => triggerRef.current?.focus(), 0);
  }

  async function generateFor(date) {
    setField('start_date', date);
    await generatePackage({ objective: 'MINIMUM_COST' }); // matches the proven minimum shown
    const { submit } = bookingStore.getState();
    if (submit.status === 'invalid' || submit.status === 'error') {
      throw new Error(submit.message ?? 'The holiday could not be generated.');
    }
    setOpen(false);
  }

  return (
    <>
      <button
        type="button"
        ref={triggerRef}
        className="btn btn--small pl-entry"
        disabled={!ready}
        aria-describedby={ready ? undefined : 'pl-entry-hint'}
        onClick={() => {
          setTrip(toRequestBody(form)); // a snapshot: editing the form does not refetch mid-browse
          setOpen(true);
        }}
      >
        Explore flexible dates
      </button>
      {!ready && (
        <span id="pl-entry-hint" className="pl-entry__hint">Fill in from, to, first day, nights and adults to compare dates.</span>
      )}
      {open && trip && (
        <PriceLandscape
          trip={trip}
          window={meta.data?.allowed_dates ?? null}
          countryName={country?.name}
          onClose={close}
          onGenerate={generateFor}
        />
      )}
    </>
  );
}
