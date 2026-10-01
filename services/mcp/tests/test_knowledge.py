"""search_knowledge: approved hospital answers, clarification, desk routing and no-answer outcomes come
from Shobhit's service and are returned verbatim; a failure is a failure, never an answer."""

from __future__ import annotations

import pytest

from frontdesk_mcp import knowledge

from . import harness


@pytest.fixture
async def h(make_settings):
    built = harness.build(make_settings())
    yield built
    await built.aclose()


async def ask(h, question: str, language: str = "en", ctx=None):
    service = knowledge.KnowledgeService(h.knowledge, h.settings)
    return await service.search(ctx or h.ctx(), knowledge.KnowledgeRequest(question=question, language=language))


async def test_approved_answer_is_returned_verbatim_in_the_callers_language(h):
    result = await ask(h, "ಪಾರ್ಕಿಂಗ್ ಇದೆಯಾ", "kn")
    assert result.outcome == "ANSWERED" and result.nextStep == "SPEAK_ANSWER"
    assert result.answer.language == "kn" and result.answer.text.startswith("ಹೌದು. ನೆಲಮಾಳಿಗೆಯಲ್ಲಿ")
    assert result.sourceId == "kb_parking"


async def test_the_question_and_call_id_reach_the_service_unchanged(h):
    await ask(h, "  Is There Parking?  ", "en")
    request = [r for r in h.requests if r.url.host == "knowledge-stub.test"][-1]
    import json
    body = json.loads(request.content)
    assert body == {"question": "  Is There Parking?  ", "language": "en", "callId": "call-1"}


async def test_desk_transfer_answers_carry_the_destination(h):
    result = await ask(h, "cashless")
    assert result.outcome == "ROUTING_REQUIRED" and result.nextStep == "TRANSFER_DESK"
    assert result.destination == "insurance" and "insurance desk" in result.answer.text


async def test_clarification_and_no_answer_are_distinct_from_each_other_and_from_failure(h):
    clarify = await ask(h, "fees kitna hai", "hi")
    assert clarify.outcome == "CLARIFICATION_NEEDED" and clarify.nextStep == "ASK_CLARIFICATION"
    assert clarify.answer.language == "hi"
    none = await ask(h, "what is the meaning of life")
    assert none.outcome == "NO_ANSWER" and none.nextStep == "SAY_NO_ANSWER_AND_OFFER_DESK" and none.answer is None


@pytest.mark.parametrize("break_it,detail", [("outage", "UNAVAILABLE"), ("malformed", "MALFORMED"),
                                             ("unconfigured", "NOT_CONFIGURED"), ("slow", "UNAVAILABLE")])
async def test_service_problems_are_could_not_check_never_an_answer(make_settings, break_it, detail):
    settings = make_settings()
    if break_it == "unconfigured":
        settings = make_settings(env="development", knowledge_base_url="")
    if break_it == "slow":
        settings = make_settings(read_deadline_seconds=0.3, write_deadline_seconds=0.3, summary_deadline_seconds=0.3,
                                 request_timeout_seconds=0.2)
    hh = harness.build(settings)
    try:
        if break_it == "outage":
            hh.knowledge_state.fail_next.append(503)
        if break_it == "malformed":
            hh.knowledge_state.malformed_next.append(True)
        if break_it == "slow":
            hh.knowledge_state.delay_seconds = 5
        result = await ask(hh, "parking")
        assert result.outcome == "COULD_NOT_CHECK" and result.nextStep == "SAY_COULD_NOT_CHECK"
        assert result.detail == detail and result.answer is None
    finally:
        await hh.aclose()


async def test_an_empty_question_is_invalid_without_a_call(h):
    result = await ask(h, "   ")
    assert result.outcome == "INVALID_REQUEST"
    assert not [r for r in h.requests if r.url.host == "knowledge-stub.test"]
