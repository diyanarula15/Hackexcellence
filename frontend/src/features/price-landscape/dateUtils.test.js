import { describe, expect, it } from 'vitest';
import {
  addDays,
  addMonths,
  daysInMonth,
  formatLongDate,
  monthGrid,
  monthsBetween,
  parseIso,
  weekdayIndex,
} from './dateUtils.js';

describe('parseIso', () => {
  it('rejects a day that does not exist in a non-leap February', () => {
    expect(parseIso('2027-02-29')).toBeNull();
  });

  it('accepts 29 February in a leap year', () => {
    expect(parseIso('2028-02-29')).toEqual({ year: 2028, month: 2, day: 29 });
  });

  it('rejects malformed input', () => {
    expect(parseIso('2027-13-01')).toBeNull();
    expect(parseIso('2027-04-31')).toBeNull();
    expect(parseIso('12/04/2027')).toBeNull();
    expect(parseIso(undefined)).toBeNull();
  });
});

describe('daysInMonth', () => {
  it('knows February length in common and leap years', () => {
    expect(daysInMonth(2027, 2)).toBe(28);
    expect(daysInMonth(2028, 2)).toBe(29);
  });

  it('applies the century rules (1900 is not a leap year, 2000 is)', () => {
    expect(daysInMonth(1900, 2)).toBe(28);
    expect(daysInMonth(2000, 2)).toBe(29);
  });

  it('gives 30 days for April', () => {
    expect(daysInMonth(2027, 4)).toBe(30);
  });
});

describe('addMonths', () => {
  it('rolls over the year going forward', () => {
    expect(addMonths('2027-12', 1)).toBe('2028-01');
  });

  it('rolls over the year going backward', () => {
    expect(addMonths('2028-01', -1)).toBe('2027-12');
  });

  it('handles steps larger than a year in both directions', () => {
    expect(addMonths('2027-12', 13)).toBe('2029-01');
    expect(addMonths('2028-01', -25)).toBe('2025-12');
  });
});

describe('addDays', () => {
  it('crosses a month boundary', () => {
    expect(addDays('2027-04-30', 1)).toBe('2027-05-01');
    expect(addDays('2027-05-01', -1)).toBe('2027-04-30');
  });

  it('crosses a year boundary', () => {
    expect(addDays('2027-12-31', 1)).toBe('2028-01-01');
  });

  it('steps over a leap day and not over a non-leap February end', () => {
    expect(addDays('2028-02-28', 1)).toBe('2028-02-29');
    expect(addDays('2028-02-29', 1)).toBe('2028-03-01');
    expect(addDays('2027-02-28', 1)).toBe('2027-03-01');
  });

  it('returns null for an invalid date', () => {
    expect(addDays('2027-02-29', 1)).toBeNull();
  });
});

describe('weekdayIndex (Monday = 0)', () => {
  it('returns the Monday-first index of known dates', () => {
    expect(weekdayIndex('2027-04-12')).toBe(0); // Monday
    expect(weekdayIndex('2027-04-01')).toBe(3); // Thursday
    expect(weekdayIndex('2027-04-11')).toBe(6); // Sunday
  });
});

describe('monthGrid', () => {
  it('pads April 2027 with 3 leading nulls (1 April 2027 is a Thursday)', () => {
    const weeks = monthGrid('2027-04');
    expect(weeks[0].slice(0, 3)).toEqual([null, null, null]);
    expect(weeks[0][3]).toBe('2027-04-01');
  });

  it('contains exactly 30 dates for April 2027', () => {
    const dates = monthGrid('2027-04').flat().filter(Boolean);
    expect(dates).toHaveLength(30);
    expect(dates[0]).toBe('2027-04-01');
    expect(dates[29]).toBe('2027-04-30');
  });

  it('makes every week exactly 7 entries long', () => {
    for (const key of ['2027-04', '2028-02', '2027-02', '2027-12']) {
      for (const week of monthGrid(key)) expect(week).toHaveLength(7);
    }
  });

  it('contains 2028-02-29 for February 2028', () => {
    expect(monthGrid('2028-02').flat()).toContain('2028-02-29');
  });

  it('does not contain 29 February in February 2027', () => {
    const dates = monthGrid('2027-02').flat().filter(Boolean);
    expect(dates).toHaveLength(28);
    expect(dates).not.toContain('2027-02-29');
  });
});

describe('monthsBetween', () => {
  it('lists every month touched by the range, across a year boundary', () => {
    expect(monthsBetween('2027-12-20', '2028-02-03')).toEqual(['2027-12', '2028-01', '2028-02']);
  });

  it('returns an empty list when a bound is missing', () => {
    expect(monthsBetween(null, '2028-02-03')).toEqual([]);
  });
});

describe('formatLongDate', () => {
  it('formats a date as "D Month YYYY"', () => {
    expect(formatLongDate('2027-04-12')).toBe('12 April 2027');
  });
});

describe('timezone safety (no new Date(string) on calendar days)', () => {
  // A string such as "2027-01-01" parsed with new Date() is UTC midnight and can shift a day in
  // western time zones. These exact results confirm the helpers never take that path.
  it('formats the first and last day of a year exactly', () => {
    expect(formatLongDate('2027-01-01')).toBe('1 January 2027');
    expect(formatLongDate('2027-12-31')).toBe('31 December 2027');
  });

  it('builds grids whose first and last dates are exact', () => {
    const dec = monthGrid('2027-12').flat().filter(Boolean);
    expect(dec[0]).toBe('2027-12-01');
    expect(dec[dec.length - 1]).toBe('2027-12-31');
    const jan = monthGrid('2027-01').flat().filter(Boolean);
    expect(jan[0]).toBe('2027-01-01');
    expect(jan[jan.length - 1]).toBe('2027-01-31');
  });

  it('does not shift days when adding them across the year end', () => {
    expect(addDays('2027-01-01', 0)).toBe('2027-01-01');
    expect(addDays('2027-12-31', 0)).toBe('2027-12-31');
  });
});
