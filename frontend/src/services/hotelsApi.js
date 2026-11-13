/** services/hotelsApi.js — read-only hotel details and the photo credits list. */

import { request } from './apiClient.js';

/**
 * @param {string} hotelId  catalog id, e.g. `HTL-TYO-001`.
 * @param {{ signal?: AbortSignal }} [options]
 * @returns {Promise<{ hotel_id: string, name: string, city: string, country: string|null, area: string|null,
 *   stars: number|null, rating: number|null, check_in_from: string|null, check_out_until: string|null,
 *   family_friendly: boolean|null, rooms: object[], image_url: string|null, image_credit: string|null,
 *   image_is_sample: boolean, maps_url: string }>}
 * @throws {ApiError} 404 when the hotel is not in the catalog.
 */
export function getHotel(hotelId, { signal } = {}) {
  return request(`/api/hotels/${encodeURIComponent(hotelId)}`, { signal });
}

/** Every photo the app can show, with source, author and license. */
export function getPhotoCredits({ signal } = {}) {
  return request('/api/photo-credits', { signal });
}
