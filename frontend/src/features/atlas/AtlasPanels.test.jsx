import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

vi.mock('./routeDraft.js', () => ({
  routeErrors: vi.fn(() => ['Route nights must equal the holiday length.']),
  routeActions: vi.fn(() => [
    { id: 'add-osaka', label: 'Add Osaka', route: [{ city_id: 'Tokyo', nights: 2 }, { city_id: 'Osaka', nights: 3 }] },
    { id: 'blocked', label: 'Remove Tokyo', route: null, reason: 'At least one city is required.' },
  ]),
}));

import EditRoute from './EditRoute.jsx';
import RouteComparison from './RouteComparison.jsx';

afterEach(cleanup);

const options = {
  cities: [{ city_id: 'Tokyo', name: 'Tokyo' }, { city_id: 'Osaka', name: 'Osaka' }],
  min_nights_per_city: 1,
  total_nights: 5,
  current_city_plan: [{ city_id: 'Tokyo', nights: 5 }],
};

describe('Atlas route panels', () => {
  it('shows focused stop, night controls, errors and supplied route actions', async () => {
    const user = userEvent.setup();
    const onDraftChange = vi.fn();
    const draft = [{ city_id: 'Tokyo', nights: 5 }];
    render(<EditRoute options={options} draft={draft} focusedCity="Tokyo" onFocusCity={vi.fn()} onDraftChange={onDraftChange} />);

    expect(screen.getByRole('heading', { name: 'Edit Route' })).toBeTruthy();
    expect(screen.getByText('Current stop · 5 nights')).toBeTruthy();
    expect(screen.getByText('Total nights')).toBeTruthy();
    expect(screen.getByText('Route nights must equal the holiday length.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Remove Tokyo' }).disabled).toBe(true);
    await user.click(screen.getByRole('button', { name: 'Increase nights in Tokyo' }));
    expect(onDraftChange).toHaveBeenCalledWith([{ city_id: 'Tokyo', nights: 6 }]);
  });

  it('renders real proposal totals, package item prices and changed item disclosure', () => {
    const preview = {
      status: 'VALID', valid: true,
      old_total_inr: 10000, new_total_inr: 12500, price_difference_inr: 2500,
      budget_inr: 20000, over_budget_inr: 0,
      city_changes: { added: ['Osaka'], removed: [], reordered: false, nights_changed: [] },
      changed_items: [{ item_id: 'stay:Osaka:2027-01-01:2027-01-03', type: 'hotel', label: 'Hotel in Osaka', action: 'REPLACED', reason: 'Route changed', price_difference_inr: 2500, before: { name: 'Tokyo Inn' }, after: { name: 'Osaka Stay' } }],
      automatic_repairs: [], preserved_items: [{ item_id: 'flight:arrival', type: 'flight', name: 'Arrival flight' }],
      warnings: ['One connection is tight.'], violations: [],
      proposed_package: { city_plan: [{ city: 'Tokyo', nights: 3 }, { city: 'Osaka', nights: 2 }], items: [{ item_id: 'flight:arrival', type: 'flight', name: 'Flight', price_inr: 8000 }] },
    };
    const currentPackage = { city_plan: [{ city: 'Tokyo', nights: 5 }], items: [{ item_id: 'flight:arrival', type: 'flight', name: 'Flight', price_inr: 8000 }] };
    render(<RouteComparison preview={preview} currentPackage={currentPackage} />);

    expect(screen.getByText('₹10,000')).toBeTruthy();
    expect(screen.getAllByText('+₹2,500')).toHaveLength(2);
    expect(document.querySelector('.atlas-comparison__item-detail').textContent).toContain('Tokyo Inn');
    expect(document.querySelector('.atlas-comparison__item-detail').textContent).toContain('Osaka Stay');
    expect(screen.getByText('One connection is tight.')).toBeTruthy();
    const proposed = screen.getByRole('region', { name: 'Proposed package items' });
    expect(within(proposed).getByText('₹8,000')).toBeTruthy();
  });

  it('says Added for a new item instead of "None →"', () => {
    const added = { item_id: 'leg:1', type: 'transfer', label: 'Transfer Tokyo → Osaka', action: 'ADDED', before: null,
      after: { name: 'Shinkansen Tokyo to Osaka', start: '2027-04-14T10:00', end: '2027-04-14T12:30' } };
    render(<RouteComparison preview={{ valid: true, status: 'OVER_BUDGET', changed_items: [added], proposed_package: null }} currentPackage={null} />);
    const row = document.querySelector('.atlas-comparison__item-list li');
    expect(row.textContent).toContain('Added: Shinkansen Tokyo to Osaka');
    expect(row.textContent).not.toContain('None');
    expect(screen.getByText('Over budget')).toBeTruthy();
  });

  it('does not fabricate totals for an incomplete proposal', () => {
    render(<RouteComparison preview={{ status: 'INCOMPLETE', valid: false, proposed_package: null }} currentPackage={null} />);
    expect(screen.getByText('A complete price is not available for this proposal.')).toBeTruthy();
    expect(screen.queryByText(/₹/)).toBeNull();
  });

  it('shows hotel room and checkout details and flight time shifts, with repairs shown once', () => {
    const flightChange = {
      item_id: 'flight:arrival', type: 'flight', label: 'Arrival flight', action: 'REPLACED', source: 'AUTOMATIC_REPAIR',
      before: { name: 'AB 101', start: '2027-04-10T08:30', end: '2027-04-10T10:00' },
      after: { name: 'AB 205', start: '2027-04-10T09:15', end: '2027-04-10T10:45' },
    };
    const hotelChange = {
      item_id: 'stay:Tokyo', type: 'hotel', label: 'Hotel in Tokyo', action: 'REPLACED',
      before: { name: 'Old Hotel', room_name: 'Single', rooms: 1, start: '2027-04-10', end: '2027-04-12' },
      after: { name: 'New Hotel', room_name: 'Twin', rooms: 2, room_id: 'ROOM-TWIN', start: '2027-04-10', end: '2027-04-13' },
    };
    render(<RouteComparison preview={{
      valid: true, status: 'VALID', old_total_inr: 1000, new_total_inr: 1200,
      changed_items: [flightChange, hotelChange], automatic_repairs: [flightChange], proposed_package: null,
    }} currentPackage={null} />);

    const rows = [...document.querySelectorAll('.atlas-comparison__item-list li')];
    const flightRow = rows.find((row) => row.textContent.includes('Arrival flight'));
    const hotelRow = rows.find((row) => row.textContent.includes('Hotel in Tokyo'));
    expect(flightRow.textContent).toContain('08:30');
    expect(flightRow.textContent).toContain('10:45');
    expect(flightRow.textContent).toContain('Automatic repair');
    expect(hotelRow.textContent).toContain('Single × 1');
    expect(hotelRow.textContent).toContain('Twin (ROOM-TWIN) × 2');
    expect(hotelRow.textContent).toContain('ROOM-TWIN');
    expect(hotelRow.textContent).toContain('13 Apr');
    expect(rows.filter((row) => row.textContent.includes('Arrival flight'))).toHaveLength(1);
    expect(document.querySelector('.atlas-comparison__item-list').textContent).not.toContain('None');
    expect(screen.getByText('Fits your budget')).toBeTruthy();
    expect(screen.queryByRole('heading', { name: 'Automatic repairs' })).toBeNull();
  });
});
