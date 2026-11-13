/**
 * price-landscape/useMonthPrices.js — loads one month of proven prices, safely.
 *
 * - One request per (trip, month); finished months are kept for the life of the dialog, so going
 *   back is instant (the backend caches too).
 * - In-flight requests are shared: React StrictMode runs an effect twice in development, and the
 *   second run for the same (trip, range) reuses the pending request instead of asking the backend
 *   again. A shared request is never aborted (the backend would still compute it); a stale result
 *   is simply ignored. A request leaves the shared map as soon as it settles, so a failed request
 *   is never reused and Retry always fires a new one.
 * - Rapid month changes: a sequence number makes sure a slower old response can never overwrite the
 *   month now on screen.
 * - A month with no day inside the travel window is not fetched at all (status 'outside').
 * - The reference (original) date is fetched separately when it is not in the visible month, so a
 *   comparison never relies on a guess.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { getDatePrices } from '../../services/datePricesApi.js';
import { monthBounds, monthKeyOf } from './dateUtils.js';

const tripKey = (trip) => JSON.stringify(trip);

/** `${tripKey}|${start}|${end}` -> the pending promise for that request (removed when it settles). */
const inFlight = new Map();

/**
 * Starts the request for `key`, or returns the one already in flight for it. The request is not
 * tied to any component, so cleanup never cancels it.
 */
function sharedRequest(key, send) {
  const pending = inFlight.get(key);
  if (pending) return pending;
  const promise = send(new AbortController().signal);
  inFlight.set(key, promise);
  const settle = () => {
    if (inFlight.get(key) === promise) inFlight.delete(key);
  };
  promise.then(settle, settle);
  return promise;
}

function overlapsWindow(monthKey, window) {
  if (!window) return true;
  const { start, end } = monthBounds(monthKey);
  return end >= window.first_night && start <= window.last_departure;
}

/**
 * @param {object} trip  7-field request body
 * @param {string} monthKey  "YYYY-MM"
 * @param {{ first_night: string, last_departure: string } | null} window
 * @param {typeof getDatePrices} [fetcher]  injectable for tests
 */
export function useMonthPrices(trip, monthKey, window, fetcher = getDatePrices) {
  const key = tripKey(trip);
  const cache = useRef(new Map());          // `${key}|${month}` -> response
  const seq = useRef(0);
  const [state, setState] = useState({ status: 'idle', month: monthKey, response: null, error: null });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const cacheKey = `${key}|${monthKey}`;
    seq.current += 1;
    const mine = seq.current;
    if (!overlapsWindow(monthKey, window)) {
      setState({ status: 'outside', month: monthKey, response: null, error: null });
      return undefined;
    }
    const hit = cache.current.get(cacheKey);
    if (hit) {
      setState({ status: 'ready', month: monthKey, response: hit, error: null });
      return undefined;
    }
    // never show the previous month's prices while this one loads
    setState({ status: 'loading', month: monthKey, response: null, error: null });
    const { start, end } = monthBounds(monthKey);
    sharedRequest(`${key}|${start}|${end}`, (signal) =>
      fetcher(JSON.parse(key), { rangeStart: start, rangeEnd: end }, { signal }))
      .then((response) => {
        if (mine !== seq.current) return;              // stale: a newer month is on screen
        // only keep a month once every date in it has a final answer; incomplete ones are re-asked
        if (response?.range_fully_evaluated !== false) cache.current.set(cacheKey, response);
        setState({ status: 'ready', month: monthKey, response, error: null });
      })
      .catch((error) => {
        if (mine !== seq.current) return;
        setState({ status: 'error', month: monthKey, response: null, error });
      });
    return undefined;   // no abort: the request may be shared; a stale result is ignored above
  }, [key, monthKey, window?.first_night, window?.last_departure, attempt, fetcher]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  // a state left over from another month is never returned as this month's
  const current = state.month === monthKey ? state : { status: 'loading', month: monthKey, response: null, error: null };
  return { ...current, retry };
}

/**
 * The proven result for the traveler's original date, wherever it is in the calendar.
 * @returns {{ status: 'idle'|'loading'|'ready'|'error', cell: object | null }}
 */
export function useReferenceCell(trip, referenceDate, visibleMonth, monthState, fetcher = getDatePrices) {
  const key = tripKey(trip);
  const monthResponse = monthState.status === 'ready' ? monthState.response : null;
  const inMonth = monthResponse?.dates?.find((c) => c.date === referenceDate) ?? null;
  const [state, setState] = useState({ status: 'idle', cell: null, key: null });

  // the visible month's own request already covers the original date when it is on screen
  const sameMonth = Boolean(referenceDate) && monthKeyOf(referenceDate) === visibleMonth;
  const needFetch = Boolean(referenceDate) && !sameMonth;
  useEffect(() => {
    if (!needFetch || state.key === `${key}|${referenceDate}`) return undefined;
    setState({ status: 'loading', cell: null, key: `${key}|${referenceDate}` });
    sharedRequest(`${key}|${referenceDate}|${referenceDate}`, (signal) =>
      fetcher(JSON.parse(key), { rangeStart: referenceDate, rangeEnd: referenceDate }, { signal }))
      .then((r) => setState({ status: 'ready', cell: r?.dates?.find((c) => c.date === referenceDate) ?? null,
        key: `${key}|${referenceDate}` }))
      .catch(() => setState({ status: 'error', cell: null, key: `${key}|${referenceDate}` }));
    return undefined;   // no abort: shared with a StrictMode re-run; see sharedRequest
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [needFetch, key, referenceDate, fetcher]);

  if (sameMonth) return { status: monthState.status === 'loading' ? 'loading' : 'ready', cell: inMonth };
  return needFetch ? { status: state.status, cell: state.cell } : { status: 'ready', cell: null };
}
