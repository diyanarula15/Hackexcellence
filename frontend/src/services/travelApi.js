/**
 * services/travelApi.js — the holiday API. The store imports ONLY from here; components never
 * call `fetch` directly. Response shapes are the backend's:
 *   backend/app/routes/packages.py (envelope) · backend/app/services/itinerary.py (package view)
 *
 * The backend owns all planning, pricing and validation; nothing here computes a price.
 */

import { download, request } from './apiClient.js';

/**
 * Form options: departure cities, countries, date window, nights range, traveler cap.
 * @returns {Promise<{ departure_airports: {airport: string, city: string}[],
 *   countries: {code: string, name: string, cities: string[]}[],
 *   allowed_dates: {first_night: string, last_departure: string},
 *   nights: {min: number, max: number, min_per_city: number}, max_travelers: number }>}
 */
/**
 * The nearest changed trips that DO have a valid holiday (one field changed each: start date,
 * departure city or nights), with their proven minimum price. Read-only; nothing is saved.
 * Response: { original, original_status, suggestions: [{ kind, label, change, request,
 *   min_total_inr, within_budget }], planner_searches }.
 */
export function getTripAlternatives(trip, options) {
  return request('/api/trip-alternatives', { method: 'POST', body: trip, ...options });
}

export function getMeta(options) {
  return request('/api/meta', options);
}

/**
 * Plan and save a package from the 7 request fields.
 * Resolves with `{ status, package, reasons, ... }` for FOUND / OVER_BUDGET (a saved package) and
 * INFEASIBLE / SEARCH_INCOMPLETE (package: null). Rejects with an ApiError; a 422 carries
 * `body.field_errors` (INVALID_REQUEST).
 *
 * @param {{ departure: string|null, country: string|null, start_date: string|null,
 *   nights: number|string|null, adults: number|string|null, child_ages: (number|string)[],
 *   budget: number|string|null }} trip
 */
export function createPackage(trip, options) {
  return request('/api/packages', { method: 'POST', body: trip, ...options });
}

/** A saved package exactly as stored (never re-planned). 404 → ApiError with status 404. */
export function getPackage(packageId, options) {
  return request(`/api/packages/${encodeURIComponent(packageId)}`, options);
}

/** Download the saved package in the shared trip JSON format (built by the backend). */
export function exportPackage(packageId) {
  return download(`/api/packages/${encodeURIComponent(packageId)}/export`, {
    fallbackName: 'holiday-package.json',
  });
}

const packagePath = (packageId, suffix) => `/api/packages/${encodeURIComponent(packageId)}/${suffix}`;

/**
 * Valid replacements for one part of a saved package.
 * @param {string} packageId
 * @param {{ kind: string, stay_id?: string, item_id?: string, date?: string }} target
 */
export function getPackageOptions(packageId, { kind, stay_id, item_id, date }, options) {
  return request(packagePath(packageId, 'options'), { query: { kind, stay_id, item_id, date }, ...options });
}

/**
 * The four simulated arrival delays (+1h..+4h) for one saved package, evaluated read-only.
 * Resolves with `{ package_id, base_version, package_status, scheduled_landing, arrival_airport,
 * original_pickup, scenarios: [...4 scenario views], tested_* minutes, exact_absorbed_tolerance_minutes }`.
 * 409 PACKAGE_VERSION_CONFLICT when `baseVersion` is no longer the saved version.
 */
export function getDelayScenarios(packageId, baseVersion, options) {
  return request(packagePath(packageId, 'delay-scenarios'), {
    method: 'POST',
    body: { base_version: baseVersion },
    ...options,
  });
}

/** Evaluate a change command without saving. Always 200 for an evaluated change, valid or not. */
export function previewPackageChange(packageId, command, options) {
  return request(packagePath(packageId, 'preview-change'), { method: 'POST', body: command, ...options });
}

/** Save a change. `command` carries the `preview_token` of the preview the traveler confirmed. */
export function applyPackageChange(packageId, command, options) {
  return request(packagePath(packageId, 'apply-change'), { method: 'POST', body: command, ...options });
}
