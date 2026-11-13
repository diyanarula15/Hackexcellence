"""Counts are interpreted in their local relationship/age context, never as free numbers."""
import re
from app.nlp.numbers import SMALL, integer

MONTHS = r'jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|july|august|september|october|november|december'
CHILD = r'(?:children|child|kids?|sons?|daughters?|twins?|bab(?:y|ies)|infants?)'


def extract(ctx):
    explicit = []
    for m in re.finditer(r'(?<!\w)(' + SMALL + r')\s+adults?\b|\badults?\s*[:=]?\s*(' + SMALL + r')', ctx.text):
        count = integer(m[1] or m[2]); explicit.append((count, m.span()))
    inferred = []
    # "couple", "a couple", "2 couples" are travelers; "a couple of days" is a quantity, not people.
    for m in re.finditer(r'\b(?:(' + SMALL + r')\s+couples?|(?:we(?: are|\x27re) )?(?:a )?couple)\b(?!\s+of\b)', ctx.text):
        inferred.append((2 * (integer(m[1]) if m[1] else 1), m.span()))
    relationship = re.search(r'\b(?:me|myself|i)\b[^.;!?]{0,35}?\b(?:my wife|my husband|my partner)\b|\b(?:my wife|my husband|my partner)\b[^.;!?]{0,25}?\b(?:and i|and me|with me)\b', ctx.text)
    if relationship: inferred.append((2, relationship.span()))
    spouses = re.search(r'\b(?:husband|wife)\b[ ,&]*(?:and|&)?\s*\b(?:wife|husband)\b', ctx.text)
    if spouses and not relationship: inferred.append((2, spouses.span()))
    parents = re.search(r'\bmy parents and (?:i|me)\b', ctx.text)
    if parents: inferred.append((3, parents.span()))
    solo = re.search(r'\b(?:solo|just me|traveling alone|only me)\b', ctx.text)
    if solo: inferred.append((1, solo.span()))
    for count, span in explicit:
        if count is None: ctx.issue('adults', 'INVALID_ADULT_COUNT', 'Enter a whole adult count.', 'error')
        else: ctx.add('adults', count, span)
    if not explicit:
        for count, span in inferred: ctx.add('adults', count, span, 'INFERRED')
    elif any(count is not None and n > count for n, _ in inferred for count, _ in explicit):
        ctx.issue('adults', 'ADULT_COUNT_CONFLICT', 'The relationships mentioned include more adults than your explicit adult count.')
    # Another adult relative beside a stated party ("2 adults and 1 senior parent") must not vanish silently.
    extra = re.search(r'(?:\band\b|\bwith\b|\bplus\b|\+|,)\s*(?:my |our |an? |\d+ |one |two |three )?(?:senior |elderly |old )?(?:parents?|mother|father|mom|mum|dad|grand\w+|in-laws?|friends?|brother|sister|uncle|aunt|cousins?|colleagues?)\b', ctx.text)
    if extra and not parents and (explicit or inferred):
        ctx.issue('adults', 'EXTRA_TRAVELERS_MENTIONED', f'You also mentioned "{extra[0].lstrip(" ,+").strip()}". How many adults are traveling in total?')
    child_counts = [(integer(m[1]), m.span()) for m in re.finditer(r'(?<!\w)(' + SMALL + r')\s+' + CHILD + r'\b', ctx.text)]
    children_mentioned = bool(re.search(r'\b' + CHILD + r'\b|\b(?:toddler|teenager)\b', ctx.text))
    no_children = re.search(r'\b(?:no (?:children|kids)|without (?:children|kids)|adults only)\b', ctx.text)
    if no_children: child_counts.append((0, no_children.span()))
    ages, spans = [], []
    consumed = []
    list_pattern = re.compile(r'\b(?:aged?|ages?(?: are| is)?|kids?|child(?:ren)?)\s*[:=]?\s*\(?\s*(' + SMALL + r'(?:\s*(?:,|and|&)\s*' + SMALL + r')*)')
    for m in list_pattern.finditer(ctx.text):
        # "I am aged 35" is not a child's age without a child context.
        prefix = ctx.text[max(0, m.start()-55):m.start()]
        if not re.search(r'\b' + CHILD + r'\b', prefix) and not m[0].startswith(('kid', 'child')): continue
        values = []
        last_end = m.end()
        for n in re.finditer(SMALL, m[1]):
            after = ctx.text[m.start(1)+n.end():]
            if re.match(r'[ -]*(?:nights?|days?|adults?|lakh|people|travelers|travellers|rupees|' + MONTHS + r')\b', after): break
            values.append(integer(n[0])); last_end = m.start(1) + n.end()
        if not values or any(v is None for v in values): continue
        if 'twin' in prefix and len(values) == 1: values *= 2
        ages.extend(values); spans.append((m.start(), last_end)); consumed.append((m.start(), last_end))
    for m in re.finditer(r'(?<!\w)(' + SMALL + r')[ -]*(?:years?[ -]+old|years?\s+old|yo\b|y/o\b)', ctx.text):
        if any(m.start() < b and m.end() > a for a, b in consumed): continue
        following = ctx.text[m.end():m.end()+25]
        if re.match(r'\s*(?:wife|husband|mother|father|parent|adult)\b', following): continue
        value = integer(m[1])
        if value is not None:
            ages.extend([value, value] if re.match(r'\s+twins?\b', following) else [value]); spans.append(m.span())
    for m in re.finditer(r'\b(?:son|daughter|child)(?:\s+is)?\s+(' + SMALL + r')\b', ctx.text):
        if not any(m.start() < b and m.end() > a for a, b in consumed):
            value = integer(m[1])
            if value is not None: ages.append(value); spans.append(m.span())
    months = re.search(r'(' + SMALL + r')[ -]+months?[ -]+old\b', ctx.text)
    if months: ctx.issue('child_ages', 'WHOLE_YEAR_AGE_NEEDED', 'The form accepts whole-year ages only. Enter the infant\'s age in completed whole years; months are not converted automatically.')
    counts = {n for n, _ in child_counts if n is not None}
    if len(counts) > 1: ctx.issue('child_ages', 'CHILD_COUNT_CONFLICT', 'You gave different child counts. Confirm the number and each age.')
    count = next(iter(counts)) if len(counts) == 1 else None
    if count is not None: ctx.metadata['child_count'] = count
    if no_children and ages: ctx.issue('child_ages', 'CHILD_COUNT_CONFLICT', 'You said no children but also gave child ages.')
    elif count is not None and count != len(ages):
        ctx.issue('child_ages', 'MISSING_CHILD_AGE' if count > len(ages) else 'CHILD_COUNT_CONFLICT', f'You mentioned {count} children but provided {len(ages)} ages. Give one whole-year age for each child.')
    elif ages:
        if any(not 0 <= age <= 17 for age in ages):
            ctx.issue('child_ages', 'CHILD_AGE_OUT_OF_RANGE', 'Children must be aged 0 through 17. Count travelers aged 18 or older as adults.', 'error')
        start, end = min(a for a, _ in spans), max(b for _, b in spans)
        ctx.add('child_ages', ages, (start, end), 'NORMALIZED')
        ctx.metadata['child_count'] = len(ages)
    elif count == 0 or (not children_mentioned and (explicit or inferred)):
        span = no_children.span() if no_children else (explicit or inferred)[0][1]
        ctx.add('child_ages', [], span, 'EXPLICIT' if no_children else 'INFERRED')
        if not no_children: ctx.assume('child_ages', 'No children were mentioned in the stated party. Add ages in the form if children are traveling.')
    elif children_mentioned:
        ctx.issue('child_ages', 'MISSING_CHILD_AGE', 'What are the ages of the children? Do not use a guessed age for a toddler or teenager.')
    totals = []
    for m in re.finditer(r'(?<!\w)(' + SMALL + r')\s+(?:people|persons|travelers|travellers|pax)\b|\bfamily of\s+(' + SMALL + r')', ctx.text):
        totals.append((integer(m[1] or m[2]), m.span()))
    adult_values = {c['value'] for c in ctx.claims['adults']}
    for total, span in totals:
        kids = len(ctx.claims['child_ages'][0]['value']) if ctx.claims['child_ages'] else 0
        if not adult_values and kids and total is not None and total > kids:
            # "family of 4 with 2 kids aged 5 and 8": the remaining travelers are the adults.
            ctx.add('adults', total - kids, span, 'INFERRED')
            ctx.assume('adults', f'{total} travelers minus {kids} children gives {total - kids} adults.')
            adult_values = {total - kids}
    for total, _ in totals:
        if len(adult_values) != 1 or not ctx.claims['child_ages']:
            ctx.issue('adults', 'PARTY_COMPOSITION_NEEDED', 'How many adults are traveling, and are any travelers under 18? Give every child\'s age.')
        elif total != next(iter(adult_values)) + len(ctx.claims['child_ages'][0]['value']):
            ctx.issue('adults', 'PARTY_COUNT_CONFLICT', 'The total traveler count does not match the adults plus children.')
