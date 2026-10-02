"""One session-scope rule for the live board, shared by get_doctor_availability and manage_booking so the two
tools can never disagree about the same day.

Scope = the board rows the caller's request is about:
- `session` given and the board has rows with that label → those rows, plus any unlabelled row (the owner's
  UNKNOWN/missing shape cannot be scoped away);
- `session` given but no such labelled row → if the doctor's usual schedule lists that session on that weekday,
  the row the contract promises is missing: that is UNKNOWN; otherwise the whole board stays in scope (the caller
  may mean any session);
- no `session` but a `preferred_time` inside exactly one row's window → that row plus unlabelled rows; a time no
  window holds → the rows without a known window, else the whole board;
- otherwise the whole board.

The appointment journey is callback-only when the scope holds any UNKNOWN row, no row at all, or a missing
promised row. No hours, capacity or slots are inferred here; rows are the owner's.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import contract


def normalised(label: str | None) -> str:
    return " ".join((label or "").casefold().split())


@dataclass(frozen=True)
class Scope:
    entries: list[contract.AvailabilityEntry]  # rows in scope
    resolved: bool  # a specific session (or time window) was identified
    matched: bool | None  # session argument matched a labelled row (None when no session was given)
    missing_session: bool  # the requested session is usual today but the board has no row for it
    time_outside_window: bool  # a preferred time falls outside the chosen session's known window

    @property
    def unknown(self) -> bool:
        return self.missing_session or not self.entries or any(e.status == "UNKNOWN" for e in self.entries)

    @property
    def unknown_sessions(self) -> list[str]:
        return [e.session or "" for e in self.entries if e.status == "UNKNOWN"]


def _holds(entry: contract.AvailabilityEntry, time: str) -> bool:
    return bool(entry.expectedTime and entry.expectedEndTime and entry.expectedTime <= time <= entry.expectedEndTime)


def scope_board(entries: list[contract.AvailabilityEntry], *, session: str | None = None,
                preferred_time: str | None = None, usual_today: list[str] | None = None) -> Scope:
    unlabelled = [e for e in entries if not e.session]
    if session:
        wanted = normalised(session)
        labelled = [e for e in entries if e.session and normalised(e.session) == wanted]
        if labelled:
            outside = bool(preferred_time) and any(e.expectedTime and e.expectedEndTime for e in labelled) \
                and not any(_holds(e, preferred_time) for e in labelled)
            return Scope(labelled + unlabelled, True, True, False, outside)
        missing = any(normalised(label) == wanted for label in (usual_today or []))
        return Scope(list(entries), False, False, missing, False)
    if preferred_time and len(entries) > 1:
        holding = [e for e in entries if _holds(e, preferred_time)]
        if len(holding) == 1:
            return Scope(holding + unlabelled, True, None, False, False)
        unplaced = [e for e in entries if not (e.expectedTime and e.expectedEndTime)]
        if unplaced:
            return Scope(unplaced, True, None, False, False)
    return Scope(list(entries), False, None, False, False)


def in_scope_for_department(entries: list[contract.AvailabilityEntry], session: str | None) -> bool:
    """A doctor whose only rows are labelled for other sessions is not in a session-scoped department query."""
    if not session:
        return True
    wanted = normalised(session)
    return not entries or any(not e.session or normalised(e.session) == wanted for e in entries)


def usual_sessions_on(profile: contract.DoctorDetail | None, weekday: str) -> list[str]:
    if profile is None:
        return []
    return [s.label for s in profile.usualSchedule if s.label and weekday in s.daysOfWeek]
