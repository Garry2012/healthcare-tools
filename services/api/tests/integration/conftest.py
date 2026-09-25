"""Integration fixtures: a real PostgreSQL (compose `test` profile), migrated by the owner
role, used by the app through the DML-only runtime role. Skipped when not configured."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from healthcare_api.app import create_app
from healthcare_api.seed import _upsert_directory
from healthcare_api.services import schedule
from tests.conftest import AGENT_TOKEN, STAFF_TOKEN

APP_URL = os.environ.get("TEST_DATABASE_URL")
OWNER_URL = os.environ.get("TEST_DATABASE_OWNER_URL")
API_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.postgres
if not (APP_URL and OWNER_URL):
    pytest.skip("TEST_DATABASE_URL / TEST_DATABASE_OWNER_URL not set (run `make test`)", allow_module_level=True)

TABLES = (
    "notifications", "appointment_history", "appointments", "schedule_exceptions", "board_entries",
    "idempotency_keys", "call_summaries", "lexicon_entries", "template_sessions", "schedule_templates",
    "doctor_departments", "doctors", "departments",
)


def alembic(*args: str, url: str | None = None) -> None:
    env = {**os.environ, "DATABASE_URL": url or OWNER_URL}
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=API_ROOT, env=env, check=True,
                   capture_output=True)


def async_url(url: str) -> str:
    return url.replace("postgresql://", "postgresql+asyncpg://", 1)


@pytest.fixture(scope="session", autouse=True)
def migrated() -> None:
    alembic("upgrade", "head")


@pytest.fixture(scope="session")
def app_settings(make_settings):
    return make_settings(database_url=APP_URL, database_pool_size=10)


@pytest.fixture
async def app(app_settings):
    """Empty every table (as the owner), then load the synthetic directory."""
    owner = create_async_engine(async_url(OWNER_URL))
    async with owner.begin() as conn:
        await conn.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))
    await owner.dispose()
    application = create_app(app_settings)
    async with application.state.sessionmaker() as session:
        await _upsert_directory(session, app_settings)
    yield application
    await application.state.engine.dispose()


@pytest.fixture
async def client(app) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test/api/v1") as c:
        yield c


AGENT = {"Authorization": f"Bearer {AGENT_TOKEN}"}
STAFF = {"Authorization": f"Bearer {STAFF_TOKEN}", "X-Acting-User": "desk-1"}


def call(caller: str | None = "+919000000101", call_id: str = "call-1", key: str | None = None) -> dict[str, str]:
    headers = {**AGENT, "X-Call-Id": call_id}
    if caller:
        headers["X-Caller-Number"] = caller
    if key:
        headers["Idempotency-Key"] = key
    return headers


def next_weekday(weekday: int, settings) -> date:
    """The next given weekday strictly after today (facility time), so it is never 'today'."""
    today = schedule.now_in(settings).date()
    return today + timedelta(days=((weekday - today.weekday()) % 7) or 7)


def garima_slot(day: date, position: int, n: int = 2) -> str:
    return f"slot_ses_doc_garima_{day.isoformat()}_{n}_{position:02d}"


def book_body(slot_id: str, name: str = "Lakshmi Rao", phone: str = "9000000101", **extra) -> dict:
    return {"slotId": slot_id, "patient": {"name": name, "phone": phone}, "language": "en", **extra}
