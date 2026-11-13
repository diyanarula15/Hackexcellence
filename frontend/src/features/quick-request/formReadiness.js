/** Lightweight form gating from API metadata. The backend still validates every actual search. */

/** ISO date `iso` moved by `days` (UTC, so no time-zone drift). */
export function addDaysISO(iso, days) {
  const date = new Date(`${iso}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

/**
 * The last first day the calendar should offer: the return flight (first day + nights) must still
 * be on or before the last departure date. Uses the entered nights when valid, else the minimum.
 */
export function latestStartDate(meta, nightsText) {
  if (!meta) return undefined;
  const nights = Number(nightsText);
  const valid = /^\d+$/.test(String(nightsText).trim()) && nights >= meta.nights.min && nights <= meta.nights.max;
  return addDaysISO(meta.allowed_dates.last_departure, -(valid ? nights : meta.nights.min));
}

/**
 * Every problem with the form, tied to the field it belongs to (`field` is null when it belongs to
 * none, e.g. metadata still loading), so each message can be shown on its own field.
 * @returns {{ field: string | null, text: string }[]}
 */
export function fieldIssues(form, meta, unresolved = []) {
  if (!meta) return [{ field: null, text: 'Wait for the available destinations to load.' }];
  const issues = [];
  const add = (field, text) => issues.push({ field, text });
  const whole = (text) => /^\d+$/.test(String(text).trim());
  if (!meta.departure_airports.some((d) => d.airport === form.departure)) add('departure', 'Select a departure city.');
  if (!meta.countries.some((c) => [c.name.toLowerCase(), c.code.toLowerCase()].includes(form.country.toLowerCase()))) add('country', 'Select a destination country.');
  const nights = Number(form.nights), adults = Number(form.adults);
  if (!whole(form.nights) || nights < meta.nights.min || nights > meta.nights.max) add('nights', `Enter ${meta.nights.min} to ${meta.nights.max} nights.`);
  if (!whole(form.adults) || adults < 1) add('adults', 'Enter the number of adults.');
  const ageText = form.child_ages.trim();
  const ages = ageText ? ageText.split(',').map((s) => s.trim()).filter(Boolean) : [];
  if (!ageText && unresolved.includes('child_ages')) add('child_ages', 'Provide the missing child ages, or update the request to explicitly say no children.');
  if (ages.some((age) => !whole(age) || Number(age) > 17)) add('child_ages', 'Enter each child’s age from 0 to 17, separated by commas.');
  if (adults + ages.length > meta.max_travelers) add('adults', `The party cannot exceed ${meta.max_travelers} travelers.`);
  const budget = form.budget.replace(/[₹,\s]/g, '');
  if (!whole(budget) || Number(budget) <= 0 || !Number.isSafeInteger(Number(budget))) add('budget', 'Enter a positive whole INR budget.');
  const start = new Date(`${form.start_date}T00:00:00Z`);
  const validDate = /^\d{4}-\d{2}-\d{2}$/.test(form.start_date) && !Number.isNaN(start.getTime()) && start.toISOString().slice(0, 10) === form.start_date;
  if (!validDate) add('start_date', 'Enter the destination arrival date.');
  else {
    const end = new Date(start); end.setUTCDate(end.getUTCDate() + nights);
    if (form.start_date < meta.allowed_dates.first_night || form.start_date > meta.allowed_dates.last_departure ||
        (Number.isInteger(nights) && !Number.isNaN(end.getTime()) && end.toISOString().slice(0, 10) > meta.allowed_dates.last_departure)) {
      add('start_date', `Arrival and return must fit ${meta.allowed_dates.first_night} to ${meta.allowed_dates.last_departure}.`);
    }
  }
  return issues;
}

/** The same problems as plain messages (what blocks the search). */
export function formReadiness(form, meta, unresolved = []) {
  return fieldIssues(form, meta, unresolved).map((issue) => issue.text);
}
