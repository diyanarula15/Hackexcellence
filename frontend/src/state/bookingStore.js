/**
 * state/bookingStore.js — holiday state + actions. Components read it with `useStore()` and call
 * the actions below; only this file talks to services/travelApi.js.
 *
 * SQLite (backend) is the source of truth for a package. The browser keeps only the package id,
 * in the page URL (`?package=<id>`), so a refresh, the back button or a shared link reopens the
 * same saved package. Nothing about prices or rules is computed here.
 */

import { createStore } from './store.js';
import { ApiError } from '../services/apiClient.js';
import { createPackage, exportPackage, getMeta, getPackage } from '../services/travelApi.js';

/** The 7 request fields, as the traveler typed them (strings). */
export const EMPTY_FORM = Object.freeze({
  departure: '',
  country: '',
  start_date: '',
  nights: '',
  adults: '',
  child_ages: '',
  budget: '',
});

/**
 * result.status: EMPTY | LOADING | FOUND | OVER_BUDGET | INFEASIBLE | SEARCH_INCOMPLETE |
 *                NOT_FOUND | ERROR
 * result.response: the backend envelope `{ status, package, reasons, suggestions, ... }`.
 * result.focus: bumped whenever the result section should scroll into view.
 */
const EMPTY_RESULT = Object.freeze({ status: 'EMPTY', packageId: null, response: null, error: null });

export const bookingStore = createStore({
  meta: { status: 'idle', data: null, error: null },
  form: EMPTY_FORM,
  /** submit.status: idle | loading | invalid | error */
  submit: { status: 'idle', fieldErrors: {}, message: null },
  result: { ...EMPTY_RESULT, focus: 0 },
  exporting: { status: 'idle', name: null, error: null },
});

const get = bookingStore.getState;
const set = bookingStore.setState;
/** Increments on every new result so a slower, older response can never overwrite a newer one. */
let resultSeq = 0;

// ── URL: the durable reference to the open package ─────────────────────────
const PARAM = 'package';

/** @returns {string | null} */
export function packageIdFromUrl() {
  return new URLSearchParams(window.location.search).get(PARAM)?.trim() || null;
}

/** @param {string | null} packageId @param {'push' | 'replace'} mode */
function writePackageIdToUrl(packageId, mode = 'push') {
  const url = new URL(window.location.href);
  if (packageId) url.searchParams.set(PARAM, packageId);
  else url.searchParams.delete(PARAM);
  if (url.href !== window.location.href) {
    window.history[mode === 'replace' ? 'replaceState' : 'pushState'](null, '', url);
  }
}

/**
 * Open the package named in the URL now and on back/forward navigation.
 * @returns {() => void} cleanup
 */
export function startUrlSync() {
  const sync = () => {
    const packageId = packageIdFromUrl();
    const { result } = get();
    if (packageId && packageId !== result.packageId) loadPackage(packageId);
    else if (!packageId && result.packageId) showResult(EMPTY_RESULT, false);
  };
  sync();
  window.addEventListener('popstate', sync);
  return () => window.removeEventListener('popstate', sync);
}

// ── Meta (form options) ────────────────────────────────────────────────────
export async function loadMeta() {
  if (['loading', 'ready'].includes(get().meta.status)) return;
  set({ meta: { status: 'loading', data: null, error: null } });
  try {
    set({ meta: { status: 'ready', data: await getMeta(), error: null } });
  } catch (error) {
    set({ meta: { status: 'error', data: null, error: error.message } });
  }
}

// ── Request form ───────────────────────────────────────────────────────────
/** @param {keyof typeof EMPTY_FORM} name @param {string} value */
export function setField(name, value) {
  set((state) => {
    const { [name]: _cleared, ...fieldErrors } = state.submit.fieldErrors;
    return { form: { ...state.form, [name]: value }, submit: { ...state.submit, fieldErrors } };
  });
}

/** A typed number as a number; anything else is sent as typed so the backend can explain it. */
function asNumber(text) {
  const s = String(text ?? '').trim();
  if (s === '') return null;
  const n = Number(s.replace(/[\s,₹]/g, ''));
  return Number.isFinite(n) ? n : s;
}

/** The request body for POST /api/packages. Converts types only — validation is the backend's. */
export function toRequestBody(form) {
  return {
    departure: form.departure || null,
    country: form.country || null,
    start_date: form.start_date || null,
    nights: asNumber(form.nights),
    adults: asNumber(form.adults),
    child_ages: String(form.child_ages)
      .split(',')
      .map((part) => part.trim())
      .filter(Boolean)
      .map(asNumber),
    budget: asNumber(form.budget),
  };
}

/** Fill an untouched form from a saved package's request, so "edit the trip" starts from it. */
function prefillForm(request) {
  if (!request || Object.values(get().form).some((v) => v !== '')) return;
  const text = (v) => (v === null || v === undefined ? '' : String(v));
  set({
    form: {
      departure: text(request.departure),
      country: text(request.country),
      start_date: text(request.start_date),
      nights: text(request.nights),
      adults: text(request.adults),
      child_ages: Array.isArray(request.child_ages) ? request.child_ages.join(', ') : '',
      budget: text(request.budget),
    },
  });
}

// ── Results ────────────────────────────────────────────────────────────────
function showResult(result, focus = true) {
  resultSeq += 1;
  set((state) => ({
    result: { ...EMPTY_RESULT, ...result, focus: state.result.focus + (focus ? 1 : 0) },
    exporting: { status: 'idle', name: null, error: null },
  }));
}

/** Generate a holiday from the form. Ignored while a generation is already running. */
export async function generatePackage() {
  if (get().submit.status === 'loading') return;
  const body = toRequestBody(get().form);
  set({ submit: { status: 'loading', fieldErrors: {}, message: null } });
  try {
    const response = await createPackage(body);
    set({ submit: { status: 'idle', fieldErrors: {}, message: null } });
    const packageId = response.package?.id ?? null;
    writePackageIdToUrl(packageId, 'push');
    showResult({ status: response.status, packageId, response });
  } catch (error) {
    if (error instanceof ApiError && error.status === 422 && error.body?.field_errors) {
      set({
        submit: { status: 'invalid', fieldErrors: error.body.field_errors, message: error.body.message },
      });
    } else {
      set({ submit: { status: 'error', fieldErrors: {}, message: error.message } });
    }
  }
}

/** Load a saved package by id (from the URL, the "open" box, or a retry). */
export async function loadPackage(packageId) {
  showResult({ status: 'LOADING', packageId }, false);
  const mine = resultSeq;
  try {
    const response = await getPackage(packageId);
    if (mine !== resultSeq) return;
    showResult({ status: response.status, packageId, response });
    prefillForm(response.package?.request);
  } catch (error) {
    if (mine !== resultSeq) return;
    const notFound = error instanceof ApiError && error.status === 404;
    showResult({ status: notFound ? 'NOT_FOUND' : 'ERROR', packageId, error: error.message });
  }
}

/** Open a package id typed by the traveler. */
export function openPackage(packageId) {
  const id = String(packageId ?? '').trim();
  if (!id) return;
  writePackageIdToUrl(id, 'push');
  loadPackage(id);
}

/** Retry whatever failed last: loading the open package. */
export function retryResult() {
  const { packageId } = get().result;
  if (packageId) loadPackage(packageId);
}

/** Download the open package's export file from the backend. */
export async function exportCurrentPackage() {
  const { result, exporting } = get();
  if (!result.packageId || exporting.status === 'loading') return;
  set({ exporting: { status: 'loading', name: null, error: null } });
  try {
    const { name } = await exportPackage(result.packageId);
    set({ exporting: { status: 'done', name, error: null } });
  } catch (error) {
    set({ exporting: { status: 'error', name: null, error: error.message } });
  }
}
