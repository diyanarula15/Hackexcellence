// API times are local to their destination. Format dates in UTC to avoid shifting days by timezone.

const INR = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 });
const DAY = new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', weekday: 'short', day: 'numeric', month: 'short' });
const DATE = new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', day: 'numeric', month: 'short', year: 'numeric' });

/** 233632 → "₹2,33,632" */
export const formatINR = (amount) => (Number.isFinite(amount) ? INR.format(amount) : '-');

function utcDay(iso) {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

/** Rupees with an explicit sign, for a price difference the backend already computed. */
export const formatSignedINR = (amount) =>
  Number.isFinite(amount) ? `${amount > 0 ? '+' : amount < 0 ? '-' : ''}${INR.format(Math.abs(amount))}` : '-';

/** "2027-04-10…" → "Sat 10 Apr" */
export const formatDay = (iso) => (iso ? DAY.format(utcDay(iso)) : '');

/** "2027-04-10…" → "10 Apr 2027" */
export const formatDate = (iso) => (iso ? DATE.format(utcDay(iso)) : '');

/** "2027-04-10T10:30" → "10:30" (local time at that place) */
export const formatTime = (iso) => (iso && iso.length >= 16 ? iso.slice(11, 16) : '');

/** 135 → "2h 15m" */
export function formatDuration(minutes) {
  if (!Number.isFinite(minutes)) return '';
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (!h) return `${m}m`;
  return m ? `${h}h ${m}m` : `${h}h`;
}

/** (2, 'night') → "2 nights" */
export const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** "AIRPORT_TAXI" → "Airport taxi" */
export const humanize = (code) =>
  code ? code.toLowerCase().replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase()) : '';

/** {adults: 2, child_ages: [6]} → "2 adults · 1 child (6)" */
export function formatTravelers({ adults, child_ages: ages = [] }) {
  const parts = [plural(adults, 'adult')];
  if (ages.length) parts.push(`${plural(ages.length, 'child', 'children')} (${ages.join(', ')})`);
  return parts.join(' · ');
}

/** Smooth-scroll to the end of the opening sequence, where the request form lives. */
export function scrollToPlanner() {
  const track = document.querySelector('[data-scroll-track]');
  if (!track) return;
  const top = track.getBoundingClientRect().bottom + window.scrollY - window.innerHeight;
  window.scrollTo({ top: Math.max(top, 0), behavior: 'smooth' });
}
