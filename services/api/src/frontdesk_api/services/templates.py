"""A resource's recurring week (schedule templates). Replacing a template impacts the
bookings that no longer fit; session ids stay stable across template versions."""

from __future__ import annotations

from datetime import time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import schemas as s
from ..config import Settings
from ..db import tables as t
from ..domain.intervals import weekly_clash
from ..errors import not_found, validation
from . import directory, impact, schedule, views


def _template_model(tpl: t.ScheduleTemplate, sessions: list[t.TemplateSession]) -> s.ScheduleTemplate:
    return s.ScheduleTemplate(
        resource_id=tpl.resource_id,
        effective_from=tpl.effective_from,
        effective_to=tpl.effective_to,
        sessions=[
            s.TemplateSession(
                template_session_id=row.template_session_id,
                label=row.label,
                days_of_week=row.days_of_week,
                start=views.clock(row.start_time),
                end=views.clock(row.end_time),
                capacity_model=row.capacity_model,
                slot_minutes=row.slot_minutes,
                capacity=s.CapacitySpec(mode=row.capacity_mode, value=row.capacity_value),
                walk_in_reserve_percent=row.walk_in_reserve_percent,
                last_arrival_offset_minutes=row.last_arrival_offset_minutes,
            )
            for row in sorted(sessions, key=lambda r: r.ordinal)
        ],
    )


async def get_template(session: AsyncSession, settings: Settings, resource_id: str) -> s.ScheduleTemplate:
    await directory.require_resource(session, resource_id)
    today = schedule.now_in(settings).date()
    rows = (
        await session.scalars(
            select(t.ScheduleTemplate)
            .where(t.ScheduleTemplate.resource_id == resource_id)
            .order_by(t.ScheduleTemplate.effective_from.desc())
        )
    ).all()
    current = next(
        (r for r in rows if r.effective_from <= today and (r.effective_to is None or today <= r.effective_to)),
        rows[0] if rows else None,
    )
    if current is None:
        raise not_found("This resource has no schedule template.")
    sessions = (
        await session.scalars(select(t.TemplateSession).where(t.TemplateSession.template_id == current.id))
    ).all()
    return _template_model(current, list(sessions))


def _validate_template(body: s.ScheduleTemplate) -> None:
    seen: set[str] = set()
    for i, sess in enumerate(body.sessions):
        where = f"sessions[{i}]"
        if sess.template_session_id in seen:
            raise validation("templateSessionId must be unique within a template.", where)
        seen.add(sess.template_session_id)
        if sess.end <= sess.start:
            raise validation("end must be after start.", f"{where}.end")
        if sess.capacity_model == "TIMED" and not sess.slot_minutes:
            raise validation("TIMED sessions need slotMinutes.", f"{where}.slotMinutes")
        if sess.capacity.mode != "DEFAULT" and sess.capacity.value is None:
            raise validation("capacity.value is required unless mode is DEFAULT.", f"{where}.capacity")
    if body.effective_to is not None and body.effective_to < body.effective_from:
        raise validation("effectiveTo must not be before effectiveFrom.", "effectiveTo")
    for i, sess in enumerate(body.sessions):
        for other in body.sessions[:i]:
            if weekly_clash(sess.days_of_week, sess.start, sess.end, other.days_of_week, other.start, other.end):
                raise validation(f"Overlaps {other.template_session_id} on the same day.", f"sessions[{i}]")


async def set_template(
    session: AsyncSession, settings: Settings, resource_id: str, body: s.ScheduleTemplate, actor: str
) -> s.ScheduleTemplate:
    resource = await directory.require_resource(session, resource_id)
    if body.resource_id != resource_id:
        raise validation("resourceId must match the path.", "resourceId")
    await schedule.lock_resource(session, resource.id, exclusive=True)
    _validate_template(body)
    now = schedule.now_in(settings)
    if body.effective_from < now.date():
        raise validation("A template cannot take effect before today (history is never rewritten).",
                         "effectiveFrom")
    start = max(body.effective_from, now.date())
    last_appt = await session.scalar(
        select(t.Booking.date)
        .where(t.Booking.resource_id == resource_id, t.Booking.date >= start)
        .order_by(t.Booking.date.desc())
        .limit(1)
    )
    end = last_appt or start
    before = await schedule.load(session, settings, now, [resource_id], start, end)

    existing = (
        await session.scalars(select(t.ScheduleTemplate).where(t.ScheduleTemplate.resource_id == resource_id))
    ).all()
    # Session ids (ses_<resource>_<date>_<n>) are held by bookings: a session keeps its n across
    # template versions, and a new session never reuses one (tech-lead TL2).
    known = dict((await session.execute(
        select(t.TemplateSession.template_session_id, t.TemplateSession.ordinal)
        .join(t.ScheduleTemplate, t.ScheduleTemplate.id == t.TemplateSession.template_id)
        .where(t.ScheduleTemplate.resource_id == resource_id)
        .order_by(t.ScheduleTemplate.effective_from)
    )).all())
    next_ordinal = max(known.values(), default=0) + 1
    ordinals: dict[str, int] = {}
    for sess in body.sessions:
        if sess.template_session_id in known:
            ordinals[sess.template_session_id] = known[sess.template_session_id]
        else:
            ordinals[sess.template_session_id] = next_ordinal
            next_ordinal += 1
    for row in existing:
        if row.effective_from == body.effective_from:
            await session.delete(row)
        elif row.effective_from < body.effective_from and (
            row.effective_to is None or row.effective_to >= body.effective_from
        ):
            row.effective_to = body.effective_from - timedelta(days=1)
    later = [r.effective_from for r in existing if r.effective_from > body.effective_from]
    effective_to = body.effective_to
    if later and (effective_to is None or effective_to >= min(later)):
        effective_to = min(later) - timedelta(days=1)
    await session.flush()

    template = t.ScheduleTemplate(
        id=f"tpl_{resource_id}_{body.effective_from.isoformat()}",
        resource_id=resource_id,
        effective_from=body.effective_from,
        effective_to=effective_to,
        created_by=actor,
    )
    session.add(template)
    rows = [
        t.TemplateSession(
            template_id=template.id,
            template_session_id=sess.template_session_id,
            ordinal=ordinals[sess.template_session_id],
            label=sess.label,
            days_of_week=[d.value for d in sess.days_of_week],
            start_time=time.fromisoformat(sess.start),
            end_time=time.fromisoformat(sess.end),
            capacity_model=sess.capacity_model,
            slot_minutes=sess.slot_minutes,
            capacity_mode=sess.capacity.mode,
            capacity_value=sess.capacity.value,
            walk_in_reserve_percent=sess.walk_in_reserve_percent,
            last_arrival_offset_minutes=sess.last_arrival_offset_minutes,
        )
        for sess in body.sessions
    ]
    session.add_all(rows)
    await session.flush()

    horizon = end + timedelta(days=settings.tenant_next_bookable_horizon_days)
    after = await schedule.load(session, settings, now, [resource_id], start, horizon)
    await impact.apply(
        session, settings, resource, schedule.daterange(max(body.effective_from, start), end),
        before=lambda d: before.sessions(resource_id, d, channel="DESK"),
        after=lambda d: after.sessions(resource_id, d, channel="DESK"),
        suggest=after,
        exception_id=None,
        template_change=True,
        actor=actor,
    )
    await session.commit()
    return _template_model(template, rows)
