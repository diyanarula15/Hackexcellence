/**
 * price-landscape/dateUtils.js — date-only helpers on "YYYY-MM-DD" strings.
 *
 * Calendar days never go through local-time parsing (`new Date("2027-04-12")` is UTC midnight and
 * shows as the 11th west of Greenwich). Arithmetic is done on numbers; Date.UTC is used only to
 * find a weekday, and formatting uses timeZone 'UTC', so a day can never shift.
 */

export const MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
  'September', 'October', 'November', 'December'];
export const WEEKDAY_SHORT = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

const pad = (n) => String(n).padStart(2, '0');

/** "2027-04-12" → { year: 2027, month: 4, day: 12 } (month 1-12), or null if not a real date. */
export function parseIso(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso ?? ''));
  if (!m) return null;
  const [year, month, day] = [Number(m[1]), Number(m[2]), Number(m[3])];
  if (month < 1 || month > 12 || day < 1 || day > daysInMonth(year, month)) return null;
  return { year, month, day };
}

export const toIso = (year, month, day) => `${year}-${pad(month)}-${pad(day)}`;
export const isLeapYear = (year) => (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;

/** Days in a month (month 1-12). */
export function daysInMonth(year, month) {
  return [31, isLeapYear(year) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1];
}

/** "2027-04-12" → "2027-04" */
export const monthKeyOf = (iso) => String(iso).slice(0, 7);

/** "2027-12" + 1 → "2028-01"; works for any positive or negative step. */
export function addMonths(monthKey, step) {
  const [y, m] = monthKey.split('-').map(Number);
  const index = y * 12 + (m - 1) + step;
  return `${Math.floor(index / 12)}-${pad((index % 12) + 1)}`;
}

/** First and last date of a month key. */
export function monthBounds(monthKey) {
  const [y, m] = monthKey.split('-').map(Number);
  return { start: toIso(y, m, 1), end: toIso(y, m, daysInMonth(y, m)) };
}

/** "2027-04-30" + 1 → "2027-05-01" (also across years and leap days). */
export function addDays(iso, days) {
  const d = parseIso(iso);
  if (!d) return null;
  const t = Date.UTC(d.year, d.month - 1, d.day) + days * 86400000;
  const x = new Date(t);
  return toIso(x.getUTCFullYear(), x.getUTCMonth() + 1, x.getUTCDate());
}

/** ISO strings sort lexicographically in date order. */
export const compareIso = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
export const isWithin = (iso, start, end) => Boolean(iso && start && end && iso >= start && iso <= end);

/** Monday = 0 … Sunday = 6. */
export function weekdayIndex(iso) {
  const d = parseIso(iso);
  return (new Date(Date.UTC(d.year, d.month - 1, d.day)).getUTCDay() + 6) % 7;
}

/**
 * Weeks of a month for a Monday-first grid. Each week has 7 entries: an ISO date or null padding.
 * @param {string} monthKey "YYYY-MM"
 * @returns {(string|null)[][]}
 */
export function monthGrid(monthKey) {
  const { start } = monthBounds(monthKey);
  const [y, m] = monthKey.split('-').map(Number);
  const cells = Array(weekdayIndex(start)).fill(null);
  for (let day = 1; day <= daysInMonth(y, m); day += 1) cells.push(toIso(y, m, day));
  while (cells.length % 7) cells.push(null);
  const weeks = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
  return weeks;
}

/** Months (keys) that contain at least one day of [first, last]. */
export function monthsBetween(first, last) {
  if (!first || !last) return [];
  const out = [];
  for (let k = monthKeyOf(first); k <= monthKeyOf(last); k = addMonths(k, 1)) out.push(k);
  return out;
}

/** "2027-04" → "April 2027" */
export function formatMonth(monthKey) {
  const [y, m] = monthKey.split('-').map(Number);
  return `${MONTH_NAMES[m - 1]} ${y}`;
}

/** "2027-04-12" → "12 April 2027" */
export function formatLongDate(iso) {
  const d = parseIso(iso);
  return d ? `${d.day} ${MONTH_NAMES[d.month - 1]} ${d.year}` : '';
}

/** "2027-04-12" → "Mon 12 Apr" */
export function formatShortDate(iso) {
  const d = parseIso(iso);
  return d ? `${WEEKDAY_SHORT[weekdayIndex(iso)]} ${d.day} ${MONTH_NAMES[d.month - 1].slice(0, 3)}` : '';
}
