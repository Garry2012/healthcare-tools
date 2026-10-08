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
    result = p.decide_booking(decide(facts(end=None)), session="Morning", preferred_time=preferred, now=NOW)
    assert isinstance(result, p.Handoff) and result.reason == "TIME_NOT_VERIFIABLE"


def test_session_without_time_or_end_can_be_noted():
    p = policy()
    assert isinstance(p.decide_booking(decide(facts(end=None)), session="Morning", preferred_time=None, now=NOW),
                      p.Write)


def test_mixed_sessions_ask_for_choice_but_equal_decisions_do_not():
    p = policy()
    mixed = decide(facts(statuses=("IN", "UNKNOWN")))
    assert mixed.session_choice_required is True
    assert isinstance(p.decide_booking(mixed, session=None, preferred_time=None, now=NOW), p.SessionRequired)
    equal = decide(facts(statuses=("IN", "IN")))
    assert equal.session_choice_required is False
    assert isinstance(p.decide_booking(equal, session=None, preferred_time=None, now=NOW), p.Write)
    chosen = decide(facts(statuses=("IN", "UNKNOWN")), session="evening")
    assert chosen.decision == "CALLBACK_REQUIRED" and len(chosen.sessions) == 1


def test_missing_and_stale_rows_have_distinct_reasons():
    from dataclasses import replace
    f = facts(statuses=("UNKNOWN",))
    assert decide(replace(f, entries=())).reason == "BOARD_ENTRY_MISSING"
    assert decide(f, session="Night").reason == "SESSION_NOT_ON_BOARD"
    stale = f.entries[0].model_copy(update={"isStale": True})
    assert decide(replace(f, entries=(stale,))).reason == "BOARD_STALE"


@pytest.mark.parametrize("day,want", [("today", "APPOINTMENT_REQUEST"),
                                      ("2026-10-05", "HANDOFF_REQUIRED")])
def test_on_call_needs_a_confirmed_date_entry_not_usual_hours(day, want):
    p = policy()
    result = decide(facts(attendance="ON_CALL"), date=day)
    assert result.decision == want
    assert result.reason == (None if day == "today" else "ON_CALL_DOCTOR")
    booked = p.decide_booking(result, session=None, preferred_time=None, now=NOW)
    assert isinstance(booked, p.Write if day == "today" else p.Handoff)
    hours = p.working_hours(facts(attendance="ON_CALL"), None)
    assert (hours.decision, hours.reason) == ("HANDOFF_REQUIRED", "ON_CALL_DOCTOR")
    assert not hours.sessions


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
    result = p.decide_booking(decide(facts()), session="Morning", preferred_time="14:00", now=NOW)
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
    result = p.decide_booking(doctor, session=None, preferred_time="21:00", now=NOW.replace(hour=hour))
    assert isinstance(result, p.NotAvailable) and result.reason == reason


def test_department_rollup_and_counts_do_not_list_callback_as_bookable():
    p = policy()
    good, callback = decide(facts()), decide(facts(statuses=("UNKNOWN",)))
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
                              session="Morning", preferred_time="10:00", now=NOW)
    assert isinstance(result, p.Callback) and result.reason == "BOARD_UNKNOWN"


def test_failed_profile_cannot_be_a_write_decision():
    from dataclasses import replace
    p = policy()
    decision = decide(replace(facts(), profile=None), date="2026-10-05")
    result = p.decide_booking(decision, session=None, preferred_time=None, now=NOW)
    assert isinstance(result, p.Handoff) and result.reason == "PROFILE_UNAVAILABLE"


def test_end_time_precision_includes_seconds():
    p = policy()
    result = decide(facts(end="10:00"), now=NOW.replace(second=30))
    assert result.decision == "NOT_AVAILABLE" and result.reason == "SESSION_ENDED"
    assert isinstance(p.decide_booking(result, session="Morning", preferred_time=None, now=NOW.replace(second=30)),
                      p.NotAvailable)


def test_future_unmatched_session_keeps_each_weekdays_facts_and_booking_reason():
    p = policy()
    doctor = contract.DoctorDetail(id="d", name="Doctor", active=True, departments=[], attendanceType="REGULAR",
        usualSchedule=[{"label": "Morning", "daysOfWeek": ["MON"], "start": "09:00", "end": "12:00"},
                       {"label": "Evening", "daysOfWeek": ["TUE"], "start": "17:00", "end": "19:00"}])
    result = decide(p.DoctorFacts(doctor, doctor), date="2026-10-05", session="Evening")
    assert (result.decision, result.reason) == ("NOT_AVAILABLE", "SESSION_NOT_USUAL")
    assert [(s.label, s.decision, s.reason) for s in result.sessions] == [
        ("Morning", "APPOINTMENT_REQUEST", None), ("Evening", "NOT_AVAILABLE", "NOT_USUAL_DAY")]
    booking = p.decide_booking(result, session="Evening", preferred_time=None, now=NOW)
    assert isinstance(booking, p.NotAvailable) and booking.reason == "SESSION_NOT_USUAL"
    assert [s.label for s in booking.alternatives] == ["Morning"]


@pytest.mark.parametrize("day", ["today", "2026-10-05"])
@pytest.mark.parametrize("session", [None, "Morning"])
@pytest.mark.parametrize("preferred", ["09:15", "10:30", "10:45"])
def test_booking_window_uses_facility_minute_only_for_today(day, session, preferred):
    p = policy()
    now = NOW.replace(minute=30, second=40)
    doctor = decide(facts(end="11:00"), date=day, session=session, now=now)
    result = p.decide_booking(doctor, session=session, preferred_time=preferred, now=now)
    if day == "today" and preferred == "09:15":
        assert isinstance(result, p.NotAvailable) and result.reason == "TIME_OUTSIDE_SESSION"
        assert [(s.label, s.start, s.end, s.decision) for s in result.alternatives] == [
            ("Morning", "09:00", "11:00", "APPOINTMENT_REQUEST")]
    else:
        assert isinstance(result, p.Write)


@pytest.mark.parametrize("start,end", [(None, "11:00"), ("09:00", None), (None, None)])
@pytest.mark.parametrize("session", [None, "Morning"])
@pytest.mark.parametrize("preferred", ["09:15", "10:45"])
def test_booking_window_keeps_unknown_boundaries_unverifiable(start, end, session, preferred):
    from dataclasses import replace
    p = policy()
    f = facts(end=end)
    row = f.entries[0].model_copy(update={"expectedTime": start})
    doctor = decide(replace(f, entries=(row,)), session=session, now=NOW.replace(minute=30))
    result = p.decide_booking(doctor, session=session, preferred_time=preferred, now=NOW.replace(minute=30))
    assert isinstance(result, p.Handoff) and result.reason == "TIME_NOT_VERIFIABLE"


# Hand-authored owner facts; expectations below come from C-1 through C-8.
def block(start="10:00", end="10:30", available=2, bookable=True):
    return contract.SlotBlock(start=start, end=end, capacity=3, booked=0,
                              available=available, bookable=bookable)


def slot_session(label="Morning", status="IN", bookable=True, blocks=None):
    return contract.SlotSession(session=label, status=status, bookable=bookable,
                                slots=[block()] if blocks is None else blocks)


def with_slots(f, *sessions, day="2026-10-01"):
    from dataclasses import replace
    return replace(f, slots=contract.SlotPlan(doctorId=f.doctor.id, date=day, enabled=True,
                                             blockMinutes=30, sessions=list(sessions)))


@pytest.mark.parametrize("board,expected", [
    ("UNKNOWN", ["UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN"]),
    ("CANCELLED", ["UNKNOWN", "CANCELLED", "CANCELLED", "CANCELLED", "CANCELLED"]),
    ("NOT_CONFIRMED", ["UNKNOWN", "CANCELLED", "NOT_CONFIRMED", "NOT_CONFIRMED", "NOT_CONFIRMED"]),
    ("LATE", ["UNKNOWN", "CANCELLED", "NOT_CONFIRMED", "LATE", "LATE"]),
    ("IN", ["UNKNOWN", "CANCELLED", "NOT_CONFIRMED", "LATE", "IN"]),
])
@pytest.mark.parametrize("stale", [False, True])
def test_slot_status_reconciliation_preserves_the_most_restrictive_fact(board, expected, stale):
    from dataclasses import replace
    f = facts(statuses=(board,))
    f = replace(f, entries=(f.entries[0].model_copy(update={"isStale": stale}),))
    for status, want in zip(["UNKNOWN", "CANCELLED", "NOT_CONFIRMED", "LATE", "IN"], expected, strict=True):
        result = decide(with_slots(f, slot_session(status=status)))
        row = result.sessions[0]
        assert row.owner_status == want
        if want == "UNKNOWN":
            assert (row.decision, row.reason) == ("CALLBACK_REQUIRED",
                "BOARD_STALE" if board == "UNKNOWN" and stale else "BOARD_UNKNOWN")
            assert row.open_slots == ()
        elif want == "CANCELLED":
            assert (row.decision, row.reason, row.open_slots) == ("NOT_AVAILABLE", "CANCELLED", ())
        else:
            assert (row.decision, row.reason) == ("APPOINTMENT_REQUEST", None)
            assert [b.start for b in row.open_slots] == ["10:00"]


@pytest.mark.parametrize("status,flag,blocks,want,reason", [
    ("UNKNOWN", False, [], "CALLBACK_REQUIRED", "BOARD_UNKNOWN"),
    ("IN", False, [block()], "NOT_AVAILABLE", "NO_OPEN_SLOT"),
    ("IN", True, [], "NOT_AVAILABLE", "NO_OPEN_SLOT"),
    ("IN", True, [block(end="10:00", start="09:30")], "NOT_AVAILABLE", "SESSION_ENDED"),
    ("IN", True, [block(bookable=False)], "NOT_AVAILABLE", "NO_OPEN_SLOT"),
    ("IN", True, [block(available=0)], "NOT_AVAILABLE", "NO_OPEN_SLOT"),
    ("NOT_CONFIRMED", True, [block()], "APPOINTMENT_REQUEST", None),
])
def test_session_slot_precedence_and_empty_offers(status, flag, blocks, want, reason):
    result = decide(with_slots(facts(end="09:00"), slot_session(status=status, bookable=flag, blocks=blocks)))
    assert (result.decision, result.reason) == (want, reason)
    assert result.sessions[0].open_slots == (tuple(blocks) if want == "APPOINTMENT_REQUEST" else ())


@pytest.mark.parametrize("b,now,want", [
    (block(bookable=False), None, "CLOSED"), (block(available=0), None, "FULL"),
    (block(), None, "OPEN"), (block(end="10:00", start="09:30"), NOW, "CLOSED"),
    (block(end="10:00", start="09:30", available=0), NOW, "CLOSED"),
    (block(), NOW.replace(second=59), "OPEN"),
])
def test_block_classification_uses_owner_capacity_and_minute_expiry(b, now, want):
    assert policy().block_state(b, now) == want


@pytest.mark.parametrize("label", ["", None])
def test_today_joins_blank_labels_and_duplicate_board_rows_without_losing_missing_evidence(label):
    from dataclasses import replace
    f = facts(statuses=("IN", "IN", "IN"))
    f = replace(f, entries=(f.entries[0].model_copy(update={"session": label}),
                            f.entries[1].model_copy(update={"session": ""}), f.entries[2]))
    result = decide(with_slots(f, slot_session(label=None), slot_session(label="Extra")))
    assert len(result.sessions) == 4
    assert result.sessions[0].evidence == result.sessions[1].evidence
    assert result.sessions[2].reason == "NO_OPEN_SLOT" and result.sessions[2].open_slots == ()
    extra = result.sessions[3]
    assert (extra.basis, extra.owner_status, extra.start, extra.end) == ("LIVE_BOARD", "IN", "10:00", "10:30")
    assert (extra.delay_minutes, extra.note, extra.is_stale) == (None, None, False)


@pytest.mark.parametrize("capture", [1, 2])
def test_live_capture_policy_keeps_ended_morning_and_offers_only_evening(capture):
    from .test_contract import LIVE_SLOT_CAPTURE_1, LIVE_SLOT_CAPTURE_2
    raw = LIVE_SLOT_CAPTURE_1 if capture == 1 else LIVE_SLOT_CAPTURE_2
    # Board/profile context copied from the same capture; only the display name is synthetic.
    doctor = contract.DoctorDetail(id=raw["doctorId"], name="Capture doctor", active=True, departments=[],
        attendanceType="REGULAR", usualSchedule=[] if capture == 1 else [
            {"label": "Morning", "daysOfWeek": ["MON", "TUE", "WED", "THU", "FRI", "SAT"],
             "start": "10:30", "end": "12:00"},
            {"label": "Evening", "daysOfWeek": ["MON", "TUE", "WED", "THU", "FRI", "SAT"],
             "start": "18:30", "end": "19:30"}])
    board = [(None, "IN", "10:30", "12:00")] if capture == 1 else [
        ("Morning", "NOT_CONFIRMED", None, None), ("Evening", "NOT_CONFIRMED", "18:30", "19:30")]
    entries = tuple(contract.AvailabilityEntry(doctorId=doctor.id, doctorName=doctor.name, date=raw["date"],
        session=label, status=status, expectedTime=start, expectedEndTime=end, isStale=False)
        for label, status, start, end in board)
    f = policy().DoctorFacts(doctor, doctor, entries, contract.SlotPlan.model_validate(raw))
    result = decide(f, now=NOW.replace(day=7, hour=14, minute=35))
    assert (result.sessions[0].decision, result.sessions[0].reason, result.sessions[0].open_slots) == (
        "NOT_AVAILABLE", "SESSION_ENDED", ())
    assert result.sessions[0].owner_status == ("IN" if capture == 1 else "NOT_CONFIRMED")
    if capture == 1:
        assert result.decision == "NOT_AVAILABLE" and not result.alternatives
    else:
        assert result.decision == "APPOINTMENT_REQUEST"
        assert [s.label for s in result.alternatives] == ["Evening"]
        assert [b.start for b in result.sessions[1].open_slots] == ["18:30", "19:00"]


@pytest.mark.parametrize("status,want,reason", [("UNKNOWN", "CALLBACK_REQUIRED", "BOARD_UNKNOWN"),
    ("CANCELLED", "NOT_AVAILABLE", "CANCELLED"), ("NOT_CONFIRMED", "APPOINTMENT_REQUEST", None)])
@pytest.mark.parametrize("day", ["2026-10-05", "2026-10-02"])
def test_future_slot_facts_keep_joined_and_one_day_refusals(status, want, reason, day):
    f = with_slots(facts(), slot_session(status=status), day=day)
    result = decide(f, date=day, now=NOW.replace(hour=23))
    assert (result.decision, result.reason) == (want, reason)
    [row] = result.sessions
    assert row.owner_status == status and row.one_day == (day == "2026-10-02")
    assert row.open_slots == ((block(),) if want == "APPOINTMENT_REQUEST" else ())
    assert policy().on_requested_date(row, policy().resolve_date(day, NOW, policy().Purpose.AVAILABILITY))


@pytest.mark.parametrize("label", ["", None])
@pytest.mark.parametrize("attendance,want", [("REGULAR", "CALLBACK_REQUIRED"), ("ON_CALL", "HANDOFF_REQUIRED")])
def test_future_named_scope_keeps_unlabelled_unresolved_one_day_facts(label, attendance, want):
    p = policy()
    f = with_slots(facts(attendance=attendance), slot_session(),
                   slot_session(label=label, status="UNKNOWN", blocks=[]), day="2026-10-05")
    result = decide(f, date="2026-10-05", session="Morning")
    assert result.decision == want
    assert [s.label for s in result.sessions] == ["Morning", label]
    unresolved = result.sessions[1]
    assert (unresolved.one_day, unresolved.start, unresolved.end, unresolved.open_slots) == (True, None, None, ())
    booking = p.decide_booking(result, session="Morning", preferred_time="10:15", now=NOW)
    assert isinstance(booking, p.Callback if attendance == "REGULAR" else p.Handoff)


def test_future_missing_join_and_weekday_rows_are_separate_from_offers():
    from dataclasses import replace
    f = facts()
    profile = f.profile.model_copy(update={"usualSchedule": [*f.profile.usualSchedule,
        contract.UsualSession(label="Evening", daysOfWeek=["TUE"], start="17:00", end="19:00")]})
    f = with_slots(replace(f, profile=profile), slot_session(label="One day"), day="2026-10-05")
    chosen = decide(f, date="2026-10-05", session="One day")
    assert [s.label for s in chosen.sessions] == ["One day"]
    result = decide(f, date="2026-10-05", session="Night")
    assert result.reason == "SESSION_NOT_USUAL"
    assert [(s.label, s.reason) for s in result.sessions] == [
        ("Morning", "NO_OPEN_SLOT"), ("Evening", "NOT_USUAL_DAY"), ("One day", None)]
    assert [s.label for s in result.alternatives] == ["One day"]


@pytest.mark.parametrize("status,want", [("IN", "APPOINTMENT_REQUEST"), ("UNKNOWN", "CALLBACK_REQUIRED")])
def test_future_without_usual_schedule_can_have_one_day_evidence(status, want):
    f = with_slots(facts(schedule=False), slot_session(status=status), day="2026-10-05")
    assert decide(f, date="2026-10-05").decision == want
    assert decide(with_slots(facts(schedule=False), day="2026-10-05"), date="2026-10-05").reason == "NO_USUAL_SCHEDULE"
    hours = policy().working_hours(f, None)
    assert hours.reason == "NO_USUAL_SCHEDULE" and not hours.sessions


@pytest.mark.parametrize("status,start,end,slots,want,reason", [
    ("IN", "09:00", "12:00", None, "APPOINTMENT_REQUEST", None),
    ("LATE", "09:00", "12:00", None, "APPOINTMENT_REQUEST", None),
    ("IN", "09:00", None, None, "HANDOFF_REQUIRED", "ON_CALL_DOCTOR"),
    ("IN", None, "12:00", None, "HANDOFF_REQUIRED", "ON_CALL_DOCTOR"),
    ("IN", "09:00", "09:59", None, "HANDOFF_REQUIRED", "ON_CALL_DOCTOR"),
    ("UNKNOWN", None, None, None, "HANDOFF_REQUIRED", "ON_CALL_DOCTOR"),
    ("CANCELLED", None, None, None, "NOT_AVAILABLE", "CANCELLED"),
    ("IN", None, None, [block()], "APPOINTMENT_REQUEST", None),
    ("IN", "09:00", "12:00", [block(available=0)], "NOT_AVAILABLE", "NO_OPEN_SLOT"),
    ("IN", None, None, [block(available=0)], "HANDOFF_REQUIRED", "ON_CALL_DOCTOR"),
    ("NOT_CONFIRMED", None, None, [block()], "HANDOFF_REQUIRED", "ON_CALL_DOCTOR"),
])
def test_on_call_requires_confirmed_usable_facts_before_offering_blocks(status, start, end, slots, want, reason):
    from dataclasses import replace
    f = facts(statuses=(status,), attendance="ON_CALL")
    f = replace(f, entries=(f.entries[0].model_copy(update={"expectedTime": start, "expectedEndTime": end}),))
    if slots is not None:
        f = with_slots(f, slot_session(status=status, blocks=slots))
    result = decide(f)
    assert (result.decision, result.reason) == (want, reason)
    assert result.sessions[0].open_slots == (
        None if slots is None else tuple(slots) if want == "APPOINTMENT_REQUEST" else ())


@pytest.mark.parametrize("day", ["today", "2026-10-05"])
@pytest.mark.parametrize("session", [None, "Absent"])
def test_on_call_empty_scope_is_handoff_even_when_profile_is_deliberately_unread(day, session):
    from dataclasses import replace
    f = replace(facts(attendance="ON_CALL"), entries=(), profile=None)
    result = decide(f, date=day, session=session)
    assert (result.decision, result.reason) == ("HANDOFF_REQUIRED", "ON_CALL_DOCTOR")


@pytest.mark.parametrize("status,want", [("IN", "APPOINTMENT_REQUEST"), ("LATE", "APPOINTMENT_REQUEST"),
    ("CANCELLED", "NOT_AVAILABLE"), ("NOT_CONFIRMED", "HANDOFF_REQUIRED"), ("UNKNOWN", "HANDOFF_REQUIRED")])
def test_future_on_call_one_day_uses_status_not_usual_hours(status, want):
    from dataclasses import replace
    f = with_slots(replace(facts(attendance="ON_CALL"), profile=None), slot_session(status=status), day="2026-10-05")
    result = decide(f, date="2026-10-05")
    assert result.decision == want and result.sessions[0].one_day


@pytest.mark.parametrize("day", ["today", "2026-10-05"])
@pytest.mark.parametrize("session", [None, "Morning"])
def test_unread_department_slots_are_matches_not_capacity(day, session):
    from dataclasses import replace
    p = policy()
    f = replace(facts(statuses=("NOT_CONFIRMED",)), slots=p.SlotsNotRead())
    d = decide(f, date=day, session=session)
    assert d.decision == "SLOT_CHECK_REQUIRED" and d.sessions[0].open_slots is None
    result = p.aggregate([d], p.SearchState(1, 1, False))
    assert (result.outcome, result.next_step, result.bookable_found) == ("DOCTORS_MATCHED", "ASK_WHICH_DOCTOR", 0)
    assert p.rank(result.candidates, 1) == [d]


@pytest.mark.parametrize("status", ["UNKNOWN", "CANCELLED"])
@pytest.mark.parametrize("session,want", [(None, "SLOT_CHECK_REQUIRED"), ("Evening", None)])
def test_unread_department_mixed_scope_preserves_refusals(status, session, want):
    from dataclasses import replace
    p = policy()
    f = replace(facts(statuses=("IN", status)), slots=p.SlotsNotRead())
    d = decide(f, session=session)
    assert d.decision == (want or ("CALLBACK_REQUIRED" if status == "UNKNOWN" else "NOT_AVAILABLE"))
    assert d.session_choice_required == (session is None)
    assert [s.label for s in d.alternatives] == ["Morning"]


def test_callback_outranks_handoff_under_a_cap_and_on_call_matches_need_bounds():
    from dataclasses import replace
    p = policy()
    callback = decide(facts(statuses=("UNKNOWN",)))
    handoff = decide(facts(statuses=("UNKNOWN",), attendance="ON_CALL"))
    result = p.aggregate([handoff, callback], p.SearchState(0, 2, True))
    assert result.outcome == "CALLBACK_REQUIRED" and p.rank(result.candidates, 1) == [callback]
    result = p.aggregate([handoff], p.SearchState(0, 1, True))
    assert (result.outcome, result.next_step, result.reason, result.bookable_found) == (
        "HANDOFF_REQUIRED", "TRANSFER_DESK", "ON_CALL_DOCTOR", 0)
    usable = decide(replace(facts(attendance="ON_CALL"), slots=p.SlotsNotRead()))
    assert usable.decision == "SLOT_CHECK_REQUIRED"
    unbounded = decide(replace(facts(attendance="ON_CALL", end=None), slots=p.SlotsNotRead()))
    assert unbounded.decision == "HANDOFF_REQUIRED"
    matches = p.aggregate([handoff, usable], p.SearchState(1, 2, True))
    assert matches.candidates == (usable,) and matches.bookable_found == 0


@pytest.mark.parametrize("day", ["today", "2026-10-05"])
def test_on_call_named_scope_absent_from_existing_day_is_handoff(day):
    f = facts(attendance="ON_CALL")
    if day != "today":
        f = with_slots(f, slot_session(), day=day)
    result = decide(f, date=day, session="Absent")
    assert (result.decision, result.reason) == ("HANDOFF_REQUIRED", "ON_CALL_DOCTOR")


def test_future_join_uses_only_requested_weekday_and_hours_never_receive_evidence():
    from dataclasses import replace
    f = facts()
    profile = f.profile.model_copy(update={"usualSchedule": [*f.profile.usualSchedule,
        contract.UsualSession(label="Morning", daysOfWeek=["TUE"], start="17:00", end="19:00")]})
    f = with_slots(replace(f, profile=profile), slot_session(status="NOT_CONFIRMED"), day="2026-10-05")
    result = decide(f, date="2026-10-05")
    [row] = result.sessions
    assert (row.start, row.end, row.one_day, row.owner_status) == ("09:00", "12:00", False, "NOT_CONFIRMED")
    hours = policy().working_hours(f, None)
    assert len(hours.sessions) == 2
    assert all(s.evidence is None and s.open_slots is None and s.owner_status is None for s in hours.sessions)


@pytest.mark.parametrize("label", ["", None])
def test_unread_department_named_scope_keeps_unlabelled_unknown(label):
    from dataclasses import replace
    p = policy()
    f = facts(statuses=("IN", "UNKNOWN"))
    f = replace(f, entries=(f.entries[0], f.entries[1].model_copy(update={"session": label})), slots=p.SlotsNotRead())
    result = decide(f, session="Morning")
    assert result.decision == "CALLBACK_REQUIRED" and result.reason == "BOARD_UNKNOWN"
    assert all(s.open_slots is None for s in result.sessions)


def test_future_department_wrong_weekday_and_on_call_handoff_are_not_matches():
    from dataclasses import replace
    p = policy()
    wrong_day = decide(replace(facts(), slots=p.SlotsNotRead()), date="2026-10-02")
    oncall = decide(replace(facts(attendance="ON_CALL"), profile=None, slots=p.SlotsNotRead()), date="2026-10-02")
    assert wrong_day.reason == "NOT_USUAL_DAY" and not p.is_match(wrong_day.decision)
    result = p.aggregate([wrong_day, oncall], p.SearchState(0, 2, True))
    assert (result.outcome, result.bookable_found) == ("HANDOFF_REQUIRED", 0)
    assert p.rank(result.candidates, 1) == [oncall]
    incomplete = p.aggregate([wrong_day, oncall], p.SearchState(0, 2, False))
    assert (incomplete.outcome, incomplete.reason) == ("HANDOFF_REQUIRED", "SEARCH_INCOMPLETE")


@pytest.mark.parametrize("t,want", [("09:59", None), ("10:00", "10:00"), ("10:29", "10:00"),
                                    ("10:30", "10:30"), ("11:00", None)])
def test_slot_block_lookup_is_half_open_and_boundary_belongs_to_next(t, want):
    found = policy().block_at((block(), block("10:30", "11:00")), t)
    assert (found.start if found else None) == want


@pytest.mark.parametrize("status,want,reason", [
    ("IN", "TimeRequired", None), ("UNKNOWN", "Callback", "BOARD_UNKNOWN"),
    ("CANCELLED", "NotAvailable", "CANCELLED")])
def test_slot_booking_requires_time_only_after_whole_scope_refusal(status, want, reason):
    p = policy()
    d = decide(with_slots(facts(), slot_session(status=status)))
    result = p.decide_booking(d, session=None, preferred_time=None, now=NOW)
    assert type(result).__name__ == want
    if reason:
        assert result.reason == reason
    else:
        assert result.alternatives == d.alternatives
        assert [b.start for b in result.alternatives[0].open_slots] == ["10:00"]


# The W-2 frozen case table, including session-before-block precedence.
@pytest.mark.parametrize("blocks,flag,t,label,want,reason,expected", [
    ([block(available=0)], True, "10:15", None, "NotAvailable", "NO_OPEN_SLOT", None),
    ([block(available=0)], True, "10:15", "Morning", "NotAvailable", "NO_OPEN_SLOT", None),
    ([block(available=0), block("10:30", "11:00")], True, "10:15", None, "NotAvailable", "SLOT_FULL", None),
    ([block(available=0), block("10:30", "11:00")], True, "10:15", "Morning", "NotAvailable", "SLOT_FULL", None),
    ([block(bookable=False), block("10:30", "11:00")], True, "10:15", None,
     "NotAvailable", "TIME_OUTSIDE_SESSION", None),
    ([block("09:00", "09:30"), block("10:30", "11:00")], True, "09:15", None,
     "NotAvailable", "TIME_OUTSIDE_SESSION", None),
    ([block("09:00", "09:30")], True, "09:15", None, "NotAvailable", "SESSION_ENDED", None),
    ([block()], False, "10:15", None, "NotAvailable", "NO_OPEN_SLOT", None),
    ([block(), block("10:30", "11:00")], True, "10:30", None, "Write", None, "10:30"),
    ([block()], True, "10:30", None, "NotAvailable", "TIME_OUTSIDE_SESSION", None),
    ([block()], True, "14:00", None, "NotAvailable", "TIME_OUTSIDE_SESSION", None),
    ([block()], True, "10:15", None, "Write", None, "10:00"),
])
def test_slot_booking_selected_session_precedes_block_reason(blocks, flag, t, label, want, reason, expected):
    p = policy()
    d = decide(with_slots(facts(), slot_session(bookable=flag, blocks=blocks)), session=label)
    result = p.decide_booking(d, session=label, preferred_time=t, now=NOW)
    assert type(result).__name__ == want
    if want == "Write":
        assert result.expected_slot == expected
    else:
        assert result.reason == reason and result.alternatives == d.alternatives


@pytest.mark.parametrize("other", [False, True])
def test_slot_booking_full_named_session_does_not_depend_on_other_sessions(other):
    p = policy()
    sessions = [slot_session(bookable=True, blocks=[block(available=0)])]
    if other:
        sessions.append(slot_session(label="Evening", blocks=[block("17:00", "17:30")]))
    d = decide(with_slots(facts(), *sessions), session="Morning")
    result = p.decide_booking(d, session="Morning", preferred_time="10:15", now=NOW)
    assert isinstance(result, p.NotAvailable) and result.reason == "NO_OPEN_SLOT"


@pytest.mark.parametrize("real_morning", [False, True])
def test_named_slot_booking_cannot_use_an_unlabelled_open_block(real_morning):
    from dataclasses import replace
    p = policy()
    slots = [slot_session(label=None, blocks=[block("10:30", "11:00")])]
    if real_morning:
        slots.append(slot_session(blocks=[block("11:00", "11:30")]))
    d = decide(with_slots(replace(facts(), entries=()), *slots), session="Morning")
    result = p.decide_booking(d, session="Morning", preferred_time="10:45", now=NOW)
    assert isinstance(result, p.NotAvailable) and result.reason == "TIME_OUTSIDE_SESSION"


@pytest.mark.parametrize("day", ["today", "2026-10-05"])
@pytest.mark.parametrize("bounds", [(None, "12:00"), ("09:00", None), (None, None)])
@pytest.mark.parametrize("slots", [False, True])
def test_booking_d7_labelled_unknown_is_ruled_out_by_matched_time(day, bounds, slots):
    from dataclasses import replace
    p = policy()
    f = facts(statuses=("IN", "UNKNOWN"))
    f = replace(f, entries=(f.entries[0], f.entries[1].model_copy(update={
        "expectedTime": bounds[0], "expectedEndTime": bounds[1], "isStale": True})))
    if slots:
        f = with_slots(f, slot_session(blocks=[block("10:30", "11:00")]),
                       slot_session(label="Evening", status="UNKNOWN", blocks=[]),
                       day="2026-10-01" if day == "today" else day)
    d = decide(f, date=day)
    result = p.decide_booking(d, session=None, preferred_time="10:45", now=NOW)
    assert isinstance(result, p.Write)
    assert result.expected_slot == ("10:30" if slots else None)


@pytest.mark.parametrize("label", ["Earlier", None])
@pytest.mark.parametrize("bounds", [("08:00", "09:30"), (None, None)])
def test_slot_booking_d6_passed_blockless_unknown_window_and_unbounded_fallback(label, bounds):
    from dataclasses import replace
    p = policy()
    f = facts(statuses=("IN", "UNKNOWN"))
    f = replace(f, entries=(f.entries[0], f.entries[1].model_copy(update={
        "session": label, "expectedTime": bounds[0], "expectedEndTime": bounds[1]})))
    d = decide(with_slots(f, slot_session(blocks=[block("10:30", "11:00")]),
                           slot_session(label=label, status="UNKNOWN", blocks=[])))
    result = p.decide_booking(d, session=None, preferred_time="09:00", now=NOW)
    if bounds[0] is None:
        assert isinstance(result, p.Callback) and result.reason == "BOARD_UNKNOWN"
    else:
        assert isinstance(result, p.NotAvailable) and result.reason == "TIME_OUTSIDE_SESSION"
        assert [s.label for s in result.alternatives] == ["Morning"]


@pytest.mark.parametrize("label", [None, "Afternoon"])
def test_slot_booking_retains_blockless_unknown_that_could_contain_time(label):
    from dataclasses import replace
    p = policy()
    f = facts(statuses=("IN", "UNKNOWN"), end="19:00")
    f = replace(f, entries=(f.entries[0], f.entries[1].model_copy(update={"session": label,
        "expectedTime": "15:00", "expectedEndTime": "17:00"})))
    d = decide(with_slots(f, slot_session(), slot_session(label=label, status="UNKNOWN", blocks=[])))
    result = p.decide_booking(d, session=None, preferred_time="15:30", now=NOW)
    assert isinstance(result, p.Callback) and result.reason == "BOARD_UNKNOWN"


@pytest.mark.parametrize("day", ["today", "2026-10-05"])
def test_slot_booking_uses_blocks_without_requiring_board_bounds(day):
    from dataclasses import replace
    p = policy()
    f = replace(facts(), entries=())
    f = with_slots(f, slot_session(blocks=[block("09:00", "09:30"), block("10:30", "11:00")]),
                   day="2026-10-01" if day == "today" else day)
    d = decide(f, date=day)
    result = p.decide_booking(d, session=None, preferred_time="09:15", now=NOW)
    if day == "today":
        assert isinstance(result, p.NotAvailable) and result.reason == "TIME_OUTSIDE_SESSION"
    else:
        assert isinstance(result, p.Write) and result.expected_slot == "09:00"


@pytest.mark.parametrize("session", [None, "Evening"])
def test_slot_booking_stale_labelled_morning_cannot_block_evening(session):
    from dataclasses import replace
    p = policy()
    f = facts(statuses=("UNKNOWN", "IN"), end="19:00")
    f = replace(f, entries=(f.entries[0].model_copy(update={
        "expectedTime": None, "expectedEndTime": None, "isStale": True}), f.entries[1]))
    f = with_slots(f, slot_session(status="UNKNOWN", blocks=[]),
                   slot_session(label="Evening", blocks=[block("17:00", "17:30")]))
    d = decide(f, session=session)
    result = p.decide_booking(d, session=session, preferred_time="17:15", now=NOW)
    assert isinstance(result, p.Write) and result.expected_slot == "17:00"


@pytest.mark.parametrize("day", ["today", "2026-10-05"])
@pytest.mark.parametrize("session", [None, "Morning"])
def test_slot_booking_retains_unlabelled_unknown_beside_matching_open_block(day, session):
    from dataclasses import replace
    p = policy()
    f = facts(statuses=("IN", "UNKNOWN"))
    f = replace(f, entries=(f.entries[0], f.entries[1].model_copy(update={
        "session": None, "expectedTime": None, "expectedEndTime": None})))
    f = with_slots(f, slot_session(), slot_session(label=None, status="UNKNOWN", blocks=[]),
                   day="2026-10-01" if day == "today" else day)
    result = p.decide_booking(decide(f, date=day, session=session), session=session,
                              preferred_time="10:15", now=NOW)
    assert isinstance(result, p.Callback) and result.reason == "BOARD_UNKNOWN"


@pytest.mark.parametrize("status,want", [("IN", "APPOINTMENT_REQUEST"), ("CANCELLED", "NOT_AVAILABLE")])
@pytest.mark.parametrize("slots", [False, True])
def test_booking_matched_time_rules_out_unbounded_labelled_non_unknown_rows(status, want, slots):
    from dataclasses import replace
    p = policy()
    f = facts(statuses=("IN", status))
    f = replace(f, entries=(f.entries[0], f.entries[1].model_copy(update={
        "expectedTime": None, "expectedEndTime": None})))
    if slots:
        f = with_slots(f, slot_session(),
                       slot_session(label="Evening", status=status, blocks=[block("17:00", "17:30")]))
    d = decide(f)
    assert d.sessions[1].decision == want
    result = p.decide_booking(d, session=None, preferred_time="10:15", now=NOW)
    assert isinstance(result, p.Write) and result.expected_slot == ("10:00" if slots else None)


@pytest.mark.parametrize("named", [None, "Morning"])
def test_full_session_precedes_open_sibling_when_selected_by_name_or_time(named):
    p = policy()
    f = with_slots(facts(), slot_session(blocks=[block(available=0)]),
                   slot_session(label="Evening", blocks=[block("17:00", "17:30")]))
    result = p.decide_booking(decide(f, session=named), session=named, preferred_time="10:15", now=NOW)
    assert isinstance(result, p.NotAvailable) and result.reason == "NO_OPEN_SLOT"
    assert [s.label for s in result.alternatives] == ["Evening"]


@pytest.mark.parametrize("kind,reason", [("full", "NO_OPEN_SLOT"), ("ended", "SESSION_ENDED"),
                                       ("oncall", "ON_CALL_DOCTOR"), ("profile", "PROFILE_UNAVAILABLE")])
def test_slot_booking_missing_time_does_not_replace_whole_scope_failures(kind, reason):
    from dataclasses import replace
    p = policy()
    f = with_slots(facts(attendance="ON_CALL" if kind == "oncall" else "REGULAR"), slot_session(
        status="UNKNOWN" if kind == "oncall" else "IN",
        blocks=[block("09:00", "09:30")] if kind == "ended" else [block(available=0)]))
    day = "today"
    if kind == "profile":
        f = replace(f, profile=None)
        day = "2026-10-05"
    result = p.decide_booking(decide(f, date=day), session=None, preferred_time=None, now=NOW)
    assert isinstance(result, p.Handoff if kind in ("oncall", "profile") else p.NotAvailable)
    assert result.reason == reason


@pytest.mark.parametrize("evidence", [None, "unread"])
@pytest.mark.parametrize("kind", ["TODAY", "FUTURE"])
@pytest.mark.parametrize("status", ["IN", "LATE", "NOT_CONFIRMED", "UNKNOWN", "CANCELLED"])
def test_department_unread_end_guard_keeps_status_and_date_precedence(evidence, kind, status):
    p = policy()
    facts = p.SessionFacts(status, False, p.SlotsNotRead() if evidence else None,
                           p.DateKind(kind), NOW.replace(hour=14), "12:00")
    result = p.session_decision(facts)
    if status == "UNKNOWN":
        assert result == ("CALLBACK_REQUIRED", "BOARD_UNKNOWN")
    elif status == "CANCELLED":
        assert result == ("NOT_AVAILABLE", "CANCELLED")
    elif kind == "TODAY" and status == "NOT_CONFIRMED" and evidence is None:
        assert result == ("CALLBACK_REQUIRED", "BOARD_NOT_CONFIRMED")
    elif kind == "TODAY":
        assert result == ("NOT_AVAILABLE", "SESSION_ENDED")
    else:
        assert result == ("SLOT_CHECK_REQUIRED" if evidence else "APPOINTMENT_REQUEST", None)


@pytest.mark.parametrize("end", [None, "10:00", "10:01"])
def test_unread_end_guard_does_not_invent_an_end_or_change_exact_boundary(end):
    p = policy()
    result = p.session_decision(p.SessionFacts("IN", False, p.SlotsNotRead(), p.DateKind.TODAY, NOW, end))
    assert result == ("SLOT_CHECK_REQUIRED", None)
