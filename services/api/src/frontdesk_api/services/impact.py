"""What a schedule change does to existing bookings: move them forward in a shorter queue,
or to NEEDS_RESCHEDULE with a notification carrying structured facts for the desk."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..db import tables as t
from ..domain import booking_status, ids
from ..domain.availability import CANCELLED_STATUS, SessionView, find_session
from . import schedule, views

Sessions = Callable[[date], list[SessionView]]


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


async def apply(
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
                t.Booking.status.in_(booking_status.BEFORE_VISIT),
            )
            .with_for_update()
        )
    ).all()
    # Earliest in the queue first, so a capacity cut keeps the people who booked first.
    bookings = sorted(bookings, key=lambda b: (b.date, b.session_id, _position(b.slot_id)))
    held = set(
        (
            await session.scalars(
                select(t.Booking.slot_id).where(
                    t.Booking.resource_id == resource.id,
                    t.Booking.date >= dates[0],
                    t.Booking.date <= dates[-1],
                    t.Booking.status.in_(booking_status.HOLDS_SLOT),
                )
            )
        ).all()
    )
    now = schedule.now_in(settings)
    moved_to_reschedule = notified = 0
    cache_before: dict[date, list[SessionView]] = {}
    cache_after: dict[date, list[SessionView]] = {}
    for booking in bookings:
        was = find_session(cache_before.setdefault(booking.date, before(booking.date)), booking.session_id)
        now_view = find_session(cache_after.setdefault(booking.date, after(booking.date)), booking.session_id)
        removed = now_view is None or now_view.status == CANCELLED_STATUS
        gone = removed or booking.slot_id not in now_view.offered_slot_ids
        previous_slot: str | None = None
        if gone and not removed and now_view.capacity_model == "SEQUENCE":
            # The queue got shorter but has free places: move forward instead of bumping.
            free = _free_position(now_view, held, now, timedelta(minutes=settings.tenant_move_lead_minutes))
            if free is not None:
                previous_slot, previous_status = booking.slot_id, booking.status
                booking.slot_id = free
                # A time the desk confirmed was for the old position.
                booking.timing_confirmed, booking.confirmed_start = False, None
                if booking.status == "CONFIRMED_BY_DESK":
                    booking.status = "BOOKED"
                held.add(free)
                held.discard(previous_slot)
                session.add(t.BookingHistory(
                    booking_id=booking.id, by=actor, change="SLOT_MOVED",
                    details={"previousSlotId": previous_slot, "slotId": free, "exceptionId": exception_id,
                             "previous": previous_status},
                ))
                gone = False
        moved = not gone and was is not None and (
            previous_slot is not None or (was.start, was.end) != (now_view.start, now_view.end)
        )
        if not gone and not moved:
            continue
        # The session keeps its hours: only its size changed, so no one is told "the time changed".
        same_hours = not removed and was is not None and (was.start, was.end) == (now_view.start, now_view.end)
        smaller = same_hours and now_view.total < was.total
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
            id=ids.new_id("ntf"),
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
                **({"previousSlotId": previous_slot} if previous_slot else {}),
                **({"reason": "CAPACITY_REDUCED"} if smaller else {}),
            },
        ))
        notified += 1
    await session.flush()
    return moved_to_reschedule, notified


def _position(slot_id: str) -> int:
    ref = ids.parse_slot_id(slot_id)
    return int(ref.suffix) if ref else 0


_STILL_ADMITS = (None, "FULL", "DESK_ONLY")  # FULL: the cut itself over-fills the session


def _free_position(view: SessionView, held: set[str], now: datetime, lead: timedelta) -> str | None:
    """The first queue position in `view` nobody holds and the caller can still reach."""
    if view.not_bookable_reason not in _STILL_ADMITS:
        return None  # ended, doctor left, arrive-by passed, not offered
    # Today, a position is only worth moving someone to if they can still get there.
    reachable_from = (now + lead).time() if view.date == now.date() else None
    for slot in view.slots:
        if slot.slot_id in held:
            continue
        if reachable_from is not None and slot.window_to is not None and slot.window_to < reachable_from:
            continue
        return slot.slot_id
    return None


async def withdraw_resource(session: AsyncSession, settings: Settings, resource: t.Resource, actor: str) -> int:
    """The resource no longer offers anything (left, deactivated, NOT_OFFERED): every future live
    booking is impacted like a cancelled session, so the desk phones each customer. No commit."""
    await schedule.lock_resource(session, resource.id, exclusive=True)
    now = schedule.now_in(settings)
    last = await session.scalar(
        select(t.Booking.date).where(t.Booking.resource_id == resource.id, t.Booking.date >= now.date(),
                                     t.Booking.status.in_(booking_status.BEFORE_VISIT)).order_by(t.Booking.date.desc()).limit(1))
    if last is None:
        return 0
    before = await schedule.load(session, settings, now, [resource.id], now.date(), last)
    impacted, _ = await apply(
        session, settings, resource, schedule.daterange(now.date(), last),
        before=lambda d: before.sessions(resource.id, d, channel="DESK"),
        after=lambda d: [],
        suggest=before,
        exception_id=None,
        template_change=False,
        actor=actor,
    )
    return impacted
