# ContextForge registration

ContextForge is infrastructure: it federates `healthcare-mcp` as an MCP gateway
(`integration_type: MCP`, streamable HTTP) and adds auth, observability and rate limits.
Nothing is built or changed in the ContextForge fork.

```
voice agent ──MCP + X-Call-Id, X-Caller-Number──▶ ContextForge ──passthrough──▶ healthcare-mcp ──▶ healthcare-api
```

## Prerequisites on the gateway

- `ENABLE_HEADER_PASSTHROUGH=true` on ContextForge. The registration lists
  `X-Call-Id` and `X-Caller-Number` as `passthrough_headers`; without the flag they are dropped
  and every write is refused (no call id, no idempotency key).
- A network path from ContextForge to the adapter (`MCP_PUBLIC_URL`, ending in `/mcp/`).

## Register (idempotent)

```bash
export CONTEXTFORGE_URL=https://<gateway-host>
export CONTEXTFORGE_ADMIN_EMAIL=... CONTEXTFORGE_ADMIN_PASSWORD=...   # or CONTEXTFORGE_TOKEN=<admin JWT>
export MCP_PUBLIC_URL=https://<adapter-host>/mcp/
export MCP_BEARER_TOKEN=<same value the adapter is configured with>

cd services/mcp
uv run python ../../deploy/contextforge/register.py --dry-run   # prints the payload, token redacted
uv run python ../../deploy/contextforge/register.py              # registers, or reports "already registered"
```

Re-running is safe. The same name and URL is a no-op, and a changed visibility or passthrough
list is updated in place. A name that already points elsewhere is refused, as is a tool-name
collision with an existing gateway.

## The same with curl

```bash
TOKEN=$(curl -s -X POST "$CONTEXTFORGE_URL/v1/auth/login" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$CONTEXTFORGE_ADMIN_EMAIL\",\"password\":\"$CONTEXTFORGE_ADMIN_PASSWORD\"}" | jq -r .access_token)

curl -s -X POST "$CONTEXTFORGE_URL/v1/gateways" -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d @- <<JSON
{
  "name": "healthcare-frontdesk",
  "url": "$MCP_PUBLIC_URL",
  "description": "Hospital front-desk tools: find_availability, manage_appointment",
  "transport": "STREAMABLEHTTP",
  "auth_type": "bearer",
  "auth_token": "$MCP_BEARER_TOKEN",
  "passthrough_headers": ["X-Call-Id", "X-Caller-Number"],
  "visibility": "private",
  "tags": ["healthcare", "front-desk"]
}
JSON
```

ContextForge then lists the tools with the gateway prefix, e.g.
`healthcare-frontdesk-find-availability`. The live registration hasn't been run from this
workspace; only `--dry-run` has been verified.
