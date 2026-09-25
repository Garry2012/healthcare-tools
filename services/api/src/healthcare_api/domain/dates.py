"""Relative date expressions, resolved in the facility's timezone (openapi RULE on search).

The model never does calendar arithmetic; it forwards what the caller said. Day-part
words ("evening", "ಸಂಜೆ", "shaam") come from the tenant's DAY_PART lexicon; the words
for today/tomorrow/weekdays are language data kept here so a new tenant gets them free.

Rules:
- explicit `dateFrom`/`dateTo` always win;
- "today"/"now", "tomorrow", "day after tomorrow" in English, Kannada and Hindi (native
  script or romanised);
- a bare weekday is its next occurrence, today included;
- "next <weekday>" is the first occurrence strictly after today;
- "this week" is today..Sunday, "next week" is next Monday..Sunday;
- a day-part word alone means today.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

from .text import contains_phrase, normalise, tokens


def _forms(*words: str) -> frozenset[str]:
    return frozenset(normalise(w) for w in words)


_TODAY = _forms("today", "now", "right now", "abhi", "aaj", "ivattu", "indu", "iga",
                "ಇಂದು", "ಇವತ್ತು", "ಈಗ", "ಈಗಲೇ", "आज", "अभी")
_TOMORROW = _forms("tomorrow", "tmrw", "tommorow", "kal", "naale", "nale",
                   "ನಾಳೆ", "कल")
_DAY_AFTER = _forms("day after tomorrow", "parso", "parson", "naadiddu", "nadiddu",
                    "ನಾಡಿದ್ದು", "परसों")
_NEXT = _forms("next", "coming", "agle", "agla", "agli", "mundina", "ಮುಂದಿನ", "अगले", "अगला")
_THIS = _forms("this", "is", "ee", "ಈ", "इस")
_WEEK = _forms("week", "hafte", "hafta", "vaara", "ವಾರ", "हफ्ते", "सप्ताह")

_WEEKDAYS: tuple[frozenset[str], ...] = (
    _forms("monday", "mon", "somvar", "somavara", "somavar", "ಸೋಮವಾರ", "सोमवार"),
    _forms("tuesday", "tue", "tues", "mangalvar", "mangalavara", "mangalavar",
           "ಮಂಗಳವಾರ", "मंगलवार"),
    _forms("wednesday", "wed", "budhvar", "budhavara", "budhavar", "ಬುಧವಾರ", "बुधवार"),
    _forms("thursday", "thu", "thurs", "guruvar", "guruvara", "brihaspativar",
           "ಗುರುವಾರ", "गुरुवार"),
    _forms("friday", "fri", "shukravar", "shukravara", "ಶುಕ್ರವಾರ", "शुक्रवार"),
    _forms("saturday", "sat", "shanivar", "shanivara", "ಶನಿವಾರ", "शनिवार"),
    _forms("sunday", "sun", "ravivar", "bhanuvar", "bhanuvara", "ಭಾನುವಾರ", "रविवार"),
)


@dataclass(frozen=True, slots=True)
class WhenResult:
    date_from: date
    date_to: date
    day_part: str | None
    resolved: bool  # False: an expression was given and nothing in it was understood


def _day_part(text: str, day_parts: Iterable[tuple[str, str]]) -> str | None:
    # Longest term first so "early morning" beats "morning".
    for term, part in sorted(day_parts, key=lambda p: -len(p[0])):
        if contains_phrase(text, term):
            return part
    return None


def _weekday(words: list[str], today: date) -> date | None:
    for i, word in enumerate(words):
        for index, forms in enumerate(_WEEKDAYS):
            if word not in forms:
                continue
            ahead = (index - today.weekday()) % 7
            if i > 0 and words[i - 1] in _NEXT:
                ahead = ahead or 7
            return today + timedelta(days=ahead)
    return None


def _dates(text: str, today: date) -> tuple[date, date] | None:
    words = tokens(text)
    if any(contains_phrase(text, p) for p in _DAY_AFTER):
        return today + timedelta(days=2), today + timedelta(days=2)
    for i, word in enumerate(words):
        if word in _WEEK and i > 0:
            if words[i - 1] in _NEXT:
                monday = today + timedelta(days=7 - today.weekday())
                return monday, monday + timedelta(days=6)
            if words[i - 1] in _THIS:
                return today, today + timedelta(days=6 - today.weekday())
    if any(contains_phrase(text, p) for p in _TOMORROW):
        return today + timedelta(days=1), today + timedelta(days=1)
    day = _weekday(words, today)
    if day is not None:
        return day, day
    if any(contains_phrase(text, p) for p in _TODAY):
        return today, today
    return None


def resolve_when(
    *,
    today: date,
    expression: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    day_part: str | None = None,
    utterance: str | None = None,
    day_parts: Iterable[tuple[str, str]] = (),
    default_days: int = 7,
) -> WhenResult:
    """`day_parts` are (normalised term, DayPart) pairs from the approved lexicon."""
    day_parts = list(day_parts)
    part = None if day_part in (None, "ANY") else day_part
    if date_from is not None or date_to is not None:
        start = date_from or date_to
        end = date_to or start
        assert start is not None and end is not None
        return WhenResult(min(start, end), max(start, end), part, True)

    for source, strict in ((expression, True), (utterance, False)):
        if not source:
            continue
        text = normalise(source)
        found = _dates(text, today)
        part = part or _day_part(text, day_parts)
        if found:
            return WhenResult(found[0], found[1], part, True)
        if part:
            return WhenResult(today, today, part, True)
        if strict:
            return WhenResult(today, today + timedelta(days=default_days - 1), None, False)
    return WhenResult(today, today + timedelta(days=default_days - 1), part, True)
