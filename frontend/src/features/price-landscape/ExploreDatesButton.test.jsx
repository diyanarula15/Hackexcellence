/**
 * Audit regression: generating from the Price Landscape asks for the proven-minimum package
 * (objective MINIMUM_COST) with the chosen start date and the traveler's other details unchanged.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const { FORM, store } = vi.hoisted(() => ({
  FORM: { departure: 'BLR', country: 'Japan', start_date: '2027-04-10', nights: '6', adults: '2',
    child_ages: '6', budget: '350000' },
  store: { state: null, calls: [] },
}));

vi.mock('../../state/bookingStore.js', () => {
  store.state = {
    form: { ...FORM },
    meta: { status: 'ready', data: { allowed_dates: { first_night: '2027-04-01', last_departure: '2027-04-20' },
      countries: [{ code: 'JP', name: 'Japan' }] } },
    submit: { status: 'idle' },
  };
  return {
    bookingStore: { getState: () => store.state, subscribe: () => () => {} },
    setField: (name, value) => { store.state = { ...store.state, form: { ...store.state.form, [name]: value } }; },
    generatePackage: vi.fn(async (options) => { store.calls.push({ form: { ...store.state.form }, options }); }),
    toRequestBody: (form) => ({ departure: form.departure, country: form.country, start_date: form.start_date,
      nights: Number(form.nights), adults: Number(form.adults), child_ages: [Number(form.child_ages)],
      budget: Number(form.budget) }),
  };
});

vi.mock('./PriceLandscape.jsx', () => ({
  default: ({ onGenerate }) => <button type="button" onClick={() => onGenerate('2027-04-12')}>pick 12 April</button>,
}));

import ExploreDatesButton from './ExploreDatesButton.jsx';

afterEach(cleanup);

describe('ExploreDatesButton → generation', () => {
  it('generates the MINIMUM_COST package for the chosen date, other trip details unchanged', async () => {
    const user = userEvent.setup();
    render(<ExploreDatesButton />);
    await user.click(screen.getByRole('button', { name: 'Explore flexible dates' }));
    await user.click(screen.getByRole('button', { name: 'pick 12 April' }));
    await waitFor(() => expect(store.calls).toHaveLength(1));
    expect(store.calls[0].options).toEqual({ objective: 'MINIMUM_COST' });
    expect(store.calls[0].form).toEqual({ ...FORM, start_date: '2027-04-12' });
  });
});
