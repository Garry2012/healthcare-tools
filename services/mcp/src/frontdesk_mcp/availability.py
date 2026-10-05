"""Resolve a target, retrieve contracted facts, apply the shared policy and present them."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from . import availability_policy as policy
from . import contract, outcomes
from .cache import DirectoryCache
from .clock import Clock, Deadline, local_now
from .config import Settings
from .context import CallContext
from .ops_client import InvalidIdentifier, OpsClient, Rejected, Unavailable
from .schedule_reader import READ_ERRORS, ScheduleReader

logger = logging.getLogger(__name__)


class AvailabilityRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: str | None = None
    purpose: policy.Purpose = policy.Purpose.AVAILABILITY
    doctorName: str | None = Field(default=None, max_length=100)  # noqa: N815
    doctorId: str | None = Field(default=None, max_length=64)  # noqa: N815
    departmentName: str | None = Field(default=None, max_length=100)  # noqa: N815
    departmentId: str | None = Field(default=None, max_length=64)  # noqa: N815
    session: str | None = Field(default=None, max_length=40)
    gender: Literal["FEMALE", "MALE"] | None = None


def _choice(d: contract.Department) -> outcomes.DepartmentChoice:
    return outcomes.DepartmentChoice(id=d.id, name=d.name)


def doctor_out(d: policy.DoctorDecision, requested: policy.RequestedDate | None) -> outcomes.DoctorAvailability:
    doctor, profile = d.facts.doctor, d.facts.profile
    sessions = [outcomes.session_out(s, requested) for s in d.sessions]
    return outcomes.DoctorAvailability(
        doctorId=doctor.id, name=doctor.name, departments=[r.name for r in doctor.departments],
        attendanceType=doctor.attendanceType, gender=doctor.gender,
        dataConfirmed=profile.dataConfirmed if profile else None,
        board=sessions if d.basis == policy.Basis.LIVE_BOARD else [],
        usualSessions=sessions if d.basis == policy.Basis.USUAL_SCHEDULE else None,
        decision=d.decision, reason=d.reason, sessionChoiceRequired=d.session_choice_required)


class AvailabilityService:
    def __init__(self, ops: OpsClient, cache: DirectoryCache, settings: Settings,
                 clock: Clock, reader: ScheduleReader | None = None) -> None:
        self.reader = reader or ScheduleReader(ops, cache, settings)
        self.settings, self.clock = settings, clock

    async def get(self, ctx: CallContext, request: AvailabilityRequest) -> outcomes.AvailabilityResult:
        now = local_now(self.clock, self.settings.zone)
        requested = policy.resolve_date(request.date, now, request.purpose)
        if isinstance(requested, policy.DateError):
            return outcomes.AvailabilityResult(outcome="INVALID_REQUEST", nextStep="ASK_EXPLICIT_DATE",
                                               facilityToday=now.date().isoformat(), detail=requested)
        base = {"facilityToday": now.date().isoformat(),
                "requestedDate": requested.value.isoformat() if requested else None,
                "weekday": requested.weekday if requested else None}
        deadline = Deadline(self.settings.read_deadline_seconds)
        try:
            return await self._resolve(request, requested, now, deadline, base)
        except READ_ERRORS as exc:
            return self._service_error(exc, base)

    def _service_error(self, exc: BaseException, base: dict) -> outcomes.AvailabilityResult:
        retry = exc.retry_after if isinstance(exc, Unavailable) else None
        detail = {"board": "BOARD_UNAVAILABLE", "profile": "PROFILE_UNAVAILABLE"}.get(
            getattr(exc, "stage", None), "DIRECTORY_UNAVAILABLE")
        if isinstance(exc, Rejected) and exc.code == "NOT_FOUND":
            return outcomes.AvailabilityResult(outcome="NOT_FOUND", nextStep="ASK_TO_REPHRASE", **base)
        if isinstance(exc, (Rejected, InvalidIdentifier)):
            return outcomes.AvailabilityResult(outcome="INVALID_REQUEST", nextStep="ASK_TO_REPHRASE", **base,
                                               detail="DIRECTORY_REJECTED")
        logger.warning("availability_could_not_check",
                       extra={"fields": {"error": type(exc).__name__, "detail": detail}})
        return outcomes.AvailabilityResult(outcome="COULD_NOT_CHECK", nextStep="SAY_COULD_NOT_CHECK", **base,
                                           detail=detail, retryAfterSeconds=retry)

    async def _resolve(self, request: AvailabilityRequest, requested: policy.RequestedDate | None,
                       now: datetime, deadline: Deadline, base: dict) -> outcomes.AvailabilityResult:
        def evaluate(facts: policy.DoctorFacts) -> policy.DoctorDecision:
            if request.purpose == policy.Purpose.WORKING_HOURS:
                return policy.working_hours(facts, requested)
            return policy.decide_doctor(facts, requested, session=request.session, now=now)

        if request.doctorId:
            facts = await self.reader.doctor(request.doctorId, requested, request.purpose, deadline)
            return self._single(evaluate(facts), requested, request, base)
        if request.doctorName:
            page = await self.reader.search(deadline, query=request.doctorName, gender=request.gender)
            if not page.items:
                return outcomes.AvailabilityResult(outcome="NOT_FOUND", nextStep="ASK_TO_REPHRASE", **base)
            if len(page.items) == 1 and page.total == 1:
                facts = await self.reader.doctor(page.items[0].id, requested, request.purpose, deadline, page.items[0])
                return self._single(evaluate(facts), requested, request, base)
            choices = [outcomes.DoctorChoice(doctorId=d.id, name=d.name, departments=[r.name for r in d.departments],
                                             gender=d.gender) for d in page.items[:self.settings.doctor_choice_limit]]
            return outcomes.AvailabilityResult(outcome="CLARIFICATION_NEEDED", nextStep="ASK_WHICH_DOCTOR", **base,
                                               choices=choices, totalMatches=page.total,
                                               complete=page.total <= len(page.items))
        if not request.departmentId and not request.departmentName:
            return outcomes.AvailabilityResult(outcome="INVALID_REQUEST", nextStep="ASK_TO_REPHRASE", **base,
                                               detail="TARGET_REQUIRED")
        departments = [d for d in await self.reader.departments(deadline) if d.active]
        matches = [d for d in departments if (d.id == request.departmentId if request.departmentId else
                   policy.normalised(d.name) == policy.normalised(request.departmentName))]
        if len(matches) != 1:
            return outcomes.AvailabilityResult(outcome="CLARIFICATION_NEEDED", nextStep="ASK_WHICH_DEPARTMENT", **base,
                departmentChoices=[_choice(d) for d in departments if d.hasConsultant],
                detail="DEPARTMENT_AMBIGUOUS" if matches else "DEPARTMENT_UNMATCHED")
        department = matches[0]
        if not department.hasConsultant:
            return outcomes.AvailabilityResult(outcome="NOT_FOUND", nextStep="TRANSFER_DESK", **base,
                                               department=_choice(department), detail="NO_CONSULTANT")
        found = await self.reader.department(department.id, request.gender, requested, request.purpose,
                                             deadline, evaluate)
        if found.total == 0:
            return outcomes.AvailabilityResult(outcome="NOT_FOUND", nextStep="TRANSFER_DESK", **base,
                                               department=_choice(department), detail="NO_DOCTORS")
        decisions = [evaluate(f) for f in found.facts]
        result = policy.aggregate(decisions, found.search, request.purpose)
        listed = policy.rank(result.candidates, self.settings.doctor_choice_limit)
        today = request.purpose == policy.Purpose.AVAILABILITY and requested.kind == policy.DateKind.TODAY
        basis = policy.Basis.LIVE_BOARD if today else policy.Basis.USUAL_SCHEDULE
        return outcomes.AvailabilityResult(outcome=result.outcome, nextStep=result.next_step, **base,
            department=_choice(department), basis=basis, doctors=[doctor_out(d, requested) for d in listed],
            bookableFound=result.bookable_found, totalMatches=found.total, complete=found.search.complete,
            detail=result.reason,
            callback=outcomes.Callback(reason=result.reason) if result.outcome == "CALLBACK_REQUIRED" else None)

    @staticmethod
    def _single(d: policy.DoctorDecision, requested: policy.RequestedDate | None,
                request: AvailabilityRequest, base: dict) -> outcomes.AvailabilityResult:
        outcome, step = {
            policy.Decision.APPOINTMENT_REQUEST: ("AVAILABILITY", "ASK_WHICH_SESSION" if d.session_choice_required
                                                 else "OFFER_APPOINTMENT_REQUEST"),
            policy.Decision.CALLBACK_REQUIRED: ("CALLBACK_REQUIRED", "ASK_CALLBACK_DETAILS"),
            policy.Decision.NOT_AVAILABLE: ("NOT_AVAILABLE", "OFFER_OTHER_SESSION_OR_DATE"),
            policy.Decision.COULD_NOT_CHECK: ("COULD_NOT_CHECK", "SAY_COULD_NOT_CHECK"),
        }[d.decision]
        if request.purpose == policy.Purpose.WORKING_HOURS and d.decision == policy.Decision.APPOINTMENT_REQUEST:
            outcome, step = "WORKING_HOURS", "PRESENT_WORKING_HOURS"
        matched = any(s.label and policy.normalised(s.label) == policy.normalised(request.session)
                      and (s.basis == policy.Basis.LIVE_BOARD or requested is None or requested.weekday in s.days)
                      for s in d.sessions) if request.session else None
        return outcomes.AvailabilityResult(outcome=outcome, nextStep=step, **base, basis=d.basis,
            doctors=[doctor_out(d, requested)], detail=d.reason, sessionMatched=matched,
            callback=outcomes.Callback(reason=d.reason) if outcome == "CALLBACK_REQUIRED" else None,
            bookableFound=int(request.purpose == policy.Purpose.AVAILABILITY
                              and d.decision == policy.Decision.APPOINTMENT_REQUEST))
