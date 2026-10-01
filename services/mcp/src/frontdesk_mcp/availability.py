"""get_doctor_availability: one invocation composes the required routing decision, directory lookup,
doctor profile and live board for the requested date. Board status qualifies usual hours (never the
reverse); UNKNOWN stops the appointment journey (callback only); a failed board is a service error.
No slots, capacity, token numbers or arrival times are ever computed here."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from . import contract, outcomes
from . import knowledge_contract as kc
from .cache import DirectoryCache
from .clock import Clock, Deadline, local_now
from .config import Settings
from .context import CallContext
from .knowledge_client import KnowledgeClient, KnowledgeUnavailable
from .ops_client import InvalidIdentifier, Malformed, OpsClient, Rejected, Unavailable

logger = logging.getLogger(__name__)

WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


class AvailabilityRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: str = Field(description="'today' or an explicit confirmed calendar date YYYY-MM-DD.")
    doctorName: str | None = Field(default=None, max_length=100)  # noqa: N815 - wire names
    doctorId: str | None = Field(default=None, max_length=64)  # noqa: N815
    departmentName: str | None = Field(default=None, max_length=100)  # noqa: N815
    departmentId: str | None = Field(default=None, max_length=64)  # noqa: N815
    session: str | None = Field(default=None, max_length=40)
    gender: Literal["FEMALE", "MALE"] | None = None


class _Routing:
    def __init__(self, decision: kc.RouteResponse | None, failure: str | None) -> None:
        self.decision = decision
        self.failure = failure

    @property
    def cleared(self) -> bool:
        return self.decision is not None and self.decision.decision in kc.CLEARANCE


def _routing_outcome(routing: _Routing, today: str) -> outcomes.AvailabilityResult:
    if routing.decision is None:
        return outcomes.AvailabilityResult(outcome="ROUTING_UNAVAILABLE", nextStep="TRANSFER_DESK",
                                           facilityToday=today, detail=routing.failure)
    decision = routing.decision
    step = {"EMERGENCY_TRANSFER": "TRANSFER_EMERGENCY", "DESK_TRANSFER": "TRANSFER_DESK",
            "CLARIFY": "ASK_ROUTING_CLARIFICATION"}[decision.decision]
    return outcomes.AvailabilityResult(outcome="ROUTING_REQUIRED", nextStep=step, facilityToday=today,
                                       routing=_routing_out(decision))


def _routing_out(decision: kc.RouteResponse | None) -> outcomes.Routing | None:
    if decision is None:
        return None
    speak = outcomes.Speech(text=decision.speak.text, language=decision.speak.language) if decision.speak else None
    return outcomes.Routing(decision=decision.decision, speak=speak,
                            department=decision.department.name if decision.department else None)


class AvailabilityService:
    def __init__(self, ops: OpsClient, knowledge: KnowledgeClient, cache: DirectoryCache, settings: Settings,
                 clock: Clock) -> None:
        self.ops = ops
        self.knowledge = knowledge
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

    # ------------------------------------------------------------------ routing

    async def routing(self, ctx: CallContext, deadline: Deadline) -> _Routing:
        if ctx.turn is None:
            return _Routing(None, "TURN_CONTEXT_MISSING")
        try:
            return _Routing(await self.knowledge.route(ctx.turn, ctx, deadline), None)
        except KnowledgeUnavailable as exc:
            return _Routing(None, {"NOT_CONFIGURED": "ROUTING_NOT_CONFIGURED", "MALFORMED": "ROUTING_MALFORMED",
                                   "UNAVAILABLE": "ROUTING_UNAVAILABLE"}[exc.reason])

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

        # The routing decision and the first directory read are independent: overlap them.
        routing, directory = await asyncio.gather(self.routing(ctx, deadline),
                                                  self._prefetch(request, deadline), return_exceptions=True)
        if isinstance(routing, BaseException):  # defensive: routing() maps its own failures
            routing = _Routing(None, "ROUTING_UNAVAILABLE")
        if not routing.cleared:
            return _routing_outcome(routing, today_iso)
        routing_out = _routing_out(routing.decision)
        if isinstance(directory, BaseException):
            return self._service_error(directory, base, routing_out)

        try:
            target = await self._resolve(request, routing.decision, directory, deadline, base, routing_out)
            if isinstance(target, outcomes.AvailabilityResult):
                return target
            kind, ident = target
            if kind == "doctor":
                return await self._doctor(ident, requested, today, now, request.session, deadline, base, routing_out)
            return await self._department(ident, requested, today, now, request, deadline, base, routing_out)
        except (Unavailable, Malformed, Rejected, InvalidIdentifier) as exc:
            return self._service_error(exc, base, routing_out)

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _requested_date(value: str, today: date) -> tuple[date | None, str | None]:
        if value.strip().lower() == "today":
            return today, None
        try:
            parsed = date.fromisoformat(value.strip())
        except ValueError:
            return None, "DATE_FORMAT"
        if parsed < today:
            return None, "PAST_DATE"
        return parsed, None

    async def _prefetch(self, request: AvailabilityRequest, deadline: Deadline):
        """What the directory can answer before the routing decision is known."""
        if request.doctorId:
            return None
        if request.doctorName:
            return await self.ops.search_doctors(deadline, query=request.doctorName, gender=request.gender,
                                                 limit=self.settings.directory_page_size)
        return await self.departments(deadline)

    def _service_error(self, exc: BaseException, base: dict, routing_out) -> outcomes.AvailabilityResult:
        retry = exc.retry_after if isinstance(exc, Unavailable) else None
        detail = "BOARD_UNAVAILABLE" if getattr(exc, "stage", None) == "board" else "DIRECTORY_UNAVAILABLE"
        if isinstance(exc, Rejected) and exc.code == "NOT_FOUND":
            return outcomes.AvailabilityResult(outcome="NOT_FOUND", nextStep="ASK_TO_REPHRASE", **base,
                                               routing=routing_out)
        if isinstance(exc, (Rejected, InvalidIdentifier)):
            return outcomes.AvailabilityResult(outcome="INVALID_REQUEST", nextStep="ASK_TO_REPHRASE", **base,
                                               detail="DIRECTORY_REJECTED", routing=routing_out)
        logger.warning("availability_could_not_check",
                       extra={"fields": {"error": type(exc).__name__, "detail": detail}})
        return outcomes.AvailabilityResult(outcome="COULD_NOT_CHECK", nextStep="SAY_COULD_NOT_CHECK", **base,
                                           detail=detail, retryAfterSeconds=retry, routing=routing_out)

    async def _resolve(self, request, decision, directory, deadline, base, routing_out):
        if request.doctorId:
            return "doctor", request.doctorId
        if request.doctorName:
            page: contract.DoctorPage = directory
            if not page.items:
                return outcomes.AvailabilityResult(outcome="NOT_FOUND", nextStep="ASK_TO_REPHRASE", **base,
                                                   routing=routing_out)
            if len(page.items) == 1 and page.total <= 1:
                return "doctor", page.items[0].id
            choices = [outcomes.DoctorChoice(doctorId=d.id, name=d.name, departments=[r.name for r in d.departments],
                                             gender=d.gender) for d in page.items]
            return outcomes.AvailabilityResult(outcome="CLARIFICATION_NEEDED", nextStep="ASK_WHICH_DOCTOR", **base,
                                               choices=choices, complete=page.total <= len(page.items),
                                               totalMatches=page.total, routing=routing_out)
        departments: list[contract.Department] = [d for d in directory if d.active]
        wanted_id, wanted_name = request.departmentId, request.departmentName
        if not wanted_id and not wanted_name and decision.department is not None:
            wanted_name = decision.department.name
        if not wanted_id and not wanted_name:
            return outcomes.AvailabilityResult(outcome="INVALID_REQUEST", nextStep="ASK_TO_REPHRASE", **base,
                                               detail="TARGET_REQUIRED", routing=routing_out)
        if wanted_id:
            matches = [d for d in departments if d.id == wanted_id]
        else:
            needle = " ".join(wanted_name.casefold().split())
            matches = [d for d in departments if d.name.casefold() == needle]
            if not matches:
                matches = [d for d in departments if needle in d.name.casefold() or d.name.casefold() in needle]
        offered = [outcomes.DepartmentChoice(id=d.id, name=d.name) for d in departments if d.hasConsultant]
        if len(matches) != 1:
            return outcomes.AvailabilityResult(outcome="CLARIFICATION_NEEDED", nextStep="ASK_WHICH_DEPARTMENT",
                                               **base, departmentChoices=offered, routing=routing_out,
                                               detail="DEPARTMENT_AMBIGUOUS" if matches else "DEPARTMENT_UNMATCHED")
        department = matches[0]
        if not department.hasConsultant:
            return outcomes.AvailabilityResult(outcome="NOT_FOUND", nextStep="TRANSFER_DESK", **base,
                                               detail="NO_CONSULTANT", routing=routing_out,
                                               department=outcomes.DepartmentChoice(id=department.id,
                                                                                    name=department.name))
        return "department", department

    async def _board(self, deadline: Deadline, *, date_param: str, doctor_id: str | None = None,
                     department: str | None = None) -> contract.AvailabilityBoard:
        try:
            return await self.ops.get_availability(deadline, date=date_param, doctor_id=doctor_id,
                                                   department=department)
        except (Unavailable, Malformed, Rejected) as exc:
            exc.stage = "board"  # type: ignore[attr-defined]
            raise

    async def _doctor(self, doctor_id, requested, today, now, session, deadline, base, routing_out):
        date_param = "today" if requested == today else requested.isoformat()
        profile_task = asyncio.create_task(self.profile(doctor_id, deadline))
        board_task = asyncio.create_task(self._board(deadline, date_param=date_param, doctor_id=doctor_id))
        profile, board = await asyncio.gather(profile_task, board_task, return_exceptions=True)
        if isinstance(board, BaseException):
            if isinstance(profile, BaseException) and isinstance(profile, Rejected) and profile.code == "NOT_FOUND":
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
        if profile is None and not board.items:
            return outcomes.AvailabilityResult(outcome="NOT_FOUND", nextStep="ASK_TO_REPHRASE", **base,
                                               routing=routing_out)
        entries = [e for e in board.items if e.doctorId == doctor_id]
        matched = None
        if session:
            scoped = [e for e in entries if e.session and e.session.casefold() == session.strip().casefold()]
            matched = bool(scoped)
            if scoped:
                entries = scoped
        name = profile.name if profile else (entries[0].doctorName if entries else doctor_id)
        doctor = self._overlay(profile, name, doctor_id, entries, requested, today, now)
        return self._finish([doctor], base, routing_out, session_matched=matched, detail=detail,
                            default_step="OFFER_APPOINTMENT_REQUEST")

    async def _department(self, department, requested, today, now, request, deadline, base, routing_out):
        date_param = "today" if requested == today else requested.isoformat()
        page, board = await asyncio.gather(
            self.ops.search_doctors(deadline, department=department.id, gender=request.gender,
                                    limit=self.settings.directory_page_size),
            self._board(deadline, date_param=date_param, department=department.id))
        doctors = []
        for summary in page.items:
            entries = [e for e in board.items if e.doctorId == summary.id]
            doctors.append(self._overlay(None, summary.name, summary.id, entries, requested, today, now,
                                         summary=summary))
        dept_out = outcomes.DepartmentChoice(id=department.id, name=department.name)
        if not doctors:
            return outcomes.AvailabilityResult(outcome="NOT_FOUND", nextStep="TRANSFER_DESK", **base,
                                               department=dept_out, detail="NO_DOCTORS", routing=routing_out)
        return self._finish(doctors, base, routing_out, default_step="ASK_WHICH_DOCTOR", department=dept_out,
                            complete=page.total <= len(page.items), total=page.total)

    def _overlay(self, profile, name, doctor_id, entries, requested, today, now,
                 summary=None) -> outcomes.DoctorAvailability:
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
        unknown = [e.session or "" for e in entries if e.status == "UNKNOWN"]
        attendance = source.attendanceType if source else "REGULAR"
        if entries and all(e.status == "UNKNOWN" for e in entries):
            journey = "CALLBACK_ONLY"
        elif attendance == "ON_CALL" and not any(e.status in ("IN", "LATE") for e in entries):
            journey = "DESK"
        else:
            journey = "APPOINTMENT_REQUEST"
        return outcomes.DoctorAvailability(
            doctorId=doctor_id, name=name, departments=[r.name for r in source.departments] if source else [],
            attendanceType=attendance, gender=source.gender if source else None,
            dataConfirmed=profile.dataConfirmed if profile else None, usualSessions=usual, board=board,
            unknownSessions=[s for s in unknown], journey=journey)

    @staticmethod
    def _expired(entry: contract.AvailabilityEntry, requested: date, today: date, now: datetime) -> bool:
        if requested != today or not entry.expectedEndTime or entry.status in ("CANCELLED", "UNKNOWN"):
            return False
        hour, minute = (int(part) for part in entry.expectedEndTime.split(":"))
        return (now.hour, now.minute) >= (hour, minute)

    @staticmethod
    def _finish(doctors, base, routing_out, *, default_step, session_matched=None, detail=None, department=None,
                complete=True, total=None) -> outcomes.AvailabilityResult:
        common = {**base, "doctors": doctors, "routing": routing_out, "department": department,
                  "sessionMatched": session_matched, "detail": detail, "complete": complete, "totalMatches": total}
        if all(d.journey == "CALLBACK_ONLY" for d in doctors):
            return outcomes.AvailabilityResult(outcome="CALLBACK_REQUIRED", nextStep="ASK_CALLBACK_DETAILS",
                                               callback=outcomes.Callback(), **common)
        if len(doctors) == 1 and doctors[0].journey == "DESK":
            return outcomes.AvailabilityResult(outcome="AVAILABILITY", nextStep="TRANSFER_DESK", **common)
        return outcomes.AvailabilityResult(outcome="AVAILABILITY", nextStep=default_step, **common)
