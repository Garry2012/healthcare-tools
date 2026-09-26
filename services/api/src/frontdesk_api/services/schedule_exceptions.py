"""Known deviations from a template (leave, surgery, extra sessions, capacity changes), their
impact on bookings, and withdrawing them again."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import schemas as s
from ..config import Settings
from ..db import tables as t
from ..domain import booking_status, ids
from ..domain.availability import CANCELLED_STATUS, find_session
from ..domain.intervals import overlaps
from ..errors import ApiError, not_found, validation
from . import directory, impact, schedule, views
from .booking_views import context_for, history_of, staff_view
from .notifications import notification_model

MAX_EXCEPTION_DAYS = 366


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
    start, end = views.time_of(body.new_start), views.time_of(body.new_end)
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


def insert_exception(session: AsyncSession, body: s.ScheduleExceptionInput, actor: str) -> t.ScheduleException:
    """Record an exception row only; the caller decides whether bookings are impacted."""
    row = t.ScheduleException(
        id=ids.new_id("exc"),
        resource_id=body.resource_id,
        date_from=body.date_from,
        date_to=body.date_to,
        scope=body.scope,
        template_session_id=body.template_session_id,
        effect=body.effect,
        new_start=views.time_of(body.new_start),
        new_end=views.time_of(body.new_end),
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
    resource = await directory.require_resource(session, body.resource_id)
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
        start, end = views.time_of(body.new_start), views.time_of(body.new_end)
        for day in dates:
            for view in before.sessions(resource.id, day, channel="DESK"):
                if view.status != CANCELLED_STATUS and overlaps(view.start, view.end, start, end):
                    raise ApiError("CONFLICT", f"The extra session overlaps an existing session on {day}.")

    row = insert_exception(session, body, actor)
    await session.flush()
    after = await schedule.load(session, settings, now, [resource.id], body.date_from, horizon)
    impacted, notified = await impact.apply(
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

    told: dict[str, t.Notification] = {}
    for notice in notices:
        if notice.status == "PENDING":
            # The customer was never told; there is nothing to take back.
            await session.delete(notice)
        else:
            told[notice.booking_id] = notice
    for bkg_id, booking in bookings.items():
        still_needs = booking.status == "NEEDS_RESCHEDULE" and not restored.get(bkg_id, True)
        if still_needs or (bkg_id in told and _changes_back(booking, told[bkg_id])):
            session.add(t.Notification(
                id=ids.new_id("ntf"),
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
    resource_row = resource or await directory.require_resource(session, row.resource_id)
    today = now.date()
    dates = [d for d in schedule.daterange(max(row.date_from, today), row.date_to)] if row.date_to >= today else []
    after = await schedule.load(session, settings, now, [row.resource_id], row.date_from, horizon)
    await impact.apply(
        session, settings, resource_row, dates,
        before=lambda d: with_exception.sessions(row.resource_id, d, channel="DESK"),
        after=lambda d: after.sessions(row.resource_id, d, channel="DESK"),
        suggest=after,
        exception_id=exception_id,
        template_change=False,
        actor=actor,
    )
    await session.commit()


def _changes_back(booking: t.Booking, told: t.Notification) -> bool:
    """Withdrawing the exception changes something for this customer only if they still hold the
    slot they were told about. Not if they moved or cancelled since, and not if a shorter queue
    moved them forward: that position stays theirs."""
    facts = told.facts or {}
    return (booking.status in booking_status.HOLDS_SLOT and booking.slot_id == facts.get("slotId")
            and "previousSlotId" not in facts)


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
        details = details or {}
        if details.get("exceptionId") == exception_id and details.get("previous") in booking_status.BEFORE_VISIT:
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
