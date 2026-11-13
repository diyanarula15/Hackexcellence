/**
 * services/packageOptionsApi.js - multi-itinerary search (Phase 8B).
 *
 * POST /api/package-options takes the same body as POST /api/packages. When a holiday is found it
 * answers { status: 'OPTIONS', search_id, options: [...] } and saves nothing; any other outcome
 * (OVER_BUDGET, INFEASIBLE, SEARCH_INCOMPLETE, 422) is exactly what POST /api/packages answers.
 * Choosing an option saves only that one as a normal PLANNED package.
 */

import { request } from './apiClient.js';

export function searchPackageOptions(trip, options) {
  return request('/api/package-options', { method: 'POST', body: trip, ...options });
}

/** @returns {Promise<object>} the same envelope as POST /api/packages (201) for the saved package */
export function selectPackageOption(searchId, optionId, options) {
  return request(`/api/package-options/${encodeURIComponent(searchId)}/select`, {
    method: 'POST',
    body: { option_id: optionId },
    ...options,
  });
}
