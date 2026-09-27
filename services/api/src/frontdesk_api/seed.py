"""`frontdesk-api seed` — a demo rollout plus its dated scenario, idempotent, relative to the run date.

The rollout in ROLLOUT_DIR (rollouts/demo-hospital, rollouts/demo-hotel) is applied every run,
exactly as `frontdesk-api rollout apply` would. Date-specific data (bookings, exceptions, board)
comes from the demo scenario named after the rollout (`frontdesk_api.demo`) and is created once;
a second run leaves it alone. `--reset` empties every table
first (destructive) so the demo can be re-dated. The scenario goes through the same services
the API uses, so an exception really does move its customers to NEEDS_RESCHEDULE and queue
notifications.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import demo, locales
from . import schemas as s
from .config import Settings
from .db import tables as t
from .db.session import make_engine, make_sessionmaker
from .logging import configure_logging, log_event
from .services import board, bookings, rollout_apply, schedule, schedule_exceptions
from .services.idempotency import run as idempotent

logger = logging.getLogger(__name__)
SEED_ACTOR = "seed"
# Children before parents. `--reset` empties all of them: a demo database returns to exactly
# the seed state, whatever was written through the API in between.
ALL_TABLES = (
    t.Notification, t.BookingHistory, t.Booking, t.ScheduleException, t.BoardEntry,
    t.IdempotencyKey, t.CallSummary, t.KnowledgeEntry, t.LexiconEntry, t.TemplateSession, t.ScheduleTemplate,
    t.ResourceCategory, t.Resource, t.Category,
)


class SeedRefused(RuntimeError):
    """The seed would put synthetic data where it must not go."""


class LegacyDemoData(SeedRefused):
    """Demo rows from before migration 0002 (doc_*/dept_* ids) would duplicate the pack's directory."""


async def load_directory(session: AsyncSession, settings: Settings, rollout_dir: str | None = None) -> dict[str, int]:
    """Apply the demo rollout (domain baseline + its data) and commit."""
    try:
        composed = rollout_apply.load(settings, rollout_dir)
    except rollout_apply.RolloutInvalid as exc:
        raise SeedRefused(str(exc)) from None
    legacy = await session.scalar(select(func.count()).select_from(t.Resource).where(
        t.Resource.id.like("doc\\_%"), t.Resource.id.notin_([r.id for r in composed.rollout.resources])))
    if legacy:
        raise LegacyDemoData(
            f"{legacy} demo resources use pre-0002 ids (doc_*); run `frontdesk-api seed --reset` to re-date the demo"
        )
    summary = await rollout_apply.apply(session, settings, composed)
    await session.commit()
    return summary


class Seeder:
    """What a pack scenario may do: book, add exceptions, mark the board. All through services."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.now: datetime = schedule.now_in(settings)
        self.today: date = self.now.date()

    def next_weekday(self, weekday: int, *, include_today: bool = False) -> date:
        ahead = (weekday - self.today.weekday()) % 7
        if ahead == 0 and not include_today:
            ahead = 7
        return self.today + timedelta(days=ahead)

    async def first_free(self, resource_id: str, on: date, session_n: str | None = None,
                         skip: int = 0) -> list[str]:
        loaded = await schedule.load(self.session, self.settings, self.now, [resource_id], on, on)
        slots: list[str] = []
        for view in loaded.sessions(resource_id, on):
            if session_n and not view.session_id.endswith(f"_{session_n}"):
                continue
            slots += [x.slot_id for x in view.available_slots()]
        return slots[skip:]

    async def book(self, slot_id: str, customer: demo.Customer, *, channel: str = "AGENT") -> int:
        body = s.AgentBookRequest(
            slot_id=slot_id,
            customer=s.BookCustomer(name=customer.name, phone=customer.phone, relation_to_caller=customer.relation),
            reason_verbatim=customer.reason,
            language=customer.language,
        )

        async def operation() -> tuple[int, dict]:
            booked = await bookings.book(
                self.session, self.settings, body, channel=channel, call_id=f"seed-{slot_id}",
                caller_number=customer.caller if channel == "AGENT" else None, actor=SEED_ACTOR,
            )
            return 201, {"id": booked.row.id}

        await idempotent(self.session, None, "", operation)
        return 1

    async def exception(self, **fields) -> None:
        body = s.ScheduleExceptionInput(**fields)

        async def operation() -> tuple[int, dict]:
            created = await schedule_exceptions.create_exception(self.session, self.settings, body, SEED_ACTOR)
            return 201, {"id": created.id}

        await idempotent(self.session, None, "", operation)

    async def board(self, resource_id: str, n: str, **fields) -> None:
        entry = s.BoardEntryInput(date=self.today, session_id=f"ses_{resource_id}_{self.today.isoformat()}_{n}",
                                  **fields)
        await board.set_board(self.session, self.settings, resource_id, entry, SEED_ACTOR)


async def run(settings: Settings, *, reset: bool = False, rollout_dir: str | None = None) -> dict[str, int]:
    if settings.env == "production":
        # A real provider's data is its rollout (`frontdesk-api rollout apply`), never the demo.
        raise SeedRefused("refusing to seed synthetic data with ENV=production")
    configure_logging(settings.log_level, settings.provider_id)
    locales.select(settings.languages)
    engine = make_engine(settings)
    try:
        async with make_sessionmaker(engine)() as session:
            if reset:
                for table in ALL_TABLES:
                    await session.execute(delete(table))
                await session.commit()
            applied = await load_directory(session, settings, rollout_dir)
            already = await session.scalar(
                select(func.count()).select_from(t.ScheduleException).where(
                    t.ScheduleException.created_by == SEED_ACTOR
                )
            )
            scenario = demo.scenario_for(settings.provider_id)
            if already or scenario is None:
                summary = {"bookings": 0, "exceptions": 0, "board": 0}
                log_event(logger, logging.INFO, "seed_dynamic_skipped", reason="already seeded or no scenario")
            else:
                summary = await scenario(Seeder(session, settings))
            log_event(logger, logging.INFO, "seed_complete", rollout=settings.provider_id, **summary, **applied)
            return summary
    finally:
        await engine.dispose()
