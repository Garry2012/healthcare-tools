"""Relational schema. Alembic migrations are the source of DDL; these models mirror them."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ..domain import booking_status


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


LIVE_SQL = _in("status", booking_status.HOLDS_SLOT)


class Base(DeclarativeBase):
    pass


class _Stamped:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Category(_Stamped, Base):
    __tablename__ = "categories"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    code: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    localized_names: Mapped[dict[str, str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    offers_bookings: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")


class Resource(_Stamped, Base):
    __tablename__ = "resources"
    __table_args__ = (
        CheckConstraint(_in("gender", ("FEMALE", "MALE")), name="gender"),
        CheckConstraint(_in("attendance_type", ("REGULAR", "VISITING", "ON_CALL")), name="attendance"),
        CheckConstraint(_in("booking_policy", ("BOOKABLE", "DESK_ONLY", "NOT_OFFERED")), name="policy"),
    )
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    localized_names: Mapped[dict[str, str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    name_variants: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    gender: Mapped[str | None] = mapped_column(Text)
    # Domain-pack facts the agent may speak (healthcare: qualification, yearsOfExperience).
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    languages_spoken: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    price_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    price_currency: Mapped[str | None] = mapped_column(Text)
    price_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    attendance_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="REGULAR")
    booking_policy: Mapped[str] = mapped_column(Text, nullable=False, server_default="BOOKABLE")
    data_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ResourceCategory(Base):
    __tablename__ = "resource_categories"
    resource_id: Mapped[str] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), primary_key=True
    )
    category_id: Mapped[str] = mapped_column(ForeignKey("categories.id"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class LexiconEntry(_Stamped, Base):
    __tablename__ = "lexicon_entries"
    __table_args__ = (
        UniqueConstraint("concept_type", "concept_id", "term", "language", name="lexicon_term"),
        CheckConstraint(
            _in(
                "concept_type",
                ("CATEGORY", "RESOURCE", "NEED_ROUTE", "RED_FLAG", "DAY_PART", "SERVICE_TRANSFER"),
            ),
            name="concept_type",
        ),
        CheckConstraint(
            _in("source", ("PROVIDER", "TRANSCRIPT_MINED", "AUTO_TRANSLITERATION")), name="source"
        ),
        Index("ix_lexicon_approved_type", "approved", "concept_type"),
    )
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    concept_type: Mapped[str] = mapped_column(Text, nullable=False)
    concept_id: Mapped[str] = mapped_column(Text, nullable=False)
    term: Mapped[str] = mapped_column(Text, nullable=False)
    term_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(Text, nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default="PROVIDER")


class ScheduleTemplate(_Stamped, Base):
    __tablename__ = "schedule_templates"
    __table_args__ = (UniqueConstraint("resource_id", "effective_from", name="template_effective"),)
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    resource_id: Mapped[str] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    created_by: Mapped[str | None] = mapped_column(Text)


class TemplateSession(Base):
    __tablename__ = "template_sessions"
    __table_args__ = (
        CheckConstraint("end_time > start_time", name="session_order"),
        CheckConstraint(_in("capacity_model", ("SEQUENCE", "TIMED")), name="capacity_model"),
        CheckConstraint(_in("capacity_mode", ("FIXED", "PER_HOUR", "DEFAULT")), name="capacity_mode"),
        CheckConstraint("walk_in_reserve_percent BETWEEN 0 AND 100", name="walk_in_reserve"),
    )
    template_id: Mapped[str] = mapped_column(
        ForeignKey("schedule_templates.id", ondelete="CASCADE"), primary_key=True
    )
    template_session_id: Mapped[str] = mapped_column(Text, primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(Text)
    days_of_week: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    capacity_model: Mapped[str] = mapped_column(Text, nullable=False)
    slot_minutes: Mapped[int | None] = mapped_column(Integer)
    capacity_mode: Mapped[str] = mapped_column(Text, nullable=False)
    capacity_value: Mapped[int | None] = mapped_column(Integer)
    walk_in_reserve_percent: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_arrival_offset_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="15"
    )


class ScheduleException(_Stamped, Base):
    __tablename__ = "schedule_exceptions"
    __table_args__ = (
        CheckConstraint("date_to >= date_from", name="date_order"),
        CheckConstraint(_in("scope", ("WHOLE_DAY", "SESSION", "TIME_RANGE")), name="scope"),
        CheckConstraint(
            _in(
                "effect",
                (
                    "UNAVAILABLE", "TIME_CHANGE", "CAPACITY_CHANGE", "EXTRA_SESSION",
                    "TIMING_PENDING", "TIMING_CONFIRMED",
                ),
            ),
            name="effect",
        ),
        Index("ix_exceptions_resource_dates", "resource_id", "date_from", "date_to"),
    )
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    resource_id: Mapped[str] = mapped_column(ForeignKey("resources.id", ondelete="CASCADE"), nullable=False)
    date_from: Mapped[date] = mapped_column(Date, nullable=False)
    date_to: Mapped[date] = mapped_column(Date, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    template_session_id: Mapped[str | None] = mapped_column(Text)
    effect: Mapped[str] = mapped_column(Text, nullable=False)
    new_start: Mapped[time | None] = mapped_column(Time)
    new_end: Mapped[time | None] = mapped_column(Time)
    new_capacity: Mapped[int | None] = mapped_column(Integer)
    reason_category: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    impact_bookings: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    impact_notifications: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[str | None] = mapped_column(Text)


class BoardEntry(Base):
    __tablename__ = "board_entries"
    __table_args__ = (
        CheckConstraint(_in("presence", ("NOT_ARRIVED", "ARRIVING", "PRESENT", "LEFT")), name="presence"),
        CheckConstraint(_in("capacity_state", ("OPEN", "FULL")), name="capacity_state"),
        Index("ix_board_resource_date", "resource_id", "date"),
    )
    session_id: Mapped[str] = mapped_column(Text, primary_key=True)
    resource_id: Mapped[str] = mapped_column(ForeignKey("resources.id", ondelete="CASCADE"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    presence: Mapped[str | None] = mapped_column(Text)
    expected_start: Mapped[time | None] = mapped_column(Time)
    delay_minutes: Mapped[int | None] = mapped_column(Integer)
    session_ended: Mapped[bool | None] = mapped_column(Boolean)
    capacity_state: Mapped[str | None] = mapped_column(Text)
    tokens_issued: Mapped[int | None] = mapped_column(Integer)
    last_arrival_time: Mapped[time | None] = mapped_column(Time)
    timing_confirmed: Mapped[bool | None] = mapped_column(Boolean)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)


class Booking(_Stamped, Base):
    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint(_in("status", booking_status.ALL), name="status"),
        CheckConstraint(_in("created_via", ("AGENT", "DESK", "WEB")), name="created_via"),
        CheckConstraint(_in("follow_up", ("NONE", "DESK_WILL_CONFIRM_TIMING")), name="follow_up"),
        # One live booking per slot: uniqueness is a constraint, not application logic.
        Index(
            "uq_bookings_live_slot",
            "slot_id",
            unique=True,
            postgresql_where=text(LIVE_SQL),
        ),
        Index("ix_bookings_phone", "phone"),
        Index("ix_bookings_caller_number", "caller_number"),
        Index("ix_bookings_resource_date", "resource_id", "date"),
        Index("ix_bookings_session", "session_id"),
    )
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    confirmation_code: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    customer_name: Mapped[str] = mapped_column(Text, nullable=False)
    customer_name_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str] = mapped_column(Text, nullable=False)
    relation_to_caller: Mapped[str | None] = mapped_column(Text)
    caller_number: Mapped[str | None] = mapped_column(Text)
    resource_id: Mapped[str] = mapped_column(ForeignKey("resources.id"), nullable=False)
    category_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id"))
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    slot_id: Mapped[str] = mapped_column(Text, nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    timing_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    confirmed_start: Mapped[time | None] = mapped_column(Time)
    reason_verbatim: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(Text)
    created_via: Mapped[str] = mapped_column(Text, nullable=False)
    call_id: Mapped[str | None] = mapped_column(Text)
    follow_up: Mapped[str] = mapped_column(Text, nullable=False, server_default="NONE")
    impacted_by_exception_id: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class BookingHistory(Base):
    __tablename__ = "booking_history"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    booking_id: Mapped[str] = mapped_column(
        ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    by: Mapped[str] = mapped_column(Text, nullable=False)
    change: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class Notification(_Stamped, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(
            _in("trigger", ("SESSION_CANCELLED", "SESSION_TIME_CHANGED", "TEMPLATE_CHANGED", "DESK_MESSAGE")),
            name="trigger",
        ),
        CheckConstraint(_in("status", ("PENDING", "SENT", "FAILED", "ACKNOWLEDGED")), name="status"),
        Index("ix_notifications_status", "status"),
    )
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    booking_id: Mapped[str] = mapped_column(
        ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    exception_id: Mapped[str | None] = mapped_column(Text, index=True)
    trigger: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="PENDING")
    channel: Mapped[str | None] = mapped_column(Text)
    customer_phone: Mapped[str] = mapped_column(Text, nullable=False)
    customer_language: Mapped[str | None] = mapped_column(Text)
    facts: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_by: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class CallSummary(_Stamped, Base):
    __tablename__ = "call_summaries"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    call_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    language: Mapped[str | None] = mapped_column(Text)
    caller_number: Mapped[str | None] = mapped_column(Text)
    intent: Mapped[str] = mapped_column(Text, nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    transferred_to: Mapped[str | None] = mapped_column(Text)
    booking_id: Mapped[str | None] = mapped_column(Text)
    tool_outcomes: Mapped[dict[str, str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    summary_text: Mapped[str | None] = mapped_column(Text)


class KnowledgeEntry(_Stamped, Base):
    """An approved answer with the ways callers ask for it (any language, any script)."""

    __tablename__ = "knowledge_entries"
    __table_args__ = (
        CheckConstraint(_in("action", ("ANSWER", "TRANSFER_DESK")), name="knowledge_action"),
        CheckConstraint(_in("source", ("PROVIDER", "DOCUMENT")), name="knowledge_source"),
        CheckConstraint("action <> 'TRANSFER_DESK' OR destination IS NOT NULL", name="knowledge_destination"),
        Index("ix_knowledge_approved_topic", "approved", "topic"),
    )
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    questions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    answers: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    action: Mapped[str] = mapped_column(Text, nullable=False, server_default="ANSWER")
    destination: Mapped[str | None] = mapped_column(Text)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default="PROVIDER")
    updated_by: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CacheVersion(Base):
    """Version stamp per cached data set ('directory', 'knowledge'); bumped by every writer."""

    __tablename__ = "cache_versions"
    name: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
