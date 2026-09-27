"""Demo scenarios: dated bookings, exceptions and board entries for the demo rollouts.

Test and demo data, not part of any rollout's contract: a real rollout is its data files only.
`frontdesk-api seed` runs the scenario named after the rollout (if any) after applying it, and
refuses ENV=production. Scenarios only use `ScenarioBuilder`, which `seed.Seeder` provides.
"""

from __future__ import annotations

import importlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol


@dataclass(frozen=True)
class Customer:
    name: str
    phone: str
    caller: str | None  # E.164 network number the booking was made from
    relation: str = "SELF"
    language: str = "en"
    reason: str | None = None


class ScenarioBuilder(Protocol):
    """What a scenario may do. Owned here so scenarios never import the seeder or the database."""

    today: date

    def next_weekday(self, weekday: int, *, include_today: bool = False) -> date: ...

    async def first_free(self, resource_id: str, on: date, session_n: str | None = None,
                         skip: int = 0) -> list[str]: ...

    async def book(self, slot_id: str, customer: Customer, *, channel: str = "AGENT") -> int: ...

    async def exception(self, **fields: Any) -> None: ...

    async def board(self, resource_id: str, n: str, **fields: Any) -> None: ...


Scenario = Callable[[ScenarioBuilder], Awaitable[dict[str, int]]]

# Rollout id -> module in this package holding its `scenario`.
_MODULES = {"demo-hospital": "hospital", "demo-hotel": "hotel"}


def scenario_for(rollout_id: str) -> Scenario | None:
    module = _MODULES.get(rollout_id)
    return importlib.import_module(f"{__name__}.{module}").scenario if module else None
