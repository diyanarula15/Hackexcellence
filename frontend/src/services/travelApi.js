/**
 * services/travelApi.js — domain API stubs (stays, flights, destinations).
 *
 * UI components and the store import ONLY from this file — never call
 * `fetch` directly. Each function already has its final signature; to go
 * live, set VITE_API_BASE_URL and adjust the endpoint paths / response
 * mapping below. Until then every call resolves with mock data.
 *
 * @typedef {{ id: string, name: string, city: string, pricePerNight: number, rating: number }} Stay
 * @typedef {{ id: string, from: string, to: string, departAt: string, price: number, carrier: string }} Flight
 * @typedef {{ id: string, city: string, country: string }} Destination
 */

import { USE_MOCKS, mockResponse, request } from './apiClient.js';

/** @type {Stay[]} */
const MOCK_STAYS = [
  { id: 'stay_1', name: 'Placeholder Hotel One', city: 'Lisbon', pricePerNight: 142, rating: 4.7 },
  { id: 'stay_2', name: 'Placeholder Hotel Two', city: 'Lisbon', pricePerNight: 98, rating: 4.4 },
  { id: 'stay_3', name: 'Placeholder Resort Three', city: 'Lisbon', pricePerNight: 231, rating: 4.9 },
];

/** @type {Flight[]} */
const MOCK_FLIGHTS = [
  { id: 'flt_1', from: 'DEL', to: 'LIS', departAt: '2027-01-12T06:40:00Z', price: 512, carrier: 'Placeholder Air' },
  { id: 'flt_2', from: 'DEL', to: 'LIS', departAt: '2027-01-12T13:05:00Z', price: 468, carrier: 'Placeholder Air' },
];

/** @type {Destination[]} */
const MOCK_DESTINATIONS = [
  { id: 'dst_1', city: 'Lisbon', country: 'Portugal' },
  { id: 'dst_2', city: 'Kyoto', country: 'Japan' },
  { id: 'dst_3', city: 'Cape Town', country: 'South Africa' },
];

/**
 * Search hotel / resort stays.
 * @param {{ destination: string, checkIn?: string, checkOut?: string, guests?: number }} params
 * @param {{ signal?: AbortSignal }} [options]
 * @returns {Promise<Stay[]>}
 */
export function searchStays(params, { signal } = {}) {
  if (USE_MOCKS) return mockResponse(MOCK_STAYS);
  return request('/stays/search', { query: params, signal });
}

/**
 * Search flights.
 * @param {{ from: string, to: string, date?: string, passengers?: number }} params
 * @param {{ signal?: AbortSignal }} [options]
 * @returns {Promise<Flight[]>}
 */
export function searchFlights(params, { signal } = {}) {
  if (USE_MOCKS) return mockResponse(MOCK_FLIGHTS);
  return request('/flights/search', { query: params, signal });
}

/**
 * Featured / autocomplete destinations.
 * @param {{ query?: string }} [params]
 * @param {{ signal?: AbortSignal }} [options]
 * @returns {Promise<Destination[]>}
 */
export function getDestinations(params = {}, { signal } = {}) {
  if (USE_MOCKS) return mockResponse(MOCK_DESTINATIONS, 200);
  return request('/destinations', { query: params, signal });
}
