"""Language data the resolver, date rules and knowledge search understand.

One module per language holds that language's words (native script and the romanised forms
callers and speech-to-text produce). Every module is available to every domain and rollout;
a rollout switches on the ones it serves (`TENANT_SUPPORTED_LANGUAGES`, applied once at
startup with `select`), and the core only ever sees the union of the selected languages.
Supporting a new language is a new module here plus a line in AVAILABLE: no change to
matching logic. Words are stored as spoken; the core normalises them.
"""

from __future__ import annotations

from collections.abc import Iterable
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
    # A day of the month said in words. Cardinals ("paanch", "ಐದು") count only before a
    # day-of-month word ("tareekh"); ordinals ("fifth", "ಐದನೇ") may also stand next to a month;
    # tens ("twenty") only as the first half of "twenty first".
    cardinals: dict[str, int]
    ordinals: dict[str, int]
    tens: dict[str, int]
    ambiguous_months: tuple[str, ...]  # month names that are everyday words: "may", "मई" (mai), "ಮೇ" (me)
    date_fillers: tuple[str, ...]  # between a day and its month: "the fifth of October"
    day_parts: dict[str, tuple[str, ...]]  # MORNING/AFTERNOON/EVENING -> the words for it


AVAILABLE: dict[str, Locale] = {loc.code: loc for loc in (Locale(**m.WORDS) for m in (en, hi, kn))}
DAY_PARTS = ("MORNING", "AFTERNOON", "EVENING")

_NUMBER_TABLES = ("cardinals", "ordinals", "tens")
_WORD_LISTS = {f.name for f in fields(Locale)} - {"code", "script", "weekdays", "months", "day_parts",
                                                   *_NUMBER_TABLES}
_selected: tuple[str, ...] = tuple(AVAILABLE)


def select(codes: Iterable[str]) -> tuple[str, ...]:
    """Switch on the rollout's languages (process-wide: one deployment serves one rollout)."""
    global _selected
    wanted = set(codes)
    if unknown := sorted(wanted - set(AVAILABLE)):
        raise ValueError(f"no language module for {', '.join(unknown)} (available: {', '.join(AVAILABLE)})")
    if not wanted:
        raise ValueError("at least one language is required")
    _selected = tuple(code for code in AVAILABLE if code in wanted)  # registration order: stable
    return _selected


def selected() -> tuple[str, ...]:
    """The switched-on language codes; every derived word table is keyed by this."""
    return _selected


def _active(codes: tuple[str, ...] | None) -> tuple[Locale, ...]:
    return tuple(AVAILABLE[c] for c in (_selected if codes is None else codes))


def union(name: str, codes: tuple[str, ...] | None = None) -> tuple[str, ...]:
    """Every selected language's words for one list, in registration order."""
    if name not in _WORD_LISTS:
        raise KeyError(name)
    return tuple(word for loc in _active(codes) for word in getattr(loc, name))


def numbers(table: str, codes: tuple[str, ...] | None = None) -> dict[str, int]:
    """One number table ("cardinals", "ordinals" or "tens") across the selected languages."""
    if table not in _NUMBER_TABLES:
        raise KeyError(table)
    merged: dict[str, int] = {}
    for loc in _active(codes):
        merged.update(getattr(loc, table))
    return merged


def calendar(name: str, codes: tuple[str, ...] | None = None) -> tuple[tuple[str, ...], ...]:
    """Weekdays or months: position i holds every selected language's words for that day or month."""
    size = {"weekdays": 7, "months": 12}[name]
    return tuple(tuple(w for loc in _active(codes) for w in getattr(loc, name)[i]) for i in range(size))


def day_parts(codes: tuple[str, ...] | None = None) -> tuple[tuple[str, str], ...]:
    """(word, MORNING|AFTERNOON|EVENING) for every selected language."""
    return tuple((word, part) for loc in _active(codes) for part, words in loc.day_parts.items() for word in words)
