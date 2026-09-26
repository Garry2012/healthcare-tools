"""Text normalisation shared by the resolver, the lexicon and identity matching.

Everything is compared in one space: NFC, lower-case, Indic scripts transliterated to
plain Latin, diacritics removed, punctuation collapsed to spaces. A lexicon term and a
caller's words go through the same function, so what matters is consistency, not a
linguistically perfect romanisation.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

from indic_transliteration import sanscript
from metaphone import doublemetaphone

from .. import locales

# Unicode blocks -> sanscript scheme. Scripts not listed pass through unchanged.
_SCRIPTS: tuple[tuple[int, int, str], ...] = (
    (0x0900, 0x097F, sanscript.DEVANAGARI),
    (0x0980, 0x09FF, sanscript.BENGALI),
    (0x0A00, 0x0A7F, sanscript.GURMUKHI),
    (0x0A80, 0x0AFF, sanscript.GUJARATI),
    (0x0B00, 0x0B7F, sanscript.ORIYA),
    (0x0B80, 0x0BFF, sanscript.TAMIL),
    (0x0C00, 0x0C7F, sanscript.TELUGU),
    (0x0C80, 0x0CFF, sanscript.KANNADA),
    (0x0D00, 0x0D7F, sanscript.MALAYALAM),
)

# IAST letters whose everyday romanisation differs from "strip the accent".
_IAST_FIXUPS: tuple[tuple[str, str], ...] = (
    ("ś", "sh"),
    ("ṣ", "sh"),
    ("c", "ch"),
    ("ṛ", "ri"),
    ("ḻ", "l"),
)
_ANUSVARA = re.compile(r"ṃ(?=[pbm])")
# \w misses Indic vowel signs and viramas (category M), which would split words apart.
_WORD = re.compile(r"(?:[^\W_]|[\u0300-\u036f\u0900-\u0dff\u200c\u200d])+")
# English possessive: "children's doctor" means "children doctor"; "D'Souza" is untouched.
_POSSESSIVE = re.compile(r"(?<=\w)['’]s\b")

# Titles callers put in front of a resource's name, in the scripts we see.
HONORIFICS = frozenset(locales.union("titles"))


# Words that carry no topic in the languages callers use (romanised forms included, since
# Kannada and Devanagari are transliterated before this runs). Question words (when/where,
# kab/kahan, yavaga/elli) are kept: they separate "opening hours" from "location".
STOPWORDS = frozenset(locales.union("stopwords"))


def _script_of(ch: str) -> str | None:
    code = ord(ch)
    for low, high, scheme in _SCRIPTS:
        if low <= code <= high:
            return scheme
    return None


def _strip_marks(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _romanise_word(word: str, scheme: str) -> str:
    latin = sanscript.transliterate(word, scheme, sanscript.IAST)
    # Hindi drops the inherent final vowel ("शाम" is "shaam", not "shaama").
    if scheme == sanscript.DEVANAGARI and len(latin) > 2 and latin.endswith("a"):
        last = word[-1]
        if unicodedata.category(last) == "Lo" and not ("ऄ" <= last <= "औ"):
            latin = latin[:-1]
    # Chandrabindu (ँ) comes out as "~"; it is a nasal like anusvara (ं), so "पाँच" = "पांच".
    latin = _ANUSVARA.sub("m", latin.replace("~", "ṃ")).replace("ṃ", "n")
    for src, dst in _IAST_FIXUPS:
        latin = latin.replace(src, dst)
    return latin


def transliterate(text: str) -> str:
    """Romanise every Indic-script word; leave Latin and other scripts alone."""
    out: list[str] = []
    for match in re.finditer(r"\S+", text):
        word = match.group(0)
        scheme = next((s for s in map(_script_of, word) if s), None)
        out.append(_romanise_word(word, scheme) if scheme else word)
    return " ".join(out)


def tokens(text: str) -> list[str]:
    return _WORD.findall(text)


# Pure functions of their input, called for every directory term on every search: memoised
# (bounded) so the resolver pays for transliteration once per distinct string, not per request.
@lru_cache(maxsize=16384)
def native_form(text: str) -> str:
    """NFC + lower-case + punctuation removed, script preserved."""
    return " ".join(tokens(_POSSESSIVE.sub("", unicodedata.normalize("NFC", text).casefold())))


@lru_cache(maxsize=16384)
def normalise(text: str, *, strip_honorifics: bool = False) -> str:
    """NFC → lower → (honorifics) → transliterate → strip accents → single spaces."""
    words = tokens(_POSSESSIVE.sub("", unicodedata.normalize("NFC", text).casefold()))
    if strip_honorifics:
        words = [w for w in words if w not in HONORIFICS]
    latin = _strip_marks(transliterate(" ".join(words)))
    return " ".join(tokens(latin.lower()))


@lru_cache(maxsize=16384)
def phonetic_keys(token: str) -> frozenset[str]:
    primary, secondary = doublemetaphone(token)
    return frozenset(k for k in (primary, secondary) if k)


def contains_phrase(haystack: str, needle: str) -> bool:
    """Whole-word containment of an already-normalised phrase."""
    if not needle:
        return False
    return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack) is not None


def normalise_person_name(name: str) -> str:
    """Identity comparison form of a customer name."""
    return normalise(name, strip_honorifics=True)


def loosely_same(a: str, b: str) -> bool:
    """The same word up to inflection: 'pain'/'paining', 'bleed'/'bleeding', 'breathe'/'breathing'.
    A shared stem is not enough ('breathing' is not 'breathlessness')."""
    if a == b:
        return True
    short, long = sorted((a, b), key=len)
    if len(short) < 4:
        return False
    return long.startswith(short) or (short.endswith("e") and long.startswith(short[:-1]) and len(short) > 4)


def content_words(text: str) -> list[str]:
    """Normalised words that carry meaning (stopwords and 1-letter tokens removed)."""
    return [w for w in tokens(normalise(text)) if w not in STOPWORDS and len(w) > 1]
