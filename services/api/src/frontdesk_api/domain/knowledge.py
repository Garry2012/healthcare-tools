"""Knowledge-base retrieval over approved answers (docs/architecture/TARGET.md A4).

Deterministic and in memory: every question variant and the caller's words go through the
resolver's normaliser (NFC, lower-case, Indic scripts transliterated to Latin), then each
entry is scored by its best-matching variant:

  phrase  — the whole variant appears in the caller's words              → 1.0
  tokens  — IDF-weighted F-score of shared tokens (variant recall weighs double)

Below the tenant's thresholds the retriever proposes (CLARIFY) or declines (NO_ANSWER); it
never picks. `Retriever` is the seam for a document/embedding source later.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from .text import STOPWORDS, contains_phrase, normalise, tokens

CONF_PHRASE = 1.0


@dataclass(frozen=True, slots=True)
class Entry:
    entry_id: str
    topic: str
    questions: tuple[str, ...]
    answers: dict[str, str]
    action: str = "ANSWER"  # ANSWER | TRANSFER_DESK
    destination: str | None = None
    source: str = "CURATED"  # CURATED | DOCUMENT


@dataclass(frozen=True, slots=True)
class Hit:
    entry: Entry
    score: float
    matched_question: str
    # Content words of the question that no approved question contains ("ICU" in "visiting hours
    # for ICU"): the answer may be about something else, so it is confirmed, not spoken.
    uncovered: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Thresholds:
    answer: float = 0.6
    clarify: float = 0.35
    margin: float = 0.1  # the best entry must beat the runner-up by this much to answer


class Retriever(Protocol):
    def search(self, query: str, limit: int = 3) -> list[Hit]: ...


def _terms(text: str) -> list[str]:
    return [t for t in tokens(normalise(text)) if t not in STOPWORDS and len(t) > 1]


@dataclass(slots=True)
class _Variant:
    entry: Entry
    text: str
    phrase: str  # normalised, stopwords kept: phrase containment must see the real words
    terms: frozenset[str]


@dataclass(slots=True)
class LexicalIndex:
    """Built once per knowledge-base version; `search` is pure CPU over a few hundred variants."""

    variants: list[_Variant] = field(default_factory=list)
    idf: dict[str, float] = field(default_factory=dict)

    @classmethod
    def build(cls, entries: Iterable[Entry]) -> LexicalIndex:
        variants = [
            _Variant(entry, q, " ".join(tokens(normalise(q))), frozenset(_terms(q)))
            for entry in entries
            for q in entry.questions
        ]
        df = Counter(term for v in variants for term in v.terms)
        n = max(len(variants), 1)
        idf = {term: math.log(1 + n / count) for term, count in df.items()}
        return cls(variants, idf)

    def _weight(self, terms: Iterable[str]) -> float:
        # Unknown words weigh like the rarest known word: they dilute precision honestly.
        rare = max(self.idf.values(), default=1.0)
        return sum(self.idf.get(t, rare) for t in terms)

    def search(self, query: str, limit: int = 3) -> list[Hit]:
        phrase = " ".join(tokens(normalise(query)))
        q_terms = frozenset(_terms(query))
        if not phrase:
            return []
        uncovered = tuple(sorted(t for t in q_terms if t not in self.idf))
        best: dict[str, Hit] = {}
        for v in self.variants:
            if v.phrase and contains_phrase(phrase, v.phrase):
                score = CONF_PHRASE
            elif v.terms and q_terms:
                shared = v.terms & q_terms
                if not shared:
                    continue
                recall = self._weight(shared) / self._weight(v.terms)
                precision = self._weight(shared) / self._weight(q_terms)
                score = 3 * recall * precision / (2 * precision + recall)  # F-beta, beta² = 2
            else:
                continue
            current = best.get(v.entry.entry_id)
            if current is None or score > current.score:
                best[v.entry.entry_id] = Hit(v.entry, round(score, 3), v.text, uncovered)
        return sorted(best.values(), key=lambda h: (-h.score, h.entry.entry_id))[:limit]


@dataclass(frozen=True, slots=True)
class Decision:
    outcome: str  # ANSWERED | CLARIFICATION_NEEDED | NO_ANSWER
    hit: Hit | None = None
    options: tuple[Hit, ...] = ()


def decide(hits: Sequence[Hit], thresholds: Thresholds) -> Decision:
    if not hits or hits[0].score < thresholds.clarify:
        return Decision("NO_ANSWER")
    top = hits[0]
    if top.uncovered:
        # The caller asked about something no approved question mentions: confirm first.
        return Decision("CLARIFICATION_NEEDED", options=tuple(h for h in hits if h.score >= thresholds.clarify)[:3])
    runner_up = hits[1].score if len(hits) > 1 else 0.0
    if top.score >= thresholds.answer and top.score - runner_up >= thresholds.margin:
        return Decision("ANSWERED", hit=top)
    close = tuple(h for h in hits if h.score >= thresholds.clarify)
    if len(close) == 1 and top.score >= thresholds.answer:
        return Decision("ANSWERED", hit=top)
    return Decision("CLARIFICATION_NEEDED", options=close[:3])


def pick_answer(entry: Entry, language: str) -> tuple[str, str]:
    """The approved text in the caller's language, else English, else any; never a translation."""
    for lang in (language, language.split("-")[0], "en"):
        if lang in entry.answers:
            return lang, entry.answers[lang]
    lang = next(iter(entry.answers))
    return lang, entry.answers[lang]
