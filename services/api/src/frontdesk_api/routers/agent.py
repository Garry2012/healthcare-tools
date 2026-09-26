"""Agent facade — the only operations exposed as MCP tools (tag `Agent`)."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.exc import InterfaceError, OperationalError

from .. import schemas as s
from ..auth import require_scopes
from ..db import tables as t
from ..domain import booking_status
from ..logging import log_event
from ..services import booking_views, bookings, knowledge, schedule, search
from ..services import idempotency as idem
from .deps import (
    ApiDate,
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
router = APIRouter(tags=["Agent"], dependencies=[Depends(require_scopes("agent"))])
REPLAY = {"Idempotent-Replay": "true"}


def _still_holds(session):
    """A stored book/reschedule answer is only replayed while the booking still holds that slot."""

    async def check(stored: dict) -> bool:
        booking_id, slot = stored.get("bookingId"), (stored.get("slot") or {}).get("slotId")
        row = await session.get(t.Booking, booking_id, populate_existing=True) if booking_id else None
        return row is not None and row.status in booking_status.HOLDS_SLOT and row.slot_id == slot

    return check


def _dump(model: s.ApiModel) -> dict:
    return model.model_dump(mode="json", by_alias=True, exclude_none=True)


@router.post(
    "/agent/availability-search",
    operation_id="agentAvailabilitySearch",
    summary="Find resources, sessions and bookable slots from the caller's own words",
    response_model=s.AvailabilitySearchResponse,
    responses=errors(400, 401, 429, 500, 503),
)
async def availability_search(
    body: s.AvailabilitySearchRequest,
    call_id: CallId,
    request: Request,
    session: Session,
    settings: SettingsDep,
    caller_number: CallerNumber = None,
):
    try:
        async with asyncio.timeout(settings.read_timeout_seconds):
            result = await search.agent_search(session, settings, body, request.app.state.directory_cache)
    except (OperationalError, InterfaceError, OSError, TimeoutError) as exc:
        # RULE: never an empty list for a failure.
        log_event(logger, logging.ERROR, "availability_search_failed", error=type(exc).__name__)
        result = s.AvailabilitySearchResponse(
            outcome="COULD_NOT_CHECK",
            as_of=schedule.now_in(settings),
            routing=s.Routing(action="TRANSFER_DESK", destination=settings.pack.desk_destination),
            understood=s.Understood(resources=[], categories=[]),
            results=[],
            alternatives=[],
            partial=True,
        )
    log_event(logger, logging.INFO, "availability_search", outcome=result.outcome,
              action=result.routing.action, results=len(result.results))
    return respond(result)


@router.post(
    "/agent/bookings",
    operation_id="agentCreateBooking",
    summary="Reserve one slot for one customer",
    status_code=201,
    response_model=s.AgentBooking,
    responses={200: {"model": s.AgentBooking, "description": "Idempotent replay."},
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
    fingerprint = idem.request_hash("POST", "/agent/bookings", body.model_dump(mode="json"), caller_number)

    async def operation() -> tuple[int, dict]:
        booked = await bookings.book(session, settings, body, channel="AGENT", call_id=call_id,
                                  caller_number=caller_number, actor=f"agent:{call_id}")
        ctx = await booking_views.context_for(session, settings, [booked.row])
        view = booking_views.agent_view(booked.row, ctx, "BOOKED" if booked.created else "ALREADY_BOOKED")
        return (201 if booked.created else 200), _dump(view)

    outcome = await within(settings.write_timeout_seconds,
                           idem.run(session, key, fingerprint, operation, still_current=_still_holds(session)))
    log_event(logger, logging.INFO, "booking_booked", status=outcome.status,
              bookingId=outcome.body.get("bookingId"), replay=outcome.replay)
    return respond(outcome.body, outcome.status, REPLAY if outcome.replay else None)


@router.get(
    "/agent/bookings",
    operation_id="agentListBookings",
    summary="Bookings belonging to the caller's phone number",
    response_model=s.AgentBookingList,
    responses=errors(400, 401, 429, 500),
)
async def list_bookings(
    call_id: CallId,
    session: Session,
    settings: SettingsDep,
    caller_number: CallerNumber = None,
    customer_name: Annotated[str | None, Query(alias="customerName", max_length=100)] = None,
    phone: Annotated[str | None, Query(pattern=r"^[0-9]{6,15}$")] = None,
    date_from: Annotated[ApiDate | None, Query(alias="from")] = None,
    date_to: Annotated[ApiDate | None, Query(alias="to")] = None,
):
    result = await bookings.agent_list(session, settings, caller_number=caller_number,
                                    customer_name=customer_name, phone=phone,
                                    date_from=date_from, date_to=date_to)
    log_event(logger, logging.INFO, "bookings_listed", outcome=result.outcome,
              count=len(result.items), basis=result.identity_basis)
    return respond(result)


@router.post(
    "/agent/bookings/{bookingId}/cancel",
    operation_id="agentCancelBooking",
    summary="Cancel the caller's booking",
    response_model=s.AgentBooking,
    responses=errors(404, 409, 429, 500),
)
async def cancel(
    bookingId: str,  # noqa: N803 - path parameter name is part of the contract
    body: s.CancelRequest,
    call_id: CallId,
    session: Session,
    settings: SettingsDep,
    caller_number: CallerNumber = None,
    idempotency_key: IdempotencyKey = None,
):
    key = require_key(idempotency_key)
    fingerprint = idem.request_hash("POST", f"/agent/bookings/{bookingId}/cancel",
                                    body.model_dump(mode="json"), caller_number)

    async def operation() -> tuple[int, dict]:
        row, cancelled_now = await bookings.cancel(session, settings, bookingId, body,
                                                   caller_number=caller_number, actor=f"agent:{call_id}")
        ctx = await booking_views.context_for(session, settings, [row])
        return 200, _dump(booking_views.agent_view(row, ctx, "CANCELLED" if cancelled_now else "ALREADY_CANCELLED"))

    outcome = await within(settings.write_timeout_seconds, idem.run(session, key, fingerprint, operation))
    log_event(logger, logging.INFO, "booking_cancelled", bookingId=bookingId, replay=outcome.replay)
    return respond(outcome.body, 200, REPLAY if outcome.replay else None)


@router.post(
    "/agent/bookings/{bookingId}/reschedule",
    operation_id="agentRescheduleBooking",
    summary="Move the caller's booking to another slot",
    response_model=s.AgentBooking,
    responses=errors(404, 409, 429, 500),
)
async def reschedule(
    bookingId: str,  # noqa: N803
    body: s.RescheduleRequest,
    call_id: CallId,
    session: Session,
    settings: SettingsDep,
    caller_number: CallerNumber = None,
    idempotency_key: IdempotencyKey = None,
):
    key = require_key(idempotency_key)
    fingerprint = idem.request_hash("POST", f"/agent/bookings/{bookingId}/reschedule",
                                    body.model_dump(mode="json"), caller_number)

    async def operation() -> tuple[int, dict]:
        row, previous = await bookings.reschedule(session, settings, bookingId, body,
                                               caller_number=caller_number, actor=f"agent:{call_id}")
        ctx = await booking_views.context_for(session, settings, [row])
        return 200, _dump(booking_views.agent_view(row, ctx, "RESCHEDULED", previous_slot=previous))

    outcome = await within(settings.write_timeout_seconds,
                           idem.run(session, key, fingerprint, operation, still_current=_still_holds(session)))
    log_event(logger, logging.INFO, "booking_rescheduled", bookingId=bookingId, replay=outcome.replay)
    return respond(outcome.body, 200, REPLAY if outcome.replay else None)


@router.post(
    "/agent/knowledge-search",
    operation_id="agentKnowledgeSearch",
    summary="Answer a caller's general question from approved answers only",
    response_model=s.KnowledgeSearchResponse,
    responses=errors(400, 401, 429, 500, 503),
)
async def knowledge_search(
    body: s.KnowledgeSearchRequest,
    call_id: CallId,
    request: Request,
    session: Session,
    settings: SettingsDep,
    caller_number: CallerNumber = None,
):
    try:
        async with asyncio.timeout(settings.read_timeout_seconds):
            result = await knowledge.agent_search(session, settings, request.app.state.knowledge_cache, body)
    except (OperationalError, InterfaceError, OSError, TimeoutError) as exc:
        log_event(logger, logging.ERROR, "knowledge_search_failed", error=type(exc).__name__)
        desk = s.KnowledgeRouting(action="TRANSFER_DESK", destination=settings.pack.desk_destination)
        result = s.KnowledgeSearchResponse(outcome="COULD_NOT_CHECK", as_of=schedule.now_in(settings), routing=desk)
    log_event(logger, logging.INFO, "knowledge_search", outcome=result.outcome, action=result.routing.action,
              entryId=result.answer.entry_id if result.answer else None)
    return respond(result)
