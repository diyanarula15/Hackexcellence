import { request } from './apiClient.js';

export function getCityPlanOptions(packageId, options) {
  return request(`/api/packages/${encodeURIComponent(packageId)}/city-plan-options`, options);
}

export function previewCityPlan(packageId, baseVersion, cityPlan, options) {
  return request(`/api/packages/${encodeURIComponent(packageId)}/preview-change`, {
    method: 'POST', body: { kind: 'CHANGE_CITY_PLAN', base_version: baseVersion, city_plan: cityPlan }, ...options,
  });
}

export function applyCityPlan(packageId, baseVersion, cityPlan, previewToken, options) {
  return request(`/api/packages/${encodeURIComponent(packageId)}/apply-change`, {
    method: 'POST', body: { kind: 'CHANGE_CITY_PLAN', base_version: baseVersion, city_plan: cityPlan, preview_token: previewToken }, ...options,
  });
}
