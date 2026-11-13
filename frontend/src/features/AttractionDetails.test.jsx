/**
 * The attraction detail drawer: right data per id, photo fallback, map link, Escape, and the
 * change actions per package status.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const { mocks } = vi.hoisted(() => ({
  mocks: {
    getAttraction: vi.fn(),
    closeAttractionDetails: vi.fn(),
    previewRemoveAttraction: vi.fn(),
    toggleAttractionSelection: vi.fn(),
  },
}));

vi.mock('../services/attractionsApi.js', () => ({ getAttraction: mocks.getAttraction }));

vi.mock('../state/bookingStore.js', async () => {
  const { createStore } = await import('../state/store.js');
  const bookingStore = createStore({
    attractionDetails: { open: false, attraction_id: null, item_id: null, date: null },
    attractionSelection: [],
    result: { response: null },
  });
  return {
    bookingStore,
    closeAttractionDetails: mocks.closeAttractionDetails,
    previewRemoveAttraction: mocks.previewRemoveAttraction,
    toggleAttractionSelection: mocks.toggleAttractionSelection,
  };
});

import { bookingStore } from '../state/bookingStore.js';
import AttractionDetails from './AttractionDetails.jsx';

const KYOTO = {
  attraction_id: 'ATT-KYO-001', name: 'Kiyomizu-dera', name_ja: '清水寺', city: 'Kyoto', country: 'Japan',
  category: 'TEMPLE', open_days: ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'], open_from: '06:00',
  open_until: '18:00', closed_dates: [], visit_minutes: 90, child_friendly: true, accessible: false,
  price_per_person_inr: 280, child_price_inr: 112, image_url: '/api/attractions/ATT-KYO-001/image',
  image_credit: 'Photo: Martin Falbisoner, CC BY-SA 4.0 (Wikimedia Commons)',
  maps_url: `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent('Kiyomizu-dera, Kyoto, Japan')}`,
};

const OSAKA = {
  attraction_id: 'ATT-OSA-003', name: 'Osaka Castle', name_ja: null, city: 'Osaka', country: 'Japan',
  category: 'CASTLE', open_days: ['TUE', 'SAT'], open_from: '09:00', open_until: '17:00', closed_dates: ['2027-04-12'],
  visit_minutes: 60, child_friendly: true, accessible: true, price_per_person_inr: 0, child_price_inr: null,
  image_url: '/api/attractions/ATT-OSA-003/image', image_credit: 'Photo: X, CC0 (Wikimedia Commons)',
  maps_url: `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent('Osaka Castle, Osaka, Japan')}`,
};

const DATA = { 'ATT-KYO-001': KYOTO, 'ATT-OSA-003': OSAKA };

function packageWith({ status = 'PLANNED', visit = null } = {}) {
  const days = [{ date: '2027-04-10', events: visit ? [visit] : [] }];
  return { status, days };
}

function open(attraction_id, { date = '2027-04-10', item_id = null } = {}) {
  act(() => {
    bookingStore.setState({ attractionDetails: { open: true, attraction_id, item_id, date } });
  });
}

function setPackage(pkg) {
  act(() => {
    bookingStore.setState({ result: { response: { package: pkg } } });
  });
}

beforeEach(() => {
  mocks.getAttraction.mockImplementation(async (id) => DATA[id]);
  bookingStore.setState({
    attractionDetails: { open: false, attraction_id: null, item_id: null, date: null },
    attractionSelection: [],
    result: { response: null },
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('AttractionDetails', () => {
  it('shows the right attraction for each id it is opened with', async () => {
    render(<AttractionDetails />);
    open('ATT-KYO-001');
    expect(await screen.findByRole('heading', { name: 'Kiyomizu-dera' })).toBeTruthy();
    expect(screen.getByText('Kyoto · Japan')).toBeTruthy();
    expect(screen.getByText('Photo: Martin Falbisoner, CC BY-SA 4.0 (Wikimedia Commons)')).toBeTruthy();

    open('ATT-OSA-003');
    expect(await screen.findByRole('heading', { name: 'Osaka Castle' })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: 'Kiyomizu-dera' })).toBeNull();
    expect(screen.getByText('Closed')).toBeTruthy();
    expect(screen.getByText('Same as adult')).toBeTruthy();
    expect(screen.getByText('Free')).toBeTruthy();
    expect(mocks.getAttraction).toHaveBeenCalledWith('ATT-OSA-003', expect.anything());
  });

  it('shows a fallback block instead of a broken image', async () => {
    render(<AttractionDetails />);
    open('ATT-KYO-001');
    const photo = await screen.findByRole('img', { name: 'Kiyomizu-dera' });
    fireEvent.error(photo);
    expect(screen.queryByRole('img', { name: 'Kiyomizu-dera' })).toBeNull();
    const fallback = document.querySelector('.attraction-details__fallback');
    expect(fallback.textContent).toContain('Temple');
    expect(fallback.textContent).toContain('Kiyomizu-dera');
  });

  it('links to a Google Maps search with the query encoded and labelled as a map search', async () => {
    render(<AttractionDetails />);
    open('ATT-KYO-001');
    const link = await screen.findByRole('link', { name: 'View on Google Maps' });
    expect(link.getAttribute('href')).toBe(KYOTO.maps_url);
    expect(link.getAttribute('href')).toContain('query=Kiyomizu-dera%2C%20Kyoto%2C%20Japan');
    expect(link.getAttribute('target')).toBe('_blank');
    expect(link.getAttribute('rel')).toBe('noopener noreferrer');
  });

  it('closes on Escape', async () => {
    render(<AttractionDetails />);
    open('ATT-KYO-001');
    await screen.findByRole('dialog', { name: 'Kiyomizu-dera' });
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(mocks.closeAttractionDetails).toHaveBeenCalledTimes(1);
  });

  it('shows no change buttons for a booked holiday', async () => {
    setPackage(packageWith({ status: 'BOOKED', visit: { kind: 'ATTRACTION', catalog_id: 'ATT-KYO-001', item_id: 'visit:ATT-KYO-001' } }));
    render(<AttractionDetails />);
    open('ATT-KYO-001', { item_id: 'visit:ATT-KYO-001' });
    await screen.findByRole('heading', { name: 'Kiyomizu-dera' });
    expect(screen.getByText('This holiday is booked; details only.')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Remove from holiday|Add to selection|Selected/ })).toBeNull();
  });

  it('offers Add to selection for an unscheduled attraction in a planned holiday', async () => {
    setPackage(packageWith({ status: 'PLANNED' }));
    render(<AttractionDetails />);
    open('ATT-KYO-001');
    const add = await screen.findByRole('button', { name: 'Add to selection' });
    fireEvent.click(add);
    expect(mocks.toggleAttractionSelection).toHaveBeenCalledWith({
      attraction_id: 'ATT-KYO-001', name: 'Kiyomizu-dera', city: 'Kyoto', date: '2027-04-10',
    });
  });
});
