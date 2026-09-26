"""Doctors, departments and the lexicon."""

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
from ..domain.resolver import DepartmentEntry, Directory, DoctorEntry, LexiconTerm
from ..domain.text import normalise
from ..errors import not_found, validation
from . import views


@dataclass(slots=True)
class DirectorySnapshot:
    doctors: dict[str, t.Doctor]
    departments: dict[str, t.Department]
    doctor_departments: dict[str, list[str]]
    lexicon: list[t.LexiconEntry]

    def departments_of(self, doctor_id: str) -> list[t.Department]:
        return [self.departments[d] for d in self.doctor_departments.get(doctor_id, [])
                if d in self.departments]

    def resolver_directory(self) -> Directory:
        return Directory(
            doctors=tuple(
                DoctorEntry(
                    doctor_id=d.id,
                    name=d.name,
                    department_ids=tuple(self.doctor_departments.get(d.id, [])),
                    name_variants=tuple(d.name_variants or ()),
                    localized_names=tuple((d.localized_names or {}).values()),
                    active=d.active and d.booking_policy != "NO_OPD",
                    booking_policy=d.booking_policy,
                )
                for d in self.doctors.values()
            ),
            departments=tuple(
                DepartmentEntry(
                    department_id=d.id,
                    name=d.name,
                    code=d.code,
                    localized_names=tuple((d.localized_names or {}).values()),
                    has_consultant=d.has_consultant,
                    active=d.active,
                )
                for d in self.departments.values()
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
    doctors = {d.id: d for d in (await session.scalars(select(t.Doctor))).all()}
    departments = {d.id: d for d in (await session.scalars(select(t.Department))).all()}
    links: dict[str, list[str]] = {}
    for row in await session.scalars(
        select(t.DoctorDepartment).order_by(t.DoctorDepartment.doctor_id, t.DoctorDepartment.position)
    ):
        links.setdefault(row.doctor_id, []).append(row.department_id)
    query = select(t.LexiconEntry)
    if approved_lexicon_only:
        query = query.where(t.LexiconEntry.approved.is_(True))
    lexicon = list((await session.scalars(query)).all())
    return DirectorySnapshot(doctors, departments, links, lexicon)


# ---------------------------------------------------------------- departments


async def list_departments(session: AsyncSession) -> tuple[s.DepartmentList, str]:
    rows = (await session.scalars(select(t.Department).order_by(t.Department.name))).all()
    body = s.DepartmentList(items=[views.department(r) for r in rows])
    etag = hashlib.sha256(
        json.dumps(body.model_dump(mode="json", by_alias=True), sort_keys=True).encode()
    ).hexdigest()[:32]
    return body, f'"{etag}"'


# ---------------------------------------------------------------- doctors


def _slug(name: str) -> str:
    base = normalise(name, strip_honorifics=True)
    return re.sub(r"[^a-z0-9]+", "_", base).strip("_")[:40] or "doctor"


async def _doctor_departments(session: AsyncSession, doctor_id: str) -> list[t.Department]:
    rows = await session.execute(
        select(t.Department)
        .join(t.DoctorDepartment, t.DoctorDepartment.department_id == t.Department.id)
        .where(t.DoctorDepartment.doctor_id == doctor_id)
        .order_by(t.DoctorDepartment.position)
    )
    return list(rows.scalars())


async def list_doctors(
    session: AsyncSession, *, department: str | None, active: bool | None, limit: int, offset: int
) -> s.DoctorPage:
    query = select(t.Doctor)
    if active is not None:
        query = query.where(t.Doctor.active.is_(active))
    if department:
        wanted = department.casefold()
        dept_ids = [
            d.id
            for d in (await session.scalars(select(t.Department))).all()
            if wanted in {d.id.casefold(), (d.code or "").casefold(), d.name.casefold()}
        ]
        query = query.where(
            t.Doctor.id.in_(
                select(t.DoctorDepartment.doctor_id).where(t.DoctorDepartment.department_id.in_(dept_ids))
            )
        )
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (await session.scalars(query.order_by(t.Doctor.name).limit(limit).offset(offset))).all()
    items = [views.doctor(r, await _doctor_departments(session, r.id)) for r in rows]
    return s.DoctorPage(items=items, total=total)


async def get_doctor(session: AsyncSession, doctor_id: str) -> s.Doctor:
    row = await session.get(t.Doctor, doctor_id)
    if row is None:
        raise not_found("No such doctor.")
    return views.doctor(row, await _doctor_departments(session, doctor_id))


def _apply_doctor(row: t.Doctor, body: s.DoctorInput, currency: str) -> None:
    row.name = body.name
    row.localized_names = body.localized_names or {}
    row.name_variants = body.name_variants or []
    row.gender = body.gender.value if body.gender else None
    row.qualification = body.qualification
    row.years_of_experience = body.years_of_experience
    row.languages_spoken = body.languages_spoken or []
    if body.fee is not None:
        row.fee_amount = Decimal(str(body.fee.amount))
        row.fee_currency = body.fee.currency or currency
        row.fee_confirmed = body.fee.confirmed
    else:
        row.fee_amount, row.fee_currency, row.fee_confirmed = None, None, False
    row.attendance_type = body.attendance_type or "REGULAR"
    row.booking_policy = body.booking_policy or "BOOKABLE"
    row.data_confirmed = bool(body.data_confirmed)
    row.active = True if body.active is None else body.active


async def _set_departments(session: AsyncSession, doctor_id: str, department_ids: list[str]) -> None:
    known = set((await session.scalars(select(t.Department.id).where(t.Department.id.in_(department_ids)))).all())
    unknown = [d for d in department_ids if d not in known]
    if unknown:
        raise validation(f"Unknown department: {', '.join(unknown)}.", "departmentIds")
    await session.execute(delete(t.DoctorDepartment).where(t.DoctorDepartment.doctor_id == doctor_id))
    for position, dept_id in enumerate(dict.fromkeys(department_ids)):
        session.add(t.DoctorDepartment(doctor_id=doctor_id, department_id=dept_id, position=position))


async def create_doctor(session: AsyncSession, body: s.DoctorInput, currency: str) -> s.Doctor:
    base = f"doc_{_slug(body.name)}"
    doctor_id, n = base, 1
    while await session.get(t.Doctor, doctor_id) is not None:
        n += 1
        doctor_id = f"{base}_{n}"
    row = t.Doctor(id=doctor_id)
    _apply_doctor(row, body, currency)
    session.add(row)
    await session.flush()
    await _set_departments(session, doctor_id, body.department_ids)
    await session.commit()
    return await get_doctor(session, doctor_id)


async def update_doctor(session: AsyncSession, doctor_id: str, body: s.DoctorInput, currency: str) -> s.Doctor:
    row = await session.get(t.Doctor, doctor_id)
    if row is None:
        raise not_found("No such doctor.")
    _apply_doctor(row, body, currency)
    await _set_departments(session, doctor_id, body.department_ids)
    await session.commit()
    return await get_doctor(session, doctor_id)


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
    if concept_type in ("DEPARTMENT", "SYMPTOM_ROUTE"):
        ok = await session.get(t.Department, concept_id) is not None
    elif concept_type == "DOCTOR":
        ok = await session.get(t.Doctor, concept_id) is not None
    elif concept_type == "DAY_PART":
        ok = concept_id in _DAY_PARTS
    elif concept_type == "SERVICE_TRANSFER":
        ok = concept_id in transfers
    else:  # RED_FLAG: the concept id is a free label; the action is always emergency transfer.
        ok = True
    if not ok:
        raise validation(f"conceptId {concept_id!r} does not exist for {concept_type}.", "conceptId")


async def upsert_lexicon(
    session: AsyncSession, body: s.LexiconEntryInput, transfers: dict[str, str], *, source: str = "HOSPITAL"
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
    await session.commit()
    return _lexicon_model(row)

