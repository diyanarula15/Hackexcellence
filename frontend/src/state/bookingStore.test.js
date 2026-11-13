// Store flows: "Search a new trip" starts blank; "Back to all options" returns to the list a package came from.
import { afterEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  options: {
    status: 'OPTIONS',
    search_id: 'search-1',
    options: [{ option_id: 'opt-1' }, { option_id: 'opt-2' }, { option_id: 'opt-3' }],
  },
}));

vi.mock('../services/packageOptionsApi.js', () => ({
  searchPackageOptions: vi.fn(async () => api.options),
  selectPackageOption: vi.fn(async (_searchId, optionId) => ({
    status: 'FOUND',
    package: { id: `pkg-${optionId}`, status: 'PLANNED' },
  })),
}));

const store = await import('./bookingStore.js');
const { EMPTY_FORM, backToOptions, bookingStore, canGoBackToOptions, choosePackageOption, generatePackage, setField, startNewSearch } = store;

function fillForm() {
  setField('departure', 'BLR');
  setField('country', 'Japan');
  setField('start_date', '2027-04-10');
  setField('nights', '6');
  setField('adults', '2');
  setField('child_ages', '6, 9');
  setField('budget', '350000');
}

afterEach(() => startNewSearch());

describe('startNewSearch', () => {
  it('clears every field the previous trip filled in', () => {
    fillForm();
    startNewSearch();
    const state = bookingStore.getState();
    expect(state.form).toEqual(EMPTY_FORM);
    expect(state.submit.status).toBe('idle');
  });
});

describe('back to all options', () => {
  it('reopens the same options list after choosing one, and choosing another works', async () => {
    fillForm();
    await generatePackage();
    expect(bookingStore.getState().result.status).toBe('OPTIONS');

    await choosePackageOption('opt-2');
    let state = bookingStore.getState();
    expect(state.result.packageId).toBe('pkg-opt-2');
    expect(canGoBackToOptions(state)).toBe(true);

    backToOptions();
    state = bookingStore.getState();
    expect(state.result.status).toBe('OPTIONS');
    expect(state.result.response.search_id).toBe('search-1');
    expect(state.result.response.options).toHaveLength(3);

    await choosePackageOption('opt-3');
    state = bookingStore.getState();
    expect(state.result.packageId).toBe('pkg-opt-3');
    expect(state.optionsBack.chosen).toEqual(['pkg-opt-2', 'pkg-opt-3']);
    expect(canGoBackToOptions(state)).toBe(true);
  });

  it('is not offered after a new search', async () => {
    fillForm();
    await generatePackage();
    await choosePackageOption('opt-1');
    startNewSearch();
    expect(canGoBackToOptions(bookingStore.getState())).toBe(false);
    expect(bookingStore.getState().optionsBack).toBeNull();
  });
});
