"""record_call_summary: invoked by the authenticated call-end lifecycle, outside conversational tool
selection. Authoritative call identity and timing come from trusted context; the payload is built once
and frozen; a replay returns the original; CALLBACK_NOTED carries the caller's name and number without
dropping them to fit 500 characters; a failed write is never reported as a saved callback."""

from __future__ import annotations

import hashlib
import json

import pytest
from fastmcp import Client, FastMCP

from frontdesk_mcp import access, context, summary

from . import harness

LIFECYCLE = {"operation_id": None, "started_at": "2026-10-01T09:58:00+05:30", "duration": "184", "turn": None}
CALLBACK = {"intent": "AVAILABILITY", "outcome": "CALLBACK_NOTED", "callerName": "Lakshmi Rao",
            "callerMobile": "9000000101", "doctorId": "doc_garima", "language": "kn-IN",
            "summaryText": "Asked for Dr. Garima tomorrow morning; board status UNKNOWN."}


@pytest.fixture
async def h(make_settings):
    built = harness.build(make_settings())
    yield built
    await built.aclose()


async def record(h, ctx=None, **args):
    service = summary.SummaryService(h.ops, h.settings)
    return await service.record(ctx or h.ctx(**LIFECYCLE), summary.SummaryRequest(**args))


def posted(h) -> list:
    return [r for r in h.requests if r.url.path.endswith("/call-summaries")]


async def test_callback_summary_is_stored_with_trusted_timing_and_a_frozen_body(h):
    result = await record(h, **CALLBACK)
    assert result.outcome == "STORED" and result.summaryId and result.nextStep == "DONE"
    [request] = posted(h)
    body = json.loads(request.content)
    assert body == {
        "callId": "call-1", "startedAt": "2026-10-01T09:58:00+05:30", "durationSeconds": 184, "language": "KN",
        "callerMobile": "9000000101", "intent": "AVAILABILITY", "outcome": "CALLBACK_NOTED", "doctorId": "doc_garima",
        "summaryText": "Caller: Lakshmi Rao. Callback requested. Requested: doc_garima. "
                       "Asked for Dr. Garima tomorrow morning; board status UNKNOWN.",
    }
    assert "appointmentId" not in body and "transferredTo" not in body
    assert request.headers["idempotency-key"] == hashlib.sha256(b"demo-hospital|summary|call-1").hexdigest()


async def test_replay_returns_the_original_unchanged(h):
    first = await record(h, **CALLBACK)
    second = await record(h, **CALLBACK)
    assert second.outcome == "REPLAYED" and second.summaryId == first.summaryId
    assert len(h.ops_state.summaries) == 1
    bodies = [json.loads(r.content) for r in posted(h)]
    assert bodies[0] == bodies[1]


@pytest.mark.parametrize("missing", ["call_id", "started_at"])
async def test_lifecycle_context_is_required_and_never_invented(h, missing):
    kwargs = {**LIFECYCLE, missing: None}
    result = await record(h, h.ctx(**kwargs), **CALLBACK)
    assert result.outcome == "LIFECYCLE_CONTEXT_MISSING" and posted(h) == []


async def test_duration_is_optional_but_comes_only_from_context(h):
    result = await record(h, h.ctx(**{**LIFECYCLE, "duration": None}), **CALLBACK)
    assert result.outcome == "STORED"
    assert "durationSeconds" not in json.loads(posted(h)[0].content)


async def test_caller_mobile_is_never_copied_from_caller_id(h):
    args = {**CALLBACK, "outcome": "RESOLVED_BY_AGENT", "intent": "GENERAL_INFO"}
    del args["callerMobile"], args["callerName"]
    result = await record(h, **args)  # the context carries +919000000101, the caller never gave it
    assert result.outcome == "STORED"
    assert "callerMobile" not in json.loads(posted(h)[0].content)


@pytest.mark.parametrize("override,field", [
    ({"callerMobile": None}, "callerMobile"),
    ({"callerName": None}, "callerName"),
    ({"callerMobile": "+919000000101"}, "callerMobile"),
    ({"appointmentId": "appt_1"}, "appointmentId"),
    ({"transferredTo": "desk"}, "transferredTo"),
])
async def test_callback_noted_requires_name_and_number_and_forbids_appointment_or_transfer(h, override, field):
    result = await record(h, **{**CALLBACK, **override})
    assert result.outcome == "INVALID_REQUEST" and field in result.fields and posted(h) == []


async def test_five_hundred_characters_never_drop_the_callback_details(h):
    long_text = "Caller explained a long history. " * 40  # well over 500 characters
    result = await record(h, **{**CALLBACK, "summaryText": long_text})
    assert result.outcome == "STORED"
    text = json.loads(posted(h)[0].content)["summaryText"]
    assert len(text) <= 500 and text.startswith("Caller: Lakshmi Rao. Callback requested. ")
    assert text.endswith("…")


@pytest.mark.parametrize("tag,expected", [("en", "EN"), ("en-IN", "EN"), ("kn", "KN"), ("hi-IN", "HI"),
                                          ("ta", None), ("", None), (None, None)])
async def test_language_tags_map_to_the_contract_or_are_omitted(h, tag, expected):
    args = {**CALLBACK, "language": tag}
    await record(h, h.ctx(**{**LIFECYCLE, "call_id": f"call-{tag}"}), **args)
    body = json.loads(posted(h)[-1].content)
    assert body.get("language") == expected


async def test_transferred_to_is_only_for_transfer_outcomes(h):
    ok = await record(h, intent="LAB", outcome="TRANSFERRED", transferredTo="laboratory",
                      summaryText="Asked for a report.")
    assert ok.outcome == "STORED" and json.loads(posted(h)[0].content)["transferredTo"] == "laboratory"
    bad = await record(h, h.ctx(**{**LIFECYCLE, "call_id": "call-2"}), intent="LAB", outcome="RESOLVED_BY_AGENT",
                       transferredTo="laboratory", summaryText="x")
    assert bad.outcome == "INVALID_REQUEST" and "transferredTo" in bad.fields


async def test_a_completed_outcome_survives_an_abrupt_hang_up(h):
    """The platform decides the outcome from the call record; MCP stores what it is told, including an
    APPOINTMENT_NOTED after the caller dropped, and ABANDONED only when the platform says so."""
    noted = await record(h, intent="BOOKING", outcome="APPOINTMENT_NOTED", appointmentId="appt_0001",
                         doctorId="doc_garima", summaryText="Request noted; caller hung up after confirmation.")
    assert noted.outcome == "STORED" and json.loads(posted(h)[0].content)["appointmentId"] == "appt_0001"
    abandoned = await record(h, h.ctx(**{**LIFECYCLE, "call_id": "call-2"}), intent="OTHER", outcome="ABANDONED",
                             summaryText="Caller disconnected before stating a request.")
    assert abandoned.outcome == "STORED"


async def test_failed_persistence_is_not_a_saved_callback(h):
    h.ops_state.fail_next.append(("/call-summaries", 429, {"Retry-After": "30"}))  # refused before processing
    result = await record(h, **CALLBACK)
    assert result.outcome == "COULD_NOT_RECORD" and result.retryAfterSeconds == 30 and result.summaryId is None
    assert len(h.ops_state.summaries) == 0
    h.ops_state.fail_next.append(("/call-summaries", 503, {}))  # failed after receiving it: may be stored
    uncertain = await record(h, **CALLBACK)
    assert uncertain.outcome == "UNCERTAIN" and uncertain.nextStep == "RETRY_SAME_PAYLOAD"


async def test_lost_response_is_uncertain_and_the_platform_retry_replays(h):
    h.ops_state.commit_then["/call-summaries"] = 504
    lost = await record(h, **CALLBACK)
    assert lost.outcome == "UNCERTAIN" and lost.summaryId is None
    retried = await record(h, **CALLBACK)  # the platform resends the same finalized inputs
    assert retried.outcome in ("STORED", "REPLAYED") and len(h.ops_state.summaries) == 1
    bodies = [json.loads(r.content) for r in posted(h)]
    assert bodies[0] == bodies[-1]


async def test_owner_rejection_and_wrong_scope(h, make_settings):
    h.ops_state.malformed_next.append("/call-summaries")
    odd = await record(h, **CALLBACK)
    assert odd.outcome == "UNCERTAIN" and odd.detail == "MALFORMED_SUCCESS"
    hh = harness.build(make_settings())
    hh.ops_state.clients["mcp-test"] = ("ops-secret", {"appointments.write"})  # no calls.write
    try:
        forbidden = await record(hh, hh.ctx(**LIFECYCLE), **CALLBACK)
        assert forbidden.outcome == "COULD_NOT_RECORD" and forbidden.detail == "AUTH"
    finally:
        await hh.aclose()


async def test_summary_works_while_the_knowledge_service_is_down(h):
    h.knowledge_state.fail_next.append(503)
    assert (await record(h, **CALLBACK)).outcome == "STORED"


# ------------------------------------------------------------------ lifecycle access boundary


def gated_server() -> FastMCP:
    mcp = FastMCP("gate-test", middleware=[access.LifecycleGate()])

    @mcp.tool(name="get_doctor_availability")
    def a() -> str:
        return "a"

    @mcp.tool(name="manage_booking")
    def b() -> str:
        return "b"

    @mcp.tool(name="search_knowledge")
    def c() -> str:
        return "c"

    @mcp.tool(name="record_call_summary", tags={access.LIFECYCLE_TAG})
    def d() -> str:
        return "d"

    return mcp


async def test_conversational_principal_cannot_see_or_call_the_summary_tool():
    context.principal_var.set("conversation")
    async with Client(gated_server()) as client:
        names = sorted(t.name for t in await client.list_tools())
        assert names == ["get_doctor_availability", "manage_booking", "search_knowledge"]
        refused = await client.call_tool("record_call_summary", {}, raise_on_error=False)
        assert refused.is_error and "lifecycle" in refused.content[0].text.lower()
        ok = await client.call_tool("search_knowledge", {})
        assert ok.data == "c"


async def test_lifecycle_principal_sees_only_the_summary_tool():
    context.principal_var.set("lifecycle")
    async with Client(gated_server()) as client:
        assert [t.name for t in await client.list_tools()] == ["record_call_summary"]
        assert (await client.call_tool("record_call_summary", {})).data == "d"
        refused = await client.call_tool("manage_booking", {}, raise_on_error=False)
        assert refused.is_error


async def test_no_principal_means_no_tools():
    context.principal_var.set(None)
    async with Client(gated_server()) as client:
        assert await client.list_tools() == []
        refused = await client.call_tool("search_knowledge", {}, raise_on_error=False)
        assert refused.is_error


# ------------------------------------------------------------------ review fixes (1 Oct 2026)


async def test_callback_essentials_survive_truncation_as_structured_prefix(h):
    """Review fix: the requested date and doctor must not live only in the truncatable free text."""
    long_text = "Caller explained a long history. " * 40
    result = await record(h, **{**CALLBACK, "summaryText": long_text, "requestedDate": "2026-10-05"})
    assert result.outcome == "STORED"
    text = json.loads(posted(h)[0].content)["summaryText"]
    assert len(text) <= 500
    assert text.startswith("Caller: Lakshmi Rao. Callback requested. Requested: 2026-10-05 with doc_garima. ")


async def test_transient_summary_failures_tell_the_platform_to_retry(h):
    h.ops_state.fail_next.append(("/call-summaries", 429, {"Retry-After": "30"}))
    result = await record(h, **CALLBACK)
    assert result.outcome == "COULD_NOT_RECORD" and result.nextStep == "RETRY_SAME_PAYLOAD"
    assert result.retryAfterSeconds == 30


async def test_credential_failure_is_terminal_for_the_platform(h, make_settings):
    hh = harness.build(make_settings(ops_client_secret="wrong"))
    try:
        result = await record(hh, hh.ctx(**LIFECYCLE), **CALLBACK)
        assert result.outcome == "COULD_NOT_RECORD" and result.nextStep == "RECORD_FAILED" and result.detail == "AUTH"
    finally:
        await hh.aclose()


async def test_transferred_to_is_free_text_up_to_64_characters(h):
    ok = await record(h, intent="INSURANCE", outcome="TRANSFERRED", transferredTo="Insurance desk (ground floor)",
                      summaryText="Cashless query.")
    assert ok.outcome == "STORED"
    from pydantic import ValidationError
    with pytest.raises(ValidationError):  # the tool schema (max_length=64) refuses longer values before the service
        summary.SummaryRequest(intent="INSURANCE", outcome="TRANSFERRED", transferredTo="x" * 65, summaryText="x")
    blank = await record(h, h.ctx(**{**LIFECYCLE, "call_id": "call-2"}), intent="INSURANCE", outcome="TRANSFERRED",
                         transferredTo="   ", summaryText="Cashless query.")
    assert blank.outcome == "INVALID_REQUEST" and "transferredTo" in blank.fields


# ------------------------------------------------------------------ re-review (summary)


async def test_a_200_for_a_different_summary_under_the_same_call_id_is_a_conflict_not_done(h):
    """The owner returns the EXISTING summary unchanged on 200; if it is not ours, the callback was not saved."""
    other = {**CALLBACK, "outcome": "RESOLVED_BY_AGENT", "intent": "GENERAL_INFO", "summaryText": "FAQ only."}
    del other["callerMobile"], other["callerName"]
    first = await record(h, **other)
    assert first.outcome == "STORED"
    result = await record(h, **CALLBACK)  # same call id, different summary
    assert result.outcome == "CONFLICT" and result.nextStep == "FIX_PLATFORM_INPUT"
    assert result.detail == "CALL_ID_ALREADY_USED" and result.summaryId is None


async def test_a_slow_but_healthy_owner_still_stores_the_summary(h):
    h.ops_state.delay_for_prefix["/call-summaries"] = 0.4  # above the 0.30 s in-call cap; summaries run after the call
    assert h.settings.request_timeout_seconds == pytest.approx(0.30)
    result = await record(h, **CALLBACK)
    assert result.outcome == "STORED"
