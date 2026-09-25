"""Agent facade — the only operations exposed as MCP tools (tag `Agent`)."""

from __future__ import annotations

import logging
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import InterfaceError, OperationalError

from .. import schemas as s
from ..auth import require_scopes
from ..logging import log_event
from ..services import appointments as appts
from ..services import idempotency as idem
from ..services import schedule, search
from .deps import (
    CallerNumber,
    CallId,
    IdempotencyKey,
    Session,
    SettingsDep,
    errors,
    require_key,
    respond,
    within,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Agent"], dependencies=[Depends(require_scopes())])
REPLAY = {"Idempotent-Replay": "true"}


def _dump(model: s.ApiModel) -> dict:
    return model.model_dump(mode="json", by_alias=True, exclude_none=True)


@router.post(
    "/agent/availability-search",
    operation_id="agentAvailabilitySearch",
    summary="Find doctors, sessions and bookable slots from the caller's own words",
    response_model=s.AvailabilitySearchResponse,
    responses=errors(400, 401, 429, 500, 503),
)
async def availability_search(
    body: s.AvailabilitySearchRequest,
    call_id: CallId,
    session: Session,
    settings: SettingsDep,
    caller_number: CallerNumber = None,
):
    try:
        result = await search.agent_search(session, settings, body)
    except (OperationalError, InterfaceError, OSError, TimeoutError) as exc:
        # RULE: never an empty list for a failure.
        log_event(logger, logging.ERROR, "availability_search_failed", error=type(exc).__name__)
        result = s.AvailabilitySearchResponse(
            outcome="COULD_NOT_CHECK",
            as_of=schedule.now_in(settings),
            routing=s.Routing(action="TRANSFER_DESK", destination="desk"),
            understood=s.Understood(doctors=[], departments=[]),
            results=[],
            alternatives=[],
            partial=True,
        )
    log_event(logger, logging.INFO, "availability_search", outcome=result.outcome,
              action=result.routing.action, results=len(result.results))
    return respond(result)


@router.post(
    "/agent/appointments",
    operation_id="agentBookAppointment",
    summary="Reserve one slot for one patient",
    status_code=201,
    response_model=s.AgentAppointment,
    responses={200: {"model": s.AgentAppointment, "description": "Idempotent replay."},
               **errors(400, 401, 409, 429, 500, 504)},
)
async def book(
    body: s.AgentBookRequest,
    call_id: CallId,
    session: Session,
    settings: SettingsDep,
    caller_number: CallerNumber = None,
    idempotency_key: IdempotencyKey = None,
):
    key = require_key(idempotency_key)
    fingerprint = idem.request_hash("POST", "/agent/appointments", body.model_dump(mode="json"), caller_number)

    async def operation() -> tuple[int, dict]:
        booked = await appts.book(session, settings, body, channel="AGENT", call_id=call_id,
                                  caller_number=caller_number, actor=f"agent:{call_id}")
        ctx = await appts.context_for(session, settings, [booked.row])
        view = appts.agent_view(booked.row, ctx, "BOOKED" if booked.created else "ALREADY_BOOKED")
        return (201 if booked.created else 200), _dump(view)

    outcome = await within(settings.write_timeout_seconds, idem.run(session, key, fingerprint, operation))
    log_event(logger, logging.INFO, "appointment_booked", status=outcome.status,
              appointmentId=outcome.body.get("appointmentId"), replay=outcome.replay)
    return respond(outcome.body, outcome.status, REPLAY if outcome.replay else None)


@router.get(
    "/agent/appointments",
    operation_id="agentListAppointments",
    summary="Appointments belonging to the caller's phone number",
    response_model=s.AgentAppointmentList,
    responses=errors(400, 401, 429, 500),
)
async def list_appointments(
    call_id: CallId,
    session: Session,
    settings: SettingsDep,
    caller_number: CallerNumber = None,
    patient_name: Annotated[str | None, Query(alias="patientName", max_length=100)] = None,
    phone: Annotated[str | None, Query(pattern=r"^[0-9]{6,15}$")] = None,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
):
    result = await appts.agent_list(session, settings, caller_number=caller_number,
                                    patient_name=patient_name, phone=phone,
                                    date_from=date_from, date_to=date_to)
    log_event(logger, logging.INFO, "appointments_listed", outcome=result.outcome,
              count=len(result.items), basis=result.identity_basis)
    return respond(result)


@router.post(
    "/agent/appointments/{appointmentId}/cancel",
    operation_id="agentCancelAppointment",
    summary="Cancel the caller's appointment",
    response_model=s.AgentAppointment,
    responses=errors(404, 409, 429, 500),
)
async def cancel(
    appointmentId: str,  # noqa: N803 - path parameter name is part of the contract
    body: s.CancelRequest,
    call_id: CallId,
    session: Session,
    settings: SettingsDep,
    caller_number: CallerNumber = None,
    idempotency_key: IdempotencyKey = None,
):
    key = require_key(idempotency_key)
    fingerprint = idem.request_hash("POST", f"/agent/appointments/{appointmentId}/cancel",
                                    body.model_dump(mode="json"), caller_number)

    async def operation() -> tuple[int, dict]:
        row = await appts.cancel(session, settings, appointmentId, body, caller_number=caller_number,
                                 actor=f"agent:{call_id}")
        ctx = await appts.context_for(session, settings, [row])
        return 200, _dump(appts.agent_view(row, ctx, "CANCELLED"))

    outcome = await within(settings.write_timeout_seconds, idem.run(session, key, fingerprint, operation))
    log_event(logger, logging.INFO, "appointment_cancelled", appointmentId=appointmentId, replay=outcome.replay)
    return respond(outcome.body, 200, REPLAY if outcome.replay else None)


@router.post(
    "/agent/appointments/{appointmentId}/reschedule",
    operation_id="agentRescheduleAppointment",
    summary="Move the caller's appointment to another slot",
    response_model=s.AgentAppointment,
    responses=errors(404, 409, 429, 500),
)
async def reschedule(
    appointmentId: str,  # noqa: N803
    body: s.RescheduleRequest,
    call_id: CallId,
    session: Session,
    settings: SettingsDep,
    caller_number: CallerNumber = None,
    idempotency_key: IdempotencyKey = None,
):
    key = require_key(idempotency_key)
    fingerprint = idem.request_hash("POST", f"/agent/appointments/{appointmentId}/reschedule",
                                    body.model_dump(mode="json"), caller_number)

    async def operation() -> tuple[int, dict]:
        row, previous = await appts.reschedule(session, settings, appointmentId, body,
                                               caller_number=caller_number, actor=f"agent:{call_id}")
        ctx = await appts.context_for(session, settings, [row])
        return 200, _dump(appts.agent_view(row, ctx, "RESCHEDULED", previous_slot=previous))

    outcome = await within(settings.write_timeout_seconds, idem.run(session, key, fingerprint, operation))
    log_event(logger, logging.INFO, "appointment_rescheduled", appointmentId=appointmentId, replay=outcome.replay)
    return respond(outcome.body, 200, REPLAY if outcome.replay else None)
