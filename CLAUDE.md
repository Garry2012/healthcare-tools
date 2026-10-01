# Front-desk MCP adapter (voice agent tools)

Four MCP tools for a LiveKit voice agent, consuming two owner services over HTTPS. This repository
owns only the adapter: `services/mcp`. Manoj owns the operational API (directory, live board,
appointments, call summaries; pinned contract in `docs/handover/mcp-only/contracts/`). Shobhit owns
knowledge, symptom routing and red flags (contract pending; provisional boundary in
`services/mcp/src/frontdesk_mcp/knowledge_contract.py`). Plan and target: `docs/handover/mcp-only/`.
Implementation evidence: `docs/handover/mcp-only/implementation/`.

## Commands
- Fast (no processes), run after every change: `make test-fast`
- Everything a reviewer runs on a clean checkout: `./scripts/test.sh` (lint, hermetic suites, process e2e, package and image build); CI runs it
- Process e2e only: `make test-e2e`; walk the tools: `make demo`; latency: `make bench`
- Tool surface: `make schema` must equal `services/mcp/tests/contracts/mcp-tools.snapshot.json`; bump `prompt.SCHEMA_VERSION` and regenerate when it changes
- Local stack against the development stubs: `cp .env.example .env && make up`
- Deploy: `deploy/azure/deploy.sh rollouts/<id> --dry-run` (needs OPS_BASE_URL and KNOWLEDGE_BASE_URL of the owners' real hosts)

## Rules the code will not tell you
- No business rules here: no scheduling, slot, capacity, interpretation, knowledge or clinical logic; no database, queue or local fallback backend. The adapter validates, authenticates, forwards trusted context, applies deadlines, maps statuses and composes contracted reads.
- Trusted context (`X-Call-Id`, `X-Caller-Number`, `X-Caller-Verification`, `X-Turn-Context`, `X-Operation-Id`, `X-Call-Started-At`, `X-Call-Duration-Seconds`) comes only from request headers. The principal (gateway vs call-end lifecycle) comes only from the bearer. Never from tool arguments.
- Availability, CREATE and search_knowledge wait for a current routing clearance from the knowledge service on the trusted turn plus the caller's relayed words (`reasonVerbatim`, the question); CANCEL/RESCHEDULE route their reason when given. Missing, malformed or oversized context (> 4,000 characters, never truncated), outage or an unknown response is never clearance. Independent reads overlap the check and are cancelled if it does not clear.
- UNKNOWN board (today or later) stops the appointment journey: collect name and callback number, say someone will call back, record a CALLBACK_NOTED summary. No booking, transfer, alternate or task. A failed board read is COULD_NOT_CHECK, not UNKNOWN.
- A create is NOTED, never confirmed. Writes need `callerConfirmed`, call id and operation id; the body is frozen and keyed by `sha256(tenant|call|action|operation)` (no target: a changed target conflicts). A create also reads the live board for the visit date (in parallel with routing) with the same session scope as availability (`session`, else the window holding `preferredTime`, else the day) and refuses an UNKNOWN scope with the callback-only outcome or asks which session when the scope is unresolved and statuses are mixed. UNCERTAIN is a distinct outcome: once a write attempt may have reached the owner, no later failure is reported as definite. One same-key retry at most, within the invocation deadline.
- Caller authority for LIST/CANCEL/RESCHEDULE is the verified caller number under the configured country rule, with an explicit `X-Caller-Verification` in the accepted set; a bare number is unverified. A dictated mobile is contact data. No prefix stripping, never "the last ten digits".
- `record_call_summary` is reachable only with the lifecycle bearer; MCP stays stateless; the platform owns durable finalization and retries.
- Results and logs never carry caller numbers, patient names, reasons, raw upstream prose or secrets. Request-URL loggers stay at WARNING.
- Contract changes are reviewed changes: the pinned snapshot, its hash, the overlay and `contract.py` literals are asserted by tests. Stubs (`services/mcp/dev/`) are fixtures, never engines; production refuses stub/mock hosts.
- Domain words live in `packs/healthcare.json`; tenant identity (timezone, calling code, languages) in `rollouts/<id>/rollout.env` with no defaults.

- Deadlines derive from the voice budget: `VOICE_RESPONSE_BUDGET_SECONDS` − `RESERVED_STAGE_SECONDS` (default 0.35 s read, 0.6 s write); explicit `READ_DEADLINE_SECONDS` etc. are diagnostic overrides, never production defaults.

## Gotchas
- Don't `source` rollout.env; use `scripts/rollout-env.sh`.
- Test conftest strips every `Settings` field from the environment; pass overrides via `make_settings(...)`.
- The clients cap every exchange with `asyncio.timeout` (httpx timeouts are per phase); in-process stub tests rely on that, and `test_ops_client.py` has a real-TCP dribbling-server test.
