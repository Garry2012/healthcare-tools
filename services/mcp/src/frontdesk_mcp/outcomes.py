"""Model-facing result envelopes: compact, typed, complete. They preserve status, ambiguity, completeness
and the next step; they never carry raw upstream prose, patient contact data, or
invented slots/capacity. These are MCP schema choices; the owner contracts' statuses are untouched."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_serializer

from . import contract
from .availability_policy import Basis, Decision, Reason, RequestedDate, SessionDecision, on_requested_date


def _blank_session(value: str | None) -> str | None:
    return None if isinstance(value, str) and not value.strip() else value


SessionChoice = Annotated[str | None, AfterValidator(_blank_session)]


class _Out(BaseModel):
    model_config = ConfigDict(frozen=True)


class Callback(_Out):
    """Callback reason and summary category; no appointment or separate task is created."""

    reason: Reason
    summaryOutcome: Literal["CALLBACK_NOTED"] = "CALLBACK_NOTED"  # noqa: N815 - wire names


class SlotOut(_Out):
    start: str = Field(pattern=contract.APPROX_TIME_PATTERN,
                       description="Open block start in HH:MM facility local time, inclusive.")
    end: str = Field(pattern=contract.APPROX_TIME_PATTERN,
                     description="Open block end in HH:MM facility local time, exclusive.")
    available: int = Field(ge=0, description=(
        "Remaining places reported by the owner for this block; MCP does not compute capacity or reserve a place."))


_OPEN_SLOTS_DESCRIPTION = (
    "Open blocks offered for this session and date: the owner's open blocks when the session permits a request. "
    "null means slots were not checked (disabled, WORKING_HOURS, or a department search pending doctor selection); "
    "[] means checked and no block is offered (none open, or the session does not permit a request). "
    "When slots apply, CREATE or RESCHEDULE times outside these blocks are refused."
)


class UsualSessionOut(_Out):
    label: str | None
    daysOfWeek: list[str]  # noqa: N815
    start: str | None = Field(description=(
        "Session start in facility local time. null only for a one-day session whose hours the owner did not supply. "
        "Such a session has no bookable time."))
    end: str | None = Field(description=(
        "Session end in facility local time. null only for a one-day session whose hours the owner did not supply. "
        "Such a session has no bookable time."))
    onRequestedDate: bool | None  # noqa: N815
    decision: Decision
    reason: Reason | None = None
    openSlots: list[SlotOut] | None = Field(default=None, description=_OPEN_SLOTS_DESCRIPTION)  # noqa: N815
    status: contract.AvailabilityStatus | None = Field(default=None,
        description="Owner's slot status for this session on the requested date; null when slots were not checked.")
    oneDay: bool = Field(default=False, description=(  # noqa: N815
        "A session the desk added for the requested date only; not part of the regular schedule."))


class BoardSessionOut(_Out):
    session: str | None
    status: contract.AvailabilityStatus
    expectedTime: str | None = None  # noqa: N815
    expectedEndTime: str | None = None  # noqa: N815
    delayMinutes: int | None = None  # noqa: N815
    note: str | None = None
    isStale: bool  # noqa: N815
    decision: Decision
    reason: Reason | None = None
    openSlots: list[SlotOut] | None = Field(default=None, description=_OPEN_SLOTS_DESCRIPTION)  # noqa: N815


def session_out(s: SessionDecision, requested: RequestedDate | None):
    slots = None if s.open_slots is None else [SlotOut(start=b.start, end=b.end, available=b.available)
                                              for b in s.open_slots]
    if s.basis == Basis.LIVE_BOARD:
        return BoardSessionOut(session=s.label, status=s.owner_status, decision=s.decision, reason=s.reason,
                                        expectedTime=s.start, expectedEndTime=s.end, delayMinutes=s.delay_minutes,
                                        note=s.note, isStale=s.is_stale, openSlots=slots)
    return UsualSessionOut(label=s.label, daysOfWeek=list(s.days), start=s.start, end=s.end,
                                    onRequestedDate=on_requested_date(s, requested) if requested else None,
                                    decision=s.decision, reason=s.reason, openSlots=slots,
                                    status=s.owner_status, oneDay=s.one_day)



class DoctorAvailability(_Out):
    doctorId: str  # noqa: N815
    name: str
    departments: list[str]
    attendanceType: contract.AttendanceType  # noqa: N815
    gender: str | None = None
    dataConfirmed: bool | None = None  # noqa: N815
    usualSessions: list[UsualSessionOut] | None = Field(  # noqa: N815
        description="Requested-date sessions with their slot status and desk-added one-day sessions, "
                    "or usual working hours for WORKING_HOURS. null when these session facts were not fetched.")
    board: list[BoardSessionOut]
    decision: Decision
    reason: Reason | None = None
    sessionChoiceRequired: bool = False  # noqa: N815


class DoctorChoice(_Out):
    doctorId: str  # noqa: N815
    name: str
    departments: list[str]
    gender: str | None = None


class DepartmentChoice(_Out):
    id: str
    name: str


AvailabilityOutcome = Literal[
    "AVAILABILITY", "CLARIFICATION_NEEDED", "CALLBACK_REQUIRED",
    "NOT_FOUND", "COULD_NOT_CHECK", "INVALID_REQUEST",
    "NOT_AVAILABLE", "WORKING_HOURS", "HANDOFF_REQUIRED", "DOCTORS_MATCHED",
]
NextStep = Literal[
    "OFFER_APPOINTMENT_REQUEST", "ASK_WHICH_DOCTOR", "ASK_WHICH_DEPARTMENT", "ASK_CALLBACK_DETAILS",
    "TRANSFER_DESK", "ASK_TO_REPHRASE", "SAY_COULD_NOT_CHECK",
    "ASK_EXPLICIT_DATE", "ASK_WHICH_SESSION", "OFFER_OTHER_SESSION_OR_DATE", "PRESENT_WORKING_HOURS",
]


class AvailabilityResult(_Out):
    outcome: AvailabilityOutcome
    nextStep: NextStep  # noqa: N815
    facilityToday: str  # noqa: N815
    requestedDate: str | None = None  # noqa: N815
    weekday: str | None = None
    department: DepartmentChoice | None = None
    doctors: list[DoctorAvailability] = []
    choices: list[DoctorChoice] = Field(default=[], description=(
        "Doctors matching a doctorName with several directory matches, capped by the configured limit; "
        "a doctorId from here gives a doctor-specific result."))
    departmentChoices: list[DepartmentChoice] = Field(default=[], description=(  # noqa: N815
        "Departments with consultants, returned when departmentName or departmentId matched none or several; "
        "a departmentId from here gives a department result."))
    complete: bool = Field(default=True,
                           description="Every directory candidate was evaluated; no failed or unchecked reads.")
    totalMatches: int | None = Field(default=None,  # noqa: N815
                                    description="Directory count across all attendance types and decisions.")  # noqa: N815
    bookableFound: int = Field(default=0,  # noqa: N815
                               description="Bookable doctors found among those checked; may exceed the capped list. "
                                           "Always zero for WORKING_HOURS.")  # noqa: N815
    basis: Basis | None = None
    sessionMatched: bool | None = None  # noqa: N815
    callback: Callback | None = None
    detail: str | None = Field(default=None, description="Machine-readable reason for non-success outcomes.")
    retryAfterSeconds: int | None = None  # noqa: N815


# ---------------------------------------------------------------------------------- manage_booking


class AppointmentOut(_Out):
    """Appointment request data, excluding contact numbers and reason text."""

    appointmentId: str  # noqa: N815
    status: contract.AppointmentStatus
    visitDate: str  # noqa: N815
    expectedTime: str | None = None  # noqa: N815
    doctorId: str | None = None  # noqa: N815
    department: str | None = None
    patientName: str  # noqa: N815
    slotTime: str | None = Field(default=None, pattern=contract.APPROX_TIME_PATTERN, description=(  # noqa: N815
        "Time recorded for this request in HH:MM facility local time: the owner's slotTime (block start), "
        "otherwise the request's expectedTime, otherwise null."))
    slotMoved: bool = Field(default=False, description=(  # noqa: N815
        "True only when the owner moved CREATE or RESCHEDULE to a different block, for example for a late doctor "
        "or a passed time. Choosing 10:45 and receiving its 10:30 block start is not moved. "
        "False for LIST and CANCEL."))


BookingOutcome = Literal[
    "NOTED", "CHANGED", "CANCELLED", "FOUND", "NOT_FOUND", "REJECTED", "CONFLICT", "UNCERTAIN",
    "CALLBACK_REQUIRED", "NOT_AVAILABLE", "HANDOFF_REQUIRED",
    "CONFIRMATION_REQUIRED", "OPERATION_CONTEXT_MISSING", "COULD_NOT_RECORD", "COULD_NOT_CHECK", "INVALID_REQUEST",
]
BookingNextStep = Literal[
    "SAY_REQUEST_NOTED", "SAY_CHANGED", "SAY_CANCELLED", "OFFER_CHOICES", "SAY_NOT_FOUND", "ASK_TO_CORRECT",
    "SAY_UNCERTAIN_AND_TRANSFER", "TRANSFER_DESK",
    "ASK_CALLBACK_DETAILS", "ASK_CONFIRMATION", "SAY_COULD_NOT_RECORD", "SAY_COULD_NOT_CHECK",
    "ASK_WHICH_SESSION", "OFFER_OTHER_SESSION_OR_TIME", "OFFER_OTHER_SESSION_OR_DATE", "ASK_WHICH_TIME",
]


class BookingResult(_Out):
    sessions: list[BoardSessionOut | UsualSessionOut] = []
    outcome: BookingOutcome
    nextStep: BookingNextStep  # noqa: N815
    appointment: AppointmentOut | None = None
    appointments: list[AppointmentOut] = []
    fields: list[str] = Field(default=[], description="Request fields that were invalid or rejected.")
    callback: Callback | None = None
    detail: str | None = None
    retryAfterSeconds: int | None = None  # noqa: N815


# ----------------------------------------------------------------------------- record_call_summary


SummaryOutcome = Literal["SAVED", "ALREADY_SAVED", "INVALID_REQUEST", "NOT_CONFIRMED", "NOT_SAVED"]


class SummaryResult(_Out):
    outcome: SummaryOutcome
    fields: list[str] = Field(default_factory=list)

    @model_serializer(mode="wrap")
    def _wire(self, handler):
        result = handler(self)
        if self.outcome != "INVALID_REQUEST":
            result.pop("fields", None)
        return result
