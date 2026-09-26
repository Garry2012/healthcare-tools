"""Mapping from rows and engine views to wire models."""

from __future__ import annotations

from datetime import time

from .. import schemas as s
from ..db import tables as t
from ..domain.availability import SessionView, SlotView


def time_of(value: str | None) -> time | None:
    """The inverse of `clock`: an "HH:MM" string from a request as a `time`."""
    return time.fromisoformat(value) if value else None


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
        resource_id=view.resource_id,
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


def category(row: t.Category) -> s.Category:
    return s.Category(
        id=row.id,
        code=row.code,
        name=row.name,
        localized_names=row.localized_names or None,
        offers_bookings=row.offers_bookings,
        active=row.active,
    )


def money(row: t.Resource) -> s.Money | None:
    if row.price_amount is None:
        return None
    return s.Money(
        amount=float(row.price_amount),
        currency=row.price_currency or "",
        confirmed=row.price_confirmed,
    )


def spoken_money(row: t.Resource) -> s.Money | None:
    """What the voice agent may see: a fee only once the provider has confirmed it."""
    return money(row) if row.price_confirmed else None


def resource(row: t.Resource, categories: list[t.Category]) -> s.Resource:
    return s.Resource(
        id=row.id,
        name=row.name,
        localized_names=row.localized_names or None,
        name_variants=row.name_variants or None,
        gender=row.gender,
        categories=[category(d) for d in categories],
        attributes=row.attributes or None,
        languages_spoken=row.languages_spoken or None,
        price=money(row),
        attendance_type=row.attendance_type,
        booking_policy=row.booking_policy,
        data_confirmed=row.data_confirmed,
        active=row.active,
    )


def result_resource(row: t.Resource, categories: list[t.Category]) -> s.ResultResource:
    return s.ResultResource(
        resource_id=row.id,
        name=row.name,
        localized_names=row.localized_names or None,
        categories=[category(d) for d in categories],
        gender=row.gender,
        attributes=row.attributes or None,
        price=spoken_money(row),
        data_confirmed=row.data_confirmed,
    )
