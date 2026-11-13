// "Search a new trip" leaves the open package and starts from a blank form.
import { describe, expect, it } from 'vitest';
import { EMPTY_FORM, bookingStore, setField, startNewSearch } from './bookingStore.js';

describe('startNewSearch', () => {
  it('clears every field the previous trip filled in', () => {
    setField('departure', 'BLR');
    setField('country', 'Japan');
    setField('start_date', '2027-04-10');
    setField('nights', '6');
    setField('adults', '2');
    setField('child_ages', '6, 9');
    setField('budget', '350000');

    startNewSearch();

    const state = bookingStore.getState();
    expect(state.form).toEqual(EMPTY_FORM);
    expect(state.submit.status).toBe('idle');
  });
});
