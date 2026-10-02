"""Directory, profiles and live board only. UNKNOWN in scope requires callback details;
a failed owner read is a service error. Independent profile and board reads overlap."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from . import board_scope, contract, outcomes
from .cache import DirectoryCache
from .clock import Clock, Deadline, local_now
from .config import Settings
from .context import CallContext
from .ops_client import InvalidIdentifier, Malformed, OpsClient, Rejected, Unavailable

logger = logging.getLogger(__name__)

WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
READ_ERRORS = (Unavailable, Malformed, Rejected, InvalidIdentifier)


class AvailabilityRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: str = Field(description="'today' or an explicit confirmed calendar date YYYY-MM-DD.")
    doctorName: str | None = Field(default=None, max_length=100)  # noqa: N815 - wire names
    doctorId: str | None = Field(default=None, max_length=64)  # noqa: N815
    departmentName: str | None = Field(default=None, max_length=100)  # noqa: N815
    departmentId: str | None = Field(default=None, max_length=64)  # noqa: N815
    session: str | None = Field(default=None, max_length=40)
    gender: Literal["FEMALE", "MALE"] | None = None


def _normalised(name: str) -> str:
    return " ".join(name.casefold().split())


def _choice(d: contract.Department) -> outcomes.DepartmentChoice:
    return outcomes.DepartmentChoice(id=d.id, name=d.name)


class AvailabilityService:
    def __init__(self, ops: OpsClient, cache: DirectoryCache, settings: Settings,
                 clock: Clock) -> None:
        self.ops = ops
        self.cache = cache
        self.settings = settings
        self.clock = clock

    # ------------------------------------------------------------------ cached directory reads

    async def departments(self, deadline: Deadline) -> list[contract.Department]:
        cached = self.cache.get(("departments",))
        if cached is not None:
            return cached
        items = (await self.ops.list_departments(deadline)).items
        self.cache.set(("departments",), items)
        return items

    async def profile(self, doctor_id: str, deadline: Deadline) -> contract.DoctorDetail:
        cached = self.cache.get(("doctor", doctor_id))
        if cached is not None:
            return cached
        detail = await self.ops.get_doctor(doctor_id, deadline)
        self.cache.set(("doctor", doctor_id), detail)
        return detail

    # ------------------------------------------------------------------ the tool

    async def get(self, ctx: CallContext, request: AvailabilityRequest) -> outcomes.AvailabilityResult:
        now = local_now(self.clock, self.settings.zone)
        today = now.date()
        today_iso = today.isoformat()
        deadline = Deadline(self.settings.read_deadline_seconds)

        requested, date_detail = self._requested_date(request.date, today)
        if requested is None:
            return outcomes.AvailabilityResult(outcome="INVALID_REQUEST", nextStep="ASK_EXPLICIT_DATE",
                                               facilityToday=today_iso, detail=date_detail)
        base = {"facilityToday": today_iso, "requestedDate": requested.isoformat(),
                "weekday": WEEKDAYS[requested.weekday()]}
        date_param = "today" if requested == today else requested.isoformat()

        try:
            fetched = await self._prefetch(request, date_param, deadline)
            return self._compose(request, fetched, requested, today, now, base)
        except READ_ERRORS as exc:
            return self._service_error(exc, base)

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _requested_date(value: str, today: date) -> tuple[date | None, str | None]:
        text = value.strip()
        if text.lower() == "today":
            return today, None
        if not ISO_DATE.fullmatch(text):
            return None, "DATE_FORMAT"
        try:
            parsed = date.fromisoformat(text)
        except ValueError:
            return None, "DATE_FORMAT"
        if parsed < today:
            return None, "PAST_DATE"
        return parsed, None

    async def _prefetch(self, request: AvailabilityRequest, date_param: str, deadline: Deadline) -> dict[str, Any]:
        """Resolve the target, overlapping independent owner reads."""
        if request.doctorId:
            profile, board = await asyncio.gather(self.profile(request.doctorId, deadline),
                                                  self._board(deadline, date_param=date_param,
                                                              doctor_id=request.doctorId), return_exceptions=True)
            return {"kind": "doctor", "doctor_id": request.doctorId, "profile": profile, "board": board}
        if request.doctorName:
            page = await self.ops.search_doctors(deadline, query=request.doctorName, gender=request.gender,
                                                 limit=self.settings.directory_page_size)
            if len(page.items) == 1 and page.total <= 1:  # the doctor is now known
                doctor_id = page.items[0].id
                profile, board = await asyncio.gather(self.profile(doctor_id, deadline),
                                                      self._board(deadline, date_param=date_param, doctor_id=doctor_id),
                                                      return_exceptions=True)
                return {"kind": "doctor", "doctor_id": doctor_id, "profile": profile, "board": board}
            return {"kind": "search", "page": page}
        departments = await self.departments(deadline)
        result: dict[str, Any] = {"kind": "departments", "departments": departments}
        wanted = request.departmentId or request.departmentName
        if wanted:
            matches = self._match_department(departments, request.departmentId, request.departmentName)
            result["matches"] = matches
            if len(matches) == 1 and matches[0].hasConsultant:
                page, board = await asyncio.gather(
                    self.ops.search_doctors(deadline, department=matches[0].id, gender=request.gender,
                                            limit=self.settings.directory_page_size),
                    self._board(deadline, date_param=date_param, department=matches[0].id), return_exceptions=True)
                result.update(page=page, board=board)
        return result

    @staticmethod
    def _match_department(departments, department_id, department_name) -> list[contract.Department]:
        active = [d for d in departments if d.active]
        if department_id:
            return [d for d in active if d.id == department_id]
        needle = _normalised(department_name or "")
        return [d for d in active if _normalised(d.name) == needle]  # exact only: never guess a department

    def _service_error(self, exc: BaseException, base: dict) -> outcomes.AvailabilityResult:
        retry = exc.retry_after if isinstance(exc, Unavailable) else None
        detail = "BOARD_UNAVAILABLE" if getattr(exc, "stage", None) == "board" else "DIRECTORY_UNAVAILABLE"
        if isinstance(exc, Rejected) and exc.code == "NOT_FOUND":
            return outcomes.AvailabilityResult(outcome="NOT_FOUND", nextStep="ASK_TO_REPHRASE", **base)
        if isinstance(exc, (Rejected, InvalidIdentifier)):
            return outcomes.AvailabilityResult(outcome="INVALID_REQUEST", nextStep="ASK_TO_REPHRASE", **base,
                                               detail="DIRECTORY_REJECTED")
        logger.warning("availability_could_not_check",
                       extra={"fields": {"error": type(exc).__name__, "detail": detail}})
        return outcomes.AvailabilityResult(outcome="COULD_NOT_CHECK", nextStep="SAY_COULD_NOT_CHECK", **base,
                                           detail=detail, retryAfterSeconds=retry)

    async def _board(self, deadline: Deadline, *, date_param: str, doctor_id: str | None = None,
                     department: str | None = None) -> contract.AvailabilityBoard:
        try:
            return await self.ops.get_availability(deadline, date=date_param, doctor_id=doctor_id,
                                                   department=department)
        except (Unavailable, Malformed, Rejected) as exc:
            exc.stage = "board"  # type: ignore[attr-defined]
            raise

    def _compose(self, request, fetched, requested, today, now, base) -> outcomes.AvailabilityResult:
        if fetched["kind"] == "doctor":
            return self._doctor(fetched["doctor_id"], fetched["profile"], fetched["board"], requested, today, now,
                                request.session, base)
        if fetched["kind"] == "search":
            page: contract.DoctorPage = fetched["page"]
            if not page.items:
                return outcomes.AvailabilityResult(outcome="NOT_FOUND", nextStep="ASK_TO_REPHRASE", **base)
            choices = [outcomes.DoctorChoice(doctorId=d.id, name=d.name, departments=[r.name for r in d.departments],
                                             gender=d.gender) for d in page.items]
            return outcomes.AvailabilityResult(outcome="CLARIFICATION_NEEDED", nextStep="ASK_WHICH_DOCTOR", **base,
                                               choices=choices, complete=page.total <= len(page.items),
                                               totalMatches=page.total)
        departments: list[contract.Department] = fetched["departments"]
        offered = [_choice(d) for d in departments if d.active and d.hasConsultant]
        matches = fetched.get("matches")
        if matches is None:
            return outcomes.AvailabilityResult(outcome="INVALID_REQUEST", nextStep="ASK_TO_REPHRASE", **base,
                                               detail="TARGET_REQUIRED")
        if len(matches) != 1:
            return outcomes.AvailabilityResult(outcome="CLARIFICATION_NEEDED", nextStep="ASK_WHICH_DEPARTMENT", **base,
                                               departmentChoices=offered,
                                               detail="DEPARTMENT_AMBIGUOUS" if matches else "DEPARTMENT_UNMATCHED")
        department = matches[0]
        if not department.hasConsultant:
            return outcomes.AvailabilityResult(outcome="NOT_FOUND", nextStep="TRANSFER_DESK", **base,
                                               detail="NO_CONSULTANT",
                                               department=_choice(department))
        page, board = fetched["page"], fetched["board"]
        return self._department(department, page, board, requested, today, now, request.session, base)

    def _doctor(self, doctor_id, profile, board, requested, today, now, session, base):
        if isinstance(board, BaseException):
            if isinstance(profile, Rejected) and profile.code == "NOT_FOUND":
                raise profile
            raise board
        detail = None
        if isinstance(profile, BaseException):
            if isinstance(profile, Rejected) and profile.code == "NOT_FOUND":
                raise profile
            if isinstance(profile, (Unavailable, Malformed)):
                detail, profile = "PROFILE_UNAVAILABLE", None
            else:
                raise profile
        entries = [e for e in board.items if e.doctorId == doctor_id]
        if profile is None and not entries:
            # The profile read failed and the owner returned no row: nothing is known. A failed read is never a
            # definite "no such doctor".
            return outcomes.AvailabilityResult(outcome="COULD_NOT_CHECK", nextStep="SAY_COULD_NOT_CHECK", **base,
                                               detail="PROFILE_UNAVAILABLE")
        weekday = WEEKDAYS[requested.weekday()]
        scope = board_scope.scope_board(entries, session=session,
                                        usual_today=board_scope.usual_sessions_on(profile, weekday))
        if scope.missing_session:
            detail = "SESSION_ROW_MISSING"  # the contract promises a row per session; its absence is UNKNOWN
        elif not entries and detail is None:
            detail = "BOARD_ENTRY_MISSING"  # the owner returned no row: that is UNKNOWN, never bookable hours
        name = profile.name if profile else (entries[0].doctorName if entries else doctor_id)
        doctor = self._overlay(profile, name, doctor_id, scope, requested, today, now)
        return self._finish([doctor], base, session_matched=scope.matched, detail=detail,
                            default_step="OFFER_APPOINTMENT_REQUEST")

    def _department(self, department, page, board, requested, today, now, session, base):
        if isinstance(board, BaseException):
            raise board
        if isinstance(page, BaseException):
            raise page
        doctors = []
        for summary in page.items:
            entries = [e for e in board.items if e.doctorId == summary.id]
            if not board_scope.in_scope_for_department(entries, session):
                continue  # only rows for other sessions: not UNKNOWN, simply not in this session
            scope = board_scope.scope_board(entries, session=session)
            doctors.append(self._overlay(None, summary.name, summary.id, scope, requested, today, now,
                                         summary=summary))
        dept_out = _choice(department)
        if not doctors:
            return outcomes.AvailabilityResult(outcome="NOT_FOUND", nextStep="TRANSFER_DESK", **base,
                                               department=dept_out,
                                               detail="NO_SESSION" if session and page.items else "NO_DOCTORS")
        return self._finish(doctors, base, default_step="ASK_WHICH_DOCTOR", department=dept_out,
                            complete=page.total <= len(page.items), total=page.total,
                            session_matched=bool(session) or None)

    def _overlay(self, profile, name, doctor_id, scope: board_scope.Scope, requested, today, now,
                 summary=None) -> outcomes.DoctorAvailability:
        entries = scope.entries
        source = profile or summary
        weekday = WEEKDAYS[requested.weekday()]
        usual = None
        if profile is not None:
            usual = [outcomes.UsualSessionOut(label=s.label, daysOfWeek=list(s.daysOfWeek), start=s.start, end=s.end,
                                              onRequestedDate=weekday in s.daysOfWeek) for s in profile.usualSchedule]
        board = [outcomes.BoardSessionOut(
            session=e.session, status=e.status, expectedTime=e.expectedTime, expectedEndTime=e.expectedEndTime,
            delayMinutes=e.delayMinutes, note=e.note, isStale=e.isStale,
            expired=self._expired(e, requested, today, now)) for e in entries]
        unknown = scope.unknown_sessions
        attendance = source.attendanceType if source else "REGULAR"
        if scope.unknown:
            journey = "CALLBACK_ONLY"  # any UNKNOWN row in scope, a missing promised row, or no row at all
        elif attendance == "ON_CALL" and not any(e.status in ("IN", "LATE") for e in entries):
            journey = "DESK"
        else:
            journey = "APPOINTMENT_REQUEST"
        return outcomes.DoctorAvailability(
            doctorId=doctor_id, name=name, departments=[r.name for r in source.departments] if source else [],
            attendanceType=attendance, gender=source.gender if source else None,
            dataConfirmed=profile.dataConfirmed if profile else None, usualSessions=usual, board=board,
            unknownSessions=unknown, journey=journey)

    @staticmethod
    def _expired(entry: contract.AvailabilityEntry, requested: date, today: date, now: datetime) -> bool:
        if requested != today or not entry.expectedEndTime or entry.status in ("CANCELLED", "UNKNOWN"):
            return False
        hour, minute = (int(part) for part in entry.expectedEndTime.split(":"))
        return (now.hour, now.minute) >= (hour, minute)

    @staticmethod
    def _finish(doctors, base, *, default_step, session_matched=None, detail=None, department=None,
                complete=True, total=None) -> outcomes.AvailabilityResult:
        common = {**base, "doctors": doctors, "department": department,
                  "sessionMatched": session_matched, "detail": detail, "complete": complete, "totalMatches": total}
        if all(d.journey == "CALLBACK_ONLY" for d in doctors):
            return outcomes.AvailabilityResult(outcome="CALLBACK_REQUIRED", nextStep="ASK_CALLBACK_DETAILS",
                                               callback=outcomes.Callback(), **common)
        if len(doctors) == 1 and doctors[0].journey == "DESK":
            return outcomes.AvailabilityResult(outcome="AVAILABILITY", nextStep="TRANSFER_DESK", **common)
        return outcomes.AvailabilityResult(outcome="AVAILABILITY", nextStep=default_step, **common)
