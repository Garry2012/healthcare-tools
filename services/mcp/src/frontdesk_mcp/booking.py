"""manage_booking: create/list/cancel/reschedule on Manoj's appointment contract.

Authority to list or change comes from the trusted caller identity; the dictated patient mobile is
contact data only. A write needs the caller's confirmation, trusted call and operation context and
the shared today/future schedule policy before CREATE or RESCHEDULE. The outgoing body is
frozen and keyed by sha256(tenant|call|action|operation) so a retry replays and any changed payload,
including a changed target, conflicts at the owner.
Outcomes keep validated success, definite rejection, state/idempotency conflict and uncertain
completion distinct. A successful create is NOTED: recorded, never a reserved time.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from . import availability_policy as policy
from . import contract, identity, outcomes
from .cache import DirectoryCache
from .clock import Clock, Deadline, local_now
from .config import Settings
from .context import CallContext
from .ops_client import InvalidIdentifier, Malformed, OpsClient, Rejected, Unavailable, UncertainWrite
from .schedule_reader import ScheduleReader

logger = logging.getLogger(__name__)

Action = Literal["CREATE", "LIST", "CANCEL", "RESCHEDULE"]
_ID = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


class BookingRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action: Action
    # CREATE
    patientName: str | None = Field(default=None, max_length=100)  # noqa: N815 - wire names
    patientMobile: str | None = Field(default=None, max_length=20)  # noqa: N815
    doctorId: str | None = Field(default=None, max_length=64)  # noqa: N815
    visitDate: str | None = Field(default=None, max_length=10)  # noqa: N815
    preferredTime: str | None = Field(default=None, max_length=5)  # noqa: N815
    session: str | None = Field(default=None, max_length=40, description="The board session the caller chose.")
    reasonVerbatim: str | None = Field(default=None, max_length=500)  # noqa: N815
    # CANCEL / RESCHEDULE
    appointmentId: str | None = Field(default=None, max_length=64)  # noqa: N815
    newVisitDate: str | None = Field(default=None, max_length=10)  # noqa: N815
    newPreferredTime: str | None = Field(default=None, max_length=5)  # noqa: N815
    # LIST
    fromDate: str | None = Field(default=None, max_length=10)  # noqa: N815
    toDate: str | None = Field(default=None, max_length=10)  # noqa: N815
    status: contract.AppointmentStatus | None = None
    # every write
    callerConfirmed: bool = False  # noqa: N815


_OWNER_FIELDS: dict[Action, dict[str, str]] = {
    "CREATE": {"patientName": "patientName", "mobile": "patientMobile", "doctorId": "doctorId",
               "visitDate": "visitDate", "expectedTime": "preferredTime", "reasonVerbatim": "reasonVerbatim"},
    "CANCEL": {"reason": "reasonVerbatim"},
    "RESCHEDULE": {"newVisitDate": "newVisitDate", "newExpectedTime": "newPreferredTime"},
}


def _write_body(request: BookingRequest, **validated: str | None) -> dict[str, Any]:
    """Map validated tool values to owner fields; trusted context is added separately."""
    values = request.model_dump() | validated
    return {owner: values[tool] for owner, tool in _OWNER_FIELDS[request.action].items() if values[tool]}


def operation_key(provider: str, call_id: str, action: str, operation_id: str) -> str:
    """Opaque, 64 characters, bound to tenant, call, action and the platform's operation id. The target is
    deliberately not part of the key: a retry that changed doctor or appointment must conflict, not fork."""
    return hashlib.sha256("|".join((provider, call_id, action, operation_id)).encode("utf-8")).hexdigest()


def _appointment_out(a: contract.Appointment) -> outcomes.AppointmentOut:
    return outcomes.AppointmentOut(appointmentId=a.id, status=a.status, visitDate=a.visitDate.isoformat(),
                                   expectedTime=a.expectedTime, doctorId=a.doctorId, department=a.department,
                                   patientName=a.patientName)


def _list_date(value: str | None, field: str, issues: list[str]) -> str | None:
    if not value:
        return None
    parsed = policy.resolve_date(value, datetime.min, policy.Purpose.AVAILABILITY)
    if value.strip().lower() == "today" or isinstance(parsed, policy.DateError):
        issues.append(field)
        return None
    return parsed.value.isoformat()


def _time(value: str | None, field: str, issues: list[str]) -> str | None:
    if value is None:
        return None
    if not identity.is_approx_time(value):
        issues.append(field)
        return None
    return value


class BookingService:
    def __init__(self, ops: OpsClient, settings: Settings, clock: Clock,
                 cache: DirectoryCache | None = None, reader: ScheduleReader | None = None) -> None:
        self.ops = ops
        self.settings = settings
        self.clock = clock
        self.reader = reader or ScheduleReader(ops, cache or DirectoryCache(settings), settings)


    async def manage(self, ctx: CallContext, request: BookingRequest) -> outcomes.BookingResult:
        if request.action == "LIST":
            return await self._list(ctx, request)
        if request.action == "CREATE":
            return await self._create(ctx, request)
        return await self._change(ctx, request)

    # ------------------------------------------------------------------ shared gates

    @staticmethod
    def _invalid(fields: list[str], detail: str | None = None) -> outcomes.BookingResult:
        return outcomes.BookingResult(outcome="INVALID_REQUEST", nextStep="ASK_TO_CORRECT", fields=fields,
                                      detail=detail)

    def _write_gate(self, ctx: CallContext, request: BookingRequest) -> outcomes.BookingResult | None:
        if not request.callerConfirmed:
            return outcomes.BookingResult(outcome="CONFIRMATION_REQUIRED", nextStep="ASK_CONFIRMATION")
        if not ctx.call_id or not ctx.operation_id:
            logger.warning("write_without_operation_context")
            return outcomes.BookingResult(outcome="OPERATION_CONTEXT_MISSING", nextStep="SAY_COULD_NOT_RECORD",
                                          detail="CALL_ID_MISSING" if not ctx.call_id else "OPERATION_ID_MISSING")
        return None

    @staticmethod
    def _identity_unavailable() -> outcomes.BookingResult:
        return outcomes.BookingResult(outcome="IDENTITY_UNAVAILABLE", nextStep="TRANSFER_DESK")

    def _failure(self, exc: Exception, write: bool) -> outcomes.BookingResult:
        if isinstance(exc, Rejected):
            if exc.code == "NOT_FOUND":
                return outcomes.BookingResult(outcome="NOT_FOUND", nextStep="SAY_NOT_FOUND")
            if exc.code == "IDEMPOTENCY_CONFLICT":
                return outcomes.BookingResult(outcome="CONFLICT", nextStep="TRANSFER_DESK",
                                              detail="IDEMPOTENCY_CONFLICT")
            if exc.code == "CONFLICT":
                return outcomes.BookingResult(outcome="CONFLICT", nextStep="TRANSFER_DESK", detail="STATE_CONFLICT")
            names = {owner: tool for mapping in _OWNER_FIELDS.values() for owner, tool in mapping.items()}
            fields = {names.get(field, field) for field in exc.fields} & BookingRequest.model_fields.keys()
            return outcomes.BookingResult(outcome="REJECTED", nextStep="ASK_TO_CORRECT", fields=sorted(fields),
                                          detail=exc.code or "REJECTED")
        if isinstance(exc, UncertainWrite):
            return outcomes.BookingResult(outcome="UNCERTAIN", nextStep="SAY_UNCERTAIN_AND_TRANSFER",
                                          detail="NO_VERIFIED_RESPONSE")
        if isinstance(exc, Malformed):
            if write:
                return outcomes.BookingResult(outcome="UNCERTAIN", nextStep="SAY_UNCERTAIN_AND_TRANSFER",
                                              detail="MALFORMED_SUCCESS")
            return outcomes.BookingResult(outcome="COULD_NOT_CHECK", nextStep="SAY_COULD_NOT_CHECK", detail="MALFORMED")
        if isinstance(exc, Unavailable):
            return outcomes.BookingResult(outcome="COULD_NOT_RECORD" if write else "COULD_NOT_CHECK",
                                          nextStep="SAY_COULD_NOT_RECORD" if write else "SAY_COULD_NOT_CHECK",
                                          detail=exc.reason, retryAfterSeconds=exc.retry_after)
        raise exc

    async def _list(self, ctx: CallContext, request: BookingRequest) -> outcomes.BookingResult:
        mobile = identity.authorised_mobile(ctx, self.settings)
        if mobile is None:
            return self._identity_unavailable()
        issues: list[str] = []
        from_date = _list_date(request.fromDate, "fromDate", issues)
        to_date = _list_date(request.toDate, "toDate", issues)
        if issues:
            return self._invalid(issues)
        deadline = Deadline(self.settings.read_deadline_seconds)
        try:
            found = await self.ops.find_appointments(deadline, mobile=mobile, from_date=from_date, to_date=to_date,
                                                     status=request.status)
        except (Rejected, Malformed, Unavailable) as exc:
            return self._failure(exc, write=False)
        items = [_appointment_out(a) for a in found.items]
        if not items:
            return outcomes.BookingResult(outcome="NOT_FOUND", nextStep="SAY_NOT_FOUND")
        return outcomes.BookingResult(outcome="FOUND", nextStep="OFFER_CHOICES", appointments=items)

    async def _create(self, ctx: CallContext, request: BookingRequest) -> outcomes.BookingResult:
        now = local_now(self.clock, self.settings.zone)
        issues: list[str] = []
        if not (request.patientName or "").strip():
            issues.append("patientName")
        if not request.patientMobile or not identity.is_contract_mobile(request.patientMobile):
            issues.append("patientMobile")
        if not request.doctorId or not _ID.fullmatch(request.doctorId):
            issues.append("doctorId")
        requested = policy.resolve_date(request.visitDate, now, policy.Purpose.AVAILABILITY)
        if isinstance(requested, policy.DateError):
            return self._invalid(sorted(set([*issues, "visitDate"])), requested)
        visit_date = requested.value.isoformat()
        preferred = _time(request.preferredTime, "preferredTime", issues)
        if issues:
            return self._invalid(sorted(set(issues)))
        if gate := self._write_gate(ctx, request):
            return gate
        deadline = Deadline(self.settings.write_deadline_seconds)
        if blocked := await self._schedule_gate(request.doctorId, requested, request.session, preferred, deadline, now):
            return blocked
        body = _write_body(request, patientName=request.patientName.strip(), visitDate=visit_date,
                           preferredTime=preferred)
        body["callId"] = ctx.call_id
        key = operation_key(self.settings.provider_id, ctx.call_id, "CREATE", ctx.operation_id)
        try:
            _, appointment = await self.ops.create_appointment(body, key, deadline)
        except (Rejected, Malformed, Unavailable, UncertainWrite) as exc:
            return self._failure(exc, write=True)
        return self._written(appointment, "SAY_REQUEST_NOTED")

    async def _schedule_gate(self, doctor_id: str, requested: policy.RequestedDate, session: str | None,
                             preferred: str | None, deadline: Deadline, now: datetime) -> outcomes.BookingResult | None:
        try:
            facts = await self.reader.doctor(doctor_id, requested, policy.Purpose.AVAILABILITY, deadline)
        except (Unavailable, Malformed, InvalidIdentifier) as exc:
            retry = exc.retry_after if isinstance(exc, Unavailable) else None
            detail = "AUTH" if isinstance(exc, Unavailable) and exc.reason == "AUTH" else (
                "BOARD_UNAVAILABLE" if getattr(exc, "stage", None) == "board" else "PROFILE_UNAVAILABLE")
            return outcomes.BookingResult(outcome="COULD_NOT_RECORD", nextStep="SAY_COULD_NOT_RECORD",
                                          detail=detail, retryAfterSeconds=retry)
        except Rejected as exc:
            return self._failure(exc, write=True)
        decision = policy.decide_doctor(facts, requested, session=session, now=now)
        booking = policy.decide_booking(decision, session=session, preferred_time=preferred, now=now)
        if isinstance(booking, policy.Write):
            return None
        if isinstance(booking, policy.SessionRequired):
            return outcomes.BookingResult(outcome="INVALID_REQUEST", nextStep="ASK_WHICH_SESSION",
                fields=["session"], detail="SESSION_REQUIRED",
                sessions=[outcomes.session_out(s, requested) for s in booking.sessions])
        if isinstance(booking, policy.Callback):
            return outcomes.BookingResult(outcome="CALLBACK_REQUIRED", nextStep="ASK_CALLBACK_DETAILS",
                detail=booking.reason, callback=outcomes.Callback(reason=booking.reason))
        if isinstance(booking, policy.Handoff):
            return outcomes.BookingResult(outcome="HANDOFF_REQUIRED", nextStep="TRANSFER_DESK", detail=booking.reason)
        return outcomes.BookingResult(outcome="NOT_AVAILABLE", detail=booking.reason,
            nextStep="OFFER_OTHER_SESSION_OR_TIME" if booking.alternatives else "OFFER_OTHER_SESSION_OR_DATE",
            sessions=[outcomes.session_out(s, requested) for s in booking.alternatives])

    async def _change(self, ctx: CallContext, request: BookingRequest) -> outcomes.BookingResult:
        now = local_now(self.clock, self.settings.zone)
        issues: list[str] = []
        if not request.appointmentId or not _ID.fullmatch(request.appointmentId):
            issues.append("appointmentId")
        new_date = new_time = None
        if request.action == "RESCHEDULE":
            requested = policy.resolve_date(request.newVisitDate, now, policy.Purpose.AVAILABILITY)
            if isinstance(requested, policy.DateError):
                return self._invalid(sorted(set([*issues, "newVisitDate"])), requested)
            new_date = requested.value.isoformat()
            new_time = _time(request.newPreferredTime, "newPreferredTime", issues)
            if request.doctorId:
                issues.append("doctorId")  # no doctor change in the contract
        if issues:
            detail = "DOCTOR_CHANGE_UNSUPPORTED" if "doctorId" in issues else None
            return self._invalid(sorted(set(issues)), detail)
        if gate := self._write_gate(ctx, request):
            return gate
        mobile = identity.authorised_mobile(ctx, self.settings)
        if mobile is None:
            return self._identity_unavailable()
        deadline = Deadline(self.settings.write_deadline_seconds)
        if request.action == "RESCHEDULE":
            if blocked := await self._reschedule_gate(mobile, request, requested, new_time, deadline, now):
                return blocked
        body = _write_body(request, newVisitDate=new_date, newPreferredTime=new_time)
        body.update(callerMobile=mobile, callId=ctx.call_id)
        if request.action == "CANCEL":
            key = operation_key(self.settings.provider_id, ctx.call_id, "CANCEL", ctx.operation_id)
            call = self.ops.cancel_appointment(request.appointmentId, body, key, deadline)
            step = "SAY_CANCELLED"
        else:
            key = operation_key(self.settings.provider_id, ctx.call_id, "RESCHEDULE", ctx.operation_id)
            call = self.ops.reschedule_appointment(request.appointmentId, body, key, deadline)
            step = "SAY_CHANGED"
        try:
            _, appointment = await call
        except (Rejected, Malformed, Unavailable, UncertainWrite, InvalidIdentifier) as exc:
            if isinstance(exc, InvalidIdentifier):
                return self._invalid(["appointmentId"])
            return self._failure(exc, write=True)
        if request.action == "RESCHEDULE":
            return outcomes.BookingResult(outcome="NOTED", nextStep="SAY_REQUEST_NOTED",
                                          appointment=_appointment_out(appointment))
        return self._written(appointment, step)

    async def _reschedule_gate(self, mobile: str, request: BookingRequest, requested: policy.RequestedDate,
                              new_time: str | None, deadline: Deadline, now: datetime) -> outcomes.BookingResult | None:
        try:
            listed = await self.ops.find_appointments(deadline, mobile=mobile)
        except (Rejected, Malformed, Unavailable) as exc:
            if isinstance(exc, Rejected):
                return self._failure(exc, write=True)
            retry = exc.retry_after if isinstance(exc, Unavailable) else None
            return outcomes.BookingResult(outcome="COULD_NOT_RECORD", nextStep="SAY_COULD_NOT_RECORD",
                                          detail="APPOINTMENT_UNAVAILABLE", retryAfterSeconds=retry)
        current = next((a for a in listed.items if a.id == request.appointmentId), None)
        if current is None:
            return None  # preserve the owner's neutral NOT_FOUND for this verified caller
        if not current.doctorId:
            return outcomes.BookingResult(outcome="COULD_NOT_RECORD", nextStep="SAY_COULD_NOT_RECORD",
                                          detail="MALFORMED")
        return await self._schedule_gate(current.doctorId, requested, request.session, new_time, deadline, now)

    @staticmethod
    def _written(appointment: contract.Appointment, step: str) -> outcomes.BookingResult:
        outcome = {"NOTED": "NOTED", "CONFIRMED_BY_DESK": "NOTED", "CHANGED": "CHANGED",
                   "CANCELLED": "CANCELLED"}[appointment.status]
        step = {"NOTED": "SAY_REQUEST_NOTED", "CHANGED": "SAY_CHANGED", "CANCELLED": "SAY_CANCELLED"}[outcome]
        return outcomes.BookingResult(outcome=outcome, nextStep=step, appointment=_appointment_out(appointment))
