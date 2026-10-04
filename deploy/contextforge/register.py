"""Register frontdesk-mcp with IBM ContextForge as a federated MCP gateway and verify the tool surface.

Idempotent: the same name and URL is a no-op; a changed visibility or passthrough-header list is
updated in place; a name that already points at a different URL is refused. After registering or
updating, the gateway's discovered tools are compared with what the adapter itself serves (names and
input schemas); drift triggers one refresh attempt and then fails the run. Credentials come only from
the environment.

    CONTEXTFORGE_URL             e.g. http://127.0.0.1:4444
    CONTEXTFORGE_TOKEN           an admin JWT, or instead:
    CONTEXTFORGE_ADMIN_EMAIL / CONTEXTFORGE_ADMIN_PASSWORD   (POST /v1/auth/login)
    MCP_PUBLIC_URL               URL ContextForge uses to reach the adapter, ending /mcp/
    MCP_BEARER_TOKEN             the GATEWAY bearer the adapter expects
    CONTEXTFORGE_TEAM_ID         required with --visibility team
    PROVIDER_ID, DOMAIN_PACK     from rollouts/<provider>/rollout.env: one gateway per rollout,
                                 named frontdesk-<provider> (the voice agent's tool prefix)

    python deploy/contextforge/register.py --dry-run
    python deploy/contextforge/register.py

ContextForge must run with ENABLE_HEADER_PASSTHROUGH=true so the trusted call headers reach the
adapter. The gateway entry carries the gateway bearer: all four tools are available through it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

import httpx
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

TOOLS = ("get_doctor_availability", "manage_booking", "search_knowledge", "record_call_summary")
# Trusted call context travels from the voice platform through the gateway to the adapter.
PASSTHROUGH = ["X-Call-Id", "X-Caller-Number", "X-Caller-Verification", "X-Operation-Id",
               "X-Call-Started-At"]


def env(name: str, *, required: bool = True) -> str:
    value = os.environ.get(name, "")
    if required and not value:
        raise SystemExit(f"{name} is not set")
    return value


def payload(args: argparse.Namespace) -> dict:
    return {
        "name": args.name,
        "url": env("MCP_PUBLIC_URL"),
        "description": f"Hospital front-desk tools: {', '.join(TOOLS)}",
        "transport": "STREAMABLEHTTP",
        "authType": "bearer",
        "authToken": env("MCP_BEARER_TOKEN"),
        "passthroughHeaders": PASSTHROUGH,
        "visibility": args.visibility,
        "tags": ["front-desk", env("DOMAIN_PACK", required=False) or "healthcare", args.name],
    }


def redacted(body: dict) -> dict:
    return {**body, "authToken": "***" if body.get("authToken") else ""}


def rows(body, key: str) -> list[dict]:
    if isinstance(body, list):
        return body
    return body.get(key) or body.get("items") or body.get("data") or []


def admin_token(client: httpx.Client) -> str:
    if token := env("CONTEXTFORGE_TOKEN", required=False):
        return token
    response = client.post("/v1/auth/login", json={
        "email": env("CONTEXTFORGE_ADMIN_EMAIL"), "password": env("CONTEXTFORGE_ADMIN_PASSWORD"),
    })
    response.raise_for_status()
    return response.json()["access_token"]


def drift(served: list[dict], gateway_tools: list[dict], prefix: str) -> list[str]:
    """Differences between the adapter's tools and what the gateway discovered."""
    problems: list[str] = []
    expected = {t["name"]: t for t in served}
    discovered: dict[str, dict] = {}
    for tool in gateway_tools:
        name = str(tool.get("name", ""))
        if not name.startswith(prefix):
            continue
        local = name[len(prefix):].lstrip("-_").replace("-", "_")
        discovered[local] = tool
    for name, tool in expected.items():
        if name not in discovered:
            problems.append(f"{name}: not discovered by the gateway")
            continue
        schema = discovered[name].get("input_schema") or discovered[name].get("inputSchema") or {}
        if schema != (tool.get("inputSchema") or {}):
            problems.append(f"{name}: gateway input schema differs from the adapter's (stale discovery)")
    for name in sorted(set(discovered) - set(expected)):
        problems.append(f"{name.replace('_', '-')}: gateway lists a tool the adapter no longer serves")
    return problems


async def served_tools(url: str, token: str) -> list[dict]:
    async with Client(StreamableHttpTransport(url, headers={"Authorization": f"Bearer {token}"})) as client:
        return [{"name": t.name, "inputSchema": t.inputSchema} for t in await client.list_tools()]


def verify(client: httpx.Client, gateway_id: str, name: str) -> None:
    served = asyncio.run(served_tools(env("MCP_PUBLIC_URL"), env("MCP_BEARER_TOKEN")))
    if sorted(t["name"] for t in served) != sorted(TOOLS):
        raise SystemExit("the adapter does not serve exactly the four tools to the gateway bearer")
    for attempt in (1, 2):
        tools = client.get("/v1/tools", params={"include_inactive": "true"})
        tools.raise_for_status()
        problems = drift(served, rows(tools.json(), "tools"), name)
        if not problems:
            print(f"verified: gateway tools match the adapter ({', '.join(TOOLS)})")
            return
        if attempt == 1:
            print("tool drift detected; asking the gateway to rediscover", file=sys.stderr)
            refresh = client.post(f"/v1/gateways/{gateway_id}/tools/refresh")
            if refresh.status_code >= 400:  # not every ContextForge version has this endpoint
                print(f"refresh endpoint unavailable ({refresh.status_code}); toggling the gateway", file=sys.stderr)
                client.post(f"/v1/gateways/{gateway_id}/state", params={"activate": "false"}).raise_for_status()
                client.post(f"/v1/gateways/{gateway_id}/state", params={"activate": "true"}).raise_for_status()
    raise SystemExit("gateway tool surface still differs from the adapter:\n  " + "\n  ".join(problems))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    provider = os.environ.get("PROVIDER_ID", "")
    parser.add_argument("--name", default=f"frontdesk-{provider}" if provider else None,
                        help="gateway name, the tool prefix in ContextForge (default frontdesk-$PROVIDER_ID)")
    parser.add_argument("--visibility", choices=("private", "team", "public"), default="private")
    parser.add_argument("--dry-run", action="store_true", help="print the registration payload and exit")
    parser.add_argument("--skip-verify", action="store_true", help="do not compare discovered tools with the adapter")
    args = parser.parse_args()
    if not args.name:
        parser.error("set PROVIDER_ID (or pass --name): each provider is its own gateway")

    body = payload(args)
    if args.visibility == "team":
        body["teamId"] = env("CONTEXTFORGE_TEAM_ID")
    if args.dry_run:
        print(json.dumps({"method": "POST", "path": "/v1/gateways", "json": redacted(body),
                          "verify": "GET /v1/tools vs adapter tools/list"}, indent=2))
        return

    with httpx.Client(base_url=env("CONTEXTFORGE_URL").rstrip("/"), timeout=30) as client:
        client.headers["Authorization"] = f"Bearer {admin_token(client)}"
        current = client.get("/v1/gateways", params={"include_inactive": "true"})
        current.raise_for_status()
        same = next((g for g in rows(current.json(), "gateways") if g.get("name") == args.name), None)
        if same is not None:
            if str(same.get("url", "")).rstrip("/") != body["url"].rstrip("/"):
                raise SystemExit(f"gateway {args.name!r} already points at {same.get('url')}; refusing to repoint")
            registered = same.get("passthrough_headers") or same.get("passthroughHeaders") or []
            changed = (same.get("visibility") != args.visibility or sorted(registered) != sorted(PASSTHROUGH)
                       or (body.get("teamId") is not None
                           and (same.get("teamId") or same.get("team_id")) != body["teamId"]))
            if changed:
                client.put(f"/v1/gateways/{same['id']}", json=body).raise_for_status()
                print(f"updated: {args.name} ({same['id']})")
            else:
                print(f"already registered: {args.name} ({same['id']})")
            gateway_id = str(same["id"])
        else:
            tools = client.get("/v1/tools", params={"include_inactive": "true"})
            tools.raise_for_status()
            existing = {str(t.get("name")) for t in rows(tools.json(), "tools")}
            predicted = {f"{args.name}-{t.replace('_', '-')}" for t in TOOLS} | {f"{args.name}-{t}" for t in TOOLS}
            if clash := sorted(existing & predicted):
                raise SystemExit(f"tool-name collision: {', '.join(clash)}")
            created = client.post("/v1/gateways", json=body)
            if created.status_code >= 400:
                print(f"registration failed (HTTP {created.status_code}); response body suppressed", file=sys.stderr)
            created.raise_for_status()
            result = created.json()
            gateway_id = str(result.get("id"))
            print(f"registered: {result.get('name')} ({gateway_id}), conversational tools: {', '.join(TOOLS)}")
        if not args.skip_verify:
            verify(client, gateway_id, args.name)


if __name__ == "__main__":
    main()
