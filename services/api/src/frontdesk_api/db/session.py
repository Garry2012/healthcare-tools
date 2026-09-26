"""Async engine and session factory. The runtime role has DML privileges only."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextvars import ContextVar
from dataclasses import dataclass

from fastapi import Request
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..config import Settings


@dataclass(slots=True)
class DbStats:
    """Round trips and time spent in the database for one request (reported in Server-Timing)."""

    queries: int = 0
    seconds: float = 0.0


db_stats_var: ContextVar[DbStats | None] = ContextVar("db_stats", default=None)


def _instrument(engine: AsyncEngine) -> None:
    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        conn.info["query_started"] = time.perf_counter()

    @event.listens_for(engine.sync_engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        stats = db_stats_var.get()
        if stats is not None:
            stats.queries += 1
            stats.seconds += time.perf_counter() - conn.info.pop("query_started", time.perf_counter())


def make_engine(settings: Settings) -> AsyncEngine:
    connect_args: dict[str, object] = {"server_settings": {"application_name": "frontdesk-api"}}
    if settings.database_disable_prepared_statements:
        connect_args["statement_cache_size"] = 0
    else:
        connect_args["server_settings"]["statement_timeout"] = str(settings.database_statement_timeout_ms)
    engine = create_async_engine(
        settings.async_database_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_pool_size,
        pool_pre_ping=True,
        pool_timeout=settings.database_pool_timeout_seconds,
        # Statement parameters carry names, phones and symptoms: never in error messages or logs.
        hide_parameters=True,
        connect_args=connect_args,
    )
    _instrument(engine)
    return engine


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    async with factory() as session:
        yield session
