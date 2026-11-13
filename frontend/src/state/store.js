/**
 * state/store.js - 40-line, dependency-free state container.
 *
 * Enough for a hackathon (subscribe / select / update); API-compatible in
 * spirit with Zustand, so swapping it in later is a small change confined
 * to this folder.
 */

import { useSyncExternalStore } from 'react';

/**
 * Create an observable store.
 * @template T
 * @param {T} initialState
 * @returns {{
 *   getState: () => T,
 *   setState: (patch: Partial<T> | ((state: T) => Partial<T>)) => void,
 *   subscribe: (listener: () => void) => () => void,
 * }}
 */
export function createStore(initialState) {
  let state = initialState;
  const listeners = new Set();

  return {
    getState: () => state,
    setState(patch) {
      const next = typeof patch === 'function' ? patch(state) : patch;
      state = { ...state, ...next };
      listeners.forEach((listener) => listener());
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

/**
 * React hook: subscribe a component to a slice of a store.
 * The selector must return a stable reference (a primitive or an object that
 * already lives in state) - do not build new objects inside it.
 *
 * @template T, S
 * @param {ReturnType<typeof createStore<T>>} store
 * @param {(state: T) => S} [selector]
 * @returns {S}
 */
export function useStore(store, selector = (state) => state) {
  return useSyncExternalStore(store.subscribe, () => selector(store.getState()));
}
