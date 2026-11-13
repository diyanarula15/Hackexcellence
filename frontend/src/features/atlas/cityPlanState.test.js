import { afterEach, describe, expect, it } from 'vitest';
import { acceptCityPlan, bookingStore } from '../../state/bookingStore.js';
const original = bookingStore.getState();
afterEach(() => bookingStore.setState(original));
describe('Installing an applied city plan', () => {
  it('updates the active identity and invalidates route-dependent selections and scenarios', () => {
    bookingStore.setState({ result: { packageId: 'one', focus: 0 }, delay: { status: 'ready', batch: { base_version: 1 } },
      attractionSelection: [{ attraction_id: 'old-city' }], attractionDetails: { open: true }, panel: 'atlas' });
    const response = { status: 'FOUND', package: { id: 'one', version: 2, city_plan: [{ city: 'Kyoto', nights: 6 }] } };
    acceptCityPlan(response);
    const state = bookingStore.getState();
    expect(state.result.response).toBe(response); expect(state.result.packageId).toBe('one');
    expect(state.delay.batch).toBeNull(); expect(state.attractionSelection).toEqual([]); expect(state.attractionDetails.open).toBe(false);
    expect(new URL(location.href).searchParams.get('package')).toBe('one');
  });
  it('never replaces another active package after a late apply response', () => {
    const result = { packageId: 'other' }; bookingStore.setState({ result });
    acceptCityPlan({ status: 'FOUND', package: { id: 'one', version: 2 } });
    expect(bookingStore.getState().result).toBe(result);
  });
});
