"""Independent expectations, written from the contract text only.

Nothing here imports production code. Each function restates a rule of
docs/frontdesk-api/openapi.yaml (`getAvailability` description, `CapacitySpec`, `Slot.expectedWindow`,
`TemplateSession`) and IMPLEMENTATION.md §2.2, so a test can compare what the service returns with
what the specification says it must return.

Spec text restated (IMPLEMENTATION.md §2.2, openapi getAvailability step 4):
  capacity.total   = FIXED value | PER_HOUR value × hours | tenant default
  walkInReserve    = ceil(total × walkInReservePercent / 100)
  slots            = positions 1..(total − walkInReserve)       [SEQUENCE]
                   | start..end step slotMinutes                [TIMED]
  intervalMinutes  = 60 / capacity.value [PER_HOUR] | sessionMinutes / total [FIXED or DEFAULT]
  boundary(n)      = min(expectedStartOrStart + floor(n × intervalMinutes), end)
  expectedWindow(p)= [boundary(p−1), boundary(p)]
  arriveBy         = min(board.lastArrivalTime, end − lastArrivalOffsetMinutes)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction


def hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def minutes_of(clock: str) -> int:
    h, m = clock.split(":")
    return int(h) * 60 + int(m)


@dataclass(frozen=True)
class SessionSpec:
    """One template session as a test declares it (the same fields the staff API accepts)."""

    start: str
    end: str
    model: str = "SEQUENCE"  # SEQUENCE | TIMED
    mode: str = "PER_HOUR"  # FIXED | PER_HOUR | DEFAULT
    value: int | None = 4
    reserve_percent: int = 0
    slot_minutes: int | None = None
    last_arrival_offset: int = 15

    @property
    def minutes(self) -> int:
        return minutes_of(self.end) - minutes_of(self.start)


def expected_total(spec: SessionSpec, default_capacity: int = 12) -> int:
    """CapacitySpec: FIXED value | PER_HOUR value × session hours | tenant default."""
    if spec.mode == "FIXED":
        return int(spec.value)
    if spec.mode == "PER_HOUR":
        return math.floor(Fraction(spec.value) * Fraction(spec.minutes, 60))
    return default_capacity


def expected_reserve(total: int, percent: int) -> int:
    return math.ceil(Fraction(total * percent, 100))


def expected_offered(spec: SessionSpec, default_capacity: int = 12) -> int:
    total = expected_total(spec, default_capacity)
    return max(0, total - expected_reserve(total, spec.reserve_percent))


def expected_sequence_windows(
    spec: SessionSpec, *, default_capacity: int = 12, expected_start: str | None = None
) -> dict[int, tuple[str, str]]:
    """position -> (from, to) for every offered SEQUENCE position (Slot.expectedWindow)."""
    total = expected_total(spec, default_capacity)
    offered = expected_offered(spec, default_capacity)
    if spec.mode == "PER_HOUR":
        interval = Fraction(60, spec.value)
    else:
        interval = Fraction(spec.minutes, total)
    origin = minutes_of(expected_start or spec.start)
    end = minutes_of(spec.end)

    def boundary(n: int) -> int:
        return min(origin + math.floor(n * interval), end)

    return {p: (hhmm(boundary(p - 1)), hhmm(boundary(p))) for p in range(1, offered + 1)}


def expected_timed_grid(spec: SessionSpec) -> list[tuple[str, str]]:
    """TIMED: slots = start..end step slotMinutes (every full slot that fits in the session)."""
    step = spec.slot_minutes
    start, end = minutes_of(spec.start), minutes_of(spec.end)
    return [(hhmm(m), hhmm(m + step)) for m in range(start, end - step + 1, step)]


def arrive_by(spec: SessionSpec, last_arrival_time: str | None = None) -> str:
    candidates = [minutes_of(spec.end) - spec.last_arrival_offset]
    if last_arrival_time:
        candidates.append(minutes_of(last_arrival_time))
    return hhmm(min(candidates))


def window_overlaps(window: tuple[str, str], lo: str, hi: str) -> bool:
    return minutes_of(window[0]) < minutes_of(hi) and minutes_of(lo) < minutes_of(window[1])
