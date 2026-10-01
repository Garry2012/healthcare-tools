# ContextForge registration

ContextForge federates `frontdesk-mcp` as an MCP gateway (streamable HTTP) and adds auth,
observability and rate limits. Each hospital is one gateway entry, `frontdesk-<provider>`, pointing
at that hospital's adapter with the **gateway** bearer. Through it the voice agent sees the three
conversational tools; `record_call_summary` is invoked by the call-end lifecycle with the separate
lifecycle bearer (directly or through its own gateway entry), never through this one.

```
voice agent ──MCP + trusted call headers──▶ ContextForge ──passthrough──▶ frontdesk-mcp ──▶ owner services
```

## Prerequisites on the gateway

- `ENABLE_HEADER_PASSTHROUGH=true`. The registration lists every trusted header as
  `passthrough_headers`: `X-Call-Id`, `X-Caller-Number`, `X-Caller-Verification`, `X-Turn-Context`,
  `X-Operation-Id`, `X-Call-Started-At`, `X-Call-Duration-Seconds`. Without passthrough, writes are
  refused (no call/operation id) and availability returns ROUTING_UNAVAILABLE (no trusted turn).
- A network path from ContextForge to the adapter (`MCP_PUBLIC_URL`, ending in `/mcp/`).

## Register, verify, refresh

```bash
export CONTEXTFORGE_URL=https://<gateway-host>
export CONTEXTFORGE_ADMIN_EMAIL=... CONTEXTFORGE_ADMIN_PASSWORD=...   # or CONTEXTFORGE_TOKEN=<admin JWT>
export MCP_PUBLIC_URL=https://<adapter-host>/mcp/
export MCP_BEARER_TOKEN=<the adapter's GATEWAY bearer>
eval "$(scripts/rollout-env.sh <rollout dir>)"     # PROVIDER_ID, DOMAIN_PACK

cd services/mcp
uv run python ../../deploy/contextforge/register.py --dry-run   # payload, token redacted
uv run python ../../deploy/contextforge/register.py              # register or update, then verify
```

After registering or updating, the script lists the gateway's discovered tools and compares names
and input schemas with what the adapter serves (`tools/list` through the same bearer). On drift it
asks the gateway to rediscover once (`POST /v1/gateways/{id}/refresh`, falling back to a
deactivate/activate toggle) and fails if the surface still differs. Run it after every change of
`prompt.SCHEMA_VERSION`; LiveKit's cached tool view must be refreshed in the same step.

**Verification status:** no ContextForge instance is deployed for this project (the `mcp-gateway`
app in `vcare-rc-rg` belongs to another project). The refresh/toggle endpoints and header passthrough
are implemented from the ContextForge documentation and are unverified against a live gateway; see
`mcp-only/implementation/OPEN-DEPENDENCIES.md`.
