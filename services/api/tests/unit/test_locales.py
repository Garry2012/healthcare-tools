"""Language data is well-formed: every language fills the calendar, and each word is filed
under the language whose script it is written in (a Kannada word in the Hindi file would
still work today, but would vanish if Hindi were ever switched off for a hospital)."""

from __future__ import annotations

import pytest

from frontdesk_api import locales
from frontdesk_api.locales import LOCALES, Locale

LISTS = [f for f in Locale.__dataclass_fields__ if f not in ("code", "script", "weekdays", "months")]


def _words(loc: Locale):
    for name in LISTS:
        yield from getattr(loc, name)
    for group in (*loc.weekdays, *loc.months):
        yield from group


def test_codes_are_unique_and_calendars_complete():
    assert len({loc.code for loc in LOCALES}) == len(LOCALES)
    for loc in LOCALES:
        assert len(loc.weekdays) == 7 and all(loc.weekdays), loc.code
        assert len(loc.months) == 12, loc.code


@pytest.mark.parametrize("loc", LOCALES, ids=lambda loc: loc.code)
def test_native_script_words_belong_to_their_own_language(loc):
    scripts = {other.code: other.script for other in LOCALES if other.script}
    for word in _words(loc):
        for code, (low, high) in scripts.items():
            if any(low <= ch <= high for ch in word):
                assert code == loc.code, f"{word!r} is {code} script but filed under {loc.code}"


def test_union_keeps_every_language():
    assert {"today", "aaj", "ಇಂದು"} <= set(locales.union("today"))
    monday = locales.calendar("weekdays")[0]
    assert {"monday", "somvar", "ಸೋಮವಾರ"} <= set(monday)
    with pytest.raises(KeyError):
        locales.union("weekdays")
