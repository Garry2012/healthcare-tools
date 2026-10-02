"""manage_booking: create/list/cancel/reschedule on Manoj's appointment contract.

Authority to list or change comes from the trusted caller identity; the dictated patient mobile is
contact data only. A write needs the caller's confirmation, trusted call and operation context and
a live-board check that refuses an UNKNOWN date with the callback-only outcome. The outgoing body is
frozen and keyed by sha256(tenant|call|action|operation) so a retry replays and any changed payload,
including a changed target, conflicts at the owner.
Outcomes keep validated success, definite rejection, state/idempotency conflict and uncertain
completion distinct. A successful create is NOTED: recorded, never a reserved time.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from . import board_scope, contract, identity, outcomes
from .cache import DirectoryCache
from .clock import Clock, Deadline, local_now
from .config import Settings
from .context import CallContext
from .ops_client import InvalidIdentifier, Malformed, OpsClient, Rejected, Unavailable, UncertainWrite

logger = logging.getLogger(__name__)

Action = Literal["CREATE", "LIST", "CANCEL", "RESCHEDULE"]
WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
_ID = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class BookingRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: Action
    # CREATE
    patientName: str | None = Field(default=None, max_length=100)  # noqa: N815 - wire names
    patientMobile: str | None = Field(default=None, max_length=20)  # noqa: N815
    doctorId: str | None = Field(default=None, max_length=64)  # noqa: N815
    departmentId: str | None = Field(default=None, max_length=64)  # noqa: N815
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


def operation_key(provider: str, call_id: str, action: str, operation_id: str) -> str:
    """Opaque, 64 characters, bound to tenant, call, action and the platform's operation id. The target is
    deliberately not part of the key: a retry that changed doctor or appointment must conflict, not fork."""
    return hashlib.sha256("|".join((provider, call_id, action, operation_id)).encode("utf-8")).hexdigest()


def _appointment_out(a: contract.Appointment) -> outcomes.AppointmentOut:
    return outcomes.AppointmentOut(appointmentId=a.id, status=a.status, visitDate=a.visitDate.isoformat(),
                                   expectedTime=a.expectedTime, doctorId=a.doctorId, department=a.department,
                                   patientName=a.patientName)


def _iso(value: str | None, today: date, field: str, issues: list[str], *, required: bool) -> str | None:
    if not value:
        if required:
            issues.append(field)
        return None
    text = value.strip()
    if not _ISO.fullmatch(text):
        issues.append(field)
        return None
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        issues.append(field)
        return None
    if parsed < today:
        issues.append(field)
        return None
    return parsed.isoformat()


def _time(value: str | None, field: str, issues: list[str]) -> str | None:
    if value is None:
        return None
    if not identity.is_approx_time(value):
        issues.append(field)
        return None
    return value


class BookingService:
    def __init__(self, ops: OpsClient, settings: Settings, clock: Clock,
                 cache: DirectoryCache | None = None) -> None:
        self.ops = ops
        self.settings = settings
        self.clock = clock
        self.cache = cache or DirectoryCache(settings)

    async def _profile(self, doctor_id: str, deadline: Deadline) -> contract.DoctorDetail | None:
        """Cached profile for the session-scope rule; a failure here is not fatal (the board decides)."""
        cached = self.cache.get(("doctor", doctor_id))
        if cached is not None:
            return cached
        try:
            detail = await self.ops.get_doctor(doctor_id, deadline)
        except (Unavailable, Malformed, Rejected, InvalidIdentifier):
            return None
        self.cache.set(("doctor", doctor_id), detail)
        return detail

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
            return outcomes.BookingResult(outcome="REJECTED", nextStep="ASK_TO_CORRECT", fields=list(exc.fields),
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
        today = local_now(self.clock, self.settings.zone).date()
        issues: list[str] = []
        from_date = _iso(request.fromDate, date.min, "fromDate", issues, required=False)
        to_date = _iso(request.toDate, date.min, "toDate", issues, required=False)
        if issues:
            return self._invalid(issues)
        del today
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
        today = local_now(self.clock, self.settings.zone).date()
        issues: list[str] = []
        if not (request.patientName or "").strip():
            issues.append("patientName")
        if not request.patientMobile or not identity.is_contract_mobile(request.patientMobile):
            issues.append("patientMobile")
        if bool(request.doctorId) == bool(request.departmentId):
            issues.append("doctorId")
        for field, value in (("doctorId", request.doctorId), ("departmentId", request.departmentId)):
            if value and not _ID.fullmatch(value):
                issues.append(field)
        visit_date = _iso(request.visitDate, today, "visitDate", issues, required=True)
        preferred = _time(request.preferredTime, "preferredTime", issues)
        if issues:
            return self._invalid(sorted(set(issues)))
        if gate := self._write_gate(ctx, request):
            return gate
        deadline = Deadline(self.settings.write_deadline_seconds)
        date_param = "today" if visit_date == today.isoformat() else visit_date
        board_read = self.ops.get_availability(
            deadline, date=date_param, doctor_id=request.doctorId, department=request.departmentId)
        try:
            if request.doctorId and request.session:
                profile, board = await asyncio.gather(self._profile(request.doctorId, deadline), board_read,
                                                     return_exceptions=True)
                if isinstance(board, BaseException):
                    raise board
            else:
                profile, board = None, await board_read
        except (Unavailable, Malformed) as exc:
            retry = exc.retry_after if isinstance(exc, Unavailable) else None
            detail = "AUTH" if isinstance(exc, Unavailable) and exc.reason == "AUTH" else "BOARD_UNAVAILABLE"
            return outcomes.BookingResult(outcome="COULD_NOT_RECORD", nextStep="SAY_COULD_NOT_RECORD",
                                          detail=detail, retryAfterSeconds=retry)
        except Rejected as exc:
            return self._failure(exc, write=True)
        weekday = WEEKDAYS[date.fromisoformat(visit_date).weekday()]
        usual = board_scope.usual_sessions_on(profile, weekday)
        if blocked := self._board_gate(board, request.doctorId, request.session, preferred, usual):
            return blocked
        body: dict[str, Any] = {"patientName": request.patientName.strip(), "mobile": request.patientMobile}
        if request.doctorId:
            body["doctorId"] = request.doctorId
        else:
            body["department"] = request.departmentId
        body["visitDate"] = visit_date
        if preferred:
            body["expectedTime"] = preferred
        if request.reasonVerbatim:
            body["reasonVerbatim"] = request.reasonVerbatim
        body["callId"] = ctx.call_id
        key = operation_key(self.settings.provider_id, ctx.call_id, "CREATE", ctx.operation_id)
        try:
            _, appointment = await self.ops.create_appointment(body, key, deadline)
        except (Rejected, Malformed, Unavailable, UncertainWrite) as exc:
            return self._failure(exc, write=True)
        return self._written(appointment, "SAY_REQUEST_NOTED")

    @staticmethod
    def _board_gate(board: contract.AvailabilityBoard, doctor_id: str | None, session: str | None,
                    preferred_time: str | None, usual_today: list[str]) -> outcomes.BookingResult | None:
        """Live-board check before a write, with exactly the session scope get_doctor_availability uses
        (board_scope.scope_board). Doctor target: an UNKNOWN or missing row in scope → callback only; a preferred
        time outside the chosen session's window → invalid. Department target: the same scope per doctor; when no
        doctor in scope is free of UNKNOWN → callback only."""
        callback = outcomes.BookingResult(outcome="CALLBACK_REQUIRED", nextStep="ASK_CALLBACK_DETAILS",
                                          callback=outcomes.Callback(), detail="BOARD_UNKNOWN")
        if doctor_id:
            entries = [e for e in board.items if e.doctorId == doctor_id]
            scope = board_scope.scope_board(entries, session=session, preferred_time=preferred_time,
                                            usual_today=usual_today)
            if scope.time_outside_window:
                return outcomes.BookingResult(outcome="INVALID_REQUEST", nextStep="ASK_TO_CORRECT",
                                              fields=["preferredTime"], detail="TIME_OUTSIDE_SESSION")
            return callback if scope.unknown else None
        by_doctor: dict[str, list[contract.AvailabilityEntry]] = {}
        for e in board.items:
            by_doctor.setdefault(e.doctorId, []).append(e)
        offered = False
        for entries in by_doctor.values():
            if not board_scope.in_scope_for_department(entries, session):
                continue
            if not board_scope.scope_board(entries, session=session, preferred_time=preferred_time).unknown:
                offered = True
        return None if offered else callback

    async def _change(self, ctx: CallContext, request: BookingRequest) -> outcomes.BookingResult:
        today = local_now(self.clock, self.settings.zone).date()
        issues: list[str] = []
        if not request.appointmentId or not _ID.fullmatch(request.appointmentId):
            issues.append("appointmentId")
        new_date = new_time = None
        if request.action == "RESCHEDULE":
            new_date = _iso(request.newVisitDate, today, "newVisitDate", issues, required=True)
            new_time = _time(request.newPreferredTime, "newPreferredTime", issues)
            if request.doctorId or request.departmentId:
                issues.append("doctorId" if request.doctorId else "departmentId")  # no doctor change in the contract
        if issues:
            detail = "DOCTOR_CHANGE_UNSUPPORTED" if "doctorId" in issues or "departmentId" in issues else None
            return self._invalid(sorted(set(issues)), detail)
        if gate := self._write_gate(ctx, request):
            return gate
        mobile = identity.authorised_mobile(ctx, self.settings)
        if mobile is None:
            return self._identity_unavailable()
        deadline = Deadline(self.settings.write_deadline_seconds)
        if request.action == "RESCHEDULE":
            if blocked := await self._reschedule_gate(mobile, request, new_date, new_time, today, deadline):
                return blocked
        body: dict[str, Any] = {"callerMobile": mobile}
        if request.action == "CANCEL":
            if request.reasonVerbatim:
                body["reason"] = request.reasonVerbatim
            body["callId"] = ctx.call_id
            key = operation_key(self.settings.provider_id, ctx.call_id, "CANCEL", ctx.operation_id)
            call = self.ops.cancel_appointment(request.appointmentId, body, key, deadline)
            step = "SAY_CANCELLED"
        else:
            body["newVisitDate"] = new_date
            if new_time:
                body["newExpectedTime"] = new_time
            body["callId"] = ctx.call_id
            key = operation_key(self.settings.provider_id, ctx.call_id, "RESCHEDULE", ctx.operation_id)
            call = self.ops.reschedule_appointment(request.appointmentId, body, key, deadline)
            step = "SAY_CHANGED"
        try:
            _, appointment = await call
        except (Rejected, Malformed, Unavailable, UncertainWrite, InvalidIdentifier) as exc:
            if isinstance(exc, InvalidIdentifier):
                return self._invalid(["appointmentId"])
            return self._failure(exc, write=True)
        return self._written(appointment, step)

    async def _reschedule_gate(self, mobile: str, request: BookingRequest, new_date: str, new_time: str | None,
                               today: date, deadline: Deadline) -> outcomes.BookingResult | None:
        """A move lands on a date too: find the caller's appointment, then apply the same board rule to the new
        date for its doctor (or department). An appointment the owner does not list for this caller is left to
        the owner's neutral not-found."""
        try:
            listed = await self.ops.find_appointments(deadline, mobile=mobile)
        except (Rejected, Malformed, Unavailable) as exc:
            if isinstance(exc, Rejected):
                return self._failure(exc, write=True)
            retry = exc.retry_after if isinstance(exc, Unavailable) else None
            return outcomes.BookingResult(outcome="COULD_NOT_RECORD", nextStep="SAY_COULD_NOT_RECORD",
                                          detail="BOARD_UNAVAILABLE", retryAfterSeconds=retry)
        current = next((a for a in listed.items if a.id == request.appointmentId), None)
        if current is None or not (current.doctorId or current.department):
            return None
        date_param = "today" if new_date == today.isoformat() else new_date
        try:
            board = await self.ops.get_availability(deadline, date=date_param, doctor_id=current.doctorId,
                                                    department=None if current.doctorId else current.department)
        except (Rejected, Malformed, Unavailable) as exc:
            if isinstance(exc, Rejected):
                return self._failure(exc, write=True)
            retry = exc.retry_after if isinstance(exc, Unavailable) else None
            return outcomes.BookingResult(outcome="COULD_NOT_RECORD", nextStep="SAY_COULD_NOT_RECORD",
                                          detail="BOARD_UNAVAILABLE", retryAfterSeconds=retry)
        usual: list[str] = []
        if current.doctorId and request.session:
            profile = await self._profile(current.doctorId, deadline)
            usual = board_scope.usual_sessions_on(profile, WEEKDAYS[date.fromisoformat(new_date).weekday()])
        return self._board_gate(board, current.doctorId, request.session, new_time, usual)

    @staticmethod
    def _written(appointment: contract.Appointment, step: str) -> outcomes.BookingResult:
        outcome = {"NOTED": "NOTED", "CONFIRMED_BY_DESK": "NOTED", "CHANGED": "CHANGED",
                   "CANCELLED": "CANCELLED"}[appointment.status]
        step = {"NOTED": "SAY_REQUEST_NOTED", "CHANGED": "SAY_CHANGED", "CANCELLED": "SAY_CANCELLED"}[outcome]
        return outcomes.BookingResult(outcome=outcome, nextStep=step, appointment=_appointment_out(appointment))
