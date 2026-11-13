/** Convert longitude/latitude into spherical Mercator coordinates. */
export function mercator([longitude, latitude]) {
  const safeLatitude = Math.max(-85.05112878, Math.min(85.05112878, latitude));
  const lambda = (longitude * Math.PI) / 180;
  const phi = (safeLatitude * Math.PI) / 180;
  return [lambda, Math.log(Math.tan(Math.PI / 4 + phi / 2))];
}

export function projectIntoView([x, y], [centerX, centerY], scale, width = 1000, height = 620) {
  return [width / 2 + (x - centerX) * scale, height / 2 + (y - centerY) * scale];
}

function eachPosition(geometry, visit) {
  if (!geometry) return;
  const walk = (value) => {
    if (!Array.isArray(value)) return;
    if (value.length >= 2 && typeof value[0] === 'number') {
      visit(value);
      return;
    }
    value.forEach(walk);
  };
  walk(geometry.coordinates);
}

/** Fit a GeoJSON geometry into a fixed SVG viewBox while preserving its shape. */
export function createProjection(geometry, width = 1000, height = 620, padding = 42) {
  const points = [];
  eachPosition(geometry, (coordinate) => points.push(mercator(coordinate)));
  if (!points.length) return () => [width / 2, height / 2];

  const xs = points.map(([x]) => x);
  const ys = points.map(([, y]) => y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const spanX = Math.max(maxX - minX, 1e-9);
  const spanY = Math.max(maxY - minY, 1e-9);
  const scale = Math.min((width - padding * 2) / spanX, (height - padding * 2) / spanY);
  const offsetX = (width - spanX * scale) / 2;
  const offsetY = (height - spanY * scale) / 2;

  return (coordinate) => {
    const [x, y] = mercator(coordinate);
    return [offsetX + (x - minX) * scale, height - offsetY - (y - minY) * scale];
  };
}

/** Return a path string for the outline and any islands in a GeoJSON geometry. */
export function geometryPath(geometry, project) {
  const rings = [];
  const addPolygon = (polygon) => polygon.forEach((ring) => rings.push(ring));
  if (geometry?.type === 'Polygon') addPolygon(geometry.coordinates);
  if (geometry?.type === 'MultiPolygon') geometry.coordinates.forEach(addPolygon);
  return rings
    .map((ring) => {
      if (!ring.length) return '';
      return `${ring
        .map((coordinate, index) => {
          const [x, y] = project(coordinate);
          return `${index === 0 ? 'M' : 'L'}${x.toFixed(2)},${y.toFixed(2)}`;
        })
        .join(' ')} Z`;
    })
    .join(' ');
}

export function permittedRouteSegments(route = [], connections = []) {
  const allowed = new Set(connections.map(({ from_city, to_city }) => `${from_city}\u0000${to_city}`));
  return route.slice(1).flatMap((stop, index) => {
    const from_city = route[index]?.city_id;
    const to_city = stop?.city_id;
    return from_city && to_city && allowed.has(`${from_city}\u0000${to_city}`)
      ? [{ from_city, to_city }]
      : [];
  });
}
