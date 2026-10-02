"""Single knowledge exchange: owner wording and decisions, never an implicit scheduling gate."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from frontdesk_mcp.context import CallContext
from frontdesk_mcp.knowledge import KnowledgeRequest
from frontdesk_mcp.tools import Services


@pytest.mark.parametrize("payload,outcome,step", [
    ({"outcome": "ANSWERED", "answer": {"text": "ಪಾರ್ಕಿಂಗ್ ಇದೆ", "language": "kn"}, "sourceId": "parking"},
     "ANSWERED", "SPEAK_ANSWER"),
    ({"outcome": "NO_ANSWER"}, "NO_ANSWER", "SAY_NO_ANSWER_AND_OFFER_DESK"),
    ({"outcome": "CLARIFY", "answer": {"text": "Which service?", "language": "en"}},
     "CLARIFICATION_NEEDED", "ASK_CLARIFICATION"),
    ({"outcome": "DESK_TRANSFER", "destination": "desk"}, "ROUTING_REQUIRED", "TRANSFER_DESK"),
    ({"outcome": "EMERGENCY_TRANSFER", "answer": {"text": "Owner emergency instruction", "language": "en"}},
     "ROUTING_REQUIRED", "TRANSFER_EMERGENCY"),
    ({"outcome": "ROUTE_DEPARTMENT", "department": {"name": "Paediatrics"}},
     "ROUTING_REQUIRED", "CHECK_AVAILABILITY"),
])
async def test_one_exchange_maps_owner_outcome_without_transcript(make_settings, payload, outcome, step, caplog):
    requests = []

    async def owner(request):
        requests.append(request)
        return httpx.Response(200, json=payload)

    services = Services.build(make_settings(), knowledge_transport=httpx.MockTransport(owner))
    try:
        question = "  ಪಾರ್ಕಿಂಗ್ ಇದೆಯಾ  "
        result = await services.search.search(CallContext(call_id="call-1"),
                                             KnowledgeRequest(question=question, language="kn"))
        assert (result.outcome, result.nextStep) == (outcome, step)
        [request] = requests
        assert request.url.path == "/v1/answer" and request.method == "POST"
        assert request.headers["authorization"] == "Bearer knowledge-secret"
        assert json.loads(request.content) == {"question": question, "language": "kn", "callId": "call-1"}
        if "answer" in payload and payload["outcome"] in ("ANSWERED", "CLARIFY"):
            assert result.answer.model_dump() == payload["answer"]
        if payload["outcome"] in ("EMERGENCY_TRANSFER", "DESK_TRANSFER", "ROUTE_DEPARTMENT"):
            assert result.answer is None
            assert result.routing.decision == payload["outcome"]
            assert (result.routing.speak.model_dump() if result.routing.speak else None) == payload.get("answer")
        if "department" in payload:
            assert result.routing.department == "Paediatrics"
        assert result.destination == payload.get("destination")
        assert result.sourceId == payload.get("sourceId")
        assert question not in caplog.text
    finally:
        await services.aclose()


@pytest.mark.parametrize("failure,detail", [
    ("timeout", "UNAVAILABLE"), ("network", "UNAVAILABLE"), (401, "UNAVAILABLE"), (403, "UNAVAILABLE"),
    (503, "UNAVAILABLE"), ("json", "MALFORMED"), ([], "MALFORMED"), ({}, "MALFORMED"),
    ({"outcome": "invented"}, "MALFORMED"), ({"outcome": "ANSWERED"}, "MALFORMED"),
    ({"outcome": "CLARIFY"}, "MALFORMED"), ({"outcome": "ROUTE_DEPARTMENT"}, "MALFORMED"),
    ({"outcome": "ROUTE_DEPARTMENT", "department": {"name": " "}}, "MALFORMED"),
    ({"outcome": "ANSWERED", "answer": {"text": " ", "language": "en"}}, "MALFORMED"),
])
async def test_owner_failure_is_not_an_answer(make_settings, failure, detail, caplog):
    requests = []
    cancelled = asyncio.Event()

    async def owner(request):
        requests.append(request)
        if failure == "timeout":
            try:
                await asyncio.sleep(1)
            finally:
                cancelled.set()
        if failure == "network":
            raise httpx.ConnectError("private upstream error", request=request)
        if isinstance(failure, int):
            return httpx.Response(failure, text="private upstream error")
        if failure == "json":
            return httpx.Response(200, text="not json")
        return httpx.Response(200, json=failure)

    services = Services.build(make_settings(read_deadline_seconds=0.05),
                              knowledge_transport=httpx.MockTransport(owner))
    try:
        started = asyncio.get_running_loop().time()
        result = await services.search.search(
            CallContext(), KnowledgeRequest(question="private caller question", language="en"))
        assert (result.outcome, result.nextStep, result.detail) == ("COULD_NOT_CHECK", "SAY_COULD_NOT_CHECK", detail)
        assert result.answer is None and result.routing is None and len(requests) == 1
        assert "private upstream error" not in result.model_dump_json()
        assert "private caller question" not in caplog.text and "private upstream error" not in caplog.text
        if failure == "timeout":
            assert cancelled.is_set() and asyncio.get_running_loop().time() - started < 0.3
    finally:
        await services.aclose()


@pytest.mark.parametrize("question,language", [("", "en"), ("  ", "en"), ("parking", " ")])
async def test_empty_input_does_not_call_owner(make_settings, question, language):
    async def forbidden(request):
        raise AssertionError("invalid input must not reach owner")

    services = Services.build(make_settings(), knowledge_transport=httpx.MockTransport(forbidden))
    try:
        result = await services.search.search(CallContext(), KnowledgeRequest(question=question, language=language))
        assert (result.outcome, result.nextStep) == ("INVALID_REQUEST", "ASK_TO_REPHRASE")
    finally:
        await services.aclose()


async def test_question_limit_preserves_entire_question_and_rejects_overflow(make_settings):
    requests = []

    async def owner(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"outcome": "NO_ANSWER"})

    services = Services.build(make_settings(), knowledge_transport=httpx.MockTransport(owner))
    try:
        question = "ಕ" * 499 + "?"
        result = await services.search.search(CallContext(), KnowledgeRequest(question=question, language="kn"))
        assert result.outcome == "NO_ANSWER" and requests == [{"question": question, "language": "kn"}]
        with pytest.raises(ValidationError):
            KnowledgeRequest(question=question + "!", language="kn")
        assert len(requests) == 1
    finally:
        await services.aclose()


@pytest.mark.parametrize("outcome,step", [("EMERGENCY_TRANSFER", "TRANSFER_EMERGENCY"),
                                         ("DESK_TRANSFER", "TRANSFER_DESK")])
@pytest.mark.parametrize("field,bad", [
    ("answer", {"text": "Owner instruction", "language": " "}),
    ("answer", {"text": "x" * 1001, "language": "en"}),
    ("department", {"name": " "}), ("sourceId", {"private": "owner-private"}),
])
async def test_transfer_survives_invalid_optional_field(make_settings, outcome, step, field, bad, caplog):
    payload = {"outcome": outcome, "destination": "desk", field: bad}
    services = Services.build(make_settings(), knowledge_transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=payload)))
    try:
        result = await services.search.search(
            CallContext(), KnowledgeRequest(question="private question", language="en"))
        assert (result.outcome, result.nextStep, result.routing.decision) == ("ROUTING_REQUIRED", step, outcome)
        assert result.destination == "desk"
        assert getattr(result, "answer" if field == "answer" else "sourceId") is None
        assert result.routing.department is None
        assert "knowledge_optional_field_dropped" in caplog.text
        assert "owner-private" not in caplog.text and "private question" not in caplog.text
        assert "Owner instruction" not in caplog.text
    finally:
        await services.aclose()


@pytest.mark.parametrize("content_type", ["text/html", "text/plain", ""])
async def test_knowledge_refuses_non_json_media_type(make_settings, content_type):
    services = Services.build(make_settings(), knowledge_transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=b'{"outcome":"NO_ANSWER"}',
                                      headers={"content-type": content_type})))
    try:
        result = await services.search.search(CallContext(), KnowledgeRequest(question="parking", language="en"))
        assert (result.outcome, result.detail) == ("COULD_NOT_CHECK", "MALFORMED")
    finally:
        await services.aclose()


@pytest.mark.parametrize("field", ["destination", "sourceId"])
@pytest.mark.parametrize("length", [64, 65])
async def test_knowledge_metadata_is_bounded(make_settings, field, length):
    services = Services.build(make_settings(), knowledge_transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"outcome": "ANSWERED",
            "answer": {"text": "Parking is available.", "language": "en"}, field: "x" * length})))
    try:
        result = await services.search.search(CallContext(), KnowledgeRequest(question="parking", language="en"))
        if length == 64:
            assert result.outcome == "ANSWERED" and getattr(result, field) == "x" * 64
        else:
            assert (result.outcome, result.detail) == ("COULD_NOT_CHECK", "MALFORMED")
    finally:
        await services.aclose()


@pytest.mark.parametrize("outcome", ["EMERGENCY_TRANSFER", "DESK_TRANSFER", "ROUTE_DEPARTMENT"])
async def test_routing_speech_has_one_authoritative_location(make_settings, outcome):
    payload = {"outcome": outcome, "answer": {"text": "Owner wording", "language": "en"},
               "department": {"name": "Paediatrics"}}
    services = Services.build(make_settings(), knowledge_transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=payload)))
    try:
        result = await services.search.search(CallContext(), KnowledgeRequest(question="caller words", language="en"))
        assert result.answer is None
        assert result.routing.speak.text == "Owner wording" and result.routing.speak.language == "en"
        assert result.model_dump_json().count("Owner wording") == 1
    finally:
        await services.aclose()


async def test_external_cancellation_propagates_through_knowledge(make_settings):
    started, stopped = asyncio.Event(), asyncio.Event()

    async def owner(request):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    services = Services.build(make_settings(allow_budget_overrides=True, read_deadline_seconds=2,
                                            write_deadline_seconds=2, request_timeout_seconds=2),
                              knowledge_transport=httpx.MockTransport(owner))
    task = asyncio.create_task(services.search.search(
        CallContext(), KnowledgeRequest(question="private question", language="en")))
    try:
        async with asyncio.timeout(1):
            await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stopped.is_set()
    finally:
        task.cancel()
        await services.aclose()
