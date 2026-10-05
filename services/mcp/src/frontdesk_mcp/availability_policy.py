"""Pure mapping of contracted schedule/board facts to revision 6 caller decisions. No I/O."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time
from enum import StrEnum

from . import contract

WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


class Purpose(StrEnum):
    AVAILABILITY = "AVAILABILITY"
    WORKING_HOURS = "WORKING_HOURS"


class DateKind(StrEnum):
    TODAY = "TODAY"
    FUTURE = "FUTURE"


class Basis(StrEnum):
    LIVE_BOARD = "LIVE_BOARD"
    USUAL_SCHEDULE = "USUAL_SCHEDULE"


class Decision(StrEnum):
    APPOINTMENT_REQUEST = "APPOINTMENT_REQUEST"
    CALLBACK_REQUIRED = "CALLBACK_REQUIRED"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    COULD_NOT_CHECK = "COULD_NOT_CHECK"


class Reason(StrEnum):
    ON_CALL_DOCTOR = "ON_CALL_DOCTOR"
    BOARD_UNKNOWN = "BOARD_UNKNOWN"
    BOARD_STALE = "BOARD_STALE"
    BOARD_ENTRY_MISSING = "BOARD_ENTRY_MISSING"
    SESSION_NOT_ON_BOARD = "SESSION_NOT_ON_BOARD"
    BOARD_NOT_CONFIRMED = "BOARD_NOT_CONFIRMED"
    CANCELLED = "CANCELLED"
    SESSION_ENDED = "SESSION_ENDED"
    NOT_USUAL_DAY = "NOT_USUAL_DAY"
    SESSION_NOT_USUAL = "SESSION_NOT_USUAL"
    NO_USUAL_SCHEDULE = "NO_USUAL_SCHEDULE"
    NO_REGULAR_HOURS = "NO_REGULAR_HOURS"
    PROFILE_UNAVAILABLE = "PROFILE_UNAVAILABLE"
    TIME_OUTSIDE_SESSION = "TIME_OUTSIDE_SESSION"
    SESSION_REQUIRED = "SESSION_REQUIRED"
    TIME_NOT_VERIFIABLE = "TIME_NOT_VERIFIABLE"
    SEARCH_INCOMPLETE = "SEARCH_INCOMPLETE"


class DateError(StrEnum):
    DATE_FORMAT = "DATE_FORMAT"
    PAST_DATE = "PAST_DATE"
    DATE_REQUIRED = "DATE_REQUIRED"


@dataclass(frozen=True)
class RequestedDate:
    value: date
    kind: DateKind
    weekday: str


@dataclass(frozen=True)
class DoctorFacts:
    doctor: contract.DoctorSummary
    profile: contract.DoctorDetail | None = None
    entries: tuple[contract.AvailabilityEntry, ...] = ()


@dataclass(frozen=True)
class SessionDecision:
    label: str | None
    basis: Basis
    owner_status: contract.AvailabilityStatus | None
    decision: Decision
    reason: Reason | None
    start: str | None
    end: str | None
    days: tuple[str, ...] = ()
    delay_minutes: int | None = None
    note: str | None = None
    is_stale: bool = False


@dataclass(frozen=True)
class DoctorDecision:
    facts: DoctorFacts
    decision: Decision
    reason: Reason | None
    basis: Basis
    sessions: tuple[SessionDecision, ...] = ()
    session_choice_required: bool = False
    alternatives: tuple[SessionDecision, ...] = ()


@dataclass(frozen=True)
class Write:
    pass


@dataclass(frozen=True)
class SessionRequired:
    sessions: tuple[SessionDecision, ...]


@dataclass(frozen=True)
class Callback:
    reason: Reason


@dataclass(frozen=True)
class NotAvailable:
    reason: Reason
    alternatives: tuple[SessionDecision, ...]


@dataclass(frozen=True)
class Handoff:
    reason: Reason


BookingDecision = Write | SessionRequired | Callback | NotAvailable | Handoff


@dataclass(frozen=True)
class SearchState:
    bookable_found: int
    checked: int
    complete: bool


@dataclass(frozen=True)
class ResultOutcome:
    outcome: str
    next_step: str
    reason: Reason | None = None


def resolve_date(text: str | None, facility_now: datetime, purpose: Purpose) -> RequestedDate | DateError | None:
    if text is None:
        return None if purpose == Purpose.WORKING_HOURS else DateError.DATE_REQUIRED
    text = text.strip()
    today = facility_now.date()
    if text.lower() == "today":
        value = today
    else:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return DateError.DATE_FORMAT
        try:
            value = date.fromisoformat(text)
        except ValueError:
            return DateError.DATE_FORMAT
    if value < today:
        return DateError.PAST_DATE
    return RequestedDate(value, DateKind.TODAY if value == today else DateKind.FUTURE, WEEKDAYS[value.weekday()])


TODAY_STATUS: dict[contract.AvailabilityStatus, tuple[Decision, Reason | None]] = {
    "IN": (Decision.APPOINTMENT_REQUEST, None),
    "LATE": (Decision.APPOINTMENT_REQUEST, None),
    "CANCELLED": (Decision.NOT_AVAILABLE, Reason.CANCELLED),
    "NOT_CONFIRMED": (Decision.CALLBACK_REQUIRED, Reason.BOARD_NOT_CONFIRMED),
    "UNKNOWN": (Decision.CALLBACK_REQUIRED, Reason.BOARD_UNKNOWN),
}


def normalised(text: str) -> str:
    return " ".join(text.casefold().split())


def _window(end: str | None, now: datetime | None = None) -> str:
    if end is None:
        return "UNKNOWN_END"
    if now is not None and now.time() > time.fromisoformat(end):
        return "ENDED"
    return "OPEN"


def _combine(sessions: tuple[SessionDecision, ...], named: bool) -> tuple[Decision, Reason | None, bool]:
    kinds = {s.decision for s in sessions}
    if len(kinds) == 1:
        return sessions[0].decision, sessions[0].reason, False
    if Decision.APPOINTMENT_REQUEST in kinds and not named:
        return Decision.APPOINTMENT_REQUEST, None, True
    # An unlabelled unresolved row stays in scope even after a named session was selected.
    if Decision.CALLBACK_REQUIRED in kinds:
        s = next(s for s in sessions if s.decision == Decision.CALLBACK_REQUIRED)
        return s.decision, s.reason, False
    s = next(s for s in sessions if s.decision == Decision.NOT_AVAILABLE)
    return s.decision, s.reason, False


def _on_call(facts: DoctorFacts, basis: Basis) -> DoctorDecision:
    return DoctorDecision(facts, Decision.CALLBACK_REQUIRED, Reason.ON_CALL_DOCTOR, basis)


def _today(facts: DoctorFacts, session: str | None, now: datetime) -> DoctorDecision:
    sessions = []
    for row in facts.entries:
        decision, reason = TODAY_STATUS[row.status]
        if row.status == "UNKNOWN" and row.isStale:
            reason = Reason.BOARD_STALE
        if decision == Decision.APPOINTMENT_REQUEST and _window(row.expectedEndTime, now) == "ENDED":
            decision, reason = Decision.NOT_AVAILABLE, Reason.SESSION_ENDED
        sessions.append(SessionDecision(row.session, Basis.LIVE_BOARD, row.status, decision, reason,
                                        row.expectedTime, row.expectedEndTime, delay_minutes=row.delayMinutes,
                                        note=row.note, is_stale=row.isStale))
    alternatives = tuple(s for s in sessions if s.decision == Decision.APPOINTMENT_REQUEST)
    scoped = tuple(s for s in sessions if not session or not normalised(s.label or "")
                   or normalised(s.label) == normalised(session))
    if not scoped:
        reason = Reason.SESSION_NOT_ON_BOARD if facts.entries and session else Reason.BOARD_ENTRY_MISSING
        return DoctorDecision(facts, Decision.CALLBACK_REQUIRED, reason, Basis.LIVE_BOARD,
                              alternatives=alternatives)
    decision, reason, choice = _combine(scoped, bool(session))
    return DoctorDecision(facts, decision, reason, Basis.LIVE_BOARD, scoped, choice, alternatives)


def _usual(row: contract.UsualSession, decision: Decision = Decision.APPOINTMENT_REQUEST,
           reason: Reason | None = None) -> SessionDecision:
    return SessionDecision(row.label, Basis.USUAL_SCHEDULE, None, decision, reason, row.start, row.end,
                           tuple(row.daysOfWeek))


def _future(facts: DoctorFacts, requested: RequestedDate, session: str | None) -> DoctorDecision:
    if facts.profile is None:
        return DoctorDecision(facts, Decision.COULD_NOT_CHECK, Reason.PROFILE_UNAVAILABLE, Basis.USUAL_SCHEDULE)
    usual = facts.profile.usualSchedule
    if not usual:
        return DoctorDecision(facts, Decision.CALLBACK_REQUIRED, Reason.NO_USUAL_SCHEDULE, Basis.USUAL_SCHEDULE)
    sessions = tuple(_usual(s) if requested.weekday in s.daysOfWeek
                     else _usual(s, Decision.NOT_AVAILABLE, Reason.NOT_USUAL_DAY) for s in usual)
    alternatives = tuple(s for s in sessions if s.decision == Decision.APPOINTMENT_REQUEST)
    selected = tuple(s for s in alternatives if not session or normalised(s.label or "") == normalised(session))
    if not selected:
        reason = Reason.SESSION_NOT_USUAL if alternatives and session else Reason.NOT_USUAL_DAY
        return DoctorDecision(facts, Decision.NOT_AVAILABLE, reason, Basis.USUAL_SCHEDULE,
                              sessions, alternatives=alternatives)
    return DoctorDecision(facts, Decision.APPOINTMENT_REQUEST, None, Basis.USUAL_SCHEDULE,
                          selected, alternatives=alternatives)


def decide_doctor(facts: DoctorFacts, requested: RequestedDate, *, session: str | None,
                  now: datetime) -> DoctorDecision:
    basis = Basis.LIVE_BOARD if requested.kind == DateKind.TODAY else Basis.USUAL_SCHEDULE
    if facts.doctor.attendanceType == "ON_CALL":
        return _on_call(facts, basis)
    return _today(facts, session, now) if requested.kind == DateKind.TODAY else _future(facts, requested, session)


def working_hours(facts: DoctorFacts, requested: RequestedDate | None) -> DoctorDecision:
    if facts.doctor.attendanceType == "ON_CALL":
        return DoctorDecision(facts, Decision.CALLBACK_REQUIRED, Reason.NO_REGULAR_HOURS, Basis.USUAL_SCHEDULE)
    if facts.profile is None:
        return DoctorDecision(facts, Decision.COULD_NOT_CHECK, Reason.PROFILE_UNAVAILABLE, Basis.USUAL_SCHEDULE)
    if not facts.profile.usualSchedule:
        return DoctorDecision(facts, Decision.CALLBACK_REQUIRED, Reason.NO_USUAL_SCHEDULE, Basis.USUAL_SCHEDULE)
    return DoctorDecision(facts, Decision.APPOINTMENT_REQUEST, None, Basis.USUAL_SCHEDULE,
                          tuple(_usual(s) for s in facts.profile.usualSchedule))


def decide_booking(decision: DoctorDecision, *, session: str | None,
                   preferred_time: str | None) -> BookingDecision:
    if decision.reason == Reason.ON_CALL_DOCTOR:
        return Callback(Reason.ON_CALL_DOCTOR)
    if decision.decision == Decision.CALLBACK_REQUIRED:
        return Callback(decision.reason)
    if decision.decision == Decision.COULD_NOT_CHECK:
        return Handoff(Reason.PROFILE_UNAVAILABLE)
    if decision.decision == Decision.NOT_AVAILABLE:
        return NotAvailable(decision.reason, decision.alternatives)
    sessions = decision.sessions
    alternatives = decision.alternatives
    if preferred_time and sessions and not session:
        matched = tuple(s for s in sessions if s.start and s.end and s.start <= preferred_time <= s.end)
        if matched:
            sessions = matched + tuple(s for s in sessions if not normalised(s.label or "") and s not in matched)
        else:
            unbounded = tuple(s for s in sessions if s.start is None or s.end is None)
            if not unbounded:
                return NotAvailable(Reason.TIME_OUTSIDE_SESSION, alternatives)
            sessions = unbounded
    if sessions:
        kinds = {s.decision for s in sessions}
        if len(kinds) > 1 and not session and not preferred_time:
            return SessionRequired(sessions)
        value, reason, _ = _combine(sessions, True)
    else:
        value, reason = decision.decision, decision.reason
    if value == Decision.CALLBACK_REQUIRED:
        return Callback(reason)
    if value == Decision.NOT_AVAILABLE:
        return NotAvailable(reason, alternatives)
    if preferred_time and sessions:
        if any(_window(s.end) == "UNKNOWN_END" or s.start is None for s in sessions):
            return Handoff(Reason.TIME_NOT_VERIFIABLE)
        if not any(s.start <= preferred_time <= s.end for s in sessions):
            return NotAvailable(Reason.TIME_OUTSIDE_SESSION, alternatives)
    return Write()


def rank(decisions: list[DoctorDecision], limit: int) -> list[DoctorDecision]:
    bookable = [d for d in decisions if d.decision == Decision.APPOINTMENT_REQUEST]
    candidates = bookable or [d for d in decisions
                             if d.decision in (Decision.CALLBACK_REQUIRED, Decision.NOT_AVAILABLE)]
    order = {Decision.APPOINTMENT_REQUEST: 0, Decision.CALLBACK_REQUIRED: 1, Decision.NOT_AVAILABLE: 2}
    return sorted(candidates,
                  key=lambda d: (order[d.decision], d.facts.doctor.name.casefold(), d.facts.doctor.id))[:limit]


def aggregate(decisions: list[DoctorDecision], search: SearchState,
              purpose: Purpose = Purpose.AVAILABILITY) -> ResultOutcome:
    if search.bookable_found:
        outcome = "WORKING_HOURS" if purpose == Purpose.WORKING_HOURS else "AVAILABILITY"
        return ResultOutcome(outcome, "ASK_WHICH_DOCTOR")
    if not search.complete:
        return ResultOutcome("HANDOFF_REQUIRED", "TRANSFER_DESK", Reason.SEARCH_INCOMPLETE)
    if purpose == Purpose.WORKING_HOURS:
        return ResultOutcome("WORKING_HOURS", "ASK_WHICH_DOCTOR")
    callback = next((d for d in decisions if d.decision == Decision.CALLBACK_REQUIRED), None)
    if callback:
        return ResultOutcome("CALLBACK_REQUIRED", "ASK_CALLBACK_DETAILS", callback.reason)
    return ResultOutcome("NOT_AVAILABLE", "OFFER_OTHER_SESSION_OR_DATE")
