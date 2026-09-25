"""Booking, lookup, cancel, reschedule — agent and desk paths.

Slot uniqueness is enforced by the partial unique index `uq_appointments_live_slot`:
booking is `INSERT … ON CONFLICT DO NOTHING`, rescheduling is an UPDATE inside a savepoint.
The availability check before the write is for a good error message, not for safety.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import date, time

from sqlalchemy import func, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import schemas as s
from ..config import Settings
from ..db import tables as t
from ..domain import ids
from ..domain.availability import SessionView, SlotView, find_session
from ..domain.identity import (
    BookingIdentity,
    name_matches,
    national_number,
    number_matches,
    patients_on,
)
from ..domain.text import normalise_person_name
from ..errors import ApiError, not_found, validation
from . import schedule, views

LISTED_STATUSES = ("BOOKED", "CONFIRMED_BY_DESK", "RESCHEDULED", "NEEDS_RESCHEDULE", "ARRIVED")
CHANGEABLE_STATUSES = ("BOOKED", "CONFIRMED_BY_DESK", "RESCHEDULED", "NEEDS_RESCHEDULE")
_LIVE_WHERE = text(t.LIVE_SQL)


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


def _code() -> str:
    return f"{secrets.randbelow(10_000):04d}"


def _identity(row: t.Appointment) -> BookingIdentity:
    return BookingIdentity(row.id, row.patient_name, row.phone, row.caller_number)


def _history(session: AsyncSession, appointment_id: str, by: str, change: str, **details) -> None:
    session.add(t.AppointmentHistory(appointment_id=appointment_id, by=by, change=change, details=details))


# ---------------------------------------------------------------- views


def _slot_from_id(slot_id: str) -> SlotView:
    ref = ids.parse_slot_id(slot_id)
    suffix = ref.suffix if ref else ""
    # Positions are written with two or three digits, TIMED slots as HHMM.
    if len(suffix) == 4 and int(suffix[:2]) < 24 and int(suffix[2:]) < 60:
        at = time(int(suffix[:2]), int(suffix[2:]))
        return SlotView(slot_id=slot_id, kind="TIMED", available=False, start=at)
    return SlotView(slot_id=slot_id, kind="SEQUENCE", available=False,
                    position=int(suffix) if suffix.isdigit() else None)


def _slot_in(view: SessionView | None, slot_id: str) -> SlotView:
    if view is not None:
        for slot in view.slots:
            if slot.slot_id == slot_id:
                return slot
    return _slot_from_id(slot_id)


@dataclass(slots=True)
class Context:
    """Everything needed to describe appointments without further queries."""

    data: schedule.ScheduleData
    departments: dict[str, t.Department]

    def session_view(self, row: t.Appointment) -> SessionView | None:
        if row.doctor_id not in self.data.doctors:
            return None
        return find_session(self.data.sessions(row.doctor_id, row.date, channel="DESK"), row.session_id)


async def context_for(
    session: AsyncSession, settings: Settings, rows: list[t.Appointment]
) -> Context:
    now = schedule.now_in(settings)
    if rows:
        first, last = min(r.date for r in rows), max(r.date for r in rows)
        first = min(first, now.date())
        last = max(last, now.date())
    else:
        first = last = now.date()
    data = await schedule.load(session, settings, now, {r.doctor_id for r in rows}, first, last)
    departments = {d.id: d for d in (await session.scalars(select(t.Department))).all()}
    return Context(data, departments)


def _certainty(row: t.Appointment, view: SessionView | None) -> str:
    if row.timing_confirmed:
        return "CONFIRMED"
    return view.timing_certainty if view else "EXPECTED"


def agent_view(
    row: t.Appointment, ctx: Context, outcome: str, *, previous_slot: SlotView | None = None,
    with_today: bool = False,
) -> s.AgentAppointment:
    view = ctx.session_view(row)
    doctor = ctx.data.doctors.get(row.doctor_id)
    dept = ctx.departments.get(row.department_id or "")
    today = ctx.data.now.date()
    return s.AgentAppointment(
        outcome=outcome,
        appointment_id=row.id,
        confirmation_code=row.confirmation_code,
        status=row.status,
        patient=s.PatientSummary(name=row.patient_name, phone=row.phone),
        doctor=s.DoctorSummary(
            doctor_id=row.doctor_id,
            name=doctor.name if doctor else None,
            localized_names=(doctor.localized_names or None) if doctor else None,
        ),
        department=views.department(dept) if dept else None,
        date=row.date,
        session=s.SessionSummary(
            session_id=row.session_id,
            label=view.label if view else None,
            start=views.clock(view.start) if view else None,
            end=views.clock(view.end) if view else None,
        ),
        slot=views.slot(_slot_in(view, row.slot_id)),
        previous_slot=views.slot(previous_slot) if previous_slot else None,
        arrive_by=views.clock(view.arrive_by) if view else None,
        timing_certainty=_certainty(row, view),
        fee=views.money(doctor) if doctor else None,
        follow_up=row.follow_up,
        doctor_today=(
            views.session_instance(view, include_slots=False)
            if with_today and view is not None and row.date == today else None
        ),
    )


def staff_view(row: t.Appointment, ctx: Context, history: list[t.AppointmentHistory]) -> s.Appointment:
    view = ctx.session_view(row)
    return s.Appointment(
        id=row.id,
        confirmation_code=row.confirmation_code,
        status=row.status,
        patient=s.AppointmentPatient(
            name=row.patient_name, phone=row.phone, relation_to_caller=row.relation_to_caller
        ),
        caller_number=row.caller_number,
        doctor_id=row.doctor_id,
        session_id=row.session_id,
        slot_id=row.slot_id,
        date=row.date,
        slot=views.slot(_slot_in(view, row.slot_id)),
        arrive_by=views.clock(view.arrive_by) if view else None,
        timing_certainty=_certainty(row, view),
        confirmed_start=views.clock(row.confirmed_start),
        reason_verbatim=row.reason_verbatim,
        language=row.language,
        created_via=row.created_via,
        call_id=row.call_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        history=[s.HistoryItem(at=h.at, by=h.by, change=h.change) for h in history],
    )


async def history_of(session: AsyncSession, appointment_ids: list[str]) -> dict[str, list[t.AppointmentHistory]]:
    out: dict[str, list[t.AppointmentHistory]] = {a: [] for a in appointment_ids}
    if appointment_ids:
        rows = await session.scalars(
            select(t.AppointmentHistory)
            .where(t.AppointmentHistory.appointment_id.in_(appointment_ids))
            .order_by(t.AppointmentHistory.id)
        )
        for h in rows:
            out[h.appointment_id].append(h)
    return out


# ---------------------------------------------------------------- slot checks


@dataclass(slots=True)
class SlotCheck:
    ref: ids.SlotRef
    data: schedule.ScheduleData
    view: SessionView | None
    slot: SlotView | None


async def _check_slot(
    session: AsyncSession, settings: Settings, slot_id: str, channel: str
) -> SlotCheck:
    ref = ids.parse_slot_id(slot_id)
    if ref is None:
        raise validation("slotId is not a slot id returned by availability search.", "slotId")
    now = schedule.now_in(settings)
    data = await schedule.load(session, settings, now, [ref.session.doctor_id], ref.session.date, ref.session.date)
    if ref.session.doctor_id not in data.doctors:
        return SlotCheck(ref, data, None, None)
    view = find_session(data.sessions(ref.session.doctor_id, ref.session.date, channel=channel),
                        ref.session.session_id)
    slot = next((x for x in view.slots if x.slot_id == slot_id), None) if view else None
    return SlotCheck(ref, data, view, slot)


def _current_slots(view: SessionView | None) -> list[dict]:
    if view is None or not view.bookable:
        return []
    return [views.slot(x).model_dump(mode="json", by_alias=True, exclude_none=True)
            for x in view.available_slots()]


def _slot_unavailable(view: SessionView | None, message: str = "That slot is no longer available.") -> ApiError:
    return ApiError("SLOT_UNAVAILABLE", message, current_slots=_current_slots(view))


async def _recheck(session: AsyncSession, settings: Settings, slot_id: str, channel: str) -> ApiError:
    check = await _check_slot(session, settings, slot_id, channel)
    return _slot_unavailable(check.view)


# ---------------------------------------------------------------- booking


@dataclass(slots=True)
class Booked:
    row: t.Appointment
    created: bool


async def book(
    session: AsyncSession,
    settings: Settings,
    body: s.AgentBookRequest,
    *,
    channel: str,
    call_id: str | None,
    caller_number: str | None,
    actor: str,
) -> Booked:
    if not re.fullmatch(settings.tenant_phone_pattern, body.patient.phone):
        raise validation("patient.phone does not match the facility's phone format.", "patient.phone")
    check = await _check_slot(session, settings, body.slot_id, channel)
    if check.view is None or check.slot is None:
        raise _slot_unavailable(check.view, "That slot does not exist in the current schedule.")

    name_key = normalise_person_name(body.patient.name)
    existing = await session.scalar(
        select(t.Appointment).where(
            t.Appointment.session_id == check.view.session_id,
            t.Appointment.patient_name_normalized == name_key,
            t.Appointment.phone == body.patient.phone,
            t.Appointment.status.in_(t.LIVE_STATUSES),
        )
    )
    if existing is not None:
        return Booked(existing, created=False)

    if not check.view.bookable or not check.slot.available:
        raise _slot_unavailable(check.view)

    doctor = check.data.doctors[check.ref.session.doctor_id]
    department_id = await session.scalar(
        select(t.DoctorDepartment.department_id)
        .where(t.DoctorDepartment.doctor_id == doctor.id)
        .order_by(t.DoctorDepartment.position)
        .limit(1)
    )
    follow_up = (
        "DESK_WILL_CONFIRM_TIMING"
        if body.request_timing_confirmation
        and settings.tenant_desk_follow_up_list_enabled
        and check.view.timing_certainty == "NOT_CONFIRMED"
        else "NONE"
    )
    appointment_id = new_id("appt")
    inserted = await session.scalar(
        insert(t.Appointment)
        .values(
            id=appointment_id,
            confirmation_code=_code(),
            status="BOOKED",
            patient_name=body.patient.name.strip(),
            patient_name_normalized=name_key,
            phone=body.patient.phone,
            relation_to_caller=body.patient.relation_to_caller,
            caller_number=caller_number,
            doctor_id=doctor.id,
            department_id=department_id,
            session_id=check.view.session_id,
            slot_id=body.slot_id,
            date=check.view.date,
            reason_verbatim=body.reason_verbatim,
            language=body.language,
            created_via="AGENT" if channel == "AGENT" else "DESK",
            call_id=call_id,
            follow_up=follow_up,
        )
        .on_conflict_do_nothing(index_elements=["slot_id"], index_where=_LIVE_WHERE)
        .returning(t.Appointment.id)
    )
    if inserted is None:
        raise await _recheck(session, settings, body.slot_id, channel)
    _history(session, appointment_id, actor, "BOOKED", slotId=body.slot_id)
    await session.flush()
    row = await session.get(t.Appointment, appointment_id)
    assert row is not None
    return Booked(row, created=True)


# ---------------------------------------------------------------- agent lookup / changes


async def agent_list(
    session: AsyncSession,
    settings: Settings,
    *,
    caller_number: str | None,
    patient_name: str | None,
    phone: str | None,
    date_from: date | None,
    date_to: date | None,
) -> s.AgentAppointmentList:
    if not caller_number and not phone:
        return s.AgentAppointmentList(
            outcome="IDENTITY_UNAVAILABLE", items=[], patients_on_number=0, identity_basis="NONE"
        )
    basis = "CALLER_NUMBER" if caller_number else "SPOKEN_NUMBER"
    today = schedule.now_in(settings).date()
    numbers = []
    if caller_number:
        numbers.append(national_number(caller_number, settings.tenant_country_calling_code))
    if phone:
        numbers.append(phone)
    reachable = [t.Appointment.phone.in_(numbers)]
    if caller_number:
        reachable.append(t.Appointment.caller_number == caller_number)
    query = select(t.Appointment).where(
        t.Appointment.status.in_(LISTED_STATUSES),
        t.Appointment.date >= (date_from or today),
        or_(*reachable),
    )
    if date_to:
        query = query.where(t.Appointment.date <= date_to)
    rows = [
        r for r in (await session.scalars(query.order_by(t.Appointment.date, t.Appointment.slot_id))).all()
        if number_matches(_identity(r), caller_number=caller_number, spoken_phone=phone,
                          country_code=settings.tenant_country_calling_code)
    ]
    patients = patients_on(_identity(r) for r in rows)
    if patient_name:
        rows = [r for r in rows if name_matches(_identity(r), patient_name)]
    elif patients > 1:
        return s.AgentAppointmentList(
            outcome="NAME_REQUIRED", items=[], patients_on_number=patients, identity_basis=basis
        )
    ctx = await context_for(session, settings, rows)
    items = [agent_view(r, ctx, "FOUND", with_today=True) for r in rows]
    return s.AgentAppointmentList(
        outcome="FOUND" if items else "NONE_FOUND",
        items=items,
        patients_on_number=patients,
        identity_basis=basis,
    )


async def _locate(
    session: AsyncSession, settings: Settings, appointment_id: str, patient_name: str,
    caller_number: str | None,
) -> t.Appointment:
    """Neutral 404 for missing, not-yours and wrong-name alike."""
    row = await session.get(t.Appointment, appointment_id, with_for_update=True)
    if row is None or not caller_number:
        raise not_found()
    identity = _identity(row)
    if not number_matches(identity, caller_number=caller_number, spoken_phone=None,
                          country_code=settings.tenant_country_calling_code):
        raise not_found()
    if not name_matches(identity, patient_name):
        raise not_found()
    return row


async def cancel(
    session: AsyncSession, settings: Settings, appointment_id: str, body: s.CancelRequest,
    *, caller_number: str | None, actor: str,
) -> t.Appointment:
    row = await _locate(session, settings, appointment_id, body.patient_name, caller_number)
    if row.status not in CHANGEABLE_STATUSES:
        raise ApiError("CONFLICT", "This appointment can no longer be cancelled.")
    previous = row.status
    row.status = "CANCELLED_BY_PATIENT"
    _history(session, row.id, actor, "CANCELLED_BY_PATIENT", previous=previous,
             reasonProvided=bool(body.reason_verbatim))
    await session.flush()
    return row


async def _move(
    session: AsyncSession, settings: Settings, row: t.Appointment, new_slot_id: str, *,
    channel: str, actor: str, status: str,
) -> SlotView:
    """Release the old slot and take the new one atomically, or change nothing."""
    if new_slot_id == row.slot_id:
        raise ApiError("CONFLICT", "The appointment already holds that slot.")
    old_check = await _check_slot(session, settings, row.slot_id, "DESK")
    previous = _slot_in(old_check.view, row.slot_id)
    check = await _check_slot(session, settings, new_slot_id, channel)
    if check.view is None or check.slot is None or not check.view.bookable or not check.slot.available:
        raise _slot_unavailable(check.view)
    department_id = await session.scalar(
        select(t.DoctorDepartment.department_id)
        .where(t.DoctorDepartment.doctor_id == check.ref.session.doctor_id)
        .order_by(t.DoctorDepartment.position)
        .limit(1)
    )
    old_slot = row.slot_id
    try:
        async with session.begin_nested():
            row.slot_id = new_slot_id
            row.session_id = check.view.session_id
            row.doctor_id = check.ref.session.doctor_id
            row.department_id = department_id
            row.date = check.view.date
            row.status = status
            row.timing_confirmed = False
            row.confirmed_start = None
            row.follow_up = "NONE"
            row.impacted_by_exception_id = None
            await session.flush()
    except IntegrityError:
        # The savepoint rolled back; the appointment still holds its original slot.
        await session.refresh(row)
        raise await _recheck(session, settings, new_slot_id, channel) from None
    _history(session, row.id, actor, "RESCHEDULED", fromSlot=old_slot, toSlot=new_slot_id)
    await session.flush()
    return previous


async def reschedule(
    session: AsyncSession, settings: Settings, appointment_id: str, body: s.RescheduleRequest,
    *, caller_number: str | None, actor: str,
) -> tuple[t.Appointment, SlotView]:
    row = await _locate(session, settings, appointment_id, body.patient_name, caller_number)
    if row.status not in CHANGEABLE_STATUSES:
        raise ApiError("CONFLICT", "This appointment can no longer be moved.")
    if ids.parse_slot_id(body.new_slot_id) is None:
        raise validation("newSlotId is not a slot id returned by availability search.", "newSlotId")
    previous = await _move(session, settings, row, body.new_slot_id, channel="AGENT", actor=actor,
                           status="RESCHEDULED")
    return row, previous


# ---------------------------------------------------------------- staff


async def search(
    session: AsyncSession, *, doctor_id: str | None, session_id: str | None, on: date | None,
    phone: str | None, status: str | None, limit: int, offset: int,
) -> tuple[list[t.Appointment], int]:
    query = select(t.Appointment)
    if doctor_id:
        query = query.where(t.Appointment.doctor_id == doctor_id)
    if session_id:
        query = query.where(t.Appointment.session_id == session_id)
    if on:
        query = query.where(t.Appointment.date == on)
    if phone:
        query = query.where(t.Appointment.phone == phone)
    if status:
        query = query.where(t.Appointment.status == status)
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (
        await session.scalars(
            query.order_by(t.Appointment.date, t.Appointment.slot_id).limit(limit).offset(offset)
        )
    ).all()
    return list(rows), total


async def get(session: AsyncSession, appointment_id: str, *, lock: bool = False) -> t.Appointment:
    row = await session.get(t.Appointment, appointment_id, with_for_update=lock)
    if row is None:
        raise not_found("No such appointment.")
    return row


_STAFF_TRANSITIONS = {
    "ARRIVED": ("BOOKED", "CONFIRMED_BY_DESK", "RESCHEDULED"),
    "COMPLETED": ("BOOKED", "CONFIRMED_BY_DESK", "RESCHEDULED", "ARRIVED"),
    "NO_SHOW": ("BOOKED", "CONFIRMED_BY_DESK", "RESCHEDULED"),
    "CANCELLED_BY_HOSPITAL": CHANGEABLE_STATUSES,
}


async def set_status(
    session: AsyncSession, appointment_id: str, body: s.StatusRequest, actor: str
) -> t.Appointment:
    row = await get(session, appointment_id, lock=True)
    if row.status not in _STAFF_TRANSITIONS[body.status]:
        raise ApiError("CONFLICT", f"Cannot move an appointment from {row.status} to {body.status}.")
    previous = row.status
    row.status = body.status
    _history(session, row.id, actor, body.status, previous=previous, note=body.note)
    await session.flush()
    return row
