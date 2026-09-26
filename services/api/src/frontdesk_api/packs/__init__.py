"""Domain packs (docs/architecture/TARGET.md A3).

A pack is data, never logic branches in the core: the escalation destination for red
flags, default transfer destinations, and the synthetic seed (directory, lexicon,
knowledge base, and a dated demo scenario). `DOMAIN_PACK` selects one per deployment.
"""

from __future__ import annotations

import importlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from functools import cache
from typing import Any, Protocol

from ..domain.intervals import weekly_clash

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


class ScenarioBuilder(Protocol):
    """What a pack's demo scenario may do. Owned here so packs stay data and never import the
    seeder (or the database behind it); `seed.Seeder` provides it."""

    today: date

    def next_weekday(self, weekday: int, *, include_today: bool = False) -> date: ...

    async def first_free(self, resource_id: str, on: date, session_n: str | None = None,
                         skip: int = 0) -> list[str]: ...

    async def book(self, slot_id: str, customer: CustomerSeed, *, channel: str = "AGENT") -> int: ...

    async def exception(self, **fields: Any) -> None: ...

    async def board(self, resource_id: str, n: str, **fields: Any) -> None: ...


Scenario = Callable[[ScenarioBuilder], Awaitable[dict[str, int]]]


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
    # Where the core sends a caller it cannot help (not understood, desk-only, no answer).
    desk_destination: str = "desk"


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
    if pack.desk_destination not in destinations:
        problems.append(f"desk {pack.desk_destination!r} is not a transfer destination")
    for r in pack.resources:
        problems += [f"{r.id}: unknown category {c!r}" for c in r.categories if c not in categories]
        if not r.categories:
            problems.append(f"{r.id}: needs at least one category")
        for i, a in enumerate(r.sessions):  # the same rule PUT /schedule-template enforces
            for b in r.sessions[:i]:
                if weekly_clash(a.days, a.start, a.end, b.days, b.start, b.end):
                    problems.append(f"{r.id}: sessions {b.key!r} and {a.key!r} overlap")
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
