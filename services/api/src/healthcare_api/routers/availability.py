"""Computed availability for staff and web (tag `Availability`)."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from .. import schemas as s
from ..auth import require_scopes
from ..errors import validation
from ..services import search
from .deps import Session, SettingsDep, errors, respond

router = APIRouter(tags=["Availability"], dependencies=[Depends(require_scopes())])
MAX_DAYS = 62


@router.get("/availability", operation_id="getAvailability",
            summary="Materialised sessions with slots for a doctor or department over a date range",
            response_model=s.AvailabilityList, responses=errors(400, 401))
async def get_availability(
    session: Session,
    settings: SettingsDep,
    date_from: Annotated[date, Query(alias="from")],
    date_to: Annotated[date, Query(alias="to")],
    doctor_id: Annotated[str | None, Query(alias="doctorId")] = None,
    department: str | None = None,
    include_slots: Annotated[bool, Query(alias="includeSlots")] = True,
):
    if date_to < date_from:
        raise validation("to must not be before from.", "to")
    if (date_to - date_from).days >= MAX_DAYS:
        raise validation(f"A range may span at most {MAX_DAYS} days.", "to")
    return respond(await search.staff_availability(
        session, settings, doctor_id=doctor_id, department=department,
        date_from=date_from, date_to=date_to, include_slots=include_slots,
    ))
