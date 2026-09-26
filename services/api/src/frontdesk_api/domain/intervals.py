"""When two periods clash. One definition for templates, extra sessions and pack validation."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import time


def overlaps[T: (time, str)](start_a: T, end_a: T, start_b: T, end_b: T) -> bool:
    """Half-open periods [start, end) overlap; touching ends (12:00-12:00) do not.
    Works for `time` values and zero-padded "HH:MM" strings alike."""
    return start_a < end_b and start_b < end_a


def weekly_clash[T: (time, str)](
    days_a: Iterable[str], start_a: T, end_a: T, days_b: Iterable[str], start_b: T, end_b: T
) -> bool:
    """Two weekly sessions clash when they share a weekday and their hours overlap."""
    return bool(set(days_a) & set(days_b)) and overlaps(start_a, end_a, start_b, end_b)
