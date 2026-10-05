"""Shared contracted directory/schedule retrieval; policy decides when enough facts were read."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from . import availability_policy as policy
from . import contract
from .cache import DirectoryCache
from .clock import Deadline
from .config import Settings
from .ops_client import InvalidIdentifier, Malformed, OpsClient, Rejected, Unavailable

READ_ERRORS = (Unavailable, Malformed, Rejected, InvalidIdentifier)


@dataclass(frozen=True)
class ReadFailure:
    doctor: contract.DoctorSummary


@dataclass(frozen=True)
class Unchecked:
    doctor: contract.DoctorSummary


@dataclass(frozen=True)
class DepartmentFacts:
    facts: tuple[policy.DoctorFacts, ...]
    results: tuple[policy.DoctorFacts | ReadFailure | Unchecked, ...]
    total: int
    search: policy.SearchState


class ScheduleReader:
    def __init__(self, ops: OpsClient, cache: DirectoryCache, settings: Settings) -> None:
        self.ops, self.cache, self.settings = ops, cache, settings

    async def departments(self, deadline: Deadline) -> list[contract.Department]:
        cached = self.cache.get(("departments",))
        if cached is None:
            cached = (await self.ops.list_departments(deadline)).items
            self.cache.set(("departments",), cached)
        return cached

    async def profile(self, doctor_id: str, deadline: Deadline) -> contract.DoctorDetail:
        cached = self.cache.get(("doctor", doctor_id))
        if cached is None:
            cached = await self.ops.get_doctor(doctor_id, deadline)
            self.cache.set(("doctor", doctor_id), cached)
        return cached

    async def search(self, deadline: Deadline, *, query: str | None = None,
                     department: str | None = None, gender: str | None = None) -> contract.DoctorPage:
        page = await self.ops.search_doctors(deadline, query=query, department=department, gender=gender, limit=100)
        return page.model_copy(update={"items": sorted(page.items, key=lambda d: (d.name.casefold(), d.id))})

    async def board(self, deadline: Deadline, *, doctor_id: str | None = None,
                    department: str | None = None) -> contract.AvailabilityBoard:
        try:
            return await self.ops.get_availability(deadline, date="today", doctor_id=doctor_id, department=department)
        except READ_ERRORS as exc:
            exc.stage = "board"
            raise

    async def doctor(self, doctor_id: str, requested: policy.RequestedDate | None, purpose: policy.Purpose,
                     deadline: Deadline, summary: contract.DoctorSummary | None = None) -> policy.DoctorFacts:
        today = purpose == policy.Purpose.AVAILABILITY and requested.kind == policy.DateKind.TODAY
        if today:
            if summary is None:
                results = await asyncio.gather(self.profile(doctor_id, deadline),
                                                self.board(deadline, doctor_id=doctor_id), return_exceptions=True)
                for result in results:
                    if isinstance(result, BaseException):
                        raise result
                profile, board = results
                return policy.DoctorFacts(profile, profile, tuple(e for e in board.items if e.doctorId == doctor_id))
            board = await self.board(deadline, doctor_id=doctor_id)
            return policy.DoctorFacts(summary, entries=tuple(e for e in board.items if e.doctorId == doctor_id))
        if summary is not None and summary.attendanceType == "ON_CALL":
            return policy.DoctorFacts(summary)
        profile = await self.profile(doctor_id, deadline)
        return policy.DoctorFacts(profile, profile)

    async def _candidate(self, doctor: contract.DoctorSummary,
                         deadline: Deadline) -> policy.DoctorFacts | ReadFailure:
        try:
            profile = await self.profile(doctor.id, deadline)
        except READ_ERRORS:
            return ReadFailure(doctor)
        return policy.DoctorFacts(doctor, profile)

    async def department(self, department_id: str, gender: str | None, requested: policy.RequestedDate | None,
                         purpose: policy.Purpose, deadline: Deadline,
                         evaluate: Callable[[policy.DoctorFacts], policy.DoctorDecision]) -> DepartmentFacts:
        if purpose == policy.Purpose.AVAILABILITY and requested.kind == policy.DateKind.TODAY:
            results = await asyncio.gather(self.search(deadline, department=department_id, gender=gender),
                                            self.board(deadline, department=department_id), return_exceptions=True)
            for result in results:
                if isinstance(result, BaseException):
                    raise result
            page, board = results
            facts = tuple(policy.DoctorFacts(d, entries=tuple(e for e in board.items if e.doctorId == d.id))
                          for d in page.items)
            found = sum(evaluate(f).decision == policy.Decision.APPOINTMENT_REQUEST for f in facts)
            search = policy.SearchState(found, len(facts), page.total <= len(facts))
            return DepartmentFacts(facts, facts, page.total, search)
        page = await self.search(deadline, department=department_id, gender=gender)
        reached: dict[str, policy.DoctorFacts | ReadFailure | Unchecked] = {
            d.id: policy.DoctorFacts(d) if d.attendanceType == "ON_CALL" else Unchecked(d) for d in page.items}
        pending = [d for d in page.items if d.attendanceType != "ON_CALL"]
        found = 0
        size = self.settings.profile_batch_size
        for offset in range(0, len(pending), size):
            if deadline.remaining() < self.settings.min_batch_headroom_seconds:
                break
            batch = pending[offset:offset + size]
            try:
                async with asyncio.timeout(max(0, deadline.remaining())):
                    fetched = await asyncio.gather(*(self._candidate(d, deadline) for d in batch))
            except TimeoutError:
                break  # gather cancellation is awaited; this whole batch remains unchecked
            for doctor, result in zip(batch, fetched, strict=True):
                reached[doctor.id] = result
                if isinstance(result, policy.DoctorFacts):
                    found += evaluate(result).decision == policy.Decision.APPOINTMENT_REQUEST
            if found >= self.settings.doctor_choice_limit:
                break
        all_results = tuple(reached[d.id] for d in page.items)
        facts = tuple(r for r in all_results if isinstance(r, policy.DoctorFacts))
        complete = len(facts) == len(page.items) and page.total <= len(page.items)
        return DepartmentFacts(facts, all_results, page.total, policy.SearchState(found, len(facts), complete))
