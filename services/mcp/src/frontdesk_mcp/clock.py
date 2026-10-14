"""Injectable wall clock (facility-time decisions) and one monotonic deadline per tool invocation."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from zoneinfo import ZoneInfo


class Clock(Protocol):
    def now(self) -> datetime:  # timezone-aware
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    def __init__(self, at: datetime) -> None:
        if at.tzinfo is None:
            raise ValueError("FixedClock needs an aware datetime")
        self._at = at

    def now(self) -> datetime:
        return self._at


def local_now(clock: Clock, zone: ZoneInfo) -> datetime:
    return clock.now().astimezone(zone)


class DeadlineExceeded(Exception):
    """The invocation's total budget (pool wait, auth, every call, any retry) is spent."""


@dataclass(frozen=True)
class Budget:
    total: float
    exchange: float


class Deadline:
    """One invocation deadline carrying its own per-exchange cap."""

    def __init__(self, budget: Budget, monotonic: Callable[[], float] = time.monotonic) -> None:
        self._monotonic = monotonic
        self._end = monotonic() + budget.total
        self.cap = budget.exchange

    def remaining(self) -> float:
        return self._end - self._monotonic()

    @property
    def expired(self) -> bool:
        return self.remaining() <= 0

    def timeout(self) -> float:
        """The next exchange cannot exceed either its cap or the remaining total."""
        left = self.remaining()
        if left <= 0:
            raise DeadlineExceeded
        return min(left, self.cap)
