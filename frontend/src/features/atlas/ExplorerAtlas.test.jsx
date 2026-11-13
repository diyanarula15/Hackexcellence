import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ExplorerAtlas from './ExplorerAtlas.jsx';
import { applyCityPlan, getCityPlanOptions, previewCityPlan } from '../../services/cityPlansApi.js';
vi.mock('../../services/cityPlansApi.js', () => ({ applyCityPlan: vi.fn(), getCityPlanOptions: vi.fn(), previewCityPlan: vi.fn() }));
vi.mock('./CountryMap.jsx', () => ({ default: ({ onSelectCity }) => <button onClick={() => onSelectCity('Osaka')}>Osaka pin</button> }));

const route = [{ city_id: 'Tokyo', nights: 3 }, { city_id: 'Kyoto', nights: 3 }];
const options = { package_id: 'p1', base_version: 1, country: 'Japan', country_code: 'JP', current_city_plan: route,
  cities: ['Tokyo', 'Kyoto', 'Osaka'].map((name) => ({ city_id: name, name })), total_nights: 6, min_nights_per_city: 2,
  connections: ['Tokyo', 'Kyoto', 'Osaka'].flatMap((from_city) => ['Tokyo', 'Kyoto', 'Osaka'].filter((to_city) => from_city !== to_city).map((to_city) => ({ from_city, to_city }))) };
const pkg = { id: 'p1', version: 1, country: 'Japan', nights: 6, total_inr: 200000, budget_inr: 250000, city_plan: route.map((s) => ({ city: s.city_id, nights: s.nights })) };
const proposal = { valid: true, status: 'FOUND', package_id: 'p1', base_version: 1, preview_token: 'real-server-token',
  old_total_inr: 200000, new_total_inr: 210000, price_difference_inr: 10000, warnings: [], violations: [], changed_items: [], automatic_repairs: [],
  proposed_package: { city_plan: [{ city: 'Tokyo', nights: 3 }, { city: 'Osaka', nights: 3 }], items: [], days: [] } };
let onClose, onApplied, onReload;
beforeEach(() => {
  vi.resetAllMocks(); getCityPlanOptions.mockResolvedValue(options); previewCityPlan.mockResolvedValue(proposal);
  onClose = vi.fn(); onApplied = vi.fn(); onReload = vi.fn();
});
afterEach(cleanup);
const mount = () => render(<ExplorerAtlas pkg={pkg} onClose={onClose} onApplied={onApplied} onReload={onReload} />);
async function edit(user) {
  await screen.findByRole('heading', { name: 'Edit Route' });
  await user.click(screen.getByRole('button', { name: 'Osaka pin' }));
  await user.click(screen.getByRole('button', { name: 'Replace Kyoto with Osaka' }));
}

describe('Atlas workflow', () => {
  it('clicking a pin immediately focuses Edit Route without searching or saving', async () => {
    const user = userEvent.setup(); mount();
    await screen.findByRole('heading', { name: 'Edit Route' });
    await user.click(screen.getByRole('button', { name: 'Osaka pin' }));
    expect(screen.getByText('Not in holiday')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Replace Kyoto with Osaka' })).toBeTruthy();
    expect(previewCityPlan).not.toHaveBeenCalled(); expect(applyCityPlan).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Keep Current Trip' })); expect(onClose).toHaveBeenCalledOnce();
  });
  it('previews the exact draft and applies only the server token/response', async () => {
    const user = userEvent.setup(); const updated = { package: { ...pkg, version: 2 } }; applyCityPlan.mockResolvedValue(updated);
    mount(); await edit(user);
    await user.click(screen.getByRole('button', { name: 'Preview New Route' }));
    await screen.findByRole('button', { name: 'Apply New Route' });
    const expected = [{ city_id: 'Tokyo', nights: 3 }, { city_id: 'Osaka', nights: 3 }];
    expect(previewCityPlan).toHaveBeenCalledWith('p1', 1, expected, expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(screen.getByText('₹2,10,000')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Apply New Route' }));
    await waitFor(() => expect(onApplied).toHaveBeenCalledWith(updated));
    expect(applyCityPlan).toHaveBeenCalledWith('p1', 1, expected, 'real-server-token');
  });
  it('clears an accepted preview when the local route changes', async () => {
    const user = userEvent.setup(); mount(); await edit(user);
    await user.click(screen.getByRole('button', { name: 'Preview New Route' }));
    await screen.findByRole('button', { name: 'Apply New Route' });
    await user.click(screen.getByRole('button', { name: 'Increase nights in Tokyo' }));
    expect(screen.queryByRole('button', { name: 'Apply New Route' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Preview New Route' }).disabled).toBe(true);
  });
  it('requires explicit acknowledgment of a real over-budget total', async () => {
    previewCityPlan.mockResolvedValue({ ...proposal, status: 'OVER_BUDGET', over_budget_inr: 10000 });
    const user = userEvent.setup(); mount(); await edit(user);
    await user.click(screen.getByRole('button', { name: 'Preview New Route' }));
    const apply = await screen.findByRole('button', { name: 'Apply New Route' }); expect(apply.disabled).toBe(true);
    await user.click(screen.getByRole('checkbox')); expect(apply.disabled).toBe(false);
  });
  it('keeps incomplete proposals unsaved with no apply action', async () => {
    previewCityPlan.mockResolvedValue({ ...proposal, valid: false, status: 'SEARCH_INCOMPLETE', proposed_package: null, preview_token: null, new_total_inr: null, price_difference_inr: null });
    const user = userEvent.setup(); mount(); await edit(user); await user.click(screen.getByRole('button', { name: 'Preview New Route' }));
    await screen.findByText('SEARCH_INCOMPLETE'); expect(screen.queryByRole('button', { name: 'Apply New Route' })).toBeNull();
    expect(applyCityPlan).not.toHaveBeenCalled();
  });
  it('rejects stale initial options and asks for the latest saved holiday', async () => {
    getCityPlanOptions.mockResolvedValue({ ...options, base_version: 2 });
    const user = userEvent.setup(); mount();
    await user.click(await screen.findByRole('button', { name: 'Reload latest holiday' }));
    expect(onReload).toHaveBeenCalledOnce(); expect(previewCityPlan).not.toHaveBeenCalled();
  });
  it('disables duplicate submissions and ignores a canceled late preview', async () => {
    let resolve; previewCityPlan.mockImplementation(() => new Promise((r) => { resolve = r; }));
    const user = userEvent.setup(); const view = mount(); await edit(user);
    const btn = screen.getByRole('button', { name: 'Preview New Route' });
    btn.click(); btn.click();
    await waitFor(() => expect(previewCityPlan).toHaveBeenCalledTimes(1));
    view.unmount(); resolve(proposal);
    await Promise.resolve(); expect(onApplied).not.toHaveBeenCalled(); expect(applyCityPlan).not.toHaveBeenCalled();
  });
  it('sends one apply request even for two immediate activations', async () => {
    let finish; applyCityPlan.mockImplementation(() => new Promise((r) => { finish = r; }));
    const user = userEvent.setup(); mount(); await edit(user);
    await user.click(screen.getByRole('button', { name: 'Preview New Route' }));
    const button = await screen.findByRole('button', { name: 'Apply New Route' });
    button.click(); button.click();
    await waitFor(() => expect(applyCityPlan).toHaveBeenCalledTimes(1));
    const updated = { package: { ...pkg, version: 2 } }; finish(updated);
    await waitFor(() => expect(onApplied).toHaveBeenCalledOnce());
  });
  it('discards a stale accepted preview and requires a package reload', async () => {
    applyCityPlan.mockRejectedValue(Object.assign(new Error('Your holiday changed.'), { body: { error: 'PACKAGE_VERSION_CONFLICT' } }));
    const user = userEvent.setup(); mount(); await edit(user);
    await user.click(screen.getByRole('button', { name: 'Preview New Route' }));
    await user.click(await screen.findByRole('button', { name: 'Apply New Route' }));
    await user.click(await screen.findByRole('button', { name: 'Reload latest holiday' }));
    expect(screen.queryByRole('button', { name: 'Apply New Route' })).toBeNull();
    expect(onReload).toHaveBeenCalledOnce(); expect(onApplied).not.toHaveBeenCalled();
  });
});
