"""End to end with real processes over TCP: the stubs (`python -m frontdesk_stubs`) and the adapter
(`frontdesk-mcp serve`) as deployed, driven by the release smoke and by a full journey with trusted
headers. Marked e2e; runs in CI without any database or backend source."""

from __future__ import annotations

import contextlib
import os
import runpy
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from . import harness
from .conftest import free_port

pytestmark = pytest.mark.e2e
ROOT = Path(__file__).resolve().parents[3]


def _wait(url: str, proc: subprocess.Popen, seconds: float = 15) -> None:
    for _ in range(int(seconds / 0.1)):
        with contextlib.suppress(httpx.HTTPError):
            if httpx.get(url, timeout=1).status_code < 500:
                return
        if proc.poll() is not None:
            raise RuntimeError((proc.stderr.read() if proc.stderr else b"").decode())
        time.sleep(0.1)
    raise RuntimeError(f"{url} did not come up")


@pytest.fixture(scope="module")
def processes():
    ops_port, kb_port, mcp_port = free_port(), free_port(), free_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("OPS_", "KNOWLEDGE_", "MCP_", "TENANT_"))}
    stubs = subprocess.Popen(
        [sys.executable, "-m", "frontdesk_stubs", "--ops-port", str(ops_port), "--knowledge-port", str(kb_port),
         "--ops-prefix", "/api/v1", "--client-id", "mcp-e2e", "--client-secret", "e2e-secret",
         "--knowledge-bearer", "kb-e2e"],
        env={**env, "PYTHONPATH": "dev:src"}, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    mcp_env = {**env, "ENV": "test", "PROVIDER_ID": "demo-hospital", "DOMAIN_PACK": "healthcare",
               "TENANT_SUPPORTED_LANGUAGES": "en,kn,hi", "TENANT_TIMEZONE": "Asia/Kolkata",
               "TENANT_COUNTRY_CALLING_CODE": "91", "OPS_BASE_URL": f"http://127.0.0.1:{ops_port}/api/v1",
               "OPS_CLIENT_ID": "mcp-e2e", "OPS_CLIENT_SECRET": "e2e-secret",
               "KNOWLEDGE_BASE_URL": f"http://127.0.0.1:{kb_port}", "KNOWLEDGE_BEARER_TOKEN": "kb-e2e",
               "MCP_BEARER_TOKEN": "gateway-e2e", "MCP_LIFECYCLE_BEARER_TOKEN": "lifecycle-e2e",
               "HOST": "127.0.0.1", "PORT": str(mcp_port), "LOG_LEVEL": "WARNING"}
    mcp = subprocess.Popen([sys.executable, "-m", "frontdesk_mcp.cli", "serve"], env=mcp_env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        _wait(f"http://127.0.0.1:{ops_port}/api/v1/departments", stubs)
        _wait(f"http://127.0.0.1:{mcp_port}/health", mcp)
        yield {"mcp": f"http://127.0.0.1:{mcp_port}", "ops": f"http://127.0.0.1:{ops_port}/api/v1"}
    finally:
        for proc in (mcp, stubs):
            proc.terminate()
            proc.wait(timeout=10)


async def test_release_smoke_passes_against_real_processes(processes):
    smoke = runpy.run_path(str(ROOT / "deploy/azure/smoke.py"))
    await smoke["smoke"](f"{processes['mcp']}/mcp/", "gateway-e2e", "lifecycle-e2e", "en", "General Medicine")


async def test_journey_and_lifecycle_through_real_transport(processes):
    base = processes["mcp"]
    headers = {"Authorization": "Bearer gateway-e2e", **harness.headers(call_id="e2e-1", operation_id="op-e2e-1",
                                                                       turn="Dr Garima tomorrow please")}
    # The stub's board for a far future date is UNKNOWN unless scripted: script a confirmed session first.
    httpx.post(f"{processes['ops']}/__stub/scenario", json={"boards": {"2099-01-05": [
        {"doctorId": "doc_garima", "session": "Morning", "status": "NOT_CONFIRMED", "expectedTime": "09:00",
         "updatedMinutesAgo": 1}]}}, timeout=5).raise_for_status()
    async with Client(StreamableHttpTransport(f"{base}/mcp/", headers=headers)) as c:
        today = await c.call_tool("get_doctor_availability", {"doctorName": "garima", "date": "today"})
        assert today.structured_content["outcome"] in ("AVAILABILITY", "CALLBACK_REQUIRED")  # real weekday/board
        noted = (await c.call_tool("manage_booking", {
            "action": "CREATE", "patientName": "E2E Patient", "patientMobile": "9000000101", "doctorId": "doc_garima",
            "visitDate": "2099-01-05", "callerConfirmed": True})).structured_content
        assert noted["outcome"] == "NOTED"
        replay = (await c.call_tool("manage_booking", {
            "action": "CREATE", "patientName": "E2E Patient", "patientMobile": "9000000101", "doctorId": "doc_garima",
            "visitDate": "2099-01-05", "callerConfirmed": True})).structured_content
        assert replay["appointment"]["appointmentId"] == noted["appointment"]["appointmentId"]
        refused = await c.call_tool("record_call_summary", {"intent": "BOOKING", "outcome": "APPOINTMENT_NOTED",
                                                            "summaryText": "x"}, raise_on_error=False)
        assert refused.is_error
    lifecycle = {"Authorization": "Bearer lifecycle-e2e", **harness.headers(
        call_id="e2e-1", turn=None, started_at="2026-10-01T10:00:00+05:30", duration="120")}
    async with Client(StreamableHttpTransport(f"{base}/mcp/", headers=lifecycle)) as c:
        assert [t.name for t in await c.list_tools()] == ["record_call_summary"]
        stored = (await c.call_tool("record_call_summary", {
            "intent": "BOOKING", "outcome": "APPOINTMENT_NOTED", "appointmentId": noted["appointment"]["appointmentId"],
            "summaryText": "E2E journey."})).structured_content
        assert stored["outcome"] == "STORED"
        again = (await c.call_tool("record_call_summary", {
            "intent": "BOOKING", "outcome": "APPOINTMENT_NOTED", "appointmentId": noted["appointment"]["appointmentId"],
            "summaryText": "E2E journey."})).structured_content
        assert again["outcome"] == "REPLAYED" and again["summaryId"] == stored["summaryId"]
    state = httpx.get(f"{processes['ops']}/__stub/state").json()
    assert len(state["appointments"]) == 1 and len(state["summaries"]) == 1
