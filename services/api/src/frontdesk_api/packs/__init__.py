"""Domain packs (docs/architecture/TARGET.md A3).

A pack is data, never logic branches in the core: the escalation destination for red
flags, default transfer destinations, and the synthetic seed (directory, lexicon,
knowledge base, and a dated demo scenario). `DOMAIN_PACK` selects one per deployment.
"""

from __future__ import annotations

import importlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from functools import cache
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..seed import Seeder

ALL_DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


@dataclass(frozen=True)
class CategorySeed:
    id: str
    code: str
    name: str
    localized: dict[str, str] = field(default_factory=dict)
    offers_bookings: bool = True


@dataclass(frozen=True)
class SessionSeed:
    key: str  # suffix of the templateSessionId
    label: str
    days: tuple[str, ...]
    start: str
    end: str
    mode: str = "PER_HOUR"
    value: int | None = 4
    model: str = "SEQUENCE"
    slot_minutes: int | None = None
    reserve: int = 25


@dataclass(frozen=True)
class ResourceSeed:
    id: str
    name: str
    categories: tuple[str, ...]
    localized: dict[str, str] = field(default_factory=dict)
    gender: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    price: int | None = None
    price_confirmed: bool = True
    attendance: str = "REGULAR"
    policy: str = "BOOKABLE"
    data_confirmed: bool = True
    variants: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    sessions: tuple[SessionSeed, ...] = ()


@dataclass(frozen=True)
class CustomerSeed:
    name: str
    phone: str
    caller: str | None  # E.164 network number the booking was made from
    relation: str = "SELF"
    language: str = "en"
    reason: str | None = None


@dataclass(frozen=True)
class KnowledgeSeed:
    """One approved answer. `questions` are ways callers ask, in any language or script."""

    id: str
    topic: str
    questions: tuple[str, ...]
    answers: dict[str, str]  # language -> approved spoken answer
    action: str = "ANSWER"  # ANSWER | TRANSFER_DESK
    destination: str | None = None


LexiconRow = tuple[str, str, str, str]  # (concept_type, concept_id, term, language)
Scenario = Callable[["Seeder"], Awaitable[dict[str, int]]]


@dataclass(frozen=True)
class Pack:
    name: str
    escalation_destination: str
    transfer_destinations: dict[str, str]
    categories: tuple[CategorySeed, ...]
    resources: tuple[ResourceSeed, ...]
    lexicon: tuple[LexiconRow, ...]
    knowledge: tuple[KnowledgeSeed, ...] = ()
    scenario: Scenario | None = None


@cache
def load(name: str) -> Pack:
    if not name.isidentifier():
        raise ValueError(f"DOMAIN_PACK {name!r} is not a valid pack name")
    try:
        module = importlib.import_module(f"{__name__}.{name}")
    except ModuleNotFoundError as exc:
        raise ValueError(f"Unknown DOMAIN_PACK {name!r}") from exc
    pack = module.PACK
    if not isinstance(pack, Pack):
        raise TypeError(f"{module.__name__}.PACK must be a Pack")
    return pack


def validate(pack: Pack) -> list[str]:
    """Referential checks a pack must pass before it ships (run by the unit tests)."""
    problems: list[str] = []
    categories = {c.id for c in pack.categories}
    resources = {r.id for r in pack.resources}
    destinations = set(pack.transfer_destinations)
    if pack.escalation_destination not in destinations:
        problems.append(f"escalation {pack.escalation_destination!r} is not a transfer destination")
    for r in pack.resources:
        problems += [f"{r.id}: unknown category {c!r}" for c in r.categories if c not in categories]
        if not r.categories:
            problems.append(f"{r.id}: needs at least one category")
    targets = {"CATEGORY": categories, "NEED_ROUTE": categories, "RESOURCE": resources,
               "SERVICE_TRANSFER": destinations, "DAY_PART": {"MORNING", "AFTERNOON", "EVENING", "ANY"}}
    for concept_type, concept_id, term, _ in pack.lexicon:
        if concept_type in targets and concept_id not in targets[concept_type]:
            problems.append(f"lexicon {concept_type} {term!r} points at unknown {concept_id!r}")
    seen: set[str] = set()
    for k in pack.knowledge:
        if k.id in seen:
            problems.append(f"knowledge {k.id}: duplicate id")
        seen.add(k.id)
        if not k.questions or not k.answers:
            problems.append(f"knowledge {k.id}: needs questions and at least one answer")
        if k.action == "TRANSFER_DESK" and k.destination not in destinations:
            problems.append(f"knowledge {k.id}: unknown destination {k.destination!r}")
    return problems
