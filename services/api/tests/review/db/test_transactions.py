"""Database-level guarantees, exercised with separate connections and an explicit interleaving,
so the test proves the constraint (not the scheduler) decides the race."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from frontdesk_api import schemas as s
from frontdesk_api.errors import ApiError
from frontdesk_api.services import bookings

from ..conftest import API_ROOT, OWNER_URL, async_url
from ..oracle import SessionSpec

pytestmark = pytest.mark.postgres
NAME = "Dr Zenobia Quillfeather"


def _request(slot_id: str, name: str, phone: str) -> s.AgentBookRequest:
    return s.AgentBookRequest(slot_id=slot_id, customer=s.BookCustomer(name=name, phone=phone), language="en")


async def test_second_writer_blocks_on_the_first_and_then_loses(app, desk, clock, review_settings, owner_db):
    """Two transactions book one slot. The first has inserted and not committed; the second must
    wait on the live-slot unique index, then fail cleanly once the first commits."""
    built = await desk.resource(NAME, {"s1": SessionSpec("15:00", "17:00", mode="PER_HOUR", value=4)})
    day = clock.today + timedelta(days=1)
    (session,) = await desk.availability(built.resource_id, day)
    slot = session["slots"][0]["slotId"]
    maker = app.state.sessionmaker

    async with maker() as first, maker() as second:
        won = await bookings.book(first, review_settings, _request(slot, "First Writer", "9812600001"),
                                  channel="AGENT", call_id="t1", caller_number="+919812600001", actor="t1")
        assert won.created
        racing = asyncio.create_task(bookings.book(
            second, review_settings, _request(slot, "Second Writer", "9812600002"), channel="AGENT",
            call_id="t2", caller_number="+919812600002", actor="t2"))
        await asyncio.sleep(0.3)
        assert not racing.done(), "the second writer did not wait for the first transaction"
        await first.commit()
        with pytest.raises(ApiError) as lost:
            await racing
        assert lost.value.code == "SLOT_UNAVAILABLE"
        await second.rollback()

    async with owner_db.connect() as conn:
        live = (await conn.execute(text("SELECT customer_name FROM bookings WHERE slot_id = :s"), {"s": slot})).all()
    assert [r.customer_name for r in live] == ["First Writer"]


async def test_the_live_slot_index_refuses_a_duplicate_even_without_the_application(app, desk, clock, owner_db):
    """The guarantee is the database's: a direct second INSERT of a live booking for a held slot fails."""
    built = await desk.resource(NAME, {"s1": SessionSpec("15:00", "17:00", mode="PER_HOUR", value=4)})
    day = clock.today + timedelta(days=1)
    (session,) = await desk.availability(built.resource_id, day)
    slot = session["slots"][0]["slotId"]
    insert = text(
        "INSERT INTO bookings (id, confirmation_code, status, customer_name, customer_name_normalized, phone, "
        "resource_id, session_id, slot_id, date, language, created_via, follow_up) VALUES "
        "(:id, '0001', :status, 'X', 'x', '9812600009', :r, :sid, :slot, :d, 'en', 'DESK', 'NONE')")
    params = {"r": built.resource_id, "sid": session["sessionId"], "slot": slot, "d": day}
    async with owner_db.begin() as conn:
        await conn.execute(insert, {**params, "id": "bkg_direct_1", "status": "BOOKED"})
        await conn.execute(insert, {**params, "id": "bkg_direct_2", "status": "CANCELLED_BY_CUSTOMER"})
    with pytest.raises(IntegrityError):
        async with owner_db.begin() as conn:
            await conn.execute(insert, {**params, "id": "bkg_direct_3", "status": "ARRIVED"})


def _alembic(url: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=API_ROOT,
                          env={**os.environ, "DATABASE_URL": url}, capture_output=True, text=True)


async def test_migrations_build_a_clean_database_downgrade_and_rebuild(owner_db):
    """Clean start: an empty database migrates to head, every revision downgrades, and head again."""
    scratch = "frontdesk_review_scratch"
    admin = create_async_engine(async_url(OWNER_URL), isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text(f"DROP DATABASE IF EXISTS {scratch}"))
        await conn.execute(text(f"CREATE DATABASE {scratch}"))
    url = OWNER_URL.rsplit("/", 1)[0] + f"/{scratch}"
    try:
        for step in (("upgrade", "head"), ("downgrade", "base"), ("upgrade", "head")):
            done = _alembic(url, *step)
            assert done.returncode == 0, f"alembic {' '.join(step)} failed:\n{done.stderr[-2000:]}"
        heads = _alembic(url, "current")
        assert "(head)" in heads.stdout
    finally:
        async with admin.connect() as conn:
            await conn.execute(text(f"DROP DATABASE IF EXISTS {scratch} WITH (FORCE)"))
        await admin.dispose()


async def test_clean_start_is_not_ready_until_migrated(make_settings, owner_db):
    """An empty database must never be reported ready (the app would 500 on every call)."""
    import httpx

    from frontdesk_api.app import create_app

    scratch = "frontdesk_review_clean"
    admin = create_async_engine(async_url(OWNER_URL), isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text(f"DROP DATABASE IF EXISTS {scratch}"))
        await conn.execute(text(f"CREATE DATABASE {scratch}"))
    url = OWNER_URL.rsplit("/", 1)[0] + f"/{scratch}"
    try:
        application = create_app(make_settings(database_url=url))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://t") as c:
            empty = await c.get("/ready")
            assert empty.status_code == 503
            assert _alembic(url, "upgrade", "head").returncode == 0
            migrated = await c.get("/ready")
            assert migrated.status_code == 200 and migrated.json()["status"] == "ready"
        await application.state.engine.dispose()
    finally:
        async with admin.connect() as conn:
            await conn.execute(text(f"DROP DATABASE IF EXISTS {scratch} WITH (FORCE)"))
        await admin.dispose()


@pytest.mark.xfail(strict=True, reason="ARCHITECTURAL RISK R-11: nothing binds a database to its provider at run "
                                       "time; a deployment configured with another provider's DATABASE_URL serves "
                                       "that provider's customers")
async def test_a_deployment_refuses_another_providers_database(app, make_settings):
    import httpx

    from frontdesk_api.app import create_app

    other = create_app(make_settings(database_url=os.environ["TEST_DATABASE_URL"], provider_id="demo-hotel",
                                     domain_pack="hospitality", rollout_dir=None, tenant_supported_languages="en"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=other), base_url="http://t") as c:
        ready = await c.get("/ready")
    await other.state.engine.dispose()
    assert ready.status_code == 503, "a hotel deployment reports ready on the hospital's database"
