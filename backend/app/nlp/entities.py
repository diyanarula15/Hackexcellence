"""Evidence collection and deterministic slot conflict resolution."""
import json
import re

FIELDS = ('departure', 'country', 'start_date', 'nights', 'adults', 'child_ages', 'budget')


class Context:
    def __init__(self, normalized, catalog, reference_date):
        self.normalized, self.catalog, self.reference_date = normalized, catalog, reference_date
        self.text = normalized.text
        self.claims = {field: [] for field in FIELDS}
        self.issues, self.assumptions, self.metadata, self.entities = [], [], {}, []

    def add(self, field, value, span, status='EXPLICIT', **metadata):
        if value is None: return
        start, end = span
        if re.search(r'\b(?:not|instead of|rather than)\s*$', self.text[max(0, start-20):start]): return
        if field in ('nights', 'adults', 'child_ages', 'budget') and re.search(r'(?:(?:^|[\s₹(])[-\u2212]|\bminus\s*)$', self.text[:start]):
            self.issue(field, 'NEGATIVE_VALUE', 'Negative counts and amounts are not valid. Confirm this value.', 'error')
            return
        source_span = self.normalized.span(start, end)
        claim = {'type': field.upper(), 'value': value, 'status': status,
                 'span': source_span, 'source_text': self.normalized.source(start, end), **metadata}
        self.claims[field].append(claim); self.entities.append(claim)

    def issue(self, field, code, message, severity='clarification', **metadata):
        record = {'field': field, 'code': code, 'message': message, 'severity': severity, **metadata}
        if record not in self.issues: self.issues.append(record)

    def assume(self, field, message):
        self.assumptions.append({'field': field, 'message': message})

    def resolve(self):
        fields, interpretations, evidence = {}, {}, {}
        for field, claims in self.claims.items():
            values = {json.dumps(c['value'], sort_keys=True): c['value'] for c in claims}
            problems = [i for i in self.issues if i['field'] == field and i['severity'] != 'warning']
            status = 'MISSING'
            value = None
            if len(values) > 1:
                status = 'AMBIGUOUS' if len({tuple(c['span']) for c in claims}) == 1 else 'CONFLICT'
                self.issue(field, status, f'You gave conflicting {field.replace("_", " ")} values. Choose one.', candidates=list(values.values()))
            elif values:
                value = next(iter(values.values()))
                status = min((c['status'] for c in claims), key=('EXPLICIT', 'NORMALIZED', 'INFERRED').index)
            if problems:
                status = 'UNSUPPORTED' if any(i['severity'] == 'error' for i in problems) else 'AMBIGUOUS'
                value = None
            fields[field] = value
            interpretations[field] = {'value': value, 'status': status,
                                      'source_text': ' / '.join(dict.fromkeys(c['source_text'] for c in claims)),
                                      'spans': [c['span'] for c in claims]}
            evidence[field] = list(dict.fromkeys(c['source_text'] for c in claims))
            if problems: interpretations[field]['message'] = problems[0]['message']
            if len(values) > 1: interpretations[field]['candidates'] = list(values.values())
        return fields, interpretations, evidence
