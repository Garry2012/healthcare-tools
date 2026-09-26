"""The availability engine (openapi `getAvailability`, IMPLEMENTATION.md §2.2).

A pure function: template ⊕ exceptions ⊕ board ⊕ held slots, evaluated at `now`.
Nothing here touches the database and nothing it returns is ever persisted.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time

from . import ids

DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
CANCELLED_STATUS = "CANCELLED"
_CERTAINTY_RANK = {"NOT_CONFIRMED": 0, "EXPECTED": 1, "CONFIRMED": 2}


# ---------------------------------------------------------------- inputs


@dataclass(frozen=True, slots=True)
class CapacityRule:
    mode: str  # FIXED | PER_HOUR | DEFAULT
    value: int | None = None


@dataclass(frozen=True, slots=True)
class TemplateSessionDef:
    template_session_id: str
    ordinal: int
    days_of_week: frozenset[str]
    start: time
    end: time
    capacity_model: str  # SEQUENCE | TIMED
    capacity: CapacityRule
    label: str | None = None
    slot_minutes: int | None = None
    walk_in_reserve_percent: int = 0
    last_arrival_offset_minutes: int = 15


@dataclass(frozen=True, slots=True)
class TemplateDef:
    effective_from: date
    effective_to: date | None
    sessions: tuple[TemplateSessionDef, ...]

    def effective_on(self, on: date) -> bool:
        return self.effective_from <= on and (self.effective_to is None or on <= self.effective_to)


@dataclass(frozen=True, slots=True)
class ExceptionDef:
    seq: int
    exception_id: str
    date_from: date
    date_to: date
    scope: str  # WHOLE_DAY | SESSION | TIME_RANGE
    effect: str
    template_session_id: str | None = None
    new_start: time | None = None
    new_end: time | None = None
    new_capacity: int | None = None

    def covers(self, on: date) -> bool:
        return self.date_from <= on <= self.date_to


@dataclass(frozen=True, slots=True)
class BoardDef:
    session_id: str
    presence: str | None = None
    expected_start: time | None = None
    delay_minutes: int | None = None
    session_ended: bool | None = None
    capacity_state: str | None = None
    tokens_issued: int | None = None
    last_arrival_time: time | None = None
    timing_confirmed: bool | None = None


@dataclass(frozen=True, slots=True)
class ResourceDef:
    resource_id: str
    attendance_type: str = "REGULAR"
    booking_policy: str = "BOOKABLE"
    data_confirmed: bool = True


@dataclass(frozen=True, slots=True)
class EngineConfig:
    default_capacity: int = 12
    default_walk_in_reserve_percent: int = 0
    default_last_arrival_offset_minutes: int = 15
    sequence_window_minutes: int = 20
    default_slot_minutes: int = 15


# ---------------------------------------------------------------- outputs


@dataclass(frozen=True, slots=True)
class SlotView:
    slot_id: str
    kind: str
    available: bool
    position: int | None = None
    start: time | None = None
    end: time | None = None
    window_from: time | None = None
    window_to: time | None = None


@dataclass(frozen=True, slots=True)
class SessionView:
    session_id: str
    resource_id: str
    template_session_id: str | None
    date: date
    label: str | None
    start: time
    end: time
    status: str
    timing_certainty: str
    capacity_model: str
    total: int
    booked: int
    remaining: int
    walk_in_reserve: int
    capacity_source: str
    arrive_by: time | None
    bookable: bool
    not_bookable_reason: str | None
    slots: tuple[SlotView, ...]
    presence: str | None = None
    expected_start: time | None = None
    delay_minutes: int | None = None
    tokens_issued: int | None = None

    @property
    def offered_slot_ids(self) -> frozenset[str]:
        return frozenset(s.slot_id for s in self.slots)

    def available_slots(self) -> list[SlotView]:
        return [s for s in self.slots if s.available]


# ---------------------------------------------------------------- helpers


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def _clock(minutes: int) -> time:
    minutes = max(0, min(minutes, 23 * 60 + 59))
    return time(minutes // 60, minutes % 60)


@dataclass(slots=True)
class _Working:
    n: str
    template_session_id: str | None
    label: str | None
    start: time
    end: time
    capacity_model: str
    capacity: CapacityRule
    slot_minutes: int | None
    walk_in_reserve_percent: int
    last_arrival_offset_minutes: int
    status: str = "SCHEDULED"
    certainty: str = "EXPECTED"


def select_template(templates: Iterable[TemplateDef], on: date) -> TemplateDef | None:
    effective = [t for t in templates if t.effective_on(on)]
    return max(effective, key=lambda t: t.effective_from) if effective else None


def _base_sessions(resource: ResourceDef, template: TemplateDef | None, on: date) -> list[_Working]:
    if resource.attendance_type == "ON_CALL" or template is None:
        return []
    weekday = DAYS[on.weekday()]
    return [
        _Working(
            n=str(s.ordinal),
            template_session_id=s.template_session_id,
            label=s.label,
            start=s.start,
            end=s.end,
            capacity_model=s.capacity_model,
            capacity=s.capacity,
            slot_minutes=s.slot_minutes,
            walk_in_reserve_percent=s.walk_in_reserve_percent,
            last_arrival_offset_minutes=s.last_arrival_offset_minutes,
        )
        for s in sorted(template.sessions, key=lambda s: s.ordinal)
        if weekday in s.days_of_week
    ]


def _targets(sessions: list[_Working], exc: ExceptionDef) -> list[_Working]:
    live = [s for s in sessions if s.status != CANCELLED_STATUS]
    if exc.scope == "WHOLE_DAY":
        return live
    if exc.scope == "SESSION":
        return [s for s in live if s.template_session_id == exc.template_session_id]
    if exc.new_start is None or exc.new_end is None:
        return []
    lo, hi = _minutes(exc.new_start), _minutes(exc.new_end)
    return [s for s in live if _minutes(s.start) < hi and lo < _minutes(s.end)]


def _block(session: _Working, exc: ExceptionDef) -> None:
    """UNAVAILABLE over part of a session: keep the longer remaining part."""
    if exc.scope != "TIME_RANGE" or exc.new_start is None or exc.new_end is None:
        session.status = CANCELLED_STATUS
        return
    s, e = _minutes(session.start), _minutes(session.end)
    lo, hi = _minutes(exc.new_start), _minutes(exc.new_end)
    if lo <= s and hi >= e:
        session.status = CANCELLED_STATUS
        return
    before, after = max(0, lo - s), max(0, e - hi)
    if before >= after:
        session.end = _clock(lo)
    else:
        session.start = _clock(hi)
    session.status = "CHANGED"


def apply_exceptions(
    sessions: list[_Working], exceptions: Iterable[ExceptionDef], on: date, cfg: EngineConfig
) -> list[_Working]:
    for exc in sorted((e for e in exceptions if e.covers(on)), key=lambda e: e.seq):
        if exc.effect == "EXTRA_SESSION":
            if exc.new_start is None or exc.new_end is None:
                continue
            sessions.append(
                _Working(
                    n=f"e{exc.seq}",
                    template_session_id=None,
                    label="Extra session",
                    start=exc.new_start,
                    end=exc.new_end,
                    capacity_model="SEQUENCE",
                    capacity=(
                        CapacityRule("FIXED", exc.new_capacity)
                        if exc.new_capacity is not None
                        else CapacityRule("DEFAULT")
                    ),
                    slot_minutes=None,
                    walk_in_reserve_percent=cfg.default_walk_in_reserve_percent,
                    last_arrival_offset_minutes=cfg.default_last_arrival_offset_minutes,
                    status="CHANGED",
                )
            )
            continue
        for s in _targets(sessions, exc):
            if exc.effect == "UNAVAILABLE":
                _block(s, exc)
            elif exc.effect == "TIME_CHANGE" and exc.new_start and exc.new_end:
                s.start, s.end, s.status = exc.new_start, exc.new_end, "CHANGED"
            elif exc.effect == "CAPACITY_CHANGE" and exc.new_capacity is not None:
                s.capacity = CapacityRule("FIXED", exc.new_capacity)
            elif exc.effect == "TIMING_PENDING":
                s.certainty = "NOT_CONFIRMED"
            elif exc.effect == "TIMING_CONFIRMED":
                s.certainty = "CONFIRMED"
    return sessions


def _capacity(s: _Working, cfg: EngineConfig) -> tuple[int, str, float]:
    """(total, capacitySource, customers per hour) for one session."""
    minutes = max(0, _minutes(s.end) - _minutes(s.start))
    hours = minutes / 60 if minutes else 0.0
    mode, value = s.capacity.mode, s.capacity.value
    if s.capacity_model == "TIMED":
        step = s.slot_minutes or cfg.default_slot_minutes
        grid = minutes // step
        if mode == "FIXED" and value is not None:
            total, source = min(grid, value), "FIXED"
        elif mode == "PER_HOUR" and value is not None:
            total, source = min(grid, math.floor(value * hours)), "PER_HOUR"
        else:
            total, source = grid, "DEFAULT"
        return total, source, (60 / step)
    if mode == "FIXED" and value is not None:
        total, source = value, "FIXED"
    elif mode == "PER_HOUR" and value is not None:
        total, source = math.floor(value * hours), "PER_HOUR"
    else:
        total, source = cfg.default_capacity, "DEFAULT"
    if mode == "PER_HOUR" and value:
        pph = float(value)
    else:
        pph = total / hours if hours else float(total or 1)
    return total, source, pph


def compute_sessions(
    resource: ResourceDef,
    templates: Iterable[TemplateDef],
    exceptions: Iterable[ExceptionDef],
    board: Mapping[str, BoardDef],
    held_slot_ids: Iterable[str],
    on: date,
    now: datetime,
    cfg: EngineConfig,
    *,
    channel: str = "AGENT",
) -> list[SessionView]:
    """All session instances for one resource on one date, including CANCELLED tombstones."""
    today = now.date()
    now_min = _minutes(now.time())
    held = set(held_slot_ids)
    working = apply_exceptions(
        _base_sessions(resource, select_template(templates, on), on), exceptions, on, cfg
    )
    views: list[SessionView] = []
    for w in working:
        sid = ids.session_id(resource.resource_id, on, w.n)
        entry = board.get(sid) if on == today else None
        total, source, pph = _capacity(w, cfg)
        reserve = math.ceil(total * w.walk_in_reserve_percent / 100) if total else 0
        offered = max(0, total - reserve)

        certainty = w.certainty
        if entry and entry.timing_confirmed:
            certainty = "CONFIRMED"
        if not resource.data_confirmed and _CERTAINTY_RANK[certainty] > _CERTAINTY_RANK["EXPECTED"]:
            certainty = "EXPECTED"

        delay = entry.delay_minutes if entry else None
        expected_start = entry.expected_start if entry else None
        if expected_start is None and delay:
            expected_start = _clock(_minutes(w.start) + delay)
        run_from = _minutes(expected_start or w.start)
        end_min = _minutes(w.end)

        arrive_by_min = max(_minutes(w.start), end_min - w.last_arrival_offset_minutes)
        if entry and entry.last_arrival_time is not None:
            arrive_by_min = min(arrive_by_min, _minutes(entry.last_arrival_time))
        arrive_by = _clock(arrive_by_min)

        status = w.status
        ended = on < today or (
            on == today and (bool(entry and entry.session_ended) or now_min >= end_min)
        )
        if status != CANCELLED_STATUS and ended:
            status = "ENDED"

        booked = sum(1 for h in held if h.startswith(f"slot_{sid}_"))
        remaining = max(0, offered - booked)

        reason: str | None = None
        if status == CANCELLED_STATUS:
            reason = "CANCELLED"
        elif resource.booking_policy == "NOT_OFFERED":
            reason = "NOT_OFFERED"
        elif entry and entry.presence == "LEFT":
            reason = "LEFT_FOR_DAY"
        elif status == "ENDED":
            reason = "SESSION_ENDED"
        elif (entry and entry.capacity_state == "FULL") or remaining == 0:
            reason = "FULL"
        elif on == today and now_min > arrive_by_min:
            reason = "ARRIVE_BY_PASSED"
        elif channel == "AGENT" and resource.booking_policy == "DESK_ONLY":
            reason = "DESK_ONLY"
        bookable = reason is None

        slots: list[SlotView] = []
        if status != CANCELLED_STATUS:
            if w.capacity_model == "TIMED":
                step = w.slot_minutes or cfg.default_slot_minutes
                for i in range(offered):
                    start_m = _minutes(w.start) + i * step
                    slot_id = ids.timed_slot_id(sid, _clock(start_m).strftime("%H:%M"))
                    slots.append(
                        SlotView(
                            slot_id=slot_id,
                            kind="TIMED",
                            available=bookable and slot_id not in held,
                            start=_clock(start_m),
                            end=_clock(start_m + step),
                        )
                    )
            else:
                interval = 60 / pph if pph else 0
                for position in range(1, offered + 1):
                    slot_id = ids.position_slot_id(sid, position)
                    at = min(run_from + math.floor((position - 1) * interval), end_min)
                    slots.append(
                        SlotView(
                            slot_id=slot_id,
                            kind="SEQUENCE",
                            available=bookable and slot_id not in held,
                            position=position,
                            window_from=_clock(at),
                            window_to=_clock(min(at + cfg.sequence_window_minutes, end_min)),
                        )
                    )

        views.append(
            SessionView(
                session_id=sid,
                resource_id=resource.resource_id,
                template_session_id=w.template_session_id,
                date=on,
                label=w.label,
                start=w.start,
                end=w.end,
                status=status,
                timing_certainty=certainty,
                capacity_model=w.capacity_model,
                total=total,
                booked=booked,
                remaining=remaining,
                walk_in_reserve=reserve,
                capacity_source=source,
                arrive_by=arrive_by if status != CANCELLED_STATUS else None,
                bookable=bookable,
                not_bookable_reason=reason,
                slots=tuple(slots),
                presence=entry.presence if entry else None,
                expected_start=expected_start,
                delay_minutes=delay,
                tokens_issued=entry.tokens_issued if entry else None,
            )
        )
    return sorted(views, key=lambda v: (_minutes(v.start), v.session_id))


def find_session(views: Iterable[SessionView], session_id: str) -> SessionView | None:
    return next((v for v in views if v.session_id == session_id), None)


def without_exception(exceptions: Iterable[ExceptionDef], exception_id: str) -> list[ExceptionDef]:
    return [e for e in exceptions if e.exception_id != exception_id]
