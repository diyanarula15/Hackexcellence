/**
 * price-landscape/types.js — shapes shared by the Price Landscape (JSDoc; the app is plain JS).
 *
 * @typedef {'FOUND' | 'INFEASIBLE' | 'SEARCH_INCOMPLETE'} DatePriceStatus
 *
 * @typedef {object} DatePriceCell  one start date from POST /api/date-prices
 * @property {string} date                         YYYY-MM-DD
 * @property {DatePriceStatus} status
 * @property {number | null} min_total_inr         proven minimum (FOUND only), integer INR
 * @property {boolean} proven_minimum
 * @property {boolean | null} [within_budget]
 * @property {number | null} [difference_vs_reference_inr]  this date minus the reference (both proven)
 * @property {number | null} [proven_savings_inr]           reference minus this date, when > 0
 * @property {string} [incomplete_reason]
 *
 * @typedef {object} DatePricesResponse
 * @property {DatePriceCell[]} dates
 * @property {string} range_start
 * @property {string} range_end
 * @property {{ first_night: string, last_departure: string }} data_window
 * @property {boolean} range_fully_evaluated
 * @property {string | null} lowest_proven_date
 * @property {number | null} lowest_proven_total_inr
 * @property {number | null} highest_proven_total_inr
 * @property {string | null} cheapest_date       only when range_fully_evaluated
 * @property {number | null} cheapest_total_inr
 * @property {{ reference_date: string, reference_status: DatePriceStatus | null,
 *              reference_min_total_inr: number | null, max_proven_savings_inr: number | null,
 *              best_saving_date: string | null }} comparison
 *
 * @typedef {'FOUND' | 'INFEASIBLE' | 'SEARCH_INCOMPLETE' | 'LOADING' | 'OUTSIDE_WINDOW' |
 *           'NOT_ELIGIBLE' | 'ERROR'} TileState
 *   OUTSIDE_WINDOW: not in the catalog's travel window. NOT_ELIGIBLE: inside the window but the
 *   trip would not fit (the backend did not list it). ERROR: the month failed to load.
 *
 * @typedef {'IDLE' | 'LOADING' | 'READY' | 'PARTIALLY_EVALUATED' | 'EMPTY' | 'ERROR'} ViewState
 */

export const FOUND = 'FOUND';
export const INFEASIBLE = 'INFEASIBLE';
export const SEARCH_INCOMPLETE = 'SEARCH_INCOMPLETE';
export const LOADING = 'LOADING';
export const OUTSIDE_WINDOW = 'OUTSIDE_WINDOW';
export const NOT_ELIGIBLE = 'NOT_ELIGIBLE';
export const ERROR = 'ERROR';
