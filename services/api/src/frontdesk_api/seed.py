"""`frontdesk-api seed` — synthetic demo data, idempotent, relative to the run date.

Directory rows (departments, doctors, templates, lexicon) are upserted every run.
Date-specific data (bookings, exceptions, board) is created once; a second run leaves it
alone. `--reset` empties every table first (destructive) so the demo can be re-dated.
Bookings and exceptions go through the same services the API uses, so the surgery
exception really does move its patients to NEEDS_RESCHEDULE and queue notifications.
"""

from __future__ import annotations

import logging
from datetime import date, time, timedelta
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import schemas as s
from . import seed_data as data
from .config import Settings
from .db import tables as t
from .db.session import make_engine, make_sessionmaker
from .domain.text import normalise
from .logging import configure_logging, log_event
from .services import appointments, directory, schedule, scheduling
from .services.idempotency import run as idempotent

logger = logging.getLogger(__name__)
TEMPLATE_FROM = date(2020, 1, 1)
SEED_ACTOR = "seed"
# Children before parents. `--reset` empties all of them: a demo database returns to exactly
# the seed state, whatever was written through the API in between.
ALL_TABLES = (
    t.Notification, t.AppointmentHistory, t.Appointment, t.ScheduleException, t.BoardEntry,
    t.IdempotencyKey, t.CallSummary, t.LexiconEntry, t.TemplateSession, t.ScheduleTemplate,
    t.DoctorDepartment, t.Doctor, t.Department,
)


def _next(today: date, weekday: int, *, include_today: bool) -> date:
    ahead = (weekday - today.weekday()) % 7
    if ahead == 0 and not include_today:
        ahead = 7
    return today + timedelta(days=ahead)


async def _upsert_directory(session: AsyncSession, settings: Settings) -> None:
    for d in data.DEPARTMENTS:
        row = await session.get(t.Department, d.id) or t.Department(id=d.id)
        row.code, row.name, row.localized_names = d.code, d.name, {"kn": d.kn, "hi": d.hi}
        row.has_consultant, row.active = True, True
        session.add(row)
    await session.flush()

    for doc in data.DOCTORS:
        row = await session.get(t.Doctor, doc.id) or t.Doctor(id=doc.id)
        row.name = doc.name
        row.localized_names = {k: v for k, v in (("kn", doc.kn), ("hi", doc.hi)) if v}
        row.name_variants = list(doc.variants)
        row.gender = doc.gender
        row.qualification = doc.qualification
        row.languages_spoken = ["en", "kn", "hi"]
        row.fee_amount = Decimal(doc.fee) if doc.fee is not None else None
        row.fee_currency = settings.tenant_currency if doc.fee is not None else None
        row.fee_confirmed = doc.fee_confirmed and doc.fee is not None
        row.attendance_type, row.booking_policy = doc.attendance, doc.policy
        row.data_confirmed, row.active = doc.data_confirmed, True
        session.add(row)
        await session.flush()
        await session.execute(delete(t.DoctorDepartment).where(t.DoctorDepartment.doctor_id == doc.id))
        for position, dept in enumerate(doc.departments):
            session.add(t.DoctorDepartment(doctor_id=doc.id, department_id=dept, position=position))

        template_id = f"tpl_{doc.id}_{TEMPLATE_FROM.isoformat()}"
        existing = await session.get(t.ScheduleTemplate, template_id)
        if existing is not None:
            await session.delete(existing)
            await session.flush()
        if doc.sessions:
            session.add(t.ScheduleTemplate(id=template_id, doctor_id=doc.id, effective_from=TEMPLATE_FROM,
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

    for concept_type, concept_id, term, language in data.LEXICON:
        entry_id = directory.lexicon_id(concept_type, concept_id, term, language)
        row = await session.get(t.LexiconEntry, entry_id) or t.LexiconEntry(
            id=entry_id, concept_type=concept_type, concept_id=concept_id, term=term, language=language,
        )
        row.term_normalized, row.approved, row.source = normalise(term), True, "HOSPITAL"
        session.add(row)
    await session.commit()


async def _book(session: AsyncSession, settings: Settings, slot_id: str, patient: data.Patient,
                *, channel: str = "AGENT") -> bool:
    body = s.AgentBookRequest(
        slot_id=slot_id,
        patient=s.BookPatient(name=patient.name, phone=patient.phone, relation_to_caller=patient.relation),
        reason_verbatim=patient.reason,
        language=patient.language,
    )

    async def operation() -> tuple[int, dict]:
        booked = await appointments.book(
            session, settings, body, channel=channel, call_id=f"seed-{slot_id}",
            caller_number=patient.caller if channel == "AGENT" else None, actor=SEED_ACTOR,
        )
        return 201, {"id": booked.row.id}

    await idempotent(session, None, "", operation)
    return True


async def _first_free(session: AsyncSession, settings: Settings, doctor_id: str, on: date,
                      session_n: str | None = None, skip: int = 0) -> list[str]:
    loaded = await schedule.load(session, settings, schedule.now_in(settings), [doctor_id], on, on)
    slots: list[str] = []
    for view in loaded.sessions(doctor_id, on):
        if session_n and not view.session_id.endswith(f"_{session_n}"):
            continue
        slots += [x.slot_id for x in view.available_slots()]
    return slots[skip:]


async def _seed_dynamic(session: AsyncSession, settings: Settings) -> dict[str, int]:
    now = schedule.now_in(settings)
    today = now.date()
    tomorrow = today + timedelta(days=1)
    next_thursday = _next(today, 3, include_today=False)
    next_sunday = _next(today, 6, include_today=False)
    pool = iter(data.POOL)
    booked = 0

    # 1. Three patients in Dr. Garima's afternoon on the coming Thursday; the surgery
    #    exception below removes that session, so these become the impacted patients.
    for slot in (await _first_free(session, settings, "doc_garima", next_thursday, "2"))[:3]:
        booked += await _book(session, settings, slot, next(pool))

    # 2. Two patients on one phone (mother and child), and a booking made from a
    #    different number than the patient's own.
    for patient, doctor in ((data.LAKSHMI, "doc_arjun_menon"), (data.AARAV, "doc_meera_kulkarni")):
        slots = await _first_free(session, settings, doctor, tomorrow)
        if slots:
            booked += await _book(session, settings, slots[0], patient)
    slots = await _first_free(session, settings, "doc_anil_sharma", _next(today, 0, include_today=False))
    if slots:
        booked += await _book(session, settings, slots[0], data.RAMESH)

    # 3. Spread the rest over the next seven days, a couple per doctor-day.
    spread = ("doc_garima", "doc_arjun_menon", "doc_meera_kulkarni", "doc_rohan_shetty", "doc_sunita_patil",
              "doc_kiran_hegde", "doc_ravi_sharma", "doc_priya_nair")
    for offset in range(7):
        day = today + timedelta(days=offset)
        for i, doctor in enumerate(spread):
            if booked >= 30 or (offset + i) % 3:
                continue
            for slot in (await _first_free(session, settings, doctor, day, skip=1))[:2]:
                patient = next(pool, None)
                if patient is None:
                    break
                booked += await _book(session, settings, slot, patient)

    # 4. Reality differs from the template.
    exceptions = [
        s.ScheduleExceptionInput(doctor_id="doc_garima", date_from=next_thursday, date_to=next_thursday,
                                 scope="SESSION", template_session_id="tpl_doc_garima_pm", effect="UNAVAILABLE",
                                 reason_category="SURGERY", note="Two surgeries (synthetic)"),
        s.ScheduleExceptionInput(doctor_id="doc_arjun_menon", date_from=today, date_to=today, scope="SESSION",
                                 template_session_id="tpl_doc_arjun_menon_eve", effect="TIME_CHANGE",
                                 new_start="18:00", new_end="20:00", reason_category="OTHER"),
        s.ScheduleExceptionInput(doctor_id="doc_garima", date_from=next_sunday, date_to=next_sunday,
                                 scope="TIME_RANGE", effect="EXTRA_SESSION", new_start="10:00", new_end="12:00",
                                 new_capacity=8, reason_category="OTHER"),
        s.ScheduleExceptionInput(doctor_id="doc_meera_kulkarni", date_from=tomorrow, date_to=tomorrow,
                                 scope="SESSION", template_session_id="tpl_doc_meera_kulkarni_pm",
                                 effect="TIMING_PENDING", reason_category="OTHER"),
    ]
    for body in exceptions:
        async def operation(body=body) -> tuple[int, dict]:
            created = await scheduling.create_exception(session, settings, body, SEED_ACTOR)
            return 201, {"id": created.id}

        await idempotent(session, None, "", operation)

    # 5. What the desk has marked on today's board.
    board = [
        ("doc_arjun_menon", "1", {"presence": "ARRIVING", "delay_minutes": 20, "expected_start": "10:20"}),
        ("doc_meera_kulkarni", "1", {"presence": "PRESENT", "tokens_issued": 7}),
        ("doc_rohan_shetty", "1", {"presence": "LEFT"}),
    ]
    for doctor_id, n, fields in board:
        entry = s.BoardEntryInput(date=today, session_id=f"ses_{doctor_id}_{today.isoformat()}_{n}", **fields)
        await scheduling.set_board(session, settings, doctor_id, entry, SEED_ACTOR)

    return {"appointments": booked, "exceptions": len(exceptions), "board": len(board)}


async def run(settings: Settings, *, reset: bool = False) -> dict[str, int]:
    configure_logging(settings.log_level)
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
            if already:
                summary = {"appointments": 0, "exceptions": 0, "board": 0}
                log_event(logger, logging.INFO, "seed_dynamic_skipped", reason="already seeded")
            else:
                summary = await _seed_dynamic(session, settings)
            log_event(logger, logging.INFO, "seed_complete", **summary,
                      doctors=len(data.DOCTORS), departments=len(data.DEPARTMENTS), lexicon=len(data.LEXICON))
            return summary
    finally:
        await engine.dispose()
