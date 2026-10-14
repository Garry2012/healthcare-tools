"""External acceptance gates (marker `external`): owner-designated services and the deployed MCP transport.
Selected only by `pytest -m external`. A missing input FAILS the test with `BLOCKED: …`; nothing here skips
silently and nothing here weakens an assertion to pass without the service.

Layers and their variables (set what you are testing; the report must name the layer):

  Operational API (Manoj):   OPS_E2E_BASE_URL, OPS_E2E_CLIENT_ID, OPS_E2E_CLIENT_SECRET,
                             OPS_E2E_MODE=mock|live (mock = the public Prism contract mock: static example bodies,
                             any bearer accepted, no state; live = a real backend with registered credentials),
                             OPS_E2E_DEPARTMENT (name present in the tenant; default General Medicine)
  Synthetic write journey:   OPS_E2E_ALLOW_WRITES=1 and OPS_E2E_WRITE_TENANT=<designated synthetic tenant id>
                             plus OPS_E2E_DOCTOR_ID, OPS_E2E_VISIT_DATE and OPS_E2E_RESCHEDULE_DATE
                             (two future usual working days; negative gate requires UNKNOWN/NOT_CONFIRMED today)
                             slots_path records enabled (offered times required) or disabled (day-level journey).
"""

from __future__ import annotations

import contextlib
import os
import uuid
from datetime import UTC, datetime

import pytest

from frontdesk_mcp import availability, booking, context, summary
from frontdesk_mcp.cache import DirectoryCache
from frontdesk_mcp.clock import Deadline, SystemClock
from frontdesk_mcp.config import Settings
from frontdesk_mcp.ops_client import OpsClient

from . import gates, harness
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
                    mcp_bearer_token="external-gateway",
                    # Local test voice allocation accommodates the laptop network; no production bypass.
                    voice_response_budget_seconds=(6.0 + Settings.model_fields["reserved_stage_seconds"].default
                                                   + Settings.model_fields["gateway_overhead_seconds"].default),
                    write_deadline_seconds=8.0, write_exchange_timeout_seconds=5.0,
                    summary_deadline_seconds=12.0, summary_exchange_timeout_seconds=12.0)


@pytest.fixture
async def ops(settings):
    import httpx

    # Cold-start warm-up (not a gate, not counted): the public mock and a scaled-to-zero backend can take >5 s on
    # the first request; the gates below then run against a warm service with their normal caps.
    async with httpx.AsyncClient(timeout=30) as http:
        with contextlib.suppress(httpx.HTTPError):  # the gates below decide; this only wakes the service
            await http.get(f"{settings.ops_base_url}/departments")
    client = OpsClient(settings)
    await client.start()
    yield client
    await client.aclose()


# ------------------------------------------------------------------ reads (mock or live)


async def test_machine_token_is_issued_and_reads_work(ops, settings):
    """Verifies: token endpoint at <base>/auth/token, bearer accepted on reads, contract-shaped bodies."""
    mode()
    deadline = Deadline(settings.read_budget)
    departments = await ops.list_departments(deadline)
    assert departments.items, "the service returned no departments"
    doctors = await ops.search_doctors(Deadline(settings.read_budget), query="a")
    assert doctors.total >= 0 and all(d.id for d in doctors.items)
    board = await ops.get_availability(Deadline(settings.read_budget), date="today",
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
    """Scheduling reads work independently of knowledge configuration."""
    mode()
    ops = OpsClient(settings)
    try:
        service = availability.AvailabilityService(ops, DirectoryCache(settings), settings, SystemClock())
        ctx = context.from_headers(harness.headers(call_id=f"ext-{uuid.uuid4().hex[:8]}"),
                                   settings)
        department = os.environ.get("OPS_E2E_DEPARTMENT", "General Medicine")
        result = await service.get(ctx, availability.AvailabilityRequest(date="today", departmentName=department))
        assert result.outcome in (
            "AVAILABILITY", "CALLBACK_REQUIRED", "CLARIFICATION_NEEDED", "NOT_FOUND", "DOCTORS_MATCHED"), result
    finally:
        await ops.aclose()


# ------------------------------------------------------------------ writes (designated synthetic tenant only)


async def _write_gate(ops: OpsClient) -> None:
    if os.environ.get("OPS_E2E_ALLOW_WRITES") != "1":
        pytest.fail("BLOCKED: OPS_E2E_ALLOW_WRITES=1 not set; the synthetic write journey was not verified")
    tenant = required("OPS_E2E_WRITE_TENANT")
    if mode() != "live":
        pytest.fail("BLOCKED: the write journey needs a stateful live test tenant; the Prism mock keeps no state")
    await gates.assert_authenticated_write_tenant(ops, tenant)


async def test_positive_write_journey_create_list_reschedule_cancel_summary(settings, record_property):
    """Deterministic positive journey on the designated synthetic tenant; every step must succeed."""
    doctor_id = required("OPS_E2E_DOCTOR_ID")
    visit = required("OPS_E2E_VISIT_DATE")  # owner-designated usual working day
    move_date = required("OPS_E2E_RESCHEDULE_DATE")  # another usual working day
    ops = OpsClient(settings)
    try:
        await _write_gate(ops)
        slots_enabled = (await ops.get_capabilities(Deadline(settings.read_budget))).slots.enabled
        record_property("slots_path", "enabled" if slots_enabled else "disabled")
        svc = booking.BookingService(ops, settings, SystemClock())
        availability_service = availability.AvailabilityService(ops, DirectoryCache(settings), settings, SystemClock())
        call_id = f"ext-{uuid.uuid4().hex[:8]}"

        def ctx(op: str):
            return context.from_headers(harness.headers(call_id=call_id, operation_id=f"{call_id}-{op}"), settings)

        async def open_time(day: str) -> str:
            result = await availability_service.get(ctx("availability"), availability.AvailabilityRequest(
                doctorId=doctor_id, date=day))
            block = next((b for doctor in result.doctors
                          for session in [*doctor.board, *(doctor.usualSessions or [])]
                          for b in session.openSlots or []), None)
            if block is None:
                pytest.fail("BLOCKED: the owner-designated date has no open block; "
                            f"outcome={result.outcome}, detail={result.detail}")
            return block.start

        create = booking.BookingRequest(
            action="CREATE", patientName="Synthetic Test Patient", patientMobile=harness.CALLER[3:], doctorId=doctor_id,
            visitDate=visit, callerConfirmed=True)
        if slots_enabled:
            time = await open_time(visit)
            window = booking.BookingRequest(action="LIST", fromDate=visit, toDate=visit)
            before = gates.assert_list_succeeded(await svc.manage(ctx("before"), window))
            refused = await svc.manage(ctx("missing-time"), create)
            assert (refused.outcome, refused.nextStep) == ("INVALID_REQUEST", "ASK_WHICH_TIME"), refused
            after = gates.assert_list_succeeded(await svc.manage(ctx("after"), window))
            gates.assert_no_new_appointment(before, after, doctor_id, visit)
            create = create.model_copy(update={"preferredTime": time})
        created = await svc.manage(ctx("create"), create)
        assert created.outcome == "NOTED", created  # the designated doctor/date must not be UNKNOWN
        if slots_enabled:
            assert created.appointment.slotTime is not None
        appointment_id = created.appointment.appointmentId
        listed = gates.assert_list_succeeded(await svc.manage(ctx("list"), booking.BookingRequest(action="LIST")))
        assert appointment_id in [a.appointmentId for a in listed]
        move = booking.BookingRequest(
            action="RESCHEDULE", appointmentId=appointment_id,
            newVisitDate=move_date, callerConfirmed=True)
        if slots_enabled:
            move = move.model_copy(update={"newPreferredTime": await open_time(move_date)})
        moved = await svc.manage(ctx("move"), move)
        assert moved.outcome == "NOTED" and moved.appointment.status == "CHANGED", moved
        if slots_enabled:
            assert moved.appointment.slotTime is not None
        cancelled = await svc.manage(ctx("cancel"), booking.BookingRequest(
            action="CANCEL", appointmentId=appointment_id, callerConfirmed=True))
        assert cancelled.outcome == "CANCELLED", cancelled
        stored = await summary.SummaryService(ops, settings).record(context.from_headers(harness.headers(
            call_id=call_id, started_at=datetime.now(UTC).isoformat()), settings),
            summary.SummaryRequest(intent="BOOKING", outcome="APPOINTMENT_CANCELLED", appointmentId=appointment_id,
                                   summaryText="External synthetic journey: created, moved, cancelled."))
        assert stored.outcome == "SAVED", stored
        replay = await summary.SummaryService(ops, settings).record(context.from_headers(harness.headers(
            call_id=call_id, started_at=datetime.now(UTC).isoformat()), settings),
            summary.SummaryRequest(intent="BOOKING", outcome="APPOINTMENT_CANCELLED", appointmentId=appointment_id,
                                   summaryText="External synthetic journey: created, moved, cancelled."))
        assert replay.model_dump(mode="json") == {"outcome": "ALREADY_SAVED"}
    finally:
        await ops.aclose()


async def test_negative_unknown_date_is_callback_only_and_writes_nothing(settings):
    """Negative case: a date the board reports UNKNOWN must not produce an appointment on the tenant."""
    doctor_id = required("OPS_E2E_DOCTOR_ID")
    unknown_date = datetime.now(UTC).astimezone(settings.zone).date().isoformat()
    # Owner-designated doctor must have UNKNOWN/NOT_CONFIRMED today; future boards are irrelevant.
    ops = OpsClient(settings)
    try:
        await _write_gate(ops)
        svc = booking.BookingService(ops, settings, SystemClock())
        call_id = f"ext-{uuid.uuid4().hex[:8]}"
        ctx = context.from_headers(harness.headers(call_id=call_id, operation_id=f"{call_id}-create"), settings)
        window = booking.BookingRequest(action="LIST", fromDate=unknown_date, toDate=unknown_date)
        before = gates.assert_list_succeeded(await svc.manage(ctx, window))  # the baseline itself must succeed
        result = await svc.manage(ctx, booking.BookingRequest(
            action="CREATE", patientName="Synthetic Test Patient", patientMobile=harness.CALLER[3:],
            doctorId=doctor_id, visitDate=unknown_date, callerConfirmed=True))
        assert result.outcome == "CALLBACK_REQUIRED", result
        after = gates.assert_list_succeeded(await svc.manage(ctx, window))
        gates.assert_no_new_appointment(before, after, doctor_id, unknown_date)
    finally:
        await ops.aclose()


