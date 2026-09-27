"""Domain packs (docs/architecture/TARGET.md A3, A10): the middle layer of core -> domain -> rollout.

A pack is what every rollout of one domain shares, as data the core reads, never branches on:
the category codes its words point at, a versioned baseline of those words (department and
symptom words, danger signs, severity and service phrases) in every language it knows, where
transfers go by default, and its defaults for core settings. It holds no tenant's data: a
rollout (`frontdesk_api.rollouts`) brings departments, resources, schedules, local words and
approved answers, and chooses which languages are on. `DOMAIN_PACK` selects one per deployment.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from functools import cache

from ..locales import AVAILABLE, DAY_PARTS

LexiconRow = tuple[str, str, str, str]  # (concept_type, target, term, language)

# Concept types a baseline may carry, and what their target is.
_BY_CODE = ("CATEGORY", "NEED_ROUTE")  # target: a category code of the domain
_BY_DESTINATION = ("SERVICE_TRANSFER",)  # target: a transfer destination key
_FREE_LABEL = ("RED_FLAG",)  # target: a label; the action is always the emergency transfer
_DAY_PART = ("DAY_PART",)  # target: MORNING | AFTERNOON | EVENING | ANY (words beyond the locales)


@dataclass(frozen=True)
class Pack:
    name: str
    version: str  # recorded with the baseline rows a rollout loads; bump when the baseline changes
    escalation_destination: str  # where a red flag transfers to
    transfer_destinations: dict[str, str]  # default destination names; a rollout may replace them
    categories: dict[str, str]  # category code -> its usual name
    baseline: tuple[LexiconRow, ...]
    # Where the core sends a caller it cannot help (not understood, desk-only, no answer).
    desk_destination: str = "desk"
    # Defaults for core settings (field name -> value as a rollout would write it); a rollout's
    # own value always wins. Identity settings (timezone, phone, currency, languages) never have one.
    settings: dict[str, str] = field(default_factory=dict)

    def required_destinations(self) -> set[str]:
        """Destination keys the core may route a call of this domain to."""
        needed = {self.escalation_destination, self.desk_destination}
        return needed | {target for kind, target, _, _ in self.baseline if kind in _BY_DESTINATION}


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
    """Checks a pack must pass before it ships (run by the unit tests)."""
    problems: list[str] = []
    destinations = set(pack.transfer_destinations)
    if pack.escalation_destination not in destinations:
        problems.append(f"escalation {pack.escalation_destination!r} is not a transfer destination")
    if pack.desk_destination not in destinations:
        problems.append(f"desk {pack.desk_destination!r} is not a transfer destination")
    seen: set[tuple[str, str, str]] = set()
    for kind, target, term, language in pack.baseline:
        where = f"baseline {kind} {term!r}"
        if kind in _BY_CODE and target not in pack.categories:
            problems.append(f"{where} points at unknown category code {target!r}")
        elif kind in _BY_DESTINATION and target not in destinations:
            problems.append(f"{where} points at unknown destination {target!r}")
        elif kind in _DAY_PART and target not in (*DAY_PARTS, "ANY"):
            problems.append(f"{where} points at unknown day part {target!r}")
        elif kind not in (*_BY_CODE, *_BY_DESTINATION, *_FREE_LABEL, *_DAY_PART):
            problems.append(f"{where}: a domain baseline cannot carry {kind} rows (they are a rollout's)")
        if language not in AVAILABLE:
            problems.append(f"{where}: no language module for {language!r}")
        key = (kind, term.casefold(), language)
        if key in seen:
            problems.append(f"{where} ({language}) appears twice")
        seen.add(key)
    problems += [f"setting {k!r} is not a tenant setting" for k in pack.settings if not k.startswith("tenant_")]
    return problems
