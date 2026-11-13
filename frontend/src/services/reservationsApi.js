/** Reservation endpoints. The server owns confirmation and the stored judge JSON. */
import { download, request } from './apiClient.js';

export function confirmHoliday(packageId, baseVersion) {
  return request(`/api/packages/${encodeURIComponent(packageId)}/confirm`, {
    method: 'POST',
    body: { base_version: baseVersion },
  });
}

export function getReservation(reference) {
  return request(`/api/reservations/${encodeURIComponent(reference.trim())}`);
}

export function exportReservation(reference) {
  return download(`/api/reservations/${encodeURIComponent(reference.trim())}/export`, {
    fallbackName: 'holiday-reservation.json',
  });
}
