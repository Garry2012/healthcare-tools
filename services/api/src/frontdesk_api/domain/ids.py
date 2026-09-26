"""Deterministic session and slot identifiers (IMPLEMENTATION.md §2.1).

session id = ses_<doctorId>_<date>_<n>
slot id    = slot_<sessionId>_<position as 2+ digits | HHMM>

`n` is the 1-based position of the session in the doctor's template, or `e<seq>` for a
session added by an EXTRA_SESSION exception. Doctor ids may contain underscores, so ids
are parsed from the right.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_N = re.compile(r"^(\d+|e\d+)$")


@dataclass(frozen=True, slots=True)
class SessionRef:
    doctor_id: str
    date: date
    n: str

    @property
    def session_id(self) -> str:
        return session_id(self.doctor_id, self.date, self.n)


@dataclass(frozen=True, slots=True)
class SlotRef:
    session: SessionRef
    suffix: str

    @property
    def slot_id(self) -> str:
        return f"slot_{self.session.session_id}_{self.suffix}"


def session_id(doctor_id: str, on: date, n: str | int) -> str:
    return f"ses_{doctor_id}_{on.isoformat()}_{n}"


def position_slot_id(sid: str, position: int) -> str:
    return f"slot_{sid}_{position:02d}"


def timed_slot_id(sid: str, hhmm: str) -> str:
    return f"slot_{sid}_{hhmm.replace(':', '')}"


def parse_session_id(value: str) -> SessionRef | None:
    if not value.startswith("ses_"):
        return None
    parts = value[4:].rsplit("_", 2)
    if len(parts) != 3:
        return None
    doctor_id, day, n = parts
    if not doctor_id or not _DATE.match(day) or not _N.match(n):
        return None
    try:
        on = date.fromisoformat(day)
    except ValueError:
        return None
    return SessionRef(doctor_id, on, n)


def parse_slot_id(value: str) -> SlotRef | None:
    if not value.startswith("slot_"):
        return None
    sid, _, suffix = value[5:].rpartition("_")
    if not suffix.isdigit():
        return None
    ref = parse_session_id(sid)
    return SlotRef(ref, suffix) if ref else None
