/**
 * services/savedTripsApi.js — HTTP calls for saved trips (bookmarks on planned packages).
 *
 * Every call goes through apiClient.js (same origin, same error shape: ApiError with a readable
 * message). DELETE answers 204 with no body, so it is the one call that does not parse JSON.
 */

import { API_BASE_URL, ApiError, request } from './apiClient.js';

const trip = (packageId) => `/api/saved-trips/${encodeURIComponent(packageId)}`;

/**
 * Bookmark a planned package. Omitting `name` uses the server's default name for a new bookmark
 * and keeps the existing name for one that is already saved.
 * @returns {Promise<object>} the saved-trip card (201 first save, 200 when already saved)
 */
export function saveTrip(packageId, name) {
  const body = name === undefined ? {} : { name };
  return request(`/api/packages/${encodeURIComponent(packageId)}/save`, { method: 'POST', body });
}

/** @returns {Promise<object[]>} every saved-trip card, newest updated first */
export async function listSavedTrips() {
  const payload = await request('/api/saved-trips');
  return payload.trips;
}

/** @returns {Promise<object>} the updated card */
export function renameSavedTrip(packageId, name) {
  return request(trip(packageId), { method: 'PATCH', body: { name } });
}

/** Removes the bookmark only; the holiday itself is kept. @returns {Promise<void>} */
export async function removeSavedTrip(packageId) {
  let response;
  try {
    response = await fetch(API_BASE_URL + trip(packageId), {
      method: 'DELETE',
      headers: { Accept: 'application/json' },
    });
  } catch {
    throw new ApiError(0, 'Cannot reach the holiday server. Check that the backend is running, then try again.', null);
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new ApiError(response.status, payload?.message ?? `Request failed (${response.status}).`, payload);
  }
}
