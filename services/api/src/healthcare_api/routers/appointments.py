"""Staff-side appointment operations (tag `Appointments`)."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from .. import schemas as s
from ..auth import require_scopes
from ..services import appointments as svc
from ..services import idempotency as idem
from ..services import scheduling
from .deps import ActingUser, IdempotencyKey, Session, SettingsDep, errors, respond

router = APIRouter(tags=["Appointments"], dependencies=[Depends(require_scopes("appointments.staff"))])


async def _staff(session, settings, row) -> s.Appointment:
    await session.refresh(row)  # server-side updated_at is expired after a write
    ctx = await svc.context_for(session, settings, [row])
    history = await svc.history_of(session, [row.id])
    return svc.staff_view(row, ctx, history[row.id])


@router.get("/appointments", operation_id="searchAppointments", summary="Staff search (any filter)",
            response_model=s.AppointmentPage, responses=errors(403))
async def search_appointments(
    session: Session,
    settings: SettingsDep,
    doctor_id: Annotated[str | None, Query(alias="doctorId")] = None,
    session_id: Annotated[str | None, Query(alias="sessionId")] = None,
    on: Annotated[date | None, Query(alias="date")] = None,
    phone: Annotated[str | None, Query(pattern=r"^[0-9]{6,15}$")] = None,
    status: s.AppointmentStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    rows, total = await svc.search(session, doctor_id=doctor_id, session_id=session_id, on=on, phone=phone,
                                   status=status.value if status else None, limit=limit, offset=offset)
    ctx = await svc.context_for(session, settings, rows)
    history = await svc.history_of(session, [r.id for r in rows])
    return respond(s.AppointmentPage(items=[svc.staff_view(r, ctx, history[r.id]) for r in rows], total=total))


@router.post("/appointments", operation_id="deskCreateAppointment",
             summary="Desk books on behalf of a walk-in or phone caller", status_code=201,
             response_model=s.Appointment, responses=errors(400, 403, 409))
async def desk_create_appointment(
    body: s.AgentBookRequest, acting_user: ActingUser,
    session: Session, settings: SettingsDep,
    idempotency_key: IdempotencyKey = None,
):
    fingerprint = idem.request_hash("POST", "/appointments", body.model_dump(mode="json"), acting_user)

    async def operation() -> tuple[int, dict]:
        booked = await svc.book(session, settings, body, channel="DESK", call_id=None,
                                caller_number=None, actor=f"staff:{acting_user}")
        view = await _staff(session, settings, booked.row)
        return (201 if booked.created else 200), view.model_dump(mode="json", by_alias=True, exclude_none=True)

    outcome = await idem.run(session, idempotency_key, fingerprint, operation)
    return respond(outcome.body, outcome.status, {"Idempotent-Replay": "true"} if outcome.replay else None)


@router.get("/appointments/{appointmentId}", operation_id="getAppointment",
            summary="One appointment, full detail (staff)", response_model=s.Appointment,
            responses=errors(403, 404))
async def get_appointment(appointmentId: str, session: Session, settings: SettingsDep):  # noqa: N803
    return respond(await _staff(session, settings, await svc.get(session, appointmentId)))


@router.post("/appointments/{appointmentId}/confirm", operation_id="confirmAppointment",
             summary="Desk confirms the timing with the doctor", response_model=s.Appointment,
             responses=errors(403, 404))
async def confirm_appointment(
    appointmentId: str, acting_user: ActingUser, session: Session, settings: SettingsDep,  # noqa: N803
    body: s.ConfirmRequest | None = None,
):
    row = await scheduling.confirm_appointment(session, settings, appointmentId, body or s.ConfirmRequest(),
                                               f"staff:{acting_user}")
    return respond(await _staff(session, settings, row))


@router.post("/appointments/{appointmentId}/status", operation_id="setAppointmentStatus",
             summary="Desk marks arrived / completed / no-show, or cancels on the hospital's behalf",
             response_model=s.Appointment, responses=errors(403, 404, 409))
async def set_appointment_status(
    appointmentId: str, body: s.StatusRequest, acting_user: ActingUser,  # noqa: N803
    session: Session, settings: SettingsDep,
):
    row = await svc.set_status(session, appointmentId, body, f"staff:{acting_user}")
    await session.commit()
    return respond(await _staff(session, settings, row))
