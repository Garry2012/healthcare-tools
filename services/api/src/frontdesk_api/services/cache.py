"""Per-process caches of read-mostly data, kept correct across replicas (TARGET.md A5).

Each cache is built from one or more named data sets. A writer bumps the set's row in
`cache_versions` inside its own transaction; a reader does one primary-key read of the
versions and rebuilds only when they differ from what its value was built from. The
version is read *before* the data, so a build that races a write is at worst stale for
exactly one request, and is rebuilt on the next.

Cached values must be plain data (dataclasses, tuples), never ORM instances.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import tables as t

DIRECTORY = "directory"  # resources, categories, templates' resource links, lexicon
KNOWLEDGE = "knowledge"


async def versions(session: AsyncSession, names: tuple[str, ...]) -> tuple[int, ...]:
    rows = dict((await session.execute(
        select(t.CacheVersion.name, t.CacheVersion.version).where(t.CacheVersion.name.in_(names))
    )).all())
    return tuple(rows.get(name, 0) for name in names)


async def bump(session: AsyncSession, *names: str) -> None:
    """Call inside the writer's transaction, before its commit."""
    result = await session.execute(
        update(t.CacheVersion).where(t.CacheVersion.name.in_(names))
        .values(version=t.CacheVersion.version + 1, updated_at=func.now())
    )
    if result.rowcount != len(set(names)):
        # A missing row would leave every replica serving stale data forever.
        raise RuntimeError(f"cache_versions is missing a row for one of {sorted(set(names))}")


@dataclass(slots=True)
class VersionedCache[T]:
    names: tuple[str, ...]
    build: Callable[[AsyncSession], Awaitable[T]]
    _value: T | None = None
    _built_from: tuple[int, ...] | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    builds: int = 0  # observable in tests and metrics

    async def get(self, session: AsyncSession) -> T:
        current = await versions(session, self.names)
        if self._value is not None and self._built_from == current:
            return self._value
        async with self._lock:
            if self._value is None or self._built_from != current:
                self._value = await self.build(session)
                self._built_from = current
                self.builds += 1
            return self._value

    def clear(self) -> None:
        self._value, self._built_from = None, None
