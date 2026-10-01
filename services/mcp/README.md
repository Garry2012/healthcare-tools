# frontdesk-mcp

FastMCP 2.14.7 adapter exposing four tools over streamable HTTP at `/mcp/` (stateless). It consumes
two owner services over HTTPS and owns no data: Manoj's operational API (pinned contract in
`docs/handover/mcp-only/contracts/`) and Shobhit's knowledge service (provisional contract in
`src/frontdesk_mcp/knowledge_contract.py`).

| Tool | Principal | Owner calls |
|---|---|---|
| `get_doctor_availability` | gateway (in-call) | knowledge route (required clearance) ∥ `GET /departments` or `GET /doctors?query=`; then `GET /doctors/{id}` ∥ `GET /availability?doctorId=&date=` (or `department=`) |
| `manage_booking` | gateway (in-call) | `POST /appointments` (after routing clearance), `GET /appointments?mobile=`, `POST …/cancel`, `POST …/reschedule` |
| `search_knowledge` | gateway (in-call) | knowledge answer |
| `record_call_summary` | call-end lifecycle only | `POST /call-summaries` |

Trusted context arrives as HTTP headers forwarded by the gateway/platform, never as tool arguments:
`X-Call-Id`, `X-Caller-Number` (+`X-Caller-Verification`), `X-Turn-Context` (base64url JSON
`{utterance, language, turnId?}`), `X-Operation-Id` (per confirmed write), `X-Call-Started-At`,
`X-Call-Duration-Seconds` (lifecycle). Two bearers: `MCP_BEARER_TOKEN` sees the three in-call tools;
`MCP_LIFECYCLE_BEARER_TOKEN` sees only `record_call_summary` (enforced server-side).

```bash
uv sync --frozen
uv run pytest tests -q -m "not e2e"      # hermetic: stubs in process
uv run pytest tests -q -m e2e            # real processes over TCP
uv run frontdesk-mcp schema              # the pinned tool surface (tests/contracts/mcp-tools.snapshot.json)
uv run python dev/demo.py                # walk the four tools against the stubs
uv run python dev/bench.py               # tool round trips (stubs; BENCH_OPS_BASE_URL for a real host)
uv run frontdesk-mcp serve
```

Layout: `src/frontdesk_mcp/` (config, context, identity, clock, ops_client, knowledge_client, cache,
availability, booking, knowledge, summary, access, tools, server, prompt, packs/healthcare.json);
`dev/frontdesk_stubs/` (development stubs and fixtures; never in the image); `tests/`.
