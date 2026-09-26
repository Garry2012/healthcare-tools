"""Call summaries for the admin UI (tag `Calls`)."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from .. import schemas as s
from ..auth import require_scopes
from ..services import calls as svc
from .deps import Session, SettingsDep, errors, respond

router = APIRouter(tags=["Calls"])


@router.post("/call-summaries", operation_id="storeCallSummary",
             summary="Voice platform posts a summary when a call ends", status_code=201,
             response_model=s.CallSummary,
             responses={200: {"model": s.CallSummary, "description": "Same callId already stored."},
                        **errors(400)},
             dependencies=[Depends(require_scopes("calls.write"))])
async def store_call_summary(body: s.CallSummary, session: Session):
    stored, created = await svc.store(session, body)
    return respond(stored, 201 if created else 200)


@router.get("/call-summaries", operation_id="listCallSummaries", summary="Admin UI listing",
            response_model=s.CallSummaryPage, responses=errors(403),
            dependencies=[Depends(require_scopes("calls.read"))])
async def list_call_summaries(
    session: Session,
    settings: SettingsDep,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return respond(await svc.page(session, settings, date_from=date_from, date_to=date_to,
                                  limit=limit, offset=offset))
