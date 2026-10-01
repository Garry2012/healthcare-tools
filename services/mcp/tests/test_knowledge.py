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
    import json

    from frontdesk_mcp import knowledge_contract as kc

    answers = [r for r in h.requests if r.url.host == "knowledge-stub.test" and r.url.path == kc.ANSWER_PATH]
    body = json.loads(answers[-1].content)
    assert body == {"question": "  Is There Parking?  ", "language": "en", "callId": "call-1",
                    "turn": {"utterance": "is Dr Garima in today", "language": "en"}}


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


@pytest.mark.parametrize("break_it,detail", [("outage", "UNAVAILABLE"), ("malformed", "MALFORMED")])
async def test_answer_service_problems_are_could_not_check_never_an_answer(h, break_it, detail):
    """Routing cleared; the answer call failed: a failure, with the routing decision still reported."""
    from frontdesk_mcp import knowledge_contract as kc

    if break_it == "outage":
        h.knowledge_state.fail_next_for.append((kc.ANSWER_PATH, 503))
    else:
        h.knowledge_state.malformed_next_for.append(kc.ANSWER_PATH)
    result = await ask(h, "parking")
    assert result.outcome == "COULD_NOT_CHECK" and result.nextStep == "SAY_COULD_NOT_CHECK"
    assert result.detail == detail and result.answer is None and result.routing.decision == "CONTINUE"


@pytest.mark.parametrize("break_it,detail", [("unconfigured", "ROUTING_NOT_CONFIGURED"),
                                             ("slow", "ROUTING_UNAVAILABLE")])
async def test_knowledge_service_unreachable_means_no_routing_and_no_answer(make_settings, break_it, detail):
    settings = make_settings()
    if break_it == "unconfigured":
        settings = make_settings(env="development", knowledge_base_url="")
    if break_it == "slow":
        settings = make_settings(read_deadline_seconds=0.3, write_deadline_seconds=0.3, summary_deadline_seconds=0.3,
                                 request_timeout_seconds=0.2)
    hh = harness.build(settings)
    try:
        if break_it == "slow":
            hh.knowledge_state.delay_seconds = 5
        result = await ask(hh, "parking")
        assert result.outcome == "ROUTING_UNAVAILABLE" and result.nextStep == "TRANSFER_DESK"
        assert result.detail == detail and result.answer is None
    finally:
        await hh.aclose()


async def test_an_empty_question_is_invalid_without_a_call(h):
    result = await ask(h, "   ")
    assert result.outcome == "INVALID_REQUEST"
    assert not [r for r in h.requests if r.url.host == "knowledge-stub.test"]


async def test_the_trusted_turn_travels_with_the_question(h):
    """Review fix: the model's question may omit the danger sign the caller actually said."""
    import json

    from frontdesk_mcp import knowledge_contract as kc

    await ask(h, "where is cardiology", "en", h.ctx(turn="my father has chest pain, where is cardiology?"))
    answers = [r for r in h.requests if r.url.host == "knowledge-stub.test" and r.url.path == kc.ANSWER_PATH]
    body = json.loads(answers[-1].content)
    assert body["turn"] == {"utterance": "my father has chest pain, where is cardiology?", "language": "en"}


# ------------------------------------------------------------------ architect review AR-02


async def test_a_danger_sign_in_the_trusted_turn_routes_before_any_answer(h):
    """AR-02: the owner's routing decision over the caller's words comes first; a general question does not
    bypass it."""
    from frontdesk_stubs.knowledge import Decision

    text = "my father has chest pain, where is cardiology?"
    h.knowledge_state.decisions.insert(0, Decision((text,), "EMERGENCY_TRANSFER",
                                                  speak={"text": "Connecting you to emergency.", "language": "en"}))
    result = await ask(h, "where is cardiology", "en", h.ctx(turn=text))
    assert result.outcome == "ROUTING_REQUIRED" and result.nextStep == "TRANSFER_EMERGENCY"
    assert result.routing.decision == "EMERGENCY_TRANSFER" and result.routing.speak.text.startswith("Connecting")
    assert result.answer is None
    assert len(h.knowledge_state.routed) == 1 and h.knowledge_state.routed[0]["utterance"] == text


async def test_department_routing_is_returned_with_the_answer(h):
    result = await ask(h, "parking", "en", h.ctx(turn="I need a children's doctor"))
    assert result.outcome == "ANSWERED" and result.routing.decision == "ROUTE_DEPARTMENT"
    assert result.routing.department == "Paediatrics"


async def test_clarification_from_routing_takes_precedence(h):
    result = await ask(h, "parking", "en", h.ctx(turn="my child has stomach pain"))
    assert result.outcome == "ROUTING_REQUIRED" and result.nextStep == "ASK_ROUTING_CLARIFICATION"
    assert result.routing.speak.text.startswith("Is this for a child")


async def test_plain_faq_is_answered_once_routing_clears(h):
    result = await ask(h, "parking", "en", h.ctx(turn="is there parking"))
    assert result.outcome == "ANSWERED" and result.routing.decision == "CONTINUE"


@pytest.mark.parametrize("break_it,detail", [("missing_turn", "TURN_CONTEXT_MISSING"),
                                             ("outage", "ROUTING_UNAVAILABLE")])
async def test_knowledge_without_a_routing_decision_is_not_an_answer(h, break_it, detail):
    ctx = h.ctx(turn=None) if break_it == "missing_turn" else h.ctx()
    if break_it == "outage":
        from frontdesk_mcp import knowledge_contract as kc

        h.knowledge_state.fail_next_for.append((kc.ROUTE_PATH, 503))
    result = await ask(h, "parking", "en", ctx)
    assert result.outcome == "ROUTING_UNAVAILABLE" and result.nextStep == "TRANSFER_DESK" and result.detail == detail
    assert result.answer is None
