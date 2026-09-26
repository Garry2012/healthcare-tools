"""The status sets in domain/booking_status.py and the database agree: a status added to one
but not the other would allow double booking or reject valid rows."""

from __future__ import annotations

import re

from sqlalchemy import text

from frontdesk_api.domain import booking_status


def _quoted(definition: str) -> set[str]:
    return set(re.findall(r"'([A-Z_]+)'", definition))


async def test_the_unique_slot_index_uses_exactly_the_slot_holding_statuses(app):
    async with app.state.sessionmaker() as session:
        [definition] = (await session.execute(text(
            "SELECT indexdef FROM pg_indexes WHERE tablename = 'bookings' AND indexdef LIKE '%UNIQUE%slot_id%'"
        ))).scalars().all()
    assert _quoted(definition) == set(booking_status.HOLDS_SLOT)


async def test_the_status_check_constraint_allows_exactly_the_lifecycle(app):
    async with app.state.sessionmaker() as session:
        [definition] = (await session.execute(text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'bookings'::regclass AND contype = 'c' AND pg_get_constraintdef(oid) LIKE '%status%'"
        ))).scalars().all()
    assert _quoted(definition) == set(booking_status.ALL)


def test_the_sets_nest_the_way_the_rules_assume():
    assert set(booking_status.BEFORE_VISIT) < set(booking_status.HOLDS_SLOT) < set(booking_status.ALL)
    assert set(booking_status.CHANGEABLE).isdisjoint(booking_status.CANCELLED)
    for target, sources in booking_status.STAFF_TRANSITIONS.items():
        assert target in booking_status.ALL and set(sources) <= set(booking_status.ALL)
