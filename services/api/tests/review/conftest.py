"""Fixtures for the independent review suite (docs/review/).

Database tests run against a throwaway PostgreSQL given by TEST_DATABASE_URL (DML-only runtime
role) and TEST_DATABASE_OWNER_URL (migration owner), exactly like tests/integration. They never
use a real provider's database: the fixture refuses any URL that is not on localhost.

Only the clock is replaced (schedule.now_in, a time boundary). Repositories, the availability
engine, serializers and routers are always the production ones, reached through HTTP.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from frontdesk_api.app import create_app
from frontdesk_api.seed import load_directory
from frontdesk_api.services import schedule
from tests.conftest import AGENT_TOKEN, STAFF_TOKEN

from .oracle import SessionSpec

APP_URL = os.environ.get("TEST_DATABASE_URL")
OWNER_URL = os.environ.get("TEST_DATABASE_OWNER_URL")
API_ROOT = Path(__file__).resolve().parents[2]
TABLES = (
    "notifications", "booking_history", "bookings", "schedule_exceptions", "board_entries",
    "idempotency_keys", "call_summaries", "knowledge_entries", "lexicon_entries", "template_sessions",
    "schedule_templates", "resource_categories", "resources", "categories",
)
# Wednesday 23 September 2026, 10:00 facility time (Asia/Kolkata for the demo rollout).
DEFAULT_NOW = datetime(2026, 9, 23, 10, 0)
AGENT = {"Authorization": f"Bearer {AGENT_TOKEN}"}
STAFF = {"Authorization": f"Bearer {STAFF_TOKEN}", "X-Acting-User": "review-desk"}
ALL_DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def _require_db() -> None:
    if not (APP_URL and OWNER_URL):
        pytest.skip("TEST_DATABASE_URL / TEST_DATABASE_OWNER_URL not set (see docs/review/TEST-RESULTS.md)")
    for url in (APP_URL, OWNER_URL):
        host = urlparse(url).hostname
        if host not in ("127.0.0.1", "localhost", "::1"):
            pytest.exit(f"refusing to run review tests against a non-local database host {host!r}")


def async_url(url: str) -> str:
    return url.replace("postgresql://", "postgresql+asyncpg://", 1)


@pytest.fixture(scope="session")
def migrated_db() -> None:
    _require_db()
    env = {**os.environ, "DATABASE_URL": OWNER_URL}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=API_ROOT, env=env, check=True,
                   capture_output=True)


@pytest.fixture(scope="session")
def review_settings(make_settings, migrated_db):
    return make_settings(database_url=APP_URL, database_pool_size=10)


class Clock:
    """The facility's 'now' for the service under test. Tests move it to exercise same-day rules."""

    def __init__(self, tz) -> None:
        self.tz = tz
        self.now = DEFAULT_NOW.replace(tzinfo=tz)

    def set(self, value: datetime) -> datetime:
        self.now = value.replace(tzinfo=self.tz) if value.tzinfo is None else value.astimezone(self.tz)
        return self.now

    @property
    def today(self) -> date:
        return self.now.date()


@pytest.fixture
def clock(monkeypatch, review_settings) -> Clock:
    c = Clock(review_settings.tz)
    monkeypatch.setattr(schedule, "now_in", lambda settings: c.now)
    return c


@pytest.fixture
async def app(review_settings, clock):
    """Empty every table as the owner, then apply the demo rollout (pack baseline words included)."""
    owner = create_async_engine(async_url(OWNER_URL))
    async with owner.begin() as conn:
        await conn.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))
    await owner.dispose()
    application = create_app(review_settings)
    async with application.state.sessionmaker() as session:
        await load_directory(session, review_settings)
    yield application
    await application.state.engine.dispose()


@pytest.fixture
async def client(app) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test/api/v1") as c:
        yield c


@pytest.fixture
async def owner_db() -> AsyncIterator:
    """Direct SQL as the owner, to check what is really stored (never to set up behaviour)."""
    _require_db()
    engine = create_async_engine(async_url(OWNER_URL))
    yield engine
    await engine.dispose()


def call(caller: str | None = "+919812300001", call_id: str = "rv-call-1", key: str | None = None) -> dict[str, str]:
    headers = {**AGENT, "X-Call-Id": call_id}
    if caller:
        headers["X-Caller-Number"] = caller
    if key:
        headers["Idempotency-Key"] = key
    return headers


def session_body(key: str, spec: SessionSpec, days: list[str] | None = None, label: str | None = None) -> dict:
    body = {
        "templateSessionId": key,
        "label": label or key,
        "daysOfWeek": days or ALL_DAYS,
        "start": spec.start,
        "end": spec.end,
        "capacityModel": spec.model,
        "capacity": {"mode": spec.mode, "value": spec.value},
        "walkInReservePercent": spec.reserve_percent,
        "lastArrivalOffsetMinutes": spec.last_arrival_offset,
    }
    if spec.slot_minutes is not None:
        body["slotMinutes"] = spec.slot_minutes
    return body


@dataclass
class Built:
    resource_id: str
    name: str
    category_id: str


class Desk:
    """The staff side of the public API, used to create the state a scenario needs."""

    def __init__(self, client: httpx.AsyncClient, clock: Clock) -> None:
        self.client = client
        self.clock = clock
        self._n = 0

    async def resource(
        self, name: str, sessions: dict[str, SessionSpec], *, category: str = "cat_rv_review",
        days: list[str] | None = None, effective_from: date | None = None, **resource_fields,
    ) -> Built:
        r = await self.client.put(f"/categories/{category}", headers=STAFF,
                                  json={"name": f"Review {category}", "code": None})
        assert r.status_code == 200, r.text
        body = {"name": name, "categoryIds": [category], "dataConfirmed": True, **resource_fields}
        r = await self.client.post("/resources", headers=STAFF, json=body)
        assert r.status_code == 201, r.text
        resource_id = r.json()["id"]
        await self.template(resource_id, sessions, days=days, effective_from=effective_from)
        return Built(resource_id, name, category)

    async def template(self, resource_id: str, sessions: dict[str, SessionSpec], *, days: list[str] | None = None,
                       effective_from: date | None = None) -> httpx.Response:
        r = await self.client.put(f"/resources/{resource_id}/schedule-template", headers=STAFF, json={
            "resourceId": resource_id,
            "effectiveFrom": (effective_from or self.clock.today).isoformat(),
            "sessions": [session_body(k, v, days) for k, v in sessions.items()],
        })
        assert r.status_code == 200, r.text
        return r

    async def exception(self, **body) -> httpx.Response:
        self._n += 1
        payload = {k: (v.isoformat() if isinstance(v, date) else v) for k, v in body.items()}
        return await self.client.post("/schedule-exceptions", headers={**STAFF, "Idempotency-Key": f"rv-exc-{self._n}"},
                                      json=payload)

    async def board(self, resource_id: str, session_id: str, **fields) -> httpx.Response:
        return await self.client.put(f"/board/{resource_id}", headers=STAFF, json={
            "date": self.clock.today.isoformat(), "sessionId": session_id, **fields})

    async def availability(self, resource_id: str, day: date, to: date | None = None) -> list[dict]:
        r = await self.client.get("/availability", headers=STAFF, params={
            "resourceId": resource_id, "from": day.isoformat(), "to": (to or day).isoformat()})
        assert r.status_code == 200, r.text
        return r.json()["items"]


@pytest.fixture
def desk(client, clock) -> Desk:
    return Desk(client, clock)


def weekday_after(today: date, weekday: int) -> date:
    """The next given weekday strictly after `today`."""
    return today + timedelta(days=((weekday - today.weekday()) % 7) or 7)


def at(day: date, hh: int, mm: int = 0) -> datetime:
    return datetime.combine(day, time(hh, mm))


def book_body(slot_id: str, name: str = "Asha Review", phone: str = "9812300001", **extra) -> dict:
    return {"slotId": slot_id, "customer": {"name": name, "phone": phone}, "language": "en", **extra}


def search_body(name: str, day: date, **extra) -> dict:
    return {"utterance": f"is {name} available", "language": "en", "resourceName": name,
            "when": {"dateFrom": day.isoformat(), "dateTo": day.isoformat()}, **extra}


def search_sessions(body: dict) -> list[dict]:
    return [si for result in body.get("results", []) for si in result["sessions"]]
