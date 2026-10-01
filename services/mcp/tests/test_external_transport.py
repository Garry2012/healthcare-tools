"""Deployed-transport release gate (marker `external`): the MCP adapter as the voice platform reaches it,
over real streamable HTTP with the real bearers. Verifies the layer the direct-client tests cannot:
authentication, the conversational/lifecycle split, header forwarding and read-only tool calls on the
deployment. It never writes an appointment or a summary.

  MCP_E2E_URL                 https://<adapter host>/mcp/
  MCP_E2E_BEARER              the gateway bearer
  MCP_E2E_LIFECYCLE_BEARER    the lifecycle bearer (optional: when absent the lifecycle view is reported BLOCKED)
  MCP_E2E_DEPARTMENT          department name present in the tenant (default General Medicine)
"""

from __future__ import annotations

import os
import runpy
import uuid
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from . import harness

pytestmark = pytest.mark.external
ROOT = Path(__file__).resolve().parents[3]


def required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        pytest.fail(f"BLOCKED: {name} is not set; the deployed-transport gate was not verified")
    return value


async def test_release_smoke_against_the_deployed_adapter():
    url, bearer = required("MCP_E2E_URL"), required("MCP_E2E_BEARER")
    lifecycle = os.environ.get("MCP_E2E_LIFECYCLE_BEARER") or None
    smoke = runpy.run_path(str(ROOT / "deploy/azure/smoke.py"))
    await smoke["smoke"](url, bearer, lifecycle, "en", os.environ.get("MCP_E2E_DEPARTMENT", "General Medicine"))
    if lifecycle is None:
        pytest.fail("BLOCKED: MCP_E2E_LIFECYCLE_BEARER not set; conversational checks passed, lifecycle unverified")


async def test_trusted_headers_reach_the_deployed_adapter():
    """A LIST with a verified caller must be answered for that caller (FOUND/NOT_FOUND), not IDENTITY_UNAVAILABLE,
    proving X-Caller-Number/X-Caller-Verification survive the transport; without them it must be refused."""
    url, bearer = required("MCP_E2E_URL"), required("MCP_E2E_BEARER")
    with_identity = {"Authorization": f"Bearer {bearer}", **harness.headers(call_id=f"gate-{uuid.uuid4().hex[:8]}")}
    async with Client(StreamableHttpTransport(url, headers=with_identity)) as c:
        listed = (await c.call_tool("manage_booking", {"action": "LIST"})).structured_content
    assert listed["outcome"] in ("FOUND", "NOT_FOUND", "COULD_NOT_CHECK"), listed
    assert listed["outcome"] != "IDENTITY_UNAVAILABLE"
    without = {"Authorization": f"Bearer {bearer}", "X-Call-Id": f"gate-{uuid.uuid4().hex[:8]}"}
    async with Client(StreamableHttpTransport(url, headers=without)) as c:
        refused = (await c.call_tool("manage_booking", {"action": "LIST"})).structured_content
    assert refused["outcome"] == "IDENTITY_UNAVAILABLE"
