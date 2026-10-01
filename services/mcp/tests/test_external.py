"""External acceptance gates (marker `external`): owner-designated services and the deployed MCP transport.
Selected only by `pytest -m external`. A missing input FAILS the test with `BLOCKED: …`; nothing here skips
silently and nothing here weakens an assertion to pass without the service.

Layers and their variables (set what you are testing; the report must name the layer):

  Operational API (Manoj):   OPS_E2E_BASE_URL, OPS_E2E_CLIENT_ID, OPS_E2E_CLIENT_SECRET,
                             OPS_E2E_MODE=mock|live (mock = the public Prism contract mock: static example bodies,
                             any bearer accepted, no state; live = a real backend with registered credentials),
                             OPS_E2E_DEPARTMENT (name present in the tenant; default General Medicine)
  Synthetic write journey:   OPS_E2E_ALLOW_WRITES=1 and OPS_E2E_WRITE_TENANT=<designated synthetic tenant id>
                             plus OPS_E2E_DOCTOR_ID (a doctor whose board for OPS_E2E_VISIT_DATE is not UNKNOWN)
  Knowledge (Shobhit):       KNOWLEDGE_E2E_BASE_URL, KNOWLEDGE_E2E_BEARER_TOKEN
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from frontdesk_mcp import availability, booking, context, knowledge, summary
from frontdesk_mcp.cache import DirectoryCache
from frontdesk_mcp.clock import Deadline, SystemClock
from frontdesk_mcp.config import Settings
from frontdesk_mcp.knowledge_client import KnowledgeClient
from frontdesk_mcp.ops_client import OpsClient

from . import harness
from .conftest import ROLLOUT

pytestmark = pytest.mark.external


def required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        pytest.fail(f"BLOCKED: {name} is not set; this gate was not verified (no silent skip)")
    return value


def mode() -> str:
    value = os.environ.get("OPS_E2E_MODE", "")
    if value not in ("mock", "live"):
        pytest.fail("BLOCKED: OPS_E2E_MODE must be 'mock' (public contract mock) or 'live' (registered backend)")
    return value


@pytest.fixture(scope="module")
def settings() -> Settings:
    return Settings(**ROLLOUT, env="test", ops_base_url=required("OPS_E2E_BASE_URL"),
                    ops_client_id=required("OPS_E2E_CLIENT_ID"), ops_client_secret=required("OPS_E2E_CLIENT_SECRET"),
                    knowledge_base_url=os.environ.get("KNOWLEDGE_E2E_BASE_URL", "https://knowledge.pending.invalid"),
                    knowledge_bearer_token=os.environ.get("KNOWLEDGE_E2E_BEARER_TOKEN", "pending"),
                    mcp_bearer_token="external-gateway", mcp_lifecycle_bearer_token="external-lifecycle",
                    # diagnostic overrides: the laptop → Azure path is far slower than the in-region budget
                    read_deadline_seconds=6.0, write_deadline_seconds=8.0, summary_deadline_seconds=12.0,
                    request_timeout_seconds=5.0)


@pytest.fixture
async def ops(settings):
    client = OpsClient(settings)
    await client.start()
    yield client
    await client.aclose()


# ------------------------------------------------------------------ reads (mock or live)


async def test_machine_token_is_issued_and_reads_work(ops, settings):
    """Verifies: token endpoint at <base>/auth/token, bearer accepted on reads, contract-shaped bodies."""
    mode()
    deadline = Deadline(settings.read_deadline_seconds)
    departments = await ops.list_departments(deadline)
    assert departments.items, "the service returned no departments"
    doctors = await ops.search_doctors(Deadline(settings.read_deadline_seconds), query="a")
    assert doctors.total >= 0 and all(d.id for d in doctors.items)
    board = await ops.get_availability(Deadline(settings.read_deadline_seconds), date="today",
                                       department=departments.items[0].id)
    assert all(e.status in ("IN", "LATE", "CANCELLED", "NOT_CONFIRMED", "UNKNOWN") for e in board.items)
    assert ops.tokens.usable, "no machine token cached after the reads"


async def test_an_absent_bearer_is_refused_by_the_service(settings):
    """The owner (mock or live) must refuse unauthenticated reads: our bearer discipline matters."""
    import httpx

    mode()
    async with httpx.AsyncClient(base_url=settings.ops_base_url, timeout=10) as http:
        response = await http.get("/departments")
    assert response.status_code == 401


async def test_availability_tool_end_to_end_against_the_service(settings):
    """Exact behaviour depends on the knowledge host: without it the honest outcome is ROUTING_UNAVAILABLE."""
    which = mode()
    kb = KnowledgeClient(settings)
    ops = OpsClient(settings)
    try:
        service = availability.AvailabilityService(ops, kb, DirectoryCache(settings), settings, SystemClock())
        ctx = context.from_headers(harness.headers(call_id=f"ext-{uuid.uuid4().hex[:8]}", turn="availability today"),
                                   settings)
        department = os.environ.get("OPS_E2E_DEPARTMENT", "General Medicine")
        result = await service.get(ctx, availability.AvailabilityRequest(date="today", departmentName=department))
        if os.environ.get("KNOWLEDGE_E2E_BASE_URL"):
            assert result.outcome in ("AVAILABILITY", "CALLBACK_REQUIRED", "CLARIFICATION_NEEDED", "NOT_FOUND"), result
        else:
            assert result.outcome == "ROUTING_UNAVAILABLE" and result.detail == "ROUTING_UNAVAILABLE", result
        if which == "mock":
            # the Prism mock lists one department ("Orthopaedics") regardless of the query
            assert result.facilityToday
    finally:
        await ops.aclose()
        await kb.aclose()


# ------------------------------------------------------------------ writes (designated synthetic tenant only)


def _write_gate() -> None:
    if os.environ.get("OPS_E2E_ALLOW_WRITES") != "1":
        pytest.fail("BLOCKED: OPS_E2E_ALLOW_WRITES=1 not set; the synthetic write journey was not verified")
    required("OPS_E2E_WRITE_TENANT")
    if mode() != "live":
        pytest.fail("BLOCKED: the write journey needs a stateful live test tenant; the Prism mock keeps no state")
    required("KNOWLEDGE_E2E_BASE_URL")


async def test_positive_write_journey_create_list_reschedule_cancel_summary(settings):
    """Deterministic positive journey on the designated synthetic tenant; every step must succeed."""
    _write_gate()
    doctor_id = required("OPS_E2E_DOCTOR_ID")
    visit = os.environ.get("OPS_E2E_VISIT_DATE") or (datetime.now(UTC).astimezone(settings.zone).date()
                                                   + timedelta(days=1)).isoformat()
    ops, kb = OpsClient(settings), KnowledgeClient(settings)
    try:
        svc = booking.BookingService(ops, kb, settings, SystemClock())
        call_id = f"ext-{uuid.uuid4().hex[:8]}"

        def ctx(op: str):
            return context.from_headers(harness.headers(call_id=call_id, operation_id=f"{call_id}-{op}",
                                                        turn="appointment please"), settings)

        created = await svc.manage(ctx("create"), booking.BookingRequest(
            action="CREATE", patientName="Synthetic Test Patient", patientMobile=harness.CALLER[3:], doctorId=doctor_id,
            visitDate=visit, preferredTime="10:00", callerConfirmed=True))
        assert created.outcome == "NOTED", created  # the designated doctor/date must not be UNKNOWN
        appointment_id = created.appointment.appointmentId
        listed = await svc.manage(ctx("list"), booking.BookingRequest(action="LIST"))
        assert listed.outcome == "FOUND" and appointment_id in [a.appointmentId for a in listed.appointments]
        moved = await svc.manage(ctx("move"), booking.BookingRequest(
            action="RESCHEDULE", appointmentId=appointment_id,
            newVisitDate=(datetime.fromisoformat(visit).date() + timedelta(days=1)).isoformat(), callerConfirmed=True))
        assert moved.outcome == "CHANGED", moved
        cancelled = await svc.manage(ctx("cancel"), booking.BookingRequest(
            action="CANCEL", appointmentId=appointment_id, callerConfirmed=True))
        assert cancelled.outcome == "CANCELLED", cancelled
        stored = await summary.SummaryService(ops, settings).record(context.from_headers(harness.headers(
            call_id=call_id, turn=None, started_at=datetime.now(UTC).isoformat(), duration="60"), settings),
            summary.SummaryRequest(intent="BOOKING", outcome="APPOINTMENT_CANCELLED", appointmentId=appointment_id,
                                   summaryText="External synthetic journey: created, moved, cancelled."))
        assert stored.outcome == "STORED", stored
        replay = await summary.SummaryService(ops, settings).record(context.from_headers(harness.headers(
            call_id=call_id, turn=None, started_at=datetime.now(UTC).isoformat(), duration="60"), settings),
            summary.SummaryRequest(intent="BOOKING", outcome="APPOINTMENT_CANCELLED", appointmentId=appointment_id,
                                   summaryText="External synthetic journey: created, moved, cancelled."))
        assert replay.outcome == "REPLAYED" and replay.summaryId == stored.summaryId
    finally:
        await ops.aclose()
        await kb.aclose()


async def test_negative_unknown_date_is_callback_only_and_writes_nothing(settings):
    """Negative case: a date the board reports UNKNOWN must not produce an appointment on the tenant."""
    _write_gate()
    doctor_id = required("OPS_E2E_DOCTOR_ID")
    unknown_date = required("OPS_E2E_UNKNOWN_DATE")  # a date the tenant's board reports UNKNOWN for that doctor
    ops, kb = OpsClient(settings), KnowledgeClient(settings)
    try:
        svc = booking.BookingService(ops, kb, settings, SystemClock())
        call_id = f"ext-{uuid.uuid4().hex[:8]}"
        ctx = context.from_headers(harness.headers(call_id=call_id, operation_id=f"{call_id}-create",
                                                   turn="appointment please"), settings)
        result = await svc.manage(ctx, booking.BookingRequest(
            action="CREATE", patientName="Synthetic Test Patient", patientMobile=harness.CALLER[3:],
            doctorId=doctor_id, visitDate=unknown_date, callerConfirmed=True))
        assert result.outcome == "CALLBACK_REQUIRED", result
        listed = await svc.manage(ctx, booking.BookingRequest(action="LIST", fromDate=unknown_date,
                                                              toDate=unknown_date))
        assert all(a.visitDate != unknown_date or a.doctorId != doctor_id for a in listed.appointments)
    finally:
        await ops.aclose()
        await kb.aclose()


# ------------------------------------------------------------------ knowledge (Shobhit)


async def test_knowledge_search_against_the_real_host(settings):
    required("KNOWLEDGE_E2E_BASE_URL")
    kb = KnowledgeClient(settings)
    try:
        result = await knowledge.KnowledgeService(kb, settings).search(
            context.from_headers(harness.headers(call_id="ext-kb", turn="is there parking"), settings),
            knowledge.KnowledgeRequest(question="parking", language="en"))
        assert result.outcome in ("ANSWERED", "NO_ANSWER", "CLARIFICATION_NEEDED", "ROUTING_REQUIRED"), result
    finally:
        await kb.aclose()
