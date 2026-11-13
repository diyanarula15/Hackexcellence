/** services/attractionsApi.js — read-only attraction details for the detail drawer. */

import { request } from './apiClient.js';

/**
 * @param {string} attractionId  catalog id, e.g. `ATT-KYO-001`.
 * @param {{ signal?: AbortSignal }} [options]
 * @returns {Promise<{ attraction_id: string, name: string, name_ja: string|null, city: string,
 *   country: string, category: string, open_days: string[], open_from: string, open_until: string,
 *   closed_dates: string[], visit_minutes: number, child_friendly: boolean, accessible: boolean,
 *   price_per_person_inr: number, child_price_inr: number|null, image_url: string|null,
 *   image_credit: string|null, maps_url: string }>}
 * @throws {ApiError} 404 when the attraction is not in the catalog.
 */
export function getAttraction(attractionId, { signal } = {}) {
  return request(`/api/attractions/${encodeURIComponent(attractionId)}`, { signal });
}
