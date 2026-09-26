"""Booking, lookup, cancel, reschedule — agent and desk paths.

Slot uniqueness is enforced by the partial unique index `uq_bookings_live_slot`:
booking is `INSERT … ON CONFLICT DO NOTHING`, rescheduling is an UPDATE inside a savepoint.
The availability check before the write is for a good error message, not for safety.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import date, time, timedelta

from sqlalchemy import func, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import schemas as s
from ..config import Settings
from ..db import tables as t
from ..domain import ids
from ..domain.availability import SessionView, SlotView, find_session
from ..domain.identity import (
    BookingIdentity,
    customers_on,
    name_matches,
    national_number,
    number_matches,
)
from ..domain.text import normalise_person_name
from ..errors import ApiError, not_found, validation
from . import schedule, views

LISTED_STATUSES = ("BOOKED", "CONFIRMED_BY_DESK", "RESCHEDULED", "NEEDS_RESCHEDULE", "ARRIVED")
CHANGEABLE_STATUSES = ("BOOKED", "CONFIRMED_BY_DESK", "RESCHEDULED", "NEEDS_RESCHEDULE")
_LIVE_WHERE = text(t.LIVE_SQL)


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


def _code() -> str:
    return f"{secrets.randbelow(10_000):04d}"


def _identity(row: t.Booking) -> BookingIdentity:
    return BookingIdentity(row.id, row.customer_name, row.phone, row.caller_number)


def _history(session: AsyncSession, booking_id: str, by: str, change: str, **details) -> None:
    session.add(t.BookingHistory(booking_id=booking_id, by=by, change=change, details=details))


# ---------------------------------------------------------------- views


def _slot_from_id(slot_id: str) -> SlotView:
    ref = ids.parse_slot_id(slot_id)
    suffix = ref.suffix if ref else ""
    # Positions are written with two or three digits, TIMED slots as HHMM.
    if len(suffix) == 4 and int(suffix[:2]) < 24 and int(suffix[2:]) < 60:
        at = time(int(suffix[:2]), int(suffix[2:]))
        return SlotView(slot_id=slot_id, kind="TIMED", available=False, start=at)
    return SlotView(slot_id=slot_id, kind="SEQUENCE", available=False,
                    position=int(suffix) if suffix.isdigit() else None)


def _slot_in(view: SessionView | None, slot_id: str) -> SlotView:
    if view is not None:
        for slot in view.slots:
            if slot.slot_id == slot_id:
                return slot
    return _slot_from_id(slot_id)


@dataclass(slots=True)
class Context:
    """Everything needed to describe bookings without further queries."""

    data: schedule.ScheduleData
    categories: dict[str, t.Category]

    def session_view(self, row: t.Booking) -> SessionView | None:
        if row.resource_id not in self.data.resources:
            return None
        return find_session(self.data.sessions(row.resource_id, row.date, channel="DESK"), row.session_id)


async def context_for(
    session: AsyncSession, settings: Settings, rows: list[t.Booking]
) -> Context:
    now = schedule.now_in(settings)
    if rows:
        first, last = min(r.date for r in rows), max(r.date for r in rows)
        first = min(first, now.date())
        last = max(last, now.date())
    else:
        first = last = now.date()
    data = await schedule.load(session, settings, now, {r.resource_id for r in rows}, first, last)
    categories = {d.id: d for d in (await session.scalars(select(t.Category))).all()}
    return Context(data, categories)


def _certainty(row: t.Booking, view: SessionView | None) -> str:
    if row.timing_confirmed:
        return "CONFIRMED"
    return view.timing_certainty if view else "EXPECTED"


def agent_view(
    row: t.Booking, ctx: Context, outcome: str, *, previous_slot: SlotView | None = None,
    with_today: bool = False,
) -> s.AgentBooking:
    view = ctx.session_view(row)
    resource = ctx.data.resources.get(row.resource_id)
    cat = ctx.categories.get(row.category_id or "")
    today = ctx.data.now.date()
    return s.AgentBooking(
        outcome=outcome,
        booking_id=row.id,
        confirmation_code=row.confirmation_code,
        status=row.status,
        customer=s.CustomerSummary(name=row.customer_name, phone=row.phone),
        resource=s.ResourceSummary(
            resource_id=row.resource_id,
            name=resource.name if resource else None,
            localized_names=(resource.localized_names or None) if resource else None,
        ),
        category=views.category(cat) if cat else None,
        date=row.date,
        session=s.SessionSummary(
            session_id=row.session_id,
            label=view.label if view else None,
            start=views.clock(view.start) if view else None,
            end=views.clock(view.end) if view else None,
        ),
        slot=views.slot(_slot_in(view, row.slot_id)),
        previous_slot=views.slot(previous_slot) if previous_slot else None,
        arrive_by=views.clock(view.arrive_by) if view else None,
        timing_certainty=_certainty(row, view),
        price=views.money(resource) if resource else None,
        follow_up=row.follow_up,
        resource_today=(
            views.session_instance(view, include_slots=False)
            if with_today and view is not None and row.date == today else None
        ),
    )


def staff_view(row: t.Booking, ctx: Context, history: list[t.BookingHistory]) -> s.Booking:
    view = ctx.session_view(row)
    return s.Booking(
        id=row.id,
        confirmation_code=row.confirmation_code,
        status=row.status,
        customer=s.BookingCustomer(
            name=row.customer_name, phone=row.phone, relation_to_caller=row.relation_to_caller
        ),
        caller_number=row.caller_number,
        resource_id=row.resource_id,
        session_id=row.session_id,
        slot_id=row.slot_id,
        date=row.date,
        slot=views.slot(_slot_in(view, row.slot_id)),
        arrive_by=views.clock(view.arrive_by) if view else None,
        timing_certainty=_certainty(row, view),
        confirmed_start=views.clock(row.confirmed_start),
        reason_verbatim=row.reason_verbatim,
        language=row.language,
        created_via=row.created_via,
        call_id=row.call_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        history=[s.HistoryItem(at=h.at, by=h.by, change=h.change) for h in history],
    )


async def history_of(session: AsyncSession, booking_ids: list[str]) -> dict[str, list[t.BookingHistory]]:
    out: dict[str, list[t.BookingHistory]] = {a: [] for a in booking_ids}
    if booking_ids:
        rows = await session.scalars(
            select(t.BookingHistory)
            .where(t.BookingHistory.booking_id.in_(booking_ids))
            .order_by(t.BookingHistory.id)
        )
        for h in rows:
            out[h.booking_id].append(h)
    return out


# ---------------------------------------------------------------- slot checks


@dataclass(slots=True)
class SlotCheck:
    ref: ids.SlotRef
    data: schedule.ScheduleData
    view: SessionView | None
    slot: SlotView | None


async def _check_slot(
    session: AsyncSession, settings: Settings, slot_id: str, channel: str
) -> SlotCheck:
    ref = ids.parse_slot_id(slot_id)
    if ref is None:
        raise validation("slotId is not a slot id returned by availability search.", "slotId")
    now = schedule.now_in(settings)
    data = await schedule.load(session, settings, now, [ref.session.resource_id], ref.session.date, ref.session.date)
    if ref.session.resource_id not in data.resources:
        return SlotCheck(ref, data, None, None)
    view = find_session(data.sessions(ref.session.resource_id, ref.session.date, channel=channel),
                        ref.session.session_id)
    slot = next((x for x in view.slots if x.slot_id == slot_id), None) if view else None
    return SlotCheck(ref, data, view, slot)


def _current_slots(view: SessionView | None) -> list[dict]:
    if view is None or not view.bookable:
        return []
    return [views.slot(x).model_dump(mode="json", by_alias=True, exclude_none=True)
            for x in view.available_slots()]


def _slot_unavailable(view: SessionView | None, message: str = "That slot is no longer available.") -> ApiError:
    return ApiError("SLOT_UNAVAILABLE", message, current_slots=_current_slots(view))


async def _recheck(session: AsyncSession, settings: Settings, slot_id: str, channel: str) -> ApiError:
    check = await _check_slot(session, settings, slot_id, channel)
    return _slot_unavailable(check.view)


# ---------------------------------------------------------------- booking


@dataclass(slots=True)
class Booked:
    row: t.Booking
    created: bool


async def book(
    session: AsyncSession,
    settings: Settings,
    body: s.AgentBookRequest,
    *,
    channel: str,
    call_id: str | None,
    caller_number: str | None,
    actor: str,
) -> Booked:
    if not re.fullmatch(settings.tenant_phone_pattern, body.customer.phone):
        raise validation("customer.phone does not match the facility's phone format.", "customer.phone")
    ref = ids.parse_slot_id(body.slot_id)
    if ref is not None:
        await schedule.lock_resource(session, ref.session.resource_id, exclusive=False)
        today = schedule.now_in(settings).date()
        if ref.session.date > today + timedelta(days=settings.tenant_booking_horizon_days):
            raise validation(f"Bookings open {settings.tenant_booking_horizon_days} days ahead.", "slotId")
    check = await _check_slot(session, settings, body.slot_id, channel)
    if check.view is None or check.slot is None:
        raise _slot_unavailable(check.view, "That slot does not exist in the current schedule.")

    name_key = normalise_person_name(body.customer.name)
    existing = await session.scalar(
        select(t.Booking).where(
            t.Booking.session_id == check.view.session_id,
            t.Booking.customer_name_normalized == name_key,
            t.Booking.phone == body.customer.phone,
            t.Booking.status.in_(t.LIVE_STATUSES),
        )
    )
    if existing is not None:
        # Only the number the booking belongs to (or the desk) may see it; to anyone else a name
        # and a phone are not proof of identity (CLAUDE.md: identity comes only from headers).
        own = channel != "AGENT" or number_matches(
            _identity(existing), caller_number=caller_number, spoken_phone=None,
            country_code=settings.tenant_country_calling_code)
        if not own:
            raise ApiError("CONFLICT", "This customer already has a booking in this session.")
        return Booked(existing, created=False)

    if not check.view.bookable or not check.slot.available:
        raise _slot_unavailable(check.view)

    resource = check.data.resources[check.ref.session.resource_id]
    category_id = await session.scalar(
        select(t.ResourceCategory.category_id)
        .where(t.ResourceCategory.resource_id == resource.id)
        .order_by(t.ResourceCategory.position)
        .limit(1)
    )
    follow_up = (
        "DESK_WILL_CONFIRM_TIMING"
        if body.request_timing_confirmation
        and settings.tenant_desk_follow_up_list_enabled
        and check.view.timing_certainty == "NOT_CONFIRMED"
        else "NONE"
    )
    booking_id = new_id("bkg")
    inserted = await session.scalar(
        insert(t.Booking)
        .values(
            id=booking_id,
            confirmation_code=_code(),
            status="BOOKED",
            customer_name=body.customer.name.strip(),
            customer_name_normalized=name_key,
            phone=body.customer.phone,
            relation_to_caller=body.customer.relation_to_caller,
            caller_number=caller_number,
            resource_id=resource.id,
            category_id=category_id,
            session_id=check.view.session_id,
            slot_id=body.slot_id,
            date=check.view.date,
            reason_verbatim=body.reason_verbatim,
            language=body.language,
            created_via="AGENT" if channel == "AGENT" else "DESK",
            call_id=call_id,
            follow_up=follow_up,
        )
        .on_conflict_do_nothing(index_elements=["slot_id"], index_where=_LIVE_WHERE)
        .returning(t.Booking.id)
    )
    if inserted is None:
        raise await _recheck(session, settings, body.slot_id, channel)
    _history(session, booking_id, actor, "BOOKED", slotId=body.slot_id)
    await session.flush()
    row = await session.get(t.Booking, booking_id)
    assert row is not None
    return Booked(row, created=True)


# ---------------------------------------------------------------- agent lookup / changes


async def agent_list(
    session: AsyncSession,
    settings: Settings,
    *,
    caller_number: str | None,
    customer_name: str | None,
    phone: str | None,
    date_from: date | None,
    date_to: date | None,
) -> s.AgentBookingList:
    if not caller_number and not phone:
        return s.AgentBookingList(
            outcome="IDENTITY_UNAVAILABLE", items=[], customers_on_number=0, identity_basis="NONE"
        )
    basis = "CALLER_NUMBER" if caller_number else "SPOKEN_NUMBER"
    if phone and not customer_name:
        # Anyone can say a number: without the name, disclose nothing (not even whether it has
        # bookings or how many customers use it).
        return s.AgentBookingList(outcome="NAME_REQUIRED", items=[], customers_on_number=0, identity_basis=basis)
    today = schedule.now_in(settings).date()
    numbers = []
    if caller_number:
        numbers.append(national_number(caller_number, settings.tenant_country_calling_code))
    if phone:
        numbers.append(phone)
    reachable = [t.Booking.phone.in_(numbers)]
    if caller_number:
        reachable.append(t.Booking.caller_number == caller_number)
    query = select(t.Booking).where(
        t.Booking.status.in_(LISTED_STATUSES),
        t.Booking.date >= (date_from or today),
        or_(*reachable),
    )
    if date_to:
        query = query.where(t.Booking.date <= date_to)
    rows = [
        r for r in (await session.scalars(query.order_by(t.Booking.date, t.Booking.slot_id))).all()
        if number_matches(_identity(r), caller_number=caller_number, spoken_phone=phone,
                          country_code=settings.tenant_country_calling_code)
    ]
    customers = customers_on(_identity(r) for r in rows)
    if customer_name:
        rows = [r for r in rows if name_matches(_identity(r), customer_name)]
    elif customers > 1:
        return s.AgentBookingList(
            outcome="NAME_REQUIRED", items=[], customers_on_number=customers, identity_basis=basis
        )
    ctx = await context_for(session, settings, rows)
    items = [agent_view(r, ctx, "FOUND", with_today=True) for r in rows]
    return s.AgentBookingList(
        outcome="FOUND" if items else "NONE_FOUND",
        items=items,
        customers_on_number=customers,
        identity_basis=basis,
    )


async def _locate(
    session: AsyncSession, settings: Settings, booking_id: str, customer_name: str,
    caller_number: str | None,
) -> t.Booking:
    """Neutral 404 for missing, not-yours and wrong-name alike."""
    row = await session.get(t.Booking, booking_id, with_for_update=True)
    if row is None or not caller_number:
        raise not_found()
    identity = _identity(row)
    if not number_matches(identity, caller_number=caller_number, spoken_phone=None,
                          country_code=settings.tenant_country_calling_code):
        raise not_found()
    if not name_matches(identity, customer_name):
        raise not_found()
    return row


async def cancel(
    session: AsyncSession, settings: Settings, booking_id: str, body: s.CancelRequest,
    *, caller_number: str | None, actor: str,
) -> t.Booking:
    row = await _locate(session, settings, booking_id, body.customer_name, caller_number)
    if row.status not in CHANGEABLE_STATUSES:
        raise ApiError("CONFLICT", "This booking can no longer be cancelled.")
    previous = row.status
    row.status = "CANCELLED_BY_CUSTOMER"
    _history(session, row.id, actor, "CANCELLED_BY_CUSTOMER", previous=previous,
             reasonProvided=bool(body.reason_verbatim))
    await session.flush()
    return row


async def _move(
    session: AsyncSession, settings: Settings, row: t.Booking, new_slot_id: str, *,
    channel: str, actor: str, status: str,
) -> SlotView:
    """Release the old slot and take the new one atomically, or change nothing."""
    if new_slot_id == row.slot_id:
        raise ApiError("CONFLICT", "The booking already holds that slot.")
    old_check = await _check_slot(session, settings, row.slot_id, "DESK")
    previous = _slot_in(old_check.view, row.slot_id)
    check = await _check_slot(session, settings, new_slot_id, channel)
    if check.view is None or check.slot is None or not check.view.bookable or not check.slot.available:
        raise _slot_unavailable(check.view)
    category_id = await session.scalar(
        select(t.ResourceCategory.category_id)
        .where(t.ResourceCategory.resource_id == check.ref.session.resource_id)
        .order_by(t.ResourceCategory.position)
        .limit(1)
    )
    old_slot = row.slot_id
    try:
        async with session.begin_nested():
            row.slot_id = new_slot_id
            row.session_id = check.view.session_id
            row.resource_id = check.ref.session.resource_id
            row.category_id = category_id
            row.date = check.view.date
            row.status = status
            row.timing_confirmed = False
            row.confirmed_start = None
            row.follow_up = "NONE"
            row.impacted_by_exception_id = None
            await session.flush()
    except IntegrityError:
        # The savepoint rolled back; the booking still holds its original slot.
        await session.refresh(row)
        raise await _recheck(session, settings, new_slot_id, channel) from None
    _history(session, row.id, actor, "RESCHEDULED", fromSlot=old_slot, toSlot=new_slot_id)
    await session.flush()
    return previous


async def reschedule(
    session: AsyncSession, settings: Settings, booking_id: str, body: s.RescheduleRequest,
    *, caller_number: str | None, actor: str,
) -> tuple[t.Booking, SlotView]:
    target = ids.parse_slot_id(body.new_slot_id)
    if target is None:
        raise validation("newSlotId is not a slot id returned by availability search.", "newSlotId")
    # Resource locks before the row lock, in a fixed order: an exception being created takes the
    # resource lock and then locks its bookings, so the reverse order here would deadlock.
    current = await session.scalar(select(t.Booking.resource_id).where(t.Booking.id == booking_id))
    for resource_id in sorted({r for r in (current, target.session.resource_id) if r}):
        await schedule.lock_resource(session, resource_id, exclusive=False)
    row = await _locate(session, settings, booking_id, body.customer_name, caller_number)
    if row.status not in CHANGEABLE_STATUSES:
        raise ApiError("CONFLICT", "This booking can no longer be moved.")
    previous = await _move(session, settings, row, body.new_slot_id, channel="AGENT", actor=actor,
                           status="RESCHEDULED")
    return row, previous


# ---------------------------------------------------------------- staff


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


_STAFF_TRANSITIONS = {
    "ARRIVED": ("BOOKED", "CONFIRMED_BY_DESK", "RESCHEDULED"),
    "COMPLETED": ("BOOKED", "CONFIRMED_BY_DESK", "RESCHEDULED", "ARRIVED"),
    "NO_SHOW": ("BOOKED", "CONFIRMED_BY_DESK", "RESCHEDULED"),
    "CANCELLED_BY_PROVIDER": CHANGEABLE_STATUSES,
}


async def set_status(
    session: AsyncSession, settings: Settings, booking_id: str, body: s.StatusRequest, actor: str
) -> t.Booking:
    row = await get(session, booking_id, lock=True)
    if row.status not in _STAFF_TRANSITIONS[body.status]:
        raise ApiError("CONFLICT", f"Cannot move a booking from {row.status} to {body.status}.")
    today = schedule.now_in(settings).date()
    if body.status == "ARRIVED" and row.date != today:
        raise ApiError("CONFLICT", "A customer can only arrive on the day of the booking.")
    if body.status in ("COMPLETED", "NO_SHOW") and row.date > today:
        raise ApiError("CONFLICT", f"A booking on {row.date} cannot be {body.status} yet.")
    previous = row.status
    row.status = body.status
    _history(session, row.id, actor, body.status, previous=previous, note=body.note)
    await session.flush()
    return row
