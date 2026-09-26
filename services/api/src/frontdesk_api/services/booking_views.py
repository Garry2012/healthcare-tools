"""How a booking is presented: the agent's view (what a caller may hear) and the staff view,
with the session context both need, loaded in one query per call."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import schemas as s
from ..config import Settings
from ..db import tables as t
from ..domain import ids
from ..domain.availability import SessionView, SlotView, find_session
from . import schedule, views


def _slot_from_id(slot_id: str) -> SlotView:
    ref = ids.parse_slot_id(slot_id)
    suffix = ref.suffix if ref else ""
    # Positions are written with two or three digits, TIMED slots as HHMM.
    if len(suffix) == 4 and int(suffix[:2]) < 24 and int(suffix[2:]) < 60:
        at = time(int(suffix[:2]), int(suffix[2:]))
        return SlotView(slot_id=slot_id, kind="TIMED", available=False, start=at)
    return SlotView(slot_id=slot_id, kind="SEQUENCE", available=False,
                    position=int(suffix) if suffix.isdigit() else None)


def slot_in(view: SessionView | None, slot_id: str) -> SlotView:
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
        slot=views.slot(slot_in(view, row.slot_id)),
        previous_slot=views.slot(previous_slot) if previous_slot else None,
        arrive_by=views.clock(view.arrive_by) if view else None,
        timing_certainty=_certainty(row, view),
        price=views.spoken_money(resource) if resource else None,
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
        slot=views.slot(slot_in(view, row.slot_id)),
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
