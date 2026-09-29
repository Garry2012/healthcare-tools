"""Read-only release gate against the deployed MCP adapter (and its internal API).

Run with the services/mcp environment. Credentials are environment-only; response bodies
and exception details are deliberately not printed. No booking or caller identity is created.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

import httpx
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

EXPECTED_TOOLS = {"find_availability", "manage_booking", "search_knowledge"}


async def check_http(http: httpx.AsyncClient, root: str) -> None:
    for path, expected in (("health", "ok"), ("ready", "ready")):
        response = await http.get(f"{root}/{path}")
        response.raise_for_status()
        if response.json().get("status") != expected:
            raise RuntimeError(f"unexpected {path} response")
    # In particular, a forgotten MCP bearer configuration must fail the release.
    response = await http.post(f"{root}/mcp/", json={})
    if response.status_code != 401:
        raise RuntimeError("MCP accepted an unauthenticated request")


async def check_tools(client: Client, language: str) -> None:
    names = {tool.name for tool in await client.list_tools()}
    if names != EXPECTED_TOOLS:
        raise RuntimeError("unexpected MCP tool set")
    cases = (
        ("find_availability", {"utterance": "availability", "language": language},
         {"FOUND", "NONE_AVAILABLE", "CLARIFICATION_NEEDED", "TRANSFER"}),
        ("search_knowledge", {"question": "deployment connectivity check", "language": language},
         {"ANSWERED", "CLARIFICATION_NEEDED", "NO_ANSWER", "TRANSFER"}),
    )
    for name, arguments, outcomes in cases:
        result = await client.call_tool(name, arguments)
        body = result.structured_content
        # MCP can return HTTP 200 with a tool/API failure envelope. That is not a pass.
        if (result.is_error or not isinstance(body, dict) or body.get("error")
                or body.get("outcome") not in outcomes):
            raise RuntimeError(f"{name} failed its read-only smoke check")


async def smoke(url: str, token: str, language: str) -> None:
    root = url.removesuffix("/").removesuffix("/mcp")
    async with asyncio.timeout(120):
        async with httpx.AsyncClient(timeout=10) as http:
            await check_http(http, root)
        transport = StreamableHttpTransport(url, headers={
            "Authorization": f"Bearer {token}", "X-Call-Id": f"deploy-smoke-{uuid.uuid4().hex}",
        })
        async with Client(transport, timeout=20) as client:
            await check_tools(client, language)


def main() -> int:
    try:
        url = os.environ["MCP_URL"]
        token = os.environ["MCP_BEARER_TOKEN"]
        language = os.environ["SMOKE_LANGUAGE"]
        if not url.startswith("https://") or not token or not language:
            raise ValueError("HTTPS URL, token and rollout language are required")
        asyncio.run(smoke(url, token, language))
    except Exception:  # noqa: BLE001 - CLI boundary: dependency exceptions may contain credentials
        print("Deployment smoke test failed; inspect API/MCP logs. No success declared.", file=sys.stderr)
        return 1
    print("Deployment smoke passed: readiness, authentication, tool discovery, availability and knowledge.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
