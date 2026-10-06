"""The assembled server over real streamable HTTP (uvicorn): exactly four tools under gateway authentication,
trusted identity from headers only, concurrent-call isolation,
local readiness distinct from dependency status, and a pinned tool-schema snapshot."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from frontdesk_mcp import cli, packs, prompt
from frontdesk_mcp.server import JsonFormatter, create_app

from . import harness
from .conftest import serving

SNAPSHOT = Path(__file__).parent / "contracts/mcp-tools.snapshot.json"
FORBIDDEN = {"x-call-id", "xcallid", "callid", "x-caller-number", "xcallernumber", "callernumber", "callernumbers",
             "idempotency-key", "idempotencykey", "operationid", "x-operation-id",
             "turncontext", "x-turn-context", "utterance", "tenant", "tenantid", "principal",
             "startedat", "durationseconds"}
TOOLS = ["get_doctor_availability", "manage_booking", "record_call_summary", "search_knowledge"]


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


async def test_gateway_gets_all_four_tools_without_trusted_fields(served):
    base, _ = served
    async with client(base) as c:
        tools = await c.list_tools()
        instructions = c.initialize_result.instructions
    assert sorted(t.name for t in tools) == TOOLS
    for tool in tools:
        leaked = (_names(tool.inputSchema) | _names(tool.outputSchema or {})) & FORBIDDEN
        assert leaked == set(), f"{tool.name} exposes {leaked}"
        assert tool.outputSchema, f"{tool.name} has no output schema"
    booking = next(t for t in tools if t.name == "manage_booking")
    assert booking.annotations.readOnlyHint is False and booking.annotations.destructiveHint is True
    availability = next(t for t in tools if t.name == "get_doctor_availability")
    assert availability.annotations.readOnlyHint is True
    assert "NOTED" in instructions and prompt.SCHEMA_VERSION in instructions


async def test_working_hours_and_missing_date_are_exposed_through_mcp(served):
    base, h = served
    async with client(base) as c:
        tool = next(t for t in await c.list_tools() if t.name == "get_doctor_availability")
        hours = await c.call_tool("get_doctor_availability", {
            "doctorId": "doc_garima", "purpose": "WORKING_HOURS"}, raise_on_error=False)
        missing = await c.call_tool("get_doctor_availability", {"doctorId": "doc_garima"}, raise_on_error=False)
    assert not hours.is_error and hours.structured_content["outcome"] == "WORKING_HOURS"
    assert not missing.is_error and missing.structured_content["detail"] == "DATE_REQUIRED"
    assert "date" not in tool.inputSchema.get("required", []) and "/availability" not in h.ops_paths()
    assert tool.outputSchema["$defs"]["BoardSessionOut"]["properties"]["status"]["enum"] == [
        "IN", "LATE", "CANCELLED", "NOT_CONFIRMED", "UNKNOWN"]


def test_availability_description_distinguishes_counts_and_sources(make_settings):
    doc = cli.schema_document(make_settings())
    text = next(t["description"] for t in doc["tools"] if t["name"] == "get_doctor_availability")
    for fact in ("totalMatches", "bookableFound", "complete", "WORKING_HOURS", "decision", "status",
                 "NOT_AVAILABLE", "HANDOFF_REQUIRED", "SESSION_ENDED", "attendance not confirmed"):
        assert fact in text


async def test_department_booking_is_absent_from_schema_and_refused_without_writes(served):
    base, h = served
    async with client(base, operation_id="no-department") as c:
        tool = next(t for t in await c.list_tools() if t.name == "manage_booking")
        assert "departmentId" not in tool.inputSchema["properties"]
        result = await c.call_tool("manage_booking", {"action": "CREATE", "departmentId": "dept_genmed",
            "patientName": "Synthetic", "patientMobile": "9000000101", "visitDate": "2026-10-05",
            "callerConfirmed": True}, raise_on_error=False)
    assert result.is_error and not h.ops_state.appointments


async def test_gateway_can_save_a_summary_with_trusted_call_identity(served):
    base, h = served
    async with client(base, started_at="2026-10-01T09:58:00+05:30") as c:
        result = await c.call_tool("record_call_summary", {
            "intent": "GENERAL_INFO", "outcome": "RESOLVED_BY_AGENT", "summaryText": "Explained visiting hours."},
            raise_on_error=False)
        tool = next(t for t in await c.list_tools() if t.name == "record_call_summary")
    assert result.structured_content == {"outcome": "SAVED"}
    assert h.ops_state.summaries["call-1"]["summaryText"] == "Explained visiting hours."
    assert tool.annotations.readOnlyHint is False and tool.annotations.idempotentHint is True


async def test_gateway_must_authenticate_and_health_stays_open(served):
    base, _ = served
    async with httpx.AsyncClient() as http:
        assert (await http.post(f"{base}/mcp/", json={})).status_code == 401
        assert (await http.post(f"{base}/mcp/", json={}, headers={"Authorization": "Bearer nope"})).status_code == 401
        assert (await http.post(f"{base}/mcp/", json={},
                                headers={"Authorization": "Bearer lifecycle-token"})).status_code == 401
        assert (await http.get(f"{base}/health")).json() == {"status": "ok"}
        ready = await http.get(f"{base}/ready")
        assert ready.status_code == 200 and ready.json()["status"] == "ready"


def test_tool_schemas_match_the_pinned_snapshot(make_settings):
    assert SNAPSHOT.is_file(), "the tool schema snapshot must stay tracked (regenerate: frontdesk-mcp schema)"
    document = cli.schema_document(make_settings())
    assert document == json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert document["schemaVersion"] == prompt.SCHEMA_VERSION
    assert sorted(t["name"] for t in document["tools"]) == TOOLS


async def test_the_whole_journey_over_http(served):
    base, h = served
    async with client(base, operation_id="op-1") as c:
        found = await c.call_tool("get_doctor_availability", {"doctorName": "garima", "date": "2026-10-02"})
        assert found.structured_content["outcome"] == "AVAILABILITY"  # future uses the usual schedule
        today = (await c.call_tool("get_doctor_availability", {"doctorName": "garima", "date": "today"})
                 ).structured_content
        assert today["outcome"] == "AVAILABILITY" and len(today["doctors"][0]["board"]) == 2
        unknown_day = (await c.call_tool("manage_booking", {
            "action": "CREATE", "patientName": "Lakshmi Rao", "patientMobile": "9000000101",
            "doctorId": "doc_vikram_desai",
            "visitDate": "2026-10-02", "preferredTime": "09:30", "reasonVerbatim": "fever", "callerConfirmed": True,
        })).structured_content
        assert unknown_day["outcome"] == "CALLBACK_REQUIRED"  # on-call is callback on every date
        noted = (await c.call_tool("manage_booking", {
            "action": "CREATE", "patientName": "Lakshmi Rao", "patientMobile": "9000000101", "doctorId": "doc_garima",
            "visitDate": "2026-10-01", "preferredTime": "10:45", "reasonVerbatim": "fever", "callerConfirmed": True,
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
        assert unknown_move["outcome"] == "NOT_AVAILABLE"  # Saturday is not a usual day
        moved = (await c.call_tool("manage_booking", {"action": "RESCHEDULE", "appointmentId": appointment_id,
                                                      "newVisitDate": "2026-10-05", "callerConfirmed": True})
                 ).structured_content
        assert moved["outcome"] == "NOTED"
    async with client(base, operation_id="op-3") as c:
        cancelled = (await c.call_tool("manage_booking", {"action": "CANCEL", "appointmentId": appointment_id,
                                                          "callerConfirmed": True})).structured_content
        assert cancelled["outcome"] == "CANCELLED"
    async with client(base, started_at="2026-10-01T09:58:00+05:30") as c:
        stored = (await c.call_tool("record_call_summary", {
            "intent": "BOOKING", "outcome": "APPOINTMENT_CANCELLED", "appointmentId": appointment_id,
            "summaryText": "Requested, moved and cancelled an appointment with Dr. Garima."})).structured_content
        assert stored == {"outcome": "SAVED"}
    assert "durationSeconds" not in h.ops_state.summaries["call-1"]


async def test_the_model_cannot_supply_booking_identity_fields(served):
    base, h = served
    async with client(base) as c:
        for extra in ({"callId": "other"}, {"callerNumber": "+919000000999"}, {"operationId": "x"},
                      {"X-Caller-Number": "+919000000999"}, {"patientMobile": "9000000999"}):
            result = await c.call_tool("manage_booking", {"action": "LIST", **extra}, raise_on_error=False)
            assert result.is_error or result.structured_content["outcome"] in ("NOT_FOUND", "FOUND"), extra
        assert (await c.call_tool("manage_booking", {"action": "LIST"})).structured_content["outcome"] == "NOT_FOUND"
    queries = [r for r in h.requests if r.url.path.endswith("/appointments") and r.method == "GET"]
    assert queries and all(r.url.params["mobile"] == "9000000101" for r in queries)


async def test_summary_arguments_cannot_override_trusted_headers(served):
    base, h = served
    async with client(base, started_at="2026-10-01T09:58:00+05:30") as c:
        result = await c.call_tool("record_call_summary", {
            "intent": "OTHER", "outcome": "ABANDONED", "summaryText": "Caller left.",
            "callId": "forged-call", "startedAt": "2020-01-01T00:00:00Z"}, raise_on_error=False)
        assert result.is_error or result.structured_content == {"outcome": "SAVED"}
        await c.call_tool("record_call_summary", {
            "intent": "OTHER", "outcome": "ABANDONED", "summaryText": "Caller left."})
    assert set(h.ops_state.summaries) == {"call-1"}
    assert h.ops_state.summaries["call-1"]["startedAt"] == "2026-10-01T09:58:00+05:30"


async def test_concurrent_summaries_keep_their_own_call_and_start_time(served):
    base, h = served

    async def one(i):
        async with client(base, call_id=f"call-{i}", started_at=f"2026-10-01T09:0{i}:00+05:30") as c:
            return (await c.call_tool("record_call_summary", {
                "intent": "OTHER", "outcome": "ABANDONED", "summaryText": f"Conversation {i}."},
                raise_on_error=False)).structured_content

    assert await asyncio.gather(*(one(i) for i in range(1, 6))) == [{"outcome": "SAVED"}] * 5
    for i in range(1, 6):
        stored = h.ops_state.summaries[f"call-{i}"]
        assert stored["startedAt"] == f"2026-10-01T09:0{i}:00+05:30"
        assert stored["summaryText"] == f"Conversation {i}."


async def test_concurrent_calls_keep_their_own_identity(served):
    base, h = served

    async def one(call_id: str, caller: str):
        async with client(base, call_id=call_id, caller=caller, operation_id=f"op-{call_id}") as c:
            await c.call_tool("manage_booking", {
                "action": "CREATE", "patientName": f"Patient {call_id}", "patientMobile": caller[3:],
                "doctorId": "doc_garima", "visitDate": "2026-10-01", "session": "Morning", "callerConfirmed": True})
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


def test_pack_describes_exactly_the_four_tools():
    assert set(packs.load("healthcare").tools) == set(TOOLS)


def test_published_tool_text_contains_facts_not_behaviour_scripts(make_settings):
    from frontdesk_mcp.cli import schema_document

    document = schema_document(make_settings())
    text = [document["instructions"]]

    def descriptions(value):
        if isinstance(value, dict):
            text.extend(v for k, v in value.items() if k == "description")
            for child in value.values():
                descriptions(child)
        elif isinstance(value, list):
            for child in value:
                descriptions(child)

    descriptions(document["tools"])
    forbidden = ("say ", "never say", "ask ", "transfer immediately", "speak ", "pass ",
                 "read back", "read-back", "do not", "never ", "collect ", "use ")
    for entry in text:
        for phrase in forbidden:
            assert re.search(r"\b" + re.escape(phrase), entry.casefold()) is None, (phrase, entry)


def test_server_instructions_are_short_contract_facts():
    text = prompt.instructions(packs.load("healthcare"), ("en", "kn", "hi"), "Demo Hospital")
    assert len(text) < 1000
    for fact in ("Demo Hospital", "en, kn, hi", "YYYY-MM-DD", "relative dates are not accepted",
                 "NOTED", "CALLBACK_REQUIRED", "UNCERTAIN", prompt.SCHEMA_VERSION):
        assert fact in text


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
            await smoke["smoke"](f"{base}/mcp/", "mcp-token", "en", "General Medicine", "absent")
        assert "knowledge: NOT_CONFIGURED" in capsys.readouterr().out
        assert h.ops_state.summaries == {} and h.ops_state.appointments == {}
        assert not [r for r in h.requests if r.method == "POST" and r.url.path != "/api/v1/auth/token"]
    finally:
        await h.aclose()


def test_cli_exposes_only_server_and_schema_commands():
    import subprocess

    result = subprocess.run(["frontdesk-mcp", "--help"], capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert "{serve,schema}" in result.stdout



def test_routing_object_cannot_claim_a_clarification_decision():
    from pydantic import ValidationError

    from frontdesk_mcp.outcomes import Routing

    with pytest.raises(ValidationError):
        Routing(decision="CLARIFY")


def _interface_rows():
    text = (Path(__file__).resolve().parents[3] / "docs/handover/VOICE-TEAM.md").read_text()
    rows = {}
    for line in text.splitlines():
        if line.startswith("| `"):
            cells = [c.strip().strip("`") for c in line.strip("|").split(" | ")]
            assert cells[0] not in rows, f"duplicate interface row: {cells[0]}"
            rows[cells[0]] = cells[1:]
    return text, rows


def test_interface_parameter_and_output_tables_match_pinned_schema():
    snapshot = json.loads((Path(__file__).parent / "contracts/mcp-tools.snapshot.json").read_text())
    text, rows = _interface_rows()
    assert f"Schema version: `{snapshot['schemaVersion']}`" in text
    expected = {}

    def wire_shape(value):
        # Descriptions are separate prose; output defaults include callback metadata,
        # which is intentionally not reproduced as a spoken script in the interface document.
        if isinstance(value, dict):
            return {k: wire_shape(v) for k, v in value.items() if k not in ("title", "description", "default")}
        if isinstance(value, list):
            return [wire_shape(v) for v in value]
        return value

    for tool in snapshot["tools"]:
        for kind, schema in (("input", tool["inputSchema"]), ("output", tool["outputSchema"])):
            objects = [("", schema), *[(f"$defs.{name}.", definition)
                                      for name, definition in schema.get("$defs", {}).items()]]
            for prefix, obj in objects:
                for field, shape in obj.get("properties", {}).items():
                    key = f"{tool['name']}.{kind}.{prefix}{field}"
                    expected[key] = (wire_shape(shape), "required" if field in obj.get("required", []) else "optional")
                    assert key in rows, f"missing interface field: {key}"
                    cells = rows[key]
                    assert len(cells) == 3 and cells[2], f"missing field meaning: {key}"
                    assert (json.loads(cells[0]), cells[1]) == expected[key], key
                    if kind == "input":
                        assert cells[2] == shape["description"], key
    actual = {key for key in rows if ".input." in key or ".output." in key}
    assert actual == set(expected)


def test_interface_describes_every_outcome_and_next_step():
    from typing import get_args

    from frontdesk_mcp import outcomes

    _, rows = _interface_rows()
    models = {"get_doctor_availability": outcomes.AvailabilityResult, "manage_booking": outcomes.BookingResult,
              "search_knowledge": outcomes.KnowledgeResult, "record_call_summary": outcomes.SummaryResult}
    expected = set()
    for name, model in models.items():
        for field in ("outcome", "nextStep") if name != "record_call_summary" else ("outcome",):
            for value in get_args(model.model_fields[field].annotation):
                key = f"{name}.{field}.{value}"
                expected.add(key)
                assert key in rows and len(rows[key]) == 1 and rows[key][0], f"undocumented meaning: {key}"
    actual = {key for key in rows if ".outcome." in key or ".nextStep." in key}
    assert actual == expected


@pytest.mark.parametrize("length", [501, 2000])
async def test_summary_length_is_an_in_band_invalid_request(served, length):
    base, h = served
    async with client(base, started_at="2026-10-01T09:58:00+05:30") as c:
        result = await c.call_tool("record_call_summary", {
            "intent": "GENERAL_INFO", "outcome": "RESOLVED_BY_AGENT", "summaryText": "x" * length},
            raise_on_error=False)
        tool = next(t for t in await c.list_tools() if t.name == "record_call_summary")
    assert not result.is_error
    assert result.structured_content == {"outcome": "INVALID_REQUEST", "fields": ["summaryText"]}
    assert tool.inputSchema["properties"]["summaryText"]["maxLength"] == 500
    assert not h.ops_state.summaries


@pytest.mark.parametrize("invalid", [
    {"summaryText": {"private": "NAME42 9000000123 SYMPTOM42"}},
    {"summaryText": ["NAME42", "9000000123", "SYMPTOM42"]},
    {"summaryText": 9000000123},
    {"summaryText": "NAME42 9000000123 SYMPTOM42" + "x" * 1974},
    {"intent": "NAME42 9000000123 SYMPTOM42"},
    {"callerMobile": {"private": "NAME42 9000000123 SYMPTOM42"}},
    {"NAME42 9000000123 SYMPTOM42": "unexpected argument"},
], ids=["object", "list", "number", "outer-cap", "enum", "contact-type", "unexpected-key"])
async def test_invalid_summary_does_not_echo_private_input_in_protocol_or_logs(served, invalid, caplog, capsys):
    base, h = served
    async with client(base, started_at="2026-10-01T09:58:00+05:30") as c:
        result = await c.call_tool("record_call_summary", {
            "intent": "GENERAL_INFO", "outcome": "RESOLVED_BY_AGENT", "summaryText": "Whole call.", **invalid},
            raise_on_error=False)
    captured = capsys.readouterr()
    response = json.dumps({"content": [block.model_dump(mode="json") for block in result.content],
                           "structuredContent": result.structured_content, "meta": result.meta})
    for marker in ("NAME42", "9000000123", "SYMPTOM42"):
        assert marker not in response + caplog.text + captured.out + captured.err
    assert result.is_error and result.structured_content is None
    assert "argument" in response.lower()  # still an explicit argument error, not a success envelope
    assert not [r for r in h.requests if r.url.path.endswith("/call-summaries")]
    assert not h.ops_state.summaries


@pytest.mark.parametrize("arguments,expected", [
    ({}, "protocol"), ({"summaryText": None}, "protocol"),
    ({"summaryText": "  \n  "}, "invalid"),
    ({"summaryText": "NAME42 9000000123 SYMPTOM42" + "x" * 473}, "saved"),
    ({"summaryText": "  Lakshmi 9000000123 — ಜ್ವರ; बुखार.\nCallback promised.  "}, "saved"),
    ({"summaryText": "NAME42 9000000123 SYMPTOM42" + "x" * 1974}, "protocol"),
], ids=["missing", "null", "blank", "500", "multilingual-exact", "2001"])
async def test_summary_http_boundaries_preserve_text_and_log_privacy(served, arguments, expected, caplog, capsys):
    base, h = served
    async with client(base, started_at="2026-10-01T09:58:00+05:30") as c:
        result = await c.call_tool("record_call_summary", {
            "intent": "GENERAL_INFO", "outcome": "RESOLVED_BY_AGENT", **arguments}, raise_on_error=False)
    captured = capsys.readouterr()
    logs = caplog.text + captured.out + captured.err
    assert all(marker not in logs for marker in ("NAME42", "9000000123", "SYMPTOM42", "Lakshmi", "ಜ್ವರ", "बुखार"))
    writes = [r for r in h.requests if r.url.path.endswith("/call-summaries")]
    if expected == "protocol":
        assert result.is_error and writes == []
    elif expected == "invalid":
        assert result.structured_content == {"outcome": "INVALID_REQUEST", "fields": ["summaryText"]}
        assert writes == []
    else:
        assert result.structured_content == {"outcome": "SAVED"}
        assert len(writes) == 1 and json.loads(writes[0].content)["summaryText"] == arguments["summaryText"]
