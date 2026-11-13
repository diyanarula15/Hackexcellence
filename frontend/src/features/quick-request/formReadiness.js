/** Lightweight form gating from API metadata. The backend still validates every actual search. */
export function formReadiness(form, meta, unresolved = []) {
  if (!meta) return ['Wait for the available destinations to load.'];
  const issues = [];
  const whole = (text) => /^\d+$/.test(String(text).trim());
  if (!meta.departure_airports.some((d) => d.airport === form.departure)) issues.push('Select a departure city.');
  if (!meta.countries.some((c) => [c.name.toLowerCase(), c.code.toLowerCase()].includes(form.country.toLowerCase()))) issues.push('Select a destination country.');
  const nights = Number(form.nights), adults = Number(form.adults);
  if (!whole(form.nights) || nights < meta.nights.min || nights > meta.nights.max) issues.push(`Enter ${meta.nights.min} to ${meta.nights.max} nights.`);
  if (!whole(form.adults) || adults < 1) issues.push('Enter the number of adults.');
  const ageText = form.child_ages.trim();
  const ages = ageText ? ageText.split(',').map((s) => s.trim()).filter(Boolean) : [];
  if (!ageText && unresolved.includes('child_ages')) issues.push('Provide the missing child ages, or update the request to explicitly say no children.');
  if (ages.some((age) => !whole(age) || Number(age) > 17)) issues.push('Enter each child’s age from 0 to 17, separated by commas.');
  if (adults + ages.length > meta.max_travelers) issues.push(`The party cannot exceed ${meta.max_travelers} travelers.`);
  const budget = form.budget.replace(/[₹,\s]/g, '');
  if (!whole(budget) || Number(budget) <= 0 || !Number.isSafeInteger(Number(budget))) issues.push('Enter a positive whole INR budget.');
  const start = new Date(`${form.start_date}T00:00:00Z`);
  const validDate = /^\d{4}-\d{2}-\d{2}$/.test(form.start_date) && !Number.isNaN(start.getTime()) && start.toISOString().slice(0, 10) === form.start_date;
  if (!validDate) issues.push('Enter the destination arrival date.');
  else {
    const end = new Date(start); end.setUTCDate(end.getUTCDate() + nights);
    if (form.start_date < meta.allowed_dates.first_night || form.start_date > meta.allowed_dates.last_departure ||
        (Number.isInteger(nights) && !Number.isNaN(end.getTime()) && end.toISOString().slice(0, 10) > meta.allowed_dates.last_departure)) {
      issues.push(`Arrival and return must fit ${meta.allowed_dates.first_night} to ${meta.allowed_dates.last_departure}.`);
    }
  }
  return issues;
}
