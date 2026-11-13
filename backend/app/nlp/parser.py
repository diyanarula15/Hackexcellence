"""Pure, deterministic natural-language input adapter. No planning or persistence imports."""
import re
from datetime import date

from app.nlp import budget, dates, duration, locations, travelers
from app.nlp.entities import Context, FIELDS
from app.nlp.normalize import normalize, tokenize
from app.nlp.validation import validate


def recognize_intent(text):
    if re.search(r'\b(?:cancel|refund)\b.*\b(?:booking|reservation|trip)\b', text): return 'CANCEL_RESERVATION'
    if re.search(r'\b(?:show|find|lookup|look up|retrieve)\b.*\b(?:booking|reservation|reference)\b', text): return 'LOOKUP_RESERVATION'
    if re.search(r'\b(?:what|how|weather|forecast)\b.*\b(?:weather|forecast)\b|^\s*weather\b', text): return 'WEATHER'
    if re.search(r'^\s*(?:tell me about|what is|where is)\b', text): return 'INFORMATION'
    return 'PLAN_HOLIDAY'


def parse_trip_request(text: str, catalog, reference_date: date | None = None):
    if not isinstance(text, str) or not text.strip() or len(text) > 2000:
        raise ValueError('Enter a request containing 1 to 2000 characters.')
    normalized = normalize(text)
    ctx = Context(normalized, catalog, reference_date)
    intent = recognize_intent(ctx.text)
    if intent == 'PLAN_HOLIDAY':
        locations.extract(ctx)
        dates.extract(ctx)
        duration.extract(ctx)
        travelers.extract(ctx)
        budget.extract(ctx)
    fields, interpretations, evidence = ctx.resolve()
    if intent == 'PLAN_HOLIDAY' and not ctx.entities and not ctx.issues:
        intent = 'UNSUPPORTED'
    if intent != 'PLAN_HOLIDAY':
        ctx.issue('request', 'UNSUPPORTED_INTENT', 'This input fills a holiday search form. For an existing booking use Find reservation; for a new trip give destination, dates, travelers and budget.', 'error')
    else:
        validate(ctx, fields, interpretations)
        if re.search(r'\b(?:direct flights?|nonstop|\d[ -]star|vegetarian|vegan)\b', ctx.text):
            ctx.issue('request', 'UNSUPPORTED_PREFERENCE', 'Only the seven displayed trip fields are applied. Flight/hotel/meal preferences are not extra planner constraints.', 'warning')
    missing = [field for field in FIELDS if fields[field] is None]
    messages = {'departure': 'Which supported city are you departing from?', 'country': 'Which destination country?',
                'start_date': 'What is the destination-local arrival date?', 'nights': 'How many nights will you stay?',
                'adults': 'How many adults are traveling?', 'child_ages': 'Give each child\'s whole-year age, or say adults only.',
                'budget': 'What is the total INR budget?'}
    for field in missing:
        if not any(i['field'] == field for i in ctx.issues): ctx.issue(field, 'MISSING_FIELD', messages[field])
    blocked = any(i['severity'] != 'warning' for i in ctx.issues)
    can_search = intent == 'PLAN_HOLIDAY' and not missing and not blocked
    status = 'UNSUPPORTED_INTENT' if intent != 'PLAN_HOLIDAY' else 'READY' if can_search else 'NEEDS_CORRECTION' if any(i['severity'] == 'error' or i['code'] == 'CONFLICT' for i in ctx.issues) else 'NEEDS_DETAILS'
    return {'intent': intent, 'status': status, 'fields': fields, 'interpretations': interpretations,
            'issues': ctx.issues, 'missing_fields': missing, 'assumptions': ctx.assumptions,
            'evidence': evidence, 'entities': ctx.entities, 'tokens': tokenize(normalized),
            'original_text': text, 'normalized_text': normalized.text,
            'reference_date': reference_date.isoformat() if reference_date else None,
            'metadata': ctx.metadata, 'can_search': can_search, 'can_submit': can_search}
