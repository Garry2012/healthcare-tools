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
    assert sorted(body["passthroughHeaders"]) == sorted(PASSTHROUGH_HEADERS)
    assert body["transport"] == "STREAMABLEHTTP" and body["authType"] == "bearer"
    assert REGISTER["redacted"](body)["authToken"] == "***"
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


# ------------------------------------------------------------------ architect review AR-05


def _profile_dir(tmp_path, ops_base_url: str) -> str:
    """A test-only profile, so the dry runs never depend on the committed live profile's values."""
    (tmp_path / "test.env").write_text(f"""PROFILE=test
OPS_BASE_URL={ops_base_url}
OPS_E2E_MODE=live
KNOWLEDGE_BASE_URL=https://kb.example
AZ_SUBSCRIPTION_ID=4e1c081a-9a6a-4e16-9da2-90217c22378b
AZ_RESOURCE_GROUP=healthcare-rg
AZ_CONTAINERAPPS_ENV=cae-frontdesk-demo-hospital
AZ_LOG_WORKSPACE=law-frontdesk-demo-hospital
AZ_ACR=acrfd399536
AZ_KEYVAULT=kv-fd-demo-hospi-0574c1
AZ_IDENTITY=id-frontdesk-demo-hospital
""")
    return str(tmp_path)


def _dry_run(tmp_path, *args, ops_base_url="https://ops.example/api/v1", **env_extra):
    import os
    import subprocess

    env = {**os.environ, "DEPLOY_PROFILE_DIR": _profile_dir(tmp_path, ops_base_url), **env_extra}
    return subprocess.run([str(DEPLOY / "azure/deploy.sh"), str(DEPLOY.parent / "rollouts/demo-hospital"), "--profile",
                           "test", "--dry-run", *args], capture_output=True, text=True, env=env, check=False,
                          cwd=DEPLOY.parent)


def test_upgrading_an_existing_app_attaches_the_new_secrets_before_switching_env(tmp_path):
    """AR-05: the live app has only agent-token/mcp-token; an update with new secretref names must first attach
    the Key Vault references (and identity/registry access), else the revision fails to start."""
    out = _dry_run(tmp_path, DEPLOY_ASSUME_EXISTING="1")
    log = out.stderr
    assert out.returncode == 0, log[-2000:]
    secret_set = log.index("az containerapp secret set")
    identity = log.index("az containerapp identity assign")
    registry = log.index("az containerapp registry set")
    update = log.index("az containerapp update -g")
    assert secret_set < update and identity < update and registry < update, "attach secrets/identity before env"
    secrets_line = [line for line in log.splitlines() if "az containerapp secret set" in line][0]
    for name in ("mcp-token", "mcp-lifecycle-token", "ops-client-id", "ops-client-secret", "knowledge-token"):
        assert f"{name}=keyvaultref:" in secrets_line, name
    assert "az containerapp create" not in log  # the existing app is upgraded, not recreated


def test_deployment_targets_only_the_profiles_resource_group_and_never_creates_one(tmp_path):
    """Follow-up 3: the documented command cannot silently create or use rg-frontdesk-demo-hospital."""
    import subprocess

    out = _dry_run(tmp_path)
    assert out.returncode == 0, out.stderr[-1500:]
    assert "rg-frontdesk-demo-hospital" not in out.stderr and "az group create" not in out.stderr
    assert "-g healthcare-rg" in out.stderr
    for created in ("az acr create", "az keyvault create", "az identity create", "az containerapp env create",
                    "log-analytics workspace create"):
        assert created not in out.stderr, created  # shared infrastructure is required, never created
    inherited = _dry_run(tmp_path, OPS_BASE_URL="https://stale.example/api/v1", AZ_RESOURCE_GROUP="rg-stale")
    assert "stale" not in inherited.stderr  # the profile replaces inherited values
    mismatch = _dry_run(tmp_path, DEPLOY_DRY_SUBSCRIPTION="00000000-0000-0000-0000-000000000000")
    assert mismatch.returncode != 0 and "subscription" in mismatch.stderr
    without_profile = subprocess.run([str(DEPLOY / "azure/deploy.sh"), str(DEPLOY.parent / "rollouts/demo-hospital"),
                                      "--dry-run"], capture_output=True, text=True, check=False, cwd=DEPLOY.parent)
    assert without_profile.returncode != 0 and "--profile" in without_profile.stderr


def test_a_profile_with_a_blank_base_url_is_refused_and_mock_cannot_deploy(tmp_path):
    import os
    import subprocess

    env_sh = DEPLOY.parent / "scripts/env.sh"
    blank_dir = tmp_path / "blank"
    blank_dir.mkdir()
    (blank_dir / "live.env").write_text("PROFILE=live\nOPS_BASE_URL=\nAZ_RESOURCE_GROUP=healthcare-rg\n")
    blank_env = {**os.environ, "DEPLOY_PROFILE_DIR": str(blank_dir)}
    live = subprocess.run([str(env_sh), "live"], capture_output=True, text=True, check=False, env=blank_env)
    assert live.returncode == 3 and live.stdout == "" and "awaiting" in live.stderr
    aborted = subprocess.run([str(DEPLOY / "azure/deploy.sh"), str(DEPLOY.parent / "rollouts/demo-hospital"),
                              "--profile", "live", "--dry-run"], capture_output=True, text=True, check=False,
                             cwd=DEPLOY.parent, env={**blank_env, "OPS_BASE_URL": "https://inherited.example/api/v1"})
    assert aborted.returncode != 0 and "az containerapp" not in aborted.stderr  # eval must not swallow the refusal
    mock = subprocess.run([str(env_sh), "mock"], capture_output=True, text=True, check=False)
    assert mock.returncode == 0 and "healthcare-contract-mock" in mock.stdout and "OPS_E2E_MODE=mock" in mock.stdout
    assert "AZ_RESOURCE_GROUP=healthcare-rg" in mock.stdout and "4e1c081a-9a6a-4e16-9da2-90217c22378b" in mock.stdout
    refused = _dry_run(tmp_path, ops_base_url="https://healthcare-contract-mock.example")
    assert refused.returncode != 0 and "stub/mock" in refused.stderr


def test_the_committed_live_profile_names_manoj_base_and_the_canary_app():
    import subprocess

    live = subprocess.run([str(DEPLOY.parent / "scripts/env.sh"), "live"], capture_output=True, text=True, check=False)
    assert live.returncode == 0
    base = "https://healthcare-api.icytree-6543aaa9.centralindia.azurecontainerapps.io/api/v1"
    assert f"OPS_BASE_URL={base}" in live.stdout
    assert "OPS_E2E_MODE=live" in live.stdout and "AZ_MCP_APP=mcp-demo-hospital-canary" in live.stdout
    assert "AZ_RESOURCE_GROUP=healthcare-rg" in live.stdout


def test_gateway_refresh_uses_the_deployed_contextforge_api(monkeypatch):
    """The deployed 1.0.11 API refreshes at /tools/refresh, not /refresh."""
    served = [{"name": name, "inputSchema": {}} for name in CONVERSATIONAL_TOOLS]

    async def discover(*_):
        return served

    monkeypatch.setenv("MCP_PUBLIC_URL", "https://adapter.example/mcp/")
    monkeypatch.setenv("MCP_BEARER_TOKEN", "gateway-secret")
    monkeypatch.setitem(REGISTER["verify"].__globals__, "served_tools", discover)
    requests = []

    def gateway(request):
        requests.append((request.method, request.url.path))
        if request.url.path.endswith("/tools/refresh"):
            return httpx.Response(200, json={})
        tools = [] if len(requests) == 1 else [
            {"name": f"frontdesk-demo-hospital-{t['name']}", "inputSchema": {}} for t in served]
        return httpx.Response(200, json={"tools": tools})

    with httpx.Client(base_url="https://gateway.example", transport=httpx.MockTransport(gateway)) as client:
        REGISTER["verify"](client, "gateway-id", "frontdesk-demo-hospital")
    assert requests == [("GET", "/v1/tools"), ("POST", "/v1/gateways/gateway-id/tools/refresh"),
                        ("GET", "/v1/tools")]
