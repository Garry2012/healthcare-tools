"""What a rollout must satisfy before it is applied: offline, no database.

Problems block `rollout apply`; notes are for the person signing the rollout off (a domain code
with no department, an answer missing in one language). Dialogues run through the same resolver
and knowledge search the API uses, with only the rollout's languages switched on.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .. import locales
from ..domain import knowledge, resolver
from ..domain.intervals import weekly_clash
from .compose import Composed
from .model import Dialogue, Rollout

_CONCEPTS = ("CATEGORY", "NEED_ROUTE", "RESOURCE", "RED_FLAG", "SERVICE_TRANSFER", "DAY_PART")


@dataclass(frozen=True)
class Report:
    problems: tuple[str, ...]
    notes: tuple[str, ...]


def _duplicates(ids: Iterable[str], what: str) -> list[str]:
    return [f"{what} {i!r} appears {n} times" for i, n in Counter(ids).items() if n > 1]


def _structure(rollout: Rollout, destinations: Mapping[str, str]) -> list[str]:
    problems: list[str] = []
    if unknown := [c for c in rollout.languages if c not in locales.AVAILABLE]:
        problems.append(f"no language module for {', '.join(unknown)}: add one under locales/ first")
    categories = {c.id for c in rollout.categories}
    resources = {r.id for r in rollout.resources}
    problems += _duplicates((c.id for c in rollout.categories), "category")
    problems += _duplicates((r.id for r in rollout.resources), "resource")
    problems += _duplicates((k.id for k in rollout.knowledge), "knowledge entry")
    for r in rollout.resources:
        if not r.categories:
            problems.append(f"{r.id}: needs at least one category")
        problems += [f"{r.id}: unknown category {c!r}" for c in r.categories if c not in categories]
        for i, a in enumerate(r.sessions):  # the same rule PUT /schedule-template enforces
            for b in r.sessions[:i]:
                if weekly_clash(a.days, a.start, a.end, b.days, b.start, b.end):
                    problems.append(f"{r.id}: sessions {b.key!r} and {a.key!r} overlap")
    targets = {"CATEGORY": categories, "NEED_ROUTE": categories, "RESOURCE": resources,
               "SERVICE_TRANSFER": set(destinations), "DAY_PART": {*locales.DAY_PARTS, "ANY"}}
    for kind, target, term, language in rollout.terms:
        if kind not in _CONCEPTS:
            problems.append(f"term {term!r}: unknown type {kind!r}")
        elif kind in targets and target not in targets[kind]:
            problems.append(f"term {kind} {term!r} points at unknown {target!r}")
        if language not in rollout.languages:
            problems.append(f"term {term!r} is in {language!r}, which this rollout does not switch on")
    for k in rollout.knowledge:
        if not k.questions or not k.answers:
            problems.append(f"knowledge {k.id}: needs questions and at least one answer")
        if k.action == "TRANSFER_DESK" and k.destination not in destinations:
            problems.append(f"knowledge {k.id}: unknown destination {k.destination!r}")
    return problems


def _notes(composed: Composed) -> list[str]:
    languages = composed.rollout.languages
    notes = list(composed.notes)
    for k in composed.rollout.knowledge:
        if missing := [lang for lang in languages if lang not in k.answers]:
            notes.append(f"knowledge {k.id}: no approved answer in {', '.join(missing)}")
    return notes


def _dialogue(line: Dialogue, directory: resolver.Directory, index: knowledge.LexicalIndex,
              thresholds: resolver.ResolverThresholds, answer_thresholds: knowledge.Thresholds) -> str | None:
    """None when the line behaves as written, else what happened instead."""
    if line.ask:
        decision = knowledge.decide(index.search(line.ask), answer_thresholds)
        got = decision.outcome
        entry = decision.hit.entry.entry_id if decision.hit else None
        if got != line.expect or (line.expect_answer and entry != line.expect_answer):
            return f"ask {line.ask!r}: expected {line.expect} {line.expect_answer or ''}, got {got} {entry or ''}"
        return None
    res = resolver.resolve(utterance=line.say or "", directory=directory, resource_name=line.resource_name,
                           category=line.category, need_text=line.need_text, thresholds=thresholds)
    offered = [kind_id for _, kind_id in res.clarification_options]  # "which one?" choices count too
    categories = [c.category_id for c in res.categories] + res.suggestions + offered
    resources = [r.resource_id for r in res.resources] + offered
    if (res.action != line.expect
            or (line.expect_category and line.expect_category not in categories)
            or (line.expect_resource and line.expect_resource not in resources)):
        return (f"say {line.say!r}: expected {line.expect} {line.expect_category or line.expect_resource or ''}, "
                f"got {res.action} {categories or resources or ''}")
    return None


def validate(composed: Composed, destinations: Mapping[str, str], thresholds: resolver.ResolverThresholds,
             answer_thresholds: knowledge.Thresholds) -> Report:
    rollout, pack = composed.rollout, composed.pack
    problems: list[str] = []
    if rollout.domain != pack.name:
        problems.append(f"rollout is for domain {rollout.domain!r}, not {pack.name!r}")
    problems += _structure(rollout, destinations)
    needed = pack.required_destinations() | {t for k, t, _, _ in rollout.terms if k == "SERVICE_TRANSFER"}
    problems += [f"transfer destinations lack {d!r}" for d in sorted(needed - set(destinations))]
    if problems:  # dialogues against broken data would only repeat these
        return Report(tuple(problems), tuple(_notes(composed)))

    before = locales.selected()
    locales.select(rollout.languages)
    try:
        directory = composed.directory()
        index = knowledge.LexicalIndex.build(composed.knowledge_entries())
        problems += [failure for line in rollout.dialogues
                     if (failure := _dialogue(line, directory, index, thresholds, answer_thresholds))]
    finally:
        locales.select(before)
    return Report(tuple(problems), tuple(_notes(composed)))
