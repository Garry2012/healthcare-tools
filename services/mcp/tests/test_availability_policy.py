"""Revision 6 policy: owner facts stay intact; decisions never promise attendance."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from frontdesk_mcp import contract

NOW = datetime(2026, 10, 1, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


def policy():
    from frontdesk_mcp import availability_policy
    return availability_policy


def facts(*, statuses=("IN",), end="12:00", attendance="REGULAR", schedule=True):
    p = policy()
    doctor = contract.DoctorDetail(id="d", name="Doctor", active=True, departments=[], attendanceType=attendance,
                                  usualSchedule=[{"label": "Morning", "daysOfWeek": ["MON", "THU"],
                                                  "start": "09:00", "end": "12:00"}] if schedule else [])
    entries = tuple(contract.AvailabilityEntry(doctorId="d", doctorName="Doctor", date="2026-10-01",
                     session="Morning" if i == 0 else "Evening", status=status, isStale=False,
                     expectedTime="09:00" if i == 0 else "17:00", expectedEndTime=end)
                    for i, status in enumerate(statuses))
    return p.DoctorFacts(doctor=doctor, profile=doctor, entries=entries)


def decide(f, date="today", session=None, now=NOW):
    p = policy()
    return p.decide_doctor(f, p.resolve_date(date, now, p.Purpose.AVAILABILITY), session=session, now=now)


@pytest.mark.parametrize("status,want,reason", [
    ("IN", "APPOINTMENT_REQUEST", None), ("LATE", "APPOINTMENT_REQUEST", None),
    ("CANCELLED", "NOT_AVAILABLE", "CANCELLED"),
    ("NOT_CONFIRMED", "CALLBACK_REQUIRED", "BOARD_NOT_CONFIRMED"),
    ("UNKNOWN", "CALLBACK_REQUIRED", "BOARD_UNKNOWN"),
])
def test_each_owner_status_has_a_separate_decision(status, want, reason):
    result = decide(facts(statuses=(status,)))
    assert (result.decision, result.reason) == (want, reason)
    assert result.sessions[0].owner_status == status
    assert result.sessions[0].decision == want


@pytest.mark.parametrize("value,want", [(None, "DATE_REQUIRED"), ("", "DATE_FORMAT"),
    ("tomorrow", "DATE_FORMAT"), ("2026-1-5", "DATE_FORMAT"), ("2026-02-30", "DATE_FORMAT"),
    ("05/10/2026", "DATE_FORMAT"), ("2026-09-30", "PAST_DATE")])
def test_date_errors_are_machine_readable(value, want):
    p = policy()
    assert p.resolve_date(value, NOW, p.Purpose.AVAILABILITY) == want


def test_optional_working_hours_date_and_facility_midnight():
    p = policy()
    assert p.resolve_date(None, NOW, p.Purpose.WORKING_HOURS) is None
    for hour, minute, day in [(23, 59, 1), (0, 0, 2)]:
        now = NOW.replace(day=day, hour=hour, minute=minute)
        result = p.resolve_date("today", now, p.Purpose.AVAILABILITY)
        assert result.value.isoformat() == f"2026-10-0{day}" and result.kind == "TODAY"


@pytest.mark.parametrize("end,decision,reason", [("09:59", "NOT_AVAILABLE", "SESSION_ENDED"),
    ("10:01", "APPOINTMENT_REQUEST", None), (None, "APPOINTMENT_REQUEST", None)])
def test_only_a_supplied_passed_end_time_ends_a_session(end, decision, reason):
    result = decide(facts(end=end))
    assert (result.decision, result.reason) == (decision, reason)


@pytest.mark.parametrize("preferred", ["08:00", "09:30", "23:00"])
def test_specific_time_without_end_hands_off(preferred):
    p = policy()
    result = p.decide_booking(decide(facts(end=None)), session="Morning", preferred_time=preferred)
    assert isinstance(result, p.Handoff) and result.reason == "TIME_NOT_VERIFIABLE"


def test_session_without_time_or_end_can_be_noted():
    p = policy()
    assert isinstance(p.decide_booking(decide(facts(end=None)), session="Morning", preferred_time=None), p.Write)


def test_mixed_sessions_ask_for_choice_but_equal_decisions_do_not():
    p = policy()
    mixed = decide(facts(statuses=("IN", "UNKNOWN")))
    assert mixed.session_choice_required is True
    assert isinstance(p.decide_booking(mixed, session=None, preferred_time=None), p.SessionRequired)
    equal = decide(facts(statuses=("IN", "IN")))
    assert equal.session_choice_required is False
    assert isinstance(p.decide_booking(equal, session=None, preferred_time=None), p.Write)
    chosen = decide(facts(statuses=("IN", "UNKNOWN")), session="evening")
    assert chosen.decision == "CALLBACK_REQUIRED" and len(chosen.sessions) == 1


def test_missing_and_stale_rows_have_distinct_reasons():
    from dataclasses import replace
    f = facts(statuses=("UNKNOWN",))
    assert decide(replace(f, entries=())).reason == "BOARD_ENTRY_MISSING"
    assert decide(f, session="Night").reason == "SESSION_NOT_ON_BOARD"
    stale = f.entries[0].model_copy(update={"isStale": True})
    assert decide(replace(f, entries=(stale,))).reason == "BOARD_STALE"


@pytest.mark.parametrize("day", ["today", "2026-10-05"])
def test_on_call_is_callback_even_when_board_says_in(day):
    p = policy()
    result = decide(facts(attendance="ON_CALL"), date=day)
    assert (result.decision, result.reason) == ("CALLBACK_REQUIRED", "ON_CALL_DOCTOR")
    assert isinstance(p.decide_booking(result, session=None, preferred_time=None), p.Callback)
    hours = p.working_hours(facts(attendance="ON_CALL"), None)
    assert hours.reason == "ON_CALL_DOCTOR" and not hours.sessions


@pytest.mark.parametrize("attendance", ["REGULAR", "VISITING"])
def test_future_uses_usual_days_and_ignores_unknown_board(attendance):
    f = facts(statuses=("UNKNOWN",), attendance=attendance)
    result = decide(f, date="2026-10-05")
    assert result.decision == "APPOINTMENT_REQUEST" and result.basis == "USUAL_SCHEDULE"
    assert all(s.owner_status is None for s in result.sessions)
    assert decide(f, date="2026-10-02").reason == "NOT_USUAL_DAY"
    assert decide(f, date="2026-10-05", session="Evening").reason == "SESSION_NOT_USUAL"
    assert decide(facts(schedule=False), date="2026-10-05").reason == "NO_USUAL_SCHEDULE"


def test_working_hours_are_not_live_attendance():
    p = policy()
    result = p.working_hours(facts(statuses=("UNKNOWN",)), None)
    assert result.basis == "USUAL_SCHEDULE" and len(result.sessions) == 1
    assert result.sessions[0].start == "09:00" and result.sessions[0].owner_status is None


def test_outside_a_known_window_never_writes():
    p = policy()
    result = p.decide_booking(decide(facts()), session="Morning", preferred_time="14:00")
    assert isinstance(result, p.NotAvailable) and result.reason == "TIME_OUTSIDE_SESSION"


@pytest.mark.parametrize("status,hour,doctor_decision,reason", [
    ("IN", 20, "NOT_AVAILABLE", "SESSION_ENDED"),
    ("CANCELLED", 10, "NOT_AVAILABLE", "CANCELLED"),
    ("IN", 10, "APPOINTMENT_REQUEST", "TIME_OUTSIDE_SESSION"),
])
def test_preferred_time_preserves_whole_scope_unavailability_reason(status, hour, doctor_decision, reason):
    p = policy()
    doctor = decide(facts(statuses=(status, status), end="19:00"), now=NOW.replace(hour=hour))
    assert doctor.decision == doctor_decision
    assert len(doctor.sessions) == 2
    assert all(s.decision == doctor_decision for s in doctor.sessions)
    result = p.decide_booking(doctor, session=None, preferred_time="21:00")
    assert isinstance(result, p.NotAvailable) and result.reason == reason


def test_department_rollup_and_counts_do_not_list_callback_as_bookable():
    p = policy()
    good, callback = decide(facts()), decide(facts(attendance="ON_CALL"))
    search = p.SearchState(matches_found=1, checked=2, complete=True)
    result = p.aggregate([callback, good], search)
    assert (result.outcome, result.next_step) == ("AVAILABILITY", "ASK_WHICH_DOCTOR")
    assert p.rank(result.candidates, 3) == [good]
    assert p.aggregate([callback], p.SearchState(0, 1, False)).reason == "SEARCH_INCOMPLETE"
    assert p.aggregate([callback], p.SearchState(0, 1, True)).outcome == "CALLBACK_REQUIRED"
    assert len(p.rank([good] * 5, 3)) == 3


def test_selected_unknown_stays_callback_even_with_an_unverifiable_time():
    p = policy()
    result = p.decide_booking(decide(facts(statuses=("UNKNOWN",), end=None)),
                              session="Morning", preferred_time="10:00")
    assert isinstance(result, p.Callback) and result.reason == "BOARD_UNKNOWN"


def test_failed_profile_cannot_be_a_write_decision():
    from dataclasses import replace
    p = policy()
    decision = decide(replace(facts(), profile=None), date="2026-10-05")
    result = p.decide_booking(decision, session=None, preferred_time=None)
    assert isinstance(result, p.Handoff) and result.reason == "PROFILE_UNAVAILABLE"


def test_end_time_precision_includes_seconds():
    p = policy()
    result = decide(facts(end="10:00"), now=NOW.replace(second=30))
    assert result.decision == "NOT_AVAILABLE" and result.reason == "SESSION_ENDED"
    assert isinstance(p.decide_booking(result, session="Morning", preferred_time=None), p.NotAvailable)


def test_future_unmatched_session_keeps_each_weekdays_facts_and_booking_reason():
    p = policy()
    doctor = contract.DoctorDetail(id="d", name="Doctor", active=True, departments=[], attendanceType="REGULAR",
        usualSchedule=[{"label": "Morning", "daysOfWeek": ["MON"], "start": "09:00", "end": "12:00"},
                       {"label": "Evening", "daysOfWeek": ["TUE"], "start": "17:00", "end": "19:00"}])
    result = decide(p.DoctorFacts(doctor, doctor), date="2026-10-05", session="Evening")
    assert (result.decision, result.reason) == ("NOT_AVAILABLE", "SESSION_NOT_USUAL")
    assert [(s.label, s.decision, s.reason) for s in result.sessions] == [
        ("Morning", "APPOINTMENT_REQUEST", None), ("Evening", "NOT_AVAILABLE", "NOT_USUAL_DAY")]
    booking = p.decide_booking(result, session="Evening", preferred_time=None)
    assert isinstance(booking, p.NotAvailable) and booking.reason == "SESSION_NOT_USUAL"
    assert [s.label for s in booking.alternatives] == ["Morning"]
