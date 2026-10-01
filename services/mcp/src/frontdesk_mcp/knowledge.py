"""search_knowledge: approved hospital answers, clarification, desk routing and no-answer outcomes from
Shobhit's service, returned verbatim. MCP adds no wording, translation or interpretation."""

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
        deadline = Deadline(self.settings.read_deadline_seconds)
        try:
            response = await self.knowledge.answer(request.question, request.language, ctx, deadline)
        except KnowledgeUnavailable as exc:
            return outcomes.KnowledgeResult(outcome="COULD_NOT_CHECK", nextStep="SAY_COULD_NOT_CHECK",
                                            detail=exc.reason)
        speech = None
        if response.answer:
            speech = outcomes.Speech(text=response.answer.text, language=response.answer.language)
        if response.outcome == "ANSWERED":
            if speech is None:
                return outcomes.KnowledgeResult(outcome="COULD_NOT_CHECK", nextStep="SAY_COULD_NOT_CHECK",
                                                detail="MALFORMED")
            return outcomes.KnowledgeResult(outcome="ANSWERED", nextStep="SPEAK_ANSWER", answer=speech,
                                            sourceId=response.sourceId)
        if response.outcome == "CLARIFICATION_NEEDED":
            return outcomes.KnowledgeResult(outcome="CLARIFICATION_NEEDED", nextStep="ASK_CLARIFICATION", answer=speech,
                                            sourceId=response.sourceId)
        if response.outcome == "TRANSFER_DESK":
            return outcomes.KnowledgeResult(outcome="ROUTING_REQUIRED", nextStep="TRANSFER_DESK", answer=speech,
                                            sourceId=response.sourceId, destination=response.destination)
        return outcomes.KnowledgeResult(outcome="NO_ANSWER", nextStep="SAY_NO_ANSWER_AND_OFFER_DESK")
