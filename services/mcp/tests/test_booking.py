"""manage_booking: Manoj's appointment contract with trusted identity, confirmed intent, a stable
operation key and frozen payload, the board check before a create, and honest outcomes that keep
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
          "visitDate": "2026-10-01", "preferredTime": "09:30", "reasonVerbatim": "fever for three days",
          "callerConfirmed": True}


@pytest.fixture
async def h(make_settings):
    built = harness.build(make_settings())
    yield built
    await built.aclose()


def service(h) -> booking.BookingService:
    return booking.BookingService(h.ops, h.settings, h.clock)


async def run(h, ctx=None, **args):
    return await service(h).manage(ctx or h.ctx(operation_id="op-1"), booking.BookingRequest(**args))


def sent(h, path_suffix: str) -> list:
    return [r for r in h.requests if r.url.path.endswith(path_suffix) and r.method == "POST"]


async def test_create_is_noted_with_a_frozen_body_and_a_bound_key(h):
    result = await run(h, **CREATE)
    assert result.outcome == "NOTED" and result.nextStep == "SAY_REQUEST_NOTED"
    assert result.appointment.status == "NOTED" and result.appointment.visitDate == "2026-10-01"
    assert result.appointment.expectedTime == "09:30" and result.appointment.doctorId == "doc_garima"
    dumped = result.model_dump_json()
    assert "9000000101" not in dumped and "fever" not in dumped  # contact and reason never echoed to the model
    [request] = sent(h, "/appointments")
    body = json.loads(request.content)
    assert body == {"patientName": "Lakshmi Rao", "mobile": "9000000101", "doctorId": "doc_garima",
                    "visitDate": "2026-10-01", "expectedTime": "09:30", "reasonVerbatim": "fever for three days",
                    "callId": "call-1"}
    expected = hashlib.sha256(b"demo-hospital|call-1|CREATE|op-1").hexdigest()  # no target: changed target conflicts
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
    ({"visitDate": "20261001"}, "visitDate"),
    ({"visitDate": "tomorrow"}, "visitDate"),
    ({"preferredTime": "9:30"}, "preferredTime"),
    ({"patientName": ""}, "patientName"),
])
async def test_create_input_is_validated_before_any_call(h, override, field):
    result = await run(h, **{**CREATE, **override})
    assert result.outcome == "INVALID_REQUEST" and field in result.fields
    assert sent(h, "/appointments") == []


async def test_owner_validation_failure_is_a_typed_rejection(h):
    h.ops_state.reject_next_create = [{"field": "doctorId", "issue": "unknown doctor"}]
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
    h.ops_state.fail_next.append(("/appointments", 429, {"Retry-After": "5"}))  # refused before processing
    down = await run(h, **CREATE)
    assert down.outcome == "COULD_NOT_RECORD" and down.retryAfterSeconds == 5
    h.ops_state.fail_next.append(("/appointments", 503, {}))  # the owner failed after receiving the write
    uncertain = await run(h, h.ctx(operation_id="op-5"), **CREATE)
    assert uncertain.outcome == "UNCERTAIN"
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
    hh = harness.build(make_settings(allow_budget_overrides=True, read_deadline_seconds=0.3,
                                     write_deadline_seconds=0.4, summary_deadline_seconds=0.5,
                                     request_timeout_seconds=0.2))
    try:
        hh.ops_state.delay_for_prefix["/appointments"] = 2  # only the write is slow; the board check is fast
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
    {"caller": "9000000101"}, {"caller": "+919000000101", "verification": None},  # bare number: unverified
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
    h.ops_state.set_board("2026-10-03", [{"doctorId": "doc_garima", "session": "Morning", "status": "NOT_CONFIRMED",
                                          "expectedTime": "09:00", "expectedEndTime": "12:00", "updatedMinutesAgo": 1}])
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
    assert key == hashlib.sha256(b"demo-hospital|call-1|CANCEL|op-2").hexdigest()


async def test_a_dictated_number_never_reaches_a_lookup_or_change(h):
    """Family/other-number access is refused in this release: the only number used for LIST/CANCEL/RESCHEDULE
    is the verified caller's; a dictated patientMobile is contact data on CREATE and ignored elsewhere."""
    await run(h, h.ctx(operation_id="op-1"), **{**CREATE, "patientMobile": "9000000777"})  # booking for a relative
    listed = await run(h, h.ctx(), action="LIST", patientMobile="9000000777")
    assert listed.outcome == "NOT_FOUND"  # nothing under the caller's own verified number
    cancel = await run(h, h.ctx(operation_id="op-2"), action="CANCEL", appointmentId="appt_0001",
                       patientMobile="9000000777", callerConfirmed=True)
    assert cancel.outcome == "NOT_FOUND"
    for r in h.requests:
        if "/appointments" in r.url.path and r.method == "GET":
            assert r.url.params["mobile"] == "9000000101"
        if r.url.path.endswith("/cancel"):
            assert json.loads(r.content)["callerMobile"] == "9000000101"


# ------------------------------------------------------------------ review fixes (1 Oct 2026)


async def test_a_changed_target_under_the_same_operation_is_a_conflict_not_a_second_appointment(h):
    await run(h, h.ctx(operation_id="op-1"), **CREATE)
    changed = await run(h, h.ctx(operation_id="op-1"), **{**CREATE, "doctorId": "doc_arjun_menon"})
    assert changed.outcome == "CONFLICT" and changed.detail == "IDEMPOTENCY_CONFLICT"
    assert len(h.ops_state.appointments) == 1


async def test_create_checks_the_board_server_side_and_refuses_an_unknown_date(h):
    """Review fix: the callback-only rule must not depend on the model obeying nextStep."""
    tomorrow = await run(h, **{**CREATE, "visitDate": "2026-10-02"})  # fixture board: tomorrow is UNKNOWN
    assert tomorrow.outcome == "CALLBACK_REQUIRED" and tomorrow.nextStep == "ASK_CALLBACK_DETAILS"
    assert tomorrow.callback.summaryOutcome == "CALLBACK_NOTED" and sent(h, "/appointments") == []
    h.ops_state.set_board("2026-10-02", [{"doctorId": "doc_garima", "session": "Morning", "status": "NOT_CONFIRMED",
                                          "expectedTime": "09:00", "updatedMinutesAgo": 5}])
    noted = await run(h, h.ctx(operation_id="op-2"), **{**CREATE, "visitDate": "2026-10-02"})
    assert noted.outcome == "NOTED"
    boards = [r for r in h.requests if r.url.path.endswith("/availability")]
    assert boards and boards[0].url.params["doctorId"] == "doc_garima" and boards[0].url.params["date"] == "2026-10-02"


async def test_create_for_a_department_refuses_only_when_every_doctor_is_unknown(h):
    ortho = await run(h, **{**CREATE, "doctorId": None, "departmentId": "dept_ortho"})  # Rohan: missing → UNKNOWN
    assert ortho.outcome == "CALLBACK_REQUIRED" and sent(h, "/appointments") == []
    cardio = await run(h, h.ctx(operation_id="op-2"), **{**CREATE, "doctorId": None, "departmentId": "dept_cardio"})
    assert cardio.outcome == "NOTED"  # Anil IN, Ravi UNKNOWN: the department still has a confirmed doctor


async def test_a_failed_board_read_blocks_the_create_honestly(h):
    h.ops_state.fail_next.append(("/availability", 503, {}))
    result = await run(h, **CREATE)
    assert result.outcome == "COULD_NOT_RECORD" and result.detail == "BOARD_UNAVAILABLE"
    assert sent(h, "/appointments") == []


async def test_create_owner_calls_fit_the_diagnostic_budget(make_settings):
    import time

    hh = harness.build(make_settings(allow_budget_overrides=True, read_deadline_seconds=2.0,
                                     write_deadline_seconds=2.5, request_timeout_seconds=1.5))
    try:
        hh.ops_state.delay_seconds = 0.3
        started = time.monotonic()
        result = await run(hh, hh.ctx(operation_id="op-1"), **CREATE)
        elapsed = time.monotonic() - started
        assert result.outcome == "NOTED" and elapsed < 0.95, elapsed  # board (0.3) + write (0.3) + token
    finally:
        await hh.aclose()


# ------------------------------------------------------------------ architect review AR-01, AR-04


MIXED_BOARD = [
    {"doctorId": "doc_garima", "session": "Morning", "status": "IN", "expectedTime": "09:00",
     "expectedEndTime": "12:00", "updatedMinutesAgo": 1},
    {"doctorId": "doc_garima", "session": "Afternoon", "status": "UNKNOWN", "updatedMinutesAgo": 1},
]


async def test_create_scope_follows_the_session_the_caller_chose(h):
    """AR-04: availability for Morning offered a request; the create for that session must not flip to callback."""
    from frontdesk_mcp import availability

    h.ops_state.set_board("2026-10-01", MIXED_BOARD)
    service = availability.AvailabilityService(h.ops, h.cache, h.settings, h.clock)
    morning = await service.get(h.ctx(), availability.AvailabilityRequest(doctorId="doc_garima", date="today",
                                                                           session="Morning"))
    assert morning.outcome == "AVAILABILITY" and morning.nextStep == "OFFER_APPOINTMENT_REQUEST"
    created = await run(h, h.ctx(operation_id="op-m"), **{**CREATE, "session": "Morning"})
    assert created.outcome == "NOTED"
    afternoon = await run(h, h.ctx(operation_id="op-a"),
                          **{**CREATE, "session": "Afternoon", "preferredTime": "15:30"})
    assert afternoon.outcome == "CALLBACK_REQUIRED"


async def test_create_without_a_session_resolves_scope_from_the_preferred_time_or_asks(h):
    h.ops_state.set_board("2026-10-01", MIXED_BOARD)
    inside_morning = await run(h, h.ctx(operation_id="op-1"), **CREATE)  # 09:30 falls in the Morning window
    assert inside_morning.outcome == "NOTED"
    outside = await run(h, h.ctx(operation_id="op-2"), **{**CREATE, "preferredTime": "15:30"})
    assert outside.outcome == "CALLBACK_REQUIRED"  # the only session that could hold 15:30 is UNKNOWN
    unscoped = await run(h, h.ctx(operation_id="op-3"), **{**CREATE, "preferredTime": None})
    assert unscoped.outcome == "CALLBACK_REQUIRED"  # unresolved scope with an UNKNOWN row: same as availability
    assert len(h.ops_state.appointments) == 1


async def test_unknown_in_an_unrelated_session_does_not_block_a_scoped_create(h):
    h.ops_state.set_board("2026-10-01", [
        {"doctorId": "doc_garima", "session": "Morning", "status": "IN", "expectedTime": "09:00",
         "expectedEndTime": "12:00", "updatedMinutesAgo": 1},
        {"doctorId": "doc_garima", "session": "Evening", "status": "IN", "expectedTime": "17:00",
         "expectedEndTime": "19:00", "updatedMinutesAgo": 500},  # stale → UNKNOWN
    ])
    result = await run(h, h.ctx(operation_id="op-1"), **{**CREATE, "session": "morning", "preferredTime": "10:00"})
    assert result.outcome == "NOTED"


# ------------------------------------------------------------------ architect follow-up 1


async def test_availability_and_create_agree_when_an_unlabelled_unknown_row_is_present(h):
    """Journey: the doctor-specific Morning query and the Morning create must both end in callback-only; the
    UNKNOWN rule is name + number, 'someone will call back', summary only."""
    from frontdesk_mcp import availability

    h.ops_state.set_board("2026-10-01", [
        {"doctorId": "doc_garima", "session": "Morning", "status": "IN", "expectedTime": "09:00",
         "expectedEndTime": "12:00", "updatedMinutesAgo": 1},
        {"doctorId": "doc_garima", "status": "UNKNOWN", "updatedMinutesAgo": 1},
    ])
    service = availability.AvailabilityService(h.ops, h.cache, h.settings, h.clock)
    morning = await service.get(h.ctx(), availability.AvailabilityRequest(doctorId="doc_garima", date="today",
                                                                           session="Morning"))
    created = await run(h, h.ctx(operation_id="op-m"), **{**CREATE, "session": "Morning"})
    assert morning.outcome == created.outcome == "CALLBACK_REQUIRED"
    assert morning.nextStep == created.nextStep == "ASK_CALLBACK_DETAILS"
    assert created.callback.ask and "call you back" in created.callback.say
    assert len(h.ops_state.appointments) == 0 and sent(h, "/appointments") == []


# ------------------------------------------------------------------ re-review (scope consistency)


async def test_department_create_uses_the_same_session_scope_as_availability(h):
    """Garima Morning UNKNOWN, Arjun Evening IN: a Morning department query is callback-only, so a Morning
    department CREATE must be too (Arjun has no Morning row and is out of scope)."""
    from frontdesk_mcp import availability

    h.ops_state.set_board("2026-10-01", [
        {"doctorId": "doc_garima", "session": "Morning", "status": "IN", "expectedTime": "09:00",
         "expectedEndTime": "12:00", "updatedMinutesAgo": 500},  # stale → UNKNOWN
        {"doctorId": "doc_arjun_menon", "session": "Evening", "status": "IN", "expectedTime": "17:00",
         "expectedEndTime": "20:00", "updatedMinutesAgo": 1},
    ])
    service = availability.AvailabilityService(h.ops, h.cache, h.settings, h.clock)
    morning = await service.get(h.ctx(), availability.AvailabilityRequest(departmentId="dept_genmed", date="today",
                                                                           session="Morning"))
    assert morning.outcome == "CALLBACK_REQUIRED"
    created = await run(h, h.ctx(operation_id="op-1"), **{**CREATE, "doctorId": None, "departmentId": "dept_genmed",
                                                          "session": "Morning"})
    assert created.outcome == "CALLBACK_REQUIRED" and sent(h, "/appointments") == []
    evening = await run(h, h.ctx(operation_id="op-2"), **{**CREATE, "doctorId": None, "departmentId": "dept_genmed",
                                                          "session": "Evening", "preferredTime": "18:00"})
    assert evening.outcome == "NOTED"


async def test_a_preferred_time_outside_the_chosen_session_window_is_rejected(h):
    h.ops_state.set_board("2026-10-01", MIXED_BOARD)
    result = await run(h, h.ctx(operation_id="op-1"), **{**CREATE, "session": "Morning", "preferredTime": "15:30"})
    assert result.outcome == "INVALID_REQUEST" and "preferredTime" in result.fields and sent(h, "/appointments") == []


async def test_a_missing_row_for_a_usual_session_today_is_unknown_for_create_too(h):
    """Garima's profile lists Morning on Thursday; the board shows only Afternoon IN. The contract promises a row per
    session, so the missing Morning row is UNKNOWN (callback), not 'no such session'."""
    from frontdesk_mcp import availability

    h.ops_state.set_board("2026-10-01", [{"doctorId": "doc_garima", "session": "Afternoon", "status": "IN",
                                          "expectedTime": "15:00", "expectedEndTime": "17:00", "updatedMinutesAgo": 1}])
    service = availability.AvailabilityService(h.ops, h.cache, h.settings, h.clock)
    morning = await service.get(h.ctx(), availability.AvailabilityRequest(doctorId="doc_garima", date="today",
                                                                           session="Morning"))
    assert morning.outcome == "CALLBACK_REQUIRED" and morning.detail == "SESSION_ROW_MISSING"
    created = await run(h, h.ctx(operation_id="op-1"), **{**CREATE, "session": "Morning"})
    assert created.outcome == "CALLBACK_REQUIRED" and sent(h, "/appointments") == []
    afternoon = await run(h, h.ctx(operation_id="op-2"), **{**CREATE, "session": "Afternoon", "preferredTime": "15:30"})
    assert afternoon.outcome == "NOTED"


async def test_unresolved_scope_with_any_unknown_is_callback_for_create_as_for_availability(h):
    """Consistency: a whole-day availability query with mixed statuses is callback-only; a create without session or
    time on that day must not get a friendlier answer."""
    from frontdesk_mcp import availability

    h.ops_state.set_board("2026-10-01", MIXED_BOARD)
    service = availability.AvailabilityService(h.ops, h.cache, h.settings, h.clock)
    whole = await service.get(h.ctx(), availability.AvailabilityRequest(doctorId="doc_garima", date="today"))
    created = await run(h, h.ctx(operation_id="op-1"), **{**CREATE, "preferredTime": None})
    assert whole.outcome == created.outcome == "CALLBACK_REQUIRED"
    assert sent(h, "/appointments") == []


async def test_reschedule_checks_the_board_for_the_new_date(h):
    created = await run(h, h.ctx(operation_id="op-1"), **CREATE)
    appointment_id = created.appointment.appointmentId
    unknown_day = await run(h, h.ctx(operation_id="op-2"), action="RESCHEDULE", appointmentId=appointment_id,
                            newVisitDate="2026-10-05", callerConfirmed=True)  # fixture board: UNKNOWN that day
    assert unknown_day.outcome == "CALLBACK_REQUIRED" and sent(h, "/reschedule") == []
    h.ops_state.set_board("2026-10-05", [{"doctorId": "doc_garima", "session": "Morning", "status": "NOT_CONFIRMED",
                                          "expectedTime": "09:00", "expectedEndTime": "12:00", "updatedMinutesAgo": 1}])
    moved = await run(h, h.ctx(operation_id="op-3"), action="RESCHEDULE", appointmentId=appointment_id,
                      newVisitDate="2026-10-05", newPreferredTime="10:00", callerConfirmed=True)
    assert moved.outcome == "CHANGED"
    boards = [r for r in h.requests if r.url.path.endswith("/availability")]
    assert all(r.url.params.get("doctorId") == "doc_garima" for r in boards[-2:])


async def test_reschedule_of_an_unknown_appointment_is_still_the_owners_neutral_not_found(h):
    result = await run(h, h.ctx(operation_id="op-1"), action="RESCHEDULE", appointmentId="appt_9999",
                       newVisitDate="2026-10-02", callerConfirmed=True)
    assert result.outcome == "NOT_FOUND"


@pytest.mark.parametrize("reason", [None, "fever for three days", "chest pain, my left arm is numb"])
async def test_booking_journey_forwards_reason_without_knowledge_or_transcript(make_settings, reason):
    import httpx

    from frontdesk_mcp.context import CallContext
    from frontdesk_mcp.tools import Services
    from frontdesk_stubs import ops as ops_stub

    settings = make_settings()
    h = harness.build(settings)
    calls = []
    owner_requests = []
    inner = httpx.ASGITransport(app=ops_stub.create_app(h.ops_state, prefix="/api/v1"))

    async def forbidden(request):
        calls.append(request)
        raise AssertionError("booking must not contact knowledge")

    async def owner(request):
        owner_requests.append(request)
        return await inner.handle_async_request(request)

    services = Services.build(settings, clock=h.clock, ops_transport=httpx.MockTransport(owner),
                              knowledge_transport=httpx.MockTransport(forbidden))
    try:
        ctx = CallContext(call_id="call-1", caller_number=harness.CALLER,
                          caller_verification="SIP_CALLER_ID", operation_id="create")
        result = await services.booking.manage(ctx, booking.BookingRequest(**{**CREATE, "reasonVerbatim": reason}))
        assert result.outcome == "NOTED" and result.appointment.status == "NOTED"
        listed = await services.booking.manage(ctx, booking.BookingRequest(action="LIST"))
        assert listed.outcome == "FOUND" and len(listed.appointments) == 1
        for action, expected in [("RESCHEDULE", "CHANGED"), ("CANCEL", "CANCELLED")]:
            ctx = CallContext(call_id="call-1", caller_number=harness.CALLER,
                              caller_verification="SIP_CALLER_ID", operation_id=action)
            result = await services.booking.manage(ctx, booking.BookingRequest(
                action=action, appointmentId=result.appointment.appointmentId, callerConfirmed=True,
                newVisitDate="2026-10-01" if action == "RESCHEDULE" else None,
                newPreferredTime="10:00" if action == "RESCHEDULE" else None, reasonVerbatim=reason))
            assert result.outcome == expected
        bodies = {r.url.path.rsplit("/", 1)[-1]: json.loads(r.content)
                  for r in owner_requests if r.method == "POST" and "/appointments" in r.url.path}
        if reason:
            assert bodies["appointments"]["reasonVerbatim"] == reason
            assert bodies["cancel"]["reason"] == reason
        else:
            assert "reasonVerbatim" not in bodies["appointments"] and "reason" not in bodies["cancel"]
        assert calls == [] and len(h.ops_state.appointments) == 1
        assert next(iter(h.ops_state.appointments.values()))["status"] == "CANCELLED"
    finally:
        await services.aclose()
        await h.aclose()


async def test_cancelled_create_cancels_both_owner_reads_without_writing(make_settings):
    import httpx

    from frontdesk_mcp.context import CallContext
    from frontdesk_mcp.tools import Services
    from frontdesk_stubs import ops as ops_stub

    h = harness.build(make_settings(allow_budget_overrides=True, write_deadline_seconds=2))
    started = {"profile": asyncio.Event(), "board": asyncio.Event()}
    cancelled = {"profile": asyncio.Event(), "board": asyncio.Event()}
    writes = []
    inner = httpx.ASGITransport(app=ops_stub.create_app(h.ops_state, prefix="/api/v1"))

    async def owner(request):
        kind = ("profile" if "/doctors/" in request.url.path
                else "board" if "/availability" in request.url.path else None)
        if kind:
            started[kind].set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled[kind].set()
        if request.url.path.endswith("/appointments"):
            writes.append(request)
        return await inner.handle_async_request(request)

    services = Services.build(h.settings, clock=h.clock, ops_transport=httpx.MockTransport(owner))
    task = asyncio.create_task(services.booking.manage(CallContext(call_id="call-1", operation_id="op-1"),
                                booking.BookingRequest(**{**CREATE, "session": "Morning"})))
    try:
        async with asyncio.timeout(1):
            await started["profile"].wait()
            await started["board"].wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        async with asyncio.timeout(0.1):
            await cancelled["profile"].wait()
            await cancelled["board"].wait()
        assert writes == []
    finally:
        task.cancel()
        await services.aclose()
        await h.aclose()
