"""Bounded English/Indian number vocabulary. Decimal is used for money, never float."""
import re
from decimal import Decimal, InvalidOperation

ONES = dict(zip('zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split(), range(20)))
TENS = dict(zip('twenty thirty forty fifty sixty seventy eighty ninety'.split(), range(20, 100, 10)))
SCALES = {'hundred': 100, 'thousand': 1000, 'thousands': 1000, 'k': 1000, 'grand': 1000,
          'lakh': 100000, 'lakhs': 100000, 'lac': 100000, 'lacs': 100000, 'l': 100000,
          'crore': 10000000, 'crores': 10000000, 'cr': 10000000, 'million': 1000000, 'm': 1000000}
SMALL = r'(?:\d+(?:\.\d+)?|(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:[ -]+(?:one|two|three|four|five|six|seven|eight|nine))?|(?:' + '|'.join(reversed(list(ONES))) + r')|an?)(?!\w)'
SMALL = r'(?:(?:one|two|three|four|five|six|seven|eight|nine|a)[ -]+hundred(?:[ -]+and)?(?:[ -]+(?:' + '|'.join([*TENS, *ONES]) + r')){0,2}(?!\w)|' + SMALL + r')'
_DIGITS = r'\d+(?:,\d{2,3})*(?:\.\d+)?'
_WORDS = r'(?:' + '|'.join([*ONES, *TENS, *SCALES, 'and', 'a', 'half', 'quarter']) + r')\b'
_SCALE_AHEAD = r'(?=[ ]*(?:' + '|'.join(SCALES) + r')\b)'
# An amount is words/digits joined by spaces, with two guards: a digit may not follow a bare digit
# ("2027 3 lakh") and may only follow a word when a scale comes next ("3 lakh 6 nights" is not 300006).
# A bare dash between amounts ("3 lakh - 4 lakh") is a range, never a sum.
MONEY = r'(?>' + _DIGITS + r'|' + _WORDS + r')(?:(?:[ ]+|(?<=\d)(?=[a-z])|-(?=[a-z]))' + _WORDS + r'|(?<=[a-z])[ ]+' + _DIGITS + _SCALE_AHEAD + r')*'


def number(text):
    text = text.strip().lower().replace('-', ' ')
    if ',' in text:
        if not (re.fullmatch(r'\d{1,3}(?:,\d{3})+(?:\.\d+)?', text)
                or re.fullmatch(r'\d{1,2}(?:,\d{2})*,\d{3}(?:\.\d+)?', text)):
            return None
        text = text.replace(',', '')
    try:
        return Decimal(text)
    except InvalidOperation:
        pass
    words = re.findall(r'\d+(?:\.\d+)?|[a-z]+', text)
    if not words: return None
    current, total, last_scale = Decimal(0), Decimal(0), None
    for word in words:
        if word == 'and': continue
        if word in ('a', 'an'): current += 1
        elif word in ONES: current += ONES[word]
        elif word in TENS: current += TENS[word]
        elif word in ('half', 'quarter'):
            # "one and a half" has an article, not an extra whole unit.
            if words.count('a') and current: current -= 1
            current += Decimal('0.5') if word == 'half' else Decimal('0.25')
        elif word in SCALES:
            if word == 'hundred': current = (current or 1) * 100
            else:
                # "3 lakh 4 lakh" is two amounts, not 7 lakh: scales must strictly decrease.
                if last_scale is not None and SCALES[word] >= last_scale: return None
                total += (current or 1) * SCALES[word]; current = Decimal(0); last_scale = SCALES[word]
        elif re.fullmatch(r'\d+(?:\.\d+)?', word): current += Decimal(word)
        else: return None
    return total + current


def integer(text):
    value = number(text)
    return int(value) if value is not None and value == value.to_integral_value() else None
