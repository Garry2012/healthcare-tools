"""The live board: what the desk marks for today (arrived, late, left, full)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import schemas as s
from ..config import Settings
from ..db import tables as t
from ..domain import ids
from ..domain.availability import find_session
from ..errors import not_found, validation
from . import directory, schedule, views


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
    await directory.require_resource(session, resource_id)
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
    await directory.require_resource(session, resource_id)
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
            value = views.time_of(value)
        elif hasattr(value, "value"):
            value = value.value
        setattr(row, name, value)
    row.updated_at = datetime.now(settings.tz)
    row.updated_by = actor
    await session.commit()
    await session.refresh(row)
    return _board_model(row, staff=True)


async def purge_board_before(session: AsyncSession, day: date) -> int:
    """Board facts expire at day end; the engine already ignores old rows."""
    result = await session.execute(delete(t.BoardEntry).where(t.BoardEntry.date < day))
    await session.commit()
    return result.rowcount or 0
