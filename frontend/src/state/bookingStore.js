/**
 * state/bookingStore.js — app state + actions for search and results.
 *
 * Data flow:  widget → action (here) → services/travelApi.js → setState →
 *             subscribed widgets re-render.
 *
 * Usage inside a component:
 *   const results = useStore(bookingStore, (s) => s.results);
 *   <button onClick={() => runStaySearch({ destination: 'Lisbon' })} />
 */

import { createStore } from './store.js';
import { searchStays } from '../services/travelApi.js';

/**
 * @typedef {'idle' | 'loading' | 'success' | 'error'} Status
 */

export const bookingStore = createStore({
  /** Current search form values. Extend freely once the brief is known. */
  query: { destination: '', checkIn: '', checkOut: '', guests: 2 },
  /** Async result state for the results grid. */
  results: { /** @type {Status} */ status: 'idle', items: [], error: null },
});

let activeRequest = null;

/**
 * Update search form fields.
 * @param {Partial<{ destination: string, checkIn: string, checkOut: string, guests: number }>} patch
 */
export function setQuery(patch) {
  bookingStore.setState((state) => ({ query: { ...state.query, ...patch } }));
}

/**
 * Run a stay search with the current (or supplied) query and store the
 * outcome. A newer call aborts the previous in-flight request.
 * @param {Partial<{ destination: string, checkIn: string, checkOut: string, guests: number }>} [overrides]
 * @returns {Promise<void>}
 */
export async function runStaySearch(overrides) {
  if (overrides) setQuery(overrides);
  activeRequest?.abort();
  const controller = (activeRequest = new AbortController());

  bookingStore.setState({ results: { status: 'loading', items: [], error: null } });
  try {
    const items = await searchStays(bookingStore.getState().query, { signal: controller.signal });
    if (controller.signal.aborted) return;
    bookingStore.setState({ results: { status: 'success', items, error: null } });
  } catch (error) {
    if (controller.signal.aborted) return;
    bookingStore.setState({ results: { status: 'error', items: [], error: error.message } });
  }
}
