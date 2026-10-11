"""Release tooling: the read-only smoke must fail on unavailable dependencies, missing auth, failure
envelopes, a wrong tool set , and must never write; gateway registration
names the three tools, forwards every trusted header and detects schema drift."""

from __future__ import annotations

import runpy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from frontdesk_mcp.context import PASSTHROUGH_HEADERS
from frontdesk_mcp.tools import TOOL_NAMES

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
async def test_http_checks_require_readiness_dependency_health_and_auth(ready, deps, auth, ok, monkeypatch):
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


@pytest.mark.parametrize("missing", ["record_call_summary", "manage_booking", "get_doctor_availability"])
async def test_smoke_requires_all_three_tools(missing):
    from fastmcp import Client, FastMCP

    remote = FastMCP("incomplete-remote")
    for name in TOOL_NAMES:
        if name != missing:
            remote.tool(name=name)(lambda: {"outcome": "NO_ANSWER"})
    async with Client(remote) as client:
        with pytest.raises(RuntimeError, match="tool set"):
            await SMOKE["check_tools"](client, "General Medicine")


@pytest.mark.parametrize("hours_body", [
    {"outcome": "WORKING_HOURS"},
    {"outcome": "HANDOFF_REQUIRED", "detail": "ON_CALL_DOCTOR", "complete": True, "nextStep": "TRANSFER_DESK"},
])
async def test_smoke_probes_working_hours_and_accepts_a_closed_session(hours_body):
    from fastmcp import Client, FastMCP
    remote = FastMCP("read-only-policy-probe")
    purposes = []

    @remote.tool()
    def get_doctor_availability(departmentName: str, date: str | None = None,  # noqa: N803
                                purpose: str = "AVAILABILITY") -> dict:
        purposes.append(purpose)
        return hours_body if purpose == "WORKING_HOURS" else {"outcome": "NOT_AVAILABLE"}

    for name in ("manage_booking", "record_call_summary"):
        remote.tool(name=name)(lambda: pytest.fail("smoke wrote data"))
    async with Client(remote) as client:
        await SMOKE["check_tools"](client, "General Medicine")
    assert purposes == ["AVAILABILITY", "WORKING_HOURS"]


@pytest.mark.parametrize("outcome", ["DOCTORS_MATCHED", "UNKNOWN_OUTCOME"])
async def test_smoke_accepts_slot_matches_but_not_unknown_outcomes(outcome):
    from fastmcp import Client, FastMCP

    remote = FastMCP("slot-department-smoke")

    @remote.tool()
    def get_doctor_availability(departmentName: str, date: str | None = None,  # noqa: N803
                                purpose: str = "AVAILABILITY") -> dict:
        assert departmentName == "General Medicine"
        return {"outcome": "WORKING_HOURS" if purpose == "WORKING_HOURS" else outcome}

    for name in ("manage_booking", "record_call_summary"):
        remote.tool(name=name)(lambda: pytest.fail("smoke wrote data"))
    async with Client(remote) as client:
        if outcome == "DOCTORS_MATCHED":
            await SMOKE["check_tools"](client, "General Medicine")
        else:
            with pytest.raises(RuntimeError, match="read-only smoke"):
                await SMOKE["check_tools"](client, "General Medicine")


@pytest.mark.parametrize("body", [
    {"outcome": "COULD_NOT_CHECK"}, {"outcome": "UNKNOWN_OUTCOME"}, {"outcome": "INVALID_REQUEST"},
    {"error": {"code": "UNAUTHORIZED"}}, None,
])
async def test_transport_success_does_not_hide_failures(body):
    client = AsyncMock()
    client.list_tools.return_value = _tools(TOOL_NAMES)
    client.call_tool.return_value = _result(body)
    with pytest.raises(RuntimeError, match="read-only smoke"):
        await SMOKE["check_tools"](client, "General Medicine")


def test_main_requires_https_and_never_leaks(monkeypatch, capsys):
    monkeypatch.setenv("MCP_URL", "http://adapter.example/mcp/")
    monkeypatch.setenv("MCP_BEARER_TOKEN", "secret-must-not-be-printed")
    assert SMOKE["main"]() == 1
    monkeypatch.setenv("MCP_URL", "https://adapter.example/mcp/")

    async def failing_smoke(*args, **kwargs):
        raise RuntimeError("secret-must-not-be-printed")

    monkeypatch.setitem(SMOKE["main"].__globals__, "smoke", failing_smoke)
    assert SMOKE["main"]() == 1
    captured = capsys.readouterr()
    assert "smoke test failed" in captured.err and "secret-must-not-be-printed" not in captured.out + captured.err


def test_registration_names_three_tools_and_forwards_every_trusted_header(monkeypatch):
    monkeypatch.setenv("MCP_PUBLIC_URL", "https://mcp.example/mcp/")
    monkeypatch.setenv("MCP_BEARER_TOKEN", "gateway-secret")
    monkeypatch.setenv("DOMAIN_PACK", "healthcare")
    body = REGISTER["payload"](SimpleNamespace(name="frontdesk-demo-hospital", visibility="private"))
    assert body["passthroughHeaders"] == ["X-Call-Id", "X-Caller-Number", "X-Caller-Verification",
                                          "X-Operation-Id", "X-Call-Started-At"]
    assert tuple(REGISTER["TOOLS"]) == TOOL_NAMES
    assert sorted(body["passthroughHeaders"]) == sorted(PASSTHROUGH_HEADERS)
    assert body["transport"] == "STREAMABLEHTTP" and body["authType"] == "bearer"
    assert REGISTER["redacted"](body)["authToken"] == "***"
    assert "gateway-secret" not in str(REGISTER["redacted"](body))


def test_schema_drift_between_server_and_gateway_is_detected():
    served = [{"name": "get_doctor_availability", "inputSchema": {"properties": {"date": {}}}},
              {"name": "manage_booking", "inputSchema": {"properties": {"action": {}}}},
              {"name": "record_call_summary", "inputSchema": {"properties": {"summaryText": {}}}}]
    gateway_ok = [{"name": "frontdesk-demo-hospital-get-doctor-availability",
                   "input_schema": {"properties": {"date": {}}}},
                  {"name": "frontdesk-demo-hospital-manage-booking", "input_schema": {"properties": {"action": {}}}},
                  {"name": "frontdesk-demo-hospital-record-call-summary",
                   "input_schema": {"properties": {"summaryText": {}}}}]
    assert REGISTER["drift"](served, gateway_ok, "frontdesk-demo-hospital") == []
    stale = [{**t, "input_schema": {"properties": {"utterance": {}}}} if "availability" in t["name"] else t
             for t in gateway_ok]
    problems = REGISTER["drift"](served, stale, "frontdesk-demo-hospital")
    assert problems and "get_doctor_availability" in problems[0]
    missing = REGISTER["drift"](served, gateway_ok[:2], "frontdesk-demo-hospital")
    assert any("record_call_summary" in p for p in missing)
    extra = REGISTER["drift"](served, [*gateway_ok, {"name": "frontdesk-demo-hospital-find-availability",
                                                     "input_schema": {}}], "frontdesk-demo-hospital")
    assert any("find-availability" in p for p in extra)


# ------------------------------------------------------------------ architect review AR-05


def _profile_dir(tmp_path, ops_base_url: str) -> str:
    """A test-only profile, so the dry runs never depend on the committed live profile's values."""
    (tmp_path / "test.env").write_text(f"""PROFILE=test
OPS_BASE_URL={ops_base_url}
OPS_E2E_MODE=live
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
    for name in ("mcp-token", "ops-client-id", "ops-client-secret"):
        assert f"{name}=keyvaultref:" in secrets_line, name
    assert "mcp-lifecycle-token" not in log and "MCP_LIFECYCLE" not in log
    assert "SMOKE_EXPECT_KNOWLEDGE" not in log
    assert "az containerapp secret remove" not in log
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


@pytest.fixture
async def h(make_settings):
    from . import harness

    instance = harness.build(make_settings())
    try:
        yield instance
    finally:
        await instance.aclose()


@pytest.mark.parametrize("problem", ["none", "missing", "maxLength", "required"])
async def test_gateway_verifies_three_tools_and_refreshes_missing_discovery(h, monkeypatch, problem):
    import asyncio
    import copy

    from frontdesk_mcp.server import create_app

    from .conftest import serving

    app = create_app(h.settings, ops_transport=h.ops.http._transport, clock=h.clock)
    served = []
    requests = []

    def gateway(request):
        requests.append((request.method, request.url.path))
        if request.url.path.endswith("/tools/refresh"):
            return httpx.Response(200, json={})
        discovered = served if len(requests) > 1 else [t for t in served if t["name"] != "record_call_summary"]
        if problem == "missing":
            discovered = [t for t in discovered if t["name"] != "record_call_summary"]
        if problem in {"maxLength", "required"}:
            discovered = copy.deepcopy(discovered)
            for tool in discovered:
                if tool["name"] == "record_call_summary":
                    if problem == "maxLength":
                        tool["inputSchema"]["properties"]["summaryText"]["maxLength"] = 2000
                    else:
                        tool["inputSchema"]["required"].remove("summaryText")
        return httpx.Response(200, json={"tools": [
            {"name": f"frontdesk-demo-hospital-{t['name']}", "inputSchema": t["inputSchema"]} for t in discovered]})

    async with serving(app) as base:
        monkeypatch.setenv("MCP_PUBLIC_URL", f"{base}/mcp/")
        monkeypatch.setenv("MCP_BEARER_TOKEN", "mcp-token")
        served = await REGISTER["served_tools"](f"{base}/mcp/", "mcp-token")
        with httpx.Client(base_url="https://gateway.example", transport=httpx.MockTransport(gateway)) as client:
            if problem != "none":
                with pytest.raises(SystemExit, match="record_call_summary:"):
                    await asyncio.to_thread(REGISTER["verify"], client, "gateway-id", "frontdesk-demo-hospital")
            else:
                await asyncio.to_thread(REGISTER["verify"], client, "gateway-id", "frontdesk-demo-hospital")
    assert requests == [("GET", "/v1/tools"), ("POST", "/v1/gateways/gateway-id/tools/refresh"),
                        ("GET", "/v1/tools")]
    assert h.ops_state.summaries == {} and h.ops_state.appointments == {}


def test_deploy_does_not_configure_or_remove_retired_knowledge_secrets(tmp_path):
    result = _dry_run(tmp_path, DEPLOY_ASSUME_EXISTING="1")
    assert result.returncode == 0, result.stderr[-2000:]
    assert "az containerapp update" in result.stderr
    assert "knowledge-token" not in result.stderr
    assert "KNOWLEDGE_" not in result.stderr
    assert "az containerapp secret remove" not in result.stderr


@pytest.mark.parametrize("body", [[], "bad", None, {"operational": []},
                                  {"operational": {"status": "invalid"}}])
async def test_smoke_rejects_malformed_dependencies_without_attribute_error(body):
    def owner(request):
        if request.url.path == "/dependencies":
            return httpx.Response(200, json=body) if body is not None else httpx.Response(200, content=b"null")
        if request.url.path == "/mcp/":
            return httpx.Response(401)
        return httpx.Response(200, json={"status": "ready" if request.url.path == "/ready" else "ok"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(owner)) as http:
        with pytest.raises(RuntimeError):
            await SMOKE["check_http"](http, "https://adapter.example")




def test_profile_exports_no_retired_knowledge_settings(tmp_path):
    import os
    import subprocess

    (tmp_path / "fixture.env").write_text("OPS_BASE_URL=https://ops.example\n")
    result = subprocess.run([str(DEPLOY.parent / "scripts/env.sh"), "fixture"], capture_output=True,
                            text=True, env={**os.environ, "DEPLOY_PROFILE_DIR": str(tmp_path)})
    assert result.returncode == 0
    assert "export OPS_E2E_BASE_URL=https://ops.example" in result.stdout
    assert "KNOWLEDGE_" not in result.stdout


@pytest.mark.parametrize("probe", ["AVAILABILITY", "WORKING_HOURS"])
@pytest.mark.parametrize("case", ["valid", "incomplete", "missing_detail", "other_detail", "false_complete",
                                  "missing_complete", "numeric_complete", "string_complete", "wrong_step",
                                  "unknown", "tool_error", "error_envelope", "not_dict"])
async def test_smoke_handoff_requires_complete_oncall_result(probe, case):
    from fastmcp import Client, FastMCP
    from fastmcp.exceptions import ToolError

    remote = FastMCP("handoff-smoke")
    body = {"outcome": "HANDOFF_REQUIRED", "detail": "ON_CALL_DOCTOR",
            "complete": True, "nextStep": "TRANSFER_DESK"}
    changes = {"incomplete": {"detail": "SEARCH_INCOMPLETE"}, "other_detail": {"detail": "OTHER"},
               "false_complete": {"complete": False}, "numeric_complete": {"complete": 1},
               "string_complete": {"complete": "true"}, "wrong_step": {"nextStep": "ASK_TO_REPHRASE"},
               "unknown": {"outcome": "UNKNOWN_OUTCOME"}, "error_envelope": {"error": {"code": "API_ERROR"}}}
    body.update(changes.get(case, {}))
    if case.startswith("missing_"):
        del body[case.removeprefix("missing_")]

    @remote.tool()
    def get_doctor_availability(departmentName: str, date: str | None = None,  # noqa: N803
                                purpose: str = "AVAILABILITY"):
        assert departmentName == "General Medicine"
        if purpose != probe:
            return {"outcome": "WORKING_HOURS" if purpose == "WORKING_HOURS" else "DOCTORS_MATCHED"}
        if case == "tool_error":
            raise ToolError("fixture error")
        return "malformed" if case == "not_dict" else body

    for name in ("manage_booking", "record_call_summary"):
        remote.tool(name=name)(lambda: pytest.fail("smoke must not write"))
    async with Client(remote) as client:
        if case == "valid":
            await SMOKE["check_tools"](client, "General Medicine")
        else:
            with pytest.raises(RuntimeError, match="read-only smoke"):
                await SMOKE["check_tools"](client, "General Medicine")


@pytest.mark.parametrize("failure", ["timeout", "auth", "server"])
def test_smoke_cli_refuses_transport_failures(monkeypatch, capsys, failure):
    monkeypatch.setenv("MCP_URL", "https://adapter.example/mcp/")
    monkeypatch.setenv("MCP_BEARER_TOKEN", "secret-not-printed")

    async def transport(_self, request):
        if failure == "timeout":
            raise httpx.ReadTimeout("secret-not-printed", request=request)
        if request.url.path == "/mcp/":
            return httpx.Response(401 if failure == "auth" or "authorization" not in request.headers else 503,
                                  request=request)
        if request.url.path == "/dependencies":
            return httpx.Response(200, json={"operational": {"status": "ok"}}, request=request)
        return httpx.Response(200, json={"status": "ready" if request.url.path == "/ready" else "ok"},
                              request=request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", transport)
    assert SMOKE["main"]() == 1
    output = capsys.readouterr()
    assert "smoke test failed" in output.err and "Deployment smoke passed" not in output.out
    assert "secret-not-printed" not in output.err + output.out


async def test_smoke_rejects_removed_fourth_tool():
    client = AsyncMock()
    client.list_tools.return_value = _tools([
        "get_doctor_availability", "manage_booking", "record_call_summary", "search_knowledge"])
    with pytest.raises(RuntimeError, match="tool set"):
        await SMOKE["check_tools"](client, "General Medicine")
    client.call_tool.assert_not_called()


def test_registration_ignores_other_registration_but_rejects_removed_frontdesk_tool():
    served = [{"name": name, "inputSchema": {}} for name in (
        "get_doctor_availability", "manage_booking", "record_call_summary")]
    ours = [{"name": "frontdesk-demo-hospital-" + tool["name"].replace("_", "-"), "input_schema": {}}
            for tool in served]
    unrelated = {"name": "stratum-search_knowledge", "input_schema": {"properties": {"question": {}}}}
    assert REGISTER["drift"](served, [*ours, unrelated], "frontdesk-demo-hospital") == []
    removed = {"name": "frontdesk-demo-hospital-search-knowledge", "input_schema": {}}
    drift = REGISTER["drift"](served, [*ours, unrelated, removed], "frontdesk-demo-hospital")
    assert len(drift) == 1
    assert "adapter no longer serves" in drift[0]


def test_smoke_main_needs_no_language(monkeypatch, capsys):
    monkeypatch.setenv("MCP_URL", "https://adapter.example/mcp/")
    monkeypatch.setenv("MCP_BEARER_TOKEN", "secret-not-printed")
    monkeypatch.delenv("SMOKE_LANGUAGE", raising=False)
    received = []

    async def fake_smoke(*args):
        received.append(args)

    monkeypatch.setitem(SMOKE["main"].__globals__, "smoke", fake_smoke)
    assert SMOKE["main"]() == 0
    assert received == [("https://adapter.example/mcp/", "secret-not-printed", "General Medicine")]
    captured = capsys.readouterr()
    assert "secret-not-printed" not in captured.out + captured.err
