"""Whole-call summaries: exact text, callId deduplication, honest persistence outcomes and private logs."""

from __future__ import annotations

import json
import logging

import httpx
import pytest

from frontdesk_mcp import summary
from frontdesk_mcp.ops_client import OpsClient
from frontdesk_mcp.server import JsonFormatter

from . import harness
from .test_ops_client import Upstream

CALL_CONTEXT = {"operation_id": None, "started_at": "2026-10-01T09:58:00+05:30"}
CALLBACK = {"intent": "AVAILABILITY", "outcome": "CALLBACK_NOTED", "callerMobile": "9000000101",
            "doctorId": "doc_garima", "language": "kn-IN",
            "summaryText": "Lakshmi Rao, 9000000101, asked for Dr. Garima tomorrow morning; callback promised."}
GENERAL = {**CALLBACK, "outcome": "RESOLVED_BY_AGENT"}
STORED = {"id": "cs_1", "callId": "call-1", "startedAt": "2026-10-01T09:58:00+05:30",
          "intent": "GENERAL_INFO", "outcome": "RESOLVED_BY_AGENT", "summaryText": "Earlier conversation.",
          "createdAt": "2026-10-01T10:03:00+05:30"}


@pytest.fixture
async def h(make_settings):
    built = harness.build(make_settings())
    yield built
    await built.aclose()


async def record(h, ctx=None, **args):
    return await summary.SummaryService(h.ops, h.settings).record(
        ctx or h.ctx(**CALL_CONTEXT), summary.SummaryRequest(**args))


def posted(h) -> list:
    return [r for r in h.requests if r.url.path.endswith("/call-summaries")]


async def test_callback_summary_sends_exact_text_trusted_context_and_no_header_key(h):
    result = await record(h, **CALLBACK)
    assert result.model_dump(mode="json") == {"outcome": "SAVED"}
    [request] = posted(h)
    assert json.loads(request.content) == {
        "callId": "call-1", "startedAt": "2026-10-01T09:58:00+05:30", "language": "KN",
        "callerMobile": "9000000101", "intent": "AVAILABILITY", "outcome": "CALLBACK_NOTED", "doctorId": "doc_garima",
        "summaryText": CALLBACK["summaryText"],
    }
    assert "idempotency-key" not in request.headers


@pytest.mark.parametrize("text", ["x" * 500, "  ಜ್ವರ ಮೂರು ದಿನದಿಂದ.\nCaller requested help.  "])
async def test_valid_summary_text_is_not_normalized_prefixed_or_trimmed(h, text):
    result = await record(h, **{**CALLBACK, "summaryText": text})
    assert result.outcome == "SAVED" and json.loads(posted(h)[0].content)["summaryText"] == text


@pytest.mark.parametrize("text", ["", " \n\t", "x" * 501, "x" * 2000])
async def test_invalid_summary_text_is_refused_without_a_write(h, text):
    result = await record(h, **{**CALLBACK, "summaryText": text})
    assert result.model_dump(mode="json") == {"outcome": "INVALID_REQUEST", "fields": ["summaryText"]}
    assert posted(h) == []


@pytest.mark.parametrize("changed", [False, True])
async def test_same_call_returns_existing_summary_even_if_the_new_payload_differs(h, changed):
    first = await record(h, **CALLBACK)
    original = dict(h.ops_state.summaries["call-1"])
    args = {**CALLBACK}
    if changed:
        args.update(intent="GENERAL_INFO", outcome="RESOLVED_BY_AGENT", callerMobile="9000000999",
                    summaryText="Different intent, outcome, callback and text.")
    again = await record(h, **args)
    assert first.model_dump(mode="json") == {"outcome": "SAVED"}
    assert again.model_dump(mode="json") == {"outcome": "ALREADY_SAVED"}
    assert h.ops_state.summaries == {"call-1": original}


@pytest.mark.parametrize("field,value", [("call_id", None), ("call_id", "bad/id"),
                                         ("started_at", None), ("started_at", "2026-10-01T10:00:00"),
                                         ("started_at", "not-a-time")])
async def test_missing_or_malformed_trusted_context_is_not_saved(h, field, value):
    result = await record(h, h.ctx(**{**CALL_CONTEXT, field: value}), **CALLBACK)
    assert result.model_dump(mode="json") == {"outcome": "NOT_SAVED"}
    assert posted(h) == []


async def test_caller_mobile_is_never_copied_from_caller_id(h):
    args = {**CALLBACK, "outcome": "RESOLVED_BY_AGENT", "intent": "GENERAL_INFO"}
    del args["callerMobile"]
    assert (await record(h, **args)).outcome == "SAVED"
    assert "callerMobile" not in json.loads(posted(h)[0].content)


@pytest.mark.parametrize("override,field", [
    ({"callerMobile": None}, "callerMobile"), ({"callerMobile": "+919000000101"}, "callerMobile"),
    ({"callerMobile": "123"}, "callerMobile"), ({"appointmentId": "appt_1"}, "appointmentId"),
    ({"transferredTo": "desk"}, "transferredTo"), ({"doctorId": "../doc"}, "doctorId"),
])
async def test_callback_contact_and_identifier_constraints(h, override, field):
    result = await record(h, **{**CALLBACK, **override})
    assert result.model_dump(mode="json") == {"outcome": "INVALID_REQUEST", "fields": [field]}
    assert posted(h) == []


@pytest.mark.parametrize("tag,expected", [("en", "EN"), ("en-IN", "EN"), ("kn", "KN"), ("hi-IN", "HI"),
                                          ("ta", None), ("", None), (None, None)])
async def test_language_tags_map_to_the_contract_or_are_omitted(h, tag, expected):
    await record(h, **{**CALLBACK, "language": tag})
    assert json.loads(posted(h)[0].content).get("language") == expected


@pytest.mark.parametrize("outcome", ["TRANSFERRED", "EMERGENCY_TRANSFERRED"])
async def test_transfer_destination_is_forwarded_for_both_transfer_outcomes(h, outcome):
    result = await record(h, intent="LAB", outcome=outcome, transferredTo="Insurance desk (ground floor)",
                          summaryText="Explained and transferred.")
    assert result.outcome == "SAVED"
    assert json.loads(posted(h)[0].content)["transferredTo"] == "Insurance desk (ground floor)"


@pytest.mark.parametrize("outcome,destination", [("RESOLVED_BY_AGENT", "desk"), ("TRANSFERRED", "   ")])
async def test_invalid_destination_is_refused(h, outcome, destination):
    result = await record(h, intent="LAB", outcome=outcome, transferredTo=destination, summaryText="x")
    assert result.model_dump(mode="json") == {"outcome": "INVALID_REQUEST", "fields": ["transferredTo"]}
    assert posted(h) == []


@pytest.mark.parametrize("status,want", [(201, "SAVED"), (200, "ALREADY_SAVED"), (202, "NOT_CONFIRMED"),
                                        (400, "INVALID_REQUEST"), (401, "NOT_SAVED"), (403, "NOT_SAVED"),
                                        (404, "NOT_CONFIRMED"), (409, "NOT_CONFIRMED"),
                                        (429, "NOT_CONFIRMED"), (500, "NOT_CONFIRMED"),
                                        (502, "NOT_CONFIRMED"), (503, "NOT_CONFIRMED"), (504, "NOT_CONFIRMED")])
async def test_owner_statuses_are_mapped_without_returning_diagnostics(h, status, want, caplog):
    caplog.set_level(logging.INFO)
    body = STORED if status < 300 else {"error": {"code": "VALIDATION_FAILED", "message": CALLBACK["summaryText"],
                                                "details": [{"field": "summaryText",
                                                             "issue": CALLBACK["callerMobile"]}]}}
    up = Upstream(responses=[httpx.Response(status, json=body, headers={"Retry-After": "12"}) for _ in range(2)])
    async with OpsClient(h.settings, transport=httpx.MockTransport(up.handler)) as ops:
        result = await summary.SummaryService(ops, h.settings).record(h.ctx(**CALL_CONTEXT),
                                                                    summary.SummaryRequest(**GENERAL))
    expected = {"outcome": want}
    if status == 400:
        expected["fields"] = ["summaryText"]
    assert result.model_dump(mode="json") == expected
    assert len(up.api_requests()) == (2 if status == 401 else 1)
    logs = [r for r in caplog.records if r.name == "frontdesk_mcp.summary"]
    if want in ("NOT_CONFIRMED", "NOT_SAVED"):
        assert any(getattr(r, "fields", {}).get("reason") for r in logs)
    if status == 429:
        assert any(getattr(r, "fields", {}).get("retryAfterSeconds") == 12 for r in logs)
    if status == 201:
        assert any(getattr(r, "fields", {}).get("summaryId") == "cs_1" for r in logs)
    text = "\n".join(JsonFormatter().format(r) for r in caplog.records)
    assert CALLBACK["summaryText"] not in text and CALLBACK["callerMobile"] not in text and "Lakshmi" not in text


@pytest.mark.parametrize("status", [200, 201])
async def test_success_for_another_call_is_not_confirmed_and_logs_named_event(h, status, caplog):
    up = Upstream(responses=[httpx.Response(status, json={**STORED, "callId": "other-call"})])
    async with OpsClient(h.settings, transport=httpx.MockTransport(up.handler)) as ops:
        result = await summary.SummaryService(ops, h.settings).record(h.ctx(**CALL_CONTEXT),
                                                                    summary.SummaryRequest(**GENERAL))
    assert result.model_dump(mode="json") == {"outcome": "NOT_CONFIRMED"}
    assert any(r.message == "summary_call_id_mismatch" and r.fields["callId"] == "call-1" for r in caplog.records)


@pytest.mark.parametrize("status", [200, 201])
@pytest.mark.parametrize("body", [None, {"callId": "call-1"}])
async def test_unreadable_or_incomplete_success_is_not_confirmed(h, status, body):
    up = Upstream(responses=[httpx.Response(status, json=body) if body else httpx.Response(status, text="not JSON")])
    async with OpsClient(h.settings, transport=httpx.MockTransport(up.handler)) as ops:
        result = await summary.SummaryService(ops, h.settings).record(h.ctx(**CALL_CONTEXT),
                                                                    summary.SummaryRequest(**GENERAL))
    assert result.model_dump(mode="json") == {"outcome": "NOT_CONFIRMED"}


@pytest.mark.parametrize("later", [400, 401, 403, 429, 503])
async def test_refusal_after_an_unanswered_send_stays_not_confirmed(h, later):
    up = Upstream(responses=[httpx.ReadError("lost"), httpx.Response(later)])
    async with OpsClient(h.settings, transport=httpx.MockTransport(up.handler)) as ops:
        result = await summary.SummaryService(ops, h.settings).record(h.ctx(**CALL_CONTEXT),
                                                                    summary.SummaryRequest(**GENERAL))
    assert result.model_dump(mode="json") == {"outcome": "NOT_CONFIRMED"}
    assert len(up.api_requests()) == 2 and up.api_requests()[0].content == up.api_requests()[1].content


async def test_lost_write_response_then_verified_replay_is_already_saved(h):
    inner = h.ops.http._transport
    unanswered = True

    async def owner(request):
        nonlocal unanswered
        response = await inner.handle_async_request(request)
        if request.url.path.endswith("/call-summaries") and unanswered:
            unanswered = False
            assert response.status_code == 201
            raise httpx.ReadError("lost response after commit")
        return response

    async with OpsClient(h.settings, transport=httpx.MockTransport(owner)) as ops:
        result = await summary.SummaryService(ops, h.settings).record(h.ctx(**CALL_CONTEXT),
                                                                    summary.SummaryRequest(**GENERAL))
    assert result.model_dump(mode="json") == {"outcome": "ALREADY_SAVED"}
    assert len(h.ops_state.summaries) == 1 and len(posted(h)) == 2
    assert posted(h)[0].content == posted(h)[1].content


async def test_untrusted_owner_field_names_are_not_reflected(h):
    body = {"error": {"code": "VALIDATION_FAILED", "message": "private",
                       "details": [{"field": CALLBACK["summaryText"]}, {"field": "callerMobile"}]}}
    up = Upstream(responses=[httpx.Response(400, json=body)])
    async with OpsClient(h.settings, transport=httpx.MockTransport(up.handler)) as ops:
        result = await summary.SummaryService(ops, h.settings).record(h.ctx(**CALL_CONTEXT),
                                                                    summary.SummaryRequest(**GENERAL))
    assert result.model_dump(mode="json") == {"outcome": "INVALID_REQUEST", "fields": ["callerMobile"]}


async def test_summary_works_without_knowledge_and_with_a_slow_healthy_owner(h):
    h.knowledge_state.fail_next.append(503)
    h.ops_state.delay_for_prefix["/call-summaries"] = 0.4
    assert h.settings.request_timeout_seconds == pytest.approx(0.30)
    assert (await record(h, **CALLBACK)).outcome == "SAVED"


@pytest.mark.parametrize("identifier,logged", [("Lakshmi Rao 9000000101 chest pain", False), ("9000000101", False),
                                             ("cs_0107", True), ("d9b410be-aa16-425b-b18f-938584698f20", True)])
async def test_saved_id_diagnostics_omit_unsafe_owner_identifiers(h, identifier, logged, caplog):
    caplog.set_level(logging.INFO)
    up = Upstream(responses=[httpx.Response(201, json={**STORED, "id": identifier})])
    async with OpsClient(h.settings, transport=httpx.MockTransport(up.handler)) as ops:
        result = await summary.SummaryService(ops, h.settings).record(h.ctx(**CALL_CONTEXT),
                                                                    summary.SummaryRequest(**GENERAL))
    assert result.model_dump(mode="json") == {"outcome": "SAVED"}
    logs = "\n".join(JsonFormatter().format(r) for r in caplog.records)
    assert (identifier in logs) is logged
    assert any(r.message == "summary_saved" and r.fields["callId"] == "call-1" for r in caplog.records)


@pytest.mark.parametrize("status", [400, 401, 403])
async def test_token_endpoint_refusal_is_not_saved_and_never_posts_a_summary(h, status):
    up = Upstream(token_responses=[httpx.Response(status)])
    async with OpsClient(h.settings, transport=httpx.MockTransport(up.handler)) as ops:
        result = await summary.SummaryService(ops, h.settings).record(h.ctx(**CALL_CONTEXT),
                                                                    summary.SummaryRequest(**GENERAL))
    assert result.model_dump(mode="json") == {"outcome": "NOT_SAVED"}
    assert up.api_requests() == [] and len(up.requests) == 1
