"""INR amounts, ceilings/targets and explicitly disclosed per-person normalization."""
import re
from app.nlp.numbers import MONEY, number

PREFIX = re.compile(r'(?:\bbudget(?:\s+(?:is|of|around|about|under|approximately|roughly|maximum))?|\b(?:under|within|below|up to|upto|maximum|max|not more than|around|about|approximately)|₹|\brs\.?|\binr)\s*[:=]?\s*(?:₹|inr|rs\.?\s*)?\s*(?P<amount>' + MONEY + r')', re.I)
SUFFIX = re.compile(r'(?<!\w)(?P<amount>' + MONEY + r')\s*(?:rupees?\b|inr\b|rs\b)|(?<!\w)(?P<scaled>' + MONEY + r')')


def extract(ctx):
    if re.search(r'(?:₹|budget(?: is| of)?|inr|rs\.?)\s*[-\u2212]\s*\d', ctx.text):
        ctx.issue('budget', 'POSITIVE_BUDGET_NEEDED', 'Enter a positive INR budget.', 'error')
        return
    if re.search(r'\$|\b(?:usd|dollars?|eur|euros?|gbp|pounds?|aed|dirhams?)\b', ctx.text):
        ctx.issue('budget', 'INR_BUDGET_NEEDED', 'The budget must be in INR. Enter a rupee amount; no exchange-rate conversion is performed.', 'error')
        return
    found, covered = [], []
    for pattern in (PREFIX, SUFFIX):
        for m in pattern.finditer(ctx.text):
            if any(m.start() < b and m.end() > a for a, b in covered): continue
            covered.append(m.span())
            raw = m.groupdict().get('amount') or m.groupdict().get('scaled')
            if m.groupdict().get('scaled') and not re.search(r'(?:\b(?:lakhs?|lacs?|l|crores?|cr|thousands?|k|grand|million|m)\b|(?<=\d)(?:l|k|cr|m|lakhs?|lacs?|crores?)\b)', raw): continue
            value = number(raw)
            if value is None or value != value.to_integral_value():
                ctx.issue('budget', 'INVALID_INR_AMOUNT', 'Enter a whole INR amount, using valid comma grouping.', 'error'); continue
            if abs(value) > 9007199254740991:
                ctx.issue('budget', 'BUDGET_TOO_LARGE', 'That INR amount is too large to represent exactly in the search form.', 'error'); continue
            before = ctx.text[max(0, m.start()-18):m.start()]
            # "not more than" is a ceiling, while "not 2 lakh" is an excluded amount.
            if re.search(r'\b(?:instead of|rather than|not)\s*₹?\s*$', before): continue
            prefix = (before + m[0].split(raw)[0]).strip()
            ceiling = bool(re.search(r'\b(?:under|within|below|up to|upto|maximum|max|not more than)\b', prefix))
            approximate = bool(re.search(r'\b(?:around|about|approximately|roughly)\b', prefix))
            suffix = ctx.text[m.end():m.end()+35]
            per_person = bool(re.match(r'\s*(?:rupees?\s*)?(?:per (?:person|head|traveler|traveller)|each|pp)\b', suffix))
            found.append((m, int(value), 'ceiling' if ceiling else 'approximate' if approximate else 'target', per_person))
    if not found:
        # A lone grouped amount ("1,50,000") is unmistakably money even without a currency cue.
        bare = re.search(r'(?<![\d,.])(\d{1,2}(?:,\d{2})*,\d{3}|\d{1,3}(?:,\d{3})+)(?![\d,]|\.\d)', ctx.text)
        if bare and int(bare[1].replace(',', '')) >= 10000:
            ctx.add('budget', int(bare[1].replace(',', '')), bare.span(1), 'INFERRED')
            ctx.assume('budget', 'A bare grouped number was read as the total INR budget; confirm it.')
            ctx.metadata['budget_semantics'] = 'target'
    ceilings = [item for item in found if item[2] == 'ceiling']
    selected = ceilings or found
    if ceilings and len(found) > len(ceilings):
        ctx.metadata['budget_targets'] = [v for _, v, kind, _ in found if kind != 'ceiling']
        ctx.assume('budget', 'The explicitly stated maximum is used as the form budget; the other amount remains a target.')
        if any(target > ceiling for _, target, kind, _ in found if kind != 'ceiling' for _, ceiling, _, _ in ceilings):
            ctx.issue('budget', 'TARGET_ABOVE_MAXIMUM', 'Your budget target is above the stated maximum. Which amount should be used?')
    for match, amount, kind, per_person in selected:
        if per_person:
            adults = {c['value'] for c in ctx.claims['adults']}
            children = ctx.claims['child_ages']
            blocked = any(i['field'] in ('adults', 'child_ages') and i['severity'] != 'warning' for i in ctx.issues)
            if len(adults) != 1 or not children or blocked:
                ctx.issue('budget', 'PER_PERSON_TOTAL_NEEDED', 'This is a per-person budget. Confirm the full adult/child party before proposing a group total.'); continue
            party = next(iter(adults)) + len(children[0]['value'])
            unit = amount; amount *= party
            ctx.assume('budget', f'Proposed group budget: INR {unit} per person × {party} travelers = INR {amount}.')
        ctx.add('budget', amount, match.span(), 'NORMALIZED')
        ctx.metadata['budget_semantics'] = kind
        if kind == 'approximate': ctx.assume('budget', 'This amount is approximate, not a guaranteed hard ceiling. Confirm it before applying it to the form.')
    # Ranges are alternatives, not a single selectable maximum.
    if re.search(r'\b(?:budget|between)\b[^.;!?]{0,30}\d+(?:\.\d+)?\s*(?:to|or|-)\s*\d+(?:\.\d+)?\s*(?:lakh|lac|k|l)\b', ctx.text):
        ctx.issue('budget', 'BUDGET_RANGE', 'You gave a budget range. What exact maximum INR amount should the form use?')
