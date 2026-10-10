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
READ_FAILURE_STAGES = frozenset({"slots", "capabilities"})
READ_FAILURE_DETAILS = {"board": "BOARD_UNAVAILABLE", "profile": "PROFILE_UNAVAILABLE",
                        "slots": "SLOTS_UNAVAILABLE", "capabilities": "CAPABILITIES_UNAVAILABLE"}


def read_failure_detail(stage: str | None, fallback: str) -> str:
    """Map the failed read; callers retain their existing AUTH precedence and fallback."""
    return READ_FAILURE_DETAILS.get(stage, fallback)


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

    async def capabilities(self, deadline: Deadline) -> contract.Capabilities:
        cached = self.cache.get(("capabilities",))
        if cached is None:
            try:
                cached = await self.ops.get_capabilities(deadline)
            except READ_ERRORS as exc:
                exc.stage = "capabilities"
                raise
            self.cache.set(("capabilities",), cached)
        return cached

    async def profile(self, doctor_id: str, deadline: Deadline) -> contract.DoctorDetail:
        cached = self.cache.get(("doctor", doctor_id))
        if cached is None:
            try:
                cached = await self.ops.get_doctor(doctor_id, deadline)
            except READ_ERRORS as exc:
                exc.stage = "profile"
                raise
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

    async def slots(self, doctor_id: str, requested: policy.RequestedDate,
                    deadline: Deadline) -> contract.SlotPlan | None:
        try:
            plan = await self.ops.get_slots(deadline, doctor_id=doctor_id, date=requested.value.isoformat())
            if plan.doctorId != doctor_id or plan.date != requested.value:
                raise Malformed("slot plan does not match the requested doctor and date")
            labels = [policy.normalised(session.session or "") for session in plan.sessions]
            if len(labels) != len(set(labels)):
                raise Malformed("slot session labels are not unique")
            blocks = sorted((block for session in plan.sessions for block in session.slots), key=lambda b: b.start)
            if not contract.ordered_slot_blocks(blocks):
                raise Malformed("slot sessions overlap")
            return plan if plan.enabled else None
        except READ_ERRORS as exc:
            exc.stage = "slots"
            raise

    async def doctor(self, doctor_id: str, requested: policy.RequestedDate | None, purpose: policy.Purpose,
                     deadline: Deadline, summary: contract.DoctorSummary | None = None) -> policy.DoctorFacts:
        if purpose == policy.Purpose.WORKING_HOURS:
            if summary is not None and summary.attendanceType == "ON_CALL":
                return policy.DoctorFacts(summary)
            profile = await self.profile(doctor_id, deadline)
            return policy.DoctorFacts(profile, profile)
        today = requested.kind == policy.DateKind.TODAY
        reads = {}
        if summary is None or not today:
            reads["profile"] = self.profile(doctor_id, deadline)
        if today:
            reads["board"] = self.board(deadline, doctor_id=doctor_id)
        reads["slots"] = self.slots(doctor_id, requested, deadline)
        results = await asyncio.gather(*reads.values(), return_exceptions=True)
        for result in results:  # preserve profile, then board, then slots failure precedence
            if isinstance(result, BaseException):
                raise result
        fetched = dict(zip(reads, results, strict=True))
        profile, board = fetched.get("profile"), fetched.get("board")
        entries = tuple(e for e in board.items if e.doctorId == doctor_id) if board else ()
        return policy.DoctorFacts(profile or summary, profile, entries, slots=fetched["slots"])

    async def _candidate(self, doctor: contract.DoctorSummary, deadline: Deadline,
                         slots: policy.SlotsNotRead | None) -> policy.DoctorFacts | ReadFailure:
        try:
            profile = await self.profile(doctor.id, deadline)
        except READ_ERRORS:
            return ReadFailure(doctor)
        return policy.DoctorFacts(doctor, profile, slots=slots)

    async def department(self, department_id: str, gender: str | None, requested: policy.RequestedDate | None,
                         purpose: policy.Purpose, deadline: Deadline,
                         evaluate: Callable[[policy.DoctorFacts], policy.DoctorDecision]) -> DepartmentFacts:
        reads = {"search": self.search(deadline, department=department_id, gender=gender)}
        if purpose == policy.Purpose.AVAILABILITY:
            if requested.kind == policy.DateKind.TODAY:
                reads["board"] = self.board(deadline, department=department_id)
            reads["capabilities"] = self.capabilities(deadline)
        results = await asyncio.gather(*reads.values(), return_exceptions=True)
        for result in results:  # preserve search, then board, then capabilities failure precedence
            if isinstance(result, BaseException):
                raise result
        initial = dict(zip(reads, results, strict=True))
        page, board, capabilities = initial["search"], initial.get("board"), initial.get("capabilities")
        slots = policy.SlotsNotRead() if capabilities is not None and capabilities.slots.enabled else None
        if board is not None:
            facts = tuple(policy.DoctorFacts(d, entries=tuple(e for e in board.items if e.doctorId == d.id),
                                            slots=slots) for d in page.items)
            found = sum(policy.is_match(evaluate(f).decision) for f in facts)
            search = policy.SearchState(found, len(facts), page.total <= len(facts))
            return DepartmentFacts(facts, facts, page.total, search)
        reached: dict[str, policy.DoctorFacts | ReadFailure | Unchecked] = {
            d.id: policy.DoctorFacts(d, slots=slots) if d.attendanceType == "ON_CALL" else Unchecked(d)
            for d in page.items}
        pending = [d for d in page.items if d.attendanceType != "ON_CALL"]
        found = 0
        size = self.settings.profile_batch_size
        for offset in range(0, len(pending), size):
            if deadline.remaining() < self.settings.min_batch_headroom_seconds:
                break
            batch = pending[offset:offset + size]
            try:
                async with asyncio.timeout(max(0, deadline.remaining())):
                    fetched = await asyncio.gather(*(self._candidate(d, deadline, slots) for d in batch))
            except TimeoutError:
                break  # gather cancellation is awaited; this whole batch remains unchecked
            for doctor, result in zip(batch, fetched, strict=True):
                reached[doctor.id] = result
                if isinstance(result, policy.DoctorFacts):
                    found += policy.is_match(evaluate(result).decision)
            if found >= self.settings.doctor_choice_limit:
                break
        all_results = tuple(reached[d.id] for d in page.items)
        facts = tuple(r for r in all_results if isinstance(r, policy.DoctorFacts))
        complete = len(facts) == len(page.items) and page.total <= len(page.items)
        return DepartmentFacts(facts, all_results, page.total, policy.SearchState(found, len(facts), complete))
