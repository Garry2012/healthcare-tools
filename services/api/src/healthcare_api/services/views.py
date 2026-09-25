"""Mapping from rows and engine views to wire models."""

from __future__ import annotations

from datetime import time

from .. import schemas as s
from ..db import tables as t
from ..domain.availability import SessionView, SlotView


def clock(value: time | None) -> str | None:
    return value.strftime("%H:%M") if value is not None else None


def slot(view: SlotView) -> s.Slot:
    window = None
    if view.kind == "SEQUENCE":
        window = s.Window(from_=clock(view.window_from), to=clock(view.window_to))
    return s.Slot(
        slot_id=view.slot_id,
        kind=view.kind,
        position=view.position,
        start=clock(view.start),
        end=clock(view.end),
        expected_window=window,
        available=view.available,
    )


def session_instance(
    view: SessionView, *, include_slots: bool = True, max_slots: int | None = None,
    only_available: bool = False,
) -> s.SessionInstance:
    slots = None
    if include_slots:
        chosen = [v for v in view.slots if v.available] if only_available else list(view.slots)
        if max_slots is not None:
            chosen = chosen[:max_slots]
        slots = [slot(v) for v in chosen]
    return s.SessionInstance(
        session_id=view.session_id,
        doctor_id=view.doctor_id,
        template_session_id=view.template_session_id,
        date=view.date,
        label=view.label,
        start=clock(view.start),
        end=clock(view.end),
        status=view.status,
        timing_certainty=view.timing_certainty,
        presence=view.presence,
        expected_start=clock(view.expected_start),
        delay_minutes=view.delay_minutes,
        capacity_model=view.capacity_model,
        capacity=s.SessionCapacity(
            total=view.total,
            booked=view.booked,
            remaining=view.remaining,
            walk_in_reserve=view.walk_in_reserve,
            capacity_source=view.capacity_source,
        ),
        arrive_by=clock(view.arrive_by),
        bookable=view.bookable,
        not_bookable_reason=view.not_bookable_reason,
        slots=slots,
    )


def department(row: t.Department) -> s.Department:
    return s.Department(
        id=row.id,
        code=row.code,
        name=row.name,
        localized_names=row.localized_names or None,
        has_consultant=row.has_consultant,
        active=row.active,
    )


def money(row: t.Doctor) -> s.Money | None:
    if row.fee_amount is None:
        return None
    return s.Money(
        amount=float(row.fee_amount),
        currency=row.fee_currency or "",
        confirmed=row.fee_confirmed,
    )


def doctor(row: t.Doctor, departments: list[t.Department]) -> s.Doctor:
    return s.Doctor(
        id=row.id,
        name=row.name,
        localized_names=row.localized_names or None,
        name_variants=row.name_variants or None,
        gender=row.gender,
        departments=[department(d) for d in departments],
        qualification=row.qualification,
        years_of_experience=row.years_of_experience,
        languages_spoken=row.languages_spoken or None,
        fee=money(row),
        attendance_type=row.attendance_type,
        booking_policy=row.booking_policy,
        data_confirmed=row.data_confirmed,
        active=row.active,
    )


def result_doctor(row: t.Doctor, departments: list[t.Department]) -> s.ResultDoctor:
    return s.ResultDoctor(
        doctor_id=row.id,
        name=row.name,
        localized_names=row.localized_names or None,
        departments=[department(d) for d in departments],
        gender=row.gender,
        qualification=row.qualification,
        fee=money(row),
        data_confirmed=row.data_confirmed,
    )
