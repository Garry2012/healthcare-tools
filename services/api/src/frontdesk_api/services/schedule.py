"""Loads the four inputs of the availability engine for a set of doctors and dates, then
evaluates the engine. One indexed query per table, never cached across requests."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..db import tables as t
from ..domain import availability as engine


def template_session_def(row: t.TemplateSession) -> engine.TemplateSessionDef:
    return engine.TemplateSessionDef(
        template_session_id=row.template_session_id,
        ordinal=row.ordinal,
        days_of_week=frozenset(row.days_of_week),
        start=row.start_time,
        end=row.end_time,
        capacity_model=row.capacity_model,
        capacity=engine.CapacityRule(row.capacity_mode, row.capacity_value),
        label=row.label,
        slot_minutes=row.slot_minutes,
        walk_in_reserve_percent=row.walk_in_reserve_percent,
        last_arrival_offset_minutes=row.last_arrival_offset_minutes,
    )


def exception_def(row: t.ScheduleException) -> engine.ExceptionDef:
    return engine.ExceptionDef(
        seq=row.seq,
        exception_id=row.id,
        date_from=row.date_from,
        date_to=row.date_to,
        scope=row.scope,
        effect=row.effect,
        template_session_id=row.template_session_id,
        new_start=row.new_start,
        new_end=row.new_end,
        new_capacity=row.new_capacity,
    )


def board_def(row: t.BoardEntry) -> engine.BoardDef:
    return engine.BoardDef(
        session_id=row.session_id,
        presence=row.presence,
        expected_start=row.expected_start,
        delay_minutes=row.delay_minutes,
        session_ended=row.session_ended,
        capacity_state=row.capacity_state,
        tokens_issued=row.tokens_issued,
        last_arrival_time=row.last_arrival_time,
        timing_confirmed=row.timing_confirmed,
    )


def doctor_def(row: t.Doctor) -> engine.DoctorDef:
    return engine.DoctorDef(
        doctor_id=row.id,
        attendance_type=row.attendance_type,
        booking_policy=row.booking_policy,
        data_confirmed=row.data_confirmed,
    )


@dataclass(slots=True)
class ScheduleData:
    now: datetime
    settings: Settings
    doctors: dict[str, t.Doctor]
    templates: dict[str, list[engine.TemplateDef]] = field(default_factory=dict)
    exceptions: dict[str, list[engine.ExceptionDef]] = field(default_factory=dict)
    board: dict[str, engine.BoardDef] = field(default_factory=dict)
    held: dict[str, set[str]] = field(default_factory=dict)

    def sessions(
        self,
        doctor_id: str,
        on: date,
        *,
        channel: str = "AGENT",
        exceptions: Iterable[engine.ExceptionDef] | None = None,
        templates: Iterable[engine.TemplateDef] | None = None,
    ) -> list[engine.SessionView]:
        doctor = self.doctors[doctor_id]
        return engine.compute_sessions(
            doctor_def(doctor),
            self.templates.get(doctor_id, []) if templates is None else templates,
            self.exceptions.get(doctor_id, []) if exceptions is None else exceptions,
            self.board,
            self.held.get(doctor_id, set()),
            on,
            self.now,
            self.settings.engine,
            channel=channel,
        )


def daterange(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


async def load(
    session: AsyncSession,
    settings: Settings,
    now: datetime,
    doctor_ids: Iterable[str],
    date_from: date,
    date_to: date,
) -> ScheduleData:
    ids = sorted(set(doctor_ids))
    doctors = {
        d.id: d for d in (await session.scalars(select(t.Doctor).where(t.Doctor.id.in_(ids)))).all()
    }
    data = ScheduleData(now=now, settings=settings, doctors=doctors)
    if not doctors:
        return data
    ids = list(doctors)

    templates = (
        await session.scalars(select(t.ScheduleTemplate).where(t.ScheduleTemplate.doctor_id.in_(ids)))
    ).all()
    template_ids = [tpl.id for tpl in templates]
    sessions_by_template: dict[str, list[t.TemplateSession]] = defaultdict(list)
    if template_ids:
        rows = await session.scalars(
            select(t.TemplateSession).where(t.TemplateSession.template_id.in_(template_ids))
        )
        for row in rows:
            sessions_by_template[row.template_id].append(row)
    for tpl in templates:
        data.templates.setdefault(tpl.doctor_id, []).append(
            engine.TemplateDef(
                effective_from=tpl.effective_from,
                effective_to=tpl.effective_to,
                sessions=tuple(template_session_def(s) for s in sessions_by_template[tpl.id]),
            )
        )

    exceptions = await session.scalars(
        select(t.ScheduleException)
        .where(
            t.ScheduleException.doctor_id.in_(ids),
            t.ScheduleException.deleted_at.is_(None),
            t.ScheduleException.date_from <= date_to,
            t.ScheduleException.date_to >= date_from,
        )
        .order_by(t.ScheduleException.seq)
    )
    for row in exceptions:
        data.exceptions.setdefault(row.doctor_id, []).append(exception_def(row))

    today = now.date()
    if date_from <= today <= date_to:
        board = await session.scalars(
            select(t.BoardEntry).where(t.BoardEntry.doctor_id.in_(ids), t.BoardEntry.date == today)
        )
        data.board = {row.session_id: board_def(row) for row in board}

    held = await session.execute(
        select(t.Appointment.doctor_id, t.Appointment.slot_id).where(
            t.Appointment.doctor_id.in_(ids),
            t.Appointment.date >= date_from,
            t.Appointment.date <= date_to,
            t.Appointment.status.in_(t.LIVE_STATUSES),
        )
    )
    for doctor_id, slot_id in held:
        data.held.setdefault(doctor_id, set()).add(slot_id)
    return data


def now_in(settings: Settings) -> datetime:
    return datetime.now(settings.tz)
