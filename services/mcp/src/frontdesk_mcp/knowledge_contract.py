"""PROVISIONAL consumer contract for Shobhit's knowledge service.

Shobhit has not published an endpoint, schema or auth contract (docs/handover/mcp-only/OPEN-DEPENDENCIES).
This module names the outcomes our integration needs from his service so the boundary is implemented
cleanly now; the paths, field names and auth below are placeholders agreed with nobody. Replace them
with the published contract and keep the outcome vocabulary stable for the tools. Nothing here
interprets symptoms: MCP forwards the caller's words and consumes his decision.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ROUTE_PATH = "/v1/route"  # PROVISIONAL
ANSWER_PATH = "/v1/answer"  # PROVISIONAL

# What routing must tell us before an availability answer or an appointment create may proceed.
RoutingDecision = Literal["CONTINUE", "ROUTE_DEPARTMENT", "CLARIFY", "DESK_TRANSFER", "EMERGENCY_TRANSFER"]
# Decisions that permit the routine scheduling journey to continue.
CLEARANCE: frozenset[str] = frozenset({"CONTINUE", "ROUTE_DEPARTMENT"})

AnswerOutcome = Literal["ANSWERED", "NO_ANSWER", "CLARIFICATION_NEEDED", "TRANSFER_DESK"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)


class Speech(_Model):
    """Approved text the agent may speak verbatim, with its language."""

    text: str = Field(max_length=1000)
    language: str


class DepartmentHint(_Model):
    """Shobhit's department reference; MCP maps it to Manoj's directory by name, clarifying if unsure."""

    name: str


class RouteRequest(_Model):
    utterance: str
    language: str
    callId: str | None = None  # noqa: N815 - wire names
    turnId: str | None = None  # noqa: N815


class RouteResponse(_Model):
    decision: RoutingDecision
    department: DepartmentHint | None = None
    speak: Speech | None = None
    provenance: str | None = None


class AnswerRequest(_Model):
    question: str
    language: str
    callId: str | None = None  # noqa: N815


class AnswerResponse(_Model):
    outcome: AnswerOutcome
    answer: Speech | None = None
    sourceId: str | None = None  # noqa: N815
    destination: str | None = None
