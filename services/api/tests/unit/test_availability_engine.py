"""Golden cases for the availability engine (IMPLEMENTATION.md §2.2)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from frontdesk_api.domain.availability import (
    BoardDef,
    CapacityRule,
    EngineConfig,
    ExceptionDef,
    ResourceDef,
    TemplateDef,
    TemplateSessionDef,
    compute_sessions,
)

IST = ZoneInfo("Asia/Kolkata")
FRI = date(2026, 9, 25)  # "today" in these tests
SUN = date(2026, 9, 27)
MON = date(2026, 9, 28)
THU = date(2026, 10, 1)
NOW = datetime(2026, 9, 25, 8, 0, tzinfo=IST)
CFG = EngineConfig(default_capacity=10, default_last_arrival_offset_minutes=15)

GARIMA = ResourceDef("res_garima")
AM = TemplateSessionDef(
    template_session_id="tpl_res_garima_am", ordinal=1, days_of_week=frozenset({"MON", "THU", "FRI"}),
    start=time(9, 0), end=time(12, 0), capacity_model="SEQUENCE", capacity=CapacityRule("PER_HOUR", 4),
    label="Morning", walk_in_reserve_percent=25, last_arrival_offset_minutes=15,
)
PM = TemplateSessionDef(
    template_session_id="tpl_res_garima_pm", ordinal=2, days_of_week=frozenset({"MON", "THU", "FRI"}),
    start=time(15, 0), end=time(17, 0), capacity_model="SEQUENCE", capacity=CapacityRule("PER_HOUR", 4),
    label="Afternoon", walk_in_reserve_percent=25, last_arrival_offset_minutes=15,
)
TEMPLATE = TemplateDef(date(2026, 9, 1), None, (AM, PM))


def run(on=MON, *, resource=GARIMA, templates=(TEMPLATE,), exceptions=(), board=None, held=(), now=NOW,
        channel="AGENT"):
    return compute_sessions(resource, templates, exceptions, board or {}, held, on, now, CFG, channel=channel)


def exc(seq, effect, *, on=MON, scope="SESSION", tsid="tpl_res_garima_pm", **kw):
    return ExceptionDef(seq=seq, exception_id=f"exc_{seq}", date_from=on, date_to=on, scope=scope,
                        effect=effect, template_session_id=tsid if scope == "SESSION" else None, **kw)


def test_template_only_gives_expected_slots():
    am, pm = run()
    assert (am.session_id, pm.session_id) == ("ses_res_garima_2026-09-28_1", "ses_res_garima_2026-09-28_2")
    assert am.status == pm.status == "SCHEDULED"
    assert am.timing_certainty == pm.timing_certainty == "EXPECTED"
    assert am.bookable and pm.bookable
    assert (am.total, am.walk_in_reserve, len(am.slots)) == (12, 3, 9)
    assert (pm.total, pm.walk_in_reserve, len(pm.slots)) == (8, 2, 6)
    assert am.capacity_source == "PER_HOUR"
    assert am.slots[0].slot_id == "slot_ses_res_garima_2026-09-28_1_01"
    assert all(s.available for s in am.slots)


def test_no_session_on_a_non_template_day():
    assert run(on=date(2026, 9, 29)) == []  # Tuesday


def test_unavailable_exception_removes_the_session():
    am, pm = run(on=THU, exceptions=[exc(1, "UNAVAILABLE", on=THU)])
    assert am.status == "SCHEDULED" and am.bookable
    assert pm.status == "CANCELLED"
    assert pm.bookable is False and pm.not_bookable_reason == "CANCELLED"
    assert pm.slots == () and pm.arrive_by is None


def test_whole_day_unavailable_removes_every_session():
    views = run(exceptions=[exc(1, "UNAVAILABLE", scope="WHOLE_DAY")])
    assert [v.status for v in views] == ["CANCELLED", "CANCELLED"]


def test_time_change_moves_the_session_and_recomputes_capacity():
    am, _ = run(exceptions=[exc(1, "TIME_CHANGE", tsid="tpl_res_garima_am", new_start=time(10), new_end=time(12))])
    assert am.status == "CHANGED"
    assert (am.start, am.end) == (time(10), time(12))
    assert (am.total, len(am.slots)) == (8, 6)
    assert am.slots[0].window_from == time(10)
    assert am.session_id == "ses_res_garima_2026-09-28_1"  # identity survives the move


def test_extra_session_adds_one_on_a_non_template_day():
    [extra] = run(on=SUN, exceptions=[exc(7, "EXTRA_SESSION", on=SUN, scope="TIME_RANGE",
                                         new_start=time(10), new_end=time(12), new_capacity=8)])
    assert extra.session_id == "ses_res_garima_2026-09-27_e7"
    assert extra.status == "CHANGED" and extra.template_session_id is None
    assert (extra.total, extra.capacity_source, len(extra.slots)) == (8, "FIXED", 8)


def test_capacity_change_sets_total():
    _, pm = run(exceptions=[exc(1, "CAPACITY_CHANGE", new_capacity=4)])
    assert (pm.total, pm.walk_in_reserve, len(pm.slots)) == (4, 1, 3)


def test_board_left_makes_session_unbookable():
    sid = "ses_res_garima_2026-09-25_1"
    am, pm = run(on=FRI, board={sid: BoardDef(sid, presence="LEFT")})
    assert am.presence == "LEFT"
    assert (am.bookable, am.not_bookable_reason) == (False, "LEFT_FOR_DAY")
    assert not any(s.available for s in am.slots)
    assert pm.bookable  # the board is per session


def test_board_is_ignored_on_other_days():
    sid = "ses_res_garima_2026-09-28_1"
    am, _ = run(on=MON, board={sid: BoardDef(sid, presence="LEFT")})
    assert am.bookable and am.presence is None


def test_session_ended_flag_and_clock_both_end_a_session():
    sid = "ses_res_garima_2026-09-25_1"
    am, _ = run(on=FRI, board={sid: BoardDef(sid, session_ended=True)})
    assert (am.status, am.not_bookable_reason) == ("ENDED", "SESSION_ENDED")
    late = datetime(2026, 9, 25, 12, 30, tzinfo=IST)
    am, pm = run(on=FRI, now=late)
    assert (am.status, am.not_bookable_reason) == ("ENDED", "SESSION_ENDED")
    assert pm.bookable


def test_past_dates_are_ended():
    am, _ = run(on=date(2026, 9, 24))  # Thursday, yesterday
    assert am.not_bookable_reason == "SESSION_ENDED"


def test_full_from_board_and_from_bookings():
    sid = "ses_res_garima_2026-09-25_2"
    _, pm = run(on=FRI, board={sid: BoardDef(sid, capacity_state="FULL")})
    assert pm.not_bookable_reason == "FULL"
    held = [f"slot_ses_res_garima_2026-09-28_2_{i:02d}" for i in range(1, 7)]
    _, pm = run(held=held)
    assert (pm.booked, pm.remaining, pm.bookable, pm.not_bookable_reason) == (6, 0, False, "FULL")


def test_booked_slot_is_unavailable_and_counted():
    _, pm = run(held=["slot_ses_res_garima_2026-09-28_2_04"])
    assert pm.booked == 1 and pm.remaining == 5
    assert [s.position for s in pm.slots if not s.available] == [4]


def test_arrive_by_is_min_of_desk_value_and_end_minus_offset():
    _, pm = run()
    assert pm.arrive_by == time(16, 45)
    sid = "ses_res_garima_2026-09-25_2"
    _, pm = run(on=FRI, board={sid: BoardDef(sid, last_arrival_time=time(16, 0))})
    assert pm.arrive_by == time(16, 0)
    _, pm = run(on=FRI, board={sid: BoardDef(sid, last_arrival_time=time(16, 55))})
    assert pm.arrive_by == time(16, 45)


def test_arrive_by_passed_today():
    now = datetime(2026, 9, 25, 16, 50, tzinfo=IST)
    _, pm = run(on=FRI, now=now)
    assert (pm.status, pm.not_bookable_reason) == ("SCHEDULED", "ARRIVE_BY_PASSED")


@pytest.mark.parametrize(
    ("effect", "data_confirmed", "expected"),
    [
        (None, True, "EXPECTED"),
        ("TIMING_PENDING", True, "NOT_CONFIRMED"),
        ("TIMING_CONFIRMED", True, "CONFIRMED"),
        ("TIMING_CONFIRMED", False, "EXPECTED"),
        ("TIMING_PENDING", False, "NOT_CONFIRMED"),
    ],
)
def test_timing_certainty_and_data_confirmed_cap(effect, data_confirmed, expected):
    resource = ResourceDef("res_garima", data_confirmed=data_confirmed)
    exceptions = [exc(1, effect)] if effect else []
    _, pm = run(resource=resource, exceptions=exceptions)
    assert pm.timing_certainty == expected


def test_board_timing_confirmed_is_capped_by_unconfirmed_data():
    sid = "ses_res_garima_2026-09-25_2"
    board = {sid: BoardDef(sid, timing_confirmed=True)}
    assert run(on=FRI, board=board)[1].timing_certainty == "CONFIRMED"
    resource = ResourceDef("res_garima", data_confirmed=False)
    assert run(on=FRI, board=board, resource=resource)[1].timing_certainty == "EXPECTED"


def test_walk_in_reserve_reduces_offered_slots():
    no_reserve = TemplateDef(date(2026, 9, 1), None, (
        TemplateSessionDef("tpl_x", 1, frozenset({"MON"}), time(9), time(12), "SEQUENCE",
                           CapacityRule("PER_HOUR", 4), walk_in_reserve_percent=0),
    ))
    [plain] = run(templates=(no_reserve,))
    am, _ = run()
    assert len(plain.slots) == 12
    assert len(am.slots) == 9 and am.walk_in_reserve == 3


def test_sequence_expected_windows():
    am, pm = run()
    windows = [(s.position, s.window_from, s.window_to) for s in am.slots[:3]]
    assert windows == [(1, time(9, 0), time(9, 15)), (2, time(9, 15), time(9, 30)), (3, time(9, 30), time(9, 45))]
    assert pm.slots[3].window_from == time(15, 45)  # position 4 at 4 per hour


@pytest.mark.parametrize(("rate", "boundaries"), [
    (4, [0, 15, 30, 45, 60]),
    (6, [0, 10, 20, 30, 40, 50, 60]),
    (8, [0, 7, 15, 22, 30, 37, 45, 52, 60]),
    (9, [0, 6, 13, 20, 26, 33, 40, 46, 53, 60]),
])
def test_sequence_hourly_boundaries_repeat_without_drift(rate, boundaries):
    session = replace(AM, capacity=CapacityRule("PER_HOUR", rate), walk_in_reserve_percent=0)
    [view] = run(templates=(replace(TEMPLATE, sessions=(session,)),))
    assert view.total == len(view.slots) == 3 * rate
    for hour in range(3):
        slots = view.slots[hour * rate:(hour + 1) * rate]
        actual = [(s.window_from.hour * 60 + s.window_from.minute - (9 + hour) * 60,
                   s.window_to.hour * 60 + s.window_to.minute - (9 + hour) * 60) for s in slots]
        assert actual == list(zip(boundaries, boundaries[1:], strict=False))
    assert view.slots[-1].window_to == time(12)
    assert all(a.window_to == b.window_from for a, b in zip(view.slots, view.slots[1:], strict=False))


@pytest.mark.parametrize(("capacity", "step", "total"), [
    (CapacityRule("FIXED", 9), 20, 9),
    (CapacityRule("DEFAULT"), 18, 10),
])
def test_sequence_session_capacity_divides_the_whole_session(capacity, step, total):
    session = replace(AM, capacity=capacity, walk_in_reserve_percent=0)
    [view] = run(templates=(replace(TEMPLATE, sessions=(session,)),))
    assert len(view.slots) == total
    assert view.slots[0].window_to == time(9, step)
    assert view.slots[-1].window_to == time(12)
    assert all(s.window_to.hour * 60 + s.window_to.minute
               - s.window_from.hour * 60 - s.window_from.minute == step for s in view.slots)


def test_reserves_and_bookings_do_not_shift_sequence_windows():
    [plain] = run(templates=(replace(TEMPLATE, sessions=(replace(AM, walk_in_reserve_percent=0),)),))
    third = plain.slots[2].slot_id
    am, _ = run(held=(third,))
    assert (am.total, am.walk_in_reserve, am.booked, am.remaining) == (12, 3, 1, 8)
    assert [(s.slot_id, s.window_from, s.window_to) for s in am.slots] == [
        (s.slot_id, s.window_from, s.window_to) for s in plain.slots[:9]]
    assert [s.position for s in am.available_slots()] == [1, 2, 4, 5, 6, 7, 8, 9]


def test_partial_hour_keeps_the_hourly_rate():
    session = replace(AM, end=time(10, 10), capacity=CapacityRule("PER_HOUR", 9), walk_in_reserve_percent=0)
    [view] = run(templates=(replace(TEMPLATE, sessions=(session,)),))
    assert view.total == len(view.slots) == 10
    assert (view.slots[-1].window_from, view.slots[-1].window_to) == (time(10), time(10, 6))


@pytest.mark.parametrize("capacity", [CapacityRule("PER_HOUR", 61), CapacityRule("FIXED", 181)])
def test_legacy_sub_minute_capacity_is_not_offered(capacity):
    session = replace(AM, capacity=capacity)
    [view] = run(templates=(replace(TEMPLATE, sessions=(session,)),))
    assert not view.bookable and view.not_bookable_reason == "NOT_OFFERED"
    assert not view.slots


def test_delayed_windows_are_clamped_and_zero_length_positions_are_not_offered():
    sid = "ses_res_garima_2026-09-25_1"
    session = replace(AM, walk_in_reserve_percent=0)
    [view] = run(on=FRI, templates=(replace(TEMPLATE, sessions=(session,)),),
                 board={sid: BoardDef(sid, delay_minutes=20)})
    assert (view.slots[0].window_from, view.slots[0].window_to) == (time(9, 20), time(9, 35))
    assert (view.slots[10].window_from, view.slots[10].window_to) == (time(11, 50), time(12))
    assert not view.slots[11].available
    assert all(s.window_from < s.window_to <= time(12) for s in view.available_slots())


def test_sequence_windows_follow_a_late_start():
    sid = "ses_res_garima_2026-09-25_1"
    am, _ = run(on=FRI, board={sid: BoardDef(sid, presence="ARRIVING", delay_minutes=20)})
    assert am.expected_start == time(9, 20)
    assert am.slots[0].window_from == time(9, 20)
    assert am.bookable


def test_timed_slot_generation():
    timed = TemplateDef(date(2026, 9, 1), None, (
        TemplateSessionDef("tpl_obg", 1, frozenset({"MON"}), time(10), time(11), "TIMED",
                           CapacityRule("DEFAULT"), slot_minutes=15),
    ))
    [view] = run(templates=(timed,), held=["slot_ses_res_garima_2026-09-28_1_1015"])
    assert view.capacity_model == "TIMED" and view.total == 4
    assert [(s.slot_id[-4:], s.start, s.end, s.available) for s in view.slots] == [
        ("1000", time(10, 0), time(10, 15), True),
        ("1015", time(10, 15), time(10, 30), False),
        ("1030", time(10, 30), time(10, 45), True),
        ("1045", time(10, 45), time(11, 0), True),
    ]
    assert all(s.kind == "TIMED" and s.position is None for s in view.slots)


def test_default_capacity_is_flagged():
    tpl = TemplateDef(date(2026, 9, 1), None, (
        TemplateSessionDef("tpl_v", 1, frozenset({"MON"}), time(14), time(17), "SEQUENCE", CapacityRule("DEFAULT")),
    ))
    [view] = run(templates=(tpl,))
    assert (view.total, view.capacity_source) == (10, "DEFAULT")


def test_desk_only_blocks_the_agent_but_not_the_desk():
    resource = ResourceDef("res_garima", booking_policy="DESK_ONLY")
    am, _ = run(resource=resource)
    assert (am.bookable, am.not_bookable_reason) == (False, "DESK_ONLY")
    am, _ = run(resource=resource, channel="DESK")
    assert am.bookable


def test_on_call_resource_only_has_extra_sessions():
    resource = ResourceDef("res_garima", attendance_type="ON_CALL")
    assert run(resource=resource) == []
    [extra] = run(resource=resource, exceptions=[exc(3, "EXTRA_SESSION", scope="TIME_RANGE",
                                                 new_start=time(18), new_end=time(19))])
    assert extra.bookable and extra.capacity_source == "DEFAULT"


def test_template_effective_dates_are_respected():
    old = TemplateDef(date(2026, 1, 1), date(2026, 9, 27), (AM,))
    new = TemplateDef(date(2026, 9, 28), None, (PM,))
    assert [v.label for v in run(on=FRI, templates=(old, new))] == ["Morning"]
    assert [v.label for v in run(on=MON, templates=(old, new))] == ["Afternoon"]


def test_partial_time_range_block_keeps_the_longer_part():
    [am, _] = run(exceptions=[exc(1, "UNAVAILABLE", scope="TIME_RANGE", new_start=time(11), new_end=time(12))])
    assert (am.start, am.end, am.status) == (time(9), time(11), "CHANGED")


def test_timed_slots_that_already_started_today_are_not_offered():
    timed = TemplateDef(date(2026, 9, 1), None, (
        TemplateSessionDef("tpl_obg", 1, frozenset({"FRI"}), time(10), time(11), "TIMED",
                           CapacityRule("DEFAULT"), slot_minutes=15, last_arrival_offset_minutes=0),
    ))
    [view] = run(on=FRI, templates=(timed,), now=datetime(2026, 9, 25, 10, 20, tzinfo=IST))
    assert view.bookable
    assert [(s.slot_id[-4:], s.available) for s in view.slots] == [
        ("1000", False), ("1015", False), ("1030", True), ("1045", True),
    ]
    assert view.remaining == 2


def test_queue_positions_whose_window_has_closed_are_not_offered():
    # 4 per hour from 09:00: at 10:00 the first four 15-minute windows have closed.
    am, _ = run(on=FRI, now=datetime(2026, 9, 25, 10, 0, tzinfo=IST))
    available = [s.position for s in am.slots if s.available]
    assert available[0] == 5 and 4 not in available
    assert am.remaining == len(available)
    assert am.bookable


def test_future_days_are_not_trimmed_by_the_clock():
    am, _ = run(on=MON, now=datetime(2026, 9, 25, 23, 0, tzinfo=IST))
    assert all(s.available for s in am.slots)


def test_a_huge_queue_is_capped_so_slot_ids_stay_unambiguous():
    big = TemplateDef(date(2026, 9, 1), None, (
        TemplateSessionDef("tpl_big", 1, frozenset({"MON"}), time(0), time(23), "SEQUENCE",
                           CapacityRule("FIXED", 1500)),
    ))
    [view] = run(templates=(big,))
    assert view.total == 999
    assert max(len(s.slot_id.rsplit("_", 1)[1]) for s in view.slots) == 3
