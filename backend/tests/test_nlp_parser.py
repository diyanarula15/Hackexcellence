"""Representative corpus and adversarial checks for offline, explainable seven-slot parsing."""
from datetime import date
import copy
import json
import time

import pytest
from app.catalog.load import build_loaded, load_catalog, load_raw
from app.nlp.normalize import normalize, tokenize
from app.nlp.numbers import integer, number
from app.nlp.parser import parse_trip_request

CATALOG = load_catalog()

def parse(text, ref=None, catalog=CATALOG):
    return parse_trip_request(text, catalog, ref)


@pytest.mark.parametrize('text,expected', [
    ('6 nights in Japan from Bangalore for 2 adults and a 6-year-old, 10 April 2027, budget 3.5 lakh.', ('BLR','Japan','2027-04-10',6,2,[6],350000)),
    ('Delhi to UAE, 5 nights, 3 adults, start 8 April 2027, maximum ₹250000.', ('DEL','United Arab Emirates','2027-04-08',5,3,[],250000)),
    ('We are a couple traveling from Mumbai to Singapore for 4 nights starting 12 April 2027, budget 2L.', ('BOM','Singapore','2027-04-12',4,2,[],200000)),
    ('Japan 10–16 April 2027, leaving Bengaluru, me and my wife, our daughter is six, budget ₹350k.', ('BLR','Japan','2027-04-10',6,2,[6],350000)),
    ('Plan a 6-night Japan holiday from Bangalore starting 10 April 2027 for me, my wife and our 6-year-old daughter. Budget is 3.5 lakh.', ('BLR','Japan','2027-04-10',6,2,[6],350000)),
])
def test_complete_corpus(text, expected):
    r=parse(text)
    assert tuple(r['fields'].values()) == expected
    assert r['status'] == 'READY' and r['can_submit'] is True


@pytest.mark.parametrize('text,field,expected', [
    ('Japan from Banglore', 'departure','BLR'), ('Bombay to Japan','departure','BOM'),
    ('Leaving New Delhi, visiting Dubai','country','United Arab Emirates'),
    ('Flying out of Chennai for Thailand','departure','MAA'), ('BLR → Japan','country','Japan'),
    ('I want to travel to Japan from London','country','Japan'),
    ('I want to visit Bali','country','Indonesia'), ('Japan, especially Tokyo and Kyoto','country','Japan'),
    ('two couples','adults',4), ('my parents and I','adults',3),
    ('my husband and I with our 6-year-old son','child_ages',[6]),
    ('me, my wife and our twins aged 7','child_ages',[7,7]),
    ('three adults, two children aged five and eight','child_ages',[5,8]),
    ('My daughter is six','child_ages',[6]), ('two adults and a 0-year-old','child_ages',[0]),
    ('two adults and a 6 y/o','child_ages',[6]), ('two adults and a six years old child','child_ages',[6]),
    ('Start on 10th Apr','start_date','2027-04-10'), ('April 10, 2027','start_date','2027-04-10'),
    ('10/04/2027','start_date','2027-04-10'), ('2027-04-10','start_date','2027-04-10'),
    ('April 10 through April 16','nights',6), ('10 April to 16 April 2027','nights',6),
    ('₹3,50,000','budget',350000), ('350000 rupees','budget',350000),
    ('3L','budget',300000), ('350k','budget',350000), ('Budget three lakh fifty thousand','budget',350000),
    ('2 lakh 50 thousand','budget',250000), ('Around ₹2,75,000','budget',275000),
    ('INR 350000','budget',350000), ('₹50k per person for three adults','budget',150000),
    ('Budget ₹2 lakh, maximum ₹3 lakh','budget',300000), ('Under 3.5 lakh','budget',350000),
])
def test_slot_patterns(text,field,expected):
    assert parse(text)['fields'][field] == expected


@pytest.mark.parametrize('text,field', [
    ('Plan a Japan trip for my family','adults'), ('Trip for four people','adults'),
    ('2 adults and 2 kids','child_ages'), ('two kids aged 5, 8 and 10','child_ages'),
    ('2 adults, three kids aged 5 and 8','child_ages'), ('4 travelers, 2 adults and 3 children aged 5,8,10','adults'),
    ('two adults and our toddler','child_ages'), ('18-month-old baby','child_ages'),
    ('two adults and an 18-year-old child','child_ages'), ('no children and a six-year-old','child_ages'),
    ('Trip for six days','nights'), ('travel for a week','nights'),
    ('5 nights, returning after 7 nights','nights'), ('Start 10 April, arrive 12 April, six nights','start_date'),
    ('Leaving Mumbai from Delhi','departure'), ('From London to Japan','departure'),
    ('Plan a France trip from Bengaluru','country'), ('Japan or Thailand from BLR','country'),
    ('Fly out of Bangalore on 9 April','start_date'), ('Budget 2 lakh or 3 lakh','budget'),
    ('Budget USD 3000','budget'), ('₹50k per person','budget'), ('Budget ₹-350000','budget'),
    ('31 April 2027','start_date'), ('29 February 2027','start_date'),
])
def test_uncertain_or_invalid_values_are_not_chosen(text,field):
    r=parse(text)
    assert r['fields'][field] is None
    assert not r['can_submit']
    assert any(i['field']==field for i in r['issues'])


def test_invalid_catalog_values_keep_evidence_but_cannot_be_applied():
    r=parse('Delhi to Japan 18 April 2027 for 6 nights, 2 adults, budget ₹300000')
    assert r['fields']['start_date']=='2027-04-18'
    assert r['interpretations']['start_date']['status']=='UNSUPPORTED'
    assert r['interpretations']['nights']['status']=='EXPLICIT'
    assert any(i['code']=='R-REQ-5' for i in r['issues'])
    assert not r['can_submit']


def test_pydantic_party_cap_and_budget_are_used():
    r=parse('Chennai to Vietnam, April 1 2027, 10 nights, 9 adults and a 1-year-old, 9 lakh')
    assert not r['can_submit']
    assert any(i['code']=='INVALID_TRIP_REQUEST' and 'travelers' in i['message'] for i in r['issues'])
    assert not parse('Chennai to Japan, April 1 2027, 6 nights, 2 adults, budget 0')['can_submit']


def test_relative_dates_have_explicit_context_and_no_wall_clock_dependency():
    assert parse('tomorrow')['fields']['start_date'] is None
    assert parse('tomorrow',date(2027,4,9))['fields']['start_date']=='2027-04-10'
    assert parse('next Friday',date(2027,4,1))['fields']['start_date']=='2027-04-02'
    assert parse('this weekend',date(2027,4,1))['fields']['start_date']=='2027-04-03'
    assert parse('next month',date(2027,4,1))['fields']['start_date'] is None
    assert any(i['code']=='R-REQ-4' for i in parse('tomorrow',date(2026,11,13))['issues'])


def test_numeric_dates_are_dd_mm_and_disclosed():
    r=parse('04/05/2027')
    assert r['fields']['start_date']=='2027-05-04'
    assert any('DD/MM/YYYY' in a['message'] for a in r['assumptions'])


def test_normalization_preserves_original_character_spans():
    text='  JAPAN\t from Banglore; six nites, 10th Apr 2027, two adults and a 6‑year‑old, ₹３５００００ '
    r=parse(text)
    for entity in r['entities']:
        a,b=entity['span']; assert text[a:b]==entity['source_text']
    for token in r['tokens']:
        a,b=token['span']; assert text[a:b]==token['text']
    assert r['fields']['budget']==350000 and r['fields']['departure']=='BLR'
    assert normalize(text).text == normalize(text).text


def test_location_aliases_cannot_resolve_to_removed_catalog_entries():
    raw=load_raw();raw['destinations']['countries']=[c for c in raw['destinations']['countries'] if c['code']!='AE']
    # No build_loaded needed: indexes for other entities are unchanged; lexicon uses configured destinations.
    cat=copy.deepcopy(CATALOG);cat.catalog.destinations['countries'][:]=raw['destinations']['countries']
    assert parse('Visit Dubai',catalog=cat)['fields']['country'] is None
    assert parse('Japan from bombastic')['fields']['departure'] is None


def test_intent_is_not_booking_or_weather_generation():
    for text in ['What is the weather in Tokyo?', 'Tell me about Tokyo.', 'Show my reservation.', 'Cancel my booking.']:
        r=parse(text);assert r['status']=='UNSUPPORTED_INTENT' and not r['can_submit']
        assert all(v is None for v in r['fields'].values())


def test_targets_and_per_person_calculations_are_disclosed():
    r=parse('around 3 lakh');assert r['metadata']['budget_semantics']=='approximate' and r['assumptions']
    r=parse('₹50000 per person for 2 adults and a 6-year-old')
    assert r['fields']['budget']==150000 and any('× 3' in a['message'] for a in r['assumptions'])


def test_results_are_deterministic_and_catalog_is_not_mutated():
    before=copy.deepcopy(CATALOG.catalog)
    text='Japan 10-16 April 2027, Delhi, two couples, budget 9L'
    assert json.dumps(parse(text),sort_keys=True)==json.dumps(parse(text),sort_keys=True)
    assert CATALOG.catalog==before


@pytest.mark.parametrize('text,expected',[('thirty five',35),('two hundred',200),('3.5 lakh',350000),('2 lakh 50 thousand',250000),('3,50,000',350000)])
def test_context_numeric_utility(text,expected):
    assert integer(text)==expected


def test_bounded_long_input_has_no_pathological_regex_backtracking():
    start=time.monotonic();r=parse('budget '+('1'*1900));assert time.monotonic()-start<2
    assert r['fields']['adults'] is None


def test_age_context_stops_before_the_next_slot():
    r=parse('2 adults and children aged 6 and 9, 5 nights, budget 3 lakh')
    assert r['fields']['child_ages']==[6,9]
    assert r['fields']['nights']==5
    entity=next(e for e in r['entities'] if e['type']=='CHILD_AGES')
    assert '5' not in entity['source_text']


@pytest.mark.parametrize('text,field',[('-6 nights','nights'),('-2 adults','adults'),('budget -3 lakh','budget'),('-6-year-old child','child_ages')])
def test_negative_values_do_not_turn_into_positive_values(text,field):
    r=parse(text)
    assert r['fields'][field] is None
    assert r['status']=='NEEDS_CORRECTION'


def test_partial_party_is_still_checked_for_catalog_capacity():
    r=parse('two hundred adults')
    assert r['fields']['adults']==200
    assert r['interpretations']['adults']['status']=='UNSUPPORTED'
    assert r['status']=='NEEDS_CORRECTION'


def test_date_range_keeps_the_explicit_second_month():
    r=parse('Japan from Delhi, April 10 through May 16 2027, two adults, budget 3 lakh')
    assert r['fields']['start_date']=='2027-04-10'
    assert r['fields']['nights']==36
    assert not r['can_submit']
    r=parse('April 28 through May 4 2027')
    assert r['fields']['nights']==6
    assert r['fields']['start_date']=='2027-04-28'


def test_partial_date_is_checked_against_the_end_of_the_catalog_window():
    r=parse('Start 10 April 2028')
    assert r['interpretations']['start_date']['status']=='UNSUPPORTED'
    assert any(i['code']=='OUTSIDE_DATE_WINDOW' for i in r['issues'])
    r=parse('Start 10 April 1999')
    assert r['fields']['start_date']=='1999-04-10'
    assert r['interpretations']['start_date']['status']=='UNSUPPORTED'


def test_explicit_duration_has_priority_over_a_compatible_range_inference():
    r=parse('Japan April 10 through April 16 2027 for 6 nights')
    assert r['fields']['nights']==6
    assert r['interpretations']['nights']['status']=='EXPLICIT'


def codes(r, field):
    return {i['code'] for i in r['issues'] if i['field'] == field}


@pytest.mark.parametrize('text', ['Japan from Delhi 5N/6D, 10 April 2027, 2 adults, 3 lakh', 'Japan from Delhi 6D/5N, 10 April 2027, 2 adults, 3 lakh'])
def test_compact_night_day_notation_gives_nights(text):
    r = parse(text)
    assert r['fields']['nights'] == 5 and r['status'] == 'READY'


def test_inconsistent_compact_notation_is_a_conflict():
    assert 'DAY_NIGHT_CONFLICT' in codes(parse('Japan from Delhi 5N/9D, 10 April 2027, 2 adults, 3 lakh'), 'nights')


@pytest.mark.parametrize('phrase', ['a fortnight', '2 weeks', 'a week'])
def test_week_style_durations_ask_for_nights(phrase):
    r = parse(f'Japan from Delhi for {phrase}, 10 April 2027, 2 adults, 3 lakh')
    assert r['fields']['nights'] is None and 'DAYS_NOT_NIGHTS' in codes(r, 'nights')


def test_repeated_equal_night_counts_per_city_are_not_collapsed():
    r = parse('Japan from Delhi 3 nights Tokyo and 3 nights Kyoto 10 April 2027, 2 adults, 3 lakh')
    assert r['fields']['nights'] is None and 'MULTIPLE_NIGHT_COUNTS' in codes(r, 'nights')


def test_night_ranges_are_not_reduced_to_the_upper_bound():
    r = parse('Japan from Delhi 10 April 2027 4-6 nights, 2 adults, 3 lakh')
    assert r['fields']['nights'] is None and 'NIGHTS_RANGE' in codes(r, 'nights')


def test_family_total_minus_aged_children_gives_adults():
    r = parse('Japan from Delhi 6 nights, 10 April 2027, family of 4 with 2 kids aged 5 and 8, 3 lakh')
    assert r['fields']['adults'] == 2 and r['fields']['child_ages'] == [5, 8] and r['fields']['budget'] == 300000
    assert r['interpretations']['adults']['status'] == 'INFERRED' and r['status'] == 'READY'


@pytest.mark.parametrize('kids', ['1 child (7)', '2 kids (4 and 9)', 'kids 4,9'])
def test_bracketed_and_comma_child_ages(kids):
    r = parse(f'Japan from Delhi 6 nights, 10 April 2027, 2 adults {kids}, 3 lakh')
    assert r['fields']['child_ages'] in ([7], [4, 9]) and r['fields']['budget'] == 300000


def test_age_list_does_not_swallow_the_budget_into_an_invalid_amount():
    r = parse('2 adults, kids aged 5 and 8, 3 lakh')
    assert r['fields']['budget'] == 300000 and 'INVALID_INR_AMOUNT' not in codes(r, 'budget')


def test_additional_adult_relatives_force_a_party_clarification():
    r = parse('Japan from Delhi 6 nights 10 April 2027 2 adults and 1 senior parent, 3 lakh')
    assert r['fields']['adults'] is None and 'EXTRA_TRAVELERS_MENTIONED' in codes(r, 'adults')
    assert parse('2 adults including my parents')['fields']['adults'] == 2


def test_husband_and_wife_is_a_couple():
    assert parse('husband wife and 2 kids aged 5 and 8')['fields']['adults'] == 2


def test_budget_range_with_dash_is_not_summed():
    r = parse('Japan from Delhi 6 nights 10 April 2027 2 adults 3 lakh - 4 lakh')
    assert r['fields']['budget'] is None and 'CONFLICT' in codes(r, 'budget') and 'NEGATIVE_VALUE' not in codes(r, 'budget')


def test_two_amounts_never_merge_across_a_date_or_nights():
    assert parse('Japan from Delhi 10 April 2027 6 nights 2 adults 3 lakh')['fields']['budget'] == 300000
    assert parse('6 nights 10 April 2027 3 lakh 6 nights')['fields']['budget'] == 300000


def test_scale_suffix_without_a_space_and_bare_grouped_amounts():
    assert parse('budget 2lakh')['fields']['budget'] == 200000
    r = parse('Japan from Delhi 6 nights, 10 April 2027, 2 adults, 1,50,000')
    assert r['fields']['budget'] == 150000 and r['interpretations']['budget']['status'] == 'INFERRED' and r['assumptions']
    assert parse('2 adults 1,500')['fields']['budget'] is None


@pytest.mark.parametrize('text', ['10-04-2027', '10.04.2027'])
def test_dashed_and_dotted_numeric_dates_follow_dd_mm_yyyy(text):
    r = parse(text)
    assert r['fields']['start_date'] == '2027-04-10' and any('DD/MM/YYYY' in a['message'] for a in r['assumptions'])


@pytest.mark.parametrize('text', ['mid April 2027', 'first week of April 2027', 'around Diwali', 'in April 2027'])
def test_vague_dates_ask_for_an_exact_day(text):
    r = parse(f'Japan from Delhi 6 nights, {text}, 2 adults, 3 lakh')
    assert r['fields']['start_date'] is None and 'EXACT_DAY_NEEDED' in codes(r, 'start_date')


def test_city_names_ending_in_to_are_not_return_date_cues():
    r = parse('Japan from Delhi 3 nights Kyoto 10 April 2027 2 adults 3 lakh')
    assert r['fields']['start_date'] == '2027-04-10' and r['fields']['nights'] == 3


def test_unknown_home_city_is_reported_not_dropped():
    r = parse('Japan 6 nights, 10 April 2027, 2 adults, 3 lakh, we live in Pune')
    assert r['fields']['departure'] is None and 'UNSUPPORTED_LOCATION' in codes(r, 'departure')
    assert parse('ex-Mumbai to Japan')['fields']['departure'] == 'BOM'


@pytest.mark.parametrize('place', ['Maldives', 'Goa'])
def test_bare_unsupported_destination_is_reported(place):
    r = parse(f'{place} 5 nights from Mumbai 10 April 2027 2 adults 3 lakh')
    assert r['fields']['country'] is None and 'UNSUPPORTED_LOCATION' in codes(r, 'country')
    assert parse('Japan from Goa')['fields']['country'] == 'Japan'


def test_extra_unsupported_place_beside_a_supported_country_is_a_warning():
    r = parse('Japan and Maldives from Delhi 6 nights 10 April 2027 2 adults 3 lakh')
    assert r['fields']['country'] == 'Japan' and r['status'] == 'READY'
    assert any(i['code'] == 'UNSUPPORTED_LOCATION' and i['severity'] == 'warning' for i in r['issues'])


def test_common_typos_in_age_and_adult_words():
    r = parse('Japan from Delhi 4 nites, 10 April 2027, 2 adlts and a 5yr old, 3 lakh')
    assert r['fields']['adults'] == 2 and r['fields']['child_ages'] == [5]


def test_spaced_dash_before_a_count_is_not_a_negative_sign():
    assert parse('Japan - 6 nights')['fields']['nights'] == 6


def test_bare_couple_is_two_adults_but_a_couple_of_days_is_not():
    r = parse('Bali 6 nights from Delhi 12/04/2027, couple, budget 2L')
    assert r['fields']['adults'] == 2 and r['fields']['child_ages'] == []
    assert parse('Japan for a couple of days, 2 adults')['fields']['adults'] == 2
    assert parse('Japan for a couple of days from Delhi')['fields']['adults'] is None
