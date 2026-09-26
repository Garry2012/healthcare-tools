"""Templates, exceptions, the live board, and the impacted-customer loop.

Creating an exception (or a template) that removes or shortens a session moves the
bookings that no longer fit to NEEDS_RESCHEDULE and creates one notification per
booking carrying structured facts. Withdrawing the exception restores them.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import schemas as s
from ..config import Settings
from ..db import tables as t
from ..domain import ids
from ..domain.availability import CANCELLED_STATUS, SessionView, find_session
from ..errors import ApiError, not_found, validation
from . import schedule, views
from .bookings import context_for, get, history_of, new_id, staff_view

MAX_EXCEPTION_DAYS = 366
IMPACTABLE = ("BOOKED", "CONFIRMED_BY_DESK", "RESCHEDULED")
Sessions = Callable[[date], list[SessionView]]


def _t(value: str | None) -> time | None:
    return time.fromisoformat(value) if value else None


# ---------------------------------------------------------------- templates


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


async def _require_resource(session: AsyncSession, resource_id: str) -> t.Resource:
    resource = await session.get(t.Resource, resource_id)
    if resource is None:
        raise not_found("No such resource.")
    return resource


async def get_template(session: AsyncSession, settings: Settings, resource_id: str) -> s.ScheduleTemplate:
    await _require_resource(session, resource_id)
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


async def set_template(
    session: AsyncSession, settings: Settings, resource_id: str, body: s.ScheduleTemplate, actor: str
) -> s.ScheduleTemplate:
    resource = await _require_resource(session, resource_id)
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
            ordinal=i + 1,
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
        for i, sess in enumerate(body.sessions)
    ]
    session.add_all(rows)
    await session.flush()

    horizon = end + timedelta(days=settings.tenant_next_bookable_horizon_days)
    after = await schedule.load(session, settings, now, [resource_id], start, horizon)
    await _impact(
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


# ---------------------------------------------------------------- impact


def _session_facts(view: SessionView | None) -> dict[str, Any] | None:
    if view is None:
        return None
    return {
        "sessionId": view.session_id,
        "date": view.date.isoformat(),
        "label": view.label,
        "start": views.clock(view.start),
        "end": views.clock(view.end),
        "status": view.status,
    }


def _suggestions(data: schedule.ScheduleData, resource_id: str, after_date: date, limit: int = 3) -> list[dict]:
    out: list[dict] = []
    first = max(after_date, data.now.date())
    for day in schedule.daterange(first, first + timedelta(days=data.settings.tenant_next_bookable_horizon_days)):
        for view in data.sessions(resource_id, day):
            for slot in view.available_slots():
                out.append({
                    "slotId": slot.slot_id,
                    "date": day.isoformat(),
                    "sessionStart": views.clock(view.start),
                    "sessionEnd": views.clock(view.end),
                    "expectedFrom": views.clock(slot.window_from or slot.start),
                })
                break
            if len(out) >= limit:
                return out
    return out


async def _impact(
    session: AsyncSession,
    settings: Settings,
    resource: t.Resource,
    dates: list[date],
    *,
    before: Sessions,
    after: Sessions,
    suggest: schedule.ScheduleData,
    exception_id: str | None,
    template_change: bool,
    actor: str,
) -> tuple[int, int]:
    if not dates:
        return 0, 0
    bookings = (
        await session.scalars(
            select(t.Booking)
            .where(
                t.Booking.resource_id == resource.id,
                t.Booking.date >= dates[0],
                t.Booking.date <= dates[-1],
                t.Booking.status.in_(IMPACTABLE),
            )
            .with_for_update()
        )
    ).all()
    moved_to_reschedule = notified = 0
    cache_before: dict[date, list[SessionView]] = {}
    cache_after: dict[date, list[SessionView]] = {}
    for booking in bookings:
        was = find_session(cache_before.setdefault(booking.date, before(booking.date)), booking.session_id)
        now_view = find_session(cache_after.setdefault(booking.date, after(booking.date)), booking.session_id)
        removed = now_view is None or now_view.status == CANCELLED_STATUS
        gone = removed or booking.slot_id not in now_view.offered_slot_ids
        moved = not gone and was is not None and (was.start, was.end) != (now_view.start, now_view.end)
        if not gone and not moved:
            continue
        if template_change:
            trigger = "TEMPLATE_CHANGED"
        else:
            trigger = "SESSION_CANCELLED" if removed else "SESSION_TIME_CHANGED"
        if gone:
            previous = booking.status
            booking.status = "NEEDS_RESCHEDULE"
            booking.impacted_by_exception_id = exception_id
            session.add(t.BookingHistory(
                booking_id=booking.id, by=actor, change="NEEDS_RESCHEDULE",
                details={"previous": previous, "exceptionId": exception_id, "trigger": trigger},
            ))
            moved_to_reschedule += 1
        session.add(t.Notification(
            id=new_id("ntf"),
            booking_id=booking.id,
            exception_id=exception_id,
            trigger=trigger,
            status="PENDING",
            customer_phone=booking.phone,
            customer_language=booking.language,
            facts={
                "resourceId": resource.id,
                "resourceName": resource.name,
                "bookingDate": booking.date.isoformat(),
                "slotId": booking.slot_id,
                "bookingStatus": booking.status,
                "previousSession": _session_facts(was),
                "currentSession": None if removed else _session_facts(now_view),
                "suggestedSlots": _suggestions(suggest, resource.id, booking.date) if gone else [],
            },
        ))
        notified += 1
    await session.flush()
    return moved_to_reschedule, notified


# ---------------------------------------------------------------- exceptions


def _exception_model(row: t.ScheduleException, *, staff: bool) -> s.ScheduleException:
    return s.ScheduleException(
        id=row.id,
        resource_id=row.resource_id,
        date_from=row.date_from,
        date_to=row.date_to,
        scope=row.scope,
        template_session_id=row.template_session_id,
        effect=row.effect,
        new_start=views.clock(row.new_start),
        new_end=views.clock(row.new_end),
        new_capacity=row.new_capacity,
        # Internal fields; never shown to a non-staff credential.
        reason_category=row.reason_category if staff else None,
        note=row.note if staff else None,
        created_at=row.created_at,
        created_by=row.created_by if staff else "staff",
        impact=s.ExceptionImpact(
            bookings_impacted=row.impact_bookings,
            notifications_created=row.impact_notifications,
        ),
    )


async def list_exceptions(
    session: AsyncSession, *, resource_id: str | None, date_from: date | None, date_to: date | None,
    staff: bool,
) -> s.ExceptionList:
    query = select(t.ScheduleException).where(t.ScheduleException.deleted_at.is_(None))
    if resource_id:
        query = query.where(t.ScheduleException.resource_id == resource_id)
    if date_from:
        query = query.where(t.ScheduleException.date_to >= date_from)
    if date_to:
        query = query.where(t.ScheduleException.date_from <= date_to)
    rows = await session.scalars(query.order_by(t.ScheduleException.seq))
    return s.ExceptionList(items=[_exception_model(r, staff=staff) for r in rows])


async def _template_session_ids(session: AsyncSession, resource_id: str) -> set[str]:
    rows = await session.scalars(
        select(t.TemplateSession.template_session_id)
        .join(t.ScheduleTemplate, t.ScheduleTemplate.id == t.TemplateSession.template_id)
        .where(t.ScheduleTemplate.resource_id == resource_id)
    )
    return set(rows.all())


async def _validate_exception(session: AsyncSession, body: s.ScheduleExceptionInput) -> None:
    if body.date_to < body.date_from:
        raise validation("dateTo must not be before dateFrom.", "dateTo")
    if (body.date_to - body.date_from).days >= MAX_EXCEPTION_DAYS:
        raise validation("An exception may span at most a year.", "dateTo")
    start, end = _t(body.new_start), _t(body.new_end)
    if (start is None) != (end is None):
        raise validation("newStart and newEnd go together.", "newEnd")
    if start and end and end <= start:
        raise validation("newEnd must be after newStart.", "newEnd")
    if body.scope == "SESSION":
        if not body.template_session_id:
            raise validation("SESSION scope needs templateSessionId.", "templateSessionId")
        if body.template_session_id not in await _template_session_ids(session, body.resource_id):
            raise validation("templateSessionId is not in this resource's template.", "templateSessionId")
    if body.scope == "TIME_RANGE" and start is None:
        raise validation("TIME_RANGE scope needs newStart and newEnd.", "newStart")
    if body.effect == "TIME_CHANGE" and (body.scope != "SESSION" or start is None):
        raise validation("TIME_CHANGE needs SESSION scope with newStart and newEnd.", "effect")
    if body.effect == "CAPACITY_CHANGE" and body.new_capacity is None:
        raise validation("CAPACITY_CHANGE needs newCapacity.", "newCapacity")
    if body.effect == "EXTRA_SESSION" and start is None:
        raise validation("EXTRA_SESSION needs newStart and newEnd.", "newStart")


def _insert_exception(session: AsyncSession, body: s.ScheduleExceptionInput, actor: str) -> t.ScheduleException:
    row = t.ScheduleException(
        id=new_id("exc"),
        resource_id=body.resource_id,
        date_from=body.date_from,
        date_to=body.date_to,
        scope=body.scope,
        template_session_id=body.template_session_id,
        effect=body.effect,
        new_start=_t(body.new_start),
        new_end=_t(body.new_end),
        new_capacity=body.new_capacity,
        reason_category=body.reason_category,
        note=body.note,
        created_by=actor,
    )
    session.add(row)
    return row


async def create_exception(
    session: AsyncSession, settings: Settings, body: s.ScheduleExceptionInput, actor: str
) -> s.ScheduleException:
    """Does not commit; the caller's idempotency wrapper does."""
    resource = await _require_resource(session, body.resource_id)
    await schedule.lock_resource(session, resource.id, exclusive=True)
    now = schedule.now_in(settings)
    if body.date_from < now.date():
        # A past exception would move customers who have already been seen and phone them about it.
        raise validation("An exception cannot start before today.", "dateFrom")
    await _validate_exception(session, body)
    horizon = body.date_to + timedelta(days=settings.tenant_next_bookable_horizon_days)
    before = await schedule.load(session, settings, now, [resource.id], body.date_from, horizon)
    dates = schedule.daterange(body.date_from, body.date_to)

    if body.effect == "EXTRA_SESSION":
        start, end = _t(body.new_start), _t(body.new_end)
        for day in dates:
            for view in before.sessions(resource.id, day, channel="DESK"):
                if view.status != CANCELLED_STATUS and view.start < end and start < view.end:
                    raise ApiError("CONFLICT", f"The extra session overlaps an existing session on {day}.")

    row = _insert_exception(session, body, actor)
    await session.flush()
    after = await schedule.load(session, settings, now, [resource.id], body.date_from, horizon)
    impacted, notified = await _impact(
        session, settings, resource, dates,
        before=lambda d: before.sessions(resource.id, d, channel="DESK"),
        after=lambda d: after.sessions(resource.id, d, channel="DESK"),
        suggest=after,
        exception_id=row.id,
        template_change=False,
        actor=actor,
    )
    row.impact_bookings, row.impact_notifications = impacted, notified
    await session.flush()
    await session.refresh(row)
    return _exception_model(row, staff=True)


async def delete_exception(
    session: AsyncSession, settings: Settings, exception_id: str, actor: str
) -> None:
    row = await session.scalar(
        select(t.ScheduleException).where(
            t.ScheduleException.id == exception_id, t.ScheduleException.deleted_at.is_(None)
        ).with_for_update()
    )
    if row is None:
        raise not_found("No such exception.")
    await schedule.lock_resource(session, row.resource_id, exclusive=True)
    now = schedule.now_in(settings)
    horizon = row.date_to + timedelta(days=settings.tenant_next_bookable_horizon_days)
    with_exception = await schedule.load(session, settings, now, [row.resource_id], row.date_from, horizon)
    row.deleted_at, row.deleted_by = now, actor
    await session.flush()

    notices = (
        await session.scalars(select(t.Notification).where(t.Notification.exception_id == exception_id))
    ).all()
    bkg_ids = sorted({n.booking_id for n in notices})
    bookings = {
        a.id: a
        for a in (
            await session.scalars(
                select(t.Booking).where(t.Booking.id.in_(bkg_ids)).with_for_update()
            )
        ).all()
    } if bkg_ids else {}
    resource = await session.get(t.Resource, row.resource_id)
    dates = [a.date for a in bookings.values()] or [row.date_from]
    data = await schedule.load(session, settings, now, [row.resource_id], min(dates), max(dates))

    previous = await _status_before(session, list(bookings), exception_id)
    restored: dict[str, bool] = {}
    for booking in bookings.values():
        if booking.status != "NEEDS_RESCHEDULE" or booking.impacted_by_exception_id != exception_id:
            continue
        view = find_session(data.sessions(booking.resource_id, booking.date, channel="DESK"), booking.session_id)
        ok = view is not None and view.status != CANCELLED_STATUS and booking.slot_id in view.offered_slot_ids
        if ok:
            try:
                async with session.begin_nested():
                    # Back to what it was (e.g. CONFIRMED_BY_DESK), not a blanket BOOKED.
                    booking.status = previous.get(booking.id, "BOOKED")
                    booking.impacted_by_exception_id = None
                    await session.flush()
            except IntegrityError:
                await session.refresh(booking)
                ok = False
        restored[booking.id] = ok
        session.add(t.BookingHistory(
            booking_id=booking.id, by=actor, change="RESTORED" if ok else "STILL_NEEDS_RESCHEDULE",
            details={"exceptionId": exception_id},
        ))

    told: set[str] = set()
    for notice in notices:
        if notice.status == "PENDING":
            # The customer was never told; there is nothing to take back.
            await session.delete(notice)
        else:
            told.add(notice.booking_id)
    for bkg_id, booking in bookings.items():
        still_needs = booking.status == "NEEDS_RESCHEDULE" and not restored.get(bkg_id, True)
        if bkg_id in told or still_needs:
            session.add(t.Notification(
                id=new_id("ntf"),
                booking_id=bkg_id,
                exception_id=exception_id,
                trigger="DESK_MESSAGE",
                status="PENDING",
                customer_phone=booking.phone,
                customer_language=booking.language,
                facts={
                    "resourceId": booking.resource_id,
                    "resourceName": resource.name if resource else None,
                    "bookingDate": booking.date.isoformat(),
                    "slotId": booking.slot_id,
                    "change": "SLOT_NO_LONGER_AVAILABLE" if still_needs else "SESSION_RESTORED",
                    "bookingStatus": booking.status,
                },
            ))
    await session.flush()

    # Bookings that existed only because of the exception (an extra session, added capacity, a
    # moved time) lose their session when it is withdrawn: they are impacted like any removal.
    resource_row = resource or await _require_resource(session, row.resource_id)
    today = now.date()
    dates = [d for d in schedule.daterange(max(row.date_from, today), row.date_to)] if row.date_to >= today else []
    after = await schedule.load(session, settings, now, [row.resource_id], row.date_from, horizon)
    await _impact(
        session, settings, resource_row, dates,
        before=lambda d: with_exception.sessions(row.resource_id, d, channel="DESK"),
        after=lambda d: after.sessions(row.resource_id, d, channel="DESK"),
        suggest=after,
        exception_id=exception_id,
        template_change=False,
        actor=actor,
    )
    await session.commit()


async def _status_before(session: AsyncSession, booking_ids: list[str], exception_id: str) -> dict[str, str]:
    """The live status each booking had before this exception moved it to NEEDS_RESCHEDULE."""
    if not booking_ids:
        return {}
    rows = await session.execute(
        select(t.BookingHistory.booking_id, t.BookingHistory.details)
        .where(t.BookingHistory.booking_id.in_(booking_ids), t.BookingHistory.change == "NEEDS_RESCHEDULE")
        .order_by(t.BookingHistory.id)
    )
    found: dict[str, str] = {}
    for booking_id, details in rows:
        if (details or {}).get("exceptionId") == exception_id and (details or {}).get("previous") in IMPACTABLE:
            found[booking_id] = details["previous"]
    return found


async def impact_of(session: AsyncSession, settings: Settings, exception_id: str) -> s.ImpactList:
    exists = await session.scalar(select(t.ScheduleException.id).where(t.ScheduleException.id == exception_id))
    if exists is None:
        raise not_found("No such exception.")
    notices = (
        await session.scalars(
            select(t.Notification)
            .where(t.Notification.exception_id == exception_id)
            .order_by(t.Notification.created_at)
        )
    ).all()
    bookings = {
        a.id: a for a in (
            await session.scalars(
                select(t.Booking).where(t.Booking.id.in_([n.booking_id for n in notices]))
            )
        ).all()
    } if notices else {}
    ctx = await context_for(session, settings, list(bookings.values()))
    history = await history_of(session, list(bookings))
    return s.ImpactList(
        exception_id=exception_id,
        items=[
            s.ImpactedBooking(
                booking=staff_view(bookings[n.booking_id], ctx, history[n.booking_id]),
                notification=notification_model(n),
            )
            for n in notices if n.booking_id in bookings
        ],
    )


# ---------------------------------------------------------------- board


def _board_model(row: t.BoardEntry, *, staff: bool) -> s.BoardEntry:
    return s.BoardEntry(
        date=row.date,
        session_id=row.session_id,
        presence=row.presence,
        expected_start=views.clock(row.expected_start),
        delay_minutes=row.delay_minutes,
        session_ended=row.session_ended,
        capacity_state=row.capacity_state,
        tokens_issued=row.tokens_issued,
        last_arrival_time=views.clock(row.last_arrival_time),
        timing_confirmed=row.timing_confirmed,
        updated_at=row.updated_at,
        updated_by=row.updated_by if staff else "staff",
    )


async def get_board(
    session: AsyncSession, settings: Settings, resource_id: str, on: date | None, *, staff: bool
) -> s.BoardView:
    await _require_resource(session, resource_id)
    day = on or schedule.now_in(settings).date()
    rows = await session.scalars(
        select(t.BoardEntry)
        .where(t.BoardEntry.resource_id == resource_id, t.BoardEntry.date == day)
        .order_by(t.BoardEntry.session_id)
    )
    return s.BoardView(resource_id=resource_id, date=day, sessions=[_board_model(r, staff=staff) for r in rows])


async def set_board(
    session: AsyncSession, settings: Settings, resource_id: str, body: s.BoardEntryInput, actor: str
) -> s.BoardEntry:
    await _require_resource(session, resource_id)
    now = schedule.now_in(settings)
    if body.date != now.date():
        raise validation("The live board is for today only; use a schedule exception for other dates.", "date")
    ref = ids.parse_session_id(body.session_id)
    if ref is None or ref.resource_id != resource_id or ref.date != body.date:
        raise validation("sessionId does not belong to this resource and date.", "sessionId")
    data = await schedule.load(session, settings, now, [resource_id], body.date, body.date)
    if find_session(data.sessions(resource_id, body.date, channel="DESK"), body.session_id) is None:
        raise not_found("No such session today.")

    row = await session.get(t.BoardEntry, body.session_id, with_for_update=True)
    if row is None:
        row = t.BoardEntry(session_id=body.session_id, resource_id=resource_id, date=body.date, updated_by=actor)
        session.add(row)
    fields = body.model_dump(exclude_unset=True, exclude={"date", "session_id"})
    for name, value in fields.items():
        if name in ("expected_start", "last_arrival_time"):
            value = _t(value)
        elif hasattr(value, "value"):
            value = value.value
        setattr(row, name, value)
    row.updated_at = datetime.now(settings.tz)
    row.updated_by = actor
    await session.commit()
    await session.refresh(row)
    return _board_model(row, staff=True)


# ---------------------------------------------------------------- confirmation


async def confirm_booking(
    session: AsyncSession, settings: Settings, booking_id: str, body: s.ConfirmRequest, actor: str
) -> t.Booking:
    row = await get(session, booking_id, lock=True)
    if row.status not in ("BOOKED", "RESCHEDULED", "CONFIRMED_BY_DESK"):
        raise ApiError("CONFLICT", f"A {row.status} booking cannot be confirmed.")
    row.status = "CONFIRMED_BY_DESK"
    row.timing_confirmed = True
    row.confirmed_start = _t(body.confirmed_start)
    session.add(t.BookingHistory(
        booking_id=row.id, by=actor, change="CONFIRMED_BY_DESK",
        details={"confirmedStart": body.confirmed_start, "applyToSession": body.apply_to_session},
    ))
    if body.apply_to_session:
        now = schedule.now_in(settings)
        data = await schedule.load(session, settings, now, [row.resource_id], row.date, row.date)
        view = find_session(data.sessions(row.resource_id, row.date, channel="DESK"), row.session_id)
        if view is not None:
            scope = "SESSION" if view.template_session_id else "TIME_RANGE"
            _insert_exception(session, s.ScheduleExceptionInput(
                resource_id=row.resource_id,
                date_from=row.date,
                date_to=row.date,
                scope=scope,
                template_session_id=view.template_session_id,
                effect="TIMING_CONFIRMED",
                new_start=None if view.template_session_id else views.clock(view.start),
                new_end=None if view.template_session_id else views.clock(view.end),
                reason_category="OTHER",
            ), actor)
    await session.commit()
    await session.refresh(row)
    return row


# ---------------------------------------------------------------- notifications


def notification_model(row: t.Notification) -> s.Notification:
    return s.Notification(
        id=row.id,
        booking_id=row.booking_id,
        trigger=row.trigger,
        status=row.status,
        channel=row.channel,
        customer_phone=row.customer_phone,
        customer_language=row.customer_language,
        facts=row.facts,
        created_at=row.created_at,
        delivered_at=row.delivered_at,
        outcome=row.outcome,
    )


async def list_notifications(
    session: AsyncSession, *, status: str, resource_id: str | None, on: date | None
) -> s.NotificationList:
    query = select(t.Notification).where(t.Notification.status == status)
    if resource_id or on:
        query = query.join(t.Booking, t.Booking.id == t.Notification.booking_id)
        if resource_id:
            query = query.where(t.Booking.resource_id == resource_id)
        if on:
            query = query.where(t.Booking.date == on)
    rows = await session.scalars(query.order_by(t.Notification.created_at))
    return s.NotificationList(items=[notification_model(r) for r in rows])


async def mark_delivered(
    session: AsyncSession, settings: Settings, notification_id: str, body: s.DeliveredRequest, actor: str
) -> s.Notification:
    row = await session.get(t.Notification, notification_id, with_for_update=True)
    if row is None:
        raise not_found("No such notification.")
    if body.outcome == "NO_ANSWER":
        row.status = "FAILED"
    elif body.outcome is None:
        row.status = "SENT"
    else:
        row.status = "ACKNOWLEDGED"
    row.channel = body.channel
    row.outcome = body.outcome
    row.note = body.note
    row.delivered_at = datetime.now(settings.tz)
    row.delivered_by = actor
    await session.commit()
    await session.refresh(row)
    return notification_model(row)


async def purge_board_before(session: AsyncSession, day: date) -> int:
    """Board facts expire at day end; the engine already ignores old rows."""
    result = await session.execute(delete(t.BoardEntry).where(t.BoardEntry.date < day))
    await session.commit()
    return result.rowcount or 0
