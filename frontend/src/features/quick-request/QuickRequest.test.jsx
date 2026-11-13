import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';

const { parseQuickRequest } = vi.hoisted(() => ({ parseQuickRequest: vi.fn() }));
vi.mock('../../services/quickRequestApi.js', () => ({ parseQuickRequest }));

import QuickRequest from './QuickRequest.jsx';

const BASE_FORM = {
  departure: 'DEL', country: 'France', start_date: '', nights: '', adults: '1', child_ages: '', budget: '',
};
const READY = {
  status: 'READY',
  fields: { departure: 'BLR', country: 'Japan', start_date: '2027-04-10', nights: 6, adults: 2, child_ages: [6], budget: 300000 },
  missing_fields: [], issues: [], assumptions: [], can_search: true,
  interpretations: Object.fromEntries(['departure', 'country', 'start_date', 'nights', 'adults', 'child_ages', 'budget']
    .map((field) => [field, { value: null, status: 'EXPLICIT', source_text: 'from Bengaluru', spans: [] }])),
};

function openAndType(value = 'A week in Japan for two adults') {
  fireEvent.click(screen.getByRole('button', { name: /describe your trip/i }));
  fireEvent.change(screen.getByLabelText(/what do you have in mind/i), { target: { value } });
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

beforeEach(() => parseQuickRequest.mockReset());
afterEach(cleanup);

describe('QuickRequest', () => {
  it('reviews extracted values and applies only after the explicit action', async () => {
    const onApply = vi.fn((fields) => ({ applied: Object.keys(fields), skipped: [] }));
    parseQuickRequest.mockResolvedValue(READY);
    render(<QuickRequest form={BASE_FORM} onApply={onApply} />);
    openAndType();
    fireEvent.click(screen.getByRole('button', { name: 'Understand My Trip' }));

    expect(await screen.findByText('Review the details')).toBeTruthy();
    expect(screen.getByText('10 Apr 2027')).toBeTruthy();
    expect(onApply).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Use Extracted Details' }));
    expect(onApply).toHaveBeenCalledWith(READY.fields, BASE_FORM, READY, { replaceExisting: false });
    expect(screen.getByRole('status').textContent).toMatch(/Details added to the form/);
  });

  it('shows missing fields and excludes ambiguous or invalid values from apply', async () => {
    const result = {
      ...READY,
      status: 'NEEDS_DETAILS',
      missing_fields: ['start_date', 'budget'],
      fields: { ...READY.fields, start_date: null, budget: 250000, country: 'Japan' },
      interpretations: { ...READY.interpretations, country: { status: 'AMBIGUOUS', source_text: 'Japan or Korea' } },
      issues: [{ field: 'country', code: 'COUNTRY_AMBIGUOUS', severity: 'clarification', message: 'Which destination?', candidates: ['Japan', 'Korea'] }],
    };
    const onApply = vi.fn();
    parseQuickRequest.mockResolvedValue(result);
    render(<QuickRequest form={{ ...BASE_FORM, country: '' }} onApply={onApply} />);
    openAndType();
    fireEvent.click(screen.getByRole('button', { name: 'Understand My Trip' }));
    expect(await screen.findByText(/Still needed:/)).toBeTruthy();
    expect(screen.getByText('Which destination? Options: Japan, Korea.')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Use Extracted Details' }));
    const appliedFields = onApply.mock.calls[0][0];
    expect(appliedFields).not.toHaveProperty('country');
    expect(appliedFields).not.toHaveProperty('start_date');
    expect(appliedFields).toHaveProperty('budget', 250000);
  });

  it('preserves the form snapshot from parse start when fields change while pending', async () => {
    const pending = deferred();
    const onApply = vi.fn();
    parseQuickRequest.mockReturnValue(pending.promise);
    const view = render(<QuickRequest form={BASE_FORM} onApply={onApply} />);
    openAndType();
    fireEvent.click(screen.getByRole('button', { name: 'Understand My Trip' }));
    const edited = { ...BASE_FORM, departure: 'BOM', adults: '3' };
    view.rerender(<QuickRequest form={edited} onApply={onApply} />);
    await act(async () => pending.resolve(READY));
    fireEvent.click(await screen.findByRole('button', { name: 'Use Extracted Details' }));
    expect(onApply.mock.calls[0][1]).toEqual(BASE_FORM);
  });

  it('guards duplicate requests, retries errors, and ignores a response after the text changes', async () => {
    const pending = deferred();
    parseQuickRequest.mockReturnValueOnce(pending.promise).mockRejectedValueOnce(new Error('Server unavailable'))
      .mockResolvedValueOnce(READY);
    render(<QuickRequest form={BASE_FORM} onApply={vi.fn()} />);
    openAndType();
    const read = screen.getByRole('button', { name: 'Understand My Trip' });
    fireEvent.click(read);
    fireEvent.click(read);
    expect(parseQuickRequest).toHaveBeenCalledTimes(1);
    fireEvent.change(screen.getByLabelText(/what do you have in mind/i), { target: { value: 'Different trip' } });
    await act(async () => pending.resolve(READY));
    expect(screen.queryByText('Review the details')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Understand My Trip' }));
    expect((await screen.findByRole('alert')).textContent).toContain('Server unavailable');
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByText('Review the details')).toBeTruthy();
    expect(parseQuickRequest).toHaveBeenCalledTimes(3);
  });
});
