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
- Availability and CREATE wait for a current routing clearance from the knowledge service on the trusted turn. Missing context, outage or an unknown response is never clearance.
- UNKNOWN board (today or later) stops the appointment journey: collect name and callback number, say someone will call back, record a CALLBACK_NOTED summary. No booking, transfer, alternate or task. A failed board read is COULD_NOT_CHECK, not UNKNOWN.
- A create is NOTED, never confirmed. Writes need `callerConfirmed`, call id and operation id; the body is frozen and keyed by `sha256(tenant|call|action|target|operation)`. UNCERTAIN is a distinct outcome; one same-key retry at most, within the invocation deadline.
- Caller authority for LIST/CANCEL/RESCHEDULE is the verified caller number under the configured country rule. A dictated mobile is contact data. No prefix stripping, never "the last ten digits".
- `record_call_summary` is reachable only with the lifecycle bearer; MCP stays stateless; the platform owns durable finalization and retries.
- Results and logs never carry caller numbers, patient names, reasons, raw upstream prose or secrets. Request-URL loggers stay at WARNING.
- Contract changes are reviewed changes: the pinned snapshot, its hash, the overlay and `contract.py` literals are asserted by tests. Stubs (`services/mcp/dev/`) are fixtures, never engines; production refuses stub/mock hosts.
- Domain words live in `packs/healthcare.json`; tenant identity (timezone, calling code, languages) in `rollouts/<id>/rollout.env` with no defaults.

## Gotchas
- Don't `source` rollout.env; use `scripts/rollout-env.sh`.
- Test conftest strips every `Settings` field from the environment; pass overrides via `make_settings(...)`.
- In-process stub transports enforce request timeouts (tests/harness.py) so deadline tests are real.
