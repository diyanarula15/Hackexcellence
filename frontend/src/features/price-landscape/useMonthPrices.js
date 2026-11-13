/**
 * price-landscape/useMonthPrices.js — loads one month of proven prices, safely.
 *
 * - One request per (trip, month); finished months are kept for the life of the dialog, so going
 *   back is instant (the backend caches too).
 * - Rapid month changes: the previous request is aborted AND tagged with a sequence number, so a
 *   slower old response can never overwrite the month now on screen.
 * - A month with no day inside the travel window is not fetched at all (status 'outside').
 * - The reference (original) date is fetched separately when it is not in the visible month, so a
 *   comparison never relies on a guess.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { getDatePrices } from '../../services/datePricesApi.js';
import { monthBounds, monthKeyOf } from './dateUtils.js';

const tripKey = (trip) => JSON.stringify(trip);

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
    const controller = new AbortController();
    const { start, end } = monthBounds(monthKey);
    fetcher(JSON.parse(key), { rangeStart: start, rangeEnd: end }, { signal: controller.signal })
      .then((response) => {
        if (mine !== seq.current) return;              // stale: a newer month is on screen
        // only keep a month once every date in it has a final answer; incomplete ones are re-asked
        if (response?.range_fully_evaluated !== false) cache.current.set(cacheKey, response);
        setState({ status: 'ready', month: monthKey, response, error: null });
      })
      .catch((error) => {
        if (error?.name === 'AbortError' || mine !== seq.current) return;
        setState({ status: 'error', month: monthKey, response: null, error });
      });
    return () => controller.abort();
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
    const controller = new AbortController();
    setState({ status: 'loading', cell: null, key: `${key}|${referenceDate}` });
    fetcher(JSON.parse(key), { rangeStart: referenceDate, rangeEnd: referenceDate }, { signal: controller.signal })
      .then((r) => setState({ status: 'ready', cell: r?.dates?.find((c) => c.date === referenceDate) ?? null,
        key: `${key}|${referenceDate}` }))
      .catch((error) => {
        if (error?.name !== 'AbortError') setState({ status: 'error', cell: null, key: `${key}|${referenceDate}` });
      });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [needFetch, key, referenceDate, fetcher]);

  if (sameMonth) return { status: monthState.status === 'loading' ? 'loading' : 'ready', cell: inMonth };
  return needFetch ? { status: state.status, cell: state.cell } : { status: 'ready', cell: null };
}
