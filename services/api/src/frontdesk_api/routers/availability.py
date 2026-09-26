"""Computed availability for staff and web (tag `Availability`)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from .. import schemas as s
from ..auth import require_scopes
from ..errors import validation
from ..services import search
from .deps import ApiDate, Session, SettingsDep, errors, respond

router = APIRouter(tags=["Availability"], dependencies=[Depends(require_scopes())])
MAX_DAYS = 62


@router.get("/availability", operation_id="getAvailability",
            summary="Materialised sessions with slots for a resource or category over a date range",
            response_model=s.AvailabilityList, responses=errors(400, 401))
async def get_availability(
    request: Request,
    session: Session,
    settings: SettingsDep,
    date_from: Annotated[ApiDate, Query(alias="from")],
    date_to: Annotated[ApiDate, Query(alias="to")],
    resource_id: Annotated[str | None, Query(alias="resourceId")] = None,
    category: str | None = None,
    include_slots: Annotated[bool, Query(alias="includeSlots")] = True,
):
    if date_to < date_from:
        raise validation("to must not be before from.", "to")
    if (date_to - date_from).days >= MAX_DAYS:
        raise validation(f"A range may span at most {MAX_DAYS} days.", "to")
    return respond(await search.staff_availability(
        session, settings, resource_id=resource_id, category=category,
        date_from=date_from, date_to=date_to, include_slots=include_slots,
        directory_cache=request.app.state.directory_cache,
    ))
