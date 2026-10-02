"""Bounded TTL cache for permitted stable directory data (departments, doctor profiles). Live board
truth and routing decisions are never cached: they change within a call."""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from .config import Settings


class DirectoryCache:
    def __init__(self, settings: Settings, monotonic: Callable[[], float] = time.monotonic) -> None:
        self._ttl = settings.directory_cache_seconds
        self._max = settings.directory_cache_max_entries
        self._monotonic = monotonic
        self._items: OrderedDict[tuple[str, ...], tuple[float, Any]] = OrderedDict()

    def get(self, key: tuple[str, ...]) -> Any | None:
        entry = self._items.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if self._monotonic() >= expires_at:
            del self._items[key]
            return None
        self._items.move_to_end(key)
        return value

    def set(self, key: tuple[str, ...], value: Any) -> None:
        if self._ttl <= 0:
            return
        self._items[key] = (self._monotonic() + self._ttl, value)
        self._items.move_to_end(key)
        while len(self._items) > self._max:
            self._items.popitem(last=False)

    def clear(self) -> None:
        self._items.clear()
