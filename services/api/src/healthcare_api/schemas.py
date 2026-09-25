"""Wire models. Class names equal the OpenAPI component names in docs/frontdesk-api/openapi.yaml;
`tests/contract/test_openapi_matches_spec.py` fails if a required list or an enum drifts."""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pydantic.alias_generators import to_camel

ClockTime = Annotated[str, StringConstraints(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")]
Phone = Annotated[str, StringConstraints(pattern=r"^[0-9]{6,15}$")]
Language = str
LocalizedText = dict[str, str]


def _reject_nul(value: Any) -> None:
    if isinstance(value, str):
        if "\x00" in value:
            raise ValueError("text must not contain NUL characters")
    elif isinstance(value, dict):
        for key, item in value.items():
            _reject_nul(key)
            _reject_nul(item)
    elif isinstance(value, list | tuple):
        for item in value:
            _reject_nul(item)


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    @model_validator(mode="before")
    @classmethod
    def _no_nul(cls, data: Any) -> Any:
        # PostgreSQL text cannot hold NUL; reject it as a validation error, not a 500.
        _reject_nul(data)
        return data


# ---------------------------------------------------------------- enums


class Gender(StrEnum):
    FEMALE = "FEMALE"
    MALE = "MALE"


class DayOfWeek(StrEnum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"
    SUN = "SUN"


class DayPart(StrEnum):
    MORNING = "MORNING"
    AFTERNOON = "AFTERNOON"
    EVENING = "EVENING"
    ANY = "ANY"


class LexiconConceptType(StrEnum):
    DEPARTMENT = "DEPARTMENT"
    DOCTOR = "DOCTOR"
    SYMPTOM_ROUTE = "SYMPTOM_ROUTE"
    RED_FLAG = "RED_FLAG"
    DAY_PART = "DAY_PART"
    SERVICE_TRANSFER = "SERVICE_TRANSFER"


class Presence(StrEnum):
    NOT_ARRIVED = "NOT_ARRIVED"
    ARRIVING = "ARRIVING"
    PRESENT = "PRESENT"
    LEFT = "LEFT"


class TimingCertainty(StrEnum):
    CONFIRMED = "CONFIRMED"
    EXPECTED = "EXPECTED"
    NOT_CONFIRMED = "NOT_CONFIRMED"


class NotBookableReason(StrEnum):
    SESSION_ENDED = "SESSION_ENDED"
    LEFT_FOR_DAY = "LEFT_FOR_DAY"
    ARRIVE_BY_PASSED = "ARRIVE_BY_PASSED"
    FULL = "FULL"
    CANCELLED = "CANCELLED"
    NO_SESSION_THAT_DAY = "NO_SESSION_THAT_DAY"
    ON_CALL_ONLY = "ON_CALL_ONLY"
    DESK_ONLY = "DESK_ONLY"
    NO_OPD = "NO_OPD"


class AppointmentStatus(StrEnum):
    BOOKED = "BOOKED"
    CONFIRMED_BY_DESK = "CONFIRMED_BY_DESK"
    RESCHEDULED = "RESCHEDULED"
    NEEDS_RESCHEDULE = "NEEDS_RESCHEDULE"
    ARRIVED = "ARRIVED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED_BY_PATIENT = "CANCELLED_BY_PATIENT"
    CANCELLED_BY_HOSPITAL = "CANCELLED_BY_HOSPITAL"


Attendance = Literal["REGULAR", "VISITING", "ON_CALL"]
BookingPolicy = Literal["BOOKABLE", "DESK_ONLY", "NO_OPD"]
CapacityModel = Literal["SEQUENCE", "TIMED"]
Relation = Literal["SELF", "CHILD", "PARENT", "SPOUSE", "OTHER"]
NotificationStatus = Literal["PENDING", "SENT", "FAILED", "ACKNOWLEDGED"]
Channel = Literal["PHONE", "SMS", "WHATSAPP", "IN_PERSON", "VOICE_BOT"]
DeliveryOutcome = Literal["INFORMED", "RESCHEDULED", "CANCELLED", "NO_ANSWER"]
ErrorCode = Literal[
    "VALIDATION_FAILED", "NOT_FOUND", "UNAUTHORIZED", "FORBIDDEN", "CONFLICT",
    "IDEMPOTENCY_CONFLICT", "SLOT_UNAVAILABLE", "RATE_LIMITED", "INTERNAL",
    "SERVICE_UNAVAILABLE", "UPSTREAM_TIMEOUT",
]


# ---------------------------------------------------------------- primitives / directory


class Money(ApiModel):
    amount: Annotated[float, Field(ge=0, le=10_000_000)]
    currency: str
    confirmed: bool


class Department(ApiModel):
    id: str
    code: str | None = None
    name: str
    localized_names: LocalizedText | None = None
    has_consultant: bool
    active: bool


class Doctor(ApiModel):
    id: str
    name: str
    localized_names: LocalizedText | None = None
    name_variants: list[str] | None = None
    gender: Gender | None = None
    departments: list[Department]
    qualification: str | None = None
    years_of_experience: int | None = None
    languages_spoken: list[Language] | None = None
    fee: Money | None = None
    attendance_type: Attendance | None = None
    booking_policy: BookingPolicy | None = None
    data_confirmed: bool
    active: bool


class DoctorInput(ApiModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    localized_names: LocalizedText | None = None
    name_variants: list[str] | None = None
    gender: Gender | None = None
    department_ids: Annotated[list[str], Field(min_length=1)]
    qualification: str | None = None
    years_of_experience: Annotated[int, Field(ge=0, le=80)] | None = None
    languages_spoken: list[Language] | None = None
    fee: Money | None = None
    attendance_type: Attendance | None = None
    booking_policy: BookingPolicy | None = None
    data_confirmed: bool | None = None
    active: bool | None = None


class LexiconEntry(ApiModel):
    id: str
    concept_type: LexiconConceptType
    concept_id: str
    term: str
    term_normalized: str | None = None
    language: Language
    approved: bool
    source: Literal["HOSPITAL", "TRANSCRIPT_MINED", "AUTO_TRANSLITERATION"] | None = None


class LexiconEntryInput(ApiModel):
    concept_type: LexiconConceptType
    concept_id: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    term: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    language: Annotated[str, StringConstraints(min_length=2, max_length=16)]
    approved: bool = False


# ---------------------------------------------------------------- scheduling


class CapacitySpec(ApiModel):
    mode: Literal["FIXED", "PER_HOUR", "DEFAULT"]
    value: Annotated[int, Field(ge=1, le=1000)] | None = None


class TemplateSession(ApiModel):
    template_session_id: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    label: str | None = None
    days_of_week: Annotated[list[DayOfWeek], Field(min_length=1)]
    start: ClockTime
    end: ClockTime
    capacity_model: CapacityModel
    slot_minutes: Annotated[int, Field(ge=1, le=480)] | None = None
    capacity: CapacitySpec
    walk_in_reserve_percent: Annotated[int, Field(ge=0, le=100)] = 0
    last_arrival_offset_minutes: Annotated[int, Field(ge=0, le=720)] = 15


class ScheduleTemplate(ApiModel):
    doctor_id: str
    effective_from: dt.date
    effective_to: dt.date | None = None
    sessions: list[TemplateSession]


ExceptionScope = Literal["WHOLE_DAY", "SESSION", "TIME_RANGE"]
ExceptionEffect = Literal[
    "UNAVAILABLE", "TIME_CHANGE", "CAPACITY_CHANGE", "EXTRA_SESSION", "TIMING_PENDING",
    "TIMING_CONFIRMED",
]
ReasonCategory = Literal["LEAVE", "SURGERY", "CONFERENCE", "PERSONAL", "EMERGENCY_DUTY", "OTHER"]


class ScheduleExceptionInput(ApiModel):
    doctor_id: str
    date_from: dt.date
    date_to: dt.date
    scope: ExceptionScope
    template_session_id: str | None = None
    effect: ExceptionEffect
    new_start: ClockTime | None = None
    new_end: ClockTime | None = None
    new_capacity: Annotated[int, Field(ge=0, le=1000)] | None = None
    reason_category: ReasonCategory | None = None
    note: Annotated[str, StringConstraints(max_length=500)] | None = None


class ExceptionImpact(ApiModel):
    appointments_impacted: int
    notifications_created: int


class ScheduleException(ScheduleExceptionInput):
    id: str
    created_at: dt.datetime
    created_by: str
    impact: ExceptionImpact


class BoardEntryInput(ApiModel):
    date: dt.date
    session_id: str
    presence: Presence | None = None
    expected_start: ClockTime | None = None
    delay_minutes: Annotated[int, Field(ge=0, le=720)] | None = None
    session_ended: bool | None = None
    capacity_state: Literal["OPEN", "FULL"] | None = None
    tokens_issued: Annotated[int, Field(ge=0, le=100000)] | None = None
    last_arrival_time: ClockTime | None = None
    timing_confirmed: bool | None = None


class BoardEntry(BoardEntryInput):
    updated_at: dt.datetime
    updated_by: str


# ---------------------------------------------------------------- availability


class Window(ApiModel):
    from_: ClockTime | None = Field(default=None, alias="from")
    to: ClockTime | None = None


class Slot(ApiModel):
    slot_id: str
    kind: CapacityModel
    position: Annotated[int, Field(ge=1)] | None = None
    start: ClockTime | None = None
    end: ClockTime | None = None
    expected_window: Window | None = None
    available: bool


class SessionCapacity(ApiModel):
    total: int
    booked: int
    remaining: int
    walk_in_reserve: int | None = None
    capacity_source: Literal["FIXED", "PER_HOUR", "DEFAULT"] | None = None


class SessionInstance(ApiModel):
    session_id: str
    doctor_id: str
    template_session_id: str | None = None
    date: dt.date
    label: str | None = None
    start: ClockTime
    end: ClockTime
    status: Literal["SCHEDULED", "CHANGED", "CANCELLED", "ENDED"]
    timing_certainty: TimingCertainty
    presence: Presence | None = None
    expected_start: ClockTime | None = None
    delay_minutes: int | None = None
    capacity_model: CapacityModel
    capacity: SessionCapacity
    arrive_by: ClockTime | None = None
    bookable: bool
    not_bookable_reason: NotBookableReason | None = None
    slots: list[Slot] | None = None


class AvailabilityList(ApiModel):
    as_of: dt.datetime
    items: list[SessionInstance]


# ---------------------------------------------------------------- agent facade


class When(ApiModel):
    expression: Annotated[str, StringConstraints(max_length=100)] | None = None
    date_from: dt.date | None = None
    date_to: dt.date | None = None
    day_part: DayPart | None = None


class Preferences(ApiModel):
    gender: Gender | None = None
    language: Language | None = None


class AvailabilitySearchRequest(ApiModel):
    utterance: Annotated[str, StringConstraints(max_length=500)]
    language: Language
    doctor_name: Annotated[str, StringConstraints(max_length=100)] | None = None
    department: Annotated[str, StringConstraints(max_length=100)] | None = None
    symptom_text: Annotated[str, StringConstraints(max_length=300)] | None = None
    when: When | None = None
    preferences: Preferences | None = None
    max_doctors: Annotated[int, Field(ge=1, le=5)] = 3
    max_slots_per_session: Annotated[int, Field(ge=1, le=5)] = 3


class UnderstoodDoctor(ApiModel):
    doctor_id: str
    name: str
    localized_names: LocalizedText | None = None
    confidence: Annotated[float, Field(ge=0, le=1)]
    matched_on: Literal["NAME_EXACT", "NAME_PHONETIC", "NAME_VARIANT", "LEXICON"]


class UnderstoodDepartment(ApiModel):
    id: str
    name: str
    localized_names: LocalizedText | None = None
    confidence: Annotated[float, Field(ge=0, le=1)]
    matched_on: Literal["LEXICON", "SYMPTOM_ROUTE", "SEMANTIC"]


class DateRange(ApiModel):
    from_: dt.date | None = Field(default=None, alias="from")
    to: dt.date | None = None


class Understood(ApiModel):
    doctors: list[UnderstoodDoctor]
    departments: list[UnderstoodDepartment]
    dates: DateRange | None = None
    day_part: DayPart | None = None


class Routing(ApiModel):
    action: Literal["OFFER_SLOTS", "CLARIFY", "TRANSFER_EMERGENCY", "TRANSFER_DESK", "NO_SERVICE"]
    destination: str | None = None


class ClarificationOption(ApiModel):
    id: str
    label: str
    localized_labels: LocalizedText | None = None
    detail: str | None = None


class Clarification(ApiModel):
    type: Literal[
        "WHICH_DOCTOR", "WHICH_DEPARTMENT", "WHICH_DATE", "WHICH_PATIENT", "CONFIRM_INTERPRETATION"
    ]
    options: list[ClarificationOption]


class ResultDoctor(ApiModel):
    doctor_id: str
    name: str
    localized_names: LocalizedText | None = None
    departments: list[Department]
    gender: Gender | None = None
    qualification: str | None = None
    fee: Money | None = None
    data_confirmed: bool


class NextBookable(ApiModel):
    date: dt.date | None = None
    start: ClockTime | None = None
    end: ClockTime | None = None


class UnavailableSession(ApiModel):
    date: dt.date
    session_id: str | None = None
    reason: NotBookableReason
    next_bookable: NextBookable | None = None


class DoctorResult(ApiModel):
    doctor: ResultDoctor
    sessions: list[SessionInstance]
    unavailable: list[UnavailableSession]


class AvailabilitySearchResponse(ApiModel):
    outcome: Literal["FOUND", "NONE_AVAILABLE", "CLARIFICATION_NEEDED", "TRANSFER", "COULD_NOT_CHECK"]
    as_of: dt.datetime
    routing: Routing
    understood: Understood
    clarification: Clarification | None = None
    results: list[DoctorResult]
    alternatives: list[DoctorResult]
    partial: bool | None = None
    notes: list[str] | None = None


class BookPatient(ApiModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    phone: Phone
    relation_to_caller: Relation | None = None


class AgentBookRequest(ApiModel):
    slot_id: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    patient: BookPatient
    reason_verbatim: Annotated[str, StringConstraints(max_length=500)] | None = None
    language: Language
    request_timing_confirmation: bool = False


class PatientSummary(ApiModel):
    name: str | None = None
    phone: Phone | None = None


class DoctorSummary(ApiModel):
    doctor_id: str | None = None
    name: str | None = None
    localized_names: LocalizedText | None = None


class SessionSummary(ApiModel):
    session_id: str | None = None
    label: str | None = None
    start: ClockTime | None = None
    end: ClockTime | None = None


class AgentAppointment(ApiModel):
    outcome: Literal["BOOKED", "ALREADY_BOOKED", "CANCELLED", "RESCHEDULED", "FOUND"]
    appointment_id: str
    confirmation_code: str | None = None
    status: AppointmentStatus
    patient: PatientSummary
    doctor: DoctorSummary
    department: Department | None = None
    date: dt.date
    session: SessionSummary
    slot: Slot
    previous_slot: Slot | None = None
    arrive_by: ClockTime | None = None
    timing_certainty: TimingCertainty
    fee: Money | None = None
    follow_up: Literal["NONE", "DESK_WILL_CONFIRM_TIMING"] | None = None
    doctor_today: SessionInstance | None = None


class AgentAppointmentList(ApiModel):
    outcome: Literal["FOUND", "NONE_FOUND", "NAME_REQUIRED", "IDENTITY_UNAVAILABLE"]
    items: list[AgentAppointment]
    patients_on_number: int
    identity_basis: Literal["CALLER_NUMBER", "SPOKEN_NUMBER", "NONE"]


class CancelRequest(ApiModel):
    patient_name: Annotated[str, StringConstraints(max_length=100)]
    reason_verbatim: Annotated[str, StringConstraints(max_length=500)] | None = None


class RescheduleRequest(ApiModel):
    patient_name: Annotated[str, StringConstraints(max_length=100)]
    new_slot_id: str


# ---------------------------------------------------------------- staff appointments


class AppointmentPatient(ApiModel):
    name: str
    phone: Phone
    relation_to_caller: str | None = None


class HistoryItem(ApiModel):
    at: dt.datetime | None = None
    by: str | None = None
    change: str | None = None


class Appointment(ApiModel):
    id: str
    confirmation_code: str | None = None
    status: AppointmentStatus
    patient: AppointmentPatient
    caller_number: str | None = None
    doctor_id: str
    session_id: str
    slot_id: str
    date: dt.date
    slot: Slot | None = None
    arrive_by: ClockTime | None = None
    timing_certainty: TimingCertainty | None = None
    confirmed_start: ClockTime | None = None
    reason_verbatim: str | None = None
    language: Language | None = None
    created_via: Literal["AGENT", "DESK", "WEB"]
    call_id: str | None = None
    created_at: dt.datetime
    updated_at: dt.datetime | None = None
    history: list[HistoryItem] | None = None


class AppointmentPage(ApiModel):
    items: list[Appointment]
    total: int


class ConfirmRequest(ApiModel):
    confirmed_start: ClockTime | None = None
    apply_to_session: bool = False


class StatusRequest(ApiModel):
    status: Literal["ARRIVED", "COMPLETED", "NO_SHOW", "CANCELLED_BY_HOSPITAL"]
    note: Annotated[str, StringConstraints(max_length=500)] | None = None


class Notification(ApiModel):
    id: str
    appointment_id: str
    trigger: Literal["SESSION_CANCELLED", "SESSION_TIME_CHANGED", "TEMPLATE_CHANGED", "DESK_MESSAGE"]
    status: NotificationStatus
    channel: Channel | None = None
    patient_phone: Phone | None = None
    patient_language: Language | None = None
    facts: dict[str, Any] | None = None
    created_at: dt.datetime
    delivered_at: dt.datetime | None = None
    outcome: DeliveryOutcome | None = None


class ImpactedAppointment(ApiModel):
    appointment: Appointment
    notification: Notification


class ImpactList(ApiModel):
    exception_id: str
    items: list[ImpactedAppointment]


class DeliveredRequest(ApiModel):
    channel: Channel
    outcome: DeliveryOutcome | None = None
    note: Annotated[str, StringConstraints(max_length=500)] | None = None


# ---------------------------------------------------------------- lists


class DepartmentList(ApiModel):
    items: list[Department]


class DoctorPage(ApiModel):
    items: list[Doctor]
    total: int


class LexiconList(ApiModel):
    items: list[LexiconEntry]


class ExceptionList(ApiModel):
    items: list[ScheduleException]


class BoardView(ApiModel):
    doctor_id: str
    date: dt.date
    sessions: list[BoardEntry]


class NotificationList(ApiModel):
    items: list[Notification]


# ---------------------------------------------------------------- calls


class CallSummary(ApiModel):
    id: str | None = None
    call_id: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    started_at: dt.datetime
    duration_seconds: Annotated[int, Field(ge=0, le=86400)] | None = None
    language: Language | None = None
    caller_number: str | None = None
    intent: Literal[
        "AVAILABILITY", "BOOKING", "RESCHEDULE", "CANCEL", "LOOKUP", "GENERAL_INFO", "LAB",
        "PHARMACY", "INSURANCE", "EMERGENCY", "SYMPTOM_ROUTING", "ADMIN", "OTHER",
    ]
    outcome: Literal[
        "RESOLVED_BY_AGENT", "APPOINTMENT_BOOKED", "APPOINTMENT_CANCELLED",
        "APPOINTMENT_RESCHEDULED", "TRANSFERRED", "EMERGENCY_TRANSFERRED", "ABANDONED",
    ]
    transferred_to: str | None = None
    appointment_id: str | None = None
    tool_outcomes: dict[str, str] | None = None
    summary_text: Annotated[str, StringConstraints(max_length=500)] | None = None


class CallSummaryPage(ApiModel):
    items: list[CallSummary]
    total: int


# ---------------------------------------------------------------- errors


class ErrorDetail(ApiModel):
    field: str | None = None
    issue: str | None = None


class ErrorBody(ApiModel):
    code: ErrorCode
    message: str
    details: list[ErrorDetail] | None = None
    current_slots: list[Slot] | None = None


class Error(ApiModel):
    error: ErrorBody
