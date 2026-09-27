"""`frontdesk-api rollout apply`: write a composed rollout (domain baseline + rollout data).

Idempotent upserts, in one transaction, with the directory and knowledge caches bumped.

Who owns what: the files say what exists and what it says (departments, resources, schedules,
wording, answers); staff say whether each thing is on (a resource or category `active`, an
answer or a term `approved`). So a new row starts on, and an existing row keeps the switch staff
left it at: re-deploying never brings back a doctor staff retired or an answer they switched off.
The one exception is a danger sign, which is always on.

Rows the rollout no longer lists are left alone (retire them through the staff API, where
bookings are handled). The domain baseline is owned by the pack: baseline rows the current pack
version no longer carries are removed. A row the provider added itself stays the provider's even
when the baseline has the same words, so a later pack version never deletes it.
"""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import rollouts
from ..config import Settings
from ..db import tables as t
from ..domain.text import normalise
from ..rollouts import BASELINE, ROLLOUT, Composed
from . import cache, directory

TEMPLATE_FROM = date(2020, 1, 1)
ACTOR = "rollout"


class RolloutInvalid(ValueError):
    """The rollout failed its offline checks; nothing was written."""


def load(settings: Settings, rollout_dir: str | None = None) -> Composed:
    """The rollout this deployment serves, composed with its domain and validated offline."""
    path = rollout_dir or settings.rollout_dir
    if not path:
        raise RolloutInvalid("no rollout to load: set ROLLOUT_DIR (or pass the directory)")
    rollout = rollouts.load(path)
    if (rollout.id, rollout.domain, set(rollout.languages)) != (
            settings.provider_id, settings.domain_pack, set(settings.languages)):
        raise RolloutInvalid(
            f"{path} is rollout {rollout.id!r} ({rollout.domain}, {','.join(rollout.languages)}), but this deployment "
            f"runs {settings.provider_id!r} ({settings.domain_pack}, {settings.tenant_supported_languages}): deploy "
            "the rollout's own rollout.env with its data")
    composed = rollouts.compose(settings.pack, rollout)
    report = rollouts.validate(composed, settings.transfer_destinations, settings.thresholds,
                               settings.knowledge_thresholds)
    if report.problems:
        raise RolloutInvalid("the rollout is not valid:\n  " + "\n  ".join(report.problems))
    return composed


async def _categories(session: AsyncSession, composed: Composed) -> None:
    for c in composed.rollout.categories:
        row = await session.get(t.Category, c.id) or t.Category(id=c.id, active=True)
        row.code, row.name, row.localized_names = c.code, c.name, dict(c.names)
        row.offers_bookings = c.bookable
        session.add(row)
    await session.flush()


async def _resources(session: AsyncSession, settings: Settings, composed: Composed) -> None:
    for r in composed.rollout.resources:
        row = await session.get(t.Resource, r.id) or t.Resource(id=r.id, active=True)
        row.name = r.name
        row.localized_names = dict(r.names)
        row.name_variants = list(r.variants)
        row.gender = r.gender
        row.attributes = dict(r.attributes)
        row.languages_spoken = list(r.languages)
        row.price_amount = Decimal(r.price) if r.price is not None else None
        row.price_currency = settings.tenant_currency if r.price is not None else None
        row.price_confirmed = r.price_confirmed and r.price is not None
        row.attendance_type, row.booking_policy = r.attendance, r.policy
        row.data_confirmed = r.data_confirmed
        session.add(row)
        await session.flush()
        await session.execute(delete(t.ResourceCategory).where(t.ResourceCategory.resource_id == r.id))
        for position, category in enumerate(r.categories):
            session.add(t.ResourceCategory(resource_id=r.id, category_id=category, position=position))
        await _template(session, settings, r)
    await session.flush()


async def _template(session: AsyncSession, settings: Settings, r) -> None:
    template_id = f"tpl_{r.id}_{TEMPLATE_FROM.isoformat()}"
    existing = await session.get(t.ScheduleTemplate, template_id)
    if existing is not None:
        await session.delete(existing)
        await session.flush()
    if not r.sessions:
        return
    session.add(t.ScheduleTemplate(id=template_id, resource_id=r.id, effective_from=TEMPLATE_FROM, created_by=ACTOR))
    await session.flush()
    for ordinal, s in enumerate(r.sessions, start=1):
        session.add(t.TemplateSession(
            template_id=template_id, template_session_id=f"tpl_{r.id}_{s.key}", ordinal=ordinal, label=s.label,
            days_of_week=list(s.days), start_time=time.fromisoformat(s.start), end_time=time.fromisoformat(s.end),
            capacity_model=s.model, slot_minutes=s.slot_minutes, capacity_mode=s.mode, capacity_value=s.value,
            walk_in_reserve_percent=s.reserve,
            last_arrival_offset_minutes=settings.tenant_last_arrival_offset_minutes,
        ))


async def _lexicon(session: AsyncSession, composed: Composed) -> int:
    wanted: set[str] = set()
    for (kind, target, term, language), source in composed.lexicon:
        entry_id = directory.lexicon_id(kind, target, term, language)
        wanted.add(entry_id)
        row = await session.get(t.LexiconEntry, entry_id)
        if row is None:
            row = t.LexiconEntry(id=entry_id, concept_type=kind, concept_id=target, term=term, language=language,
                                 approved=True)
        elif kind == "RED_FLAG":
            row.approved = True  # danger signs are never off
        if row.source != ROLLOUT or source == ROLLOUT:  # a row the provider made stays the provider's
            row.source = source
        row.term_normalized = normalise(term)
        session.add(row)
    stale = await session.scalars(select(t.LexiconEntry.id).where(t.LexiconEntry.source == BASELINE))
    removed = [entry_id for entry_id in stale if entry_id not in wanted]
    if removed:
        await session.execute(delete(t.LexiconEntry).where(t.LexiconEntry.id.in_(removed)))
    return len(removed)


async def _knowledge(session: AsyncSession, composed: Composed) -> None:
    for k in composed.rollout.knowledge:
        entry = await session.get(t.KnowledgeEntry, k.id) or t.KnowledgeEntry(id=k.id, source="PROVIDER",
                                                                             approved=True)
        entry.topic, entry.questions, entry.answers = k.topic, list(k.questions), dict(k.answers)
        entry.action, entry.destination, entry.updated_by = k.action, k.destination, ACTOR
        session.add(entry)


async def apply(session: AsyncSession, settings: Settings, composed: Composed) -> dict[str, int]:
    """Write the rollout; the caller commits. Refuses another provider's rollout."""
    if composed.rollout.id != settings.provider_id:
        raise ValueError(f"rollout {composed.rollout.id!r} is not this deployment's provider {settings.provider_id!r}")
    await _categories(session, composed)
    await _resources(session, settings, composed)
    removed = await _lexicon(session, composed)
    await _knowledge(session, composed)
    await cache.bump(session, cache.DIRECTORY, cache.KNOWLEDGE)
    return {"categories": len(composed.rollout.categories), "resources": len(composed.rollout.resources),
            "terms": len(composed.lexicon), "baselineRemoved": removed, "knowledge": len(composed.rollout.knowledge)}
