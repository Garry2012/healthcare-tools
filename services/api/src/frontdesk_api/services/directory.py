"""Resources, categories and the lexicon."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import schemas as s
from ..db import tables as t
from ..domain.resolver import CategoryEntry, Directory, LexiconTerm, ResourceEntry
from ..domain.text import normalise
from ..errors import not_found, validation
from . import cache, views


@dataclass(slots=True)
class DirectorySnapshot:
    resources: dict[str, t.Resource]
    categories: dict[str, t.Category]
    resource_categories: dict[str, list[str]]
    lexicon: list[t.LexiconEntry]

    def categories_of(self, resource_id: str) -> list[t.Category]:
        return [self.categories[d] for d in self.resource_categories.get(resource_id, [])
                if d in self.categories]

    def resolver_directory(self) -> Directory:
        return Directory(
            resources=tuple(
                ResourceEntry(
                    resource_id=d.id,
                    name=d.name,
                    category_ids=tuple(self.resource_categories.get(d.id, [])),
                    name_variants=tuple(d.name_variants or ()),
                    localized_names=tuple((d.localized_names or {}).values()),
                    active=d.active and d.booking_policy != "NOT_OFFERED",
                    booking_policy=d.booking_policy,
                )
                for d in self.resources.values()
            ),
            categories=tuple(
                CategoryEntry(
                    category_id=d.id,
                    name=d.name,
                    code=d.code,
                    localized_names=tuple((d.localized_names or {}).values()),
                    offers_bookings=d.offers_bookings,
                    active=d.active,
                )
                for d in self.categories.values()
            ),
            lexicon=tuple(
                LexiconTerm(e.concept_type, e.concept_id, e.term, e.language, e.approved)
                for e in self.lexicon
            ),
        )

    def day_parts(self) -> list[tuple[str, str]]:
        return [
            (normalise(e.term), e.concept_id)
            for e in self.lexicon
            if e.approved and e.concept_type == "DAY_PART"
        ]


async def snapshot(session: AsyncSession, *, approved_lexicon_only: bool = True) -> DirectorySnapshot:
    resources = {d.id: d for d in (await session.scalars(select(t.Resource))).all()}
    categories = {d.id: d for d in (await session.scalars(select(t.Category))).all()}
    links: dict[str, list[str]] = {}
    for row in await session.scalars(
        select(t.ResourceCategory).order_by(t.ResourceCategory.resource_id, t.ResourceCategory.position)
    ):
        links.setdefault(row.resource_id, []).append(row.category_id)
    query = select(t.LexiconEntry)
    if approved_lexicon_only:
        query = query.where(t.LexiconEntry.approved.is_(True))
    lexicon = list((await session.scalars(query)).all())
    return DirectorySnapshot(resources, categories, links, lexicon)


# ---------------------------------------------------------------- categories


async def list_categories(session: AsyncSession) -> tuple[s.CategoryList, str]:
    rows = (await session.scalars(select(t.Category).order_by(t.Category.name))).all()
    body = s.CategoryList(items=[views.category(r) for r in rows])
    etag = hashlib.sha256(
        json.dumps(body.model_dump(mode="json", by_alias=True), sort_keys=True).encode()
    ).hexdigest()[:32]
    return body, f'"{etag}"'


# ---------------------------------------------------------------- resources


def _slug(name: str) -> str:
    base = normalise(name, strip_honorifics=True)
    return re.sub(r"[^a-z0-9]+", "_", base).strip("_")[:40] or "resource"


async def _resource_categories(session: AsyncSession, resource_id: str) -> list[t.Category]:
    rows = await session.execute(
        select(t.Category)
        .join(t.ResourceCategory, t.ResourceCategory.category_id == t.Category.id)
        .where(t.ResourceCategory.resource_id == resource_id)
        .order_by(t.ResourceCategory.position)
    )
    return list(rows.scalars())


async def list_resources(
    session: AsyncSession, *, category: str | None, active: bool | None, limit: int, offset: int
) -> s.ResourcePage:
    query = select(t.Resource)
    if active is not None:
        query = query.where(t.Resource.active.is_(active))
    if category:
        wanted = category.casefold()
        cat_ids = [
            d.id
            for d in (await session.scalars(select(t.Category))).all()
            if wanted in {d.id.casefold(), (d.code or "").casefold(), d.name.casefold()}
        ]
        query = query.where(
            t.Resource.id.in_(
                select(t.ResourceCategory.resource_id).where(t.ResourceCategory.category_id.in_(cat_ids))
            )
        )
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (await session.scalars(query.order_by(t.Resource.name).limit(limit).offset(offset))).all()
    items = [views.resource(r, await _resource_categories(session, r.id)) for r in rows]
    return s.ResourcePage(items=items, total=total)


async def get_resource(session: AsyncSession, resource_id: str) -> s.Resource:
    row = await session.get(t.Resource, resource_id)
    if row is None:
        raise not_found("No such resource.")
    return views.resource(row, await _resource_categories(session, resource_id))


def _apply_resource(row: t.Resource, body: s.ResourceInput, currency: str) -> None:
    row.name = body.name
    row.localized_names = body.localized_names or {}
    row.name_variants = body.name_variants or []
    row.gender = body.gender.value if body.gender else None
    row.attributes = dict(body.attributes or {})
    row.languages_spoken = body.languages_spoken or []
    if body.price is not None:
        row.price_amount = Decimal(str(body.price.amount))
        row.price_currency = body.price.currency or currency
        row.price_confirmed = body.price.confirmed
    else:
        row.price_amount, row.price_currency, row.price_confirmed = None, None, False
    row.attendance_type = body.attendance_type or "REGULAR"
    row.booking_policy = body.booking_policy or "BOOKABLE"
    row.data_confirmed = bool(body.data_confirmed)
    row.active = True if body.active is None else body.active


async def _set_categories(session: AsyncSession, resource_id: str, category_ids: list[str]) -> None:
    known = set((await session.scalars(select(t.Category.id).where(t.Category.id.in_(category_ids)))).all())
    unknown = [d for d in category_ids if d not in known]
    if unknown:
        raise validation(f"Unknown category: {', '.join(unknown)}.", "categoryIds")
    await session.execute(delete(t.ResourceCategory).where(t.ResourceCategory.resource_id == resource_id))
    for position, cat_id in enumerate(dict.fromkeys(category_ids)):
        session.add(t.ResourceCategory(resource_id=resource_id, category_id=cat_id, position=position))


async def create_resource(session: AsyncSession, body: s.ResourceInput, currency: str) -> s.Resource:
    base = f"res_{_slug(body.name)}"
    resource_id, n = base, 1
    while await session.get(t.Resource, resource_id) is not None:
        n += 1
        resource_id = f"{base}_{n}"
    row = t.Resource(id=resource_id)
    _apply_resource(row, body, currency)
    session.add(row)
    await session.flush()
    await _set_categories(session, resource_id, body.category_ids)
    await cache.bump(session, cache.DIRECTORY)
    await session.commit()
    return await get_resource(session, resource_id)


async def update_resource(session: AsyncSession, resource_id: str, body: s.ResourceInput, currency: str) -> s.Resource:
    row = await session.get(t.Resource, resource_id)
    if row is None:
        raise not_found("No such resource.")
    _apply_resource(row, body, currency)
    await _set_categories(session, resource_id, body.category_ids)
    await cache.bump(session, cache.DIRECTORY)
    await session.commit()
    return await get_resource(session, resource_id)


# ---------------------------------------------------------------- lexicon


def lexicon_id(concept_type: str, concept_id: str, term: str, language: str) -> str:
    digest = hashlib.sha256(f"{concept_type}|{concept_id}|{term}|{language}".encode()).hexdigest()
    return f"lex_{digest[:16]}"


def _lexicon_model(row: t.LexiconEntry) -> s.LexiconEntry:
    return s.LexiconEntry(
        id=row.id,
        concept_type=row.concept_type,
        concept_id=row.concept_id,
        term=row.term,
        term_normalized=row.term_normalized,
        language=row.language,
        approved=row.approved,
        source=row.source,
    )


async def list_lexicon(
    session: AsyncSession, *, concept_type: str | None, language: str | None, approved: bool | None
) -> s.LexiconList:
    query = select(t.LexiconEntry)
    if concept_type:
        query = query.where(t.LexiconEntry.concept_type == concept_type)
    if language:
        query = query.where(t.LexiconEntry.language == language)
    if approved is not None:
        query = query.where(t.LexiconEntry.approved.is_(approved))
    rows = await session.scalars(query.order_by(t.LexiconEntry.concept_type, t.LexiconEntry.term))
    return s.LexiconList(items=[_lexicon_model(r) for r in rows])


_DAY_PARTS = {"MORNING", "AFTERNOON", "EVENING", "ANY"}


async def _check_concept(session: AsyncSession, concept_type: str, concept_id: str, transfers: dict[str, str]) -> None:
    if concept_type in ("CATEGORY", "NEED_ROUTE"):
        ok = await session.get(t.Category, concept_id) is not None
    elif concept_type == "RESOURCE":
        ok = await session.get(t.Resource, concept_id) is not None
    elif concept_type == "DAY_PART":
        ok = concept_id in _DAY_PARTS
    elif concept_type == "SERVICE_TRANSFER":
        ok = concept_id in transfers
    else:  # RED_FLAG: the concept id is a free label; the action is always emergency transfer.
        ok = True
    if not ok:
        raise validation(f"conceptId {concept_id!r} does not exist for {concept_type}.", "conceptId")


async def upsert_lexicon(
    session: AsyncSession, body: s.LexiconEntryInput, transfers: dict[str, str], *, source: str = "PROVIDER"
) -> s.LexiconEntry:
    concept_type = body.concept_type.value
    await _check_concept(session, concept_type, body.concept_id, transfers)
    entry_id = lexicon_id(concept_type, body.concept_id, body.term, body.language)
    row = await session.get(t.LexiconEntry, entry_id)
    if row is None:
        row = t.LexiconEntry(
            id=entry_id,
            concept_type=concept_type,
            concept_id=body.concept_id,
            term=body.term,
            language=body.language,
            source=source,
        )
        session.add(row)
    row.term_normalized = normalise(body.term)
    row.approved = body.approved
    await cache.bump(session, cache.DIRECTORY)
    await session.commit()
    return _lexicon_model(row)

