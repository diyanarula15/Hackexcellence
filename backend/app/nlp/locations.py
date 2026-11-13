"""Country/city/airport lexicon is derived from the active catalog; aliases are gated by it."""
import re

ALIASES = {'bangalore': 'Bengaluru', 'banglore': 'Bengaluru', 'bombay': 'Mumbai', 'new delhi': 'Delhi',
           'madras': 'Chennai', 'uae': 'United Arab Emirates', 'u.a.e.': 'United Arab Emirates',
           'emirates': 'United Arab Emirates', 'viet nam': 'Vietnam', 'saigon': 'Ho Chi Minh City',
           'kl': 'Kuala Lumpur', 'japanese': 'Japan'}
ORIGIN = r'\b(?:(?:from|leaving|departing(?: from)?|flying out of|fly out of|departure(?: city)?(?: is|:)?|out of|(?:live|living|based) (?:in|at))\s+|ex(?!-?(?:wife|husband|partner|boss|colleague))[- ])(?:an?\s+)?'
DEST = r'\b(?:to|visit(?:ing)?|destination(?: is|:)?|holiday in|trip in|vacation in|travel(?:ing)? (?:to|in))\s+'
# Well-known places the catalog does not serve; naming one must be surfaced, not silently dropped.
UNSERVED = ('maldives', 'goa', 'kerala', 'kashmir', 'ladakh', 'manali', 'shimla', 'sri lanka', 'nepal', 'bhutan', 'mauritius', 'seychelles',
            'turkey', 'egypt', 'europe', 'switzerland', 'paris', 'london', 'france', 'italy', 'germany', 'spain', 'greece', 'usa', 'america',
            'australia', 'new zealand', 'canada', 'hong kong', 'china', 'south korea', 'korea', 'cambodia', 'philippines', 'qatar', 'oman')


def extract(ctx):
    countries = ctx.catalog.catalog.destinations['countries']
    departures = ctx.catalog.catalog.destinations['departure_cities']
    lexicon = {}
    def add(alias, kind, value, is_city=False):
        lexicon.setdefault(alias.casefold(), []).append((kind, value, is_city))
    for d in departures:
        add(d['city'], 'departure', d['airport']); add(d['airport'], 'departure', d['airport'])
    names = {}
    for country in countries:
        names[country['name']] = ('country', country['name'], False)
        add(country['name'], 'country', country['name'])
        for city in country['cities']:
            add(city['name'], 'country', country['name'], True)
            names[city['name']] = ('country', country['name'], True)
    for d in departures: names[d['city']] = ('departure', d['airport'], False)
    for alias, target in ALIASES.items():
        if target in names: add(alias, *names[target])
    for country in countries:
        for m in re.finditer(r'\b' + re.escape(country['code'].lower()) + r'\b', ctx.text):
            if re.search(DEST + r'$', ctx.text[max(0, m.start()-40):m.start()]):
                ctx.add('country', country['name'], m.span(), 'NORMALIZED')
    # Longest phrases take precedence over substrings such as Delhi inside New Delhi.
    pattern = re.compile(r'(?<!\w)(?:' + '|'.join(re.escape(k) for k in sorted(lexicon, key=len, reverse=True)) + r')(?!\w)')
    hits = list(pattern.finditer(ctx.text))
    used = []
    for m in hits:
        prefix = ctx.text[max(0, m.start()-45):m.start()]
        if re.search(r'\b(?:not|instead of|rather than)\s+$', prefix): continue
        if re.search(r'\b(?:via|transit(?:ing)?(?: through)?)\s+$', prefix):
            ctx.issue('country', 'TRANSIT_NOT_DESTINATION', f'{ctx.normalized.source(*m.span())} is a transit mention, not the holiday destination.', 'warning'); continue
        matches = lexicon[m[0]]
        origin_role = bool(re.search(ORIGIN + '$', prefix))
        kinds = {kind for kind, _, _ in matches}
        if origin_role and 'departure' not in kinds:
            ctx.issue('departure', 'UNSUPPORTED_DEPARTURE', f'{ctx.normalized.source(*m.span())} is not an available departure city.', 'error')
            used.append(m.span()); continue
        for field, value, is_city in dict.fromkeys(matches):
            if field == 'departure':
                if re.search(DEST + '$', prefix):
                    ctx.issue('country', 'UNSUPPORTED_DESTINATION', f'{m[0]} is not a supported destination in this catalog.', 'error')
                else: ctx.add(field, value, m.span(), 'NORMALIZED')
            else:
                ctx.add(field, value, m.span(), 'NORMALIZED' if is_city or m[0] != value.lower() else 'EXPLICIT')
                if is_city:
                    ctx.metadata.setdefault('preferred_cities', []).append(ctx.normalized.source(*m.span()))
            used.append(m.span())
    # Explicit location cues with no recognized lexicon hit must not silently disappear.
    flagged = set()
    for cue, field in ((ORIGIN, 'departure'), (DEST, 'country')):
        for match in re.finditer(cue, ctx.text):
            start = match.end()
            if any(a <= start < b or start == a for a, b in used): continue
            tail = ctx.text[start:]
            word = re.match(r'([a-z][a-z ]{0,45}?)(?=\s+(?:to|from|for|on|starting|with|budget|and|visiting)\b|[,.;!?\d]|$)', tail)
            if word and word[1].strip() not in ('a trip', 'a holiday', 'a vacation', 'my family'):
                name = word[1].strip()
                if not re.match(r'^(?:april|apr|tomorrow|next|travel|go|plan|find|book|visit|\d)', name):
                    alternatives = [d['city'] for d in departures] if field == 'departure' else [c['name'] for c in countries]
                    flagged.add(name)
                    ctx.issue(field, 'UNSUPPORTED_LOCATION', f'{name.title()} is not available as a {"departure" if field == "departure" else "destination"} in the current catalog.', 'error', candidates=alternatives)
    for m in re.finditer(r'(?<!\w)(?:' + '|'.join(UNSERVED) + r')(?!\w)', ctx.text):
        prefix = ctx.text[max(0, m.start()-45):m.start()]
        if m[0] in lexicon or any(m[0] in name for name in flagged) or any(a <= m.start() < b for a, b in used): continue
        if re.search(ORIGIN + r'$|\b(?:not|instead of|rather than|via|transit(?:ing)?(?: through)?)\s+$', prefix): continue
        # With a supported country present the extra place is only a warning; otherwise nothing would be filled.
        severity = 'warning' if ctx.claims['country'] else 'error'
        ctx.issue('country', 'UNSUPPORTED_LOCATION', f'{m[0].title()} is not available as a destination in the current catalog.', severity,
                  **({} if severity == 'warning' else {'candidates': [c['name'] for c in countries]}))
    if ctx.metadata.get('preferred_cities'):
        ctx.issue('country', 'CITY_PREFERENCE_ONLY', 'City mentions identify the destination country. They are preferences, not a locked route; the planner still chooses the cities.', 'warning')
