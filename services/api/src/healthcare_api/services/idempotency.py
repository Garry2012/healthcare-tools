"""Idempotency store (IMPLEMENTATION.md §2.5).

The key row is inserted *first*, inside the same transaction as the write. A concurrent
request with the same key blocks on the primary key until the first commits, then sees
the stored response and replays it; if the first rolls back, its row disappears and the
second proceeds. Only successful responses are stored.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import tables as t
from ..errors import ApiError

TTL = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class Outcome:
    status: int
    body: dict[str, Any]
    replay: bool = False


def request_hash(method: str, path: str, body: Any, caller_number: str | None) -> str:
    canonical = json.dumps(
        {"m": method, "p": path, "b": body, "c": caller_number}, sort_keys=True, default=str
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


async def run(
    session: AsyncSession,
    key: str | None,
    fingerprint: str,
    operation: Callable[[], Awaitable[tuple[int, dict[str, Any]]]],
) -> Outcome:
    """Run `operation` exactly once per key. The caller's session must be unused."""
    if key is None:
        status, body = await operation()
        await session.commit()
        return Outcome(status, body)

    await session.execute(
        delete(t.IdempotencyKey).where(
            t.IdempotencyKey.key == key, t.IdempotencyKey.created_at < func.now() - TTL
        )
    )
    claimed = await session.scalar(
        insert(t.IdempotencyKey)
        .values(key=key, request_hash=fingerprint, status=0, body=None)
        .on_conflict_do_nothing(index_elements=["key"])
        .returning(t.IdempotencyKey.key)
    )
    if claimed is None:
        stored = await session.get(t.IdempotencyKey, key)
        # Read before rollback: rollback expires the instance.
        stored_hash, stored_body = (stored.request_hash, stored.body) if stored else (None, None)
        await session.rollback()
        if stored_body is None:
            raise ApiError("CONFLICT", "A request with this Idempotency-Key is still in progress.")
        if stored_hash != fingerprint:
            raise ApiError(
                "IDEMPOTENCY_CONFLICT",
                "This Idempotency-Key was already used with a different request.",
            )
        return Outcome(200, stored_body, replay=True)

    try:
        status, body = await operation()
    except ApiError:
        await session.rollback()
        raise
    await session.execute(
        update(t.IdempotencyKey)
        .where(t.IdempotencyKey.key == key)
        .values(status=status, body=body)
    )
    await session.commit()
    return Outcome(status, body)


async def purge_expired(session: AsyncSession) -> int:
    result = await session.execute(
        delete(t.IdempotencyKey).where(t.IdempotencyKey.created_at < func.now() - TTL)
    )
    await session.commit()
    return result.rowcount or 0

