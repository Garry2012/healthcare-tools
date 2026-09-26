"""The desk's notification work-list: what customers must be told, and what they were told."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import schemas as s
from ..config import Settings
from ..db import tables as t
from ..errors import ApiError, not_found


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
    if row.status == "ACKNOWLEDGED":
        # The customer's answer is on record; a later attempt must not overwrite or erase it.
        raise ApiError("CONFLICT", "This notification was already acknowledged by the customer.")
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
