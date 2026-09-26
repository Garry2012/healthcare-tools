"""Staff-side booking operations (tag `Bookings`)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from .. import schemas as s
from ..auth import require_scopes
from ..services import booking_views, bookings, staff_bookings
from ..services import idempotency as idem
from .deps import ActingUser, ApiDate, IdempotencyKey, Session, SettingsDep, errors, respond

router = APIRouter(tags=["Bookings"], dependencies=[Depends(require_scopes("bookings.staff"))])


async def _staff(session, settings, row) -> s.Booking:
    await session.refresh(row)  # server-side updated_at is expired after a write
    ctx = await booking_views.context_for(session, settings, [row])
    history = await booking_views.history_of(session, [row.id])
    return booking_views.staff_view(row, ctx, history[row.id])


@router.get("/bookings", operation_id="searchBookings", summary="Staff search (any filter)",
            response_model=s.BookingPage, responses=errors(403))
async def search_bookings(
    session: Session,
    settings: SettingsDep,
    resource_id: Annotated[str | None, Query(alias="resourceId")] = None,
    session_id: Annotated[str | None, Query(alias="sessionId")] = None,
    on: Annotated[ApiDate | None, Query(alias="date")] = None,
    phone: Annotated[str | None, Query(pattern=r"^[0-9]{6,15}$")] = None,
    status: s.BookingStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    rows, total = await staff_bookings.search(
        session, resource_id=resource_id, session_id=session_id, on=on, phone=phone,
        status=status.value if status else None, limit=limit, offset=offset,
    )
    ctx = await booking_views.context_for(session, settings, rows)
    history = await booking_views.history_of(session, [r.id for r in rows])
    return respond(s.BookingPage(items=[booking_views.staff_view(r, ctx, history[r.id]) for r in rows], total=total))


@router.post("/bookings", operation_id="deskCreateBooking",
             summary="Desk books on behalf of a walk-in or phone caller", status_code=201,
             response_model=s.Booking, responses=errors(400, 403, 409))
async def desk_create_booking(
    body: s.AgentBookRequest, acting_user: ActingUser,
    session: Session, settings: SettingsDep,
    idempotency_key: IdempotencyKey = None,
):
    fingerprint = idem.request_hash("POST", "/bookings", body.model_dump(mode="json"), acting_user)

    async def operation() -> tuple[int, dict]:
        booked = await bookings.book(session, settings, body, channel="DESK", call_id=None,
                                caller_number=None, actor=f"staff:{acting_user}")
        view = await _staff(session, settings, booked.row)
        return (201 if booked.created else 200), view.model_dump(mode="json", by_alias=True, exclude_none=True)

    outcome = await idem.run(session, idempotency_key, fingerprint, operation)
    return respond(outcome.body, outcome.status, {"Idempotent-Replay": "true"} if outcome.replay else None)


@router.get("/bookings/{bookingId}", operation_id="getBooking",
            summary="One booking, full detail (staff)", response_model=s.Booking,
            responses=errors(403, 404))
async def get_booking(bookingId: str, session: Session, settings: SettingsDep):  # noqa: N803
    return respond(await _staff(session, settings, await staff_bookings.get(session, bookingId)))


@router.post("/bookings/{bookingId}/confirm", operation_id="confirmBooking",
             summary="Desk confirms the timing with the resource", response_model=s.Booking,
             responses=errors(403, 404))
async def confirm_booking(
    bookingId: str, acting_user: ActingUser, session: Session, settings: SettingsDep,  # noqa: N803
    body: s.ConfirmRequest | None = None,
):
    row = await staff_bookings.confirm_booking(session, settings, bookingId, body or s.ConfirmRequest(),
                                               f"staff:{acting_user}")
    return respond(await _staff(session, settings, row))


@router.post("/bookings/{bookingId}/status", operation_id="setBookingStatus",
             summary="Desk marks arrived / completed / no-show, or cancels on the provider's behalf",
             response_model=s.Booking, responses=errors(403, 404, 409))
async def set_booking_status(
    bookingId: str, body: s.StatusRequest, acting_user: ActingUser,  # noqa: N803
    session: Session, settings: SettingsDep,
):
    row = await staff_bookings.set_status(session, settings, bookingId, body, f"staff:{acting_user}")
    await session.commit()
    return respond(await _staff(session, settings, row))
