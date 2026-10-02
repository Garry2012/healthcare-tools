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
- Environments: `eval "$(scripts/env.sh mock|live)"` is the one place an owner endpoint is written (`deploy/environments/*.env`, non-secret); it feeds deploy, the external gates and the bench. `live` names Manoj's base URL and the canary app `mcp-demo-hospital-canary` (deployed 2 October 2026; knowledge host still a placeholder)
- Deploy: `deploy/azure/deploy.sh rollouts/<id> --profile live [--dry-run]` (profile names subscription `4e1c…` and `healthcare-rg`; the script never creates or defaults a resource group; `mock` can only dry-run)

## Rules the code will not tell you
- No business rules here: no scheduling, slot, capacity, interpretation, knowledge or clinical logic; no database, queue or local fallback backend. The adapter validates, authenticates, forwards trusted context, applies deadlines, maps statuses and composes contracted reads.
- Trusted context (`X-Call-Id`, `X-Caller-Number`, `X-Caller-Verification`, `X-Turn-Context`, `X-Operation-Id`, `X-Call-Started-At`, `X-Call-Duration-Seconds`) comes only from request headers. The principal (gateway vs call-end lifecycle) comes only from the bearer. Never from tool arguments.
- Availability, CREATE and search_knowledge wait for a current routing clearance from the knowledge service on the trusted turn plus the caller's relayed words (`reasonVerbatim`, the question); CANCEL/RESCHEDULE route their reason when given. Missing, malformed or oversized context (> 4,000 characters, never truncated), outage or an unknown response is never clearance. Independent reads overlap the check and are cancelled if it does not clear.
- UNKNOWN board (today or later) stops the appointment journey: collect name and callback number, say someone will call back, record a CALLBACK_NOTED summary. No booking, transfer, alternate or task. A failed board read is COULD_NOT_CHECK, not UNKNOWN.
- A create is NOTED, never confirmed. Writes need `callerConfirmed`, call id and operation id; the body is frozen and keyed by `sha256(tenant|call|action|operation)` (no target: a changed target conflicts). A create (and a reschedule, for the new date) reads the live board (in parallel with routing) and applies the one shared scope rule in `board_scope.py` that availability uses: `session`, else the window holding `preferredTime`, else the day; an UNKNOWN row, a missing promised row or no row in scope is callback-only; a preferred time outside the chosen session's window is invalid. Department targets apply the same scope per doctor. UNCERTAIN is a distinct outcome: once a write attempt may have reached the owner, no later failure is reported as definite. One same-key retry at most, within the invocation deadline.
- Caller authority for LIST/CANCEL/RESCHEDULE is the verified caller number under the configured country rule, with an explicit `X-Caller-Verification` in the accepted set; a bare number is unverified. A dictated mobile is contact data. No prefix stripping, never "the last ten digits".
- `record_call_summary` is reachable only with the lifecycle bearer; MCP stays stateless; the platform owns durable finalization and retries.
- Results never carry caller numbers, reasons, raw upstream error prose or secrets; logs carry none of those and no patient names. Two documented exceptions in results: the `patientName` of the verified caller's own appointments (needed to pick one; the number holder is authorised to hear names registered under that number) and the desk-authored board `note` (≤200 chars, written for callers). Request-URL loggers stay at WARNING.
- Contract changes are reviewed changes: the pinned snapshot, its hash, the overlay and `contract.py` literals are asserted by tests. Stubs (`services/mcp/dev/`) are fixtures, never engines; production refuses stub/mock hosts.
- Domain words live in `packs/healthcare.json`; tenant identity (timezone, calling code, languages) in `rollouts/<id>/rollout.env` with no defaults.

- Deadlines derive from the voice budget: `VOICE_RESPONSE_BUDGET_SECONDS` − `RESERVED_STAGE_SECONDS` − `GATEWAY_OVERHEAD_SECONDS` (1.0 − 0.65 − 0.05 = 0.30 s for every in-call tool, reads and confirmed writes alike); explicit `READ_DEADLINE_SECONDS`/`WRITE_DEADLINE_SECONDS` above that share are refused unless `ALLOW_BUDGET_OVERRIDES=true` (diagnostics only). Short deadlines prove nothing about success latency; that needs the live measurement.

## Gotchas
- Don't `source` rollout.env; use `scripts/rollout-env.sh`.
- Test conftest strips every `Settings` field from the environment; pass overrides via `make_settings(...)`.
- The clients cap every exchange with `asyncio.timeout` (httpx timeouts are per phase); in-process stub tests rely on that, and `test_ops_client.py` has a real-TCP dribbling-server test.
