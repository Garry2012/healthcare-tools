"""Knowledge base: approved answers for the agent, CRUD for staff (TARGET.md A4)."""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import schemas as s
from ..config import Settings
from ..db import tables as t
from ..domain import knowledge as kb
from ..domain.resolver import LexiconTerm, red_flag_terms
from ..errors import not_found, validation
from . import cache, schedule


@dataclass(frozen=True, slots=True)
class KnowledgeData:
    """Everything a search needs, built once per (directory, knowledge) version."""

    index: kb.LexicalIndex
    red_flags: tuple[LexiconTerm, ...]


async def build(session: AsyncSession) -> KnowledgeData:
    rows = (await session.scalars(select(t.KnowledgeEntry).where(t.KnowledgeEntry.approved.is_(True)))).all()
    entries = [
        kb.Entry(r.id, r.topic, tuple(r.questions), dict(r.answers), r.action, r.destination,
                 "DOCUMENT" if r.source == "DOCUMENT" else "CURATED")
        for r in rows
    ]
    flags = (await session.scalars(select(t.LexiconEntry).where(
        t.LexiconEntry.approved.is_(True), t.LexiconEntry.concept_type == "RED_FLAG"
    ))).all()
    terms = tuple(LexiconTerm(f.concept_type, f.concept_id, f.term, f.language) for f in flags)
    return KnowledgeData(kb.LexicalIndex.build(entries), terms)


def new_cache() -> cache.VersionedCache[KnowledgeData]:
    return cache.VersionedCache((cache.DIRECTORY, cache.KNOWLEDGE), build)


async def agent_search(
    session: AsyncSession, settings: Settings, data_cache: cache.VersionedCache[KnowledgeData],
    body: s.KnowledgeSearchRequest,
) -> s.KnowledgeSearchResponse:
    now = schedule.now_in(settings)
    data = await data_cache.get(session)
    # RULE (as availability-search): the safety check runs before anything else.
    if red_flag_terms([body.question], data.red_flags):
        return s.KnowledgeSearchResponse(
            outcome="TRANSFER", as_of=now,
            routing=s.KnowledgeRouting(action="TRANSFER_EMERGENCY", destination=settings.pack.escalation_destination),
        )
    hits = data.index.search(body.question, limit=5)
    if body.topic:
        hits = [h for h in hits if h.entry.topic == body.topic]
    decision = kb.decide(hits, settings.knowledge_thresholds)
    if decision.outcome == "ANSWERED" and decision.hit:
        entry = decision.hit.entry
        language, text = kb.pick_answer(entry, body.language)
        routing = (s.KnowledgeRouting(action="TRANSFER_DESK", destination=entry.destination)
                   if entry.action == "TRANSFER_DESK" else s.KnowledgeRouting(action="ANSWER"))
        return s.KnowledgeSearchResponse(
            outcome="ANSWERED", as_of=now, routing=routing,
            answer=s.KnowledgeAnswer(entry_id=entry.entry_id, topic=entry.topic, text=text, language=language,
                                     source=entry.source, confidence=decision.hit.score,
                                     matched_question=decision.hit.matched_question),
        )
    if decision.outcome == "CLARIFICATION_NEEDED":
        return s.KnowledgeSearchResponse(
            outcome="CLARIFICATION_NEEDED", as_of=now, routing=s.KnowledgeRouting(action="CLARIFY"),
            options=[s.KnowledgeOption(entry_id=h.entry.entry_id, topic=h.entry.topic,
                                     label=kb.option_label(h.entry, body.language))
                     for h in decision.options],
        )
    return s.KnowledgeSearchResponse(
        outcome="NO_ANSWER", as_of=now,
        routing=s.KnowledgeRouting(action="TRANSFER_DESK", destination=settings.pack.desk_destination),
    )


# ---------------------------------------------------------------- staff


def _model(row: t.KnowledgeEntry) -> s.KnowledgeEntry:
    return s.KnowledgeEntry(
        id=row.id, topic=row.topic, questions=list(row.questions), answers=dict(row.answers), action=row.action,
        destination=row.destination, approved=row.approved, source=row.source, updated_at=row.updated_at,
    )


def _check(body: s.KnowledgeEntryInput, settings: Settings) -> None:
    if body.action == "TRANSFER_DESK":
        if not body.destination:
            raise validation("TRANSFER_DESK needs a destination.", "destination")
        if body.destination not in settings.transfer_destinations:
            raise validation(f"Unknown destination {body.destination!r}.", "destination")
    elif body.destination:
        raise validation("Only TRANSFER_DESK entries have a destination.", "destination")


def _apply(row: t.KnowledgeEntry, body: s.KnowledgeEntryInput, actor: str) -> None:
    row.topic = body.topic
    row.questions = list(dict.fromkeys(q.strip() for q in body.questions))
    row.answers = {lang: text.strip() for lang, text in body.answers.items()}
    row.action, row.destination, row.approved = body.action, body.destination, body.approved
    row.updated_by = actor


async def list_entries(session: AsyncSession, *, topic: str | None, approved: bool | None) -> s.KnowledgeList:
    query = select(t.KnowledgeEntry)
    if topic:
        query = query.where(t.KnowledgeEntry.topic == topic)
    if approved is not None:
        query = query.where(t.KnowledgeEntry.approved.is_(approved))
    rows = await session.scalars(query.order_by(t.KnowledgeEntry.topic, t.KnowledgeEntry.id))
    return s.KnowledgeList(items=[_model(r) for r in rows])


async def create(session: AsyncSession, settings: Settings, body: s.KnowledgeEntryInput, actor: str,
                 *, entry_id: str | None = None, source: str = "PROVIDER") -> s.KnowledgeEntry:
    _check(body, settings)
    row = t.KnowledgeEntry(id=entry_id or f"kb_{secrets.token_hex(8)}", source=source)
    _apply(row, body, actor)
    session.add(row)
    await cache.bump(session, cache.KNOWLEDGE)
    await session.commit()
    await session.refresh(row)
    return _model(row)


async def update(session: AsyncSession, settings: Settings, entry_id: str, body: s.KnowledgeEntryInput,
                 actor: str) -> s.KnowledgeEntry:
    _check(body, settings)
    row = await session.get(t.KnowledgeEntry, entry_id)
    if row is None:
        raise not_found("No such knowledge entry.")
    _apply(row, body, actor)
    await cache.bump(session, cache.KNOWLEDGE)
    await session.commit()
    await session.refresh(row)
    return _model(row)


async def delete(session: AsyncSession, entry_id: str) -> None:
    row = await session.get(t.KnowledgeEntry, entry_id)
    if row is None:
        raise not_found("No such knowledge entry.")
    await session.delete(row)
    await cache.bump(session, cache.KNOWLEDGE)
    await session.commit()
