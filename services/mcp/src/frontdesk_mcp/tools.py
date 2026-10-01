"""The four tools. Each maps model-facing arguments to one service call; trusted context (call id,
caller number, turn, operation id, lifecycle timing) is read from the request headers only and is never
a parameter. Business rules live with the owners; the services here compose contracted facts."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, Literal

import httpx
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from fastmcp.tools.tool import ToolResult
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from . import availability, booking, context, contract, knowledge, outcomes, prompt, summary
from .access import LIFECYCLE_TAG
from .cache import DirectoryCache
from .clock import Clock, SystemClock
from .config import Settings
from .knowledge_client import KnowledgeClient
from .ops_client import OpsClient
from .packs import Pack

logger = logging.getLogger(__name__)

TOOL_NAMES = ("get_doctor_availability", "manage_booking", "search_knowledge", "record_call_summary")
CONVERSATIONAL_TOOLS = TOOL_NAMES[:3]
LIFECYCLE_TOOLS = TOOL_NAMES[3:]


@dataclass
class Services:
    settings: Settings
    clock: Clock
    ops: OpsClient
    knowledge: KnowledgeClient
    cache: DirectoryCache
    availability: availability.AvailabilityService
    booking: booking.BookingService
    search: knowledge.KnowledgeService
    summary: summary.SummaryService

    @classmethod
    def build(cls, settings: Settings, *, ops_transport: httpx.AsyncBaseTransport | None = None,
              knowledge_transport: httpx.AsyncBaseTransport | None = None, clock: Clock | None = None,
              monotonic: Callable[[], float] = time.monotonic) -> Services:
        clock = clock or SystemClock()
        ops = OpsClient(settings, transport=ops_transport, monotonic=monotonic)
        kb = KnowledgeClient(settings, transport=knowledge_transport)
        cache = DirectoryCache(settings, monotonic)
        return cls(settings, clock, ops, kb, cache,
                   availability.AvailabilityService(ops, kb, cache, settings, clock),
                   booking.BookingService(ops, kb, settings, clock, cache),
                   knowledge.KnowledgeService(kb, settings),
                   summary.SummaryService(ops, settings))

    async def aclose(self) -> None:
        await self.ops.aclose()
        await self.knowledge.aclose()


def _apply_pack_text(tool: Any, text: Any) -> None:
    """Domain wording for the parameters the model reads; the schema itself never changes."""
    properties = tool.parameters["properties"]
    unknown = set(text.parameters) - set(properties)
    if unknown:
        raise ValueError(f"pack describes unknown parameters of {tool.name}: {sorted(unknown)}")
    for name, description in text.parameters.items():
        properties[name]["description"] = description


Name = Annotated[str | None, Field(max_length=100)]
Ident = Annotated[str | None, Field(max_length=64)]
IsoDate = Annotated[str | None, Field(max_length=10, pattern=r"^\d{4}-\d{2}-\d{2}$")]
ApproxTime = Annotated[str | None, Field(max_length=5, pattern=r"^\d{2}:\d{2}$")]


def register(mcp: FastMCP, services: Services, pack: Pack) -> None:
    settings = services.settings
    missing = set(TOOL_NAMES) - set(pack.tools)
    if missing:
        raise ValueError(f"pack {pack.name!r} does not describe {sorted(missing)}")

    def ctx() -> context.CallContext:
        return context.from_headers(get_http_headers(), settings)

    def observed(name: str, result: BaseModel) -> ToolResult:
        """One line per tool call: tool, outcome, next step. Never arguments, names or numbers.

        The result is pydantic-validated already; returning a ToolResult with `meta` makes FastMCP hand the SDK a
        CallToolResult, which the SDK does not re-validate against the (large) output schema on every call."""
        logger.info("tool_result", extra={"fields": {"tool": name, "outcome": result.outcome,
                                                     "nextStep": getattr(result, "nextStep", None)}})
        return ToolResult(structured_content=result.model_dump(mode="json"),
                          meta={"schemaVersion": prompt.SCHEMA_VERSION})

    @mcp.tool(
        name="get_doctor_availability",
        description=pack.tools["get_doctor_availability"].description,
        output_schema=outcomes.AvailabilityResult.model_json_schema(),
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    )
    async def get_doctor_availability(  # noqa: N803 - parameter names are the wire names the model sees
        date: Annotated[str, Field(max_length=10, description="'today' or YYYY-MM-DD.")],
        doctorName: Name = None,
        doctorId: Ident = None,
        departmentName: Name = None,
        departmentId: Ident = None,
        session: Annotated[str | None, Field(max_length=40)] = None,
        gender: Literal["FEMALE", "MALE"] | None = None,
    ) -> ToolResult:
        request = availability.AvailabilityRequest(date=date, doctorName=doctorName, doctorId=doctorId,
                                                   departmentName=departmentName, departmentId=departmentId,
                                                   session=session, gender=gender)
        return observed("get_doctor_availability", await services.availability.get(ctx(), request))

    _apply_pack_text(get_doctor_availability, pack.tools["get_doctor_availability"])

    @mcp.tool(
        name="manage_booking",
        description=pack.tools["manage_booking"].description,
        output_schema=outcomes.BookingResult.model_json_schema(),
        # Mixed actions: LIST reads, CANCEL destroys, CREATE/RESCHEDULE write. Replays are keyed, so idempotent.
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True,
                                    openWorldHint=False),
    )
    async def manage_booking(  # noqa: N803
        action: booking.Action,
        patientName: Name = None,
        patientMobile: Annotated[str | None, Field(max_length=20)] = None,
        doctorId: Ident = None,
        departmentId: Ident = None,
        visitDate: IsoDate = None,
        preferredTime: ApproxTime = None,
        session: Annotated[str | None, Field(max_length=40)] = None,
        reasonVerbatim: Annotated[str | None, Field(max_length=500)] = None,
        appointmentId: Ident = None,
        newVisitDate: IsoDate = None,
        newPreferredTime: ApproxTime = None,
        fromDate: IsoDate = None,
        toDate: IsoDate = None,
        status: contract.AppointmentStatus | None = None,
        callerConfirmed: bool = False,
    ) -> ToolResult:
        request = booking.BookingRequest(
            action=action, patientName=patientName, patientMobile=patientMobile, doctorId=doctorId,
            departmentId=departmentId, visitDate=visitDate, preferredTime=preferredTime, session=session,
            reasonVerbatim=reasonVerbatim,
            appointmentId=appointmentId, newVisitDate=newVisitDate, newPreferredTime=newPreferredTime,
            fromDate=fromDate, toDate=toDate, status=status, callerConfirmed=callerConfirmed)
        return observed("manage_booking", await services.booking.manage(ctx(), request))

    _apply_pack_text(manage_booking, pack.tools["manage_booking"])

    @mcp.tool(
        name="search_knowledge",
        description=pack.tools["search_knowledge"].description,
        output_schema=outcomes.KnowledgeResult.model_json_schema(),
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    )
    async def search_knowledge(
        question: Annotated[str, Field(max_length=500)],
        language: Annotated[str, Field(max_length=16)],
    ) -> ToolResult:
        request = knowledge.KnowledgeRequest(question=question, language=language)
        return observed("search_knowledge", await services.search.search(ctx(), request))

    _apply_pack_text(search_knowledge, pack.tools["search_knowledge"])

    @mcp.tool(
        name="record_call_summary",
        description=pack.tools["record_call_summary"].description,
        tags={LIFECYCLE_TAG},
        output_schema=outcomes.SummaryResult.model_json_schema(),
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True,
                                    openWorldHint=False),
    )
    async def record_call_summary(  # noqa: N803
        intent: contract.CallIntent,
        outcome: contract.CallOutcome,
        summaryText: Annotated[str, Field(max_length=2000)],
        callerName: Name = None,
        callerMobile: Annotated[str | None, Field(max_length=20)] = None,
        language: Annotated[str | None, Field(max_length=16)] = None,
        doctorId: Ident = None,
        appointmentId: Ident = None,
        transferredTo: Annotated[str | None, Field(max_length=64)] = None,
        requestedDate: IsoDate = None,
    ) -> ToolResult:
        request = summary.SummaryRequest(intent=intent, outcome=outcome, summaryText=summaryText, callerName=callerName,
                                         callerMobile=callerMobile, language=language, doctorId=doctorId,
                                         appointmentId=appointmentId, transferredTo=transferredTo,
                                         requestedDate=requestedDate)
        return observed("record_call_summary", await services.summary.record(ctx(), request))

    _apply_pack_text(record_call_summary, pack.tools["record_call_summary"])
