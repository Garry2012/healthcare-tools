"""Core + domain + rollout: the data one deployment actually serves.

The domain's baseline is filtered to the rollout's languages and its category codes are resolved
to the rollout's categories. A rollout term replaces the baseline's meaning of the same words
(e.g. "thyroid" to Endocrinology where there is one); danger signs are add-only, never replaced.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ..domain.knowledge import Entry
from ..domain.resolver import CategoryEntry, Directory, LexiconTerm, ResourceEntry
from ..domain.text import normalise
from ..packs import LexiconRow, Pack
from .model import Rollout

BASELINE = "DOMAIN_BASELINE"  # lexicon source of rows that come from the domain pack
ROLLOUT = "PROVIDER"  # lexicon source of the rollout's own rows
_ADD_ONLY = ("RED_FLAG",)


@dataclass(frozen=True)
class Composed:
    pack: Pack
    rollout: Rollout
    lexicon: tuple[tuple[LexiconRow, str], ...]  # (row, source); row targets are ids here
    notes: tuple[str, ...]  # what the baseline could not attach to (not errors)

    def directory(self) -> Directory:
        """The resolver's view, as the API builds it from the database after `rollout apply`."""
        return Directory(
            resources=tuple(
                ResourceEntry(resource_id=r.id, name=r.name, category_ids=r.categories, name_variants=r.variants,
                              localized_names=tuple(r.names.values()), booking_policy=r.policy)
                for r in self.rollout.resources
            ),
            categories=tuple(
                CategoryEntry(category_id=c.id, name=c.name, code=c.code, localized_names=tuple(c.names.values()),
                              offers_bookings=c.bookable)
                for c in self.rollout.categories
            ),
            lexicon=tuple(LexiconTerm(*row) for row, _ in self.lexicon),
        )

    def knowledge_entries(self) -> tuple[Entry, ...]:
        return tuple(Entry(k.id, k.topic, k.questions, k.answers, k.action, k.destination)
                     for k in self.rollout.knowledge)


def compose(pack: Pack, rollout: Rollout) -> Composed:
    by_code: dict[str, list[str]] = defaultdict(list)
    for category in rollout.categories:
        by_code[category.code].append(category.id)
    replaced = {(kind, normalise(term), language) for kind, _, term, language in rollout.terms
                if kind not in _ADD_ONLY}
    languages = set(rollout.languages)

    rows: dict[LexiconRow, str] = {}
    unplaced: set[str] = set()
    for kind, target, term, language in pack.baseline:
        if language not in languages or (kind, normalise(term), language) in replaced:
            continue
        if kind in ("CATEGORY", "NEED_ROUTE"):
            if not by_code.get(target):
                unplaced.add(target)
            for category_id in by_code.get(target, ()):
                rows.setdefault((kind, category_id, term, language), BASELINE)
        else:
            rows.setdefault((kind, target, term, language), BASELINE)
    for row in rollout.terms:
        rows.setdefault(row, ROLLOUT)
    notes = tuple(f"no category has the domain code {code!r} ({pack.categories.get(code, '?')}): "
                  f"its department and symptom words are not loaded" for code in sorted(unplaced))
    return Composed(pack, rollout, tuple(rows.items()), notes)
