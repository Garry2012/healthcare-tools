"""Pure mapping of contracted schedule/board facts to revision 6 caller decisions. No I/O."""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
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
    SLOT_CHECK_REQUIRED = "SLOT_CHECK_REQUIRED"
    HANDOFF_REQUIRED = "HANDOFF_REQUIRED"


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
    PROFILE_UNAVAILABLE = "PROFILE_UNAVAILABLE"
    TIME_OUTSIDE_SESSION = "TIME_OUTSIDE_SESSION"
    SESSION_REQUIRED = "SESSION_REQUIRED"
    TIME_NOT_VERIFIABLE = "TIME_NOT_VERIFIABLE"
    SEARCH_INCOMPLETE = "SEARCH_INCOMPLETE"
    NO_OPEN_SLOT = "NO_OPEN_SLOT"
    SLOT_FULL = "SLOT_FULL"


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
class SessionSlots:
    status: contract.AvailabilityStatus | None
    bookable: bool
    blocks: tuple[contract.SlotBlock, ...]

    @classmethod
    def missing(cls) -> SessionSlots:
        return cls(None, False, ())


@dataclass(frozen=True)
class SlotsNotRead:
    pass


@dataclass(frozen=True)
class SessionFacts:
    status: contract.AvailabilityStatus | None
    is_stale: bool
    evidence: SessionSlots | SlotsNotRead | None
    kind: DateKind
    now: datetime
    end: str | None


@dataclass(frozen=True)
class DoctorFacts:
    doctor: contract.DoctorSummary
    profile: contract.DoctorDetail | None = None
    entries: tuple[contract.AvailabilityEntry, ...] = ()
    slots: contract.SlotPlan | SlotsNotRead | None = None


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
    evidence: SessionSlots | SlotsNotRead | None = None
    open_slots: tuple[contract.SlotBlock, ...] | None = None
    one_day: bool = False


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
    expected_slot: str | None = None


@dataclass(frozen=True)
class TimeRequired:
    alternatives: tuple[SessionDecision, ...]


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


BookingDecision = Write | TimeRequired | SessionRequired | Callback | NotAvailable | Handoff


@dataclass(frozen=True)
class SearchState:
    """Evaluated matches: date-specific requests or schedules, according to the query purpose."""

    matches_found: int
    checked: int
    complete: bool


@dataclass(frozen=True)
class ResultOutcome:
    outcome: str
    next_step: str
    reason: Reason | None = None
    candidates: tuple[DoctorDecision, ...] = ()
    bookable_found: int = 0


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


def normalised(text: str) -> str:
    return " ".join(text.casefold().split())


def _window(end: str | None, now: datetime | None = None) -> str:
    if end is None:
        return "UNKNOWN_END"
    if now is not None and now.time() > time.fromisoformat(end):
        return "ENDED"
    return "OPEN"


def reconcile_status(board: contract.AvailabilityStatus | None,
                     slot: contract.AvailabilityStatus | None) -> contract.AvailabilityStatus | None:
    return next((status for status in ("UNKNOWN", "CANCELLED", "NOT_CONFIRMED", "LATE", "IN")
                 if status in (board, slot)), None)


def _block_ended(block: contract.SlotBlock, now: datetime | None) -> bool:
    return now is not None and time.fromisoformat(block.end) <= now.time().replace(second=0, microsecond=0)


def block_state(block: contract.SlotBlock, now: datetime | None) -> str:
    if not block.bookable or _block_ended(block, now):
        return "CLOSED"
    return "FULL" if block.available == 0 else "OPEN"


def session_decision(facts: SessionFacts) -> tuple[Decision, Reason | None]:
    if facts.status == "UNKNOWN":
        return Decision.CALLBACK_REQUIRED, Reason.BOARD_STALE if facts.is_stale else Reason.BOARD_UNKNOWN
    if facts.status == "CANCELLED":
        return Decision.NOT_AVAILABLE, Reason.CANCELLED
    if facts.evidence is None:
        if facts.kind == DateKind.TODAY:
            if facts.status == "NOT_CONFIRMED":
                return Decision.CALLBACK_REQUIRED, Reason.BOARD_NOT_CONFIRMED
            if _window(facts.end, facts.now) == "ENDED":
                return Decision.NOT_AVAILABLE, Reason.SESSION_ENDED
        return Decision.APPOINTMENT_REQUEST, None
    if isinstance(facts.evidence, SlotsNotRead):
        return Decision.SLOT_CHECK_REQUIRED, None
    if not facts.evidence.bookable:
        return Decision.NOT_AVAILABLE, Reason.NO_OPEN_SLOT
    blocks = facts.evidence.blocks
    now = facts.now if facts.kind == DateKind.TODAY else None
    if any(block_state(block, now) == "OPEN" for block in blocks):
        return Decision.APPOINTMENT_REQUEST, None
    if blocks and all(_block_ended(block, now) for block in blocks):
        return Decision.NOT_AVAILABLE, Reason.SESSION_ENDED
    return Decision.NOT_AVAILABLE, Reason.NO_OPEN_SLOT


def on_call(s: SessionDecision, now: datetime | None) -> SessionDecision:
    if s.owner_status == "CANCELLED":
        return s
    usable = (s.start is not None and s.end is not None and _window(s.end, now) != "ENDED") or (
        isinstance(s.evidence, SessionSlots) and any(block_state(b, now) == "OPEN" for b in s.evidence.blocks))
    if s.owner_status in ("IN", "LATE") and usable:
        return s
    return replace(s, decision=Decision.HANDOFF_REQUIRED, reason=Reason.ON_CALL_DOCTOR)


def _evaluate_session(s: SessionDecision, kind: DateKind, now: datetime,
                      attendance: contract.AttendanceType) -> SessionDecision:
    status = (reconcile_status(s.owner_status, s.evidence.status)
              if isinstance(s.evidence, SessionSlots) else s.owner_status)
    facts = SessionFacts(status, s.owner_status == "UNKNOWN" and s.is_stale, s.evidence, kind, now, s.end)
    decision, reason = session_decision(facts)
    s = replace(s, owner_status=status, decision=decision, reason=reason)
    slot_now = now if kind == DateKind.TODAY else None
    if attendance == "ON_CALL":
        s = on_call(s, slot_now)
    if isinstance(s.evidence, SessionSlots):
        offered = tuple(b for b in s.evidence.blocks if block_state(b, slot_now) == "OPEN") if (
            s.decision == Decision.APPOINTMENT_REQUEST) else ()
        s = replace(s, open_slots=offered)
    return s


def is_match(decision: Decision) -> bool:
    return decision in (Decision.APPOINTMENT_REQUEST, Decision.SLOT_CHECK_REQUIRED)


def _unresolved(decision: Decision) -> bool:
    return decision in (Decision.CALLBACK_REQUIRED, Decision.HANDOFF_REQUIRED)


def on_requested_date(s: SessionDecision, requested: RequestedDate) -> bool:
    return s.one_day or requested.weekday in s.days


def _combine(sessions: tuple[SessionDecision, ...], named: bool) -> tuple[Decision, Reason | None, bool]:
    kinds = {s.decision for s in sessions}
    if len(kinds) == 1:
        return sessions[0].decision, sessions[0].reason, False
    match = next((s for s in sessions if is_match(s.decision)), None)
    if match is not None and not named:
        return match.decision, None, True
    # An unlabelled unresolved row stays in scope even after a named session was selected.
    unresolved = next((s for s in sessions if _unresolved(s.decision)), None)
    s = unresolved or next(s for s in sessions if s.decision == Decision.NOT_AVAILABLE)
    return s.decision, s.reason, False


def _empty_scope(facts: DoctorFacts, basis: Basis, decision: Decision, reason: Reason,
                 sessions: tuple[SessionDecision, ...] = (),
                 alternatives: tuple[SessionDecision, ...] = ()) -> DoctorDecision:
    if facts.doctor.attendanceType == "ON_CALL":
        decision, reason = Decision.HANDOFF_REQUIRED, Reason.ON_CALL_DOCTOR
    return DoctorDecision(facts, decision, reason, basis, sessions, alternatives=alternatives)


def _slot_sessions(facts: DoctorFacts) -> dict[str, contract.SlotSession]:
    if isinstance(facts.slots, contract.SlotPlan):
        return {normalised(s.session or ""): s for s in facts.slots.sessions}
    return {}


def _evidence(facts: DoctorFacts, slot: contract.SlotSession | None) -> SessionSlots | SlotsNotRead | None:
    if not isinstance(facts.slots, contract.SlotPlan):
        return facts.slots
    return SessionSlots(slot.status, slot.bookable, tuple(slot.slots)) if slot else SessionSlots.missing()


def _slot_only(slot: contract.SlotSession, basis: Basis) -> SessionDecision:
    return SessionDecision(slot.session, basis, slot.status, Decision.APPOINTMENT_REQUEST, None,
        slot.slots[0].start if slot.slots else None, slot.slots[-1].end if slot.slots else None,
        evidence=SessionSlots(slot.status, slot.bookable, tuple(slot.slots)), one_day=basis == Basis.USUAL_SCHEDULE)


def _today(facts: DoctorFacts, session: str | None, now: datetime) -> DoctorDecision:
    slots = _slot_sessions(facts)
    rows = [SessionDecision(row.session, Basis.LIVE_BOARD, row.status, Decision.APPOINTMENT_REQUEST, None,
                row.expectedTime, row.expectedEndTime, delay_minutes=row.delayMinutes, note=row.note,
                is_stale=row.isStale, evidence=_evidence(facts, slots.get(normalised(row.session or ""))))
            for row in facts.entries]
    labels = {normalised(row.session or "") for row in facts.entries}
    rows.extend(_slot_only(slot, Basis.LIVE_BOARD) for label, slot in slots.items() if label not in labels)
    sessions = tuple(_evaluate_session(s, DateKind.TODAY, now, facts.doctor.attendanceType) for s in rows)
    alternatives = tuple(s for s in sessions if is_match(s.decision))
    scoped = tuple(s for s in sessions if not session or not normalised(s.label or "")
                   or normalised(s.label) == normalised(session))
    if not scoped:
        reason = Reason.SESSION_NOT_ON_BOARD if sessions and session else Reason.BOARD_ENTRY_MISSING
        return _empty_scope(facts, Basis.LIVE_BOARD, Decision.CALLBACK_REQUIRED, reason, alternatives=alternatives)
    decision, reason, choice = _combine(scoped, bool(session))
    return DoctorDecision(facts, decision, reason, Basis.LIVE_BOARD, scoped, choice, alternatives)


def _usual(row: contract.UsualSession, decision: Decision = Decision.APPOINTMENT_REQUEST,
           reason: Reason | None = None) -> SessionDecision:
    return SessionDecision(row.label, Basis.USUAL_SCHEDULE, None, decision, reason, row.start, row.end,
                           tuple(row.daysOfWeek))


def _future(facts: DoctorFacts, requested: RequestedDate, session: str | None, now: datetime) -> DoctorDecision:
    if facts.doctor.attendanceType == "ON_CALL":
        usual = ()
    elif facts.profile is None:
        return DoctorDecision(facts, Decision.COULD_NOT_CHECK, Reason.PROFILE_UNAVAILABLE, Basis.USUAL_SCHEDULE)
    else:
        usual = facts.profile.usualSchedule
    slots = _slot_sessions(facts)
    rows = []
    joined = set()
    for row in usual:
        if requested.weekday not in row.daysOfWeek:
            rows.append(_usual(row, Decision.NOT_AVAILABLE, Reason.NOT_USUAL_DAY))
            continue
        label = normalised(row.label or "")
        joined.add(label)
        rows.append(replace(_usual(row), evidence=_evidence(facts, slots.get(label))))
    rows.extend(_slot_only(slot, Basis.USUAL_SCHEDULE) for label, slot in slots.items() if label not in joined)
    sessions = tuple(_evaluate_session(s, DateKind.FUTURE, now, facts.doctor.attendanceType)
                     if on_requested_date(s, requested) else s for s in rows)
    day = tuple(s for s in sessions if on_requested_date(s, requested))
    alternatives = tuple(s for s in day if is_match(s.decision))
    scoped = tuple(s for s in day if not session or normalised(s.label or "") == normalised(session)
                   or (not normalised(s.label or "") and _unresolved(s.decision)))
    if not day and not usual:
        return _empty_scope(facts, Basis.USUAL_SCHEDULE, Decision.CALLBACK_REQUIRED, Reason.NO_USUAL_SCHEDULE)
    if not scoped:
        reason = Reason.SESSION_NOT_USUAL if day and session else Reason.NOT_USUAL_DAY
        return _empty_scope(facts, Basis.USUAL_SCHEDULE, Decision.NOT_AVAILABLE, reason, sessions, alternatives)
    decision, reason, choice = _combine(scoped, bool(session))
    return DoctorDecision(facts, decision, reason, Basis.USUAL_SCHEDULE, scoped, choice, alternatives)


def decide_doctor(facts: DoctorFacts, requested: RequestedDate, *, session: str | None,
                  now: datetime) -> DoctorDecision:
    return _today(facts, session, now) if requested.kind == DateKind.TODAY else _future(facts, requested, session, now)


def working_hours(facts: DoctorFacts, requested: RequestedDate | None) -> DoctorDecision:
    if facts.doctor.attendanceType == "ON_CALL":
        return _empty_scope(facts, Basis.USUAL_SCHEDULE, Decision.HANDOFF_REQUIRED, Reason.ON_CALL_DOCTOR)
    if facts.profile is None:
        return DoctorDecision(facts, Decision.COULD_NOT_CHECK, Reason.PROFILE_UNAVAILABLE, Basis.USUAL_SCHEDULE)
    if not facts.profile.usualSchedule:
        return DoctorDecision(facts, Decision.CALLBACK_REQUIRED, Reason.NO_USUAL_SCHEDULE, Basis.USUAL_SCHEDULE)
    return DoctorDecision(facts, Decision.APPOINTMENT_REQUEST, None, Basis.USUAL_SCHEDULE,
                          tuple(_usual(s) for s in facts.profile.usualSchedule))


def block_at(blocks: Sequence[contract.SlotBlock], t: str) -> contract.SlotBlock | None:
    chosen = time.fromisoformat(t)
    return next((b for b in blocks if time.fromisoformat(b.start) <= chosen < time.fromisoformat(b.end)), None)


def _contains_time(s: SessionDecision, preferred: str, now: datetime) -> bool:
    if isinstance(s.evidence, SessionSlots) and s.evidence.blocks:
        return block_at(s.evidence.blocks, preferred) is not None
    if s.start is None or s.end is None:
        return False
    start = time.fromisoformat(s.start)
    if s.basis == Basis.LIVE_BOARD:
        start = max(start, now.time().replace(second=0, microsecond=0))
    return start <= time.fromisoformat(preferred) <= time.fromisoformat(s.end)


def decide_booking(decision: DoctorDecision, *, session: str | None,
                   preferred_time: str | None, now: datetime) -> BookingDecision:
    if decision.decision == Decision.HANDOFF_REQUIRED:
        return Handoff(Reason.ON_CALL_DOCTOR)
    if decision.decision == Decision.CALLBACK_REQUIRED:
        return Callback(decision.reason)
    if decision.decision == Decision.COULD_NOT_CHECK:
        return Handoff(Reason.PROFILE_UNAVAILABLE)
    if decision.decision == Decision.NOT_AVAILABLE:
        return NotAvailable(decision.reason, decision.alternatives)
    if isinstance(decision.facts.slots, contract.SlotPlan) and preferred_time is None:
        return TimeRequired(decision.alternatives)
    sessions = decision.sessions
    alternatives = decision.alternatives
    if preferred_time and sessions and not session:
        matched = tuple(s for s in sessions if _contains_time(s, preferred_time, now))
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
    if value == Decision.HANDOFF_REQUIRED:
        return Handoff(reason)
    if value == Decision.CALLBACK_REQUIRED:
        return Callback(reason)
    if value == Decision.NOT_AVAILABLE:
        return NotAvailable(reason, alternatives)
    if isinstance(decision.facts.slots, contract.SlotPlan):
        for s in sessions:
            if s.decision != Decision.APPOINTMENT_REQUEST or not isinstance(s.evidence, SessionSlots):
                continue
            block = block_at(s.evidence.blocks, preferred_time)
            if block is None:
                continue
            if session and normalised(s.label or "") != normalised(session):
                return NotAvailable(Reason.TIME_OUTSIDE_SESSION, alternatives)
            state = block_state(block, now if decision.facts.slots.date == now.date() else None)
            if state == "CLOSED":
                return NotAvailable(Reason.TIME_OUTSIDE_SESSION, alternatives)
            if state == "FULL":
                return NotAvailable(Reason.SLOT_FULL, alternatives)
            return Write(expected_slot=block.start)
        return NotAvailable(Reason.TIME_OUTSIDE_SESSION, alternatives)
    if preferred_time and sessions:
        if any(_window(s.end) == "UNKNOWN_END" or s.start is None for s in sessions):
            return Handoff(Reason.TIME_NOT_VERIFIABLE)
        if not any(_contains_time(s, preferred_time, now) for s in sessions):
            return NotAvailable(Reason.TIME_OUTSIDE_SESSION, alternatives)
    return Write()


def rank(decisions: Sequence[DoctorDecision], limit: int) -> list[DoctorDecision]:
    """Order and cap the candidates selected by the result policy."""
    order = {Decision.APPOINTMENT_REQUEST: 0, Decision.SLOT_CHECK_REQUIRED: 0,
             Decision.CALLBACK_REQUIRED: 1, Decision.HANDOFF_REQUIRED: 2, Decision.NOT_AVAILABLE: 3}
    return sorted(decisions,
                  key=lambda d: (order[d.decision], d.facts.doctor.name.casefold(), d.facts.doctor.id))[:limit]


def aggregate(decisions: list[DoctorDecision], search: SearchState,
              purpose: Purpose = Purpose.AVAILABILITY) -> ResultOutcome:
    if not search.matches_found and not search.complete:
        return ResultOutcome("HANDOFF_REQUIRED", "TRANSFER_DESK", Reason.SEARCH_INCOMPLETE)
    resolved = tuple(d for d in decisions if d.decision != Decision.COULD_NOT_CHECK)
    if purpose == Purpose.WORKING_HOURS:
        return ResultOutcome("WORKING_HOURS", "ASK_WHICH_DOCTOR", candidates=resolved)
    if search.matches_found:
        matches = tuple(d for d in resolved if is_match(d.decision))
        if matches and all(d.decision == Decision.SLOT_CHECK_REQUIRED for d in matches):
            return ResultOutcome("DOCTORS_MATCHED", "ASK_WHICH_DOCTOR", candidates=matches)
        return ResultOutcome("AVAILABILITY", "ASK_WHICH_DOCTOR", candidates=matches,
                             bookable_found=search.matches_found)
    callback = next((d for d in resolved if d.decision == Decision.CALLBACK_REQUIRED), None)
    if callback:
        return ResultOutcome("CALLBACK_REQUIRED", "ASK_CALLBACK_DETAILS", callback.reason, candidates=resolved)
    if any(d.decision == Decision.HANDOFF_REQUIRED for d in resolved):
        return ResultOutcome("HANDOFF_REQUIRED", "TRANSFER_DESK", Reason.ON_CALL_DOCTOR, candidates=resolved)
    return ResultOutcome("NOT_AVAILABLE", "OFFER_OTHER_SESSION_OR_DATE", candidates=resolved)
