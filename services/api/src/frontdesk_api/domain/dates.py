"""Relative date expressions, resolved in the facility's timezone (openapi RULE on search).

The model never does calendar arithmetic; it forwards what the caller said. Day-part
words ("evening", "ಸಂಜೆ", "shaam") come from the tenant's DAY_PART lexicon; the words
for today/tomorrow/weekdays/months are language data in `frontdesk_api.locales`.

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

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

from .. import locales
from .text import contains_phrase, normalise, tokens


def _forms(*words: str) -> frozenset[str]:
    return frozenset(normalise(w) for w in words)


_TODAY = _forms(*locales.union("today"))
_TOMORROW = _forms(*locales.union("tomorrow"))
_DAY_AFTER = _forms(*locales.union("day_after_tomorrow"))
_NEXT = _forms(*locales.union("next"))
_THIS = _forms(*locales.union("this"))
_WEEK = _forms(*locales.union("week"))
_WEEKDAYS: tuple[frozenset[str], ...] = tuple(_forms(*day) for day in locales.calendar("weekdays"))
_MONTHS: tuple[frozenset[str], ...] = tuple(_forms(*month) for month in locales.calendar("months"))
# "5 tareekh": the 5th, whichever month it next falls in.
_DAY_OF_MONTH = _forms(*locales.union("day_of_month"))
# In a sentence these start history, not the visit: "fever since monday", "pain last night".
_HISTORY = _forms(*locales.union("history"))
# Words that are dates only when given as the time: "indu" is Kannada 'today' and a common name.
_AMBIGUOUS_IN_SPEECH = _forms(*locales.union("ambiguous_in_speech"))
_ORDINAL = re.compile(r"^(\d{1,2})(st|nd|rd|th)?$")
_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")
_NUMERIC = re.compile(r"(?<![\d/.-])(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2}|\d{4}))?(?![\d/.-])")


def _make(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _upcoming(today: date, month: int, day: int) -> date | None:
    """The next such date on or after today (no year said)."""
    this_year = _make(today.year, month, day)
    if this_year is not None and this_year >= today:
        return this_year
    return _make(today.year + 1, month, day)


def _day_number(word: str) -> int | None:
    m = _ORDINAL.match(word)
    return int(m.group(1)) if m else None


def _explicit(raw: str, text: str, today: date) -> tuple[bool, date | None]:
    """(a date was stated, the date or None if impossible). Day first, as callers in India say it."""
    if m := _ISO.search(raw):
        return True, _make(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if m := _NUMERIC.search(raw):
        day, month, year = int(m.group(1)), int(m.group(2)), m.group(3)
        if year:
            return True, _make(int(year) + (2000 if len(year) == 2 else 0), month, day)
        return True, _upcoming(today, month, day) if 1 <= month <= 12 else None
    words = tokens(text)
    for i, word in enumerate(words):
        month = next((n for n, forms in enumerate(_MONTHS, start=1) if word in forms), None)
        if month is not None:
            # "5 October", "October 5", "5th of October".
            before = words[i - 2] if i >= 2 and words[i - 1] == "of" else (words[i - 1] if i else "")
            around = [before, words[i + 1] if i + 1 < len(words) else ""]
            number = next((n for w in around if (n := _day_number(w)) is not None), None)
            if number is not None:
                return True, _upcoming(today, month, number)
        if word in _DAY_OF_MONTH and i > 0 and (number := _day_number(words[i - 1])) is not None:
            if not 1 <= number <= 31:
                return True, None
            for months_ahead in range(0, 3):
                y, m = divmod(today.month - 1 + months_ahead, 12)
                candidate = _make(today.year + y, m + 1, number)
                if candidate is not None and candidate >= today:
                    return True, candidate
            return True, None
    return False, None


def _without_history(text: str) -> str:
    """Speech mode: drop words that are history or names, not the time of the visit."""
    words = tokens(text)
    kept = [w for i, w in enumerate(words)
            if w not in _AMBIGUOUS_IN_SPEECH and not (i > 0 and words[i - 1] in _HISTORY)]
    return " ".join(kept)


@dataclass(frozen=True, slots=True)
class WhenResult:
    date_from: date
    date_to: date
    day_part: str | None
    resolved: bool  # False: an expression was given and nothing in it was understood
    stated: bool = True  # False: no date was said at all; the range is the default


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
        if not strict:
            text = _without_history(text)
        stated, explicit = _explicit(source.casefold(), text, today)
        if stated:
            if explicit is None:
                if strict:
                    return WhenResult(today, today + timedelta(days=default_days - 1), None, False)
                continue
            part = part or _day_part(text, day_parts)
            return WhenResult(explicit, explicit, part, True)
        found = _dates(text, today)
        part = part or _day_part(text, day_parts)
        if found:
            return WhenResult(found[0], found[1], part, True)
        if part:
            return WhenResult(today, today, part, True)
        if strict:
            return WhenResult(today, today + timedelta(days=default_days - 1), None, False)
    return WhenResult(today, today + timedelta(days=default_days - 1), part, True, stated=part is not None)


def time_words() -> frozenset[str]:
    """Every word the date rules understand (so the resolver can tell a time from a topic)."""
    groups = (_TODAY, _TOMORROW, _DAY_AFTER, _NEXT, _THIS, _WEEK, _DAY_OF_MONTH, *_WEEKDAYS, *_MONTHS)
    return frozenset(word for group in groups for form in group for word in form.split())
