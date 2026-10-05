# frontdesk-mcp

FastMCP 2.14.7 adapter exposing four tools over streamable HTTP at `/mcp/` (stateless). It consumes
two owner services over HTTPS and owns no data: Manoj's operational API (pinned contract in
`docs/handover/mcp-only/contracts/`) and Shobhit's knowledge service (provisional contract in
`src/frontdesk_mcp/knowledge_contract.py`).

| Tool | Authentication | Owner calls |
|---|---|---|
| `get_doctor_availability` | gateway (in-call) | `GET /departments` or `GET /doctors?query=`; today: directory/profile plus `GET /availability` (doctor or department); future/WORKING_HOURS: profiles only, bounded batches for departments |
| `manage_booking` | gateway (in-call) | `POST /appointments` (after confirmation and the shared today/future schedule decision), `GET /appointments?mobile=`, `POST …/cancel`, `POST …/reschedule` |
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
availability_policy, schedule_reader, availability, booking, knowledge, summary, tools, server, prompt, packs/healthcare.json);
`dev/frontdesk_stubs/` (development stubs and fixtures; never in the image); `tests/`.

Scheduling has no knowledge dependency. An empty knowledge URL leaves only `search_knowledge` unavailable.
The tool interface, parameters and result meanings are documented in `docs/handover/VOICE-TEAM.md` at the repository root.

`DOCTOR_CHOICE_LIMIT=3`, `PROFILE_BATCH_SIZE=3` (≤ `OPS_POOL_MAX_CONNECTIONS`) and
`MIN_BATCH_HEADROOM_SECONDS=0.05` bound future/working-hours searches within the existing 0.30 s share.
Profiles use the existing 300 s cache; boards never do. `complete=false` exposes unevaluated candidates.
No new endpoint, credential, secret or rollout identity is needed for this policy. The live owner must
supply usable usual schedules for future requests; no future board is fetched.
