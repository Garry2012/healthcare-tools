"""Schedule templates, exceptions and the live board (tag `Scheduling`)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from .. import schemas as s
from ..auth import Principal, require_scopes
from ..services import idempotency as idem
from ..services import scheduling as svc
from .deps import ActingUser, ApiDate, IdempotencyKey, Session, SettingsDep, errors, respond

router = APIRouter(tags=["Scheduling"])


@router.get("/resources/{resourceId}/schedule-template", operation_id="getScheduleTemplate",
            summary="The resource's recurring sessions", response_model=s.ScheduleTemplate,
            responses=errors(404), dependencies=[Depends(require_scopes())])
async def get_schedule_template(resourceId: str, session: Session, settings: SettingsDep):  # noqa: N803
    return respond(await svc.get_template(session, settings, resourceId))


@router.put("/resources/{resourceId}/schedule-template", operation_id="setScheduleTemplate",
            summary="Replace the resource's recurring sessions (admin/desk)", response_model=s.ScheduleTemplate,
            responses=errors(400, 403, 404), dependencies=[Depends(require_scopes("schedule.write"))])
async def set_schedule_template(
    resourceId: str, body: s.ScheduleTemplate, acting_user: ActingUser,  # noqa: N803
    session: Session, settings: SettingsDep,
):
    return respond(await svc.set_template(session, settings, resourceId, body, acting_user))


@router.get("/schedule-exceptions", operation_id="listScheduleExceptions",
            summary="Known deviations from templates (leave, surgery, extra sessions)",
            response_model=s.ExceptionList, responses=errors(401))
async def list_schedule_exceptions(
    session: Session,
    principal: Annotated[Principal, Depends(require_scopes())],
    resource_id: Annotated[str | None, Query(alias="resourceId")] = None,
    date_from: Annotated[ApiDate | None, Query(alias="from")] = None,
    date_to: Annotated[ApiDate | None, Query(alias="to")] = None,
):
    return respond(await svc.list_exceptions(session, resource_id=resource_id, date_from=date_from,
                                             date_to=date_to, staff=principal.is_staff))


@router.post("/schedule-exceptions", operation_id="createScheduleException",
             summary="Record reality — today or any future date", status_code=201,
             response_model=s.ScheduleException, responses=errors(400, 403, 409),
             dependencies=[Depends(require_scopes("schedule.write"))])
async def create_schedule_exception(
    body: s.ScheduleExceptionInput, acting_user: ActingUser,
    session: Session, settings: SettingsDep,
    idempotency_key: IdempotencyKey = None,
):
    fingerprint = idem.request_hash("POST", "/schedule-exceptions", body.model_dump(mode="json"), acting_user)

    async def operation() -> tuple[int, dict]:
        created = await svc.create_exception(session, settings, body, acting_user)
        return 201, created.model_dump(mode="json", by_alias=True, exclude_none=True)

    outcome = await idem.run(session, idempotency_key, fingerprint, operation)
    return respond(outcome.body, outcome.status, {"Idempotent-Replay": "true"} if outcome.replay else None)


@router.delete("/schedule-exceptions/{exceptionId}", operation_id="deleteScheduleException",
               summary="Withdraw an exception (the resource is coming after all)", status_code=204,
               responses=errors(403, 404), dependencies=[Depends(require_scopes("schedule.write"))])
async def delete_schedule_exception(
    exceptionId: str, acting_user: ActingUser, session: Session, settings: SettingsDep,  # noqa: N803
):
    await svc.delete_exception(session, settings, exceptionId, acting_user)
    return Response(status_code=204)


@router.get("/schedule-exceptions/{exceptionId}/impact", operation_id="getScheduleExceptionImpact",
            summary="Bookings impacted by an exception, with notification state",
            response_model=s.ImpactList, responses=errors(403, 404),
            dependencies=[Depends(require_scopes("bookings.staff"))])
async def get_schedule_exception_impact(exceptionId: str, session: Session, settings: SettingsDep):  # noqa: N803
    return respond(await svc.impact_of(session, settings, exceptionId))


@router.get("/board/{resourceId}", operation_id="getBoard",
            summary="Live board for one resource on a date (right now facts)",
            response_model=s.BoardView, responses=errors(404))
async def get_board(
    resourceId: str,  # noqa: N803
    session: Session,
    settings: SettingsDep,
    principal: Annotated[Principal, Depends(require_scopes())],
    on: Annotated[ApiDate | None, Query(alias="date")] = None,
):
    return respond(await svc.get_board(session, settings, resourceId, on, staff=principal.is_staff))


@router.put("/board/{resourceId}", operation_id="setBoard",
            summary="Desk marks arrived / late / left / full for a session (today)",
            response_model=s.BoardEntry, responses=errors(400, 403, 404),
            dependencies=[Depends(require_scopes("board.write"))])
async def set_board(
    resourceId: str, body: s.BoardEntryInput, acting_user: ActingUser,  # noqa: N803
    session: Session, settings: SettingsDep,
):
    return respond(await svc.set_board(session, settings, resourceId, body, acting_user))
