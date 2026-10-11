"""Read-only release gate against the deployed MCP adapter.

Checks local health/readiness, dependency status, that an unauthenticated request is refused, that the
gateway bearer sees exactly three tools, and that two read-only tool calls return honest,
non-failure outcomes through the real MCP transport. It never creates an appointment or a summary.
Credentials are environment-only; response bodies and exception details are not printed.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

import httpx
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import ClientError, FastMCPError
from mcp import McpError

TOOL_NAMES = {"get_doctor_availability", "manage_booking", "record_call_summary"}
AVAILABILITY_OK = {"AVAILABILITY", "CALLBACK_REQUIRED", "CLARIFICATION_NEEDED", "NOT_FOUND", "NOT_AVAILABLE",
                   "DOCTORS_MATCHED"}




async def check_http(http: httpx.AsyncClient, root: str) -> None:
    for path, expected in (("health", "ok"), ("ready", "ready")):
        response = await http.get(f"{root}/{path}")
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or body.get("status") != expected:
            raise RuntimeError(f"unexpected {path} response")
    dependencies = await http.get(f"{root}/dependencies", params={"refresh": "1"})
    if dependencies.status_code != 200:
        raise RuntimeError("operational dependency is not healthy")
    body = dependencies.json()
    if not isinstance(body, dict):
        raise RuntimeError("malformed dependencies response")
    operational = body.get("operational")
    if not isinstance(operational, dict) or operational.get("status") != "ok":
        raise RuntimeError("operational dependency is not healthy")
    response = await http.post(f"{root}/mcp/", json={})
    if response.status_code != 401:
        raise RuntimeError("MCP accepted an unauthenticated request")


async def check_tools(client: Client, language: str, department: str) -> None:
    names = {tool.name for tool in await client.list_tools()}
    if names != TOOL_NAMES:
        raise RuntimeError("unexpected MCP tool set")
    cases = (
        ("get_doctor_availability", {"date": "today", "departmentName": department}, AVAILABILITY_OK),
        ("get_doctor_availability", {"purpose": "WORKING_HOURS", "departmentName": department},
         {"WORKING_HOURS", "CLARIFICATION_NEEDED", "NOT_FOUND"}),
    )
    for name, arguments, outcomes in cases:
        result = await client.call_tool(name, arguments, raise_on_error=False)
        body = result.structured_content
        # MCP can return HTTP 200 with a tool failure envelope. That is not a pass.
        if result.is_error or not isinstance(body, dict) or body.get("error"):
            raise RuntimeError(f"{name} failed its read-only smoke check")
        oncall_handoff = (name == "get_doctor_availability" and body.get("outcome") == "HANDOFF_REQUIRED"
                          and body.get("detail") == "ON_CALL_DOCTOR" and body.get("complete") is True
                          and body.get("nextStep") == "TRANSFER_DESK")
        if body.get("outcome") not in outcomes and not oncall_handoff:
            raise RuntimeError(f"{name} failed its read-only smoke check")


async def smoke(url: str, token: str, language: str, department: str) -> None:
    root = url.removesuffix("/").removesuffix("/mcp")
    async with asyncio.timeout(120):
        async with httpx.AsyncClient(timeout=10) as http:
            await check_http(http, root)
        call_id = f"deploy-smoke-{uuid.uuid4().hex}"
        headers = {"Authorization": f"Bearer {token}", "X-Call-Id": call_id}
        async with Client(StreamableHttpTransport(url, headers=headers), timeout=20) as conversational:
            await check_tools(conversational, language, department)


def main() -> int:
    try:
        url = os.environ["MCP_URL"]
        token = os.environ["MCP_BEARER_TOKEN"]
        language = os.environ["SMOKE_LANGUAGE"]
        department = os.environ.get("SMOKE_DEPARTMENT", "General Medicine")
        if not url.startswith("https://") or not token or not language:
            raise ValueError("HTTPS URL, token and rollout language are required")
        asyncio.run(smoke(url, token, language, department))
    except (KeyError, ValueError, RuntimeError, TimeoutError, httpx.HTTPError, McpError, FastMCPError, ClientError,
            ExceptionGroup):  # expected CLI/transport failures: never print raw dependency errors
        print("Deployment smoke test failed; inspect MCP logs. No success declared.", file=sys.stderr)
        return 1
    print("Deployment smoke passed: readiness, dependency status, authentication, three tools, "
          "read-only availability and working-hours checks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
