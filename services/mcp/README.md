# frontdesk-mcp

FastMCP 2.14.7 adapter exposing four tools over streamable HTTP at `/mcp/` (stateless). It consumes
two owner services over HTTPS and owns no data: Manoj's operational API (pinned contract in
`docs/handover/mcp-only/contracts/`) and Shobhit's knowledge service (provisional contract in
`src/frontdesk_mcp/knowledge_contract.py`).

| Tool | Authentication | Owner calls |
|---|---|---|
| `get_doctor_availability` | gateway (in-call) | `GET /departments` or `GET /doctors?query=`; then `GET /doctors/{id}` ∥ `GET /availability?doctorId=&date=` (or `department=`) |
| `manage_booking` | gateway (in-call) | `POST /appointments` (after confirmation and live-board check), `GET /appointments?mobile=`, `POST …/cancel`, `POST …/reschedule` |
| `search_knowledge` | gateway (in-call) | one provisional `POST /v1/answer`: answer or routing outcome |
| `record_call_summary` | gateway (LLM-called) | `POST /call-summaries` |

Trusted context arrives as HTTP headers forwarded by the gateway/platform, never as tool arguments:
`X-Call-Id`, `X-Caller-Number` (+`X-Caller-Verification`), `X-Operation-Id` (per confirmed booking write),
`X-Call-Started-At` (summary). One `MCP_BEARER_TOKEN` authenticates all four tools.
Summaries forward exact whole-call text (1–500 nonblank characters), rely on owner call-ID deduplication
and return SAVED, ALREADY_SAVED, INVALID_REQUEST, NOT_CONFIRMED or NOT_SAVED. Their default budget is 8 s.

```bash
uv sync --frozen
uv run pytest tests -q -m "not e2e and not external"      # hermetic: stubs in process
uv run pytest tests -q -m e2e            # real processes over TCP
uv run frontdesk-mcp schema              # the pinned tool surface (tests/contracts/mcp-tools.snapshot.json)
uv run python dev/demo.py                # walk the four tools against the stubs
uv run python dev/bench.py               # tool round trips (stubs; BENCH_OPS_BASE_URL for a real host)
uv run frontdesk-mcp serve
```

Layout: `src/frontdesk_mcp/` (config, context, identity, clock, ops_client, knowledge_client, cache,
availability, booking, knowledge, summary, tools, server, prompt, packs/healthcare.json);
`dev/frontdesk_stubs/` (development stubs and fixtures; never in the image); `tests/`.

Scheduling has no knowledge dependency. An empty knowledge URL leaves only `search_knowledge` unavailable.
The tool interface, parameters and result meanings are documented in `docs/handover/VOICE-TEAM.md` at the repository root.
