/**
 * Pick-your-trip step: cards, skeletons, the preview drawer, choosing, errors and reduced motion.
 * The store is real; only the package-options API is mocked.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';

const { mocks } = vi.hoisted(() => ({
  mocks: { searchPackageOptions: vi.fn(), selectPackageOption: vi.fn() },
}));

vi.mock('../../services/packageOptionsApi.js', () => ({
  searchPackageOptions: mocks.searchPackageOptions,
  selectPackageOption: mocks.selectPackageOption,
}));

import { bookingStore } from '../../state/bookingStore.js';
import { formatDate, formatINR } from '../format.js';
import PackageOptions from './PackageOptions.jsx';

const FLIGHT_OUT = {
  flight_number: 'SL 101',
  airline: 'Sky Lanka',
  from: 'BLR',
  to: 'NRT',
  depart: '2027-04-10T01:00:00',
  arrive: '2027-04-10T09:30:00',
};
const FLIGHT_HOME = {
  flight_number: 'SL 102',
  airline: 'Sky Lanka',
  from: 'KIX',
  to: 'BLR',
  depart: '2027-04-16T11:00:00',
  arrive: '2027-04-16T16:20:00',
};

/** A day in the shape services/itinerary.build_day_timeline returns. */
function arrivalDay() {
  return {
    date: '2027-04-10',
    day_number: 1,
    day_type: 'ARRIVAL',
    city: 'Tokyo',
    from_city: null,
    overnight: { item_id: 'stay:tokyo', name: 'Ginza Pearl Hotel' },
    events: [
      {
        kind: 'FLIGHT',
        item_id: 'flight:arrival',
        catalog_id: null,
        name: 'Bengaluru to Tokyo',
        start: '2027-04-10T01:00:00',
        end: '2027-04-10T09:30:00',
        quantity: 2,
        price_inr: 30000,
        display_details: {
          flight_number: 'SL 101',
          airline: 'Sky Lanka',
          from: { code: 'BLR', city: 'Bengaluru' },
          to: { code: 'NRT', city: 'Tokyo' },
          duration_minutes: 540,
        },
      },
      {
        kind: 'CHECK_IN',
        item_id: 'stay:tokyo',
        catalog_id: null,
        name: 'Ginza Pearl Hotel',
        start: '2027-04-10',
        end: '2027-04-13',
        quantity: 1,
        price_inr: 60000,
        display_details: {
          check_in_from: '14:00',
          stars: 4,
          area: 'Ginza',
          room: { name: 'Family Room' },
          rooms: 1,
          nights: 3,
        },
      },
    ],
  };
}

function preview(total, pricing, remaining) {
  return {
    days: [arrivalDay()],
    pricing: { ...pricing, total_inr: total },
    budget: {
      budget_inr: 350000,
      total_inr: total,
      remaining_inr: remaining,
      over_budget_inr: 0,
      within_budget: true,
    },
  };
}

const OPTIONS = [
  {
    option_id: 'opt-1',
    rank: 1,
    recommended: true,
    proven_minimum: false,
    total_inr: 233632,
    budget_inr: 350000,
    budget_remaining_inr: 116368,
    country: 'Japan',
    start_date: '2027-04-10',
    end_date: '2027-04-16',
    nights: 6,
    travelers: { adults: 2, child_ages: [6] },
    cities: ['Tokyo', 'Osaka'],
    city_nights: [
      { city: 'Tokyo', nights: 3 },
      { city: 'Osaka', nights: 3 },
    ],
    flights: { summary: 'BLR → NRT · return KIX → BLR', arrival: FLIGHT_OUT, return: FLIGHT_HOME },
    hotels: [{ city: 'Tokyo', name: 'Ginza Pearl Hotel', stars: 4, nights: 3, room: 'Family Room', rooms: 1 }],
    hotel_summary: '4★ Ginza Pearl Hotel (Tokyo) · 3★ Namba Lodge (Osaka)',
    attractions: ['Senso-ji', 'Ueno Park'],
    experience_summary: '8 visits incl. Senso-ji, Ueno Park, Osaka Castle',
    stats: { cities: 2, city_changes: 1, transfers: 3, attractions: 8, avg_stars: 3.5, travel_minutes: 1150 },
    labels: ['Cheapest'],
    badges: ['Cheapest'],
    why: [{ label: 'Cheapest', text: 'Lowest verified total price of any complete valid holiday for your request.' }],
    differences: [],
    preview: preview(
      233632,
      { flights: 60000, hotels: 120000, airport_transfers: 6000, intercity_transfers: 9000, attractions: 38632 },
      116368,
    ),
  },
  {
    option_id: 'opt-2',
    rank: 2,
    recommended: false,
    proven_minimum: false,
    total_inr: 247900,
    budget_inr: 350000,
    budget_remaining_inr: 102100,
    country: 'Japan',
    start_date: '2027-04-10',
    end_date: '2027-04-16',
    nights: 6,
    travelers: { adults: 2, child_ages: [6] },
    cities: ['Tokyo', 'Kyoto'],
    city_nights: [
      { city: 'Tokyo', nights: 3 },
      { city: 'Kyoto', nights: 3 },
    ],
    flights: { summary: 'BLR → NRT · return KIX → BLR', arrival: FLIGHT_OUT, return: FLIGHT_HOME },
    hotels: [{ city: 'Tokyo', name: 'Shinjuku Garden Inn', stars: 4, nights: 3, room: 'Family Room', rooms: 1 }],
    hotel_summary: '4★ Shinjuku Garden Inn (Tokyo) · 4★ Kyoto Riverside (Kyoto)',
    attractions: ['Fushimi Inari'],
    experience_summary: '6 visits incl. Fushimi Inari, Kiyomizu-dera',
    stats: { cities: 2, city_changes: 1, transfers: 3, attractions: 6, avg_stars: 4, travel_minutes: 1030 },
    labels: ['Fastest'],
    badges: ['Fastest'],
    differences: ['Different city mix', 'Higher-rated stays'],
    preview: preview(
      247900,
      { flights: 60000, hotels: 130000, airport_transfers: 6000, intercity_transfers: 9000, attractions: 42900 },
      102100,
    ),
  },
  {
    option_id: 'opt-3',
    rank: 3,
    recommended: false,
    proven_minimum: false,
    total_inr: 259450,
    budget_inr: 350000,
    budget_remaining_inr: 90550,
    country: 'Japan',
    start_date: '2027-04-10',
    end_date: '2027-04-16',
    nights: 6,
    travelers: { adults: 2, child_ages: [6] },
    cities: ['Tokyo'],
    city_nights: [{ city: 'Tokyo', nights: 6 }],
    flights: { summary: 'BLR → NRT · return NRT → BLR', arrival: FLIGHT_OUT, return: FLIGHT_HOME },
    hotels: [{ city: 'Tokyo', name: 'Ueno Park Suites', stars: 3, nights: 6, room: 'Twin Room', rooms: 2 }],
    hotel_summary: '3★ Ueno Park Suites (Tokyo)',
    attractions: ['Senso-ji'],
    experience_summary: '5 visits incl. Senso-ji',
    stats: { cities: 1, city_changes: 0, transfers: 2, attractions: 5, avg_stars: 3, travel_minutes: 1290 },
    labels: ['Best rated'],
    badges: ['Best rated'],
    differences: ['Different city mix', 'Fewer city changes'],
    preview: preview(
      259450,
      { flights: 64000, hotels: 140000, airport_transfers: 6000, intercity_transfers: 12000, attractions: 37450 },
      90550,
    ),
  },
];

const OPTIONS_RESULT = {
  status: 'OPTIONS',
  packageId: null,
  error: null,
  focus: 0,
  request: null,
  response: {
    status: 'OPTIONS',
    search_id: 'search-abc',
    objective: 'WITHIN_BUDGET',
    count: 3,
    headline: 'We found 3 holiday options for your trip',
    subline: 'Choose the one you like best',
    note: null,
    options: OPTIONS,
  },
};

const IDLE_PICK = { previewId: null, selectingId: null, error: null };

function setStore(patch) {
  act(() => {
    bookingStore.setState(patch);
  });
}

function showOptions(options = OPTIONS, extra = {}) {
  const count = options.length;
  setStore({
    result: {
      ...OPTIONS_RESULT,
      response: {
        ...OPTIONS_RESULT.response,
        count,
        headline: count === 1 ? 'We found 1 complete holiday option for your search.' : OPTIONS_RESULT.response.headline,
        note: count === 1 ? 'No additional distinct package options were verified.' : null,
        options,
      },
    },
    optionPick: IDLE_PICK,
    ...extra,
  });
}

beforeEach(() => {
  mocks.searchPackageOptions.mockReset();
  mocks.selectPackageOption.mockReset();
  showOptions();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('PackageOptions: cards', () => {
  it('renders one card per option with formatted prices and summaries', () => {
    const { container } = render(<PackageOptions />);
    const cards = screen.getAllByRole('article');
    expect(cards.length).toBe(3);

    expect(screen.getByRole('heading', { name: 'We found 3 holiday options for your trip' })).toBeTruthy();
    expect(screen.getByText('Choose the one you like best')).toBeTruthy();

    expect(screen.getByText(formatINR(233632))).toBeTruthy();
    expect(screen.getByText(formatINR(247900))).toBeTruthy();
    expect(screen.getByText(formatINR(259450))).toBeTruthy();
    expect(screen.getByText(`${formatINR(116368)} left of ${formatINR(350000)}`)).toBeTruthy();

    expect(screen.getByRole('heading', { name: 'Tokyo → Osaka' })).toBeTruthy();
    expect(screen.getAllByText('Tokyo · 3 nights').length).toBe(2);
    expect(screen.getByText('Osaka · 3 nights')).toBeTruthy();
    expect(screen.getAllByText(`Japan · ${formatDate('2027-04-10')} – ${formatDate('2027-04-16')} · 6 nights`).length).toBe(3);
    expect(screen.getAllByText('2 adults · 1 child (6)').length).toBe(3);

    expect(screen.getAllByText('BLR → NRT · return KIX → BLR').length).toBe(2);
    expect(screen.getByText('8 visits incl. Senso-ji, Ueno Park, Osaka Castle')).toBeTruthy();
    expect(screen.getByText('4★ Ginza Pearl Hotel (Tokyo) · 3★ Namba Lodge (Osaka)')).toBeTruthy();

    const stats = [...cards[0].querySelectorAll('.option-card__stat')].map((li) => li.textContent);
    expect(stats).toEqual(['2 cities', '1 city change', '3 transfers', '8 attractions', '19h 10m travel', '3.5★ avg per night']);
    expect(container.querySelectorAll('.option-card--skeleton').length).toBe(0);
  });

  it('shows the Cheapest / Fastest / Best rated labels and differences that are in the response, and no differences for option 1', () => {
    render(<PackageOptions />);
    expect(screen.getByText('Cheapest')).toBeTruthy();
    expect(screen.getByText('Fastest')).toBeTruthy();
    expect(screen.getByText('Best rated')).toBeTruthy();
    // why each label was won, from the response
    const why = screen.getAllByRole('list', { name: 'Why it won' });
    expect(why.length).toBe(1);
    expect(within(why[0]).getByText(/Lowest verified total price/)).toBeTruthy();
    expect(screen.getAllByText('Different city mix').length).toBe(2);
    expect(screen.getByText('Higher-rated stays')).toBeTruthy();
    expect(screen.getByText('Fewer city changes')).toBeTruthy();
    // option 1 (the reference) lists no differences; options 2 and 3 do
    const cards = screen.getAllByRole('article');
    expect(cards[0].querySelector('.option-card__diffs')).toBeNull();
    expect(screen.getAllByRole('list', { name: 'How it differs from option 1' }).length).toBe(2);
  });

  it('shows the single-option note', () => {
    showOptions([OPTIONS[0]]);
    render(<PackageOptions />);
    expect(screen.getByRole('heading', { name: 'We found 1 complete holiday option for your search.' })).toBeTruthy();
    expect(screen.getByText('No additional distinct package options were verified.')).toBeTruthy();
    expect(screen.getAllByRole('article').length).toBe(1);
  });
});

describe('PackageOptions: searching', () => {
  it('shows skeleton cards with no prices while the search runs', () => {
    setStore({
      result: { status: 'SEARCHING', request: {}, packageId: null, response: null, error: null, focus: 1 },
    });
    const { container } = render(<PackageOptions />);
    expect(screen.getByRole('heading', { name: 'Finding holiday options…' })).toBeTruthy();
    expect(container.querySelector('[aria-busy="true"]')).toBeTruthy();
    expect(container.querySelectorAll('.option-card--skeleton').length).toBe(3);
    expect(container.textContent.includes('₹')).toBe(false);
    expect(screen.queryAllByRole('article').length).toBe(0);
  });
});

describe('PackageOptions: details preview', () => {
  it('opens a dialog with the price, flights, stays and day timeline, then closes on Escape', () => {
    render(<PackageOptions />);
    fireEvent.click(screen.getAllByRole('button', { name: 'View details' })[1]);
    expect(bookingStore.getState().optionPick.previewId).toBe('opt-2');

    const dialog = screen.getByRole('dialog', { name: 'Option 2: Tokyo → Kyoto' });
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    expect(document.activeElement).toBe(dialog);
    expect(within(dialog).getByText('Preview · Not saved yet')).toBeTruthy();
    expect(within(dialog).getByText(formatINR(247900))).toBeTruthy();
    expect(within(dialog).getByText(formatINR(130000))).toBeTruthy();
    expect(within(dialog).getByText('Shinjuku Garden Inn')).toBeTruthy();
    expect(within(dialog).getByText(/Sky Lanka · SL 101/)).toBeTruthy();

    // the day-by-day timeline is the shared DayTimeline (read-only)
    expect(dialog.querySelector('ol.days')).toBeTruthy();
    expect(within(dialog).getByText(/Arrive in Tokyo/)).toBeTruthy();
    expect(within(dialog).getByText(`Day 1`)).toBeTruthy();
    expect(within(dialog).queryByRole('button', { name: /Change flight/ })).toBeNull();

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(bookingStore.getState().optionPick.previewId).toBeNull();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('closes with the Close button', () => {
    render(<PackageOptions />);
    fireEvent.click(screen.getAllByRole('button', { name: 'View details' })[0]);
    const dialog = screen.getByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Close' }));
    expect(bookingStore.getState().optionPick.previewId).toBeNull();
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});

describe('PackageOptions: choosing', () => {
  it('calls the store action with the search and option ids, and disables every choose button while saving', () => {
    mocks.selectPackageOption.mockReturnValue(new Promise(() => {}));
    const { container } = render(<PackageOptions />);

    fireEvent.click(screen.getAllByRole('button', { name: 'Explore trip' })[1]);

    expect(mocks.selectPackageOption).toHaveBeenCalledTimes(1);
    expect(mocks.selectPackageOption).toHaveBeenCalledWith('search-abc', 'opt-2', { acceptOverBudget: false });
    expect(bookingStore.getState().optionPick.selectingId).toBe('opt-2');

    const chooseButtons = screen.getAllByRole('button', { name: 'Explore trip' });
    expect(chooseButtons.length).toBe(3);
    expect(chooseButtons.every((b) => b.disabled)).toBe(true);
    expect(screen.getByText('Opening your trip…')).toBeTruthy();
    expect(container.querySelectorAll('.option-card--selecting').length).toBe(1);
    expect(container.querySelector('.option-card__plane')).toBeTruthy();
  });

  it('an option above the budget is chosen only after its price is accepted', () => {
    mocks.selectPackageOption.mockReturnValue(new Promise(() => {}));
    const over = {
      ...OPTIONS[1],
      option_id: 'opt-2',
      labels: ['Fastest'],
      badges: ['Fastest'],
      over_budget: true,
      total_inr: 360000,
      budget_remaining_inr: -10000,
    };
    showOptions([OPTIONS[0], over]);
    render(<PackageOptions />);
    const card = screen.getAllByRole('article')[1];
    const choose = within(card).getByRole('button', { name: 'Explore trip' });
    expect(choose.disabled).toBe(true);
    expect(within(card).getByText(`Over budget by ${formatINR(10000)}`)).toBeTruthy();

    fireEvent.click(within(card).getByRole('checkbox', { name: /I accept the price/ }));
    expect(choose.disabled).toBe(false);
    fireEvent.click(choose);
    expect(mocks.selectPackageOption).toHaveBeenCalledWith('search-abc', 'opt-2', { acceptOverBudget: true });
  });

  it('shows the error in an alert, and "Search again" starts a new search', async () => {
    mocks.selectPackageOption.mockRejectedValue(new Error('Could not save that trip.'));
    render(<PackageOptions />);

    fireEvent.click(screen.getAllByRole('button', { name: 'Explore trip' })[0]);

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('Could not save that trip.');
    expect(screen.getAllByRole('button', { name: 'Explore trip' }).every((b) => !b.disabled)).toBe(true);

    fireEvent.click(within(alert).getByRole('button', { name: 'Search again' }));
    expect(bookingStore.getState().result.status).toBe('EMPTY');
    expect(bookingStore.getState().optionPick.error).toBeNull();
  });
});

describe('PackageOptions: reduced motion', () => {
  it('disables the tilt, lift, plane flight and shimmer under prefers-reduced-motion', () => {
    // vitest runs from the frontend folder, so the path is relative to it
    const css = readFileSync(resolve(process.cwd(), 'src/features/package-options/PackageOptions.css'), 'utf8');
    const start = css.indexOf('@media (prefers-reduced-motion: reduce)');
    expect(start).toBeGreaterThan(-1);
    const block = css.slice(start);
    expect(block).toMatch(/\.option-card:hover[\s\S]*transform:\s*none/);
    expect(block).toMatch(/animation:\s*none/);
    expect(block).toMatch(/transition:\s*none/);
    expect(block).toMatch(/\.option-card__flight\s*\{\s*display:\s*none/);
  });
});
