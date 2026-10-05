# Front-desk MCP adapter (voice agent tools)

Four MCP tools for calling applications, consuming two owner services over HTTPS. This repository
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
- No backend scheduling engine, slot, capacity, interpretation, knowledge or clinical logic; no database, queue or local fallback backend. The adapter validates, authenticates, forwards trusted context, applies deadlines, maps contracted schedule facts through the approved availability policy and composes contracted reads.
- Trusted context (`X-Call-Id`, `X-Caller-Number`, `X-Caller-Verification`, `X-Operation-Id`, `X-Call-Started-At`) comes only from request headers. All four tools require the gateway bearer. Never from tool arguments.
- Availability and every booking action call only Manoj. search_knowledge is an explicit tool for hospital information or symptoms; that tool makes one knowledge request with verbatim question and language. No optional routing gate, transcript header, local classifier or fallback. Voice-agent behaviour, prompts, guardrails and SDK integration belong to the voice team; the published interface is docs/handover/VOICE-TEAM.md. reasonVerbatim is forwarded to Manoj without interpretation.
- Schedule facts map through one pure `availability_policy.py` and one shared `schedule_reader.py`. Today uses only fresh live-board facts; future dates and WORKING_HOURS use usual schedules and never read the board. ON_CALL always requires callback. Today UNKNOWN/NOT_CONFIRMED require callback; CANCELLED or a supplied passed end time is NOT_AVAILABLE. Failed reads are failures, not UNKNOWN. Owner `status` and MCP `decision` remain distinct.
- CREATE requires doctorId; RESCHEDULE derives the doctor from the verified caller's appointment. Department writes are absent. Different session decisions with no selected session/time require a choice; equal decisions permit a day-level request. A specific time in a bookable session with no end time produces HANDOFF_REQUIRED/TIME_NOT_VERIFIABLE without a write. No end time is invented.
- CREATE and RESCHEDULE return NOTED, never confirmed (the nested appointment retains the owner's status). Writes need callerConfirmed, call id and operation id; the body remains frozen and keyed by sha256(tenant|call|action|operation). Booking uncertainty remains UNCERTAIN; summary uncertainty remains NOT_CONFIRMED. One same-key retry at most, within the invocation deadline; refresh only on 401.
- WORKING_HOURS for a single on-call doctor or empty schedule uses the full callback result. A doctor with hours returns PRESENT_WORKING_HOURS; bookableFound is always zero for hours-only queries. Department hours keep on-call facts within the cap. Sessions crossing midnight are unsupported.
- Callback metadata is reason plus summaryOutcome=CALLBACK_NOTED. MCP creates no callback task or telephone transfer. Summary text may include the name, date, session and callback reason; their presence is not enforced by the summary service.
- Caller authority for LIST/CANCEL/RESCHEDULE is the verified caller number under the configured country rule, with an explicit `X-Caller-Verification` in the accepted set; a bare number is unverified. A dictated mobile is contact data. No prefix stripping, never "the last ten digits".
- `record_call_summary` is LLM-callable with the same gateway bearer as the other three tools. Exact whole-call summaryText is required, nonblank and at most 500 characters; no text composition or truncation. Call ID and start time come from headers. The first accepted summary is final; same-call owner 200 means ALREADY_SAVED, even with a different payload. Summaries send no Idempotency-Key and no duration; MCP stays stateless.
- Results never carry caller numbers, reasons, raw upstream error prose or secrets; logs carry none of those and no patient names. Two documented exceptions in results: the `patientName` of the verified caller's own appointments (needed to pick one; the number holder is authorised to hear names registered under that number) and the desk-authored board `note` (≤200 chars, written for callers). Request-URL loggers stay at WARNING.
- Contract changes are reviewed changes: the pinned snapshot, its hash, the overlay and `contract.py` literals are asserted by tests. Stubs (`services/mcp/dev/`) are fixtures, never engines; production refuses stub/mock hosts.
- Domain words live in `packs/healthcare.json`; tenant identity (timezone, calling code, languages) in `rollouts/<id>/rollout.env` with no defaults.

- Deadlines derive from the voice budget: `VOICE_RESPONSE_BUDGET_SECONDS` − `RESERVED_STAGE_SECONDS` − `GATEWAY_OVERHEAD_SECONDS` (1.0 − 0.65 − 0.05 = 0.30 s for scheduling/knowledge, reads and confirmed booking writes alike); explicit `READ_DEADLINE_SECONDS`/`WRITE_DEADLINE_SECONDS` above that share are refused unless `ALLOW_BUDGET_OVERRIDES=true` (diagnostics only). Summaries retain their separate SUMMARY_DEADLINE_SECONDS budget (default 8 s), including exchanges/retry; they are not a 300 ms promise. Short deadlines prove nothing about success latency; that needs the live measurement.

## Gotchas
- Don't `source` rollout.env; use `scripts/rollout-env.sh`.
- Test conftest strips every `Settings` field from the environment; pass overrides via `make_settings(...)`.
- The clients cap every exchange with `asyncio.timeout` (httpx timeouts are per phase); in-process stub tests rely on that, and `test_ops_client.py` has a real-TCP dribbling-server test.
