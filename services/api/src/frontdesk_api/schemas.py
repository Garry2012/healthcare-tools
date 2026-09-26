"""Wire models. Class names equal the OpenAPI component names in docs/frontdesk-api/openapi.yaml;
`tests/contract/test_openapi_matches_spec.py` fails if a required list or an enum drifts."""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pydantic.alias_generators import to_camel

ClockTime = Annotated[str, StringConstraints(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")]
Phone = Annotated[str, StringConstraints(pattern=r"^[0-9]{6,15}$")]
Language = str
LocalizedText = dict[str, str]
# Domain-pack facts about a resource, e.g. {"qualification": "MBBS, MD"} in healthcare.
Attributes = dict[str, str | int | float | bool]


MAX_DEPTH = 32
# Every date the API accepts or stores; outside it an input is a mistake (or an attack), and
# date arithmetic near year 9999 overflows.
EARLIEST, LATEST = dt.date(2000, 1, 1), dt.date(2100, 12, 31)


def _reject_nul(value: Any) -> None:
    """Iterative walk (a deeply nested body must be a 400, not a RecursionError)."""
    stack: list[tuple[Any, int]] = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        if depth > MAX_DEPTH:
            raise ValueError(f"request nests deeper than {MAX_DEPTH} levels")
        if isinstance(item, str):
            if "\x00" in item:
                raise ValueError("text must not contain NUL characters")
        elif isinstance(item, dict):
            stack.extend((x, depth + 1) for pair in item.items() for x in pair)
        elif isinstance(item, list | tuple):
            stack.extend((x, depth + 1) for x in item)


def in_range(value: dt.date) -> dt.date:
    day = value.date() if isinstance(value, dt.datetime) else value
    if not EARLIEST <= day <= LATEST:
        raise ValueError(f"date must be between {EARLIEST} and {LATEST}")
    return value


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    @model_validator(mode="before")
    @classmethod
    def _no_nul(cls, data: Any) -> Any:
        # PostgreSQL text cannot hold NUL; reject it as a validation error, not a 500.
        _reject_nul(data)
        return data

    @model_validator(mode="after")
    def _dates_in_range(self) -> ApiModel:
        for name in type(self).model_fields:
            value = getattr(self, name)
            if isinstance(value, dt.date):
                try:
                    in_range(value)
                except ValueError as exc:
                    raise ValueError(f"{name}: {exc}") from None
        return self


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
    CATEGORY = "CATEGORY"
    RESOURCE = "RESOURCE"
    NEED_ROUTE = "NEED_ROUTE"
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
    NO_SESSION_IN_DAY_PART = "NO_SESSION_IN_DAY_PART"
    ON_CALL_ONLY = "ON_CALL_ONLY"
    DESK_ONLY = "DESK_ONLY"
    NOT_OFFERED = "NOT_OFFERED"


class BookingStatus(StrEnum):
    BOOKED = "BOOKED"
    CONFIRMED_BY_DESK = "CONFIRMED_BY_DESK"
    RESCHEDULED = "RESCHEDULED"
    NEEDS_RESCHEDULE = "NEEDS_RESCHEDULE"
    ARRIVED = "ARRIVED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED_BY_CUSTOMER = "CANCELLED_BY_CUSTOMER"
    CANCELLED_BY_PROVIDER = "CANCELLED_BY_PROVIDER"


Attendance = Literal["REGULAR", "VISITING", "ON_CALL"]
BookingPolicy = Literal["BOOKABLE", "DESK_ONLY", "NOT_OFFERED"]
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


class Category(ApiModel):
    id: str
    code: str | None = None
    name: str
    localized_names: LocalizedText | None = None
    offers_bookings: bool
    active: bool


class CategoryInput(ApiModel):
    code: Annotated[str, StringConstraints(max_length=20)] | None = None
    name: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    localized_names: LocalizedText | None = None
    offers_bookings: bool = True
    active: bool = True


class Resource(ApiModel):
    id: str
    name: str
    localized_names: LocalizedText | None = None
    name_variants: list[str] | None = None
    gender: Gender | None = None
    categories: list[Category]
    attributes: Attributes | None = None
    languages_spoken: list[Language] | None = None
    price: Money | None = None
    attendance_type: Attendance | None = None
    booking_policy: BookingPolicy | None = None
    data_confirmed: bool
    active: bool


class ResourceInput(ApiModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    localized_names: LocalizedText | None = None
    name_variants: list[str] | None = None
    gender: Gender | None = None
    category_ids: Annotated[list[str], Field(min_length=1)]
    attributes: Attributes | None = None
    languages_spoken: list[Language] | None = None
    price: Money | None = None
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
    source: Literal["PROVIDER", "TRANSCRIPT_MINED", "AUTO_TRANSLITERATION"] | None = None


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
    resource_id: str
    effective_from: dt.date
    effective_to: dt.date | None = None
    sessions: list[TemplateSession]


ExceptionScope = Literal["WHOLE_DAY", "SESSION", "TIME_RANGE"]
ExceptionEffect = Literal[
    "UNAVAILABLE", "TIME_CHANGE", "CAPACITY_CHANGE", "EXTRA_SESSION", "TIMING_PENDING",
    "TIMING_CONFIRMED",
]
ReasonCategory = Literal["LEAVE", "OTHER_DUTY", "EVENT", "PERSONAL", "OTHER"]


class ScheduleExceptionInput(ApiModel):
    resource_id: str
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
    bookings_impacted: int
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
    resource_id: str
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
    resource_name: Annotated[str, StringConstraints(max_length=100)] | None = None
    category: Annotated[str, StringConstraints(max_length=100)] | None = None
    need_text: Annotated[str, StringConstraints(max_length=300)] | None = None
    when: When | None = None
    preferences: Preferences | None = None
    max_resources: Annotated[int, Field(ge=1, le=5)] = 3
    max_slots_per_session: Annotated[int, Field(ge=1, le=5)] = 3


class UnderstoodResource(ApiModel):
    resource_id: str
    name: str
    localized_names: LocalizedText | None = None
    confidence: Annotated[float, Field(ge=0, le=1)]
    matched_on: Literal["NAME_EXACT", "NAME_PHONETIC", "NAME_VARIANT", "LEXICON"]


class UnderstoodCategory(ApiModel):
    id: str
    name: str
    localized_names: LocalizedText | None = None
    confidence: Annotated[float, Field(ge=0, le=1)]
    matched_on: Literal["LEXICON", "NEED_ROUTE", "SEMANTIC", "FORMER_RESOURCE"]


class DateRange(ApiModel):
    from_: dt.date | None = Field(default=None, alias="from")
    to: dt.date | None = None


class Understood(ApiModel):
    resources: list[UnderstoodResource]
    categories: list[UnderstoodCategory]
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
        "WHICH_RESOURCE", "WHICH_CATEGORY", "WHICH_DATE", "WHICH_CUSTOMER", "CONFIRM_INTERPRETATION"
    ]
    options: list[ClarificationOption]


class ResultResource(ApiModel):
    resource_id: str
    name: str
    localized_names: LocalizedText | None = None
    categories: list[Category]
    gender: Gender | None = None
    attributes: Attributes | None = None
    price: Money | None = None
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


class ResourceResult(ApiModel):
    resource: ResultResource
    sessions: list[SessionInstance]
    unavailable: list[UnavailableSession]


class AvailabilitySearchResponse(ApiModel):
    outcome: Literal["FOUND", "NONE_AVAILABLE", "CLARIFICATION_NEEDED", "TRANSFER", "COULD_NOT_CHECK"]
    as_of: dt.datetime
    routing: Routing
    understood: Understood
    clarification: Clarification | None = None
    results: list[ResourceResult]
    alternatives: list[ResourceResult]
    partial: bool | None = None
    notes: list[str] | None = None


class BookCustomer(ApiModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    phone: Phone
    relation_to_caller: Relation | None = None


class AgentBookRequest(ApiModel):
    slot_id: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    customer: BookCustomer
    reason_verbatim: Annotated[str, StringConstraints(max_length=500)] | None = None
    language: Language
    request_timing_confirmation: bool = False


class CustomerSummary(ApiModel):
    name: str | None = None
    phone: Phone | None = None


class ResourceSummary(ApiModel):
    resource_id: str | None = None
    name: str | None = None
    localized_names: LocalizedText | None = None


class SessionSummary(ApiModel):
    session_id: str | None = None
    label: str | None = None
    start: ClockTime | None = None
    end: ClockTime | None = None


class AgentBooking(ApiModel):
    outcome: Literal["BOOKED", "ALREADY_BOOKED", "CANCELLED", "ALREADY_CANCELLED", "RESCHEDULED", "FOUND"]
    booking_id: str
    confirmation_code: str | None = None
    status: BookingStatus
    customer: CustomerSummary
    resource: ResourceSummary
    category: Category | None = None
    date: dt.date
    session: SessionSummary
    slot: Slot
    previous_slot: Slot | None = None
    arrive_by: ClockTime | None = None
    timing_certainty: TimingCertainty
    price: Money | None = None
    follow_up: Literal["NONE", "DESK_WILL_CONFIRM_TIMING"] | None = None
    resource_today: SessionInstance | None = None


class AgentBookingList(ApiModel):
    outcome: Literal["FOUND", "NONE_FOUND", "NAME_REQUIRED", "IDENTITY_UNAVAILABLE"]
    items: list[AgentBooking]
    customers_on_number: int
    identity_basis: Literal["CALLER_NUMBER", "SPOKEN_NUMBER", "NONE"]


class CancelRequest(ApiModel):
    customer_name: Annotated[str, StringConstraints(max_length=100)]
    reason_verbatim: Annotated[str, StringConstraints(max_length=500)] | None = None


class RescheduleRequest(ApiModel):
    customer_name: Annotated[str, StringConstraints(max_length=100)]
    new_slot_id: str


# ---------------------------------------------------------------- staff bookings


class BookingCustomer(ApiModel):
    name: str
    phone: Phone
    relation_to_caller: str | None = None


class HistoryItem(ApiModel):
    at: dt.datetime | None = None
    by: str | None = None
    change: str | None = None


class Booking(ApiModel):
    id: str
    confirmation_code: str | None = None
    status: BookingStatus
    customer: BookingCustomer
    caller_number: str | None = None
    resource_id: str
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


class BookingPage(ApiModel):
    items: list[Booking]
    total: int


class ConfirmRequest(ApiModel):
    confirmed_start: ClockTime | None = None
    apply_to_session: bool = False


class StatusRequest(ApiModel):
    status: Literal["ARRIVED", "COMPLETED", "NO_SHOW", "CANCELLED_BY_PROVIDER"]
    note: Annotated[str, StringConstraints(max_length=500)] | None = None


class Notification(ApiModel):
    id: str
    booking_id: str
    trigger: Literal["SESSION_CANCELLED", "SESSION_TIME_CHANGED", "TEMPLATE_CHANGED", "DESK_MESSAGE"]
    status: NotificationStatus
    channel: Channel | None = None
    customer_phone: Phone | None = None
    customer_language: Language | None = None
    facts: dict[str, Any] | None = None
    created_at: dt.datetime
    delivered_at: dt.datetime | None = None
    outcome: DeliveryOutcome | None = None


class ImpactedBooking(ApiModel):
    booking: Booking
    notification: Notification


class ImpactList(ApiModel):
    exception_id: str
    items: list[ImpactedBooking]


class DeliveredRequest(ApiModel):
    channel: Channel
    outcome: DeliveryOutcome | None = None
    note: Annotated[str, StringConstraints(max_length=500)] | None = None


# ---------------------------------------------------------------- lists


class CategoryList(ApiModel):
    items: list[Category]


class ResourcePage(ApiModel):
    items: list[Resource]
    total: int


class LexiconList(ApiModel):
    items: list[LexiconEntry]


class ExceptionList(ApiModel):
    items: list[ScheduleException]


class BoardView(ApiModel):
    resource_id: str
    date: dt.date
    sessions: list[BoardEntry]


class NotificationList(ApiModel):
    items: list[Notification]


# ---------------------------------------------------------------- calls


class CallSummary(ApiModel):
    id: str | None = None
    call_id: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    started_at: AwareDatetime
    duration_seconds: Annotated[int, Field(ge=0, le=86400)] | None = None
    language: Language | None = None
    caller_number: str | None = None
    intent: Literal[
        "AVAILABILITY", "BOOKING", "RESCHEDULE", "CANCEL", "LOOKUP", "GENERAL_INFO", "SERVICE_TRANSFER",
        "EMERGENCY", "NEED_ROUTING", "ADMIN", "OTHER",
    ]
    outcome: Literal[
        "RESOLVED_BY_AGENT", "BOOKING_CREATED", "BOOKING_CANCELLED",
        "BOOKING_RESCHEDULED", "TRANSFERRED", "EMERGENCY_TRANSFERRED", "ABANDONED",
    ]
    transferred_to: str | None = None
    booking_id: str | None = None
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


# ---------------------------------------------------------------- knowledge base


class KnowledgeSearchRequest(ApiModel):
    question: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    language: Annotated[str, StringConstraints(min_length=2, max_length=16)]
    topic: Annotated[str, StringConstraints(min_length=1, max_length=50)] | None = None


class KnowledgeRouting(ApiModel):
    action: Literal["ANSWER", "CLARIFY", "TRANSFER_DESK", "TRANSFER_EMERGENCY"]
    destination: str | None = None


class KnowledgeAnswer(ApiModel):
    entry_id: str
    topic: str
    text: str
    language: str
    source: Literal["CURATED", "DOCUMENT"]
    confidence: float
    matched_question: str


class KnowledgeOption(ApiModel):
    entry_id: str
    topic: str
    label: str


class KnowledgeSearchResponse(ApiModel):
    outcome: Literal["ANSWERED", "CLARIFICATION_NEEDED", "NO_ANSWER", "TRANSFER", "COULD_NOT_CHECK"]
    as_of: dt.datetime
    routing: KnowledgeRouting
    answer: KnowledgeAnswer | None = None
    options: list[KnowledgeOption] | None = None


Question = Annotated[str, StringConstraints(min_length=1, max_length=200)]
AnswerText = Annotated[str, StringConstraints(min_length=1, max_length=1000)]


class KnowledgeEntryInput(ApiModel):
    topic: Annotated[str, StringConstraints(min_length=1, max_length=50, pattern=r"^[a-z0-9_]+$")]
    questions: Annotated[list[Question], Field(min_length=1, max_length=50)]
    answers: Annotated[dict[Language, AnswerText], Field(min_length=1)]
    action: Literal["ANSWER", "TRANSFER_DESK"] = "ANSWER"
    destination: str | None = None
    approved: bool = False


class KnowledgeEntry(KnowledgeEntryInput):
    id: str
    source: Literal["PROVIDER", "DOCUMENT"]
    updated_at: dt.datetime


class KnowledgeList(ApiModel):
    items: list[KnowledgeEntry]
