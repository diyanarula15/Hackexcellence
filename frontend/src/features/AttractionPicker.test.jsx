/**
 * AttractionPicker: ticks build one selection, duplicates are impossible, Clear empties it and Preview
 * sends the whole selection once. The store module is mocked; its state is a real store so ticks re-render.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
// (plain assertions: jest-dom is not part of this project's test setup)
import userEvent from '@testing-library/user-event';

vi.mock('../state/bookingStore.js', async () => {
  const { createStore } = await import('../state/store.js');
  const bookingStore = createStore({
    result: {
      response: {
        package: {
          days: [
            { date: '2027-04-10', city: 'Tokyo' },
            { date: '2027-04-11', city: 'Tokyo' },
            { date: '2027-04-12', city: 'Osaka' },
            { date: '2027-04-13', city: 'Osaka' },
          ],
        },
      },
    },
    attractionSelection: [],
  });
  return {
    bookingStore,
    toggleAttractionSelection: vi.fn((entry) => {
      const state = bookingStore.getState();
      const has = state.attractionSelection.some((e) => e.attraction_id === entry.attraction_id);
      bookingStore.setState({
        attractionSelection: has
          ? state.attractionSelection.filter((e) => e.attraction_id !== entry.attraction_id)
          : [...state.attractionSelection, { preferred_start: null, ...entry }],
      });
    }),
    updateAttractionSelection: vi.fn(),
    clearAttractionSelection: vi.fn(() => bookingStore.setState({ attractionSelection: [] })),
    previewSelectedAttractions: vi.fn(),
    openAttractionDetails: vi.fn(),
    selectChangeOption: vi.fn(),
  };
});

import AttractionPicker from './AttractionPicker.jsx';
import { bookingStore, clearAttractionSelection, previewSelectedAttractions, toggleAttractionSelection } from '../state/bookingStore.js';

const option = (catalog_id, name, extra = {}) => ({
  catalog_id,
  name,
  valid: true,
  current: false,
  item_price_inr: 0,
  command: { kind: 'ADD_ATTRACTION', date: '2027-04-11', attraction_id: catalog_id },
  reasons: [],
  details: { city: 'Tokyo', category: 'culture', visit_minutes: 60, open_from: '09:00', open_until: '17:00' },
  ...extra,
});

const OPTIONS = {
  date: '2027-04-11',
  alternatives: [
    option('ATT-TYO-009', 'Ameyoko Market'),
    option('ATT-TYO-010', 'Meiji Jingu'),
    option('ATT-TYO-004', 'Senso-ji', {
      valid: false,
      reasons: ['Senso-ji is already in this holiday on Sat 10 Apr 2027 at 10:00; an attraction can be visited only once.'],
    }),
  ],
};

function renderPicker() {
  return render(<AttractionPicker options={OPTIONS} date="2027-04-11" busy={false} />);
}

beforeEach(() => {
  bookingStore.setState({ attractionSelection: [] });
  vi.clearAllMocks();
});
afterEach(cleanup);

describe('AttractionPicker', () => {
  it('ticking attractions updates the count', async () => {
    const user = userEvent.setup();
    renderPicker();
    expect(screen.getByText('0 attractions selected')).toBeTruthy();

    await user.click(screen.getByRole('checkbox', { name: 'Ameyoko Market' }));
    expect(screen.getByText('1 attraction selected')).toBeTruthy();
    expect(toggleAttractionSelection).toHaveBeenLastCalledWith({
      attraction_id: 'ATT-TYO-009', name: 'Ameyoko Market', city: 'Tokyo', date: '2027-04-11',
    });

    await user.click(screen.getByRole('checkbox', { name: 'Meiji Jingu' }));
    expect(screen.getByText('2 attractions selected')).toBeTruthy();
  });

  it('a duplicate tick cannot add the same attraction twice', async () => {
    const user = userEvent.setup();
    renderPicker();
    const box = screen.getByRole('checkbox', { name: 'Ameyoko Market' });
    await user.click(box);
    expect(bookingStore.getState().attractionSelection.map((e) => e.attraction_id)).toEqual(['ATT-TYO-009']);
    await user.click(box); // the second tick on the same attraction unticks it
    expect(bookingStore.getState().attractionSelection).toEqual([]);
    expect(screen.getByText('0 attractions selected')).toBeTruthy();
  });

  it('already-planned and invalid options are disabled and show their reason', () => {
    renderPicker();
    const planned = screen.getByRole('checkbox', { name: 'Senso-ji' });
    expect(planned.disabled).toBe(true);
    expect(screen.getByText(/already in this holiday/)).toBeTruthy();
    expect(screen.getByRole('checkbox', { name: 'Ameyoko Market' }).disabled).toBe(false);
  });

  it('Clear empties the selection', async () => {
    const user = userEvent.setup();
    renderPicker();
    await user.click(screen.getByRole('checkbox', { name: 'Ameyoko Market' }));
    await user.click(screen.getByRole('checkbox', { name: 'Meiji Jingu' }));
    await user.click(screen.getByRole('button', { name: 'Clear' }));
    expect(clearAttractionSelection).toHaveBeenCalledTimes(1);
    expect(screen.getByText('0 attractions selected')).toBeTruthy();
  });

  it('Preview calls previewSelectedAttractions once for the whole selection', async () => {
    const user = userEvent.setup();
    renderPicker();
    await user.click(screen.getByRole('checkbox', { name: 'Ameyoko Market' }));
    await user.click(screen.getByRole('checkbox', { name: 'Meiji Jingu' }));
    await user.click(screen.getByRole('button', { name: 'Preview 2 attractions' }));
    expect(previewSelectedAttractions).toHaveBeenCalledTimes(1);
  });

  it('the single-option Choose button still calls selectChangeOption', async () => {
    const user = userEvent.setup();
    const { selectChangeOption } = await import('../state/bookingStore.js');
    renderPicker();
    const row = document.querySelector('[data-catalog-id="ATT-TYO-010"]');
    await user.click(within(row).getByRole('button', { name: 'Choose' }));
    expect(selectChangeOption).toHaveBeenCalledWith(OPTIONS.alternatives[1]);
    expect(screen.getByText('0 attractions selected')).toBeTruthy();
  });
});
