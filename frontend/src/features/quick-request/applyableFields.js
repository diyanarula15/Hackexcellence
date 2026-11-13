/** The one rule for which parsed values may be written to the form. Used by the review
 *  screen (QuickRequest) and the apply step (bookingStore) so they can never disagree. */
export const QUICK_FIELDS = [
  ['departure', 'Leaving from'], ['country', 'Destination'], ['start_date', 'First day'],
  ['nights', 'Nights'], ['adults', 'Adults'], ['child_ages', "Children's ages"], ['budget', 'Budget'],
];

const APPLYABLE_STATUSES = ['EXPLICIT', 'NORMALIZED', 'INFERRED'];

/** True when the interpretation status or an issue means the user must decide this field. */
export function isFieldBlocked(field, result) {
  const status = result.interpretations?.[field]?.status;
  if (status && !APPLYABLE_STATUSES.includes(status)) return true;
  return (result.issues ?? []).some((issue) => issue.field === field &&
    (issue.severity !== 'warning' || issue.candidates?.length));
}

/** `{ field: value }` for every field that has a value and is not blocked. */
export function applyableFields(result) {
  return Object.fromEntries(QUICK_FIELDS
    .filter(([field]) => result.fields?.[field] != null && !isFieldBlocked(field, result))
    .map(([field]) => [field, result.fields[field]]));
}
