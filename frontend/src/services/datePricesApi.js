/**
 * services/datePricesApi.js — client for the Phase 7A Price Landscape endpoint.
 *
 *   POST /api/date-prices   (backend/app/routes/date_prices.py on feature/phase7a-price-calendar)
 *
 * Body: the 7 trip fields of POST /api/packages + range_start / range_end (YYYY-MM-DD).
 * Response (fields this UI reads):
 *   dates: [{ date, status: 'FOUND'|'INFEASIBLE'|'SEARCH_INCOMPLETE', min_total_inr, proven_minimum,
 *             within_budget, difference_vs_reference_inr, proven_savings_inr, incomplete_reason? }]
 *   range_start, range_end, data_window {first_night, last_departure}, range_fully_evaluated,
 *   lowest_proven_date, lowest_proven_total_inr, highest_proven_total_inr,
 *   cheapest_date, cheapest_total_inr, comparison {reference_date, reference_status,
 *   reference_min_total_inr, max_proven_savings_inr, best_saving_date}, status_counts.
 *
 * Every price is computed by the backend planner (objective MINIMUM_COST). Nothing is computed or
 * invented here, and there is no mock fallback: a failure surfaces as an ApiError.
 */

import { request } from './apiClient.js';

export const DATE_PRICES_PATH = '/api/date-prices';

/**
 * @param {object} trip  the 7-field body built by bookingStore.toRequestBody(form)
 * @param {{ rangeStart: string, rangeEnd: string }} range
 * @param {{ signal?: AbortSignal }} [options]
 * @returns {Promise<import('../features/price-landscape/types.js').DatePricesResponse>}
 */
export function getDatePrices(trip, { rangeStart, rangeEnd }, options = {}) {
  return request(DATE_PRICES_PATH, {
    method: 'POST',
    body: { ...trip, range_start: rangeStart, range_end: rangeEnd },
    signal: options.signal,
  });
}
