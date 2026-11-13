"""Reuse existing request rules, and Pydantic for every complete interpretation."""
from pydantic import ValidationError
from app.models import TripRequest
from app.rules.request import check_request

API = {'departure_airport': 'departure', 'destination_country': 'country', 'start_date': 'start_date',
       'nights': 'nights', 'adults': 'adults', 'children_ages': 'child_ages', 'budget': 'budget'}
RULE_FIELDS = {'R-REQ-1': ['departure'], 'R-REQ-2': ['country'], 'R-REQ-3': ['nights'],
               'R-REQ-4': ['start_date'], 'R-REQ-5': ['start_date','nights'], 'R-REQ-6': ['adults'],
               'R-REQ-7': ['child_ages'], 'R-REQ-8': ['budget']}


def validate(ctx, fields, interpretations):
    raw = {key: fields[value] for key, value in API.items()}
    for violation in check_request(raw, ctx.catalog):
        relevant = RULE_FIELDS.get(violation.rule, [])
        if not relevant or any(fields[field] is None for field in relevant): continue
        # An arrival outside the window does not make an independently valid night count unknown.
        for field in (['start_date'] if violation.rule == 'R-REQ-5' else relevant):
            ctx.issue(field, violation.rule, violation.message, 'error')
            interpretations[field].update(status='UNSUPPORTED', message=violation.message)
    window = ctx.catalog.catalog.destinations['rules']['data_window']
    if fields['start_date'] is not None and fields['start_date'] > window['last_departure'] and not any(
            i['field'] == 'start_date' and i['severity'] == 'error' for i in ctx.issues):
        message = f"The destination arrival must fall within {window['first_night']} to {window['last_departure']}."
        ctx.issue('start_date', 'OUTSIDE_DATE_WINDOW', message, 'error')
        interpretations['start_date'].update(status='UNSUPPORTED', message=message)
    if fields['budget'] is not None and fields['budget'] <= 0:
        ctx.issue('budget', 'POSITIVE_BUDGET_NEEDED', 'Enter a positive whole INR budget.', 'error')
        interpretations['budget']['status'] = 'UNSUPPORTED'
    if fields['adults'] is not None:
        cap = max(f['seats_left'] for f in ctx.catalog.catalog.flights)
        party = fields['adults'] + len(fields['child_ages'] or [])
        if party > cap:
            message = f'At most {cap} travelers can be accommodated; every traveler needs a flight seat.'
            ctx.issue('adults', 'INVALID_TRIP_REQUEST', message, 'error')
            interpretations['adults'].update(status='UNSUPPORTED', message=message)
    if all(value is not None for value in fields.values()) and not any(i['severity'] != 'warning' for i in ctx.issues):
        try:
            TripRequest.model_validate(raw, context={'catalog': ctx.catalog})
        except ValidationError as exc:
            for error in exc.errors():
                field = API.get(str(error['loc'][0]), 'adults') if error['loc'] else 'adults'
                message = error['msg'].removeprefix('Value error, ')
                ctx.issue(field, 'INVALID_TRIP_REQUEST', message, 'error')
                interpretations[field].update(status='UNSUPPORTED', message=message)
