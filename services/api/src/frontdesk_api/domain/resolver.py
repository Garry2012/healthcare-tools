"""Server-side understanding of the caller's words (IMPLEMENTATION.md §2.3, MVP scope).

Pipeline: red flag → service transfer → resource (exact / variant / lexicon / Double
Metaphone) → category (lexicon, approved need routes, semantic hook) → decision.
Dates are resolved separately in `dates.py`. Everything is deterministic; below the
tenant's thresholds the resolver proposes, it never picks.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from .dates import time_words
from .text import (
    HONORIFICS,
    contains_phrase,
    content_words,
    loosely_same,
    native_form,
    normalise,
    phonetic_keys,
    tokens,
)

# Confidence per match kind. Tiering matters more than the exact numbers: an exact
# match suppresses phonetic look-alikes ("garima" also sounds like "karima").
CONF_EXACT = 1.0
CONF_SUBSET = 0.95
CONF_VARIANT = 0.95
CONF_LEXICON = 0.95
CONF_PHONETIC = 0.85
CONF_DEPT_EXACT = 1.0
CONF_DEPT_CONTAINED = 0.9


@dataclass(frozen=True, slots=True)
class LexiconTerm:
    concept_type: str
    concept_id: str
    term: str
    language: str
    approved: bool = True

    @property
    def latin(self) -> str:
        return normalise(self.term)

    @property
    def native(self) -> str:
        return native_form(self.term)


@dataclass(frozen=True, slots=True)
class ResourceEntry:
    resource_id: str
    name: str
    category_ids: tuple[str, ...]
    name_variants: tuple[str, ...] = ()
    localized_names: tuple[str, ...] = ()
    active: bool = True
    booking_policy: str = "BOOKABLE"


@dataclass(frozen=True, slots=True)
class CategoryEntry:
    category_id: str
    name: str
    code: str | None = None
    localized_names: tuple[str, ...] = ()
    offers_bookings: bool = True
    active: bool = True


@dataclass(frozen=True, slots=True)
class Directory:
    resources: tuple[ResourceEntry, ...]
    categories: tuple[CategoryEntry, ...]
    lexicon: tuple[LexiconTerm, ...]

    def terms(self, concept_type: str) -> list[LexiconTerm]:
        return [t for t in self.lexicon if t.approved and t.concept_type == concept_type]

    def category(self, category_id: str) -> CategoryEntry | None:
        return next((d for d in self.categories if d.category_id == category_id), None)


@dataclass(frozen=True, slots=True)
class ResolverThresholds:
    resource: float = 0.8
    category: float = 0.8
    suggestion: float = 0.7


class SemanticMatcher(Protocol):
    """Step 4 of §2.3: multilingual sentence similarity to category names.

    TODO(IMPLEMENTATION.md §2.3 step 4): plug in a LaBSE-class model once the lexicon has
    content. Until then `NoSemanticMatcher` keeps the resolver deterministic.
    """

    def match(self, text: str, categories: Sequence[CategoryEntry]) -> list[tuple[str, float]]:
        ...


class NoSemanticMatcher:
    def match(self, text: str, categories: Sequence[CategoryEntry]) -> list[tuple[str, float]]:
        return []


@dataclass(frozen=True, slots=True)
class ResourceMatch:
    resource_id: str
    confidence: float
    matched_on: str  # NAME_EXACT | NAME_PHONETIC | NAME_VARIANT | LEXICON


@dataclass(frozen=True, slots=True)
class CategoryMatch:
    category_id: str
    confidence: float
    matched_on: str  # LEXICON | NEED_ROUTE | SEMANTIC


@dataclass(slots=True)
class Resolution:
    action: str  # OFFER_SLOTS | CLARIFY | TRANSFER_EMERGENCY | TRANSFER_DESK | NO_SERVICE
    destination: str | None = None
    resources: list[ResourceMatch] = field(default_factory=list)
    categories: list[CategoryMatch] = field(default_factory=list)
    clarification_type: str | None = None
    clarification_options: list[tuple[str, str]] = field(default_factory=list)  # (kind, id)
    suggestions: list[str] = field(default_factory=list)  # category ids
    departed: str | None = None  # the caller named a resource that no longer takes bookings


# Words that only ask "is someone free?" (en, hi and kn, romanised as the normaliser does).
AVAILABILITY_WORDS = frozenset(normalise(w) for w in (
    "any", "anyone", "anybody", "someone", "somebody", "available", "availability", "free", "sitting",
    "present", "open", "see", "consult", "consultation", "appointment", "book", "booking", "slot", "token",
    "time", "timing", "currently", "koi", "milega", "milegi", "milenge", "baithe", "baithi", "yaradaru",
    "yaaradaru", "iddara", "iddare", "iddaara", "sigtara", "sigthare", "ಯಾರಾದರೂ", "ಇದ್ದಾರಾ", "ಇದ್ದಾರೆ",
    "कोई", "मिलेगा", "बैठे",
))
HONORIFICS_LATIN = frozenset(normalise(h) for h in HONORIFICS)
_NUMBER = re.compile(r"\d+(st|nd|rd|th)?")


# ---------------------------------------------------------------- matching


def _both_forms(text: str) -> tuple[str, str]:
    return normalise(text), native_form(text)


def _lexicon_hit(texts: Iterable[str], term: LexiconTerm) -> bool:
    for text in texts:
        latin, native = _both_forms(text)
        if contains_phrase(latin, term.latin) or contains_phrase(native, term.native):
            return True
    return False


def _loose_hit(texts: Iterable[str], term: LexiconTerm) -> bool:
    """Every content word of the term appears in one text, in any order and inflection.

    Used only for red flags, where a miss is the dangerous error: "my chest is paining" must
    meet "chest pain", "seene me dard" must meet "seene mein dard".
    """
    wanted = content_words(term.term)
    if not wanted:
        return False
    for text in texts:
        words = content_words(text)
        if all(any(loosely_same(w, have) for have in words) for w in wanted):
            return True
    return False


def red_flag_terms(texts: Iterable[str], terms: Iterable[LexiconTerm]) -> LexiconTerm | None:
    texts = [t for t in texts if t]
    return next(
        (t for t in terms
         if t.approved and t.concept_type == "RED_FLAG" and (_lexicon_hit(texts, t) or _loose_hit(texts, t))),
        None,
    )


def red_flag(texts: Iterable[str], directory: Directory) -> LexiconTerm | None:
    return red_flag_terms(texts, directory.terms("RED_FLAG"))


def service_transfer(texts: Iterable[str], directory: Directory) -> LexiconTerm | None:
    texts = [t for t in texts if t]
    terms = sorted(directory.terms("SERVICE_TRANSFER"), key=lambda t: -len(t.latin))
    return next((t for t in terms if _lexicon_hit(texts, t)), None)


def _name_tokens(name: str) -> list[str]:
    return tokens(normalise(name, strip_honorifics=True))


def match_resources(
    query: str, directory: Directory, *, allow_phonetic: bool, former: bool = False
) -> list[ResourceMatch]:
    """Score every active resource (or, with `former`, every one that no longer takes bookings);
    keep only the best tier."""
    q = _name_tokens(query)
    if not q:
        return []
    q_text = " ".join(q)
    resource_terms = directory.terms("RESOURCE")
    scored: list[ResourceMatch] = []
    for doc in directory.resources:
        if doc.active == former:
            continue
        name = _name_tokens(doc.name)
        localized = [_name_tokens(n) for n in doc.localized_names]
        best: ResourceMatch | None = None
        if q == name or any(q == loc for loc in localized):
            best = ResourceMatch(doc.resource_id, CONF_EXACT, "NAME_EXACT")
        elif set(q) <= set(name) or any(loc and set(q) <= set(loc) for loc in localized):
            best = ResourceMatch(doc.resource_id, CONF_SUBSET, "NAME_EXACT")
        elif any(q_text == " ".join(_name_tokens(v)) for v in doc.name_variants):
            best = ResourceMatch(doc.resource_id, CONF_VARIANT, "NAME_VARIANT")
        elif any(
            t.concept_id == doc.resource_id and " ".join(_name_tokens(t.term)) == q_text
            for t in resource_terms
        ):
            best = ResourceMatch(doc.resource_id, CONF_LEXICON, "LEXICON")
        elif allow_phonetic:
            candidates = [name, *(_name_tokens(v) for v in doc.name_variants)]
            for cand in candidates:
                if cand and all(
                    len(tok) >= 3
                    and any(phonetic_keys(tok) & phonetic_keys(c) for c in cand if len(c) >= 3)
                    for tok in q
                ):
                    best = ResourceMatch(doc.resource_id, CONF_PHONETIC, "NAME_PHONETIC")
                    break
        if best:
            scored.append(best)
    if not scored:
        return []
    top = max(m.confidence for m in scored)
    tier = CONF_SUBSET if top >= CONF_SUBSET else top
    return sorted((m for m in scored if m.confidence >= tier), key=lambda m: -m.confidence)


def _scan_utterance_for_resources(utterance: str, directory: Directory) -> list[ResourceMatch]:
    """Without an explicit resourceName, only exact name tokens in the utterance count."""
    words = set(tokens(normalise(utterance, strip_honorifics=True)))
    hits: list[ResourceMatch] = []
    for doc in directory.resources:
        if not doc.active:
            continue
        name = _name_tokens(doc.name)
        distinctive = [t for t in name if len(t) >= 3]
        if distinctive and set(distinctive) <= words:
            hits.append(ResourceMatch(doc.resource_id, CONF_SUBSET, "NAME_EXACT"))
    return hits


def match_categories(
    texts: Sequence[str],
    directory: Directory,
    semantic: SemanticMatcher,
    threshold: float,
) -> list[CategoryMatch]:
    texts = [t for t in texts if t]
    if not texts:
        return []
    found: dict[str, CategoryMatch] = {}

    def keep(match: CategoryMatch) -> None:
        cat = directory.category(match.category_id)
        if cat is None or not cat.active:
            return
        current = found.get(match.category_id)
        if current is None or match.confidence > current.confidence:
            found[match.category_id] = match

    for text in texts:
        latin, native = _both_forms(text)
        for cat in directory.categories:
            names = [cat.name, *(cat.localized_names), *([cat.code] if cat.code else [])]
            for n in names:
                n_latin, n_native = _both_forms(n)
                if latin == n_latin or native == n_native:
                    keep(CategoryMatch(cat.category_id, CONF_DEPT_EXACT, "LEXICON"))
                elif len(n_latin) > 3 and contains_phrase(latin, n_latin):
                    keep(CategoryMatch(cat.category_id, CONF_DEPT_CONTAINED, "LEXICON"))
        for kind, matched_on in (("CATEGORY", "LEXICON"), ("NEED_ROUTE", "NEED_ROUTE")):
            for term in directory.terms(kind):
                if latin == term.latin or native == term.native:
                    keep(CategoryMatch(term.concept_id, CONF_DEPT_EXACT, matched_on))
                elif contains_phrase(latin, term.latin) or contains_phrase(native, term.native):
                    keep(CategoryMatch(term.concept_id, CONF_DEPT_CONTAINED, matched_on))
    if not found:
        for text in texts:
            for cat_id, score in semantic.match(text, directory.categories):
                if score >= threshold:
                    keep(CategoryMatch(cat_id, score, "SEMANTIC"))
    return sorted(
        (m for m in found.values() if m.confidence >= threshold), key=lambda m: -m.confidence
    )


def suggest_categories(texts: Sequence[str], directory: Directory, cutoff: float) -> list[str]:
    """Spelling-level near misses ("zoologist" → urologist). Proposals only."""
    vocabulary: dict[str, str] = {}
    for cat in directory.categories:
        if cat.active and cat.offers_bookings:
            for word in tokens(normalise(cat.name)):
                if len(word) > 3:
                    vocabulary.setdefault(word, cat.category_id)
    for term in directory.terms("CATEGORY"):
        for word in tokens(term.latin):
            if len(word) > 3:
                vocabulary.setdefault(word, term.concept_id)
    ranked: list[tuple[float, str]] = []
    for text in texts:
        for word in tokens(normalise(text)):
            if len(word) <= 3 or word in vocabulary:
                continue
            for close in difflib.get_close_matches(word, vocabulary, n=3, cutoff=cutoff):
                ratio = difflib.SequenceMatcher(None, word, close).ratio()
                ranked.append((ratio, vocabulary[close]))
    seen: list[str] = []
    for _, cat_id in sorted(ranked, key=lambda r: -r[0]):
        if cat_id not in seen:
            seen.append(cat_id)
    return seen[:3]


# ---------------------------------------------------------------- decision


def resolve(
    *,
    utterance: str,
    directory: Directory,
    resource_name: str | None = None,
    category: str | None = None,
    need_text: str | None = None,
    thresholds: ResolverThresholds | None = None,
    semantic: SemanticMatcher | None = None,
) -> Resolution:
    semantic = semantic or NoSemanticMatcher()
    thresholds = thresholds or ResolverThresholds()
    everything = [utterance, resource_name or "", category or "", need_text or ""]

    flag = red_flag(everything, directory)
    if flag:
        return Resolution(action="TRANSFER_EMERGENCY")  # destination: the domain pack's escalation
    service = service_transfer(everything, directory)
    if service:
        return Resolution(action="TRANSFER_DESK", destination=service.concept_id)

    if resource_name:
        resources = [
            m
            for m in match_resources(resource_name, directory, allow_phonetic=True)
            if m.confidence >= thresholds.resource
        ]
    elif not category and not need_text:
        resources = _scan_utterance_for_resources(utterance, directory)
    else:
        resources = []

    departed: ResourceEntry | None = None
    if resource_name and not resources:
        # Never by sound alone: "Dr Keeran" must not be told that a doctor has left.
        former = [m for m in match_resources(resource_name, directory, allow_phonetic=False, former=True)
                  if m.confidence >= thresholds.resource]
        if len(former) == 1:
            departed = next(d for d in directory.resources if d.resource_id == former[0].resource_id)

    cat_texts = [t for t in (category, need_text) if t]
    if departed and not cat_texts:
        # The caller still needs that department: search it, and say the named person is not here.
        wanted = [c for c in departed.category_ids
                  if (entry := directory.category(c)) and entry.offers_bookings and entry.active]
        if wanted:
            return Resolution(action="OFFER_SLOTS", departed=departed.resource_id,
                              categories=[CategoryMatch(c, 1.0, "FORMER_RESOURCE") for c in wanted])
    if not cat_texts and (not resources or not resource_name):
        # A name found only by scanning the sentence ("I am Garima, need a skin doctor") must not
        # hide the department the caller asked for: match categories too, so a mismatch is asked.
        cat_texts = [utterance]
    categories = match_categories(cat_texts, directory, semantic, thresholds.category)
    categories = [
        d for d in categories if (entry := directory.category(d.category_id)) and entry.offers_bookings
    ]

    resolution = Resolution(action="OFFER_SLOTS", resources=resources, categories=categories)

    if len(resources) > 1:
        resolution.action = "CLARIFY"
        resolution.clarification_type = "WHICH_RESOURCE"
        resolution.clarification_options = [("resource", m.resource_id) for m in resources]
        return resolution

    if len(resources) == 1 and categories:
        resource = next(d for d in directory.resources if d.resource_id == resources[0].resource_id)
        if not set(resource.category_ids) & {d.category_id for d in categories}:
            resolution.action = "CLARIFY"
            resolution.clarification_type = "CONFIRM_INTERPRETATION"
            resolution.clarification_options = [("resource", resource.resource_id)] + [
                ("category", d.category_id) for d in categories
            ]
        return resolution

    if resources:
        return resolution

    if len(categories) > 1:
        top = categories[0].confidence
        leaders = [d for d in categories if d.confidence >= top]
        if len(leaders) > 1:
            resolution.action = "CLARIFY"
            resolution.clarification_type = "WHICH_CATEGORY"
            resolution.clarification_options = [("category", d.category_id) for d in leaders]
            return resolution
        resolution.categories = leaders
        return resolution

    if categories:
        return resolution

    # A person's name is not a misspelt department: leave it out of the spelling suggestions.
    name_words = set(_name_tokens(resource_name)) if resource_name else set()
    said = " ".join(w for w in tokens(normalise(utterance)) if w not in name_words)
    probe = [t for t in (category, need_text, said) if t]
    suggestions = suggest_categories(probe, directory, thresholds.suggestion)
    if suggestions:
        resolution.action = "CLARIFY"
        resolution.clarification_type = "CONFIRM_INTERPRETATION"
        resolution.clarification_options = [("category", d) for d in suggestions]
        resolution.suggestions = suggestions
        return resolution

    if resource_name or category or need_text:
        resolution.action = "NO_SERVICE"
        return resolution

    # "Anyone available right now?" only when every word is about availability or time; words we
    # did not understand never get a doctor offered in their place.
    day_part_words = {w for t in directory.terms("DAY_PART") for w in t.latin.split()}
    unexplained = [
        w for w in content_words(utterance)
        if w not in AVAILABILITY_WORDS and w not in HONORIFICS_LATIN and w not in time_words()
        and w not in day_part_words and not _NUMBER.fullmatch(w)
    ]
    resolution.action = "NO_SERVICE" if unexplained else "OFFER_SLOTS"
    return resolution
