"""get_doctor_availability: directory + profile + live board composed in one invocation, qualified by
the required routing decision; UNKNOWN stops the appointment journey (callback only); a failed board
is a service error, never 'no availability'; no slots are ever invented."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from frontdesk_mcp import availability

from . import harness


@pytest.fixture
async def h(make_settings):
    built = harness.build(make_settings())
    yield built
    await built.aclose()


def service(h) -> availability.AvailabilityService:
    return availability.AvailabilityService(h.ops, h.knowledge, h.cache, h.settings, h.clock)


async def ask(h, ctx=None, **args):
    return await service(h).get(ctx or h.ctx(), availability.AvailabilityRequest(**{"date": "today", **args}))


async def test_known_doctor_today_returns_every_window_and_every_board_session(h):
    result = await ask(h, doctorName="garima")
    assert result.outcome == "AVAILABILITY" and result.nextStep == "OFFER_APPOINTMENT_REQUEST"
    assert result.facilityToday == "2026-10-01" and result.requestedDate == "2026-10-01" and result.weekday == "THU"
    [doctor] = result.doctors
    assert doctor.doctorId == "doc_garima" and doctor.departments == ["General Medicine"]
    assert [(s.label, s.start, s.end, s.onRequestedDate) for s in doctor.usualSessions] == [
        ("Morning", "09:00", "12:00", True), ("Afternoon", "15:00", "17:00", True)]
    assert [(b.session, b.status, b.expectedTime, b.expectedEndTime) for b in doctor.board] == [
        ("Morning", "IN", "09:10", "12:00"), ("Afternoon", "NOT_CONFIRMED", "15:00", "17:00")]
    assert doctor.journey == "APPOINTMENT_REQUEST" and doctor.dataConfirmed is True
    assert "patientsPerHour" not in result.model_dump_json() and "slot" not in result.model_dump_json().lower()


async def test_late_session_keeps_the_supplied_revised_time_without_adding_the_delay_again(h):
    [doctor] = (await ask(h, doctorId="doc_arjun_menon")).doctors
    morning = doctor.board[0]
    assert morning.status == "LATE" and morning.delayMinutes == 30 and morning.expectedTime == "10:30"
    assert morning.note == "In a ward round" and morning.expectedEndTime == "13:00"


async def test_cancelled_session_stays_visible(h):
    [doctor] = (await ask(h, doctorName="sunita")).doctors
    assert [(b.status, b.note) for b in doctor.board] == [("CANCELLED", "On leave")]
    assert doctor.journey == "APPOINTMENT_REQUEST"  # cancelled today says nothing about another date


async def test_expected_end_time_expiry_uses_facility_time_and_the_requested_date(make_settings):
    before = harness.build(make_settings(), now=datetime(2026, 10, 1, 4, 30, tzinfo=UTC))  # 10:00 IST
    after = harness.build(make_settings(), now=datetime(2026, 10, 1, 6, 0, tzinfo=UTC))  # 11:30 IST
    try:
        [early] = (await ask(before, doctorId="doc_meera_kulkarni")).doctors
        [late] = (await ask(after, doctorId="doc_meera_kulkarni")).doctors
        assert [b.expired for b in early.board] == [False, False]
        assert [b.expired for b in late.board] == [True, False]  # morning ended 11:00; evening untouched
        after.ops_state.set_board("2026-10-02", [
            {"doctorId": "doc_meera_kulkarni", "session": "Morning", "status": "IN", "expectedTime": "09:00",
             "expectedEndTime": "11:00", "updatedMinutesAgo": 1}])
        [tomorrow] = (await ask(after, doctorId="doc_meera_kulkarni", date="2026-10-02")).doctors
        assert tomorrow.board[0].expired is False  # a future session is not expired by today's clock
    finally:
        await before.aclose(), await after.aclose()


async def test_midnight_weekday_is_decided_in_facility_time(make_settings):
    h2 = harness.build(make_settings(), now=datetime(2026, 10, 1, 19, 30, tzinfo=UTC))  # 01:00 IST on Fri 2 Oct
    try:
        result = await ask(h2, doctorId="doc_garima")
        assert result.facilityToday == "2026-10-02" and result.weekday == "FRI"
    finally:
        await h2.aclose()


@pytest.mark.parametrize("doctor_id", ["doc_kiran_hegde", "doc_rohan_shetty"])  # stale entry, missing entry
async def test_unknown_today_stops_the_journey_and_asks_for_callback_details(h, doctor_id):
    result = await ask(h, doctorId=doctor_id)
    assert result.outcome == "CALLBACK_REQUIRED" and result.nextStep == "ASK_CALLBACK_DETAILS"
    [doctor] = result.doctors
    assert doctor.journey == "CALLBACK_ONLY" and all(b.status == "UNKNOWN" for b in doctor.board)
    assert result.callback.ask and "call you back" in result.callback.say
    assert result.callback.summaryOutcome == "CALLBACK_NOTED"
    assert "transfer" not in result.callback.say.lower()
    assert doctor.usualSessions is not None  # hours still shown as background, never as attendance


async def test_unknown_on_a_future_date_also_means_callback(h):
    result = await ask(h, doctorId="doc_garima", date="2026-10-05")
    assert result.outcome == "CALLBACK_REQUIRED" and result.requestedDate == "2026-10-05" and result.weekday == "MON"
    assert result.doctors[0].usualSessions[0].onRequestedDate is True  # MON is a usual day; still not attendance


async def test_a_failed_board_is_a_service_error_not_unknown_and_not_hours(h):
    h.ops_state.fail_next.append(("/availability", 503, {"Retry-After": "4"}))
    result = await ask(h, doctorId="doc_garima")
    assert result.outcome == "COULD_NOT_CHECK" and result.detail == "BOARD_UNAVAILABLE"
    assert result.doctors == [] and result.retryAfterSeconds == 4 and result.nextStep == "SAY_COULD_NOT_CHECK"
    h.ops_state.malformed_next.append("/availability")
    assert (await ask(h, doctorId="doc_garima")).outcome == "COULD_NOT_CHECK"


async def test_profile_failure_still_reports_the_board(h):
    h.ops_state.fail_next.append(("/doctors/doc_garima", 500, {}))
    result = await ask(h, doctorId="doc_garima")
    assert result.outcome == "AVAILABILITY" and result.doctors[0].usualSessions is None
    assert result.detail == "PROFILE_UNAVAILABLE"


async def test_on_call_doctor_with_a_confirmed_entry_is_offered_otherwise_desk(h):
    result = await ask(h, doctorId="doc_vikram_desai")
    [doctor] = result.doctors
    assert doctor.attendanceType == "ON_CALL" and doctor.usualSessions == [] and doctor.board[0].status == "IN"
    assert doctor.journey == "APPOINTMENT_REQUEST"
    h.ops_state.set_board("2026-10-01", [{"doctorId": "doc_vikram_desai", "status": "NOT_CONFIRMED",
                                          "updatedMinutesAgo": 5}])
    unconfirmed = await ask(h, doctorId="doc_vikram_desai")
    assert unconfirmed.doctors[0].journey == "DESK" and unconfirmed.nextStep == "TRANSFER_DESK"


async def test_session_request_scopes_the_board_and_the_unknown_rule(h):
    h.ops_state.set_board("2026-10-01", [
        {"doctorId": "doc_garima", "session": "Morning", "status": "IN", "expectedTime": "09:00",
         "updatedMinutesAgo": 5},
        {"doctorId": "doc_garima", "session": "Afternoon", "status": "IN", "expectedTime": "15:00",
         "updatedMinutesAgo": 500},
    ])
    whole = await ask(h, doctorId="doc_garima")
    assert whole.outcome == "AVAILABILITY" and [b.status for b in whole.doctors[0].board] == ["IN", "UNKNOWN"]
    assert whole.doctors[0].journey == "APPOINTMENT_REQUEST" and whole.doctors[0].unknownSessions == ["Afternoon"]
    afternoon = await ask(h, doctorId="doc_garima", session="afternoon")
    assert afternoon.outcome == "CALLBACK_REQUIRED" and [b.session for b in afternoon.doctors[0].board] == ["Afternoon"]
    morning = await ask(h, doctorId="doc_garima", session="Morning")
    assert morning.outcome == "AVAILABILITY" and [b.session for b in morning.doctors[0].board] == ["Morning"]
    unmatched = await ask(h, doctorId="doc_garima", session="Night")
    assert unmatched.outcome == "AVAILABILITY" and len(unmatched.doctors[0].board) == 2
    assert unmatched.sessionMatched is False


async def test_ambiguous_name_asks_the_caller_to_choose(h):
    result = await ask(h, doctorName="Dr Sharma")
    assert result.outcome == "CLARIFICATION_NEEDED" and result.nextStep == "ASK_WHICH_DOCTOR"
    assert sorted(c.doctorId for c in result.choices) == ["doc_anil_sharma", "doc_ravi_sharma"]
    assert result.complete is True and result.doctors == []
    assert "/availability" not in h.ops_paths()  # no board call before the caller chose


async def test_bounded_search_reports_incompleteness_instead_of_pretending(make_settings):
    h3 = harness.build(make_settings(directory_page_size=3))
    try:
        result = await ask(h3, doctorName="a")  # every demo name contains an 'a': ten matches, three returned
        assert result.outcome == "CLARIFICATION_NEEDED" and len(result.choices) == 3
        assert result.complete is False and result.totalMatches == 10
    finally:
        await h3.aclose()


async def test_unknown_name_is_not_found_never_no_availability(h):
    result = await ask(h, doctorName="Dr Nobody")
    assert result.outcome == "NOT_FOUND" and result.nextStep == "ASK_TO_REPHRASE" and result.doctors == []


async def test_department_by_name_uses_one_board_call_and_no_profile_fan_out(h):
    result = await ask(h, departmentName="cardiology")
    assert result.outcome == "AVAILABILITY" and result.nextStep == "ASK_WHICH_DOCTOR"
    assert sorted(d.doctorId for d in result.doctors) == ["doc_anil_sharma", "doc_ravi_sharma"]
    assert all(d.usualSessions is None for d in result.doctors)  # summaries only: bounded fan-out
    anil = next(d for d in result.doctors if d.doctorId == "doc_anil_sharma")
    ravi = next(d for d in result.doctors if d.doctorId == "doc_ravi_sharma")
    assert anil.board[0].status == "IN" and ravi.board[0].status == "UNKNOWN" and ravi.journey == "CALLBACK_ONLY"
    paths = h.ops_paths()
    assert paths.count("/availability") == 1 and not any(p.startswith("/doctors/") for p in paths)
    assert result.department.id == "dept_cardio"


async def test_department_with_all_unknown_is_callback_required(h):
    result = await ask(h, departmentId="dept_ortho")
    assert result.outcome == "CALLBACK_REQUIRED" and result.doctors[0].journey == "CALLBACK_ONLY"


async def test_department_without_a_consultant_is_never_confirmed(h):
    result = await ask(h, departmentName="Dental")
    assert result.outcome == "NOT_FOUND" and result.detail == "NO_CONSULTANT" and result.nextStep == "TRANSFER_DESK"


async def test_unmatched_department_name_offers_the_real_list(h):
    result = await ask(h, departmentName="bone doctor")
    assert result.outcome == "CLARIFICATION_NEEDED" and result.nextStep == "ASK_WHICH_DEPARTMENT"
    assert "Orthopaedics" in [c.name for c in result.departmentChoices]
    assert "Dental" not in [c.name for c in result.departmentChoices]  # hasConsultant=false is not offered


async def test_routing_decision_comes_from_the_trusted_turn_not_the_model_argument(h):
    ctx = h.ctx(turn="Dr Garima, I have chest pain")
    result = await ask(h, ctx, doctorName="garima")
    assert result.outcome == "ROUTING_REQUIRED" and result.nextStep == "TRANSFER_EMERGENCY"
    assert result.routing.decision == "EMERGENCY_TRANSFER" and "emergency" in result.routing.speak.text.lower()
    assert result.doctors == [] and result.choices == []
    assert h.knowledge_state.routed[-1]["utterance"] == "Dr Garima, I have chest pain"
    assert h.knowledge_state.routed[-1]["callId"] == "call-1"


async def test_desk_and_clarify_decisions_block_routine_results(h):
    desk = await ask(h, h.ctx(turn="severe stomach pain"), doctorName="garima")
    assert desk.outcome == "ROUTING_REQUIRED" and desk.nextStep == "TRANSFER_DESK" and desk.doctors == []
    clarify = await ask(h, h.ctx(turn="my child has stomach pain"), departmentName="paediatrics")
    assert clarify.outcome == "ROUTING_REQUIRED" and clarify.nextStep == "ASK_ROUTING_CLARIFICATION"
    assert clarify.routing.speak.text.startswith("Is this for a child")


async def test_routed_department_fills_a_missing_target(h):
    result = await ask(h, h.ctx(turn="I need a children's doctor"))
    assert result.outcome == "AVAILABILITY" and result.department.name == "Paediatrics"
    assert [d.doctorId for d in result.doctors] == ["doc_meera_kulkarni"]
    assert result.routing.decision == "ROUTE_DEPARTMENT"


async def test_no_target_and_no_routed_department_is_invalid(h):
    result = await ask(h)
    assert result.outcome == "INVALID_REQUEST" and result.detail == "TARGET_REQUIRED"


@pytest.mark.parametrize("break_it", ["missing_turn", "outage", "malformed", "unconfigured", "slow"])
async def test_routing_problems_never_become_clearance(make_settings, break_it):
    settings = make_settings()
    if break_it == "unconfigured":
        settings = make_settings(env="development", knowledge_base_url="")
    hh = harness.build(settings)
    try:
        ctx = hh.ctx(turn=None) if break_it == "missing_turn" else hh.ctx()
        if break_it == "outage":
            hh.knowledge_state.fail_next.append(503)
        if break_it == "malformed":
            hh.knowledge_state.malformed_next.append(True)
        if break_it == "slow":
            await hh.aclose()
            hh = harness.build(make_settings(read_deadline_seconds=0.3, write_deadline_seconds=0.3,
                                             summary_deadline_seconds=0.3, request_timeout_seconds=0.2))
            hh.knowledge_state.delay_seconds = 5
            ctx = hh.ctx()
        result = await ask(hh, ctx, doctorId="doc_garima")
        assert result.outcome == "ROUTING_UNAVAILABLE" and result.doctors == []
        assert result.nextStep == "TRANSFER_DESK"
        expected = {"missing_turn": "TURN_CONTEXT_MISSING", "outage": "ROUTING_UNAVAILABLE",
                    "malformed": "ROUTING_MALFORMED", "unconfigured": "ROUTING_NOT_CONFIGURED",
                    "slow": "ROUTING_UNAVAILABLE"}[break_it]
        assert result.detail == expected
    finally:
        await hh.aclose()


async def test_directory_and_profile_are_cached_but_the_board_is_not(h):
    await ask(h, departmentName="cardiology")
    await ask(h, departmentName="cardiology")
    await ask(h, doctorId="doc_garima")
    await ask(h, doctorId="doc_garima")
    paths = h.ops_paths()
    assert paths.count("/departments") == 1 and paths.count("/doctors/doc_garima") == 1
    assert paths.count("/availability") == 4


async def test_profile_and_board_reads_overlap_once_the_doctor_is_known(h):
    """Both reads start before either finishes: the stub records request order, and both are issued."""
    await ask(h, doctorId="doc_garima")
    assert {"/doctors/doc_garima", "/availability"} <= set(h.ops_paths())


@pytest.mark.parametrize("date,detail", [("2026-09-30", "PAST_DATE"), ("tomorrow", "DATE_FORMAT"),
                                         ("01/10/2026", "DATE_FORMAT")])
async def test_dates_are_today_or_explicit_iso(h, date, detail):
    result = await ask(h, doctorId="doc_garima", date=date)
    assert result.outcome == "INVALID_REQUEST" and result.detail == detail and result.facilityToday == "2026-10-01"


async def test_unconfirmed_profile_data_is_flagged(h):
    h.ops_state.set_board("2026-10-01", [{"doctorId": "doc_kiran_hegde", "session": "Evening", "status": "IN",
                                          "expectedTime": "17:00", "updatedMinutesAgo": 5}])
    [doctor] = (await ask(h, doctorId="doc_kiran_hegde")).doctors
    assert doctor.dataConfirmed is False


async def test_gender_filter_reaches_the_directory(h):
    result = await ask(h, departmentName="General Medicine", gender="FEMALE")
    assert [d.doctorId for d in result.doctors] == ["doc_garima"]
