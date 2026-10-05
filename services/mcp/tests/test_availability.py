"""get_doctor_availability: directory + profile + live board composed in one invocation, without knowledge calls.
UNKNOWN stops the appointment journey (callback only); a failed board
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
    return availability.AvailabilityService(h.ops, h.cache, h.settings, h.clock)


async def ask(h, ctx=None, **args):
    return await service(h).get(ctx or h.ctx(), availability.AvailabilityRequest(**{"date": "today", **args}))


async def test_known_doctor_today_returns_every_window_and_every_board_session(h):
    result = await ask(h, doctorName="garima")
    assert result.outcome == "AVAILABILITY" and result.nextStep == "ASK_WHICH_SESSION"
    assert result.facilityToday == "2026-10-01" and result.requestedDate == "2026-10-01" and result.weekday == "THU"
    [doctor] = result.doctors
    assert doctor.doctorId == "doc_garima" and doctor.departments == ["General Medicine"]
    assert doctor.usualSessions is None
    assert [(b.session, b.status, b.expectedTime, b.expectedEndTime) for b in doctor.board] == [
        ("Morning", "IN", "09:10", "12:00"), ("Afternoon", "NOT_CONFIRMED", "15:00", "17:00")]
    assert doctor.decision == "APPOINTMENT_REQUEST" and doctor.sessionChoiceRequired is True
    assert "patientsPerHour" not in result.model_dump_json() and "slot" not in result.model_dump_json().lower()


async def test_late_session_keeps_the_supplied_revised_time_without_adding_the_delay_again(h):
    [doctor] = (await ask(h, doctorId="doc_arjun_menon")).doctors
    morning = doctor.board[0]
    assert morning.status == "LATE" and morning.delayMinutes == 30 and morning.expectedTime == "10:30"
    assert morning.note == "In a ward round" and morning.expectedEndTime == "13:00"


async def test_cancelled_session_stays_visible(h):
    [doctor] = (await ask(h, doctorName="sunita")).doctors
    assert [(b.status, b.note) for b in doctor.board] == [("CANCELLED", "On leave")]
    assert doctor.decision == "NOT_AVAILABLE" and doctor.reason == "CANCELLED"


async def test_expected_end_time_expiry_uses_facility_time_and_the_requested_date(make_settings):
    before = harness.build(make_settings(), now=datetime(2026, 10, 1, 4, 30, tzinfo=UTC))  # 10:00 IST
    after = harness.build(make_settings(), now=datetime(2026, 10, 1, 6, 0, tzinfo=UTC))  # 11:30 IST
    try:
        [early] = (await ask(before, doctorId="doc_meera_kulkarni")).doctors
        [late] = (await ask(after, doctorId="doc_meera_kulkarni")).doctors
        assert [b.decision for b in early.board] == ["APPOINTMENT_REQUEST", "APPOINTMENT_REQUEST"]
        assert [b.decision for b in late.board] == ["NOT_AVAILABLE", "APPOINTMENT_REQUEST"]
        after.ops_state.set_board("2026-10-02", [
            {"doctorId": "doc_meera_kulkarni", "session": "Morning", "status": "IN", "expectedTime": "09:00",
             "expectedEndTime": "11:00", "updatedMinutesAgo": 1}])
        [tomorrow] = (await ask(after, doctorId="doc_meera_kulkarni", date="2026-10-02")).doctors
        assert tomorrow.board == []  # a future session is not expired by today's clock
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
    assert doctor.decision == "CALLBACK_REQUIRED" and all(b.status == "UNKNOWN" for b in doctor.board)
    assert result.callback.summaryOutcome == "CALLBACK_NOTED"
    assert doctor.usualSessions is None


async def test_future_date_uses_usual_schedule_not_the_board(h):
    result = await ask(h, doctorId="doc_garima", date="2026-10-05")
    assert result.outcome == "AVAILABILITY" and result.requestedDate == "2026-10-05" and result.weekday == "MON"
    assert result.doctors[0].usualSessions[0].onRequestedDate is True
    assert result.nextStep == "OFFER_APPOINTMENT_REQUEST" and "/availability" not in h.ops_paths()


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
    assert result.outcome == "COULD_NOT_CHECK" and result.doctors == []
    assert result.detail == "PROFILE_UNAVAILABLE"


async def test_on_call_doctor_with_a_confirmed_entry_is_offered_otherwise_desk(h):
    result = await ask(h, doctorId="doc_vikram_desai")
    [doctor] = result.doctors
    assert doctor.attendanceType == "ON_CALL" and doctor.usualSessions is None
    assert doctor.decision == "CALLBACK_REQUIRED" and doctor.reason == "ON_CALL_DOCTOR"
    h.ops_state.set_board("2026-10-01", [{"doctorId": "doc_vikram_desai", "status": "NOT_CONFIRMED",
                                          "updatedMinutesAgo": 5}])
    unconfirmed = await ask(h, doctorId="doc_vikram_desai")
    assert unconfirmed.doctors[0].decision == "CALLBACK_REQUIRED" and unconfirmed.nextStep == "ASK_CALLBACK_DETAILS"


async def test_any_unknown_session_in_scope_stops_the_journey(h):
    """Review fix: the caller may mean the UNKNOWN session; without a matched session the whole board is in
    scope and one UNKNOWN entry is enough for callback-only."""
    h.ops_state.set_board("2026-10-01", [
        {"doctorId": "doc_garima", "session": "Morning", "status": "IN", "expectedTime": "09:00",
         "updatedMinutesAgo": 5},
        {"doctorId": "doc_garima", "session": "Afternoon", "status": "IN", "expectedTime": "15:00",
         "updatedMinutesAgo": 500},
    ])
    whole = await ask(h, doctorId="doc_garima")
    assert whole.outcome == "AVAILABILITY" and [b.status for b in whole.doctors[0].board] == ["IN", "UNKNOWN"]
    assert whole.doctors[0].sessionChoiceRequired is True and whole.nextStep == "ASK_WHICH_SESSION"
    afternoon = await ask(h, doctorId="doc_garima", session="afternoon")
    assert afternoon.outcome == "CALLBACK_REQUIRED" and [b.session for b in afternoon.doctors[0].board] == ["Afternoon"]
    morning = await ask(h, doctorId="doc_garima", session="Morning")
    assert morning.outcome == "AVAILABILITY" and [b.session for b in morning.doctors[0].board] == ["Morning"]
    unmatched = await ask(h, doctorId="doc_garima", session="this evening")
    assert unmatched.outcome == "CALLBACK_REQUIRED" and unmatched.sessionMatched is False
    assert unmatched.doctors[0].board == [] and unmatched.detail == "SESSION_NOT_ON_BOARD"


async def test_unmatched_session_without_any_unknown_is_availability(h):
    result = await ask(h, doctorId="doc_garima", session="Night")  # fixture: Morning IN, Afternoon NOT_CONFIRMED
    assert result.outcome == "CALLBACK_REQUIRED" and result.sessionMatched is False
    assert result.detail == "SESSION_NOT_ON_BOARD"


async def test_department_queries_honour_the_session_too(h):
    h.ops_state.set_board("2026-10-01", [
        {"doctorId": "doc_anil_sharma", "session": "Morning", "status": "IN", "expectedTime": "10:00",
         "updatedMinutesAgo": 5},
        {"doctorId": "doc_ravi_sharma", "session": "Evening", "status": "IN", "expectedTime": "16:00",
         "updatedMinutesAgo": 500},  # stale → UNKNOWN
    ])
    evening = await ask(h, departmentName="cardiology", session="Evening")
    assert evening.outcome == "CALLBACK_REQUIRED" and len(evening.doctors) == 2
    none = await ask(h, departmentName="cardiology", session="Night")
    assert none.outcome == "CALLBACK_REQUIRED" and all(d.reason == "SESSION_NOT_ON_BOARD" for d in none.doctors)


async def test_a_board_that_omits_the_doctor_is_treated_as_unknown(h):
    """The contract says a missing entry comes back as UNKNOWN; an owner that returns no row must not make
    usual hours look bookable."""
    h.ops_state.omit_missing_entries = True
    h.ops_state.set_board("2026-10-01", [])
    result = await ask(h, doctorId="doc_garima")
    assert result.outcome == "CALLBACK_REQUIRED" and result.doctors[0].decision == "CALLBACK_REQUIRED"
    assert result.doctors[0].board == [] and result.detail == "BOARD_ENTRY_MISSING"
    department = await ask(h, departmentName="cardiology")
    assert department.outcome == "CALLBACK_REQUIRED"


async def test_ambiguous_name_asks_the_caller_to_choose(h):
    result = await ask(h, doctorName="Dr Sharma")
    assert result.outcome == "CLARIFICATION_NEEDED" and result.nextStep == "ASK_WHICH_DOCTOR"
    assert sorted(c.doctorId for c in result.choices) == ["doc_anil_sharma", "doc_ravi_sharma"]
    assert result.complete is True and result.doctors == []
    assert "/availability" not in h.ops_paths()  # no board call before the caller chose


async def test_bounded_search_reports_incompleteness_instead_of_pretending(make_settings):
    h3 = harness.build(make_settings(doctor_choice_limit=3))
    try:
        result = await ask(h3, doctorName="a")  # every demo name contains an 'a': ten matches, three returned
        assert result.outcome == "CLARIFICATION_NEEDED" and len(result.choices) == 3
        assert result.complete is True and result.totalMatches == 10
    finally:
        await h3.aclose()


async def test_unknown_name_is_not_found_never_no_availability(h):
    result = await ask(h, doctorName="Dr Nobody")
    assert result.outcome == "NOT_FOUND" and result.nextStep == "ASK_TO_REPHRASE" and result.doctors == []


async def test_department_by_name_uses_one_board_call_and_no_profile_fan_out(h):
    result = await ask(h, departmentName="cardiology")
    assert result.outcome == "AVAILABILITY" and result.nextStep == "ASK_WHICH_DOCTOR"
    assert [d.doctorId for d in result.doctors] == ["doc_anil_sharma"]
    assert all(d.usualSessions is None for d in result.doctors)  # summaries only: bounded fan-out
    anil = next(d for d in result.doctors if d.doctorId == "doc_anil_sharma")
    assert anil.board[0].status == "IN" and result.bookableFound == 1 and result.totalMatches == 2
    paths = h.ops_paths()
    assert paths.count("/availability") == 1 and not any(p.startswith("/doctors/") for p in paths)
    assert result.department.id == "dept_cardio"


async def test_department_with_all_unknown_is_callback_required(h):
    result = await ask(h, departmentId="dept_ortho")
    assert result.outcome == "CALLBACK_REQUIRED" and result.doctors[0].decision == "CALLBACK_REQUIRED"


async def test_department_without_a_consultant_is_never_confirmed(h):
    result = await ask(h, departmentName="Dental")
    assert result.outcome == "NOT_FOUND" and result.detail == "NO_CONSULTANT" and result.nextStep == "TRANSFER_DESK"


async def test_department_names_match_exactly_or_ask(h):
    """Review fix: substring matching sent 'dentist' to ENT; only an exact normalised name resolves."""
    partial = await ask(h, departmentName="medicine")  # substring of General Medicine
    assert partial.outcome == "CLARIFICATION_NEEDED" and partial.nextStep == "ASK_WHICH_DEPARTMENT"
    exact = await ask(h, departmentName="  general   MEDICINE ")
    assert exact.outcome == "AVAILABILITY" and exact.department.id == "dept_genmed"


async def test_unmatched_department_name_offers_the_real_list(h):
    result = await ask(h, departmentName="bone doctor")
    assert result.outcome == "CLARIFICATION_NEEDED" and result.nextStep == "ASK_WHICH_DEPARTMENT"
    assert "Orthopaedics" in [c.name for c in result.departmentChoices]
    assert "Dental" not in [c.name for c in result.departmentChoices]  # hasConsultant=false is not offered


async def test_no_target_is_invalid(h):
    result = await ask(h)
    assert result.outcome == "INVALID_REQUEST" and result.detail == "TARGET_REQUIRED"


@pytest.mark.parametrize("target", [{"doctorId": "doc_garima"}, {"doctorName": "garima"},
                                    {"departmentId": "dept_genmed"}])
async def test_working_hours_need_no_date_and_never_read_live_board(h, target):
    result = await ask(h, purpose="WORKING_HOURS", date=None, **target)
    assert result.outcome == "WORKING_HOURS" and result.basis == "USUAL_SCHEDULE"
    assert result.requestedDate is None and result.doctors[0].usualSessions
    assert all(s.onRequestedDate is None for s in result.doctors[0].usualSessions)
    assert "/availability" not in h.ops_paths()


async def test_availability_missing_date_is_an_in_band_request_error(h):
    result = await ask(h, doctorId="doc_garima", date=None)
    assert result.outcome == "INVALID_REQUEST" and result.detail == "DATE_REQUIRED"
    assert h.ops_paths() == []


async def test_working_hours_on_call_does_not_offer_a_booking(h):
    result = await ask(h, purpose="WORKING_HOURS", date=None, doctorId="doc_vikram_desai")
    assert result.outcome == "WORKING_HOURS" and result.nextStep == "ASK_CALLBACK_DETAILS"
    assert result.doctors[0].reason == "NO_REGULAR_HOURS"


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
                                         ("01/10/2026", "DATE_FORMAT"), ("20261005", "DATE_FORMAT"),
                                         ("2026-W41-1", "DATE_FORMAT")])
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


async def test_known_doctor_profile_and_board_overlap(make_settings):
    """Profile and board overlap when the doctor is already known."""
    import time

    hh = harness.build(make_settings(allow_budget_overrides=True, read_deadline_seconds=2.0,
                                     write_deadline_seconds=2.5, request_timeout_seconds=1.5))
    try:
        hh.ops_state.delay_seconds = 0.3
        started = time.monotonic()
        result = await ask(hh, doctorId="doc_garima")
        elapsed = time.monotonic() - started
        assert result.outcome == "AVAILABILITY" and elapsed < 0.5, elapsed  # sequential would be ≥ 0.9 s
    finally:
        await hh.aclose()


# ------------------------------------------------------------------ architect review AR-03


async def test_department_session_query_keeps_a_sessionless_unknown_row(h):
    """AR-03: a sessionless UNKNOWN row cannot be scoped away; it is unknown availability, not 'no such session'."""
    h.ops_state.set_board("2026-10-01", [{"doctorId": "doc_garima", "status": "UNKNOWN", "updatedMinutesAgo": 1}])
    result = await ask(h, departmentName="General Medicine", session="Morning")
    assert result.outcome == "CALLBACK_REQUIRED" and result.nextStep == "ASK_CALLBACK_DETAILS"
    assert any(d.doctorId == "doc_garima" and d.decision == "CALLBACK_REQUIRED" for d in result.doctors)


async def test_department_session_query_with_a_missing_row_is_unknown_too(h):
    h.ops_state.omit_missing_entries = True
    h.ops_state.set_board("2026-10-01", [])
    result = await ask(h, departmentName="General Medicine", session="Morning")
    assert result.outcome == "CALLBACK_REQUIRED"


async def test_doctor_session_query_with_a_sessionless_stale_row_is_unknown(h):
    h.ops_state.set_board("2026-10-01", [{"doctorId": "doc_garima", "status": "IN", "updatedMinutesAgo": 500}])
    result = await ask(h, doctorId="doc_garima", session="Morning")
    assert result.outcome == "CALLBACK_REQUIRED" and result.sessionMatched is False


async def test_a_doctor_who_simply_lacks_the_session_is_not_unknown(h):
    h.ops_state.set_board("2026-10-01", [
        {"doctorId": "doc_anil_sharma", "session": "Morning", "status": "IN", "expectedTime": "10:00",
         "updatedMinutesAgo": 5},
        {"doctorId": "doc_ravi_sharma", "session": "Evening", "status": "IN", "expectedTime": "16:00",
         "updatedMinutesAgo": 5},
    ])
    result = await ask(h, departmentName="cardiology", session="Morning")
    assert result.outcome == "AVAILABILITY" and [d.doctorId for d in result.doctors] == ["doc_anil_sharma"]


# ------------------------------------------------------------------ architect follow-up 1


UNLABELLED_UNKNOWN_BOARD = [
    {"doctorId": "doc_garima", "session": "Morning", "status": "IN", "expectedTime": "09:00",
     "expectedEndTime": "12:00", "updatedMinutesAgo": 1},
    {"doctorId": "doc_garima", "status": "UNKNOWN", "updatedMinutesAgo": 1},  # no label: cannot be scoped away
]


async def test_doctor_session_query_keeps_an_unlabelled_unknown_row_next_to_a_matched_session(h):
    h.ops_state.set_board("2026-10-01", UNLABELLED_UNKNOWN_BOARD)
    result = await ask(h, doctorId="doc_garima", session="Morning")
    assert result.outcome == "CALLBACK_REQUIRED" and result.nextStep == "ASK_CALLBACK_DETAILS"
    assert [(b.session, b.status) for b in result.doctors[0].board] == [("Morning", "IN"), (None, "UNKNOWN")]
    assert result.callback.summaryOutcome == "CALLBACK_NOTED"
    department = await ask(h, departmentName="General Medicine", session="Morning")
    assert department.outcome == "CALLBACK_REQUIRED"


# ------------------------------------------------------------------ re-review (scope / profile failure)


async def test_a_missing_row_for_a_usual_session_today_is_unknown(h):
    h.ops_state.set_board("2026-10-01", [{"doctorId": "doc_garima", "session": "Afternoon", "status": "IN",
                                          "expectedTime": "15:00", "expectedEndTime": "17:00", "updatedMinutesAgo": 1}])
    result = await ask(h, doctorId="doc_garima", session="Morning")
    assert result.outcome == "CALLBACK_REQUIRED" and result.detail == "SESSION_NOT_ON_BOARD"
    afternoon = await ask(h, doctorId="doc_garima", session="Afternoon")
    assert afternoon.outcome == "AVAILABILITY"
    saturday = await ask(h, doctorId="doc_garima", date="2026-10-03", session="Morning")  # not a usual Saturday session
    assert saturday.outcome == "NOT_AVAILABLE" and saturday.detail == "NOT_USUAL_DAY"


async def test_profile_failure_with_no_board_row_is_could_not_check_not_not_found(h):
    h.ops_state.omit_missing_entries = True
    h.ops_state.set_board("2026-10-01", [])
    h.ops_state.fail_next.append(("/doctors/doc_garima", 503, {}))
    result = await ask(h, doctorId="doc_garima")
    assert result.outcome == "COULD_NOT_CHECK" and result.detail == "PROFILE_UNAVAILABLE"


async def test_single_match_search_then_profile_and_board_overlap(make_settings):
    import time

    hh = harness.build(make_settings(allow_budget_overrides=True, read_deadline_seconds=2.0,
                                     write_deadline_seconds=2.5, request_timeout_seconds=1.5))
    try:
        hh.ops_state.delay_seconds = 0.2  # search 0.2 then profile ∥ board 0.2 = 0.4, independent reads
        started = time.monotonic()
        result = await ask(hh, doctorName="garima")
        elapsed = time.monotonic() - started
        assert result.outcome == "AVAILABILITY" and elapsed < 0.55, elapsed  # serial owner reads would be ≥ 0.6
    finally:
        await hh.aclose()


@pytest.mark.parametrize("target,expected,step", [
    ({"doctorId": "doc_garima"}, "AVAILABILITY", "ASK_WHICH_SESSION"),
    ({"doctorName": "garima"}, "AVAILABILITY", "ASK_WHICH_SESSION"),
    ({"doctorName": "Dr Sharma"}, "CLARIFICATION_NEEDED", "ASK_WHICH_DOCTOR"),
    ({"departmentId": "dept_cardio"}, "AVAILABILITY", "ASK_WHICH_DOCTOR"),
    ({"departmentName": "cardiology"}, "AVAILABILITY", "ASK_WHICH_DOCTOR"),
    ({"doctorId": "doc_rohan_shetty"}, "CALLBACK_REQUIRED", "ASK_CALLBACK_DETAILS"),
    ({"doctorName": "Nobody"}, "NOT_FOUND", "ASK_TO_REPHRASE"),
    ({}, "INVALID_REQUEST", "ASK_TO_REPHRASE"),
    ({"doctorId": "doc_garima", "date": "tomorrow"}, "INVALID_REQUEST", "ASK_EXPLICIT_DATE"),
])
@pytest.mark.parametrize("configured", [True, False])
async def test_availability_is_independent_of_knowledge_and_transcript(make_settings, target, expected,
                                                                    step, configured):
    import httpx

    from frontdesk_mcp.context import CallContext
    from frontdesk_mcp.tools import Services
    from frontdesk_stubs import ops as ops_stub

    settings = make_settings(env="development", knowledge_base_url="https://knowledge.test" if configured else "")
    h = harness.build(settings)
    knowledge_requests = []

    async def forbidden(request):
        knowledge_requests.append(request)
        raise AssertionError("availability must not contact knowledge")

    services = Services.build(settings, clock=h.clock,
                              ops_transport=httpx.ASGITransport(app=ops_stub.create_app(h.ops_state, prefix="/api/v1")),
                              knowledge_transport=httpx.MockTransport(forbidden))
    try:
        result = await services.availability.get(CallContext(), availability.AvailabilityRequest(
            **{"date": "today", **target}))
        assert (result.outcome, result.nextStep) == (expected, step)
        assert result.facilityToday == "2026-10-01"
        assert knowledge_requests == []
        if expected == "AVAILABILITY":
            assert result.doctors and result.doctors[0].board
        if expected == "AVAILABILITY":
            ids = {doctor.doctorId for doctor in result.doctors}
            assert ids == ({"doc_anil_sharma"}
                           if "departmentId" in target or "departmentName" in target else {"doc_garima"})
            assert result.choices == []
        if expected == "CLARIFICATION_NEEDED":
            assert {choice.doctorId for choice in result.choices} == {"doc_anil_sharma", "doc_ravi_sharma"}
            assert result.doctors == []
        if expected == "NOT_FOUND":
            assert result.doctors == [] and result.choices == [] and result.departmentChoices == []
        if expected == "CALLBACK_REQUIRED":
            assert result.callback.summaryOutcome == "CALLBACK_NOTED"
        if not target:
            assert result.detail == "TARGET_REQUIRED"
    finally:
        await services.aclose()
        await h.aclose()
