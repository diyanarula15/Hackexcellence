import { useEffect, useMemo, useRef, useState } from 'react';
import countries from './data/countries.json';
import { cityAnchors } from './data/cityAnchors';
import { createProjection, geometryPath, permittedRouteSegments, projectIntoView } from './geography';
import './CountryMap.css';

const VIEW_WIDTH = 1000;
const VIEW_HEIGHT = 620;
const COUNTRY_IDS = { JP: '392', AE: '784', TH: '764', SG: '702', MY: '458', ID: '360', VN: '704' };

function connectorPath(from, to) {
  const dx = to[0] - from[0];
  const dy = to[1] - from[1];
  const length = Math.max(Math.hypot(dx, dy), 1);
  const bend = Math.min(30, length * 0.12);
  const controlX = (from[0] + to[0]) / 2 - (dy / length) * bend;
  const controlY = (from[1] + to[1]) / 2 + (dx / length) * bend;
  return `M${from[0].toFixed(2)},${from[1].toFixed(2)} Q${controlX.toFixed(2)},${controlY.toFixed(2)} ${to[0].toFixed(2)},${to[1].toFixed(2)}`;
}

function pinPath() {
  return 'M0 0 C-3 -5 -16 -18 -16 -27 C-16 -36 -9 -43 0 -43 C9 -43 16 -36 16 -27 C16 -18 3 -5 0 0 Z';
}

export default function CountryMap({
  countryCode,
  countryName,
  cities = [],
  currentRoute = [],
  draftRoute = [],
  focusedCity,
  onSelectCity,
  connections = [],
}) {
  const country = countries.features.find((feature) => String(feature.id) === COUNTRY_IDS[countryCode]);
  const anchorMap = cityAnchors[countryCode] || {};
  const projection = useMemo(
    () => country && createProjection(country.geometry, VIEW_WIDTH, VIEW_HEIGHT),
    [country],
  );
  const cityPoints = useMemo(() => new Map(cities.map((city) => {
    const anchor = anchorMap[city.name];
    return [city.city_id, anchor && projection ? projection(anchor.coordinates) : null];
  })), [cities, anchorMap, projection]);
  const draftOrder = new Map(draftRoute.map(({ city_id }, index) => [city_id, index + 1]));
  const draftChanges = new Map(draftRoute.map((stop, index) => {
    const previousIndex = currentRoute.findIndex((currentStop) => currentStop.city_id === stop.city_id);
    if (previousIndex < 0) return [stop.city_id, 'added'];
    const previous = currentRoute[previousIndex];
    const nightsChanged = stop.nights != null && previous.nights != null && stop.nights !== previous.nights;
    return [stop.city_id, previousIndex !== index || nightsChanged ? 'changed' : 'persisted'];
  }));
  const currentSegments = permittedRouteSegments(currentRoute, connections);
  const draftSegments = permittedRouteSegments(draftRoute, connections);
  const [view, setView] = useState({ zoom: 1, center: [VIEW_WIDTH / 2, VIEW_HEIGHT / 2] });
  const { zoom, center } = view;
  const viewRef = useRef(view);
  const dragRef = useRef(null);
  const pointers = useRef(new Map());
  const wheelRef = useRef(null);
  const [dragging, setDragging] = useState(false);
  const [viewScale, setViewScale] = useState(1);
  const svgRef = useRef(null);
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return undefined;
    const measure = () => {
      const { width, height } = svg.getBoundingClientRect();
      if (width > 0 && height > 0) setViewScale(Math.min(width / VIEW_WIDTH, height / VIEW_HEIGHT));
    };
    measure();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(svg);
    return () => observer.disconnect();
  }, [country]);
  const markerId = `atlas-arrow-${countryCode || 'unknown'}`;
  const countryPath = useMemo(() => country && projection ? geometryPath(country.geometry, projection) : '', [country, projection]);
  const routePoints = draftRoute.map(({ city_id }) => cityPoints.get(city_id)).filter(Boolean);
  const routeCenter = routePoints.length
    ? [routePoints.reduce((sum, [x]) => sum + x, 0) / routePoints.length, routePoints.reduce((sum, [, y]) => sum + y, 0) / routePoints.length]
    : [VIEW_WIDTH / 2, VIEW_HEIGHT / 2];
  const zoomFocus = cityPoints.get(focusedCity) || routeCenter;
  const mapTransform = `translate(${VIEW_WIDTH / 2} ${VIEW_HEIGHT / 2}) scale(${zoom}) translate(${-center[0]} ${-center[1]})`;
  const mapPoint = (point) => projectIntoView(point, center, zoom, VIEW_WIDTH, VIEW_HEIGHT);
  const updateView = (next) => { viewRef.current = next; setView(next); };
  const zoomAt = (nextZoom, anchor, start = viewRef.current) => {
    const z = Math.max(1, Math.min(24, nextZoom));
    // Keep the geographic point under the cursor stationary while changing magnification.
    const point = [start.center[0] + (anchor[0] - 500) / start.zoom, start.center[1] + (anchor[1] - 310) / start.zoom];
    updateView({ zoom: z, center: [point[0] - (anchor[0] - 500) / z, point[1] - (anchor[1] - 310) / z] });
  };
  const screenPoint = (event) => {
    const svg = svgRef.current;
    const matrix = svg?.getScreenCTM?.();
    if (matrix && typeof DOMPoint !== 'undefined') {
      const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse());
      return [point.x, point.y];
    }
    const rect = svg?.getBoundingClientRect() ?? { left: 0, top: 0, width: 1000, height: 620 };
    const scale = Math.min((rect.width || 1000) / 1000, (rect.height || 620) / 620);
    return [(event.clientX - rect.left - ((rect.width || 1000) - 1000 * scale) / 2) / scale,
      (event.clientY - rect.top - ((rect.height || 620) - 620 * scale) / 2) / scale];
  };
  const selectMarker = (event, cityId) => {
    // Nearby cities can share a touch target. Choose the nearest pin when an invisible target
    // receives the click; painted pins and labels still select the city the traveler can see.
    if (event.target.classList?.contains('atlas-marker__target')) {
      const [px, py] = screenPoint(event);
      const markerScale = 30 / (43 * Math.max(viewScale, 0.1));
      let nearest = Infinity;
      for (const city of cities) {
        const source = cityPoints.get(city.city_id);
        if (!source) continue;
        const [x, y] = mapPoint(source);
        const distance = Math.hypot(px - x, py - (y - 22 * markerScale));
        if (distance < nearest) { nearest = distance; cityId = city.city_id; }
      }
    }
    onSelectCity?.(cityId);
  };
  wheelRef.current = (event) => {
    event.preventDefault();
    const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? 300 : 1);
    zoomAt(viewRef.current.zoom * Math.exp(-Math.max(-400, Math.min(400, delta)) * 0.003), screenPoint(event));
  };
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return undefined;
    const wheel = (event) => wheelRef.current(event);
    svg.addEventListener('wheel', wheel, { passive: false });
    return () => svg.removeEventListener('wheel', wheel);
  }, [country]);
  const resetView = () => updateView({ zoom: 1, center: [500, 310] });
  const pointerDown = (event) => {
    if (event.target.closest?.('.atlas-marker') || (event.pointerType !== 'touch' && event.button !== 0)) return;
    event.preventDefault();
    svgRef.current?.focus();
    pointers.current.set(event.pointerId, screenPoint(event));
    svgRef.current?.setPointerCapture?.(event.pointerId);
    const positions = [...pointers.current.values()];
    dragRef.current = positions.length === 2
      ? { mode: 'pinch', start: viewRef.current, distance: Math.hypot(positions[0][0] - positions[1][0], positions[0][1] - positions[1][1]), anchor: [(positions[0][0] + positions[1][0]) / 2, (positions[0][1] + positions[1][1]) / 2] }
      : { mode: event.shiftKey ? 'pan' : 'zoom', start: viewRef.current, anchor: positions[0], clientY: event.clientY };
    setDragging(true);
  };
  const pointerMove = (event) => {
    if (!pointers.current.has(event.pointerId) || !dragRef.current) return;
    pointers.current.set(event.pointerId, screenPoint(event));
    const drag = dragRef.current;
    if (drag.mode === 'pinch' && pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()];
      zoomAt(drag.start.zoom * Math.hypot(a[0] - b[0], a[1] - b[1]) / Math.max(drag.distance, 1), drag.anchor, drag.start);
    } else if (drag.mode === 'pan') {
      const point = screenPoint(event);
      updateView({ zoom: drag.start.zoom, center: [drag.start.center[0] - (point[0] - drag.anchor[0]) / drag.start.zoom, drag.start.center[1] - (point[1] - drag.anchor[1]) / drag.start.zoom] });
    } else if (drag.mode === 'zoom') {
      zoomAt(drag.start.zoom * Math.exp((drag.clientY - event.clientY) * 0.009), drag.anchor, drag.start);
    }
  };
  const pointerEnd = (event) => {
    pointers.current.delete(event.pointerId);
    if (svgRef.current?.hasPointerCapture?.(event.pointerId)) svgRef.current.releasePointerCapture(event.pointerId);
    dragRef.current = null; setDragging(false);
  };
  const keyDown = (event) => {
    if (event.target.closest?.('.atlas-marker')) return;
    const current = viewRef.current;
    if (['+', '=', '-', '_'].includes(event.key)) {
      event.preventDefault(); zoomAt(current.zoom * (['+', '='].includes(event.key) ? 1.6 : 1 / 1.6), projectIntoView(zoomFocus, current.center, current.zoom));
    } else if (event.key === '0' || event.key === 'Home') { event.preventDefault(); resetView(); }
    else if (event.key.startsWith('Arrow')) {
      event.preventDefault();
      const delta = { ArrowLeft: [-64, 0], ArrowRight: [64, 0], ArrowUp: [0, -64], ArrowDown: [0, 64] }[event.key];
      if (delta) updateView({ zoom: current.zoom, center: [current.center[0] + delta[0] / current.zoom, current.center[1] + delta[1] / current.zoom] });
    }
  };

  const routeElements = (segments, type) => segments.map(({ from_city, to_city }, index) => {
    const from = cityPoints.get(from_city);
    const to = cityPoints.get(to_city);
    if (!from || !to) return null;
    return (
      <path
        key={`${type}-${from_city}-${to_city}-${index}`}
        className={`atlas-route atlas-route--${type}`}
        d={connectorPath(from, to)}
        markerEnd={`url(#${markerId})`}
        aria-label={`${type === 'draft' ? 'Draft' : 'Current'} route: ${from_city} to ${to_city}`}
      />
    );
  });

  return (
    <section className="country-map" aria-label={`${countryName || countryCode || 'Country'} map`}>
      <div className={`country-map__canvas${dragging ? ' is-dragging' : ''}`}>
        {country && projection ? (
          <svg
            ref={svgRef}
            className="country-map__svg"
            viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
            role="group"
            tabIndex={0}
            aria-describedby="atlas-map-gestures"
            onPointerDown={pointerDown} onPointerMove={pointerMove}
            onPointerUp={pointerEnd} onPointerCancel={pointerEnd} onLostPointerCapture={pointerEnd}
            onKeyDown={keyDown}
            onDoubleClick={(event) => { if (!event.target.closest?.('.atlas-marker')) resetView(); }}
            aria-label={`${countryName || country.properties?.name} outline and city markers`}
          >
            <defs>
              <marker id={markerId} viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
                <path d="M0 0 L10 5 L0 10 Z" className="atlas-arrowhead" />
              </marker>
            </defs>
            <g className="atlas-map-world" transform={mapTransform}>
              <g className="atlas-country-relief" aria-hidden="true">
                {[12, 8, 4].map((depth) => <path key={depth} d={countryPath} transform={`translate(0 ${depth / zoom})`} fillRule="evenodd" />)}
              </g>
              <path className="atlas-country-shape" d={countryPath} fillRule="evenodd" />
              <g aria-label="Current route">{routeElements(currentSegments, 'current')}</g>
              <g aria-label="Draft route">{routeElements(draftSegments, 'draft')}</g>
            </g>
              {[...cities].sort((a, b) =>
                (Number(draftOrder.has(a.city_id)) + Number(a.city_id === focusedCity) * 2)
                - (Number(draftOrder.has(b.city_id)) + Number(b.city_id === focusedCity) * 2)
              ).map((city) => {
              const cityIndex = cities.indexOf(city);
              const sourcePoint = cityPoints.get(city.city_id);
              if (!sourcePoint) return null;
              const [x, y] = mapPoint(sourcePoint);
              const markerScale = 30 / (43 * Math.max(viewScale, 0.1));
              const draftNumber = draftOrder.get(city.city_id);
              const selected = draftNumber != null;
              const draftChange = draftChanges.get(city.city_id);
              const isFocused = focusedCity === city.city_id;
              const anchor = anchorMap[city.name];
              const hasNearbyLabel = cities.some((otherCity) => {
                if (otherCity.city_id === city.city_id) return false;
                const otherPoint = cityPoints.get(otherCity.city_id);
                return otherPoint && Math.hypot(otherPoint[0] - sourcePoint[0], otherPoint[1] - sourcePoint[1]) < 70;
              });
              const labelSide = !hasNearbyLabel ? 'default' : cityIndex % 2 === 1 ? 'above' : 'below';
              return (
                <g
                  key={city.city_id}
                  className={`atlas-marker${selected ? ' atlas-marker--selected' : ''}${draftChange ? ` atlas-marker--${draftChange}` : ''}${isFocused ? ' atlas-marker--focused' : ''}`}
                  transform={`translate(${x.toFixed(2)} ${y.toFixed(2)}) scale(${markerScale.toFixed(3)})`}
                  role="button"
                  tabIndex={0}
                  aria-label={`${city.name}${selected ? `, draft stop ${draftNumber}` : ''}${anchor?.approximate ? ', approximate destination anchor' : ''}`}
                  aria-pressed={selected}
                  onClick={(event) => selectMarker(event, city.city_id)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault();
                      onSelectCity?.(city.city_id);
                    }
                  }}
                >
                  <circle className="atlas-marker__target" cx="0" cy="-22" r="1" stroke="transparent" strokeWidth="44" vectorEffect="non-scaling-stroke" pointerEvents="stroke" />
                  <g className="atlas-marker__symbol">
                  <path className="atlas-marker__pin" d={pinPath()} />
                  {!selected && <circle className="atlas-marker__dot" cx="0" cy="-27" r="3.1" />}
                  {selected && <text className="atlas-marker__number" x="0" y="-23">{draftNumber}</text>}
                  </g>
                  {labelSide !== 'default' && <path className="atlas-marker__leader" d={labelSide === 'above' ? 'M8 -22 L18 -43' : 'M8 -19 L18 12'} />}
                  <text className="atlas-marker__label" x="21" y={labelSide === 'above' ? '-43' : labelSide === 'below' ? '12' : '-25'}>{city.name}</text>
                  <title>{anchor?.label || city.name}</title>
                </g>
              );
            })}
          </svg>
        ) : (
          <div className="country-map__empty" role="status">Map outline unavailable for this destination.</div>
        )}
        {country && projection && <span className="country-map__north" aria-hidden="true">N ↑</span>}

      </div>

      <p className="country-map__gestures" id="atlas-map-gestures">Drag up to zoom in · Down to zoom out · Shift-drag to move<br />Scroll or pinch to zoom · Double-click to reset<span className="atlas-sr-only">. Keyboard: plus and minus zoom, arrow keys move, zero resets.</span></p>
      <div className="country-map__city-list" role="group" aria-label="Choose a city">
        {cities.map((city) => {
          const anchor = anchorMap[city.name];
          return (
            <button
              key={city.city_id}
              type="button"
              className={`country-map__city${focusedCity === city.city_id ? ' is-focused' : ''}`}
              aria-pressed={focusedCity === city.city_id}
              onClick={() => onSelectCity?.(city.city_id)}
            >
              {city.name}
              {!anchor && <span className="country-map__no-point">map point unavailable</span>}
              {anchor?.approximate && <span className="country-map__approximate">destination anchor</span>}
            </button>
          );
        })}
      </div>
      <footer className="country-map__attribution">
        Map data: <a href="https://www.naturalearthdata.com/about/terms-of-use/" target="_blank" rel="noreferrer">Natural Earth</a>
        {' · '}Place data: <a href="https://www.geonames.org/" target="_blank" rel="noreferrer">GeoNames (CC BY 4.0)</a>
      </footer>
    </section>
  );
}
