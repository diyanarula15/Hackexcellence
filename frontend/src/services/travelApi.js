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
