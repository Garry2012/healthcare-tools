"""manage_booking: Manoj's appointment contract with trusted identity, confirmed intent, a stable
operation key and frozen payload, the routing gate before a create, and honest outcomes that keep
validated success, definite rejection and uncertain completion apart."""

from __future__ import annotations

import asyncio
import hashlib
import json

import pytest

from frontdesk_mcp import booking
from frontdesk_mcp.ops_client import InvalidIdentifier  # noqa: F401 - documents the guarded boundary

from . import harness

CREATE = {"action": "CREATE", "patientName": "Lakshmi Rao", "patientMobile": "9000000101", "doctorId": "doc_garima",
          "visitDate": "2026-10-02", "preferredTime": "09:30", "reasonVerbatim": "fever for three days",
          "callerConfirmed": True}


@pytest.fixture
async def h(make_settings):
    built = harness.build(make_settings())
    yield built
    await built.aclose()


def service(h) -> booking.BookingService:
    return booking.BookingService(h.ops, h.knowledge, h.settings, h.clock)


async def run(h, ctx=None, **args):
    return await service(h).manage(ctx or h.ctx(operation_id="op-1"), booking.BookingRequest(**args))


def sent(h, path_suffix: str) -> list:
    return [r for r in h.requests if r.url.path.endswith(path_suffix) and r.method == "POST"]


async def test_create_is_noted_with_a_frozen_body_and_a_bound_key(h):
    result = await run(h, **CREATE)
    assert result.outcome == "NOTED" and result.nextStep == "SAY_REQUEST_NOTED"
    assert result.appointment.status == "NOTED" and result.appointment.visitDate == "2026-10-02"
    assert result.appointment.expectedTime == "09:30" and result.appointment.doctorId == "doc_garima"
    dumped = result.model_dump_json()
    assert "9000000101" not in dumped and "fever" not in dumped  # contact and reason never echoed to the model
    [request] = sent(h, "/appointments")
    body = json.loads(request.content)
    assert body == {"patientName": "Lakshmi Rao", "mobile": "9000000101", "doctorId": "doc_garima",
                    "visitDate": "2026-10-02", "expectedTime": "09:30", "reasonVerbatim": "fever for three days",
                    "callId": "call-1"}
    expected = hashlib.sha256(b"demo-hospital|call-1|CREATE|doc_garima|op-1").hexdigest()
    assert request.headers["idempotency-key"] == expected and len(expected) == 64


async def test_create_needs_the_callers_confirmation(h):
    result = await run(h, **{**CREATE, "callerConfirmed": False})
    assert result.outcome == "CONFIRMATION_REQUIRED" and result.nextStep == "ASK_CONFIRMATION"
    assert sent(h, "/appointments") == []


@pytest.mark.parametrize("missing", ["call_id", "operation_id"])
async def test_writes_refuse_without_trusted_call_and_operation_context(h, missing):
    ctx = h.ctx(call_id=None, operation_id="op-1") if missing == "call_id" else h.ctx(operation_id=None)
    result = await run(h, ctx, **CREATE)
    assert result.outcome == "OPERATION_CONTEXT_MISSING" and result.nextStep == "SAY_COULD_NOT_RECORD"
    assert sent(h, "/appointments") == []


async def test_create_waits_for_a_current_routing_clearance(h):
    emergency = await run(h, h.ctx(operation_id="op-1", turn="Dr Garima, I have chest pain"), **CREATE)
    assert emergency.outcome == "ROUTING_REQUIRED" and emergency.nextStep == "TRANSFER_EMERGENCY"
    h.knowledge_state.fail_next.append(503)
    outage = await run(h, h.ctx(operation_id="op-2"), **CREATE)
    assert outage.outcome == "ROUTING_UNAVAILABLE" and outage.detail == "ROUTING_UNAVAILABLE"
    missing = await run(h, h.ctx(operation_id="op-3", turn=None), **CREATE)
    assert missing.outcome == "ROUTING_UNAVAILABLE" and missing.detail == "TURN_CONTEXT_MISSING"
    assert sent(h, "/appointments") == [] and len(h.ops_state.appointments) == 0
    assert h.knowledge_state.routed[0]["utterance"] == "Dr Garima, I have chest pain"


async def test_same_intent_replays_the_same_write(h):
    first = await run(h, h.ctx(operation_id="op-1"), **CREATE)
    again = await run(h, h.ctx(operation_id="op-1"), **CREATE)
    assert first.appointment.appointmentId == again.appointment.appointmentId
    assert len(h.ops_state.appointments) == 1
    keys = {r.headers["idempotency-key"] for r in sent(h, "/appointments")}
    assert len(keys) == 1


async def test_changed_payload_under_the_same_operation_is_a_conflict_not_a_second_appointment(h):
    await run(h, h.ctx(operation_id="op-1"), **CREATE)
    changed = await run(h, h.ctx(operation_id="op-1"), **{**CREATE, "preferredTime": "10:00"})
    assert changed.outcome == "CONFLICT" and changed.detail == "IDEMPOTENCY_CONFLICT"
    assert changed.nextStep == "TRANSFER_DESK" and len(h.ops_state.appointments) == 1


async def test_a_new_operation_id_is_a_new_intent(h):
    await run(h, h.ctx(operation_id="op-1"), **CREATE)
    second = await run(h, h.ctx(operation_id="op-2"), **CREATE)
    assert second.outcome == "NOTED" and len(h.ops_state.appointments) == 2


async def test_concurrent_same_intent_attempts_record_one_appointment(h):
    results = await asyncio.gather(*(run(h, h.ctx(operation_id="op-1"), **CREATE) for _ in range(5)))
    assert {r.outcome for r in results} == {"NOTED"}
    assert len({r.appointment.appointmentId for r in results}) == 1 and len(h.ops_state.appointments) == 1


@pytest.mark.parametrize("override,field", [
    ({"patientMobile": "+919000000101"}, "patientMobile"),
    ({"patientMobile": "90000001"}, "patientMobile"),
    ({"departmentId": "dept_genmed"}, "doctorId"),
    ({"doctorId": None}, "doctorId"),
    ({"visitDate": "2026-09-30"}, "visitDate"),
    ({"visitDate": "tomorrow"}, "visitDate"),
    ({"preferredTime": "9:30"}, "preferredTime"),
    ({"patientName": ""}, "patientName"),
])
async def test_create_input_is_validated_before_any_call(h, override, field):
    result = await run(h, **{**CREATE, **override})
    assert result.outcome == "INVALID_REQUEST" and field in result.fields
    assert sent(h, "/appointments") == []


async def test_owner_validation_failure_is_a_typed_rejection(h):
    h.ops_state.data["doctors"] = [d for d in h.ops_state.data["doctors"] if d["id"] != "doc_garima"]
    result = await run(h, **CREATE)
    assert result.outcome == "REJECTED" and result.fields == ["doctorId"] and result.nextStep == "ASK_TO_CORRECT"
    assert "fever" not in result.model_dump_json()


async def test_lost_response_after_commit_is_uncertain_and_the_same_intent_reconciles(h):
    h.ops_state.commit_then["/appointments"] = 504
    lost = await run(h, h.ctx(operation_id="op-1"), **CREATE)
    assert lost.outcome == "UNCERTAIN" and lost.nextStep == "SAY_UNCERTAIN_AND_TRANSFER"
    assert len(h.ops_state.appointments) == 1
    recovered = await run(h, h.ctx(operation_id="op-1"), **CREATE)  # platform retry: same intent, same key
    assert recovered.outcome == "NOTED" and len(h.ops_state.appointments) == 1


async def test_unavailable_owner_is_could_not_record_and_malformed_success_is_uncertain(h):
    h.ops_state.fail_next.append(("/appointments", 503, {"Retry-After": "5"}))
    down = await run(h, **CREATE)
    assert down.outcome == "COULD_NOT_RECORD" and down.retryAfterSeconds == 5
    h.ops_state.malformed_next.append("/appointments")
    odd = await run(h, h.ctx(operation_id="op-9"), **CREATE)
    assert odd.outcome == "UNCERTAIN" and odd.detail == "MALFORMED_SUCCESS"


async def test_credential_rejection_never_reaches_the_caller(make_settings):
    hh = harness.build(make_settings(ops_client_secret="wrong"))
    try:
        result = await run(hh, **CREATE)
        assert result.outcome == "COULD_NOT_RECORD" and result.detail == "AUTH"
        assert "wrong" not in result.model_dump_json()
    finally:
        await hh.aclose()


async def test_total_deadline_bounds_a_slow_write(make_settings):
    hh = harness.build(make_settings(read_deadline_seconds=0.3, write_deadline_seconds=0.4,
                                     summary_deadline_seconds=0.5, request_timeout_seconds=0.2))
    try:
        hh.ops_state.delay_seconds = 2
        result = await run(hh, **CREATE)
        assert result.outcome == "UNCERTAIN"
    finally:
        await hh.aclose()


async def test_list_uses_the_trusted_number_only(h):
    await run(h, h.ctx(operation_id="op-1"), **CREATE)
    listed = await run(h, h.ctx(), action="LIST", patientMobile="9000000999")  # the model's number is ignored
    assert listed.outcome == "FOUND" and [a.appointmentId for a in listed.appointments]
    assert listed.appointments[0].patientName == "Lakshmi Rao"
    assert "9000000101" not in listed.model_dump_json()
    query = [r for r in h.requests if r.url.path.endswith("/appointments") and r.method == "GET"][0]
    assert query.url.params["mobile"] == "9000000101"


@pytest.mark.parametrize("ctx_kwargs", [
    {"caller": None}, {"caller": "+449000000101"}, {"caller": "+919000000101", "verification": "NONE"},
    {"caller": "9000000101"},
])
async def test_list_cancel_reschedule_need_an_authorised_number(h, ctx_kwargs):
    for args in ({"action": "LIST"}, {"action": "CANCEL", "appointmentId": "appt_0001", "callerConfirmed": True},
                 {"action": "RESCHEDULE", "appointmentId": "appt_0001", "newVisitDate": "2026-10-03",
                  "callerConfirmed": True}):
        result = await run(h, h.ctx(operation_id="op-1", **ctx_kwargs), **args)
        assert result.outcome == "IDENTITY_UNAVAILABLE" and result.nextStep == "TRANSFER_DESK", args
    assert not [r for r in h.requests if "/appointments" in r.url.path]


async def test_stricter_verification_policy_is_honoured(make_settings):
    hh = harness.build(make_settings(accepted_caller_verification="OTP"))
    try:
        sip = await run(hh, hh.ctx(), action="LIST")
        otp = await run(hh, hh.ctx(verification="OTP"), action="LIST")
        assert sip.outcome == "IDENTITY_UNAVAILABLE" and otp.outcome == "NOT_FOUND"
    finally:
        await hh.aclose()


async def test_list_with_nothing_registered_is_not_found(h):
    result = await run(h, h.ctx(), action="LIST")
    assert result.outcome == "NOT_FOUND" and result.appointments == [] and result.nextStep == "SAY_NOT_FOUND"


async def test_cancel_and_reschedule_follow_the_owner_lifecycle(h):
    created = await run(h, h.ctx(operation_id="op-1"), **CREATE)
    appointment_id = created.appointment.appointmentId
    moved = await run(h, h.ctx(operation_id="op-2"), action="RESCHEDULE", appointmentId=appointment_id,
                      newVisitDate="2026-10-03", newPreferredTime="11:00", callerConfirmed=True)
    assert moved.outcome == "CHANGED" and moved.appointment.visitDate == "2026-10-03"
    assert moved.appointment.expectedTime == "11:00" and moved.nextStep == "SAY_CHANGED"
    body = json.loads(sent(h, "/reschedule")[0].content)
    assert body == {"callerMobile": "9000000101", "newVisitDate": "2026-10-03", "newExpectedTime": "11:00",
                    "callId": "call-1"}
    cancelled = await run(h, h.ctx(operation_id="op-3"), action="CANCEL", appointmentId=appointment_id,
                          reasonVerbatim="coming another day", callerConfirmed=True)
    assert cancelled.outcome == "CANCELLED" and cancelled.nextStep == "SAY_CANCELLED"
    assert json.loads(sent(h, "/cancel")[0].content) == {"callerMobile": "9000000101", "reason": "coming another day",
                                                         "callId": "call-1"}
    again = await run(h, h.ctx(operation_id="op-4"), action="CANCEL", appointmentId=appointment_id,
                      callerConfirmed=True)
    assert again.outcome == "CONFLICT" and again.detail == "STATE_CONFLICT"


async def test_another_callers_appointment_looks_exactly_like_not_found(h):
    created = await run(h, h.ctx(operation_id="op-1"), **CREATE)
    stranger = h.ctx(caller="+919000000102", operation_id="op-2")
    result = await run(h, stranger, action="CANCEL", appointmentId=created.appointment.appointmentId,
                       callerConfirmed=True)
    assert result.outcome == "NOT_FOUND" and result.nextStep == "SAY_NOT_FOUND"
    assert h.ops_state.appointments[created.appointment.appointmentId]["status"] == "NOTED"


@pytest.mark.parametrize("args,field", [
    ({"action": "CANCEL", "callerConfirmed": True}, "appointmentId"),
    ({"action": "CANCEL", "appointmentId": "../departments", "callerConfirmed": True}, "appointmentId"),
    ({"action": "CANCEL", "appointmentId": "appt_1?x=1", "callerConfirmed": True}, "appointmentId"),
    ({"action": "RESCHEDULE", "appointmentId": "appt_0001", "callerConfirmed": True}, "newVisitDate"),
    ({"action": "RESCHEDULE", "appointmentId": "appt_0001", "newVisitDate": "2026-09-01", "callerConfirmed": True},
     "newVisitDate"),
    ({"action": "RESCHEDULE", "appointmentId": "appt_0001", "newVisitDate": "2026-10-03", "doctorId": "doc_garima",
      "callerConfirmed": True}, "doctorId"),
    ({"action": "RESCHEDULE", "appointmentId": "appt_0001", "newVisitDate": "2026-10-03", "newPreferredTime": "11",
      "callerConfirmed": True}, "newPreferredTime"),
])
async def test_change_requests_are_validated_before_any_call(h, args, field):
    result = await run(h, h.ctx(operation_id="op-1"), **args)
    assert result.outcome == "INVALID_REQUEST" and field in result.fields, result
    assert not [r for r in h.requests if "/appointments" in r.url.path]


async def test_change_requests_need_confirmation(h):
    result = await run(h, h.ctx(operation_id="op-1"), action="CANCEL", appointmentId="appt_0001")
    assert result.outcome == "CONFIRMATION_REQUIRED"


async def test_cancel_key_is_bound_to_the_appointment_and_operation(h):
    created = await run(h, h.ctx(operation_id="op-1"), **CREATE)
    appointment_id = created.appointment.appointmentId
    await run(h, h.ctx(operation_id="op-2"), action="CANCEL", appointmentId=appointment_id, callerConfirmed=True)
    key = sent(h, "/cancel")[0].headers["idempotency-key"]
    assert key == hashlib.sha256(f"demo-hospital|call-1|CANCEL|{appointment_id}|op-2".encode()).hexdigest()
