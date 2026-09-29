"""Property-based checks of the pure availability engine (domain/availability.py) against the
contract formulas in tests/review/oracle.py. The engine is called through its public function
`compute_sessions` with plain inputs; nothing is mocked. Examples are derandomized so a run is
reproducible; Hypothesis prints the smallest failing session."""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from frontdesk_api.domain import availability as engine

from ..oracle import (
    SessionSpec,
    expected_offered,
    expected_reserve,
    expected_sequence_windows,
    expected_timed_grid,
    expected_total,
    hhmm,
    minutes_of,
)

TZ = ZoneInfo("Asia/Kolkata")
TODAY = date(2026, 9, 23)
FUTURE = date(2026, 9, 24)
NOW = datetime(2026, 9, 23, 10, 0, tzinfo=TZ)
CFG = engine.EngineConfig(default_capacity=12, default_walk_in_reserve_percent=0,
                          default_last_arrival_offset_minutes=15, default_slot_minutes=15)
PROPERTY = settings(max_examples=300, derandomize=True, deadline=None,
                    suppress_health_check=[HealthCheck.too_slow])


@st.composite
def sequence_sessions(draw) -> SessionSpec:
    start = draw(st.integers(6 * 12, 19 * 12)) * 5
    minutes = draw(st.integers(6, 60)) * 5
    end = min(start + minutes, 23 * 60)
    minutes = end - start
    mode = draw(st.sampled_from(["FIXED", "PER_HOUR", "DEFAULT"]))
    if mode == "PER_HOUR":
        value = draw(st.integers(1, 60))  # template rule: at least one minute per position
    elif mode == "FIXED":
        value = draw(st.integers(1, minutes))
    else:
        value = None
        if minutes < CFG.default_capacity:
            mode, value = "FIXED", minutes
    return SessionSpec(hhmm(start), hhmm(end), mode=mode, value=value,
                       reserve_percent=draw(st.integers(0, 100)),
                       last_arrival_offset=draw(st.sampled_from([0, 10, 15, 30])))


@st.composite
def timed_sessions(draw) -> SessionSpec:
    step = draw(st.sampled_from([10, 15, 20, 30]))
    start = draw(st.integers(7 * 12, 17 * 12)) * 5
    minutes = draw(st.integers(2, 16)) * step
    grid = minutes // step
    mode = draw(st.sampled_from(["FIXED", "PER_HOUR", "DEFAULT"]))
    value = {"FIXED": draw(st.integers(1, grid)), "PER_HOUR": draw(st.integers(1, 60 // step)), "DEFAULT": None}[mode]
    return SessionSpec(hhmm(start), hhmm(start + minutes), model="TIMED", mode=mode, value=value, slot_minutes=step,
                       reserve_percent=0)


def compute(spec: SessionSpec, *, on: date = FUTURE, now: datetime = NOW, held=(), board=None,
            data_confirmed: bool = True, policy: str = "BOOKABLE", exceptions=(), channel: str = "AGENT"):
    session = engine.TemplateSessionDef(
        template_session_id="p1", ordinal=1, days_of_week=frozenset(engine.DAYS),
        start=time.fromisoformat(spec.start), end=time.fromisoformat(spec.end), capacity_model=spec.model,
        capacity=engine.CapacityRule(spec.mode, spec.value), slot_minutes=spec.slot_minutes,
        walk_in_reserve_percent=spec.reserve_percent, last_arrival_offset_minutes=spec.last_arrival_offset)
    template = engine.TemplateDef(effective_from=date(2026, 1, 1), effective_to=None, sessions=(session,))
    resource = engine.ResourceDef("res_p", booking_policy=policy, data_confirmed=data_confirmed)
    views = engine.compute_sessions(resource, [template], list(exceptions), board or {}, set(held), on, now, CFG,
                                    channel=channel)
    assert len(views) == 1
    return views[0]


def windows(view) -> dict[int, tuple[str, str]]:
    return {s.position: (s.window_from.strftime("%H:%M"), s.window_to.strftime("%H:%M")) for s in view.slots}


# ---------------------------------------------------------------- future dates: the formulas


@PROPERTY
@given(sequence_sessions())
def test_future_queue_matches_the_contract_exactly(spec):
    view = compute(spec)
    total = expected_total(spec, CFG.default_capacity)
    assert (view.total, view.walk_in_reserve) == (total, expected_reserve(total, spec.reserve_percent))
    assert windows(view) == expected_sequence_windows(spec, default_capacity=CFG.default_capacity)
    offered = expected_offered(spec, CFG.default_capacity)
    assert view.remaining == offered and view.bookable == (offered > 0)
    assert len(view.slots) == offered and all(s.available for s in view.slots)


@PROPERTY
@given(sequence_sessions())
def test_queue_windows_are_adjacent_ordered_and_inside_the_session(spec):
    view = compute(spec)
    got = [windows(view)[p] for p in sorted(windows(view))]
    for lo, hi in got:
        assert spec.start <= lo < hi <= spec.end
    for (_, a_to), (b_from, _) in zip(got, got[1:], strict=False):
        assert a_to == b_from


@PROPERTY
@given(sequence_sessions(), st.data())
def test_held_positions_are_unavailable_and_counted(spec, data):
    offered = expected_offered(spec, CFG.default_capacity)
    positions = data.draw(st.sets(st.integers(1, max(1, offered)), max_size=offered))
    held = {f"slot_ses_res_p_{FUTURE.isoformat()}_1_{p:02d}" for p in positions}
    view = compute(spec, held=held)
    assert view.booked == len(held)
    assert view.remaining == max(0, offered - len(held))
    for slot in view.slots:
        assert slot.available == (view.bookable and slot.slot_id not in held)
    assert view.bookable == (view.remaining > 0)


@PROPERTY
@given(sequence_sessions(), st.sampled_from(["LEFT", "ENDED", "FULL", "CANCELLED", "NOT_OFFERED", "DESK_ONLY"]))
def test_an_unbookable_session_offers_no_slot(spec, how):
    sid = f"ses_res_p_{TODAY.isoformat()}_1"
    board = {"LEFT": {sid: engine.BoardDef(sid, presence="LEFT")},
             "ENDED": {sid: engine.BoardDef(sid, session_ended=True)},
             "FULL": {sid: engine.BoardDef(sid, capacity_state="FULL")}}.get(how)
    cancel = engine.ExceptionDef(1, "exc_1", TODAY, TODAY, "WHOLE_DAY", "UNAVAILABLE")
    exceptions = [cancel] if how == "CANCELLED" else []
    policy = how if how in ("NOT_OFFERED", "DESK_ONLY") else "BOOKABLE"
    early = datetime.combine(TODAY, time(5, 0), TZ)
    view = compute(spec, on=TODAY, now=early, board=board, exceptions=exceptions, policy=policy)
    assert not view.bookable
    assert not view.available_slots()


@PROPERTY
@given(sequence_sessions(), st.booleans(), st.booleans())
def test_unsigned_data_never_reaches_confirmed(spec, by_board, by_exception):
    sid = f"ses_res_p_{TODAY.isoformat()}_1"
    board = {sid: engine.BoardDef(sid, timing_confirmed=True)} if by_board else None
    confirm = engine.ExceptionDef(1, "exc_1", TODAY, TODAY, "WHOLE_DAY", "TIMING_CONFIRMED")
    exceptions = [confirm] if by_exception else []
    early = datetime.combine(TODAY, time(5, 0), TZ)
    view = compute(spec, on=TODAY, now=early, board=board, exceptions=exceptions, data_confirmed=False)
    assert view.timing_certainty in ("EXPECTED", "NOT_CONFIRMED")


# ---------------------------------------------------------------- today: session facts agree with slots


@PROPERTY
@given(sequence_sessions(), st.data())
def test_same_day_bookable_remaining_and_slots_agree(spec, data):
    """RULE (§2.2): bookable=false when remaining == 0. Whatever the moment of the day, the
    session-level answer (bookable, remaining, reason) must agree with the slots it offers."""
    at = data.draw(st.integers(minutes_of(spec.start) - 30, minutes_of(spec.end)))
    now = datetime.combine(TODAY, time(max(0, at) // 60, max(0, at) % 60), TZ)
    view = compute(spec, on=TODAY, now=now)
    available = view.available_slots()
    assert view.bookable == bool(available), (
        f"at {now:%H:%M}: bookable={view.bookable} reason={view.not_bookable_reason} "
        f"remaining={view.remaining} available={len(available)}")
    if view.bookable:
        assert view.remaining == len(available)


# ---------------------------------------------------------------- TIMED


@PROPERTY
@given(timed_sessions())
def test_timed_slots_cover_the_session_grid(spec):
    """RULE (§2.2): TIMED slots = start..end step slotMinutes; capacity caps bookings, not times."""
    view = compute(spec)
    got = [(s.start.strftime("%H:%M"), s.end.strftime("%H:%M")) for s in view.slots]
    assert got == expected_timed_grid(spec), f"total={view.total} grid={len(expected_timed_grid(spec))}"
