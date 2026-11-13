import { request } from './apiClient.js';

/** Read a short holiday description into reviewable request fields. This never creates a plan. */
export function parseQuickRequest(text, { signal } = {}) {
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  return request('/api/parse-trip-request', { method: 'POST', body: { text, timezone }, signal });
}
