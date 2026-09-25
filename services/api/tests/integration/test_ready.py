"""/ready is green only when the database is reachable AND at the code's Alembic head."""

from __future__ import annotations

import uuid

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from healthcare_api.app import create_app

from .conftest import OWNER_URL, alembic, async_url


async def _status(settings) -> int:
    app = create_app(settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        code = (await c.get("/ready")).status_code
    await app.state.engine.dispose()
    return code


async def test_ready_tracks_migration_state(make_settings):
    name = f"ready_{uuid.uuid4().hex[:8]}"
    admin = create_async_engine(async_url(OWNER_URL), isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = OWNER_URL.rsplit("/", 1)[0] + f"/{name}"
    settings = make_settings(database_url=url)
    try:
        assert await _status(settings) == 503  # empty database: no schema at all
        alembic("upgrade", "head", url=url)
        assert await _status(settings) == 200
        alembic("downgrade", "base", url=url)
        assert await _status(settings) == 503  # behind the code's head
    finally:
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await admin.dispose()


async def test_ready_is_503_when_the_database_is_unreachable(make_settings):
    assert await _status(make_settings(database_url="postgresql://x:y@127.0.0.1:1/none")) == 503
