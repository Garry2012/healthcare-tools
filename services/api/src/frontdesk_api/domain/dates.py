"""Relative date expressions, resolved in the facility's timezone (openapi RULE on search).

The model never does calendar arithmetic; it forwards what the caller said. Day-part
words ("evening", "ಸಂಜೆ", "shaam") come from the selected languages plus the tenant's
DAY_PART lexicon; the words for today/tomorrow/weekdays/months are language data in
`frontdesk_api.locales`, for the languages the rollout selected.

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
from functools import cache

from .. import locales
from .text import contains_phrase, normalise, tokens


def _forms(*words: str) -> frozenset[str]:
    return frozenset(normalise(w) for w in words)


@dataclass(frozen=True, slots=True)
class _Words:
    """The selected languages' date words, normalised (built once per language selection)."""

    today: frozenset[str]
    tomorrow: frozenset[str]
    day_after: frozenset[str]
    next: frozenset[str]
    this: frozenset[str]
    week: frozenset[str]
    weekdays: tuple[frozenset[str], ...]
    months: tuple[frozenset[str], ...]
    # "5 tareekh": the 5th, whichever month it next falls in.
    day_of_month: frozenset[str]
    # In a sentence these start history, not the visit: "fever since monday", "pain last night".
    history: frozenset[str]
    # Words that are dates only when given as the time: "indu" is Kannada 'today' and a common name.
    ambiguous_in_speech: frozenset[str]
    # A day of the month said in words (locales/): cardinals only before "tareekh", ordinals also
    # next to a month, tens only as the start of "twenty first". Digits keep their own rules.
    ordinals: dict[str, int]
    tens: dict[str, int]
    day_words: dict[str, int]  # cardinals and ordinals
    # Month names that are also everyday words ("may", "mai", "me"): never read with a number word.
    ambiguous_months: frozenset[str]
    fillers: frozenset[str]
    time_words: frozenset[str]
    day_parts: tuple[tuple[str, str], ...]  # (normalised word, MORNING|AFTERNOON|EVENING)


@cache
def _words_for(codes: tuple[str, ...]) -> _Words:
    def forms(name: str) -> frozenset[str]:
        return _forms(*locales.union(name, codes))

    def table(name: str) -> dict[str, int]:
        return {normalise(w): n for w, n in locales.numbers(name, codes).items()}

    weekdays = tuple(_forms(*day) for day in locales.calendar("weekdays", codes))
    months = tuple(_forms(*month) for month in locales.calendar("months", codes))
    groups = (forms("today"), forms("tomorrow"), forms("day_after_tomorrow"), forms("next"), forms("this"),
              forms("week"), forms("day_of_month"), *weekdays, *months)
    return _Words(
        today=forms("today"), tomorrow=forms("tomorrow"), day_after=forms("day_after_tomorrow"),
        next=forms("next"), this=forms("this"), week=forms("week"), weekdays=weekdays, months=months,
        day_of_month=forms("day_of_month"), history=forms("history"),
        ambiguous_in_speech=forms("ambiguous_in_speech"), ordinals=table("ordinals"), tens=table("tens"),
        day_words={**table("cardinals"), **table("ordinals")}, ambiguous_months=forms("ambiguous_months"),
        fillers=forms("date_fillers"),
        time_words=frozenset(word for group in groups for form in group for word in form.split()),
        day_parts=tuple((normalise(word), part) for word, part in locales.day_parts(codes)),
    )


_current: tuple[tuple[str, ...], _Words] | None = None


def _w() -> _Words:
    """The selected languages' words: called many times per parse, so the last build is kept."""
    global _current
    codes = locales.selected()
    if _current is None or _current[0] is not codes:
        _current = (codes, _words_for(codes))
    return _current[1]


UNCLEAR = -1  # a day was said but which one is not clear: ask, never guess
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


def _digit_day(word: str) -> int | None:
    """ "5" or "5th"."""
    m = _ORDINAL.match(word)
    return int(m.group(1)) if m else None


def _is_number(word: str) -> bool:
    return _digit_day(word) is not None or word in _w().day_words or word in _w().tens


def _word_day_ending_at(words: list[str], j: int, table: dict[str, int]) -> int | None:
    """The day said in words ending at words[j] ("fifth", "twenty first", "ಐದು"). UNCLEAR when
    another number stands right before it ("do teen tareekh": the 2nd or the 3rd?)."""
    if j < 0 or (n := table.get(words[j])) is None:
        return None
    before = words[j - 1] if j > 0 else ""
    if before in _w().tens:
        return _w().tens[before] + n if n < 10 and words[j] in _w().ordinals else UNCLEAR
    return UNCLEAR if _is_number(before) else n


def _ordinal_ending_the_phrase(words: list[str], k: int) -> int | None:
    """ "October fifth", "October the thirty first": an ordinal that is the last thing said, so
    "October first week" is not the 1st."""
    rest = words[k:]
    if len(rest) == 1 and rest[0] in _w().ordinals:
        return _w().ordinals[rest[0]]
    if len(rest) == 2 and rest[0] in _w().tens and _w().ordinals.get(rest[1], 10) < 10:
        return _w().tens[rest[0]] + _w().ordinals[rest[1]]
    return None


def _month_day(words: list[str], i: int) -> int | None:
    """The day given with the month at words[i]: digits exactly as always, then ordinal words."""
    before = words[i - 2] if i >= 2 and words[i - 1] == "of" else (words[i - 1] if i else "")
    around = [before, words[i + 1] if i + 1 < len(words) else ""]
    number = next((n for w in around if (n := _digit_day(w)) is not None), None)
    if number is not None or words[i] in _w().ambiguous_months:
        return number
    j = i - 1
    while j >= 0 and words[j] in _w().fillers:
        j -= 1
    number = _word_day_ending_at(words, j, _w().ordinals)
    if number is None:
        k = i + 1
        while k < len(words) and words[k] in _w().fillers:
            k += 1
        number = _ordinal_ending_the_phrase(words, k)
    return number


def _tareekh_days(words: list[str]) -> list[int]:
    """Every day said with a day-of-month word: "5 tareekh", "paanch tareekh", "ಐದನೇ ತಾರೀಖು"."""
    days = []
    for i, word in enumerate(words):
        if word in _w().day_of_month and i > 0:
            n = _digit_day(words[i - 1])
            if n is None:
                n = _word_day_ending_at(words, i - 1, _w().day_words)
            if n is not None:
                days.append(n)
    return days


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
    named_month = None
    for i, word in enumerate(words):
        month = next((n for n, forms in enumerate(_w().months, start=1) if word in forms), None)
        if month is not None and (number := _month_day(words, i)) is not None:
            # "5 October", "October 5", "5th of October", "the fifth of October", "October fifth".
            return True, None if number == UNCLEAR else _upcoming(today, month, number)
        if month is not None and word not in _w().ambiguous_months:
            named_month = named_month or month
    days = _tareekh_days(words)
    if days:
        if UNCLEAR in days or len(set(days)) > 1 or not 1 <= days[0] <= 31:
            return True, None  # "ek tareekh nahi, das tareekh", "do teen tareekh", "32 tareekh"
        if named_month is not None:  # "5 tareekh November"
            return True, _upcoming(today, named_month, days[0])
        for months_ahead in range(0, 3):
            y, m = divmod(today.month - 1 + months_ahead, 12)
            candidate = _make(today.year + y, m + 1, days[0])
            if candidate is not None and candidate >= today:
                return True, candidate
        return True, None
    return False, None


def _without_history(text: str) -> str:
    """Speech mode: drop words that are history or names, not the time of the visit."""
    words = tokens(text)
    kept = [w for i, w in enumerate(words)
            if w not in _w().ambiguous_in_speech and not (i > 0 and words[i - 1] in _w().history)]
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
        for index, forms in enumerate(_w().weekdays):
            if word not in forms:
                continue
            ahead = (index - today.weekday()) % 7
            if i > 0 and words[i - 1] in _w().next:
                ahead = ahead or 7
            return today + timedelta(days=ahead)
    return None


def _dates(text: str, today: date) -> tuple[date, date] | None:
    words = tokens(text)
    if any(contains_phrase(text, p) for p in _w().day_after):
        return today + timedelta(days=2), today + timedelta(days=2)
    for i, word in enumerate(words):
        if word in _w().week and i > 0:
            if words[i - 1] in _w().next:
                monday = today + timedelta(days=7 - today.weekday())
                return monday, monday + timedelta(days=6)
            if words[i - 1] in _w().this:
                return today, today + timedelta(days=6 - today.weekday())
    if any(contains_phrase(text, p) for p in _w().tomorrow):
        return today + timedelta(days=1), today + timedelta(days=1)
    day = _weekday(words, today)
    if day is not None:
        return day, day
    if any(contains_phrase(text, p) for p in _w().today):
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
    """`day_parts` are (normalised term, DayPart) pairs from the approved lexicon, on top of the
    selected languages' own day-part words."""
    day_parts = [*_w().day_parts, *day_parts]
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
    return _w().time_words
