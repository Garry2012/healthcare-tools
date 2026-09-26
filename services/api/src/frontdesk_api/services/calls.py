"""Call summaries posted by the voice platform when a call ends."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .. import schemas as s
from ..config import Settings
from ..db import tables as t
from .bookings import new_id


def _model(row: t.CallSummary) -> s.CallSummary:
    return s.CallSummary(
        id=row.id,
        call_id=row.call_id,
        started_at=row.started_at,
        duration_seconds=row.duration_seconds,
        language=row.language,
        caller_number=row.caller_number,
        intent=row.intent,
        outcome=row.outcome,
        transferred_to=row.transferred_to,
        booking_id=row.booking_id,
        tool_outcomes=row.tool_outcomes or None,
        summary_text=row.summary_text,
    )


async def store(session: AsyncSession, body: s.CallSummary) -> tuple[s.CallSummary, bool]:
    values = dict(
        id=new_id("call"),
        call_id=body.call_id,
        started_at=body.started_at,
        duration_seconds=body.duration_seconds,
        language=body.language,
        caller_number=body.caller_number,
        intent=body.intent,
        outcome=body.outcome,
        transferred_to=body.transferred_to,
        booking_id=body.booking_id,
        tool_outcomes=body.tool_outcomes or {},
        summary_text=body.summary_text,
    )
    # One summary per call even when the agent retries concurrently: the unique call_id decides.
    created = await session.scalar(
        insert(t.CallSummary).values(**values).on_conflict_do_nothing(index_elements=["call_id"])
        .returning(t.CallSummary.id)
    )
    await session.commit()
    row = await session.scalar(select(t.CallSummary).where(t.CallSummary.call_id == body.call_id))
    return _model(row), created is not None


async def page(
    session: AsyncSession, settings: Settings, *, date_from: date | None, date_to: date | None,
    limit: int, offset: int,
) -> s.CallSummaryPage:
    query = select(t.CallSummary)
    if date_from:
        query = query.where(t.CallSummary.started_at >= datetime.combine(date_from, time.min, settings.tz))
    if date_to:
        end = datetime.combine(date_to + timedelta(days=1), time.min, settings.tz)
        query = query.where(t.CallSummary.started_at < end)
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = await session.scalars(
        query.order_by(t.CallSummary.started_at.desc()).limit(limit).offset(offset)
    )
    return s.CallSummaryPage(items=[_model(r) for r in rows], total=total)
