"""`frontdesk-api seed` — the domain pack's synthetic demo data, idempotent, relative to the run date.

Directory rows (categories, resources, templates, lexicon) are upserted every run from
`DOMAIN_PACK`. Date-specific data (bookings, exceptions, board) comes from the pack's
`scenario` and is created once; a second run leaves it alone. `--reset` empties every table
first (destructive) so the demo can be re-dated. The scenario goes through the same services
the API uses, so an exception really does move its customers to NEEDS_RESCHEDULE and queue
notifications.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import packs
from . import schemas as s
from .config import Settings
from .db import tables as t
from .db.session import make_engine, make_sessionmaker
from .domain.text import normalise
from .logging import configure_logging, log_event
from .services import board, bookings, cache, directory, schedule, schedule_exceptions
from .services.idempotency import run as idempotent

logger = logging.getLogger(__name__)
TEMPLATE_FROM = date(2020, 1, 1)
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


async def _upsert_directory(session: AsyncSession, settings: Settings) -> None:
    data = packs.load(settings.domain_pack)
    legacy = await session.scalar(select(func.count()).select_from(t.Resource).where(
        t.Resource.id.like("doc\\_%"), t.Resource.id.notin_([r.id for r in data.resources])))
    if legacy:
        raise LegacyDemoData(
            f"{legacy} demo resources use pre-0002 ids (doc_*); run `frontdesk-api seed --reset` to re-date the demo"
        )
    for d in data.categories:
        row = await session.get(t.Category, d.id) or t.Category(id=d.id)
        row.code, row.name, row.localized_names = d.code, d.name, dict(d.localized)
        row.offers_bookings, row.active = d.offers_bookings, True
        session.add(row)
    await session.flush()

    for doc in data.resources:
        row = await session.get(t.Resource, doc.id) or t.Resource(id=doc.id)
        row.name = doc.name
        row.localized_names = dict(doc.localized)
        row.name_variants = list(doc.variants)
        row.gender = doc.gender
        row.attributes = dict(doc.attributes)
        row.languages_spoken = list(doc.languages)
        row.price_amount = Decimal(doc.price) if doc.price is not None else None
        row.price_currency = settings.tenant_currency if doc.price is not None else None
        row.price_confirmed = doc.price_confirmed and doc.price is not None
        row.attendance_type, row.booking_policy = doc.attendance, doc.policy
        row.data_confirmed, row.active = doc.data_confirmed, True
        session.add(row)
        await session.flush()
        await session.execute(delete(t.ResourceCategory).where(t.ResourceCategory.resource_id == doc.id))
        for position, cat in enumerate(doc.categories):
            session.add(t.ResourceCategory(resource_id=doc.id, category_id=cat, position=position))

        template_id = f"tpl_{doc.id}_{TEMPLATE_FROM.isoformat()}"
        existing = await session.get(t.ScheduleTemplate, template_id)
        if existing is not None:
            await session.delete(existing)
            await session.flush()
        if doc.sessions:
            session.add(t.ScheduleTemplate(id=template_id, resource_id=doc.id, effective_from=TEMPLATE_FROM,
                                           created_by=SEED_ACTOR))
            await session.flush()
            for ordinal, sess in enumerate(doc.sessions, start=1):
                session.add(t.TemplateSession(
                    template_id=template_id,
                    template_session_id=f"tpl_{doc.id}_{sess.key}",
                    ordinal=ordinal,
                    label=sess.label,
                    days_of_week=list(sess.days),
                    start_time=time.fromisoformat(sess.start),
                    end_time=time.fromisoformat(sess.end),
                    capacity_model=sess.model,
                    slot_minutes=sess.slot_minutes,
                    capacity_mode=sess.mode,
                    capacity_value=sess.value,
                    walk_in_reserve_percent=sess.reserve,
                    last_arrival_offset_minutes=settings.tenant_last_arrival_offset_minutes,
                ))
    await session.flush()

    for concept_type, concept_id, term, language in data.lexicon:
        entry_id = directory.lexicon_id(concept_type, concept_id, term, language)
        row = await session.get(t.LexiconEntry, entry_id) or t.LexiconEntry(
            id=entry_id, concept_type=concept_type, concept_id=concept_id, term=term, language=language,
        )
        row.term_normalized, row.approved, row.source = normalise(term), True, "PROVIDER"
        session.add(row)

    for k in data.knowledge:
        entry = await session.get(t.KnowledgeEntry, k.id) or t.KnowledgeEntry(id=k.id, source="PROVIDER")
        entry.topic, entry.questions, entry.answers = k.topic, list(k.questions), dict(k.answers)
        entry.action, entry.destination, entry.approved, entry.updated_by = k.action, k.destination, True, SEED_ACTOR
        session.add(entry)
    await cache.bump(session, cache.DIRECTORY, cache.KNOWLEDGE)
    await session.commit()


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

    async def book(self, slot_id: str, customer: packs.CustomerSeed, *, channel: str = "AGENT") -> int:
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


async def run(settings: Settings, *, reset: bool = False) -> dict[str, int]:
    if settings.env == "production":
        # A real provider's data is loaded through the staff API (ONBOARDING.md), never seeded.
        raise SeedRefused("refusing to seed synthetic data with ENV=production")
    configure_logging(settings.log_level, settings.provider_id)
    engine = make_engine(settings)
    try:
        async with make_sessionmaker(engine)() as session:
            if reset:
                for table in ALL_TABLES:
                    await session.execute(delete(table))
                await session.commit()
            await _upsert_directory(session, settings)
            already = await session.scalar(
                select(func.count()).select_from(t.ScheduleException).where(
                    t.ScheduleException.created_by == SEED_ACTOR
                )
            )
            data = packs.load(settings.domain_pack)
            if already or data.scenario is None:
                summary = {"bookings": 0, "exceptions": 0, "board": 0}
                log_event(logger, logging.INFO, "seed_dynamic_skipped", reason="already seeded or no scenario")
            else:
                summary = await data.scenario(Seeder(session, settings))
            log_event(logger, logging.INFO, "seed_complete", pack=data.name, **summary,
                      resources=len(data.resources), categories=len(data.categories), lexicon=len(data.lexicon),
                      knowledge=len(data.knowledge))
            return summary
    finally:
        await engine.dispose()
