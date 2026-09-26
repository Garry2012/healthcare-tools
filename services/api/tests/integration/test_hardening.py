"""Operational hardening: no customer data in SQL error logs, bounded request size, deadlines
on voice reads, and cache versions that can never silently stop refreshing."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text

from frontdesk_api.services import cache, search

from .conftest import call


async def test_sql_parameters_never_reach_logs(app):
    # Parameters of a failed statement carry names, phones and symptoms.
    assert app.state.engine.sync_engine.hide_parameters is True


async def test_oversized_body_is_refused_before_parsing(client):
    body = {"utterance": "x" * 70_000, "language": "en"}
    r = await client.post("/agent/availability-search", headers=call(), json=body)
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "VALIDATION_FAILED"


async def test_slow_availability_read_degrades_to_could_not_check(client, app, monkeypatch):
    async def stuck(*args, **kwargs):
        await asyncio.sleep(30)

    monkeypatch.setattr(search, "agent_search", stuck)
    app.state.settings = app.state.settings.model_copy(update={"read_timeout_seconds": 0.3})
    loop = asyncio.get_running_loop()
    started = loop.time()
    r = await client.post("/agent/availability-search", headers=call(),
                          json={"utterance": "Dr Garima", "language": "en"})
    assert loop.time() - started < 2
    assert r.status_code == 200 and r.json()["outcome"] == "COULD_NOT_CHECK"


async def test_bump_fails_loudly_when_the_version_row_is_missing(app):
    async with app.state.sessionmaker() as session:
        await session.execute(text("DELETE FROM cache_versions WHERE name = 'knowledge'"))
        with pytest.raises(RuntimeError, match="cache_versions"):
            await cache.bump(session, cache.KNOWLEDGE)
        await session.rollback()
