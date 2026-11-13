/**
 * Saved trips UI: the "My saved trips" list actions and the "Save trip" control.
 * The API and the booking store are mocked; these tests check what the components ask for.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

vi.mock('../../services/savedTripsApi.js', () => ({
  listSavedTrips: vi.fn(),
  saveTrip: vi.fn(),
  renameSavedTrip: vi.fn(),
  removeSavedTrip: vi.fn(),
}));

vi.mock('../../state/bookingStore.js', () => ({
  openPackage: vi.fn(),
}));

import * as api from '../../services/savedTripsApi.js';
import { openPackage } from '../../state/bookingStore.js';
import SavedTrips from './SavedTrips.jsx';
import SaveTripButton from './SaveTripButton.jsx';

const TOKYO = {
  package_id: 'pkg-tokyo',
  name: 'Cherry blossom run',
  country: 'Japan',
  start_date: '2027-04-10',
  end_date: '2027-04-16',
  nights: 6,
  travelers: { adults: 2, child_ages: [6] },
  cities: ['Tokyo', 'Osaka'],
  total_inr: 233632,
  status: 'PLANNED',
  booking_reference: null,
  version: 1,
  saved_at: '2026-11-10T09:00:00+00:00',
  updated_at: '2026-11-10T09:00:00+00:00',
};

const PARIS = {
  ...TOKYO,
  package_id: 'pkg-paris',
  name: 'Paris in May',
  country: 'France',
  start_date: '2027-05-02',
  end_date: '2027-05-06',
  nights: 4,
  travelers: { adults: 1, child_ages: [] },
  cities: ['Paris'],
  total_inr: 180000,
  status: 'BOOKED',
  booking_reference: '4826173950',
  updated_at: '2026-11-12T09:00:00+00:00',
};

const PLANNED_PKG = {
  id: 'pkg-tokyo',
  status: 'PLANNED',
  country: 'Japan',
  start_date: '2027-04-10',
  end_date: '2027-04-16',
};

beforeEach(() => {
  vi.clearAllMocks();
  api.listSavedTrips.mockResolvedValue([TOKYO, PARIS]);
});

afterEach(cleanup);

describe('SavedTrips list', () => {
  it('lists two saved trips with their facts', async () => {
    render(<SavedTrips onClose={() => {}} />);
    expect(await screen.findByRole('heading', { name: 'Cherry blossom run' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Paris in May' })).toBeTruthy();
    expect(screen.getByText('Tokyo → Osaka')).toBeTruthy();
    expect(screen.getByText('Booked · 4826173950')).toBeTruthy();
  });

  it('Open reopens that holiday and closes the list', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<SavedTrips onClose={onClose} />);
    const card = (await screen.findByRole('heading', { name: 'Cherry blossom run' })).closest('li');
    await user.click(within(card).getByRole('button', { name: 'Open' }));
    expect(openPackage).toHaveBeenCalledWith('pkg-tokyo');
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('Rename sends the new name for that trip', async () => {
    const user = userEvent.setup();
    api.renameSavedTrip.mockResolvedValue({ ...TOKYO, name: 'Spring in Japan' });
    render(<SavedTrips onClose={() => {}} />);
    const card = (await screen.findByRole('heading', { name: 'Cherry blossom run' })).closest('li');
    await user.click(within(card).getByRole('button', { name: 'Rename' }));
    const input = within(card).getByLabelText('Rename trip');
    await user.clear(input);
    await user.type(input, '  Spring in Japan  ');
    await user.click(within(card).getByRole('button', { name: 'Save name' }));
    await waitFor(() => expect(api.renameSavedTrip).toHaveBeenCalledWith('pkg-tokyo', 'Spring in Japan'));
    expect(await screen.findByRole('heading', { name: 'Spring in Japan' })).toBeTruthy();
  });

  it('Rename shows a validation error and does not call the API for a blank name', async () => {
    const user = userEvent.setup();
    render(<SavedTrips onClose={() => {}} />);
    const card = (await screen.findByRole('heading', { name: 'Cherry blossom run' })).closest('li');
    await user.click(within(card).getByRole('button', { name: 'Rename' }));
    await user.clear(within(card).getByLabelText('Rename trip'));
    await user.click(within(card).getByRole('button', { name: 'Save name' }));
    expect((within(card).getByRole('alert')).textContent).toContain('Enter a name for this trip.');
    expect(api.renameSavedTrip).not.toHaveBeenCalled();
  });

  it('Remove asks first, then removes only the bookmark', async () => {
    const user = userEvent.setup();
    api.removeSavedTrip.mockResolvedValue(undefined);
    render(<SavedTrips onClose={() => {}} />);
    const card = (await screen.findByRole('heading', { name: 'Cherry blossom run' })).closest('li');
    await user.click(within(card).getByRole('button', { name: 'Remove from saved' }));
    expect(within(card).getByText('Remove from saved trips? The holiday itself is kept.')).toBeTruthy();
    expect(api.removeSavedTrip).not.toHaveBeenCalled();
    await user.click(within(card).getByRole('button', { name: 'Remove from saved' }));
    await waitFor(() => expect(api.removeSavedTrip).toHaveBeenCalledWith('pkg-tokyo'));
    await waitFor(() => expect(screen.queryByRole('heading', { name: 'Cherry blossom run' })).toBeNull());
  });

  it('shows an empty state explaining how to save', async () => {
    api.listSavedTrips.mockResolvedValue([]);
    render(<SavedTrips onClose={() => {}} />);
    expect(await screen.findByText('No saved trips yet.')).toBeTruthy();
    expect(screen.getByText(/Save trip/)).toBeTruthy();
  });

  it('shows an error with a retry that loads again', async () => {
    const user = userEvent.setup();
    api.listSavedTrips
      .mockRejectedValueOnce(new Error('Cannot reach the holiday server.'))
      .mockResolvedValueOnce([TOKYO]);
    render(<SavedTrips onClose={() => {}} />);
    expect((await screen.findByRole('alert')).textContent).toContain('Cannot reach the holiday server.');
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('heading', { name: 'Cherry blossom run' })).toBeTruthy();
  });
});

describe('SaveTripButton', () => {
  it('saves under the edited name and then shows the saved state', async () => {
    const user = userEvent.setup();
    api.listSavedTrips.mockResolvedValue([]);
    api.saveTrip.mockResolvedValue({ ...TOKYO, name: 'My trip' });
    render(<SaveTripButton pkg={PLANNED_PKG} onViewSaved={() => {}} />);

    await user.click(screen.getByRole('button', { name: 'Save trip' }));
    const input = screen.getByLabelText('Name this trip');
    expect(input.value).toBe('Japan · 10 Apr–16 Apr 2027');
    await user.clear(input);
    await user.type(input, 'My trip');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(api.saveTrip).toHaveBeenCalledWith('pkg-tokyo', 'My trip'));
    expect((await screen.findByRole('status')).textContent).toContain('Saved as “My trip”');
    expect(screen.getByRole('button', { name: 'View saved trips' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Rename' })).toBeTruthy();
  });

  it('renders nothing for a booked package', () => {
    const { container } = render(<SaveTripButton pkg={{ ...PLANNED_PKG, status: 'BOOKED' }} />);
    expect(container.innerHTML).toBe("");
    expect(api.listSavedTrips).not.toHaveBeenCalled();
  });
});
