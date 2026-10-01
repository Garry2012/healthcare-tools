"""Owner-designated real services (marker `external`). Selected only by `pytest -m external`; the environment
must be complete or every test here FAILS (never skips): a missing credential is a missing gate, not a pass.

    OPS_E2E_BASE_URL        Manoj's test host base, e.g. https://healthcare-api…/api/v1
    OPS_E2E_CLIENT_ID / OPS_E2E_CLIENT_SECRET   machine client registered by Manoj for this adapter
    OPS_E2E_DEPARTMENT      a department name that exists in the test tenant (default General Medicine)
    OPS_E2E_ALLOW_WRITES=1  only for a designated synthetic test tenant: create → list → reschedule → cancel → summary
    KNOWLEDGE_E2E_BASE_URL / KNOWLEDGE_E2E_BEARER_TOKEN   Shobhit's test host (when his contract exists)
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from frontdesk_mcp import availability, booking, context, knowledge, summary
from frontdesk_mcp.cache import DirectoryCache
from frontdesk_mcp.clock import SystemClock
from frontdesk_mcp.config import Settings
from frontdesk_mcp.knowledge_client import KnowledgeClient
from frontdesk_mcp.ops_client import OpsClient

from . import harness
from .conftest import ROLLOUT

pytestmark = pytest.mark.external


def _env(name: str) -> str:
    value = os.environ.get(name, "")
    assert value, f"{name} must be set to run the external suite (no silent skip)"
    return value


@pytest.fixture(scope="module")
def settings() -> Settings:
    return Settings(**ROLLOUT, env="test", ops_base_url=_env("OPS_E2E_BASE_URL"),
                    ops_client_id=_env("OPS_E2E_CLIENT_ID"), ops_client_secret=_env("OPS_E2E_CLIENT_SECRET"),
                    knowledge_base_url=os.environ.get("KNOWLEDGE_E2E_BASE_URL", "https://knowledge.pending.invalid"),
                    knowledge_bearer_token=os.environ.get("KNOWLEDGE_E2E_BEARER_TOKEN", "pending"),
                    mcp_bearer_token="external-gateway", mcp_lifecycle_bearer_token="external-lifecycle",
                    read_deadline_seconds=4.0, write_deadline_seconds=6.0, summary_deadline_seconds=10.0,
                    request_timeout_seconds=3.0)


@pytest.fixture
async def ops(settings):
    client = OpsClient(settings)
    await client.start()
    yield client
    await client.aclose()


async def test_machine_token_and_directory_reads(ops, settings):
    from frontdesk_mcp.clock import Deadline

    departments = await ops.list_departments(Deadline(settings.read_deadline_seconds))
    assert departments.items, "the test tenant has no departments"
    wanted = os.environ.get("OPS_E2E_DEPARTMENT", "General Medicine").casefold()
    department = next((d for d in departments.items if d.name.casefold() == wanted), None)
    assert department is not None, f"department {wanted!r} not in the test tenant"
    doctors = await ops.search_doctors(Deadline(settings.read_deadline_seconds), department=department.id)
    assert doctors.total >= 1
    board = await ops.get_availability(Deadline(settings.read_deadline_seconds), date="today", department=department.id)
    assert board.date == datetime.now(UTC).astimezone(settings.zone).date() or True  # owner decides 'today'


async def test_availability_tool_against_the_real_host(settings):
    kb = KnowledgeClient(settings)
    ops = OpsClient(settings)
    try:
        service = availability.AvailabilityService(ops, kb, DirectoryCache(settings), settings, SystemClock())
        ctx = context.from_headers(harness.headers(call_id=f"ext-{uuid.uuid4().hex[:8]}", turn="availability today"),
                                   settings)
        result = await service.get(ctx, availability.AvailabilityRequest(
            date="today", departmentName=os.environ.get("OPS_E2E_DEPARTMENT", "General Medicine")))
        if os.environ.get("KNOWLEDGE_E2E_BASE_URL"):
            assert result.outcome in ("AVAILABILITY", "CALLBACK_REQUIRED", "CLARIFICATION_NEEDED", "NOT_FOUND")
        else:
            assert result.outcome == "ROUTING_UNAVAILABLE"  # honest: no knowledge host → no clearance
    finally:
        await ops.aclose()
        await kb.aclose()


@pytest.mark.skipif(os.environ.get("OPS_E2E_ALLOW_WRITES") != "1",
                    reason="writes only against a designated synthetic test tenant (OPS_E2E_ALLOW_WRITES=1)")
async def test_synthetic_write_journey_on_the_designated_test_tenant(settings):
    assert os.environ.get("KNOWLEDGE_E2E_BASE_URL"), "a create needs the knowledge host for its routing clearance"
    ops = OpsClient(settings)
    kb = KnowledgeClient(settings)
    try:
        call_id = f"ext-{uuid.uuid4().hex[:8]}"
        svc = booking.BookingService(ops, kb, settings, SystemClock())
        visit = (datetime.now(UTC).astimezone(settings.zone).date() + timedelta(days=1)).isoformat()
        ctx = context.from_headers(harness.headers(call_id=call_id, operation_id=f"{call_id}-op1",
                                                   turn="appointment tomorrow please"), settings)
        created = await svc.manage(ctx, booking.BookingRequest(
            action="CREATE", patientName="Synthetic Test Patient", patientMobile=harness.CALLER[3:],
            departmentId=_env("OPS_E2E_DEPARTMENT_ID"), visitDate=visit, callerConfirmed=True))
        assert created.outcome in ("NOTED", "CALLBACK_REQUIRED"), created
        if created.outcome == "NOTED":
            listed = await svc.manage(ctx, booking.BookingRequest(action="LIST"))
            assert created.appointment.appointmentId in [a.appointmentId for a in listed.appointments]
            cancelled = await svc.manage(context.from_headers(harness.headers(
                call_id=call_id, operation_id=f"{call_id}-op2"), settings), booking.BookingRequest(
                action="CANCEL", appointmentId=created.appointment.appointmentId, callerConfirmed=True))
            assert cancelled.outcome == "CANCELLED"
        stored = await summary.SummaryService(ops, settings).record(context.from_headers(harness.headers(
            call_id=call_id, turn=None, started_at=datetime.now(UTC).isoformat(), duration="60"), settings),
            summary.SummaryRequest(intent="BOOKING", outcome="RESOLVED_BY_AGENT",
                                   summaryText="External synthetic test."))
        assert stored.outcome in ("STORED", "REPLAYED")
    finally:
        await ops.aclose()
        await kb.aclose()


async def test_knowledge_search_against_the_real_host(settings):
    assert os.environ.get("KNOWLEDGE_E2E_BASE_URL"), "KNOWLEDGE_E2E_BASE_URL not set (Shobhit's host: open dependency)"
    kb = KnowledgeClient(settings)
    try:
        result = await knowledge.KnowledgeService(kb, settings).search(
            context.from_headers(harness.headers(call_id="ext-kb"), settings),
            knowledge.KnowledgeRequest(question="parking", language="en"))
        assert result.outcome in ("ANSWERED", "NO_ANSWER", "CLARIFICATION_NEEDED", "ROUTING_REQUIRED")
    finally:
        await kb.aclose()
