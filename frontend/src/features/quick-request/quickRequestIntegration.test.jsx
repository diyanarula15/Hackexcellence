import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import RequestForm from '../RequestForm.jsx';
import { applyParsedTrip, bookingStore, EMPTY_FORM, setField } from '../../state/bookingStore.js';
import { parseQuickRequest } from '../../services/quickRequestApi.js';
import { searchPackageOptions } from '../../services/packageOptionsApi.js';
import { formReadiness } from './formReadiness.js';
vi.mock('../../services/quickRequestApi.js', () => ({ parseQuickRequest: vi.fn() }));
vi.mock('../../services/packageOptionsApi.js', () => ({ searchPackageOptions: vi.fn(), selectPackageOption: vi.fn() }));
vi.mock('../price-landscape/ExploreDatesButton.jsx', () => ({ default: () => null }));
vi.mock('../DateField.jsx', () => ({ default: ({ onChange, ...props }) => <input {...props} onChange={(e) => onChange(e.target.value)} /> }));
const initial = bookingStore.getState();
const meta = { departure_airports: [{ city: 'Bengaluru', airport: 'BLR' }, { city: 'Delhi', airport: 'DEL' }], countries: [{ name: 'Japan', code: 'JP' }],
  nights: { min: 3, max: 10 }, max_travelers: 9, allowed_dates: { first_night: '2027-04-01', last_departure: '2027-04-20' } };
const fields = { departure: 'BLR', country: 'Japan', start_date: '2027-04-10', nights: 6, adults: 2, child_ages: [6], budget: 350000 };
const parsed = { status: 'READY', fields, missing_fields: [], issues: [], assumptions: [],
  interpretations: Object.fromEntries(Object.keys(fields).map((key) => [key, { value: fields[key], status: 'EXPLICIT' }])) };
beforeEach(() => {
  vi.clearAllMocks();
  bookingStore.setState({ ...initial, form: { ...EMPTY_FORM }, meta: { status: 'ready', data: meta }, naturalLanguage: { active: false, unresolved: [] } });
  vi.stubGlobal('matchMedia', () => ({ matches: true }));
  parseQuickRequest.mockResolvedValue(parsed);
  searchPackageOptions.mockResolvedValue({ status: 'OPTIONS', search_id: 'real-flow', options: [] });
});
afterEach(() => { cleanup(); bookingStore.setState(initial); vi.unstubAllGlobals(); });
async function understand(user) {
  await user.click(screen.getByRole('button', { name: /Describe your trip/ }));
  await user.type(screen.getByRole('textbox', { name: /What do you have in mind/ }), 'Japan trip for my family');
  await user.click(screen.getByRole('button', { name: 'Understand My Trip' }));
  await screen.findByRole('button', { name: 'Use Extracted Details' });
}
describe('S1 form and planner handoff', () => {
  it('applies only on review, then uses the existing option search with manual corrections', async () => {
    const user = userEvent.setup(); render(<RequestForm />); await understand(user);
    expect(bookingStore.getState().form).toEqual(EMPTY_FORM);
    expect(searchPackageOptions).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Use Extracted Details' }));
    expect(bookingStore.getState().form.child_ages).toBe('6');
    const budget = screen.getByLabelText('Budget (₹)'); await user.clear(budget); await user.type(budget, '400000');
    await user.click(screen.getByRole('button', { name: 'Find Holidays' }));
    await waitFor(() => expect(searchPackageOptions).toHaveBeenCalledWith({ ...fields, budget: 400000 }));
  });
  it('requires missing child ages and date before enabling holiday search', async () => {
    parseQuickRequest.mockResolvedValue({ ...parsed, status: 'NEEDS_DETAILS', fields: { ...fields, child_ages: null, start_date: null },
      missing_fields: ['child_ages','start_date'], issues: [{ field: 'child_ages', code: 'MISSING_CHILD_AGE', severity: 'clarification', message: 'Give both ages.' }] });
    const user = userEvent.setup(); render(<RequestForm />); await understand(user);
    await user.click(screen.getByRole('button', { name: 'Use Extracted Details' }));
    expect(screen.getByRole('button', { name: 'Find Holidays' }).disabled).toBe(true);
    await user.type(screen.getByLabelText("Children's ages"), '5, 8');
    await user.type(screen.getByLabelText('First day'), '2027-04-10');
    expect(screen.getByRole('button', { name: 'Find Holidays' }).disabled).toBe(false);
    expect(searchPackageOptions).not.toHaveBeenCalled();
  });
  it('does not overwrite existing values or in-flight manual edits even with replace checked', () => {
    setField('budget','200000');
    const result = applyParsedTrip(fields, { ...EMPTY_FORM, budget:'100000' }, parsed, { replaceExisting: true });
    expect(result.skipped).toContain('budget'); expect(bookingStore.getState().form.budget).toBe('200000');
    expect(bookingStore.getState().form.departure).toBe('BLR');
  });
  it('only replaces an unchanged existing field after explicit opt in', () => {
    setField('budget','200000'); const base = { ...bookingStore.getState().form };
    applyParsedTrip(fields, base, parsed); expect(bookingStore.getState().form.budget).toBe('200000');
    applyParsedTrip(fields, { ...bookingStore.getState().form }, parsed, { replaceExisting: true });
    expect(bookingStore.getState().form.budget).toBe('350000');
  });
  it('skips fields that the parser marked unsupported despite a candidate value', () => {
    const bad = { ...parsed, interpretations: { ...parsed.interpretations, start_date: { status: 'UNSUPPORTED' } },
      issues: [{ field: 'start_date', severity:'error', message:'Outside catalog window' }] };
    applyParsedTrip(fields, EMPTY_FORM, bad);
    expect(bookingStore.getState().form.start_date).toBe('');
    expect(searchPackageOptions).not.toHaveBeenCalled();
  });
  it('readiness uses catalog limits, whole ages, valid dates and group capacity', () => {
    const form = { departure:'BLR',country:'Japan',start_date:'2027-04-10',nights:'6',adults:'2',child_ages:'6',budget:'3,50,000' };
    expect(formReadiness(form,meta)).toEqual([]);
    for (const patch of [{ start_date:'2027-04-19' }, { child_ages:'18' }, { nights:'2' }, { budget:'0' }, { adults:'9' }, { start_date:'2027-04-31' }]) {
      expect(formReadiness({ ...form,...patch },meta).length).toBeGreaterThan(0);
    }
  });
});
