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
import {
  applyPackageChange,
  createPackage,
  exportPackage,
  getMeta,
  getPackage,
  getPackageOptions,
  previewPackageChange,
} from '../services/travelApi.js';

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

/**
 * change.status: closed | loading | options | previewing | preview | applying | error
 * change.target: { kind, stay_id?, item_id?, date?, label } — what the drawer is changing.
 * change.options: the options response; change.selectedKey: the chosen option; change.preview: the
 * preview response; change.command: the command that was previewed (with base_version).
 * change.notice: shown after a saved change.
 */
const CLOSED_CHANGE = Object.freeze({
  status: 'closed',
  target: null,
  options: null,
  selectedKey: null,
  slot: '',
  preview: null,
  command: null,
  error: null,
  notice: null,
});

export const bookingStore = createStore({
  meta: { status: 'idle', data: null, error: null },
  form: EMPTY_FORM,
  /** submit.status: idle | loading | invalid | error */
  submit: { status: 'idle', fieldErrors: {}, message: null },
  result: { ...EMPTY_RESULT, focus: 0 },
  exporting: { status: 'idle', name: null, error: null },
  change: CLOSED_CHANGE,
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
    change: CLOSED_CHANGE,
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

// ── Package changes ────────────────────────────────────────────────────────
let changeSeq = 0;
let changeTrigger = null;

export const optionKey = (option) => `${option.catalog_id}|${option.room_id ?? ''}`;

function changeError(error) {
  const body = error.body ?? null;
  return {
    status: error instanceof ApiError ? error.status : 0,
    code: body?.error ?? null,
    message: error.message,
    details: [
      ...(body?.errors ?? []).map((item) => item.message),
      ...(body?.violations ?? []).map((item) => item.message),
    ].filter((text) => text && text !== error.message),
  };
}

function patchChange(patch) {
  set((state) => ({ change: { ...state.change, ...patch } }));
}

function currentPackage() {
  return get().result.response?.package ?? null;
}

/**
 * Open the change drawer for one part of the open package and load its valid options.
 * @param {{ kind: string, stay_id?: string, item_id?: string, date?: string, label?: string }} target
 * @param {HTMLElement | null} [trigger] the button to return focus to
 */
export async function openChange(target, trigger = null) {
  const { result } = get();
  if (!result.packageId || get().change.status === 'applying') return;
  changeSeq += 1;
  const mine = changeSeq;
  if (trigger) changeTrigger = trigger;
  set({ change: { ...CLOSED_CHANGE, status: 'loading', target } });
  try {
    const options = await getPackageOptions(result.packageId, target);
    if (mine !== changeSeq) return;
    patchChange({ status: 'options', options });
  } catch (error) {
    if (mine !== changeSeq) return;
    patchChange({ status: 'error', error: changeError(error) });
  }
}

async function runPreview(command, patch = {}) {
  const { result } = get();
  changeSeq += 1;
  const mine = changeSeq;
  patchChange({ ...patch, status: 'previewing', preview: null, command, error: null });
  try {
    const preview = await previewPackageChange(result.packageId, command);
    if (mine !== changeSeq) return;
    patchChange({ status: 'preview', preview });
  } catch (error) {
    if (mine !== changeSeq) return;
    patchChange({ status: 'error', error: changeError(error) });
  }
}

/** Choose an option: preview it with the package's current version. */
export function selectChangeOption(option) {
  const pkg = currentPackage();
  if (!pkg || option.current || !option.command) return;
  return runPreview({ ...option.command, base_version: pkg.version }, { selectedKey: optionKey(option), slot: '' });
}

/** Choose a departure time of the selected intercity option. */
export function selectChangeSlot(option, slot) {
  const pkg = currentPackage();
  if (!pkg || !slot?.valid || !slot.command) return;
  return runPreview(
    { ...slot.command, base_version: pkg.version },
    { selectedKey: optionKey(option), slot: slot.pickup },
  );
}

/** Remove an attraction: show the preview (and refund) first; the traveler confirms with Apply. */
export function previewRemoveAttraction(itemId, trigger = null, label = 'Remove attraction') {
  const pkg = currentPackage();
  if (!pkg || get().change.status === 'applying') return;
  if (trigger) changeTrigger = trigger;
  const target = { kind: 'remove_attraction', item_id: itemId, label };
  return runPreview({ kind: 'REMOVE_ATTRACTION', item_id: itemId, base_version: pkg.version }, {
    ...CLOSED_CHANGE,
    target,
  });
}

/** Re-run the last preview (after "preview outdated"). */
export function repreviewChange() {
  const { command, target } = get().change;
  if (!command) return;
  const { base_version: _stale, ...rest } = command;
  const pkg = currentPackage();
  if (pkg) runPreview({ ...rest, base_version: pkg.version }, { target });
}

/** Save the previewed change. Sends the preview's token; the backend recomputes and re-checks it. */
export async function applyChange() {
  const { change, result } = get();
  if (change.status !== 'preview' || !change.preview?.valid || !change.preview.preview_token) return;
  changeSeq += 1;
  const mine = changeSeq;
  patchChange({ status: 'applying', error: null });
  try {
    const response = await applyPackageChange(result.packageId, {
      ...change.command,
      preview_token: change.preview.preview_token,
    });
    if (mine !== changeSeq) return;
    resultSeq += 1;
    const notice = `Saved. Your holiday is now version ${response.package?.version ?? response.change?.version}.`;
    set((state) => ({
      result: { ...EMPTY_RESULT, ...state.result, status: response.status ?? 'FOUND', response },
      change: { ...CLOSED_CHANGE, notice },
    }));
    writePackageIdToUrl(result.packageId, 'replace');
    restoreFocus();
  } catch (error) {
    if (mine !== changeSeq) return;
    patchChange({ status: 'error', error: changeError(error) });
  }
}

/** Close the drawer without saving. Ignored while a change is being saved. */
export function closeChange() {
  if (get().change.status === 'applying') return;
  changeSeq += 1;
  set({ change: CLOSED_CHANGE });
  restoreFocus();
}

/** After a version conflict: fetch the latest saved package, then reopen the same change. */
export async function reloadLatest() {
  const { result, change } = get();
  if (!result.packageId || !change.target) return;
  const { target } = change;
  changeSeq += 1;
  patchChange({ status: 'loading', error: null, preview: null, command: null });
  try {
    const response = await getPackage(result.packageId);
    resultSeq += 1;
    set((state) => ({ result: { ...state.result, status: response.status, response, error: null } }));
  } catch (error) {
    patchChange({ status: 'error', error: changeError(error) });
    return;
  }
  if (target.kind === 'remove_attraction') previewRemoveAttraction(target.item_id, null, target.label);
  else openChange(target);
}

export function dismissChangeNotice() {
  patchChange({ notice: null });
}

function restoreFocus() {
  const trigger = changeTrigger;
  changeTrigger = null;
  setTimeout(() => {
    const el = trigger?.isConnected ? trigger : document.getElementById('days-title');
    if (el && !el.matches('button')) el.setAttribute('tabindex', '-1');
    el?.focus();
  }, 0);
}
