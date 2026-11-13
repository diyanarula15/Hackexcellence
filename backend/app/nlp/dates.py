"""Calendar dates, arrival semantics and bounded relative-date interpretation."""
import calendar
import re
from datetime import date, timedelta

MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})
MONTHS['sept'] = 9
MONTH = '(?:' + '|'.join(sorted(MONTHS, key=len, reverse=True)) + ')'
DAY_MONTH = re.compile(r'\b(?P<day>\d{1,2})\s+(?P<month>' + MONTH + r')(?:\s*,?\s*(?P<year>\d{4}))?\b')
MONTH_DAY = re.compile(r'\b(?P<month>' + MONTH + r')\s+(?P<day>\d{1,2})(?:\s*,?\s*(?P<year>\d{4}))?\b')
ISO = re.compile(r'(?<!\d)(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})(?!\d)')
NUMERIC = re.compile(r'(?<!\d)(?P<day>\d{1,2})/(?P<month>\d{1,2})(?:/(?P<year>\d{4}))?(?!\d)')
# Dotted/dashed numeric dates are only trusted with a full year, so "4-6 nights" is never a date.
DOTTED = re.compile(r'(?<![\d-])(?P<day>\d{1,2})[.-](?P<month>\d{1,2})[.-](?P<year>\d{4})(?!\d)')
FUZZY = re.compile(r'\b(?:(?:early|mid|late|end of|beginning of|start of|middle of|(?:first|second|third|last) (?:week|half) of|sometime in|in|during)[ -]*' + MONTH + r'(?:\s+\d{4})?|diwali|deepavali|holi|dussehra|navratri|durga puja|christmas|new year|eid|onam|pongal|easter|summer (?:vacation|holidays?))\b')
RANGE = re.compile(r'\b(?P<first>\d{1,2})\s*(?:to|through|until|-)\s*(?P<last>\d{1,2})\s+(?P<month>' + MONTH + r')(?:\s*,?\s*(?P<year>\d{4}))?\b')
MONTH_RANGE = re.compile(r'\b(?P<month>' + MONTH + r')\s+(?P<first>\d{1,2})\s*(?:to|through|until|-)\s*(?:(?P<end_month>' + MONTH + r')\s+)?(?P<last>\d{1,2})(?:\s*,?\s*(?P<year>\d{4}))?\b')


def extract(ctx):
    window = ctx.catalog.catalog.destinations['rules']['data_window']
    years = set(range(date.fromisoformat(window['first_night']).year, date.fromisoformat(window['last_departure']).year + 1))
    consumed, dates = [], []
    def year(value):
        if value: return int(value)
        if len(years) == 1:
            result = next(iter(years))
            ctx.assume('start_date', f'The omitted year is {result}, the only year in the active travel catalog.')
            return result
        ctx.issue('start_date', 'MISSING_YEAR', 'Which year does the holiday start?')
        return None
    def make(y, m, d):
        if y is None: return None
        try: return date(y, m, d)
        except ValueError:
            ctx.issue('start_date', 'INVALID_DATE', 'That calendar date does not exist. Enter a valid destination arrival date.', 'error')
            return None
    def departure_context(start):
        prefix = ctx.text[max(0, start-70):start]
        # The most recent event word determines whether a date is departure or arrival.
        events = list(re.finditer(r'\b(fly out|flying out|depart(?:ing|ure)?|leav(?:e|ing)|start(?:ing)?|arriv(?:e|al|ing))\b', prefix))
        return bool(events and events[-1][1].startswith(('fly', 'depart', 'leav')))
    for pattern in (RANGE, MONTH_RANGE):
        for m in pattern.finditer(ctx.text):
            if any(a <= m.start() < b for a, b in consumed): continue
            consumed.append(m.span())
            y = year(m['year']); month = MONTHS[m['month']]
            end_month = MONTHS[m['end_month']] if pattern is MONTH_RANGE and m['end_month'] else month
            first, last = make(y, month, int(m['first'])), make(y, end_month, int(m['last']))
            if departure_context(m.start()):
                ctx.issue('start_date', 'ARRIVAL_DATE_NEEDED', 'This range starts with a departure from India. What date does the holiday arrive in the destination?')
                continue
            if first and last:
                ctx.add('start_date', first.isoformat(), m.span(), 'NORMALIZED')
                if last <= first:
                    ctx.issue('nights', 'INVALID_DATE_RANGE', 'The return date must be after destination arrival.', 'error')
                else:
                    ctx.add('nights', (last-first).days, m.span(), 'INFERRED')
                    ctx.assume('nights', 'The date range is interpreted as destination arrival through return; nights equal the difference between the dates.')
    for pattern in (ISO, NUMERIC, DOTTED, DAY_MONTH, MONTH_DAY):
        for m in pattern.finditer(ctx.text):
            if any(m.start() < b and m.end() > a for a, b in consumed): continue
            consumed.append(m.span())
            month_text = m['month']; month = int(month_text) if month_text.isdigit() else MONTHS[month_text]
            result = make(year(m['year']), month, int(m['day']))
            if pattern in (NUMERIC, DOTTED):
                ctx.assume('start_date', 'Numeric dates use the Indian DD/MM/YYYY convention; review the displayed full date.')
            if not result: continue
            if departure_context(m.start()):
                ctx.metadata.setdefault('departure_dates', []).append(result.isoformat())
                continue
            dates.append((m, result))
    # Explicit arrival -> return dates also define nights, across different months if provided.
    previous = None
    for m, result in sorted(dates, key=lambda item: item[0].start()):
        prefix = ctx.text[max(0, m.start()-24):m.start()]
        returning = bool(re.search(r'\b(?:return(?:ing)?(?: on)?|until|through|to)\s*$', prefix))
        if returning and previous:
            nights = (result-previous).days
            if nights > 0: ctx.add('nights', nights, m.span(), 'INFERRED')
            else: ctx.issue('nights', 'INVALID_DATE_RANGE', 'The return date must follow arrival.', 'error')
        elif returning:
            ctx.metadata['return_date'] = result.isoformat()
        else:
            ctx.add('start_date', result.isoformat(), m.span(), 'NORMALIZED'); previous = result
    if ctx.metadata.get('departure_dates') and not ctx.claims['start_date']:
        ctx.issue('start_date', 'ARRIVAL_DATE_NEEDED', 'You specified a flight departure date. Please give the destination-local arrival date; a flight has not been chosen yet.')
    relative = re.compile(r'\b(tomorrow|today|next (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|this weekend|next week|next month|next ' + MONTH + r')\b')
    for m in relative.finditer(ctx.text):
        if any(m.start() < b and m.end() > a for a, b in consumed): continue
        ref = ctx.reference_date
        if ref is None:
            ctx.issue('start_date', 'REFERENCE_DATE_NEEDED', 'Relative dates need your current local date. Enter an exact destination arrival date.'); continue
        phrase = m[0]; result = None
        if phrase in ('tomorrow', 'today'): result = ref + timedelta(days=phrase == 'tomorrow')
        elif phrase.startswith('next ') and phrase[5:] in [d.lower() for d in calendar.day_name]:
            weekday = [d.lower() for d in calendar.day_name].index(phrase[5:]); result = ref + timedelta(days=(weekday-ref.weekday()) % 7 or 7)
        elif phrase == 'this weekend': result = ref + timedelta(days=(5-ref.weekday()) % 7)
        else:
            ctx.issue('start_date', 'EXACT_DAY_NEEDED', f'Which exact destination arrival day do you mean by "{phrase}"?'); continue
        if departure_context(m.start()):
            ctx.issue('start_date', 'ARRIVAL_DATE_NEEDED', 'Give the destination arrival date rather than the flight departure day.'); continue
        ctx.add('start_date', result.isoformat(), m.span(), 'INFERRED')
        ctx.assume('start_date', f'"{phrase}" is resolved using your local reference date {ref.isoformat()}.')
    if not ctx.claims['start_date'] and not any(i['field'] == 'start_date' for i in ctx.issues):
        # Seasons, festivals and "mid April" name no single arrival day, and a day is never invented.
        for m in FUZZY.finditer(ctx.text):
            if any(m.start() < b and m.end() > a for a, b in consumed): continue
            ctx.issue('start_date', 'EXACT_DAY_NEEDED', f'Which exact destination arrival day do you mean by "{ctx.normalized.source(*m.span())}"?')
            break
