/** Local structural checks only. Complete travel feasibility and all pricing stay on the server. */
export function routeErrors(route, options) {
  if (!options) return ['Route information is loading.'];
  const errors = [];
  const known = new Set(options.cities.map((city) => city.city_id));
  const edges = new Set(options.connections.map((edge) => `${edge.from_city}\u0000${edge.to_city}`));
  const seen = new Set();
  if (!route.length) errors.push('Choose at least one city.');
  for (const { city_id, nights } of route) {
    if (!known.has(city_id)) errors.push(`${city_id} is not available in this country.`);
    if (seen.has(city_id)) errors.push(`Visit ${city_id} only once.`);
    seen.add(city_id);
    if (!Number.isInteger(nights) || nights < options.min_nights_per_city) {
      errors.push(`Stay at least ${options.min_nights_per_city} nights in ${city_id}.`);
    }
  }
  const total = route.reduce((sum, stop) => sum + (Number.isInteger(stop.nights) ? stop.nights : 0), 0);
  if (total !== options.total_nights) errors.push(`Allocate exactly ${options.total_nights} nights; currently ${total}.`);
  if (route.length > Math.floor(options.total_nights / options.min_nights_per_city)) {
    errors.push(`Not enough nights for ${route.length} cities at ${options.min_nights_per_city} nights each.`);
  }
  for (let i = 1; i < route.length; i += 1) {
    if (!edges.has(`${route[i - 1].city_id}\u0000${route[i].city_id}`)) {
      errors.push(`No catalog connection from ${route[i - 1].city_id} to ${route[i].city_id}.`);
    }
  }
  return errors;
}

function redistribute(route, options) {
  const minimum = options.min_nights_per_city;
  if (!route.length || route.length * minimum > options.total_nights) return route;
  const next = route.map((s) => ({ ...s, nights: Math.max(minimum, s.nights) }));
  let difference = next.reduce((sum, s) => sum + s.nights, 0) - options.total_nights;
  // Take only surplus nights, keeping each stop's minimum. No route is ever saved here.
  for (const stop of [...next].sort((a, b) => b.nights - a.nights)) {
    const take = Math.min(Math.max(difference, 0), stop.nights - minimum);
    stop.nights -= take;
    difference -= take;
  }
  if (difference < 0) next[next.length - 1].nights -= difference;
  return next;
}

export function routeActions(route, city, options) {
  if (!options || !city) return [];
  const actions = [];
  const index = route.findIndex((s) => s.city_id === city);
  const add = (id, label, next, extraReason) => {
    const reasons = extraReason ? [extraReason] : routeErrors(next, options);
    actions.push({ id, label, route: reasons.length ? null : next, reason: reasons.join(' ') });
  };
  if (index < 0) {
    if ((route.length + 1) * options.min_nights_per_city > options.total_nights) {
      add('add', `Add ${city}`, route, `Adding a city requires at least ${(route.length + 1) * options.min_nights_per_city} nights; this holiday has ${options.total_nights}.`);
    } else {
      for (let at = 0; at <= route.length; at += 1) {
        const next = [...route.slice(0, at), { city_id: city, nights: options.min_nights_per_city }, ...route.slice(at)];
        add(`add-${at}`, `Add ${city} ${at === 0 ? 'as first stop' : `after ${route[at - 1].city_id}`}`, redistribute(next, options));
      }
    }
    route.forEach((stop, at) => {
      add(`replace-${at}`, `Replace ${stop.city_id} with ${city}`, route.map((s, i) => i === at ? { ...s, city_id: city } : { ...s }));
    });
  } else {
    for (const [delta, label] of [[-1, 'Move Earlier'], [1, 'Move Later']]) {
      const at = index + delta;
      const next = route.map((s) => ({ ...s }));
      if (at >= 0 && at < next.length) [next[index], next[at]] = [next[at], next[index]];
      add(`move-${delta}`, label, next, at < 0 ? `${city} is already the first stop.` : at >= route.length ? `${city} is already the last stop.` : null);
    }
    add('remove', `Remove ${city}`, redistribute(route.filter((s) => s.city_id !== city), options), route.length === 1 ? 'Keep at least one city in the holiday.' : null);
    for (const candidate of options.cities.filter((c) => !route.some((s) => s.city_id === c.city_id))) {
      add(`replace-with-${candidate.city_id}`, `Replace ${city} with ${candidate.name}`, route.map((s, i) => i === index ? { ...s, city_id: candidate.city_id } : { ...s }));
    }
  }
  return actions;
}
