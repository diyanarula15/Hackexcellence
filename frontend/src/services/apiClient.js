/**
 * services/apiClient.js — the ONE place that talks HTTP.
 *
 * Set `VITE_API_BASE_URL` in `.env.local` to point at the backend. While it
 * is unset, `USE_MOCKS` is true and `travelApi.js` serves canned data, so the
 * UI can be built before the backend exists.
 */

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '';
export const USE_MOCKS = !API_BASE_URL;

/** Error thrown for any non-2xx response. */
export class ApiError extends Error {
  /**
   * @param {number} status  HTTP status code.
   * @param {string} message
   * @param {unknown} [body]  Parsed error payload, if any.
   */
  constructor(status, message, body) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
}

/**
 * JSON fetch wrapper: base URL, query string, headers, error normalisation.
 * Add auth headers / retry / logging HERE so every endpoint inherits them.
 *
 * @param {string} path  Path relative to the API base, e.g. `/stays/search`.
 * @param {{
 *   method?: string,
 *   query?: Record<string, string | number | undefined>,
 *   body?: unknown,
 *   signal?: AbortSignal,
 * }} [options]
 * @returns {Promise<any>} Parsed JSON body.
 * @throws {ApiError}
 */
export async function request(path, { method = 'GET', query, body, signal } = {}) {
  const url = new URL(API_BASE_URL + path, window.location.origin);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== '') url.searchParams.set(key, String(value));
  }

  const response = await fetch(url, {
    method,
    signal,
    headers: {
      Accept: 'application/json',
      ...(body ? { 'Content-Type': 'application/json' } : {}),
      // TODO(hackathon): Authorization: `Bearer ${token}`
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  const payload = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, payload?.message ?? response.statusText, payload);
  return payload;
}

/**
 * Resolve mock data after a realistic delay (used when USE_MOCKS is true).
 * @template T
 * @param {T} data
 * @param {number} [ms]
 * @returns {Promise<T>}
 */
export function mockResponse(data, ms = 450) {
  return new Promise((resolve) => setTimeout(() => resolve(structuredClone(data)), ms));
}
