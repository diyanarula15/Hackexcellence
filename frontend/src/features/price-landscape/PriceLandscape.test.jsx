/**
 * PriceLandscape.jsx — component tests with an injected fake fetcher. Nothing here touches the
 * network: every response is built in this file in the shape of the POST /api/date-prices contract.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, within, waitFor, act, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PriceLandscape from './PriceLandscape.jsx';

const TRIP = {
  departure: 'BLR', country: 'Japan', start_date: '2027-04-10', nights: 6, adults: 2, child_ages: [6],
  budget: 350000,
};
const WINDOW = { first_night: '2027-04-01', last_departure: '2027-04-20' };
const WIDE_WINDOW = { first_night: '2027-04-01', last_departure: '2027-05-31' };
const WINTER_WINDOW = { first_night: '2027-12-01', last_departure: '2028-03-10' };

/** One start date as the backend reports it. */
const cell = (date, status, min_total_inr = null, proven_minimum = false) => ({
  date, status, min_total_inr, proven_minimum, within_budget: status === 'FOUND' ? true : null,
  difference_vs_reference_inr: null, proven_savings_inr: null,
});
const found = (date, min) => cell(date, 'FOUND', min, true);

/** Dates of April 2027 the fake backend knows about. Dates not listed are NOT_ELIGIBLE. */
const APRIL = [
  found('2027-04-10', 241500),                       // original date in most tests
  found('2027-04-11', 230000),
  found('2027-04-12', 218700),                       // cheaper: 22,800 saved
  cell('2027-04-13', 'INFEASIBLE'),
  cell('2027-04-14', 'SEARCH_INCOMPLETE'),
  found('2027-04-15', 260000),                       // dearer: 18,500 more
  cell('2027-04-16', 'FOUND', 200000, false),        // FOUND but not proven -> unverified
  found('2027-04-17', 241500),                       // same price as the original
];

/** A backend response for a range, with the given cells inside that range. */
function response({ rangeStart, rangeEnd, dates, fully = true, window: travelWindow = WINDOW }) {
  return {
    dates,
    range_start: rangeStart,
    range_end: rangeEnd,
    data_window: travelWindow,
    range_fully_evaluated: fully,
    lowest_proven_date: null,
    lowest_proven_total_inr: null,
    highest_proven_total_inr: null,
    cheapest_date: null,
    cheapest_total_inr: null,
    comparison: {
      reference_date: null, reference_status: null, reference_min_total_inr: null,
      max_proven_savings_inr: null, best_saving_date: null,
    },
  };
}

/** A fetcher that answers from a fixed list of cells, filtered to the requested range. */
const answer = (cells, options = {}) => (trip, { rangeStart, rangeEnd }) => Promise.resolve(response({
  rangeStart, rangeEnd, dates: cells.filter((c) => c.date >= rangeStart && c.date <= rangeEnd), ...options,
}));

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function stubMatchMedia(reduced = false) {
  window.matchMedia = (query) => ({
    matches: reduced && query === '(prefers-reduced-motion: reduce)',
    media: query,
    onchange: null,
    addListener() {},
    removeListener() {},
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent() { return false; },
  });
}

function renderDialog({ trip = TRIP, window: travelWindow = WINDOW, fetcher = vi.fn(answer(APRIL)),
  onGenerate = vi.fn(() => Promise.resolve()) } = {}) {
  const onClose = vi.fn();
  const onSelectDate = vi.fn();
  const user = userEvent.setup();
  const utils = render(
    <PriceLandscape trip={trip} window={travelWindow} countryName="Japan" onClose={onClose}
      onSelectDate={onSelectDate} onGenerate={onGenerate} fetcher={fetcher} />,
  );
  return { user, fetcher, onClose, onSelectDate, onGenerate, ...utils };
}

const tile = (iso) => document.querySelector(`[data-date="${iso}"]`);

/** Waits until a tile reports the given state, then returns it. */
async function waitForState(iso, state) {
  await waitFor(() => expect(tile(iso)?.getAttribute('data-state')).toBe(state));
  return tile(iso);
}

const monthCalls = (fetcher, rangeStart) => fetcher.mock.calls.filter(([, range]) => range.rangeStart === rangeStart);

beforeEach(() => {
  stubMatchMedia(false);
});

afterEach(() => {
  cleanup();
});

describe('month navigation and loading', () => {
  it('renders the month of the start date and fetches that month', async () => {
    const { fetcher } = renderDialog();

    expect(await screen.findByRole('heading', { level: 3, name: 'April 2027' })).toBeTruthy();
    await waitFor(() => expect(fetcher).toHaveBeenCalledWith(
      TRIP, { rangeStart: '2027-04-01', rangeEnd: '2027-04-30' }, expect.objectContaining({ signal: expect.anything() }),
    ));
  });

  it('steps across a year boundary and disables Previous at the first month of the window', async () => {
    const { user } = renderDialog({
      trip: { ...TRIP, start_date: '2027-12-15' }, window: WINTER_WINDOW, fetcher: vi.fn(answer([])),
    });

    expect(await screen.findByRole('heading', { level: 3, name: 'December 2027' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Previous month' }).disabled).toBe(true);

    await user.click(screen.getByRole('button', { name: 'Next month' }));
    expect(await screen.findByRole('heading', { level: 3, name: 'January 2028' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Previous month' }).disabled).toBe(false);
  });

  it('shows 29 February in a leap year', async () => {
    renderDialog({
      trip: { ...TRIP, start_date: '2028-02-10' }, window: WINTER_WINDOW, fetcher: vi.fn(answer([])),
    });

    expect(await screen.findByRole('heading', { level: 3, name: 'February 2028' })).toBeTruthy();
    const leapDay = tile('2028-02-29');
    expect(leapDay).not.toBeNull();
    expect(leapDay.getAttribute('data-state')).not.toBe('OUTSIDE_WINDOW');
    expect(tile('2028-02-30')).toBeNull();
  });

  it('original date comparison is fetched separately when the original date is in another month', async () => {
    const { user, fetcher } = renderDialog({ window: WIDE_WINDOW });

    await user.click(await screen.findByRole('button', { name: 'Next month' }));
    expect(await screen.findByRole('heading', { level: 3, name: 'May 2027' })).toBeTruthy();

    await waitFor(() => expect(monthCalls(fetcher, '2027-04-10')).toHaveLength(1));
    expect(monthCalls(fetcher, '2027-04-10')[0][1]).toEqual({ rangeStart: '2027-04-10', rangeEnd: '2027-04-10' });
    // the proven April value, never a guess
    await waitFor(() => expect(screen.getByTestId('original-start-price').textContent).toBe('₹2,41,500'));
  });

  it('does not make an extra request for the original date when it is in the visible month', async () => {
    const { fetcher } = renderDialog();
    await waitFor(() => expect(screen.getByTestId('original-start-price').textContent).toBe('₹2,41,500'));
    expect(monthCalls(fetcher, '2027-04-10')).toHaveLength(0);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});

describe('tile states and prices', () => {
  it('shows the proven minimum as text on FOUND tiles', async () => {
    renderDialog();

    const found12 = await waitForState('2027-04-12', 'FOUND');
    expect(within(found12).getAllByText('₹2,18,700').length).toBeGreaterThan(0);
  });

  it('shows "No trip" on INFEASIBLE tiles, which are disabled and cannot be selected', async () => {
    const { user, onSelectDate } = renderDialog();

    const infeasible = await waitForState('2027-04-13', 'INFEASIBLE');
    expect(within(infeasible).getByText('No trip')).toBeTruthy();
    expect(infeasible.getAttribute('aria-disabled')).toBe('true');

    await user.click(infeasible);
    expect(onSelectDate).not.toHaveBeenCalled();
    expect(infeasible.getAttribute('aria-pressed')).toBeNull();
  });

  it('shows a dash and "Not verified" without a rupee amount for SEARCH_INCOMPLETE tiles', async () => {
    renderDialog();

    const incomplete = await waitForState('2027-04-14', 'SEARCH_INCOMPLETE');
    expect(within(incomplete).getByText('—')).toBeTruthy();
    expect(within(incomplete).getByText('Not verified')).toBeTruthy();
    expect(incomplete.textContent).not.toContain('₹');
  });

  it('treats a FOUND cell with proven_minimum false the same as SEARCH_INCOMPLETE', async () => {
    renderDialog();

    const unproven = await waitForState('2027-04-16', 'SEARCH_INCOMPLETE');
    expect(within(unproven).getByText('—')).toBeTruthy();
    expect(within(unproven).getByText('Not verified')).toBeTruthy();
    expect(unproven.textContent).not.toContain('₹');
  });

  it('marks dates outside the window OUTSIDE_WINDOW and window dates the backend did not list NOT_ELIGIBLE', async () => {
    renderDialog();

    const outside = await waitForState('2027-04-25', 'OUTSIDE_WINDOW');
    expect(outside.getAttribute('aria-disabled')).toBe('true');

    const notEligible = await waitForState('2027-04-19', 'NOT_ELIGIBLE');
    expect(notEligible.getAttribute('aria-disabled')).toBe('true');
  });
});

describe('comparison with the original date', () => {
  it('reports the saving when a cheaper date is selected', async () => {
    const { user, onSelectDate } = renderDialog();

    await user.click(await waitForState('2027-04-12', 'FOUND'));
    expect(onSelectDate).toHaveBeenCalledWith('2027-04-12');
    expect(await screen.findByText('Save ₹22,800 by starting on 12 April 2027.')).toBeTruthy();
  });

  it('reports "Price comparison unavailable." and no saving when the original date is not proven', async () => {
    const { user } = renderDialog({ trip: { ...TRIP, start_date: '2027-04-14' } });

    await waitFor(() => expect(screen.getByTestId('original-start-price').textContent).toBe('Not verified'));
    await user.click(await waitForState('2027-04-12', 'FOUND'));

    expect(await screen.findByText('Price comparison unavailable.')).toBeTruthy();
    expect(screen.queryByText(/\bsave\b/i)).toBeNull();
  });

  it('reports how much more a dearer date costs, and never claims a saving', async () => {
    const { user } = renderDialog();

    await user.click(await waitForState('2027-04-15', 'FOUND'));
    expect(await screen.findByText('₹18,500 more than your original date.')).toBeTruthy();
    // scoped to the verdict: the month's best-date note may legitimately mention a saving elsewhere
    expect(screen.getByRole('status').textContent).not.toMatch(/\bsave\b/i);
  });

  it('reports an equal price as the same minimum price', async () => {
    const { user } = renderDialog();

    await user.click(await waitForState('2027-04-17', 'FOUND'));
    expect(await screen.findByText('Same minimum price as your original date.')).toBeTruthy();
  });

  it('labels the best date as verified among evaluated dates when the range is not fully evaluated', async () => {
    renderDialog({ fetcher: vi.fn(answer(APRIL, { fully: false })) });

    expect(await screen.findByText('Lowest verified price among evaluated dates')).toBeTruthy();
    expect(screen.queryByText('Lowest proven price this month')).toBeNull();
  });
});

describe('rapid navigation', () => {
  it('ignores a month response that arrives after the user has moved on', async () => {
    const aprilReply = deferred();
    const mayReply = deferred();
    const fetcher = vi.fn((trip, range) => {
      if (range.rangeStart === '2027-04-01') return aprilReply.promise;
      if (range.rangeStart === '2027-05-01') return mayReply.promise;
      return answer(APRIL)(trip, range);
    });
    const { user } = renderDialog({ window: WIDE_WINDOW, fetcher });

    await waitFor(() => expect(monthCalls(fetcher, '2027-04-01')).toHaveLength(1));
    await user.click(screen.getByRole('button', { name: 'Next month' }));
    await waitFor(() => expect(monthCalls(fetcher, '2027-05-01')).toHaveLength(1));

    mayReply.resolve(response({
      rangeStart: '2027-05-01', rangeEnd: '2027-05-31', window: WIDE_WINDOW,
      dates: [found('2027-05-05', 333333)],
    }));
    const may5 = await waitForState('2027-05-05', 'FOUND');
    expect(within(may5).getAllByText('₹3,33,333').length).toBeGreaterThan(0);

    // April arrives late, after May is on screen
    await act(async () => {
      aprilReply.resolve(response({
        rangeStart: '2027-04-01', rangeEnd: '2027-04-30', window: WIDE_WINDOW,
        dates: [found('2027-04-12', 111111)],
      }));
      await new Promise((r) => setTimeout(r, 0));
    });

    expect(screen.getByRole('heading', { level: 3, name: 'May 2027' })).toBeTruthy();
    expect(tile('2027-05-05').getAttribute('data-state')).toBe('FOUND');
    expect(tile('2027-04-12')).toBeNull();
    expect(document.body.textContent).not.toContain('₹1,11,111');
  });
});

describe('generating a holiday', () => {
  it('passes the selected date to onGenerate once, and disables the button while pending', async () => {
    const pending = deferred();
    const onGenerate = vi.fn(() => pending.promise);
    const { user } = renderDialog({ onGenerate });

    await user.click(await waitForState('2027-04-12', 'FOUND'));
    const button = screen.getByRole('button', { name: 'Generate holiday' });
    await user.dblClick(button);

    expect(onGenerate).toHaveBeenCalledTimes(1);
    expect(onGenerate).toHaveBeenCalledWith('2027-04-12');
    const busy = screen.getByRole('button', { name: 'Generating…' });
    expect(busy.disabled).toBe(true);

    await act(async () => {
      pending.resolve();
      await pending.promise;
    });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Generate holiday' }).disabled).toBe(false));
  });
});

describe('traveler details and failures', () => {
  it('sends the same traveler details with every fetch', async () => {
    const { user, fetcher } = renderDialog({ window: WIDE_WINDOW });

    await waitFor(() => expect(monthCalls(fetcher, '2027-04-01')).toHaveLength(1));
    await user.click(screen.getByRole('button', { name: 'Next month' }));
    await waitFor(() => expect(monthCalls(fetcher, '2027-05-01')).toHaveLength(1));

    expect(fetcher.mock.calls.length).toBeGreaterThanOrEqual(2);
    for (const [sentTrip] of fetcher.mock.calls) {
      expect(sentTrip).toEqual(TRIP);
      expect(sentTrip.departure).toBe('BLR');
      expect(sentTrip.country).toBe('Japan');
      expect(sentTrip.nights).toBe(6);
      expect(sentTrip.adults).toBe(2);
      expect(sentTrip.child_ages).toEqual([6]);
      expect(sentTrip.budget).toBe(350000);
    }
  });

  it('shows the error and Retry, with no rupee amounts, when the API cannot be reached', async () => {
    const error = Object.assign(new Error('Cannot reach the planner. Check your connection.'), { name: 'ApiError' });
    const fetcher = vi.fn(() => Promise.reject(error));
    const { user } = renderDialog({ fetcher });

    expect(await screen.findByText('Cannot reach the planner. Check your connection.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeTruthy();
    expect(document.body.textContent).not.toContain('₹');

    await user.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(monthCalls(fetcher, '2027-04-01')).toHaveLength(2));
  });
});

describe('motion and keyboard', () => {
  it('shows the final price immediately with reduced motion', async () => {
    stubMatchMedia(true);
    const { user } = renderDialog();

    await user.click(await waitForState('2027-04-12', 'FOUND'));
    expect(screen.getByTestId('selected-start-price').textContent).toBe('₹2,18,700');
  });

  it('moves focus with ArrowRight, selects with Enter and closes with Escape', async () => {
    const { user, onClose } = renderDialog();

    const original = await waitForState('2027-04-10', 'FOUND');
    act(() => original.focus());

    await user.keyboard('{ArrowRight}');
    await waitFor(() => expect(document.activeElement).toBe(tile('2027-04-11')));

    await user.keyboard('{Enter}');
    await waitFor(() => expect(tile('2027-04-11').getAttribute('aria-pressed')).toBe('true'));

    await user.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalled();
  });

  it('exposes each tile as a button named by its date and price', async () => {
    renderDialog();

    await waitForState('2027-04-12', 'FOUND');
    const buttons = screen.getAllByRole('button', { name: /12 April 2027/ });
    const dayTile = buttons.find((b) => b.getAttribute('data-date') === '2027-04-12');
    expect(dayTile).toBeTruthy();
    expect(dayTile.tagName).toBe('BUTTON');
    expect(dayTile.getAttribute('aria-label')).toContain('₹2,18,700');
  });
});
