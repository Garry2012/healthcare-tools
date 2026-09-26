"""Register frontdesk-mcp with IBM ContextForge as a federated MCP gateway.

Idempotent: re-running with the same name and URL is a no-op; a changed
visibility or passthrough-header list is updated in place; a name that already points at a
different URL is refused. Credentials come only from the environment.

    CONTEXTFORGE_URL             e.g. http://127.0.0.1:4444
    CONTEXTFORGE_TOKEN           an admin JWT, or instead:
    CONTEXTFORGE_ADMIN_EMAIL / CONTEXTFORGE_ADMIN_PASSWORD   (POST /v1/auth/login)
    MCP_PUBLIC_URL               URL ContextForge uses to reach the adapter, ending /mcp/
    MCP_BEARER_TOKEN             bearer ContextForge presents to the adapter

    python deploy/contextforge/register.py --dry-run
    python deploy/contextforge/register.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import httpx

TOOLS = ("find_availability", "manage_appointment")
# Call identity travels from the voice platform through the gateway to the adapter.
PASSTHROUGH = ["X-Call-Id", "X-Caller-Number"]


def env(name: str, *, required: bool = True) -> str:
    value = os.environ.get(name, "")
    if required and not value:
        raise SystemExit(f"{name} is not set")
    return value


def payload(args: argparse.Namespace) -> dict:
    return {
        "name": args.name,
        "url": env("MCP_PUBLIC_URL"),
        "description": "Hospital front-desk tools: find_availability, manage_appointment",
        "transport": "STREAMABLEHTTP",
        "auth_type": "bearer",
        "auth_token": env("MCP_BEARER_TOKEN"),
        "passthrough_headers": PASSTHROUGH,
        "visibility": args.visibility,
        "tags": ["healthcare", "front-desk"],
    }


def redacted(body: dict) -> dict:
    return {**body, "auth_token": "***" if body.get("auth_token") else ""}


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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", default="healthcare-frontdesk", help="gateway name (tool prefix in ContextForge)")
    parser.add_argument("--visibility", choices=("private", "team", "public"), default="private")
    parser.add_argument("--dry-run", action="store_true", help="print the registration payload and exit")
    args = parser.parse_args()

    body = payload(args)
    if args.dry_run:
        print(json.dumps({"method": "POST", "path": "/v1/gateways", "json": redacted(body)}, indent=2))
        return

    with httpx.Client(base_url=env("CONTEXTFORGE_URL").rstrip("/"), timeout=30) as client:
        client.headers["Authorization"] = f"Bearer {admin_token(client)}"
        current = client.get("/v1/gateways", params={"include_inactive": "true"})
        current.raise_for_status()
        same = next((g for g in rows(current.json(), "gateways") if g.get("name") == args.name), None)
        if same is not None:
            if str(same.get("url", "")).rstrip("/") != body["url"].rstrip("/"):
                raise SystemExit(f"gateway {args.name!r} already points at {same.get('url')}; refusing to repoint")
            changed = (
                same.get("visibility") != args.visibility
                or sorted(same.get("passthrough_headers") or same.get("passthroughHeaders") or []) != sorted(PASSTHROUGH)
            )
            if changed:
                client.put(f"/v1/gateways/{same['id']}", json=body).raise_for_status()
                print(f"updated: {args.name} ({same['id']})")
            else:
                print(f"already registered: {args.name} ({same['id']})")
            return

        tools = client.get("/v1/tools", params={"include_inactive": "true"})
        tools.raise_for_status()
        existing = {str(t.get("name")) for t in rows(tools.json(), "tools")}
        predicted = {f"{args.name}-{t.replace('_', '-')}" for t in TOOLS} | {f"{args.name}-{t}" for t in TOOLS}
        if clash := sorted(existing & predicted):
            raise SystemExit(f"tool-name collision: {', '.join(clash)}")

        created = client.post("/v1/gateways", json=body)
        if created.status_code >= 400:
            print(created.text, file=sys.stderr)
        created.raise_for_status()
        result = created.json()
        print(f"registered: {result.get('name')} ({result.get('id')}), tools: {', '.join(TOOLS)}")


if __name__ == "__main__":
    main()
