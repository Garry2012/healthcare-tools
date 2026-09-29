"""A release must fail on unavailable upstreams, missing auth or MCP failure envelopes."""

from __future__ import annotations

import runpy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

SMOKE = runpy.run_path(str(Path(__file__).resolve().parents[3] / "deploy/azure/smoke.py"))


@pytest.mark.parametrize("ready_status,auth_status", [(200, 401), (503, 401), (200, 200)])
async def test_http_readiness_and_auth_are_both_required(ready_status, auth_status):
    def handle(request):
        if request.url.path == "/mcp/":
            assert "authorization" not in request.headers
            return httpx.Response(auth_status, json={})
        if request.url.path == "/ready":
            return httpx.Response(ready_status, json={"status": "ready"})
        return httpx.Response(200, json={"status": "ok"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        if (ready_status, auth_status) == (200, 401):
            await SMOKE["check_http"](http, "https://adapter.example")
        else:
            with pytest.raises((RuntimeError, httpx.HTTPStatusError)):
                await SMOKE["check_http"](http, "https://adapter.example")


@pytest.mark.parametrize("body", [
    {"outcome": "COULD_NOT_CHECK"},
    {"error": {"code": "UNAUTHORIZED"}},
    None,
])
async def test_successful_mcp_transport_does_not_hide_api_failures(body):
    client = AsyncMock()
    client.list_tools.return_value = [SimpleNamespace(name=name) for name in SMOKE["EXPECTED_TOOLS"]]
    client.call_tool.return_value = SimpleNamespace(is_error=False, structured_content=body)
    with pytest.raises(RuntimeError, match="read-only smoke"):
        await SMOKE["check_tools"](client, "en")


async def test_smoke_accepts_empty_data_without_writing_bookings():
    client = AsyncMock()
    client.list_tools.return_value = [SimpleNamespace(name=name) for name in SMOKE["EXPECTED_TOOLS"]]
    client.call_tool.side_effect = [
        SimpleNamespace(is_error=False, structured_content={"outcome": outcome})
        for outcome in ("NONE_AVAILABLE", "NO_ANSWER")
    ]
    await SMOKE["check_tools"](client, "hi")
    assert [call.args[0] for call in client.call_tool.call_args_list] == ["find_availability", "search_knowledge"]
    assert all(call.args[1]["language"] == "hi" for call in client.call_tool.call_args_list)


async def test_missing_tools_fail_the_release():
    client = AsyncMock()
    client.list_tools.return_value = []
    with pytest.raises(RuntimeError, match="tool set"):
        await SMOKE["check_tools"](client, "en")


def test_main_does_not_leak_exception_details(monkeypatch, capsys):
    monkeypatch.setenv("MCP_URL", "https://adapter.example/mcp/")
    monkeypatch.setenv("MCP_BEARER_TOKEN", "secret-must-not-be-printed")
    monkeypatch.setenv("SMOKE_LANGUAGE", "en")

    async def failing_smoke(*args):
        raise RuntimeError("secret-must-not-be-printed")

    monkeypatch.setitem(SMOKE["main"].__globals__, "smoke", failing_smoke)
    assert SMOKE["main"]() == 1
    captured = capsys.readouterr()
    assert "smoke test failed" in captured.err
    assert "secret-must-not-be-printed" not in captured.out + captured.err
