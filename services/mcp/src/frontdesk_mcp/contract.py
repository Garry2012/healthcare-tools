"""Client-side types for Manoj's operational contract (docs/handover/mcp-only/contracts/).

These mirror the public OpenAPI components only: no server logic, no scheduling rules. Models
accept unknown fields (`extra="allow"`) so a compatible owner revision never breaks parsing, and
they enforce the fields the contract marks required. Tests pin the literals to the snapshot's
enums; a contract change is a reviewed change here, never a silent one.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MOBILE_PATTERN = "^[0-9]{10}$"
APPROX_TIME_PATTERN = "^([01][0-9]|2[0-3]):[0-5][0-9]$"

AvailabilityStatus = Literal["IN", "LATE", "CANCELLED", "NOT_CONFIRMED", "UNKNOWN"]
AppointmentStatus = Literal["NOTED", "CONFIRMED_BY_DESK", "CHANGED", "CANCELLED"]
AttendanceType = Literal["REGULAR", "VISITING", "ON_CALL"]
CallIntent = Literal[
    "AVAILABILITY", "BOOKING", "RESCHEDULE", "CANCEL", "GENERAL_INFO", "LAB", "INSURANCE", "EMERGENCY",
    "AMBULANCE", "SYMPTOM_ROUTING", "COMPLAINT", "ADMIN", "OTHER",
]
CallOutcome = Literal[
    "RESOLVED_BY_AGENT", "APPOINTMENT_NOTED", "APPOINTMENT_CANCELLED", "APPOINTMENT_RESCHEDULED", "TRANSFERRED",
    "EMERGENCY_TRANSFERRED", "AMBULANCE_NUMBER_GIVEN", "CALLBACK_NOTED", "ABANDONED",
]
ErrorCode = Literal[
    "VALIDATION_FAILED", "NOT_FOUND", "UNAUTHORIZED", "FORBIDDEN", "CONFLICT", "IDEMPOTENCY_CONFLICT",
    "RATE_LIMITED", "INTERNAL",
]
SummaryLanguage = Literal["EN", "KN", "HI"]
Weekday = Literal["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
Gender = Literal["FEMALE", "MALE"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)


class Money(_Model):
    amount: float
    currency: str


class DepartmentRef(_Model):
    id: str
    name: str


class Department(_Model):
    id: str
    name: str
    hasConsultant: bool  # noqa: N815 - wire names
    active: bool


class UsualSession(_Model):
    label: str | None = None
    daysOfWeek: list[Weekday]  # noqa: N815
    start: str = Field(pattern=APPROX_TIME_PATTERN)
    end: str = Field(pattern=APPROX_TIME_PATTERN)


class DoctorSummary(_Model):
    id: str
    name: str
    departments: list[DepartmentRef]
    attendanceType: AttendanceType  # noqa: N815
    gender: Gender | None = None
    qualification: str | None = None
    consultationFee: Money | None = None  # noqa: N815
    languages: list[str] = []
    active: bool


class DoctorDetail(DoctorSummary):
    usualSchedule: list[UsualSession] = []  # noqa: N815
    patientsPerHour: float | None = None  # noqa: N815 - never used to allocate anything
    dataConfirmed: bool | None = None  # noqa: N815


class DoctorPage(_Model):
    items: list[DoctorSummary]
    total: int


class DepartmentList(_Model):
    items: list[Department]


class AvailabilityEntry(_Model):
    doctorId: str  # noqa: N815
    doctorName: str  # noqa: N815
    date: date
    session: str | None = None
    status: AvailabilityStatus
    delayMinutes: int | None = None  # noqa: N815
    expectedTime: str | None = Field(default=None, pattern=APPROX_TIME_PATTERN)  # noqa: N815
    expectedEndTime: str | None = Field(default=None, pattern=APPROX_TIME_PATTERN)  # noqa: N815
    note: str | None = None
    lastUpdatedAt: datetime | None = None  # noqa: N815
    updatedBy: str | None = None  # noqa: N815
    source: str | None = None
    isStale: bool  # noqa: N815


class AvailabilityBoard(_Model):
    date: date
    items: list[AvailabilityEntry]


class CreatedBy(_Model):
    type: Literal["AGENT", "STAFF"]
    id: str | None = None


class Appointment(_Model):
    id: str
    patientName: str  # noqa: N815
    mobile: str
    doctorId: str | None = None  # noqa: N815
    department: str | None = None
    visitDate: date  # noqa: N815
    expectedTime: str | None = None  # noqa: N815
    reasonVerbatim: str | None = None  # noqa: N815
    status: AppointmentStatus
    callId: str | None = None  # noqa: N815
    createdAt: datetime  # noqa: N815
    createdBy: CreatedBy  # noqa: N815
    updatedAt: datetime | None = None  # noqa: N815


class AppointmentList(_Model):
    items: list[Appointment]


class CallSummary(_Model):
    id: str
    callId: str  # noqa: N815
    startedAt: datetime  # noqa: N815
    intent: CallIntent
    outcome: CallOutcome
    createdAt: datetime  # noqa: N815


class TokenResponse(_Model):
    access_token: str
    token_type: str
    expires_in: int


class ErrorDetail(_Model):
    field: str | None = None
    issue: str | None = None


class ErrorInfo(_Model):
    code: ErrorCode
    message: str | None = None
    details: list[ErrorDetail] = []


class ErrorBody(_Model):
    error: ErrorInfo

