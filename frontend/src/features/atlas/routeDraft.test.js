import { describe, expect, it } from 'vitest';
import { routeActions, routeErrors } from './routeDraft.js';

const options = {
  cities: ['Tokyo', 'Kyoto', 'Osaka'].map((name) => ({ city_id: name, name })),
  connections: [{ from_city: 'Tokyo', to_city: 'Kyoto' }, { from_city: 'Tokyo', to_city: 'Osaka' }, { from_city: 'Osaka', to_city: 'Kyoto' }],
  min_nights_per_city: 2, total_nights: 6,
};
const route = [{ city_id: 'Tokyo', nights: 3 }, { city_id: 'Kyoto', nights: 3 }];

describe('Atlas local route structure', () => {
  it('honors directed links rather than geographic proximity', () => {
    expect(routeErrors(route, options)).toEqual([]);
    expect(routeErrors([...route].reverse(), options).join(' ')).toContain('No catalog connection');
  });
  it('rejects duplicates, wrong country, missing/minimum nights and totals', () => {
    for (const draft of [[], [{ city_id: 'Hanoi', nights: 6 }], [{ city_id: 'Tokyo', nights: 1 }, { city_id: 'Kyoto', nights: 5 }],
      [{ city_id: 'Tokyo', nights: 3 }, { city_id: 'Tokyo', nights: 3 }], [{ city_id: 'Tokyo', nights: 5 }]]) {
      expect(routeErrors(draft, options).length).toBeGreaterThan(0);
    }
  });
  it('offers add only at connected positions and redistributes surplus nights', () => {
    const before = JSON.stringify(route);
    const actions = routeActions(route, 'Osaka', options);
    const add = actions.find((a) => a.id === 'add-1');
    expect(add.route).toEqual([{ city_id: 'Tokyo', nights: 2 }, { city_id: 'Osaka', nights: 2 }, { city_id: 'Kyoto', nights: 2 }]);
    expect(actions.find((a) => a.id === 'add-0').route).toBeNull();
    expect(JSON.stringify(route)).toBe(before);
  });
  it('blocks additions when the minimum allocation will not fit', () => {
    const actions = routeActions(route, 'Osaka', { ...options, total_nights: 4 });
    expect(actions.find((a) => a.id === 'add').route).toBeNull();
    expect(actions.find((a) => a.id === 'add').reason).toContain('at least 6 nights');
  });
  it('replacement preserves allocation and rejects unsupported direction', () => {
    const actions = routeActions(route, 'Osaka', options);
    expect(actions.find((a) => a.id === 'replace-1').route).toEqual([{ city_id: 'Tokyo', nights: 3 }, { city_id: 'Osaka', nights: 3 }]);
    expect(actions.find((a) => a.id === 'replace-0').route).toEqual([{ city_id: 'Osaka', nights: 3 }, { city_id: 'Kyoto', nights: 3 }]);
  });
  it('removal reallocates nights and cannot remove the final city', () => {
    expect(routeActions(route, 'Kyoto', options).find((a) => a.id === 'remove').route).toEqual([{ city_id: 'Tokyo', nights: 6 }]);
    const single = [{ city_id: 'Tokyo', nights: 6 }];
    expect(routeActions(single, 'Tokyo', options).find((a) => a.id === 'remove').route).toBeNull();
  });
  it('reorders only when the full new directed sequence remains connected', () => {
    expect(routeActions(route, 'Kyoto', options).find((a) => a.id === 'move--1').route).toBeNull();
    const reverse = { ...options, connections: [...options.connections, { from_city: 'Kyoto', to_city: 'Tokyo' }] };
    expect(routeActions(route, 'Kyoto', reverse).find((a) => a.id === 'move--1').route).toEqual([...route].reverse());
  });
});
