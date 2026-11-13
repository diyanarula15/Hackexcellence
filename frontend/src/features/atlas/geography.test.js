import { describe, expect, it } from 'vitest';
import countries from './data/countries.json';
import { createProjection, geometryPath, mercator, permittedRouteSegments, projectIntoView } from './geography';

describe('atlas geography', () => {
  it('keeps only the seven requested Natural Earth country outlines', () => {
    expect(countries.features.map(({ id }) => String(id)).sort()).toEqual(
      ['360', '392', '458', '702', '704', '764', '784'].sort(),
    );
  });

  it('projects geographic positions into the same fitted outline coordinate space', () => {
    const geometry = countries.features.find(({ id }) => String(id) === '392').geometry;
    const project = createProjection(geometry, 1000, 620);
    const point = project([139.69171, 35.6895]);
    const path = geometryPath(geometry, project);
    expect(point.every(Number.isFinite)).toBe(true);
    expect(point[0]).toBeGreaterThanOrEqual(0);
    expect(point[0]).toBeLessThanOrEqual(1000);
    expect(path.startsWith('M')).toBe(true);
    expect(path).toContain(' Z');
    const origin = mercator([0, 0]);
    expect(origin[0]).toBe(0);
    expect(Math.abs(origin[1])).toBeLessThan(1e-12);
  });

  it('keeps only directed route legs that are explicitly permitted', () => {
    const route = [{ city_id: 'Tokyo' }, { city_id: 'Kyoto' }, { city_id: 'Osaka' }];
    const connections = [
      { from_city: 'Tokyo', to_city: 'Kyoto' },
      { from_city: 'Osaka', to_city: 'Kyoto' },
    ];
    expect(permittedRouteSegments(route, connections)).toEqual([
      { from_city: 'Tokyo', to_city: 'Kyoto' },
    ]);
  });

  it('reprojects anchors around a zoom center while retaining a shared map transform', () => {
    const source = [520, 324];
    expect(projectIntoView(source, [500, 310], 1)).toEqual([520, 324]);
    expect(projectIntoView(source, [520, 324], 4)).toEqual([500, 310]);
    const nearCity = projectIntoView([515, 332], [520, 324], 12);
    expect(Math.hypot(nearCity[0] - 500, nearCity[1] - 310)).toBeGreaterThan(80);
  });
});
