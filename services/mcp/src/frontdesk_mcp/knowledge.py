"""One LLM-chosen knowledge request; return owner wording and decisions without interpretation."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from . import outcomes
from .clock import Deadline
from .config import Settings
from .context import CallContext
from .knowledge_client import KnowledgeClient, KnowledgeUnavailable


class KnowledgeRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    question: str = Field(max_length=500)
    language: str = Field(max_length=16)


class KnowledgeService:
    def __init__(self, knowledge: KnowledgeClient, settings: Settings) -> None:
        self.knowledge = knowledge
        self.settings = settings

    async def search(self, ctx: CallContext, request: KnowledgeRequest) -> outcomes.KnowledgeResult:
        if not request.question.strip() or not request.language.strip():
            return outcomes.KnowledgeResult(outcome="INVALID_REQUEST", nextStep="ASK_TO_REPHRASE")
        try:
            response = await self.knowledge.answer(request.question, request.language, ctx,
                                                   Deadline(self.settings.read_deadline_seconds))
        except KnowledgeUnavailable as exc:
            return outcomes.KnowledgeResult(outcome="COULD_NOT_CHECK", nextStep="SAY_COULD_NOT_CHECK",
                                            detail=exc.reason)
        speech = (outcomes.Speech(text=response.answer.text, language=response.answer.language)
                  if response.answer else None)
        common = {"sourceId": response.sourceId, "destination": response.destination}
        if response.outcome == "ANSWERED":
            return outcomes.KnowledgeResult(outcome="ANSWERED", nextStep="SPEAK_ANSWER", answer=speech, **common)
        if response.outcome == "NO_ANSWER":
            return outcomes.KnowledgeResult(outcome="NO_ANSWER", nextStep="SAY_NO_ANSWER_AND_OFFER_DESK")
        if response.outcome == "CLARIFY":
            return outcomes.KnowledgeResult(outcome="CLARIFICATION_NEEDED", nextStep="ASK_CLARIFICATION",
                                            answer=speech, **common)
        step = {"EMERGENCY_TRANSFER": "TRANSFER_EMERGENCY", "DESK_TRANSFER": "TRANSFER_DESK",
                "ROUTE_DEPARTMENT": "CHECK_AVAILABILITY"}[response.outcome]
        return outcomes.KnowledgeResult(outcome="ROUTING_REQUIRED", nextStep=step, **common,
                                        routing=outcomes.Routing(decision=response.outcome, speak=speech,
                                            department=response.department.name if response.department else None))
