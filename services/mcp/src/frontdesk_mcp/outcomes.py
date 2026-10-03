"""Model-facing result envelopes: compact, typed, complete. They preserve status, ambiguity, completeness
and the next step; they never carry raw upstream prose, patient contact data from other callers, or
invented slots/capacity. These are MCP schema choices; the owner contracts' statuses are untouched."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from . import contract
from . import knowledge_contract as kc


class _Out(BaseModel):
    model_config = ConfigDict(frozen=True)


class Speech(_Out):
    text: str
    language: str


class Routing(_Out):
    decision: kc.RoutingDecision
    speak: Speech | None = None
    department: str | None = None


class Callback(_Out):
    """Callback metadata for UNKNOWN availability; summary outcome is CALLBACK_NOTED."""

    ask: str = "May I have your name and a callback number?"
    say: str = "Someone from the hospital will call you back."
    summaryOutcome: Literal["CALLBACK_NOTED"] = "CALLBACK_NOTED"  # noqa: N815 - wire names


class UsualSessionOut(_Out):
    label: str | None
    daysOfWeek: list[str]  # noqa: N815
    start: str
    end: str
    onRequestedDate: bool  # noqa: N815


class BoardSessionOut(_Out):
    session: str | None
    status: contract.AvailabilityStatus
    expectedTime: str | None = None  # noqa: N815
    expectedEndTime: str | None = None  # noqa: N815
    delayMinutes: int | None = None  # noqa: N815
    note: str | None = None
    isStale: bool  # noqa: N815
    expired: bool = Field(description="expectedEndTime has passed in facility time on the requested date.")


Journey = Literal["APPOINTMENT_REQUEST", "CALLBACK_ONLY", "DESK"]


class DoctorAvailability(_Out):
    doctorId: str  # noqa: N815
    name: str
    departments: list[str]
    attendanceType: contract.AttendanceType  # noqa: N815
    gender: str | None = None
    dataConfirmed: bool | None = None  # noqa: N815
    usualSessions: list[UsualSessionOut] | None = Field(  # noqa: N815
        description="Usual working hours, independent of live attendance. null when the profile was not fetched.")
    board: list[BoardSessionOut]
    unknownSessions: list[str] = []  # noqa: N815
    journey: Journey


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
]
NextStep = Literal[
    "OFFER_APPOINTMENT_REQUEST", "ASK_WHICH_DOCTOR", "ASK_WHICH_DEPARTMENT", "ASK_CALLBACK_DETAILS",
    "TRANSFER_DESK", "ASK_TO_REPHRASE", "SAY_COULD_NOT_CHECK",
    "ASK_EXPLICIT_DATE",
]


class AvailabilityResult(_Out):
    outcome: AvailabilityOutcome
    nextStep: NextStep  # noqa: N815
    facilityToday: str  # noqa: N815
    requestedDate: str | None = None  # noqa: N815
    weekday: str | None = None
    department: DepartmentChoice | None = None
    doctors: list[DoctorAvailability] = []
    choices: list[DoctorChoice] = []
    departmentChoices: list[DepartmentChoice] = []  # noqa: N815
    complete: bool = True
    totalMatches: int | None = None  # noqa: N815
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


BookingOutcome = Literal[
    "NOTED", "CHANGED", "CANCELLED", "FOUND", "NOT_FOUND", "REJECTED", "CONFLICT", "UNCERTAIN",
    "IDENTITY_UNAVAILABLE", "CALLBACK_REQUIRED",
    "CONFIRMATION_REQUIRED", "OPERATION_CONTEXT_MISSING", "COULD_NOT_RECORD", "COULD_NOT_CHECK", "INVALID_REQUEST",
]
BookingNextStep = Literal[
    "SAY_REQUEST_NOTED", "SAY_CHANGED", "SAY_CANCELLED", "OFFER_CHOICES", "SAY_NOT_FOUND", "ASK_TO_CORRECT",
    "SAY_UNCERTAIN_AND_TRANSFER", "TRANSFER_DESK",
    "ASK_CALLBACK_DETAILS", "ASK_CONFIRMATION", "SAY_COULD_NOT_RECORD", "SAY_COULD_NOT_CHECK",
]


class BookingResult(_Out):
    outcome: BookingOutcome
    nextStep: BookingNextStep  # noqa: N815
    appointment: AppointmentOut | None = None
    appointments: list[AppointmentOut] = []
    fields: list[str] = Field(default=[], description="Request fields that were invalid or rejected.")
    callback: Callback | None = None
    detail: str | None = None
    retryAfterSeconds: int | None = None  # noqa: N815


# -------------------------------------------------------------------------------- search_knowledge


KnowledgeOutcome = Literal["ANSWERED", "NO_ANSWER", "CLARIFICATION_NEEDED", "ROUTING_REQUIRED",
                           "COULD_NOT_CHECK", "INVALID_REQUEST"]
KnowledgeNextStep = Literal["SPEAK_ANSWER", "SAY_NO_ANSWER_AND_OFFER_DESK", "ASK_CLARIFICATION", "TRANSFER_DESK",
                            "TRANSFER_EMERGENCY", "CHECK_AVAILABILITY", "SAY_COULD_NOT_CHECK", "ASK_TO_REPHRASE"]


class KnowledgeResult(_Out):
    outcome: KnowledgeOutcome
    nextStep: KnowledgeNextStep  # noqa: N815
    answer: Speech | None = Field(default=None, description="Knowledge-service answer or clarification text.")
    sourceId: str | None = None  # noqa: N815
    destination: str | None = None
    routing: Routing | None = Field(default=None, description="The owner's routing decision over the caller's words.")
    detail: str | None = None


# ----------------------------------------------------------------------------- record_call_summary


SummaryOutcome = Literal["STORED", "REPLAYED", "REJECTED", "CONFLICT", "UNCERTAIN", "COULD_NOT_RECORD",
                         "INVALID_REQUEST", "LIFECYCLE_CONTEXT_MISSING"]


class SummaryResult(_Out):
    outcome: SummaryOutcome
    nextStep: Literal["DONE", "RETRY_SAME_PAYLOAD", "FIX_PLATFORM_INPUT", "RECORD_FAILED"]  # noqa: N815
    summaryId: str | None = None  # noqa: N815
    fields: list[str] = []
    detail: str | None = None
    retryAfterSeconds: int | None = None  # noqa: N815
