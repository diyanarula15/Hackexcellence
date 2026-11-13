"""Unicode normalization with a reversible character-span map into the original request."""
import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizedText:
    original: str
    text: str
    offsets: tuple[tuple[int, int], ...]

    def span(self, start, end):
        return [self.offsets[start][0], self.offsets[end - 1][1]] if end > start else [0, 0]

    def source(self, start, end):
        a, b = self.span(start, end)
        return self.original[a:b]


def normalize(text: str) -> NormalizedText:
    chars, offsets = [], []
    for i, char in enumerate(text):
        for part in unicodedata.normalize('NFKC', char).casefold():
            if ord(part) in range(0x2010, 0x2016): part = '-'
            if ord(part) in (0x2018, 0x2019): part = "'"
            if part.isspace(): part = ' '
            chars.append(part); offsets.append((i, i + 1))
    value = ''.join(chars)
    # Safe whole-token corrections only. Keep their original source interval.
    rules = [(r'\s+', ' '), (r'\b(\d+)(?:st|nd|rd|th)\b', lambda m: m[1]),
             (r'\bnites?\b', 'nights'), (r'\bbanglore\b', 'bangalore'),
             (r'\byrs?\b', 'years'), (r'(?<=\d)yrs?\b', ' years'), (r'\b(?:adlts?|adluts?)\b', 'adults'), (r'\btravelling\b', 'traveling')]
    for pattern, replacement in rules:
        out, mapped, cursor = [], [], 0
        for match in re.finditer(pattern, value):
            out.append(value[cursor:match.start()]); mapped.extend(offsets[cursor:match.start()])
            new = replacement(match) if callable(replacement) else replacement
            interval = (offsets[match.start()][0], offsets[match.end() - 1][1])
            out.append(new); mapped.extend([interval] * len(new)); cursor = match.end()
        out.append(value[cursor:]); mapped.extend(offsets[cursor:])
        value, offsets = ''.join(out), mapped
    return NormalizedText(text, value, tuple(offsets))


def tokenize(normalized):
    return [{'text': normalized.source(*m.span()), 'normalized': m[0],
             'span': normalized.span(*m.span()), 'category': 'NUMBER' if m[0][0].isdigit() else 'WORD' if m[0].isalpha() else 'PUNCTUATION'}
            for m in re.finditer(r'\d[\d,]*(?:\.\d+)?|[^\W\d_]+|[^\s]', normalized.text)]
