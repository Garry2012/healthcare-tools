"""search_knowledge: the owner's routing decision over the caller's trusted words comes first (a danger
sign in the turn is never bypassed by a general question); when it clears, the approved answer,
clarification, desk routing or no-answer outcome is returned verbatim. MCP adds no wording, translation
or interpretation. Both owner calls run concurrently; the answer is discarded when routing escalates."""

from __future__ import annotations

import asyncio

from pydantic import BaseModel, ConfigDict, Field

from . import knowledge_contract as kc
from . import outcomes
from .clock import Deadline
from .config import Settings
from .context import CallContext
from .knowledge_client import KnowledgeClient, KnowledgeUnavailable


class KnowledgeRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    question: str = Field(max_length=500)
    language: str = Field(max_length=16)


def _routing_out(decision: kc.RouteResponse) -> outcomes.Routing:
    speak = outcomes.Speech(text=decision.speak.text, language=decision.speak.language) if decision.speak else None
    return outcomes.Routing(decision=decision.decision, speak=speak,
                            department=decision.department.name if decision.department else None)


class KnowledgeService:
    def __init__(self, knowledge: KnowledgeClient, settings: Settings) -> None:
        self.knowledge = knowledge
        self.settings = settings

    async def search(self, ctx: CallContext, request: KnowledgeRequest) -> outcomes.KnowledgeResult:
        if not request.question.strip() or not request.language.strip():
            return outcomes.KnowledgeResult(outcome="INVALID_REQUEST", nextStep="ASK_TO_REPHRASE")
        deadline = Deadline(self.settings.read_deadline_seconds)
        if ctx.turn is None:
            return outcomes.KnowledgeResult(outcome="ROUTING_UNAVAILABLE", nextStep="TRANSFER_DESK",
                                            detail=ctx.turn_failure or "TURN_CONTEXT_MISSING")
        routing_task = asyncio.create_task(self.knowledge.route(ctx.turn, ctx, deadline, [request.question]))
        answer_task = asyncio.create_task(self.knowledge.answer(request.question, request.language, ctx, deadline))
        try:
            decision = await routing_task
        except KnowledgeUnavailable as exc:
            answer_task.cancel()
            await asyncio.gather(answer_task, return_exceptions=True)
            detail = {"NOT_CONFIGURED": "ROUTING_NOT_CONFIGURED", "MALFORMED": "ROUTING_MALFORMED",
                      "UNAVAILABLE": "ROUTING_UNAVAILABLE"}[exc.reason]
            return outcomes.KnowledgeResult(outcome="ROUTING_UNAVAILABLE", nextStep="TRANSFER_DESK", detail=detail)
        routing = _routing_out(decision)
        if decision.decision not in kc.CLEARANCE:
            answer_task.cancel()
            await asyncio.gather(answer_task, return_exceptions=True)
            step = {"EMERGENCY_TRANSFER": "TRANSFER_EMERGENCY", "DESK_TRANSFER": "TRANSFER_DESK",
                    "CLARIFY": "ASK_ROUTING_CLARIFICATION"}[decision.decision]
            return outcomes.KnowledgeResult(outcome="ROUTING_REQUIRED", nextStep=step, routing=routing)
        try:
            response = await answer_task
        except KnowledgeUnavailable as exc:
            return outcomes.KnowledgeResult(outcome="COULD_NOT_CHECK", nextStep="SAY_COULD_NOT_CHECK",
                                            detail=exc.reason, routing=routing)
        speech = None
        if response.answer:
            speech = outcomes.Speech(text=response.answer.text, language=response.answer.language)
        if response.outcome == "ANSWERED":
            if speech is None:
                return outcomes.KnowledgeResult(outcome="COULD_NOT_CHECK", nextStep="SAY_COULD_NOT_CHECK",
                                                detail="MALFORMED", routing=routing)
            return outcomes.KnowledgeResult(outcome="ANSWERED", nextStep="SPEAK_ANSWER", answer=speech,
                                            sourceId=response.sourceId, routing=routing)
        if response.outcome == "CLARIFICATION_NEEDED":
            return outcomes.KnowledgeResult(outcome="CLARIFICATION_NEEDED", nextStep="ASK_CLARIFICATION", answer=speech,
                                            sourceId=response.sourceId, routing=routing)
        if response.outcome == "TRANSFER_DESK":
            return outcomes.KnowledgeResult(outcome="ROUTING_REQUIRED", nextStep="TRANSFER_DESK", answer=speech,
                                            sourceId=response.sourceId, destination=response.destination,
                                            routing=routing)
        return outcomes.KnowledgeResult(outcome="NO_ANSWER", nextStep="SAY_NO_ANSWER_AND_OFFER_DESK", routing=routing)
