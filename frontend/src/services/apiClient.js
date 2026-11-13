/**
 * services/apiClient.js — the ONE place that talks HTTP.
 *
 * Paths are `/api/...` on the page's own origin; Vite proxies them to the FastAPI backend (see
 * vite.config.js). Set `VITE_API_BASE_URL` only to call a backend on another origin.
 *
 * There is deliberately no mock mode: when the backend is down the UI shows an error and a retry,
 * never an invented holiday.
 */

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '';

const UNREACHABLE = 'Cannot reach the holiday server. Check that the backend is running, then try again.';

/** Error thrown for any failed request. `status` is 0 when the server could not be reached. */
export class ApiError extends Error {
  /**
   * @param {number} status  HTTP status code (0 = no response).
   * @param {string} message  Text that can be shown to the traveler.
   * @param {unknown} [body]  Parsed JSON error payload, if any.
   */
  constructor(status, message, body) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
}

/** @param {string} path @param {Record<string, string | number | undefined>} [query] */
function buildUrl(path, query) {
  const url = new URL(API_BASE_URL + path, window.location.origin);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== '') url.searchParams.set(key, String(value));
  }
  return url;
}

/** fetch() that turns "no response at all" into an ApiError with status 0. */
async function send(url, init) {
  try {
    return await fetch(url, init);
  } catch (error) {
    if (error?.name === 'AbortError') throw error;
    throw new ApiError(0, UNREACHABLE, null);
  }
}

/** The ApiError for a non-2xx response. */
async function failure(response) {
  const payload = await response.json().catch(() => null);
  const message =
    payload?.message ??
    (response.status >= 500
      ? 'The holiday server had a problem (or is not running). Please try again.'
      : `Request failed (${response.status} ${response.statusText}).`);
  return new ApiError(response.status, message, payload);
}

/**
 * JSON request: base URL, query string, headers, error normalisation.
 *
 * @param {string} path  e.g. `/api/packages`.
 * @param {{ method?: string, query?: Record<string, string | number | undefined>,
 *           body?: unknown, signal?: AbortSignal }} [options]
 * @returns {Promise<any>} Parsed JSON body.
 * @throws {ApiError}
 */
export async function request(path, { method = 'GET', query, body, signal } = {}) {
  const response = await send(buildUrl(path, query), {
    method,
    signal,
    headers: {
      Accept: 'application/json',
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw await failure(response);
  return response.json();
}

/**
 * Download a file the backend serves (as-is: nothing is generated in the browser).
 * The file name comes from the response's Content-Disposition header.
 *
 * @param {string} path
 * @param {{ fallbackName?: string }} [options]
 * @returns {Promise<{ name: string, size: number }>}
 * @throws {ApiError}
 */
export async function download(path, { fallbackName = 'download' } = {}) {
  const response = await send(buildUrl(path), { headers: { Accept: 'application/json' } });
  if (!response.ok) throw await failure(response);
  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition') ?? '';
  const name = /filename="?([^";]+)"?/i.exec(disposition)?.[1] ?? fallbackName;

  const href = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = href;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
  return { name, size: blob.size };
}
