"""Release tooling: the read-only smoke must fail on unavailable dependencies, missing auth, failure
envelopes, a wrong tool set or a leaky lifecycle boundary, and must never write; gateway registration
names the four tools, forwards every trusted header and detects schema drift."""

from __future__ import annotations

import runpy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from frontdesk_mcp.context import PASSTHROUGH_HEADERS
from frontdesk_mcp.tools import CONVERSATIONAL_TOOLS, LIFECYCLE_TOOLS, TOOL_NAMES

DEPLOY = Path(__file__).resolve().parents[3] / "deploy"
SMOKE = runpy.run_path(str(DEPLOY / "azure/smoke.py"))
REGISTER = runpy.run_path(str(DEPLOY / "contextforge/register.py"))


def _tools(names):
    return [SimpleNamespace(name=name) for name in names]


def _result(body, is_error=False):
    return SimpleNamespace(is_error=is_error, structured_content=body, content=[SimpleNamespace(text="refused")])


@pytest.mark.parametrize("ready,deps,auth,ok", [
    (200, 200, 401, True), (503, 200, 401, False), (200, 503, 401, False), (200, 200, 200, False),
])
async def test_http_checks_require_readiness_dependency_health_and_auth(ready, deps, auth, ok):
    def handle(request):
        path = request.url.path
        if path == "/mcp/":
            assert "authorization" not in request.headers
            return httpx.Response(auth, json={})
        if path == "/ready":
            return httpx.Response(ready, json={"status": "ready" if ready == 200 else "starting"})
        if path == "/dependencies":
            return httpx.Response(deps, json={"operational": {"status": "ok" if deps == 200 else "unavailable"}})
        return httpx.Response(200, json={"status": "ok"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        if ok:
            await SMOKE["check_http"](http, "https://adapter.example")
        else:
            with pytest.raises((RuntimeError, httpx.HTTPStatusError)):
                await SMOKE["check_http"](http, "https://adapter.example")


async def test_conversational_tool_set_must_be_exactly_three_and_the_summary_tool_hidden():
    client = AsyncMock()
    client.list_tools.return_value = _tools(TOOL_NAMES)  # the summary tool leaked into the conversational view
    with pytest.raises(RuntimeError, match="tool set"):
        await SMOKE["check_tools"](client, "en", "General Medicine")
    client.list_tools.return_value = _tools(CONVERSATIONAL_TOOLS[:2])
    with pytest.raises(RuntimeError, match="tool set"):
        await SMOKE["check_tools"](client, "en", "General Medicine")


@pytest.mark.parametrize("body", [
    {"outcome": "COULD_NOT_CHECK"}, {"outcome": "ROUTING_UNAVAILABLE"}, {"outcome": "INVALID_REQUEST"},
    {"error": {"code": "UNAUTHORIZED"}}, None,
])
async def test_transport_success_does_not_hide_failures(body):
    client = AsyncMock()
    client.list_tools.return_value = _tools(CONVERSATIONAL_TOOLS)
    client.call_tool.return_value = _result(body)
    with pytest.raises(RuntimeError, match="read-only smoke"):
        await SMOKE["check_tools"](client, "en", "General Medicine")


async def test_smoke_reads_only_and_accepts_honest_empty_outcomes():
    client = AsyncMock()
    client.list_tools.return_value = _tools(CONVERSATIONAL_TOOLS)
    client.call_tool.side_effect = [_result({"outcome": "CALLBACK_REQUIRED"}), _result({"outcome": "NO_ANSWER"})]
    await SMOKE["check_tools"](client, "hi", "General Medicine")
    called = [call.args[0] for call in client.call_tool.call_args_list]
    assert called == ["get_doctor_availability", "search_knowledge"]
    assert "manage_booking" not in called and "record_call_summary" not in called
    assert client.call_tool.call_args_list[1].args[1]["language"] == "hi"


async def test_lifecycle_boundary_check_requires_server_side_refusal():
    conversational, lifecycle = AsyncMock(), AsyncMock()
    conversational.call_tool.return_value = _result({"outcome": "STORED"})  # the server let a gateway bearer finalize
    lifecycle.list_tools.return_value = _tools(LIFECYCLE_TOOLS)
    with pytest.raises(RuntimeError, match="lifecycle"):
        await SMOKE["check_lifecycle_boundary"](conversational, lifecycle)
    conversational.call_tool.return_value = _result(None, is_error=True)
    lifecycle.list_tools.return_value = _tools(TOOL_NAMES)  # lifecycle bearer sees in-call tools
    with pytest.raises(RuntimeError, match="lifecycle"):
        await SMOKE["check_lifecycle_boundary"](conversational, lifecycle)
    lifecycle.list_tools.return_value = _tools(LIFECYCLE_TOOLS)
    await SMOKE["check_lifecycle_boundary"](conversational, lifecycle)
    assert not lifecycle.call_tool.called  # never writes a summary as a smoke test


def test_main_requires_https_and_never_leaks(monkeypatch, capsys):
    monkeypatch.setenv("MCP_URL", "http://adapter.example/mcp/")
    monkeypatch.setenv("MCP_BEARER_TOKEN", "secret-must-not-be-printed")
    monkeypatch.setenv("SMOKE_LANGUAGE", "en")
    assert SMOKE["main"]() == 1
    monkeypatch.setenv("MCP_URL", "https://adapter.example/mcp/")

    async def failing_smoke(*args, **kwargs):
        raise RuntimeError("secret-must-not-be-printed")

    monkeypatch.setitem(SMOKE["main"].__globals__, "smoke", failing_smoke)
    assert SMOKE["main"]() == 1
    captured = capsys.readouterr()
    assert "smoke test failed" in captured.err and "secret-must-not-be-printed" not in captured.out + captured.err


def test_registration_names_four_tools_and_forwards_every_trusted_header(monkeypatch):
    monkeypatch.setenv("MCP_PUBLIC_URL", "https://mcp.example/mcp/")
    monkeypatch.setenv("MCP_BEARER_TOKEN", "gateway-secret")
    monkeypatch.setenv("DOMAIN_PACK", "healthcare")
    body = REGISTER["payload"](SimpleNamespace(name="frontdesk-demo-hospital", visibility="private"))
    assert tuple(REGISTER["TOOLS"]) == TOOL_NAMES
    assert sorted(body["passthrough_headers"]) == sorted(PASSTHROUGH_HEADERS)
    assert body["transport"] == "STREAMABLEHTTP" and body["auth_type"] == "bearer"
    assert REGISTER["redacted"](body)["auth_token"] == "***"
    assert "gateway-secret" not in str(REGISTER["redacted"](body))


def test_schema_drift_between_server_and_gateway_is_detected():
    served = [{"name": "get_doctor_availability", "inputSchema": {"properties": {"date": {}}}},
              {"name": "manage_booking", "inputSchema": {"properties": {"action": {}}}},
              {"name": "search_knowledge", "inputSchema": {"properties": {"question": {}}}}]
    gateway_ok = [{"name": "frontdesk-demo-hospital-get-doctor-availability",
                   "input_schema": {"properties": {"date": {}}}},
                  {"name": "frontdesk-demo-hospital-manage-booking", "input_schema": {"properties": {"action": {}}}},
                  {"name": "frontdesk-demo-hospital-search-knowledge",
                   "input_schema": {"properties": {"question": {}}}}]
    assert REGISTER["drift"](served, gateway_ok, "frontdesk-demo-hospital") == []
    stale = [{**t, "input_schema": {"properties": {"utterance": {}}}} if "availability" in t["name"] else t
             for t in gateway_ok]
    problems = REGISTER["drift"](served, stale, "frontdesk-demo-hospital")
    assert problems and "get_doctor_availability" in problems[0]
    missing = REGISTER["drift"](served, gateway_ok[:2], "frontdesk-demo-hospital")
    assert any("search_knowledge" in p for p in missing)
    extra = REGISTER["drift"](served, [*gateway_ok, {"name": "frontdesk-demo-hospital-find-availability",
                                                     "input_schema": {}}], "frontdesk-demo-hospital")
    assert any("find-availability" in p for p in extra)
