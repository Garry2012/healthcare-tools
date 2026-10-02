"""The assembled server over real streamable HTTP (uvicorn): exactly four tools split between the
conversational and lifecycle principals, trusted identity from headers only, concurrent-call isolation,
local readiness distinct from dependency status, and a pinned tool-schema snapshot."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from frontdesk_mcp import cli, context, packs, prompt
from frontdesk_mcp.server import JsonFormatter, create_app

from . import harness
from .conftest import serving

SNAPSHOT = Path(__file__).parent / "contracts/mcp-tools.snapshot.json"
FORBIDDEN = {"x-call-id", "xcallid", "callid", "x-caller-number", "xcallernumber", "callernumber", "callernumbers",
             "idempotency-key", "idempotencykey", "operationid", "x-operation-id",
             "turncontext", "x-turn-context", "utterance", "tenant", "tenantid", "principal",
             "startedat", "durationseconds"}
CONVERSATIONAL = ["get_doctor_availability", "manage_booking", "search_knowledge"]


def _names(schema) -> set[str]:
    found: set[str] = set()
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key == "properties" and isinstance(value, dict):
                found |= {k.lower().replace("_", "") for k in value}
            found |= _names(value)
    elif isinstance(schema, list):
        for item in schema:
            found |= _names(item)
    return found


@pytest.fixture
async def served(make_settings):
    h = harness.build(make_settings())
    app = create_app(h.settings, ops_transport=h.ops.http._transport, knowledge_transport=h.knowledge.http._transport,
                     clock=h.clock)
    async with serving(app) as base:
        yield base, h
    await h.aclose()


def client(base: str, token: str = "mcp-token", **kwargs) -> Client:
    return Client(StreamableHttpTransport(f"{base}/mcp/", headers={"Authorization": f"Bearer {token}",
                                                                    **harness.headers(**kwargs)}))


async def test_conversational_principal_gets_exactly_three_tools_without_trusted_fields(served):
    base, _ = served
    async with client(base) as c:
        tools = await c.list_tools()
        instructions = c.initialize_result.instructions
    assert sorted(t.name for t in tools) == CONVERSATIONAL
    for tool in tools:
        leaked = (_names(tool.inputSchema) | _names(tool.outputSchema or {})) & FORBIDDEN
        assert leaked == set(), f"{tool.name} exposes {leaked}"
        assert tool.outputSchema, f"{tool.name} has no output schema"
    booking = next(t for t in tools if t.name == "manage_booking")
    assert booking.annotations.readOnlyHint is False and booking.annotations.destructiveHint is True
    availability = next(t for t in tools if t.name == "get_doctor_availability")
    assert availability.annotations.readOnlyHint is True
    assert "call you back" in instructions and "NOTED" in instructions


async def test_lifecycle_principal_gets_exactly_the_summary_tool(served):
    base, _ = served
    async with client(base, token="lifecycle-token") as c:
        tools = await c.list_tools()
    assert [t.name for t in tools] == ["record_call_summary"]
    assert tools[0].annotations.readOnlyHint is False and tools[0].annotations.idempotentHint is True


async def test_gateway_and_lifecycle_must_authenticate_and_health_stays_open(served):
    base, _ = served
    async with httpx.AsyncClient() as http:
        assert (await http.post(f"{base}/mcp/", json={})).status_code == 401
        assert (await http.post(f"{base}/mcp/", json={}, headers={"Authorization": "Bearer nope"})).status_code == 401
        assert (await http.get(f"{base}/health")).json() == {"status": "ok"}
        ready = await http.get(f"{base}/ready")
        assert ready.status_code == 200 and ready.json()["status"] == "ready"


def test_tool_schemas_match_the_pinned_snapshot(make_settings):
    assert SNAPSHOT.is_file(), "the tool schema snapshot must stay tracked (regenerate: frontdesk-mcp schema)"
    document = cli.schema_document(make_settings())
    assert document == json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert document["schemaVersion"] == prompt.SCHEMA_VERSION
    assert sorted(t["name"] for t in document["tools"]) == sorted([*CONVERSATIONAL, "record_call_summary"])


async def test_the_whole_journey_over_http(served):
    base, h = served
    async with client(base, operation_id="op-1") as c:
        found = await c.call_tool("get_doctor_availability", {"doctorName": "garima", "date": "2026-10-02"})
        assert found.structured_content["outcome"] == "CALLBACK_REQUIRED"  # tomorrow's board is UNKNOWN in the fixture
        today = (await c.call_tool("get_doctor_availability", {"doctorName": "garima", "date": "today"})
                 ).structured_content
        assert today["outcome"] == "AVAILABILITY" and len(today["doctors"][0]["board"]) == 2
        unknown_day = (await c.call_tool("manage_booking", {
            "action": "CREATE", "patientName": "Lakshmi Rao", "patientMobile": "9000000101", "doctorId": "doc_garima",
            "visitDate": "2026-10-02", "preferredTime": "09:30", "reasonVerbatim": "fever", "callerConfirmed": True,
        })).structured_content
        assert unknown_day["outcome"] == "CALLBACK_REQUIRED"  # the server refuses a create on an UNKNOWN date
        noted = (await c.call_tool("manage_booking", {
            "action": "CREATE", "patientName": "Lakshmi Rao", "patientMobile": "9000000101", "doctorId": "doc_garima",
            "visitDate": "2026-10-01", "preferredTime": "09:30", "reasonVerbatim": "fever", "callerConfirmed": True,
        })).structured_content
        assert noted["outcome"] == "NOTED"
        appointment_id = noted["appointment"]["appointmentId"]
        listed = (await c.call_tool("manage_booking", {"action": "LIST"})).structured_content
        assert [a["appointmentId"] for a in listed["appointments"]] == [appointment_id]
        answer = (await c.call_tool("search_knowledge", {"question": "parking", "language": "en"})).structured_content
        assert answer["outcome"] == "ANSWERED"
    async with client(base, operation_id="op-2") as c:
        unknown_move = (await c.call_tool("manage_booking", {"action": "RESCHEDULE", "appointmentId": appointment_id,
                                                             "newVisitDate": "2026-10-03", "callerConfirmed": True})
                        ).structured_content
        assert unknown_move["outcome"] == "CALLBACK_REQUIRED"  # the new date's board is UNKNOWN in the fixture
        h.ops_state.set_board("2026-10-03", [{"doctorId": "doc_garima", "session": "Morning",
                                              "status": "NOT_CONFIRMED", "expectedTime": "09:00",
                                              "expectedEndTime": "12:00", "updatedMinutesAgo": 1}])
        moved = (await c.call_tool("manage_booking", {"action": "RESCHEDULE", "appointmentId": appointment_id,
                                                      "newVisitDate": "2026-10-03", "callerConfirmed": True})
                 ).structured_content
        assert moved["outcome"] == "CHANGED"
    async with client(base, operation_id="op-3") as c:
        cancelled = (await c.call_tool("manage_booking", {"action": "CANCEL", "appointmentId": appointment_id,
                                                          "callerConfirmed": True})).structured_content
        assert cancelled["outcome"] == "CANCELLED"
    async with client(base, token="lifecycle-token", started_at="2026-10-01T09:58:00+05:30",
                      duration="240") as c:
        stored = (await c.call_tool("record_call_summary", {
            "intent": "BOOKING", "outcome": "APPOINTMENT_CANCELLED", "appointmentId": appointment_id,
            "summaryText": "Requested, moved and cancelled an appointment with Dr. Garima."})).structured_content
        assert stored["outcome"] == "STORED"
    assert h.ops_state.summaries["call-1"]["durationSeconds"] == 240


async def test_the_model_cannot_supply_identity_or_lifecycle_fields(served):
    base, h = served
    async with client(base) as c:
        for extra in ({"callId": "other"}, {"callerNumber": "+919000000999"}, {"operationId": "x"},
                      {"X-Caller-Number": "+919000000999"}, {"patientMobile": "9000000999"}):
            result = await c.call_tool("manage_booking", {"action": "LIST", **extra}, raise_on_error=False)
            assert result.is_error or result.structured_content["outcome"] in ("NOT_FOUND", "FOUND"), extra
        assert (await c.call_tool("manage_booking", {"action": "LIST"})).structured_content["outcome"] == "NOT_FOUND"
    queries = [r for r in h.requests if r.url.path.endswith("/appointments") and r.method == "GET"]
    assert queries and all(r.url.params["mobile"] == "9000000101" for r in queries)


async def test_conversational_bearer_cannot_finalize_and_lifecycle_cannot_book(served):
    base, h = served
    async with client(base, started_at="2026-10-01T09:58:00+05:30") as c:
        refused = await c.call_tool("record_call_summary", {"intent": "OTHER", "outcome": "ABANDONED",
                                                            "summaryText": "x"}, raise_on_error=False)
        assert refused.is_error
    async with client(base, token="lifecycle-token", operation_id="op-1") as c:
        refused = await c.call_tool("manage_booking", {"action": "LIST"}, raise_on_error=False)
        assert refused.is_error
    assert h.ops_state.summaries == {} and not [r for r in h.requests if "/appointments" in r.url.path]


async def test_concurrent_calls_keep_their_own_identity(served):
    base, h = served

    async def one(call_id: str, caller: str):
        async with client(base, call_id=call_id, caller=caller, operation_id=f"op-{call_id}") as c:
            await c.call_tool("manage_booking", {
                "action": "CREATE", "patientName": f"Patient {call_id}", "patientMobile": caller[3:],
                "doctorId": "doc_garima", "visitDate": "2026-10-01", "callerConfirmed": True})
            return (await c.call_tool("manage_booking", {"action": "LIST"})).structured_content

    results = await asyncio.gather(*(one(f"call-{i}", f"+91900000010{i}") for i in range(1, 6)))
    for i, listed in enumerate(results, start=1):
        assert [a["patientName"] for a in listed["appointments"]] == [f"Patient call-{i}"]
    assert len(h.ops_state.appointments) == 5
    assert {a["callId"] for a in h.ops_state.appointments.values()} == {f"call-{i}" for i in range(1, 6)}


async def test_dependency_status_is_separate_from_local_readiness(served, monkeypatch):
    from frontdesk_mcp import server as server_module

    monkeypatch.setattr(server_module, "DEPENDENCY_REFRESH_MIN_INTERVAL", 0.0)  # the throttle has its own test
    base, h = served
    async with httpx.AsyncClient() as http:
        healthy = (await http.get(f"{base}/dependencies")).json()
        assert healthy["operational"]["status"] == "ok" and healthy["knowledge"]["status"] == "configured"
        h.ops_state.fail_next.append(("/departments", 503, {}))
        h.ops_state.fail_next.append(("/departments", 503, {}))
        degraded = await http.get(f"{base}/dependencies", params={"refresh": "1"})
        assert degraded.status_code == 503 and degraded.json()["operational"]["status"] == "unavailable"
        assert (await http.get(f"{base}/ready")).status_code == 200  # local readiness is unaffected


async def test_log_lines_carry_the_call_id_not_the_caller(served):
    base, _ = served
    lines: list[dict] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lines.append(json.loads(JsonFormatter("demo-hospital").format(record)))

    package = logging.getLogger("frontdesk_mcp")
    handler = Capture()
    package.addHandler(handler)
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        async with client(base, call_id="call-log-1") as c:
            await c.call_tool("get_doctor_availability", {"doctorName": "garima", "date": "today"})
            await c.call_tool("manage_booking", {"action": "LIST"})  # upstream query carries ?mobile=
    finally:
        package.removeHandler(handler)
        root.removeHandler(handler)
    results = [line for line in lines if line["msg"] == "tool_result"]
    assert results and results[0]["callId"] == "call-log-1" and results[0]["outcome"] == "AVAILABILITY"
    assert all(line["provider"] == "demo-hospital" for line in lines)
    assert "9000000101" not in json.dumps(lines), "a caller number reached the logs (httpx request lines?)"
    assert "garima" not in json.dumps(lines).lower()


def test_the_pack_describes_exactly_the_four_tools_and_no_core_rule():
    pack = packs.load("healthcare")
    assert set(pack.tools) == {*CONVERSATIONAL, "record_call_summary"}
    words = " ".join([pack.instructions, *(t.description for t in pack.tools.values())]).casefold()
    for rule in prompt.CORE_RULES:
        assert rule.casefold()[:60] not in words, rule
    assert "slot" not in words


def test_instructions_cover_the_fixed_policies(make_settings):
    text = prompt.instructions(packs.load("healthcare"), ("en", "kn", "hi"), "Demo Hospital")
    for phrase in ("call you back", "CALLBACK_REQUIRED", "NOTED", "never say", "UNCERTAIN", "IDENTITY_UNAVAILABLE",
                   "COULD_NOT_CHECK", "explicit date", "(en, kn, hi)", "Demo Hospital"):
        assert phrase in text, phrase
    assert "slotId" not in text and "never say 'confirmed'" in text


def test_principal_contextvar_is_not_set_by_headers(make_settings):
    ctx = context.from_headers({"x-principal": "lifecycle", "principal": "lifecycle"}, make_settings())
    assert context.principal_var.get() is None and not hasattr(ctx, "principal")


# ------------------------------------------------------------------ review fixes (1 Oct 2026)


async def test_dependency_refresh_is_single_flight_and_throttled(served):
    """Review fix: an unauthenticated ?refresh=1 must not be able to drive owner traffic per hit."""
    base, h = served
    before = len([r for r in h.requests if r.url.path.endswith("/departments")])
    async with httpx.AsyncClient() as http:
        await asyncio.gather(*(http.get(f"{base}/dependencies", params={"refresh": "1"}) for _ in range(8)))
        await http.get(f"{base}/dependencies", params={"refresh": "1"})
    after = len([r for r in h.requests if r.url.path.endswith("/departments")])
    assert after - before <= 1  # one upstream check for nine refresh requests inside the minimum interval


async def test_results_carry_an_output_schema_and_structured_content_without_sdk_revalidation(served):
    """Review fix: the SDK re-validated every result against a 6 KB schema (~16 ms CPU per call). Results
    are returned as CallToolResult (via ToolResult.meta) so the SDK trusts the pydantic-validated content;
    the schema is still advertised for clients."""
    base, _ = served
    async with client(base) as c:
        tools = {t.name: t for t in await c.list_tools()}
        assert tools["get_doctor_availability"].outputSchema["properties"]["outcome"]
        result = await c.call_tool("get_doctor_availability", {"doctorName": "garima", "date": "today"})
    assert result.structured_content["outcome"] == "AVAILABILITY"
    assert result.meta == {"schemaVersion": prompt.SCHEMA_VERSION}


def test_an_external_suite_exists_for_owner_designated_services():
    """scripts/test.sh runs `pytest -m external` when OPS_E2E_BASE_URL is set; the marker must select tests."""
    import subprocess
    import sys

    out = subprocess.run([sys.executable, "-m", "pytest", "tests", "-m", "external", "--collect-only", "-q",
                          "-p", "no:cacheprovider"], capture_output=True, text=True, check=False)
    import re

    assert "test_external.py" in out.stdout
    collected = re.search(r"(\d+)(?:/\d+)? tests? collected", out.stdout)
    assert collected and int(collected.group(1)) >= 3, out.stdout[-300:]


async def test_smoke_distinguishes_unconfigured_knowledge_from_scheduling_failure(make_settings, capsys):
    import runpy

    smoke = runpy.run_path(str(Path(__file__).resolve().parents[3] / "deploy/azure/smoke.py"))
    settings = make_settings(knowledge_base_url="", knowledge_bearer_token="")
    h = harness.build(settings)
    app = create_app(settings, ops_transport=h.ops.http._transport, clock=h.clock)
    try:
        async with serving(app) as base:
            await smoke["smoke"](f"{base}/mcp/", "mcp-token", "lifecycle-token", "en", "General Medicine")
        assert "knowledge: NOT_CONFIGURED" in capsys.readouterr().out
    finally:
        await h.aclose()


def test_agent_instructions_command_exports_versioned_rules_without_credentials():
    import subprocess

    result = subprocess.run(["make", "agent-instructions"], cwd=Path(__file__).resolve().parents[3],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert f"Tool schema {prompt.SCHEMA_VERSION}." in result.stdout
    for rule in ("NOTED", "CALLBACK_REQUIRED", "UNCERTAIN", "search_knowledge", "emergency"):
        assert rule in result.stdout
    assert "secret" not in result.stdout.casefold() and "Bearer" not in result.stdout
    artifact = Path(__file__).resolve().parents[3] / "docs/handover/mcp-only/AGENT-INSTRUCTIONS.txt"
    assert result.stdout.encode() == artifact.read_bytes()


def test_instructions_follow_real_knowledge_steps():
    text = prompt.instructions(packs.load("healthcare"), ("en",), "Demo Hospital")
    assert "or ask routing.speak" not in text
    assert "routing.department as departmentName" in text
    assert "search_knowledge CLARIFICATION_NEEDED: ask answer.text verbatim" in text


def test_model_is_told_to_act_on_emergencies_not_defer_to_infrastructure():
    text = packs.load("healthcare").instructions
    assert "transfer immediately and do not continue scheduling" in text
    assert "voice platform" not in text and "guardrail" not in text


def test_routing_object_cannot_claim_a_clarification_decision():
    from pydantic import ValidationError

    from frontdesk_mcp.outcomes import Routing

    with pytest.raises(ValidationError):
        Routing(decision="CLARIFY")
