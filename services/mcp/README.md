# frontdesk-mcp

FastMCP 2.14.7 adapter exposing three tools over streamable HTTP at `/mcp/` (stateless). It consumes
Manoj's operational API over HTTPS and owns no data (pinned contract in
`docs/handover/mcp-only/contracts/`).

| Tool | Authentication | Owner calls |
|---|---|---|
| `get_doctor_availability` | gateway (in-call) | `GET /departments` or `GET /doctors?query=`; directory/profile reads; today-only `GET /availability`; selected-doctor AVAILABILITY also reads `GET /availability/{doctorId}/slots`, departments use cached `GET /capabilities`; WORKING_HOURS reads profiles only |
| `manage_booking` | gateway (in-call) | `POST /appointments` (after confirmation and the shared today/future schedule decision), `GET /appointments?mobile=`, `POST …/cancel`, `POST …/reschedule` |
| `record_call_summary` | gateway (LLM-called) | `POST /call-summaries` |

Trusted context arrives as HTTP headers forwarded by the gateway/platform, never as tool arguments:
`X-Call-Id`, `X-Caller-Number` (+`X-Caller-Verification`), `X-Operation-Id` (per confirmed booking write),
`X-Call-Started-At` (summary). One `MCP_BEARER_TOKEN` authenticates all three tools.
Summaries forward exact whole-call text (1–500 nonblank characters), rely on owner call-ID deduplication
and return SAVED, ALREADY_SAVED, INVALID_REQUEST, NOT_CONFIRMED or NOT_SAVED. Their default budget is 8 s.

```bash
uv sync --frozen
uv run pytest tests -q -m "not e2e and not external"      # hermetic: stubs in process
uv run pytest tests -q -m e2e            # real processes over TCP
uv run frontdesk-mcp schema              # the pinned tool surface (tests/contracts/mcp-tools.snapshot.json)
uv run python dev/demo.py                # walk the three tools against the stubs
uv run python dev/bench.py               # tool round trips (stubs; BENCH_OPS_BASE_URL for a real host)
uv run frontdesk-mcp serve
```

Layout: `src/frontdesk_mcp/` (config, context, identity, clock, ops_client, cache,
availability_policy, schedule_reader, availability, booking, summary, tools, server, prompt, packs/healthcare.json);
`dev/frontdesk_stubs/` (development stubs and fixtures; never in the image); `tests/`.

Knowledge, symptom routing and emergency decisions belong to the voice team through Stratum's separate ContextForge registration; this adapter has no knowledge client.
The tool interface, parameters and result meanings are documented in `docs/handover/VOICE-TEAM.md` at the repository root.

`DOCTOR_CHOICE_LIMIT=3`, `PROFILE_BATCH_SIZE=3` (≤ `OPS_POOL_MAX_CONNECTIONS`) and
`MIN_BATCH_HEADROOM_SECONDS=0.05` bound future/working-hours searches within the existing 0.30 s share.
Profiles use the existing 300 s cache; boards never do. `complete=false` exposes unevaluated candidates.
No new endpoint, credential, secret or rollout identity is needed for this policy. The live owner must
supply usable usual schedules for future requests; no future board is fetched.
