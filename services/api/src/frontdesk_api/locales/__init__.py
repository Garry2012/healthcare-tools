"""Language data the resolver, date rules and knowledge search understand.

One module per language holds that language's words (native script and the romanised forms
callers and speech-to-text produce). The core only ever sees the union of the registered
languages, so supporting a new language is a new module here plus a line in LOCALES: no
change to matching logic. Words are stored as spoken; the core normalises them.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

from . import en, hi, kn


@dataclass(frozen=True)
class Locale:
    code: str
    script: tuple[str, str] | None  # first and last code point of the native script
    today: tuple[str, ...]
    tomorrow: tuple[str, ...]
    day_after_tomorrow: tuple[str, ...]
    next: tuple[str, ...]
    this: tuple[str, ...]
    week: tuple[str, ...]
    weekdays: tuple[tuple[str, ...], ...]  # Monday first, seven entries
    months: tuple[tuple[str, ...], ...]  # January first, twelve entries
    day_of_month: tuple[str, ...]  # "5 tareekh": the 5th
    history: tuple[str, ...]  # "since", "last": starts history, not the visit
    ambiguous_in_speech: tuple[str, ...]  # a date word that is also a common name
    titles: tuple[str, ...]  # put before a person's name ("Dr", "sir", "ji")
    stopwords: tuple[str, ...]  # carry no topic
    availability: tuple[str, ...]  # only ask "is someone free?"


LOCALES: tuple[Locale, ...] = tuple(Locale(**m.WORDS) for m in (en, hi, kn))
BY_CODE: dict[str, Locale] = {loc.code: loc for loc in LOCALES}

_WORD_LISTS = {f.name for f in fields(Locale)} - {"code", "script", "weekdays", "months"}


def union(name: str) -> tuple[str, ...]:
    """Every registered language's words for one list, in registration order."""
    if name not in _WORD_LISTS:
        raise KeyError(name)
    return tuple(word for loc in LOCALES for word in getattr(loc, name))


def calendar(name: str) -> tuple[tuple[str, ...], ...]:
    """Weekdays or months: position i holds every language's words for that day or month."""
    size = {"weekdays": 7, "months": 12}[name]
    return tuple(tuple(w for loc in LOCALES for w in getattr(loc, name)[i]) for i in range(size))
