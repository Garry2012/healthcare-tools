"""Read-only release gate against the deployed MCP adapter.

Checks local health/readiness, dependency status, that an unauthenticated request is refused, that the
gateway bearer sees exactly the three conversational tools and cannot finalize a call, that the lifecycle
bearer (when given) sees exactly record_call_summary, and that two read-only tool calls return honest,
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

CONVERSATIONAL_TOOLS = {"get_doctor_availability", "manage_booking", "search_knowledge"}
LIFECYCLE_TOOLS = {"record_call_summary"}
AVAILABILITY_OK = {"AVAILABILITY", "CALLBACK_REQUIRED", "CLARIFICATION_NEEDED", "NOT_FOUND"}
KNOWLEDGE_OK = {"ANSWERED", "NO_ANSWER", "CLARIFICATION_NEEDED", "ROUTING_REQUIRED"}




async def check_http(http: httpx.AsyncClient, root: str, expectation: str) -> bool:
    if expectation not in ("required", "absent"):
        raise ValueError("SMOKE_EXPECT_KNOWLEDGE must be required or absent")
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
    operational, knowledge = body.get("operational"), body.get("knowledge")
    if not isinstance(operational, dict) or operational.get("status") != "ok":
        raise RuntimeError("operational dependency is not healthy")
    if not isinstance(knowledge, dict) or knowledge.get("status") not in ("configured", "not_configured"):
        raise RuntimeError("malformed knowledge dependency response")
    configured = knowledge["status"] == "configured"
    if configured != (expectation == "required"):
        raise RuntimeError("knowledge configuration does not match the deployment profile")
    response = await http.post(f"{root}/mcp/", json={})
    if response.status_code != 401:
        raise RuntimeError("MCP accepted an unauthenticated request")
    return configured


async def check_tools(client: Client, language: str, department: str, *, knowledge_configured: bool = True) -> None:
    names = {tool.name for tool in await client.list_tools()}
    if names != CONVERSATIONAL_TOOLS:
        raise RuntimeError("unexpected conversational MCP tool set")
    cases = (
        ("get_doctor_availability", {"date": "today", "departmentName": department}, AVAILABILITY_OK),
        ("search_knowledge", {"question": "deployment connectivity check", "language": language}, KNOWLEDGE_OK),
    )
    for name, arguments, outcomes in cases:
        result = await client.call_tool(name, arguments, raise_on_error=False)
        body = result.structured_content
        if name == "search_knowledge" and not knowledge_configured:
            if result.is_error or not isinstance(body, dict) or (body.get("outcome"), body.get("detail")) != (
                    "COULD_NOT_CHECK", "NOT_CONFIGURED"):
                raise RuntimeError("knowledge configuration and tool result disagree")
            print("knowledge: NOT_CONFIGURED; scheduling verified, knowledge integration remains pending")
            continue
        # MCP can return HTTP 200 with a tool failure envelope. That is not a pass.
        if (result.is_error or not isinstance(body, dict) or body.get("error")
                or body.get("outcome") not in outcomes):
            raise RuntimeError(f"{name} failed its read-only smoke check")


async def check_lifecycle_boundary(conversational: Client, lifecycle: Client | None) -> None:
    """Server-side enforcement, not client-side hiding: the gateway bearer must be refused."""
    refused = await conversational.call_tool("record_call_summary", {
        "intent": "OTHER", "outcome": "ABANDONED", "summaryText": "deployment smoke must be refused"},
        raise_on_error=False)
    if not refused.is_error:
        raise RuntimeError("the conversational bearer could reach the lifecycle tool")
    if lifecycle is not None:
        names = {tool.name for tool in await lifecycle.list_tools()}
        if names != LIFECYCLE_TOOLS:
            raise RuntimeError("the lifecycle bearer does not see exactly the summary tool")


async def smoke(url: str, token: str, lifecycle_token: str | None, language: str, department: str,
                expectation: str) -> None:
    root = url.removesuffix("/").removesuffix("/mcp")
    async with asyncio.timeout(120):
        async with httpx.AsyncClient(timeout=10) as http:
            knowledge_configured = await check_http(http, root, expectation)
        call_id = f"deploy-smoke-{uuid.uuid4().hex}"
        headers = {"Authorization": f"Bearer {token}", "X-Call-Id": call_id}
        async with Client(StreamableHttpTransport(url, headers=headers), timeout=20) as conversational:
            await check_tools(conversational, language, department, knowledge_configured=knowledge_configured)
            if lifecycle_token:
                lifecycle_headers = {"Authorization": f"Bearer {lifecycle_token}", "X-Call-Id": call_id}
                async with Client(StreamableHttpTransport(url, headers=lifecycle_headers), timeout=20) as lifecycle:
                    await check_lifecycle_boundary(conversational, lifecycle)
            else:
                await check_lifecycle_boundary(conversational, None)


def main() -> int:
    try:
        url = os.environ["MCP_URL"]
        token = os.environ["MCP_BEARER_TOKEN"]
        language = os.environ["SMOKE_LANGUAGE"]
        expectation = os.environ["SMOKE_EXPECT_KNOWLEDGE"]
        if expectation not in ("required", "absent"):
            raise ValueError("invalid knowledge expectation")
        department = os.environ.get("SMOKE_DEPARTMENT", "General Medicine")
        lifecycle_token = os.environ.get("MCP_LIFECYCLE_BEARER_TOKEN") or None
        if not url.startswith("https://") or not token or not language:
            raise ValueError("HTTPS URL, token and rollout language are required")
        asyncio.run(smoke(url, token, lifecycle_token, language, department, expectation))
    except (KeyError, ValueError, RuntimeError, TimeoutError, httpx.HTTPError, McpError, FastMCPError, ClientError,
            ExceptionGroup):  # expected CLI/transport failures: never print raw dependency errors
        print("Deployment smoke test failed; inspect MCP logs. No success declared.", file=sys.stderr)
        return 1
    print("Deployment smoke passed: readiness, dependency status, authentication, three conversational tools, "
          "lifecycle boundary, read-only availability and knowledge status checks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
