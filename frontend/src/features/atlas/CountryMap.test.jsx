import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import CountryMap from './CountryMap';

afterEach(cleanup);

const cities = [
  { city_id: 'Tokyo', name: 'Tokyo' },
  { city_id: 'Kyoto', name: 'Kyoto' },
  { city_id: 'Hidden', name: 'Unmapped City' },
];

describe('CountryMap', () => {
  it('shows real outlines, numbered draft pins, and the text selector', () => {
    const { container } = render(
      <CountryMap
        countryCode="JP"
        countryName="Japan"
        cities={cities}
        currentRoute={[{ city_id: 'Tokyo' }, { city_id: 'Kyoto' }]}
        draftRoute={[{ city_id: 'Kyoto', nights: 2 }]}
        connections={[{ from_city: 'Tokyo', to_city: 'Kyoto' }]}
        onSelectCity={vi.fn()}
      />,
    );

    expect(screen.getByLabelText('Japan outline and city markers')).toBeTruthy();
    expect(document.querySelector('.atlas-country-shape')?.getAttribute('d')).toMatch(/^M/);
    expect(screen.getByRole('button', { name: 'Kyoto, draft stop 1' })).toBeTruthy();
    expect(screen.getByRole('button', { name: /Unmapped City map point unavailable/ })).toBeTruthy();
    expect(screen.getByText('map point unavailable')).toBeTruthy();
    expect(document.querySelectorAll('.atlas-route--current')).toHaveLength(1);
    expect(document.querySelector('.atlas-marker--changed .atlas-marker__label')?.textContent).toBe('Kyoto');
    expect(document.querySelector('.atlas-marker--changed')?.getAttribute('aria-pressed')).toBe('true');
    expect(document.querySelector('.atlas-marker:not(.atlas-marker--selected) .atlas-marker__dot')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Natural Earth' })).toBeTruthy();
    expect(screen.getByRole('link', { name: 'GeoNames (CC BY 4.0)' })).toBeTruthy();
  });

  it('renders only allowed route directions and selects by keyboard or text control', () => {
    const onSelectCity = vi.fn();
    const { container } = render(
      <CountryMap
        countryCode="JP"
        countryName="Japan"
        cities={cities.slice(0, 2)}
        draftRoute={[{ city_id: 'Tokyo' }, { city_id: 'Kyoto' }, { city_id: 'Tokyo' }]}
        connections={[{ from_city: 'Tokyo', to_city: 'Kyoto' }]}
        onSelectCity={onSelectCity}
      />,
    );

    expect(document.querySelectorAll('.atlas-route--draft')).toHaveLength(1);
    const tokyoMarker = container.querySelector('.atlas-marker[aria-label="Tokyo, draft stop 3"]');
    fireEvent.keyDown(tokyoMarker, { key: 'Enter' });
    expect(onSelectCity).toHaveBeenCalledWith('Tokyo');
    fireEvent.click(container.querySelector('.country-map__city-list button:nth-of-type(2)'));
    expect(onSelectCity).toHaveBeenCalledWith('Kyoto');
  });

  it('provides a city selector when a country outline is unavailable', () => {
    render(
      <CountryMap
        countryCode="XX"
        countryName="Unknown"
        cities={[{ city_id: 'Only city', name: 'Only city' }]}
        onSelectCity={() => {}}
      />,
    );
    expect(screen.getByRole('status').textContent).toContain('Map outline unavailable');
    expect(screen.getByRole('button', { name: /Only city map point unavailable/ })).toBeTruthy();
  });

  it('zooms the outline and routes around a focused stop without scaling pin hit targets', () => {
    const { container } = render(
      <CountryMap
        countryCode="JP"
        countryName="Japan"
        cities={[
          { city_id: 'Kyoto', name: 'Kyoto' },
          { city_id: 'Osaka', name: 'Osaka' },
        ]}
        focusedCity="Osaka"
        draftRoute={[{ city_id: 'Kyoto' }, { city_id: 'Osaka' }]}
        connections={[{ from_city: 'Kyoto', to_city: 'Osaka' }]}
        onSelectCity={() => {}}
      />,
    );
    const kyoto = container.querySelector('[aria-label="Kyoto, draft stop 1"]');
    const osaka = container.querySelector('[aria-label="Osaka, draft stop 2"]');
    const startTransform = kyoto.getAttribute('transform');
    const pinPath = kyoto.querySelector('.atlas-marker__pin').getAttribute('d');
    for (let step = 0; step < 7; step += 1) fireEvent.keyDown(container.querySelector('svg'), { key: '+' });
    expect(container.querySelector('.atlas-map-world').getAttribute('transform')).not.toBe('translate(500 310) scale(1) translate(-500 -310)');
    expect(kyoto.getAttribute('transform')).not.toBe(startTransform);
    expect(kyoto.querySelector('.atlas-marker__pin').getAttribute('d')).toBe(pinPath);
    expect(kyoto.querySelector('.atlas-marker__target').getAttribute('stroke-width')).toBe('44');
    const parseCenter = (value) => value.match(/translate\(([-\d.]+) ([-\d.]+)\)/).slice(1).map(Number);
    const [kx, ky] = parseCenter(kyoto.getAttribute('transform'));
    const [ox, oy] = parseCenter(osaka.getAttribute('transform'));
    expect(Math.hypot(kx - ox, ky - oy)).toBeGreaterThan(44);
    fireEvent.keyDown(container.querySelector('svg'), { key: '0' });
    expect(container.querySelector('.atlas-map-world').getAttribute('transform')).toBe('translate(500 310) scale(1) translate(-500 -310)');
  });
  it('uses wheel zoom with no zoom/pan button toolbar and keeps city activation independent', () => {
    const select = vi.fn();
    const { container } = render(<CountryMap countryCode="JP" cities={cities.slice(0, 2)} onSelectCity={select} />);
    expect(screen.queryByRole('button', { name: 'Zoom in' })).toBeNull();
    const svg = container.querySelector('svg');
    const world = container.querySelector('.atlas-map-world');
    const before = world.getAttribute('transform');
    fireEvent.wheel(svg, { deltaY: -160, clientX: 500, clientY: 310 });
    expect(world.getAttribute('transform')).not.toBe(before);
    expect(select).not.toHaveBeenCalled();
    fireEvent.keyDown(svg, { key: '0' });
    expect(world.getAttribute('transform')).toBe(before);
    fireEvent.click(container.querySelector('.atlas-marker'));
    expect(select).toHaveBeenCalledTimes(1);
  });

});
