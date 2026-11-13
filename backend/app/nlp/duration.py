import re
from app.nlp.numbers import SMALL, integer

# Compact "5N/6D", "5N 6D" or "6D/5N" notation: the night count is explicit, the day count only cross-checks it.
NIGHT_DAY = re.compile(r'(?<!\w)(\d{1,2})\s*n\s*[/&+,-]?\s*(\d{1,2})\s*d(?!\w)')
DAY_NIGHT = re.compile(r'(?<!\w)(\d{1,2})\s*d\s*[/&+,-]?\s*(\d{1,2})\s*n(?!\w)')
BARE_NIGHTS = re.compile(r'(?<![\w.])(\d{1,2})n(?!\w)')
WEEKS = re.compile(r'(?<!next )(?<!this )(?<!last )(?<!first )(?<!second )(?<!third )(?<!every )'
                   r'\b(?:(?:an?|one|two|three|\d+) )?(?:weeks?|fortnight)(?: long|-long)?\b')


def extract(ctx):
    for m in re.finditer(r'(?<![\w-])(' + SMALL + r')\s*(?:-|to|or)\s*(' + SMALL + r')[ -]+nights?\b', ctx.text):
        ctx.issue('nights', 'NIGHTS_RANGE', 'You gave a range of nights. The form needs one exact number of nights.')
    for pattern, night_group in ((NIGHT_DAY, 1), (DAY_NIGHT, 2)):
        for m in pattern.finditer(ctx.text):
            nights, days = int(m[night_group]), int(m[3 - night_group])
            ctx.add('nights', nights, m.span())
            if days != nights + 1:
                ctx.issue('nights', 'DAY_NIGHT_CONFLICT', 'Your day count and overnight stays do not agree. Confirm the number of nights.')
    nights_matches = list(re.finditer(r'(?<!\w)(' + SMALL + r')[ -]+nights?\b', ctx.text))
    for m in nights_matches:
        value = integer(m[1])
        if value is None: ctx.issue('nights', 'WHOLE_NIGHTS_NEEDED', 'Enter a whole number of nights.', 'error')
        else: ctx.add('nights', value, m.span(), 'NORMALIZED' if not m[1].isdigit() else 'EXPLICIT')
    if not ctx.claims['nights']:
        for m in BARE_NIGHTS.finditer(ctx.text): ctx.add('nights', int(m[1]), m.span(), 'NORMALIZED')
    if len(nights_matches) > 1 and len({integer(m[1]) for m in nights_matches}) == 1:
        # Equal repeats ("3 nights Tokyo and 3 nights Kyoto") would otherwise collapse into one count and drop a stay.
        ctx.issue('nights', 'MULTIPLE_NIGHT_COUNTS', 'You gave more than one night count. The form needs the total nights for the whole trip.')
    days = list(re.finditer(r'(?<!\w)(' + SMALL + r')[ -]+days?\b', ctx.text))
    week = WEEKS.search(ctx.text)
    if (days or week) and not ctx.claims['nights']:
        ctx.issue('nights', 'DAYS_NOT_NIGHTS', 'The form needs nights. Do you mean five or six nights for six days, or another number? Please specify nights.' if days else 'A week or fortnight describes days, but the form needs nights. How many nights will you stay?')
    elif days and ctx.claims['nights']:
        for m in days:
            count = integer(m[1]); nights = {c['value'] for c in ctx.claims['nights']}
            if count is not None and count - 1 not in nights:
                ctx.issue('nights', 'DAY_NIGHT_CONFLICT', 'Your day count and overnight stays do not agree. Confirm the number of nights.')
