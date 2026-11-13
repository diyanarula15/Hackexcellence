/**
 * state/bookingStore.js - holiday state + actions. Components read it with `useStore()` and call
 * the actions below; only this file talks to services/travelApi.js.
 *
 * SQLite (backend) is the source of truth for a package. The browser keeps only the package id,
 * in the page URL (`?package=<id>`), so a refresh, the back button or a shared link reopens the
 * same saved package. Nothing about prices or rules is computed here.
 */

import { createStore } from './store.js';
import { ApiError } from '../services/apiClient.js';
import { searchPackageOptions, selectPackageOption as postSelectOption } from '../services/packageOptionsApi.js';
import {
  applyPackageChange,
  exportPackage,
  getDelayScenarios,
  getMeta,
  getPackage,
  getPackageOptions,
  getTripAlternatives,
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
 * change.target: { kind, stay_id?, item_id?, date?, label } - what the drawer is changing.
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

/**
 * delay.status: idle | loading | ready | error | version_conflict | applying
 * delay.batch: the sweep response for `batch.base_version` of the open package (the four scenarios).
 * It is kept after closing so reopening the panel for the same version needs no request.
 * delay.selected: the chosen delay in minutes (60 | 120 | 180 | 240). Switching it never requests.
 * delay.error: { code, message } for a failed load or save. delay.message: the conflict notice.
 */
export const DELAY_LEVELS = Object.freeze([60, 120, 180, 240]);
const CLOSED_DELAY = Object.freeze({ status: 'idle', batch: null, selected: 60, error: null, message: null });

export const bookingStore = createStore({
  meta: { status: 'idle', data: null, error: null },
  form: EMPTY_FORM,
  /** submit.status: idle | loading | invalid | error */
  submit: { status: 'idle', fieldErrors: {}, message: null },
  result: { ...EMPTY_RESULT, focus: 0 },
  exporting: { status: 'idle', name: null, error: null },
  change: CLOSED_CHANGE,
  delay: CLOSED_DELAY,
  /** alternatives.status: idle | loading | ready | error - nearest searches that do have a trip */
  alternatives: { status: 'idle', data: null, error: null },
  /**
   * Attractions the traveler ticked to add together (Phase 8A multi-add), in tick order:
   * [{ attraction_id, name, city, date: 'YYYY-MM-DD', preferred_start: 'HH:MM' | null }].
   */
  attractionSelection: [],
  /** The attraction detail drawer: { open, attraction_id, item_id (visit:<id> when planned) | null, date | null } */
  attractionDetails: { open: false, attraction_id: null, item_id: null, date: null },
  /** The hotel detail drawer: { open, hotel_id, stay_id (the stay it was opened from) | null } */
  hotelDetails: { open: false, hotel_id: null, stay_id: null },
  /** Which top-level overlay is open: null | 'landscape' | 'saved' | 'lookup' */
  panel: null,
  /**
   * The "pick your trip" step (Phase 8B). The options themselves are result.response when
   * result.status === 'OPTIONS' (result.status === 'SEARCHING' while they load).
   * previewId: option whose details are open; selectingId: option being saved; error: message.
   */
  optionPick: { previewId: null, selectingId: null, error: null },
  /**
   * The options list a package was chosen from, so "Back to all options" can show it again:
   * { response, chosen: [package ids picked from it] } | null. Cleared by a new search.
   */
  optionsBack: null,
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
    else if (!packageId && result.packageId) {
      // browser Back from a package chosen from options returns to those options
      if (canGoBackToOptions(get())) showResult({ status: 'OPTIONS', packageId: null, response: get().optionsBack.response }, false);
      else showResult(EMPTY_RESULT, false);
    }
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

/** The request body for POST /api/packages. Converts types only - validation is the backend's. */
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
    alternatives: { status: 'idle', data: null, error: null },
    // a different package: its attraction picks and open details no longer apply
    ...(state.result.packageId !== result.packageId
      ? { attractionSelection: [], attractionDetails: { open: false, attraction_id: null, item_id: null, date: null } }
      : {}),
  }));
}

/**
 * Generate a holiday from the form. Ignored while a generation is already running.
 * @param {{ objective?: 'WITHIN_BUDGET' | 'MINIMUM_COST' }} [options]  MINIMUM_COST is used by the
 *   Price Landscape so the package matches the proven minimum it showed for the chosen date.
 */
export async function generatePackage({ objective } = {}) {
  if (get().submit.status === 'loading') return;
  const body = { ...toRequestBody(get().form), ...(objective ? { objective } : {}) };
  const previous = get().result;
  set({ submit: { status: 'loading', fieldErrors: {}, message: null }, optionPick: CLOSED_PICK, optionsBack: null });
  showResult({ status: 'SEARCHING', request: body }); // option cards show as skeletons meanwhile
  const mine = resultSeq;
  try {
    const response = await searchPackageOptions(body);
    if (mine !== resultSeq) return;
    set({ submit: { status: 'idle', fieldErrors: {}, message: null } });
    if (response.status === 'OPTIONS') {
      // nothing is saved yet: the traveler picks one first
      writePackageIdToUrl(null, 'push');
      showResult({ status: 'OPTIONS', packageId: null, response }, false);
      return;
    }
    const packageId = response.package?.id ?? null;
    writePackageIdToUrl(packageId, 'push');
    showResult({ status: response.status, packageId, response }, false);
    // no trip, or no trip within budget: look for the nearest searches that do work
    if (response.status === 'INFEASIBLE' || response.status === 'OVER_BUDGET') loadAlternatives(body);
  } catch (error) {
    if (mine === resultSeq) showResult(previous, false); // keep what was open before the search
    if (error instanceof ApiError && error.status === 422 && error.body?.field_errors) {
      set({
        submit: { status: 'invalid', fieldErrors: error.body.field_errors, message: error.body.message },
      });
    } else {
      set({ submit: { status: 'error', fieldErrors: {}, message: error.message } });
    }
  }
}

// ── Pick your trip (Phase 8B) ───────────────────────────────────────────────
const CLOSED_PICK = Object.freeze({ previewId: null, selectingId: null, error: null });

/** Open (or with null, close) the read-only details of one option. Nothing is saved. */
export function previewPackageOption(optionId) {
  set((state) => ({ optionPick: { ...state.optionPick, previewId: optionId, error: null } }));
}

/**
 * Choose one option: the backend saves ONLY that one as a normal PLANNED package, and the usual
 * itinerary view opens for it. Ignored while another choice is being saved.
 */
export async function choosePackageOption(optionId) {
  const { result, optionPick } = get();
  if (result.status !== 'OPTIONS' || optionPick.selectingId) return;
  const searchId = result.response.search_id;
  set({ optionPick: { previewId: null, selectingId: optionId, error: null } });
  try {
    const response = await postSelectOption(searchId, optionId);
    if (get().result.status !== 'OPTIONS' || get().result.response?.search_id !== searchId) return;
    const packageId = response.package?.id ?? null;
    const back = get().optionsBack;
    const chosen = back?.response?.search_id === searchId ? back.chosen : [];
    set({
      optionPick: CLOSED_PICK,
      optionsBack: { response: result.response, chosen: packageId ? [...new Set([...chosen, packageId])] : chosen },
    });
    writePackageIdToUrl(packageId, 'push');
    showResult({ status: response.status, packageId, response });
  } catch (error) {
    const expired = error instanceof ApiError && (error.status === 404 || error.status === 410);
    set({
      optionPick: {
        previewId: null,
        selectingId: null,
        error: expired ? 'These options have expired. Search again to see fresh ones.' : error.message,
      },
    });
  }
}

// ── No trip possible: nearest searches that work ───────────────────────────
let alternativesSeq = 0;

/** Ask the backend which one-field changes of this request do have a holiday. */
export async function loadAlternatives(body) {
  alternativesSeq += 1;
  const mine = alternativesSeq;
  const { objective: _ignored, ...trip } = body;
  set({ alternatives: { status: 'loading', data: null, error: null } });
  try {
    const data = await getTripAlternatives(trip);
    if (mine === alternativesSeq) set({ alternatives: { status: 'ready', data, error: null } });
  } catch (error) {
    if (mine === alternativesSeq) set({ alternatives: { status: 'error', data: null, error: error.message } });
  }
}

/** Run a suggested search: put its 7 fields in the form and plan it at its proven minimum price. */
export function searchAlternative(suggestion) {
  const r = suggestion?.request;
  if (!r) return;
  const text = (v) => (v === null || v === undefined ? '' : String(v));
  set({
    form: {
      departure: text(r.departure),
      country: text(r.country),
      start_date: text(r.start_date),
      nights: text(r.nights),
      adults: text(r.adults),
      child_ages: Array.isArray(r.child_ages) ? r.child_ages.join(', ') : '',
      budget: text(r.budget),
    },
  });
  return generatePackage({ objective: 'MINIMUM_COST' });
}

/** Leave the open package (it stays saved) and go back to an empty form and result for a new search. */
export function startNewSearch() {
  alternativesSeq += 1;
  writePackageIdToUrl(null, 'push');
  showResult(EMPTY_RESULT, false);
  set({
    form: EMPTY_FORM,
    submit: { status: 'idle', fieldErrors: {}, message: null },
    alternatives: { status: 'idle', data: null, error: null },
    optionPick: CLOSED_PICK,
    optionsBack: null,
  });
}

/** True when the open package was chosen from an options list that "Back to all options" can reopen. */
export function canGoBackToOptions(state) {
  const back = state.optionsBack;
  return Boolean(back && state.result.packageId && back.chosen.includes(state.result.packageId));
}

/**
 * Show the options list the open package was chosen from again. Nothing is deleted: the chosen
 * package stays saved, and choosing it again opens the same package (the backend reuses it).
 */
export function backToOptions() {
  const back = get().optionsBack;
  if (!back) return;
  writePackageIdToUrl(null, 'push');
  showResult({ status: 'OPTIONS', packageId: null, response: back.response });
  set({ optionPick: CLOSED_PICK });
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

/** Install the server's atomically saved G3 edit and invalidate every old route-dependent view. */
export function acceptCityPlan(response) {
  const pkg = response.package;
  if (!pkg || get().result.packageId !== pkg.id) return;
  changeSeq += 1;
  delaySeq += 1;
  alternativesSeq += 1;
  showResult({ status: response.status, packageId: pkg.id, response }, false);
  set({
    delay: { ...CLOSED_DELAY },
    attractionSelection: [],
    attractionDetails: { open: false, attraction_id: null, item_id: null, date: null },
    panel: null,
    change: { ...CLOSED_CHANGE, notice: `New route saved. Your holiday is now version ${pkg.version}.` },
  });
  writePackageIdToUrl(pkg.id, 'replace');
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

// ── Multi-attraction selection (one preview / one apply for the whole set) ─────
const MAX_SELECTION = 8;

/** Tick / untick an attraction. `entry` = { attraction_id, name, city, date, preferred_start? }. */
export function toggleAttractionSelection(entry) {
  set((state) => {
    const has = state.attractionSelection.some((e) => e.attraction_id === entry.attraction_id);
    if (has) return { attractionSelection: state.attractionSelection.filter((e) => e.attraction_id !== entry.attraction_id) };
    if (state.attractionSelection.length >= MAX_SELECTION) return {};
    return { attractionSelection: [...state.attractionSelection, { preferred_start: null, ...entry }] };
  });
}

/** Change the day or preferred start ('HH:MM' or null = let the planner decide) of a ticked attraction. */
export function updateAttractionSelection(attractionId, patch) {
  set((state) => ({
    attractionSelection: state.attractionSelection.map((e) => (e.attraction_id === attractionId ? { ...e, ...patch } : e)),
  }));
}

export function clearAttractionSelection() {
  set({ attractionSelection: [] });
}

/** Preview adding every ticked attraction at once (nothing is saved until Apply). */
export function previewSelectedAttractions(trigger = null) {
  const pkg = currentPackage();
  const selection = get().attractionSelection;
  if (!pkg || !selection.length || get().change.status === 'applying') return;
  if (trigger) changeTrigger = trigger;
  const n = selection.length;
  const target = { kind: 'attractions', label: `Add ${n} attraction${n === 1 ? '' : 's'}` };
  const additions = selection.map(({ attraction_id, date, preferred_start }) => ({
    attraction_id,
    date,
    ...(preferred_start ? { preferred_start } : {}),
  }));
  return runPreview({ kind: 'ADD_ATTRACTIONS', additions, base_version: pkg.version }, { ...CLOSED_CHANGE, target });
}

/** Preview removing several planned visits at once. `itemIds` = ['visit:<id>', ...]. */
export function previewRemoveAttractions(itemIds, trigger = null) {
  const pkg = currentPackage();
  if (!pkg || !itemIds?.length || get().change.status === 'applying') return;
  if (trigger) changeTrigger = trigger;
  const n = itemIds.length;
  const target = { kind: 'remove_attractions', item_ids: itemIds, label: `Remove ${n} attraction${n === 1 ? '' : 's'}` };
  return runPreview({ kind: 'REMOVE_ATTRACTIONS', item_ids: itemIds, base_version: pkg.version }, { ...CLOSED_CHANGE, target });
}

// ── Attraction details ─────────────────────────────────────────────────────
/** Open the detail drawer. `item_id` is the planned visit ('visit:<id>') or null; `date` the day context. */
export function openAttractionDetails({ attraction_id, item_id = null, date = null }) {
  set({ attractionDetails: { open: true, attraction_id, item_id, date } });
}

export function closeAttractionDetails() {
  set((state) => ({ attractionDetails: { ...state.attractionDetails, open: false } }));
}

/** Open the read-only hotel drawer (photo, facts, rooms, map link) for one catalog hotel. */
export function openHotelDetails({ hotel_id, stay_id = null }) {
  set({ hotelDetails: { open: true, hotel_id, stay_id } });
}

export function closeHotelDetails() {
  set((state) => ({ hotelDetails: { ...state.hotelDetails, open: false } }));
}

// ── Top-level overlays (navigation) ────────────────────────────────────────
/** @param {'landscape' | 'saved' | 'lookup'} name */
export function openPanel(name) {
  set({ panel: name });
}

export function closePanel() {
  set({ panel: null });
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
    const addedBatch = change.command?.kind === 'ADD_ATTRACTIONS';
    set((state) => ({
      result: { ...EMPTY_RESULT, ...state.result, status: response.status ?? 'FOUND', response },
      change: { ...CLOSED_CHANGE, notice },
      ...(addedBatch ? { attractionSelection: [] } : {}),
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
  // Re-run the same preview against the latest version (batch selections stay in the store).
  if (target.kind === 'remove_attraction') previewRemoveAttraction(target.item_id, null, target.label);
  else if (target.kind === 'attractions') previewSelectedAttractions(null);
  else if (target.kind === 'remove_attractions') previewRemoveAttractions(target.item_ids, null);
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

// ── Delay rescue (simulated arrival delays) ────────────────────────────────
// Every outcome, price and time here is the backend's. A proposal is only ever shown in the
// panel: the itinerary on the page changes solely after the traveler saves it.
let delaySeq = 0;
let delayTrigger = null;

const VERSION_NOTICE =
  'Your holiday changed while this check was running, so its results were discarded. The latest saved version is shown below.';

const isVersionConflict = (error) =>
  error instanceof ApiError &&
  error.status === 409 &&
  ['PACKAGE_VERSION_CONFLICT', 'PREVIEW_OUTDATED'].includes(error.body?.error);

const delayError = (error) => ({ code: error.body?.error ?? null, message: error.message });

function patchDelay(patch) {
  set((state) => ({ delay: { ...state.delay, ...patch } }));
}

/** Re-read the saved package into the page (no reload). Used after a version conflict. */
async function refreshPackage(packageId) {
  resultSeq += 1;
  try {
    const response = await getPackage(packageId);
    set((state) => ({ result: { ...state.result, status: response.status, response, error: null } }));
  } catch {
    // The conflict notice still applies; the next open of the panel loads again.
  }
}

async function enterVersionConflict(packageId) {
  patchDelay({ status: 'version_conflict', batch: null, error: null, message: VERSION_NOTICE });
  await refreshPackage(packageId);
}

/** Request the four scenarios for one package version. */
async function loadDelayBatch(packageId, baseVersion) {
  delaySeq += 1;
  const mine = delaySeq;
  patchDelay({ status: 'loading', batch: null, error: null, message: null });
  try {
    const batch = await getDelayScenarios(packageId, baseVersion);
    if (mine !== delaySeq) return;
    patchDelay({ status: 'ready', batch });
  } catch (error) {
    if (mine !== delaySeq) return;
    if (isVersionConflict(error)) await enterVersionConflict(packageId);
    else patchDelay({ status: 'error', batch: null, error: delayError(error) });
  }
}

/**
 * Open the delay panel for the open package. The batch is requested once per package version;
 * reopening for the same version reuses it.
 * @param {HTMLElement | null} [trigger] the button to return focus to
 */
export function openDelayRescue(trigger = null) {
  const { result, delay } = get();
  const pkg = currentPackage();
  if (!result.packageId || !pkg || delay.status === 'applying' || delay.status === 'loading') return;
  if (trigger) delayTrigger = trigger;
  const { batch } = delay;
  if (batch && batch.package_id === result.packageId && batch.base_version === pkg.version) {
    patchDelay({ status: 'ready', error: null, message: null });
    return;
  }
  loadDelayBatch(result.packageId, pkg.version);
}

/** Retry after a failed load or save. */
export function retryDelayRescue() {
  const { result, delay } = get();
  const pkg = currentPackage();
  if (result.packageId && pkg && delay.status !== 'applying') loadDelayBatch(result.packageId, pkg.version);
}

/** Choose a delay length: switching only changes what is displayed, never requests. */
export function selectDelay(minutes) {
  if (!DELAY_LEVELS.includes(minutes) || get().delay.status === 'applying') return;
  patchDelay({ selected: minutes });
}

function restoreDelayFocus() {
  const trigger = delayTrigger;
  delayTrigger = null;
  setTimeout(() => {
    const el = trigger?.isConnected ? trigger : document.getElementById('days-title');
    if (el && !el.matches('button')) el.setAttribute('tabindex', '-1');
    el?.focus();
  }, 0);
}

/** Close the panel. The batch is kept for this version. Ignored while a repair is being saved. */
export function closeDelayRescue() {
  if (get().delay.status === 'applying') return;
  delaySeq += 1;
  patchDelay({ status: 'idle', error: null, message: null });
  restoreDelayFocus();
}

/**
 * Save the selected delay's repair. A fresh single preview issues the token the save presents;
 * the backend re-checks everything. On success the saved package replaces the page's package.
 */
export async function applyDelayRescue() {
  const { delay, result } = get();
  const scenario = delay.batch?.scenarios.find((s) => s.delay_minutes === delay.selected);
  if (delay.status !== 'ready' || !scenario?.can_apply) return;
  delaySeq += 1;
  const mine = delaySeq;
  const command = { kind: 'ARRIVAL_DELAY', delay_minutes: delay.selected, base_version: delay.batch.base_version };
  patchDelay({ status: 'applying', error: null });
  try {
    const preview = await previewPackageChange(result.packageId, command);
    if (mine !== delaySeq) return;
    if (!preview.can_apply || !preview.preview_token) {
      patchDelay({
        status: 'error',
        error: { code: null, message: preview.apply_blocked_reason ?? 'This repair cannot be saved.' },
      });
      return;
    }
    const response = await applyPackageChange(result.packageId, {
      ...command,
      preview_token: preview.preview_token,
    });
    if (mine !== delaySeq) return;
    resultSeq += 1;
    const version = response.package?.version ?? response.change?.version;
    const notice = `Saved. Your holiday is now version ${version}, repaired for a +${command.delay_minutes / 60} h arrival delay.`;
    set((state) => ({
      result: { ...state.result, status: response.status ?? 'FOUND', response, error: null },
      delay: { ...CLOSED_DELAY, selected: state.delay.selected },
      change: { ...CLOSED_CHANGE, notice },
    }));
    restoreDelayFocus();
  } catch (error) {
    if (mine !== delaySeq) return;
    if (isVersionConflict(error)) await enterVersionConflict(result.packageId);
    else patchDelay({ status: 'error', error: delayError(error) });
  }
}
