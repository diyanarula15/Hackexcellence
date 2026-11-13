/**
 * scripts/build-world-map.mjs - regenerate src/scene/data/worldOutline.json.
 *
 * Converts Natural Earth 1:110m land (public domain, via the `world-atlas`
 * package) into a compact list of coastline rings for the line-art map:
 *   [[lon, lat, lon, lat, …], …]   (degrees, 1 decimal)
 * Antarctica and specks are dropped. Run:  node scripts/build-world-map.mjs
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { feature } from 'topojson-client';

const topology = JSON.parse(readFileSync(new URL('../node_modules/world-atlas/land-110m.json', import.meta.url)));
const land = feature(topology, topology.objects.land);
const polygons = land.features.flatMap((f) => (f.geometry.type === 'Polygon' ? [f.geometry.coordinates] : f.geometry.coordinates));

const rings = [];
for (const polygon of polygons) {
  const ring = polygon[0]; // outer boundary only
  const lats = ring.map((p) => p[1]);
  if (Math.max(...lats) < -60) continue; // Antarctica
  if (ring.length < 7) continue; // specks
  rings.push(ring.flatMap(([lon, lat]) => [Math.round(lon * 10) / 10, Math.round(lat * 10) / 10]));
}

const out = new URL('../src/scene/data/worldOutline.json', import.meta.url);
writeFileSync(out, JSON.stringify(rings));
console.log(`${rings.length} rings, ${rings.reduce((n, r) => n + r.length / 2, 0)} points`);
