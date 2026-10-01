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
    """The UNKNOWN policy: collect name and number, say someone will call back, record a summary only."""

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
        description="Background hours only, never today's position. null when the profile was not fetched.")
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
    "AVAILABILITY", "CLARIFICATION_NEEDED", "CALLBACK_REQUIRED", "ROUTING_REQUIRED", "ROUTING_UNAVAILABLE",
    "NOT_FOUND", "COULD_NOT_CHECK", "INVALID_REQUEST",
]
NextStep = Literal[
    "OFFER_APPOINTMENT_REQUEST", "ASK_WHICH_DOCTOR", "ASK_WHICH_DEPARTMENT", "ASK_CALLBACK_DETAILS",
    "TRANSFER_EMERGENCY", "TRANSFER_DESK", "ASK_ROUTING_CLARIFICATION", "ASK_TO_REPHRASE", "SAY_COULD_NOT_CHECK",
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
    routing: Routing | None = None
    callback: Callback | None = None
    detail: str | None = Field(default=None, description="Machine-readable reason for non-success outcomes.")
    retryAfterSeconds: int | None = None  # noqa: N815
