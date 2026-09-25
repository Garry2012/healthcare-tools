"""Server-side understanding of the caller's words (IMPLEMENTATION.md §2.3, MVP scope).

Pipeline: red flag → service transfer → doctor (exact / variant / lexicon / Double
Metaphone) → department (lexicon, approved symptom routes, semantic hook) → decision.
Dates are resolved separately in `dates.py`. Everything is deterministic; below the
tenant's thresholds the resolver proposes, it never picks.
"""

from __future__ import annotations

import difflib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from .text import contains_phrase, native_form, normalise, phonetic_keys, tokens

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
class DoctorEntry:
    doctor_id: str
    name: str
    department_ids: tuple[str, ...]
    name_variants: tuple[str, ...] = ()
    localized_names: tuple[str, ...] = ()
    active: bool = True
    booking_policy: str = "BOOKABLE"


@dataclass(frozen=True, slots=True)
class DepartmentEntry:
    department_id: str
    name: str
    code: str | None = None
    localized_names: tuple[str, ...] = ()
    has_consultant: bool = True
    active: bool = True


@dataclass(frozen=True, slots=True)
class Directory:
    doctors: tuple[DoctorEntry, ...]
    departments: tuple[DepartmentEntry, ...]
    lexicon: tuple[LexiconTerm, ...]

    def terms(self, concept_type: str) -> list[LexiconTerm]:
        return [t for t in self.lexicon if t.approved and t.concept_type == concept_type]

    def department(self, department_id: str) -> DepartmentEntry | None:
        return next((d for d in self.departments if d.department_id == department_id), None)


@dataclass(frozen=True, slots=True)
class ResolverThresholds:
    doctor: float = 0.8
    department: float = 0.8
    suggestion: float = 0.7


class SemanticMatcher(Protocol):
    """Step 4 of §2.3: multilingual sentence similarity to department names.

    TODO(IMPLEMENTATION.md §2.3 step 4): plug in a LaBSE-class model once the lexicon has
    content. Until then `NoSemanticMatcher` keeps the resolver deterministic.
    """

    def match(self, text: str, departments: Sequence[DepartmentEntry]) -> list[tuple[str, float]]:
        ...


class NoSemanticMatcher:
    def match(self, text: str, departments: Sequence[DepartmentEntry]) -> list[tuple[str, float]]:
        return []


@dataclass(frozen=True, slots=True)
class DoctorMatch:
    doctor_id: str
    confidence: float
    matched_on: str  # NAME_EXACT | NAME_PHONETIC | NAME_VARIANT | LEXICON


@dataclass(frozen=True, slots=True)
class DepartmentMatch:
    department_id: str
    confidence: float
    matched_on: str  # LEXICON | SYMPTOM_ROUTE | SEMANTIC


@dataclass(slots=True)
class Resolution:
    action: str  # OFFER_SLOTS | CLARIFY | TRANSFER_EMERGENCY | TRANSFER_DESK | NO_SERVICE
    destination: str | None = None
    doctors: list[DoctorMatch] = field(default_factory=list)
    departments: list[DepartmentMatch] = field(default_factory=list)
    clarification_type: str | None = None
    clarification_options: list[tuple[str, str]] = field(default_factory=list)  # (kind, id)
    suggestions: list[str] = field(default_factory=list)  # department ids


# ---------------------------------------------------------------- matching


def _both_forms(text: str) -> tuple[str, str]:
    return normalise(text), native_form(text)


def _lexicon_hit(texts: Iterable[str], term: LexiconTerm) -> bool:
    for text in texts:
        latin, native = _both_forms(text)
        if contains_phrase(latin, term.latin) or contains_phrase(native, term.native):
            return True
    return False


def red_flag(texts: Iterable[str], directory: Directory) -> LexiconTerm | None:
    texts = [t for t in texts if t]
    return next((t for t in directory.terms("RED_FLAG") if _lexicon_hit(texts, t)), None)


def service_transfer(texts: Iterable[str], directory: Directory) -> LexiconTerm | None:
    texts = [t for t in texts if t]
    terms = sorted(directory.terms("SERVICE_TRANSFER"), key=lambda t: -len(t.latin))
    return next((t for t in terms if _lexicon_hit(texts, t)), None)


def _name_tokens(name: str) -> list[str]:
    return tokens(normalise(name, strip_honorifics=True))


def match_doctors(query: str, directory: Directory, *, allow_phonetic: bool) -> list[DoctorMatch]:
    """Score every active doctor; keep only the best tier."""
    q = _name_tokens(query)
    if not q:
        return []
    q_text = " ".join(q)
    doctor_terms = directory.terms("DOCTOR")
    scored: list[DoctorMatch] = []
    for doc in directory.doctors:
        if not doc.active:
            continue
        name = _name_tokens(doc.name)
        localized = [_name_tokens(n) for n in doc.localized_names]
        best: DoctorMatch | None = None
        if q == name or any(q == loc for loc in localized):
            best = DoctorMatch(doc.doctor_id, CONF_EXACT, "NAME_EXACT")
        elif set(q) <= set(name) or any(loc and set(q) <= set(loc) for loc in localized):
            best = DoctorMatch(doc.doctor_id, CONF_SUBSET, "NAME_EXACT")
        elif any(q_text == " ".join(_name_tokens(v)) for v in doc.name_variants):
            best = DoctorMatch(doc.doctor_id, CONF_VARIANT, "NAME_VARIANT")
        elif any(
            t.concept_id == doc.doctor_id and " ".join(_name_tokens(t.term)) == q_text
            for t in doctor_terms
        ):
            best = DoctorMatch(doc.doctor_id, CONF_LEXICON, "LEXICON")
        elif allow_phonetic:
            candidates = [name, *(_name_tokens(v) for v in doc.name_variants)]
            for cand in candidates:
                if cand and all(
                    len(tok) >= 3
                    and any(phonetic_keys(tok) & phonetic_keys(c) for c in cand if len(c) >= 3)
                    for tok in q
                ):
                    best = DoctorMatch(doc.doctor_id, CONF_PHONETIC, "NAME_PHONETIC")
                    break
        if best:
            scored.append(best)
    if not scored:
        return []
    top = max(m.confidence for m in scored)
    tier = CONF_SUBSET if top >= CONF_SUBSET else top
    return sorted((m for m in scored if m.confidence >= tier), key=lambda m: -m.confidence)


def _scan_utterance_for_doctors(utterance: str, directory: Directory) -> list[DoctorMatch]:
    """Without an explicit doctorName, only exact name tokens in the utterance count."""
    words = set(tokens(normalise(utterance, strip_honorifics=True)))
    hits: list[DoctorMatch] = []
    for doc in directory.doctors:
        if not doc.active:
            continue
        name = _name_tokens(doc.name)
        distinctive = [t for t in name if len(t) >= 3]
        if distinctive and set(distinctive) <= words:
            hits.append(DoctorMatch(doc.doctor_id, CONF_SUBSET, "NAME_EXACT"))
    return hits


def match_departments(
    texts: Sequence[str],
    directory: Directory,
    semantic: SemanticMatcher,
    threshold: float,
) -> list[DepartmentMatch]:
    texts = [t for t in texts if t]
    if not texts:
        return []
    found: dict[str, DepartmentMatch] = {}

    def keep(match: DepartmentMatch) -> None:
        dept = directory.department(match.department_id)
        if dept is None or not dept.active:
            return
        current = found.get(match.department_id)
        if current is None or match.confidence > current.confidence:
            found[match.department_id] = match

    for text in texts:
        latin, native = _both_forms(text)
        for dept in directory.departments:
            names = [dept.name, *(dept.localized_names), *([dept.code] if dept.code else [])]
            for n in names:
                n_latin, n_native = _both_forms(n)
                if latin == n_latin or native == n_native:
                    keep(DepartmentMatch(dept.department_id, CONF_DEPT_EXACT, "LEXICON"))
                elif len(n_latin) > 3 and contains_phrase(latin, n_latin):
                    keep(DepartmentMatch(dept.department_id, CONF_DEPT_CONTAINED, "LEXICON"))
        for kind, matched_on in (("DEPARTMENT", "LEXICON"), ("SYMPTOM_ROUTE", "SYMPTOM_ROUTE")):
            for term in directory.terms(kind):
                if latin == term.latin or native == term.native:
                    keep(DepartmentMatch(term.concept_id, CONF_DEPT_EXACT, matched_on))
                elif contains_phrase(latin, term.latin) or contains_phrase(native, term.native):
                    keep(DepartmentMatch(term.concept_id, CONF_DEPT_CONTAINED, matched_on))
    if not found:
        for text in texts:
            for dept_id, score in semantic.match(text, directory.departments):
                if score >= threshold:
                    keep(DepartmentMatch(dept_id, score, "SEMANTIC"))
    return sorted(
        (m for m in found.values() if m.confidence >= threshold), key=lambda m: -m.confidence
    )


def suggest_departments(texts: Sequence[str], directory: Directory, cutoff: float) -> list[str]:
    """Spelling-level near misses ("zoologist" → urologist). Proposals only."""
    vocabulary: dict[str, str] = {}
    for dept in directory.departments:
        if dept.active and dept.has_consultant:
            for word in tokens(normalise(dept.name)):
                if len(word) > 3:
                    vocabulary.setdefault(word, dept.department_id)
    for term in directory.terms("DEPARTMENT"):
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
    for _, dept_id in sorted(ranked, key=lambda r: -r[0]):
        if dept_id not in seen:
            seen.append(dept_id)
    return seen[:3]


# ---------------------------------------------------------------- decision


def resolve(
    *,
    utterance: str,
    directory: Directory,
    doctor_name: str | None = None,
    department: str | None = None,
    symptom_text: str | None = None,
    thresholds: ResolverThresholds | None = None,
    semantic: SemanticMatcher | None = None,
) -> Resolution:
    semantic = semantic or NoSemanticMatcher()
    thresholds = thresholds or ResolverThresholds()
    everything = [utterance, doctor_name or "", department or "", symptom_text or ""]

    flag = red_flag(everything, directory)
    if flag:
        return Resolution(action="TRANSFER_EMERGENCY", destination="emergency")
    service = service_transfer(everything, directory)
    if service:
        return Resolution(action="TRANSFER_DESK", destination=service.concept_id)

    if doctor_name:
        doctors = [
            m
            for m in match_doctors(doctor_name, directory, allow_phonetic=True)
            if m.confidence >= thresholds.doctor
        ]
    elif not department and not symptom_text:
        doctors = _scan_utterance_for_doctors(utterance, directory)
    else:
        doctors = []

    dept_texts = [t for t in (department, symptom_text) if t]
    if not dept_texts and not doctors:
        dept_texts = [utterance]
    departments = match_departments(dept_texts, directory, semantic, thresholds.department)
    departments = [
        d for d in departments if (entry := directory.department(d.department_id)) and entry.has_consultant
    ]

    resolution = Resolution(action="OFFER_SLOTS", doctors=doctors, departments=departments)

    if len(doctors) > 1:
        resolution.action = "CLARIFY"
        resolution.clarification_type = "WHICH_DOCTOR"
        resolution.clarification_options = [("doctor", m.doctor_id) for m in doctors]
        return resolution

    if len(doctors) == 1 and departments:
        doctor = next(d for d in directory.doctors if d.doctor_id == doctors[0].doctor_id)
        if not set(doctor.department_ids) & {d.department_id for d in departments}:
            resolution.action = "CLARIFY"
            resolution.clarification_type = "CONFIRM_INTERPRETATION"
            resolution.clarification_options = [("doctor", doctor.doctor_id)] + [
                ("department", d.department_id) for d in departments
            ]
        return resolution

    if doctors:
        return resolution

    if len(departments) > 1:
        top = departments[0].confidence
        leaders = [d for d in departments if d.confidence >= top]
        if len(leaders) > 1:
            resolution.action = "CLARIFY"
            resolution.clarification_type = "WHICH_DEPARTMENT"
            resolution.clarification_options = [("department", d.department_id) for d in leaders]
            return resolution
        resolution.departments = leaders
        return resolution

    if departments:
        return resolution

    probe = [t for t in (doctor_name, department, symptom_text, utterance) if t]
    suggestions = suggest_departments(probe, directory, thresholds.suggestion)
    if suggestions:
        resolution.action = "CLARIFY"
        resolution.clarification_type = "CONFIRM_INTERPRETATION"
        resolution.clarification_options = [("department", d) for d in suggestions]
        resolution.suggestions = suggestions
        return resolution

    if doctor_name or department or symptom_text:
        resolution.action = "NO_SERVICE"
        return resolution

    # No name, no department, no problem: "anyone available right now?"
    resolution.action = "OFFER_SLOTS"
    return resolution
