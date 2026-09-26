"""Desk actions on bookings: search, status changes, timing confirmation."""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import schemas as s
from ..config import Settings
from ..db import tables as t
from ..domain import booking_status
from ..domain.availability import find_session
from ..errors import ApiError, not_found
from . import schedule, schedule_exceptions, views
from .bookings import add_history


async def confirm_booking(
    session: AsyncSession, settings: Settings, booking_id: str, body: s.ConfirmRequest, actor: str
) -> t.Booking:
    row = await get(session, booking_id, lock=True)
    if row.status not in booking_status.BEFORE_VISIT:
        raise ApiError("CONFLICT", f"A {row.status} booking cannot be confirmed.")
    row.status = "CONFIRMED_BY_DESK"
    row.timing_confirmed = True
    row.confirmed_start = views.time_of(body.confirmed_start)
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
            schedule_exceptions.insert_exception(session, s.ScheduleExceptionInput(
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


async def search(
    session: AsyncSession, *, resource_id: str | None, session_id: str | None, on: date | None,
    phone: str | None, status: str | None, limit: int, offset: int,
) -> tuple[list[t.Booking], int]:
    query = select(t.Booking)
    if resource_id:
        query = query.where(t.Booking.resource_id == resource_id)
    if session_id:
        query = query.where(t.Booking.session_id == session_id)
    if on:
        query = query.where(t.Booking.date == on)
    if phone:
        query = query.where(t.Booking.phone == phone)
    if status:
        query = query.where(t.Booking.status == status)
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (
        await session.scalars(
            query.order_by(t.Booking.date, t.Booking.slot_id).limit(limit).offset(offset)
        )
    ).all()
    return list(rows), total


async def get(session: AsyncSession, booking_id: str, *, lock: bool = False) -> t.Booking:
    row = await session.get(t.Booking, booking_id, with_for_update=lock)
    if row is None:
        raise not_found("No such booking.")
    return row


async def set_status(
    session: AsyncSession, settings: Settings, booking_id: str, body: s.StatusRequest, actor: str
) -> t.Booking:
    row = await get(session, booking_id, lock=True)
    if row.status not in booking_status.STAFF_TRANSITIONS[body.status]:
        raise ApiError("CONFLICT", f"Cannot move a booking from {row.status} to {body.status}.")
    today = schedule.now_in(settings).date()
    if body.status == "ARRIVED" and row.date != today:
        raise ApiError("CONFLICT", "A customer can only arrive on the day of the booking.")
    if body.status in ("COMPLETED", "NO_SHOW") and row.date > today:
        raise ApiError("CONFLICT", f"A booking on {row.date} cannot be {body.status} yet.")
    previous = row.status
    row.status = body.status
    add_history(session, row.id, actor, body.status, previous=previous, note=body.note)
    await session.flush()
    return row
