import { describe, expect, it } from 'vitest';
import {
  bestDateNote,
  comparePrices,
  describeTile,
  elevationFor,
  formatINR,
  isProven,
  nearestProvenDate,
  normalizedLevel,
  provenRange,
  tileState,
  viewState,
} from './landscapeModel.js';
import {
  ERROR,
  FOUND,
  INFEASIBLE,
  LOADING,
  NOT_ELIGIBLE,
  OUTSIDE_WINDOW,
  SEARCH_INCOMPLETE,
} from './types.js';

const proven = (date, min_total_inr) => ({
  date,
  status: FOUND,
  min_total_inr,
  proven_minimum: true,
});

describe('nearestProvenDate', () => {
  it('returns the proven date with the smallest day distance, on either side', () => {
    const cells = [proven('2027-04-05', 300000), proven('2027-04-09', 250000), proven('2027-04-20', 100000)];
    expect(nearestProvenDate(cells, '2027-04-12')).toBe(cells[1]);
    expect(nearestProvenDate(cells, '2027-04-18')).toBe(cells[2]);
  });

  it('breaks a tie in distance towards the earlier date', () => {
    const cells = [proven('2027-04-14', 200000), proven('2027-04-10', 260000)];
    // 12 April is two days from both 10 and 14 April
    expect(nearestProvenDate(cells, '2027-04-12').date).toBe('2027-04-10');
    expect(nearestProvenDate([...cells].reverse(), '2027-04-12').date).toBe('2027-04-10');
  });

  it('ignores cells that are not proven, including FOUND cells without proven_minimum', () => {
    const cells = [
      { date: '2027-04-13', status: INFEASIBLE, min_total_inr: null, proven_minimum: false },
      { date: '2027-04-11', status: SEARCH_INCOMPLETE, min_total_inr: null, proven_minimum: false },
      { date: '2027-04-12', status: FOUND, min_total_inr: 100000, proven_minimum: false },
      proven('2027-04-20', 240000),
    ];
    expect(nearestProvenDate(cells, '2027-04-13').date).toBe('2027-04-20');
  });

  it('returns null when no date is proven, or the input is empty or invalid', () => {
    expect(nearestProvenDate([{ date: '2027-04-13', status: INFEASIBLE, min_total_inr: null, proven_minimum: false }],
      '2027-04-13')).toBeNull();
    expect(nearestProvenDate([], '2027-04-13')).toBeNull();
    expect(nearestProvenDate(null, '2027-04-13')).toBeNull();
    expect(nearestProvenDate([proven('2027-04-20', 240000)], 'not-a-date')).toBeNull();
  });

  it('measures distance across month and year boundaries', () => {
    const cells = [proven('2028-01-02', 150000), proven('2027-12-20', 170000)];
    expect(nearestProvenDate(cells, '2027-12-31').date).toBe('2028-01-02');
  });
});
const unprovenFound = (date, min_total_inr = 200000) => ({
  date,
  status: FOUND,
  min_total_inr,
  proven_minimum: false,
});
const infeasible = (date) => ({ date, status: INFEASIBLE, min_total_inr: null, proven_minimum: false });
const incomplete = (date) => ({ date, status: SEARCH_INCOMPLETE, min_total_inr: null, proven_minimum: false });

const WINDOW = { first_night: '2027-04-01', last_departure: '2027-04-30' };

describe('isProven', () => {
  it('is true only for FOUND, proven_minimum, and an integer price', () => {
    expect(isProven(proven('2027-04-10', 218700))).toBe(true);
  });

  it('is false for unproven, non-integer, string, or non-FOUND cells', () => {
    expect(isProven(unprovenFound('2027-04-10'))).toBe(false);
    expect(isProven({ status: FOUND, proven_minimum: true, min_total_inr: 218700.5 })).toBe(false);
    expect(isProven({ status: FOUND, proven_minimum: true, min_total_inr: '218700' })).toBe(false);
    expect(isProven({ status: FOUND, proven_minimum: true, min_total_inr: null })).toBe(false);
    expect(isProven(incomplete('2027-04-10'))).toBe(false);
    expect(isProven(infeasible('2027-04-10'))).toBe(false);
    expect(isProven(null)).toBe(false);
  });
});

describe('tileState', () => {
  const cells = new Map([
    ['2027-04-10', proven('2027-04-10', 218700)],
    ['2027-04-11', unprovenFound('2027-04-11')],
    ['2027-04-12', infeasible('2027-04-12')],
    ['2027-04-13', incomplete('2027-04-13')],
  ]);

  it('returns OUTSIDE_WINDOW for a day outside the travel window', () => {
    expect(tileState('2027-05-01', cells, WINDOW)).toBe(OUTSIDE_WINDOW);
  });

  it('returns LOADING while the month has not loaded', () => {
    expect(tileState('2027-04-10', null, WINDOW)).toBe(LOADING);
    expect(tileState('2027-04-10', cells, WINDOW, { loading: true })).toBe(LOADING);
  });

  it('returns ERROR when the month failed to load', () => {
    expect(tileState('2027-04-10', null, WINDOW, { failed: true })).toBe(ERROR);
  });

  it('returns NOT_ELIGIBLE when the backend did not list the date', () => {
    expect(tileState('2027-04-20', cells, WINDOW)).toBe(NOT_ELIGIBLE);
  });

  it('returns FOUND for a proven minimum', () => {
    expect(tileState('2027-04-10', cells, WINDOW)).toBe(FOUND);
  });

  it('returns SEARCH_INCOMPLETE for a FOUND cell that is not proven', () => {
    expect(tileState('2027-04-11', cells, WINDOW)).toBe(SEARCH_INCOMPLETE);
  });

  it('returns INFEASIBLE for an infeasible date', () => {
    expect(tileState('2027-04-12', cells, WINDOW)).toBe(INFEASIBLE);
  });

  it('returns SEARCH_INCOMPLETE for an incomplete search', () => {
    expect(tileState('2027-04-13', cells, WINDOW)).toBe(SEARCH_INCOMPLETE);
  });
});

describe('provenRange', () => {
  it('uses only proven prices, ignoring unproven cells, incomplete and infeasible cells, and nulls', () => {
    const range = provenRange([
      proven('2027-04-10', 218700),
      proven('2027-04-20', 241500),
      unprovenFound('2027-04-05', 100000),
      incomplete('2027-04-06'),
      infeasible('2027-04-07'),
      null,
    ]);
    expect(range).toEqual({ min: 218700, max: 241500 });
  });

  it('returns null when no cell is proven', () => {
    expect(provenRange([unprovenFound('2027-04-05'), incomplete('2027-04-06')])).toBeNull();
    expect(provenRange(undefined)).toBeNull();
    expect(provenRange([])).toBeNull();
  });
});

describe('normalizedLevel', () => {
  const range = { min: 200000, max: 300000 };

  it('is 0 for the cheapest proven price and 1 for the dearest', () => {
    expect(normalizedLevel(proven('2027-04-10', 200000), range)).toBe(0);
    expect(normalizedLevel(proven('2027-04-20', 300000), range)).toBe(1);
  });

  it('is null for a cell without a proven price', () => {
    expect(normalizedLevel(unprovenFound('2027-04-05', 100000), range)).toBeNull();
    expect(normalizedLevel(incomplete('2027-04-06'), range)).toBeNull();
    expect(normalizedLevel(proven('2027-04-10', 200000), null)).toBeNull();
  });

  it('does not divide by zero when min equals max', () => {
    const flat = { min: 250000, max: 250000 };
    const level = normalizedLevel(proven('2027-04-10', 250000), flat);
    expect(level).toBe(0);
    expect(Number.isFinite(level)).toBe(true);
  });
});

describe('elevationFor', () => {
  it('is 0 for a null level', () => {
    expect(elevationFor(null)).toBe(0);
  });

  it('is monotonic: dearer levels stand higher', () => {
    expect(elevationFor(0)).toBeGreaterThan(0);
    expect(elevationFor(0.2)).toBeLessThan(elevationFor(0.8));
    expect(elevationFor(0.8)).toBeLessThan(elevationFor(1));
  });
});

describe('comparePrices', () => {
  const reference = proven('2027-04-12', 241500);

  it('reports SAVE with the proven difference when the selected date is cheaper', () => {
    expect(comparePrices(reference, proven('2027-04-20', 218700))).toEqual({ kind: 'SAVE', amount: 22800 });
  });

  it('reports MORE with the difference when the selected date is dearer', () => {
    expect(comparePrices(proven('2027-04-20', 218700), reference)).toEqual({ kind: 'MORE', amount: 22800 });
  });

  it('reports SAME with amount 0 for equal prices on different dates', () => {
    expect(comparePrices(reference, proven('2027-04-20', 241500))).toEqual({ kind: 'SAME', amount: 0 });
  });

  it('reports ORIGINAL for the same date', () => {
    expect(comparePrices(reference, proven('2027-04-12', 241500))).toEqual({ kind: 'ORIGINAL', amount: null });
  });

  it('reports UNAVAILABLE and no number when either side is not proven', () => {
    const cases = [
      [unprovenFound('2027-04-12'), proven('2027-04-20', 218700)],
      [reference, unprovenFound('2027-04-20')],
      [reference, infeasible('2027-04-20')],
      [reference, incomplete('2027-04-20')],
      [incomplete('2027-04-12'), proven('2027-04-20', 218700)],
      [reference, null],
      [null, proven('2027-04-20', 218700)],
    ];
    for (const [ref, sel] of cases) {
      const result = comparePrices(ref, sel);
      expect(result).toEqual({ kind: 'UNAVAILABLE', amount: null });
      expect(result.amount).toBeNull();
    }
  });
});

describe('bestDateNote', () => {
  const fully = (dates, extra = {}) => ({ dates, range_fully_evaluated: true, ...extra });

  it('uses the "Lowest proven price this month" title when the range was fully evaluated', () => {
    const note = bestDateNote(fully([proven('2027-04-10', 218700)]), null);
    expect(note.title).toBe('Lowest proven price this month');
    expect(note.date).toBe('2027-04-10');
    expect(note.total).toBe(218700);
  });

  it('uses the "Lowest verified price among evaluated dates" title when not fully evaluated', () => {
    const note = bestDateNote({ dates: [proven('2027-04-10', 218700)], range_fully_evaluated: false }, null);
    expect(note.title).toBe('Lowest verified price among evaluated dates');
    expect(note.fullyEvaluated).toBe(false);
  });

  it('picks the earliest date when prices tie, and says how many dates share the minimum', () => {
    const note = bestDateNote(
      fully([proven('2027-04-20', 218700), proven('2027-04-10', 218700), proven('2027-04-05', 250000)]),
      null,
    );
    expect(note.date).toBe('2027-04-10');
    expect(note.ties).toBe(2);
    expect(note.detail).toBe('2 dates share the same minimum price.');
  });

  it('gives a SAVE detail when the reference date is proven and the best date is cheaper', () => {
    const note = bestDateNote(fully([proven('2027-04-10', 218700)]), proven('2027-04-12', 241500));
    expect(note.detail).toBe('Start 10 April 2027 and save ₹22,800.');
  });

  it('gives no SAVE detail when the reference is not proven', () => {
    const note = bestDateNote(fully([proven('2027-04-10', 218700)]), unprovenFound('2027-04-12', 100000));
    expect(note.detail).toBeNull();
  });

  it('says the chosen date already has the lowest price when the reference is the best date', () => {
    const note = bestDateNote(fully([proven('2027-04-10', 218700)]), proven('2027-04-10', 218700));
    expect(note.detail).toBe('Your chosen date already has the lowest price.');
  });

  it('returns null when nothing is proven or there is no response', () => {
    expect(bestDateNote(null, null)).toBeNull();
    expect(bestDateNote(fully([unprovenFound('2027-04-10'), incomplete('2027-04-11')]), null)).toBeNull();
    expect(bestDateNote(fully([]), null)).toBeNull();
  });
});

describe('viewState', () => {
  it('maps the fetch status to the panel state', () => {
    expect(viewState({ status: 'idle', response: null })).toBe('IDLE');
    expect(viewState({ status: 'loading', response: null })).toBe('LOADING');
    expect(viewState({ status: 'error', response: null })).toBe('ERROR');
  });

  it('is EMPTY for a ready status with no dates', () => {
    expect(viewState({ status: 'ready', response: null })).toBe('EMPTY');
    expect(viewState({ status: 'ready', response: { dates: [] } })).toBe('EMPTY');
  });

  it('is PARTIALLY_EVALUATED when range_fully_evaluated is false', () => {
    const response = { dates: [proven('2027-04-10', 218700)], range_fully_evaluated: false };
    expect(viewState({ status: 'ready', response })).toBe('PARTIALLY_EVALUATED');
  });

  it('is READY when the range was fully evaluated', () => {
    const response = { dates: [proven('2027-04-10', 218700)], range_fully_evaluated: true };
    expect(viewState({ status: 'ready', response })).toBe('READY');
  });
});

describe('formatINR', () => {
  it('returns an em dash for non-numbers, never ₹0', () => {
    expect(formatINR(null)).toBe('—');
    expect(formatINR(undefined)).toBe('—');
    expect(formatINR(NaN)).toBe('—');
    expect(formatINR(null)).not.toBe('₹0');
  });

  it('uses Indian digit grouping', () => {
    expect(formatINR(218700)).toContain('2,18,700');
  });
});

describe('describeTile', () => {
  const cell = proven('2027-04-10', 218700);

  it('describes each state in words', () => {
    expect(describeTile('2027-04-10', FOUND, cell)).toBe('10 April 2027: minimum valid holiday ₹2,18,700');
    expect(describeTile('2027-04-10', INFEASIBLE, null)).toBe(
      '10 April 2027: no complete valid trip available for this date',
    );
    expect(describeTile('2027-04-10', SEARCH_INCOMPLETE, null)).toBe(
      '10 April 2027: minimum price not verified',
    );
    expect(describeTile('2027-04-10', LOADING, null)).toBe('10 April 2027: loading price');
    expect(describeTile('2027-04-10', ERROR, null)).toBe('10 April 2027: price could not be loaded');
    expect(describeTile('2027-04-10', NOT_ELIGIBLE, null)).toBe(
      '10 April 2027: the trip would not fit in the travel window from this date',
    );
    expect(describeTile('2027-05-10', OUTSIDE_WINDOW, null)).toBe(
      '10 May 2027: outside the travel window',
    );
  });
});
