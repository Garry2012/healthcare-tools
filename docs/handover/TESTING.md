# Testing: locally, and what to expect

No database and no owner source are needed. The owner services are replaced at the HTTP boundary by
the development stubs in `services/mcp/dev/frontdesk_stubs` (contract-shaped fixtures with a fixed
clock, scripted board, injected failures and commit-then-drop scenarios). Stub-backed results prove
the adapter; they are not evidence about Manoj's or Shobhit's services.

| Command | What runs | Time | Needs |
|---|---|---|---|
| `make test-fast` | ruff; hermetic suites: contract snapshot/overlay/types, settings and production guards, trusted context and identity, operational and knowledge clients, stubs validated against the OpenAPI schemas, the four tools, the assembled server over HTTP (uvicorn) | ~30 s | uv |
| `make test-e2e` | `python -m frontdesk_stubs` and `frontdesk-mcp serve` as real processes over TCP; the release smoke; a full journey with trusted headers and one gateway bearer | ~5 s | uv |
| `./scripts/test.sh` (= `make test`) | all of the above plus the source/wheel build and, with a Docker daemon, the production image (asserting it contains neither stubs nor dev dependencies) | ~1–2 min | uv (+ Docker) |
| `scripts/run-profile.sh live -- ./scripts/test.sh` (or `mock`) | additionally the `external` gates: `tests/test_external.py` (owner API reads; the deterministic create→list→reschedule→cancel→summary journey and the negative UNKNOWN case only with `OPS_E2E_ALLOW_WRITES=1`, `OPS_E2E_WRITE_TENANT`, `OPS_E2E_DOCTOR_ID`, `OPS_E2E_VISIT_DATE`, `OPS_E2E_RESCHEDULE_DATE` on a designated synthetic live tenant; knowledge with `KNOWLEDGE_E2E_*`) and `tests/test_external_transport.py` (the deployed adapter over real MCP transport with `MCP_E2E_URL`, `MCP_E2E_BEARER`). A missing input fails the test with `BLOCKED: …`; nothing skips silently. Report which layer ran | — | owner test tenant and machine credentials; a deployed adapter |

The profile launcher reads current owner credentials from the selected Key Vault without printing
values. Knowledge URL/token aliases are propagated to tests and benchmarks as well as runtime.
Live writes require the authenticated token's tenant to equal the owner-designated
`OPS_E2E_WRITE_TENANT`; missing or mismatching identity blocks writes. The owner must independently
confirm the tenant is synthetic. The positive journey uses `OPS_E2E_VISIT_DATE` and `OPS_E2E_RESCHEDULE_DATE`, both owner-designated
future usual working days for the selected doctor; it does not infer a time or request future boards.
The negative gate uses facility today and a doctor with UNKNOWN/NOT_CONFIRMED today.
The benchmark also defaults to read-only against external services; explicit test writes require
`BENCH_ALLOW_WRITES=1` and a matching `BENCH_WRITE_TENANT` under the live profile.

Expect `== all suites passed` for the local run. CI runs `./scripts/test.sh` on every pull request and on `main`.
With a profile loaded the script also runs the `external` gates and exits non-zero whenever any gate is BLOCKED
(by design: with the mock profile today the write, knowledge and deployed-transport gates are BLOCKED).

The hermetic suites run at a fixed moment (Thursday 1 October 2026, 10:00 IST) through an injected
clock, so a result never depends on when you run it.

## What the suites cover

- **Availability:** all five owner statuses retained alongside MCP decision/reason; today board only;
  supplied end time expiry in facility time; midnight boundaries; UNKNOWN/NOT_CONFIRMED callback;
  CANCELLED/ended unavailable; failed reads honest; ON_CALL callback. Future availability and
  WORKING_HOURS read profiles only, never boards. Missing date is DATE_REQUIRED for availability,
  allowed for working hours. Single-doctor on-call/empty hours return full callback metadata; hours-only
  results have zero bookableFound and a neutral next step. Future unmatched sessions retain same-day
  alternatives and cannot match another weekday. Mixed decisions require selection; equal decisions do not.
  Sorted department batches stop at the limit, deadline or exhaustion. Failed/unchecked candidates
  mean incomplete; incomplete absence is handoff. Counts include all attendance types.
  No knowledge calls, including with knowledge unconfigured. Directory/profile cached, board not.
- **Booking:** doctor-only CREATE; RESCHEDULE derives the verified appointment's doctor. Shared policy
  before writes; no end time plus a specific requested time is handoff, no write. Future usual days
  can record NOTED; nested owner status is preserved. LIST/CANCEL, caller confirmation, verification,
  stable frozen operation identity and uncertainty are regression-covered. No new operation on an
  uncertain result; failed reads never become negative attendance facts.
- **Knowledge:** one explicit exchange; verbatim answers and clarification; department, desk and emergency
  decisions; routing speech only once; malformed optional fields cannot erase a valid transfer decision;
  non-JSON and malformed responses fail honestly; external cancellation propagates and failure logs omit caller words.
- **Summaries:** trusted call/start headers; exact whole-call text; nonblank/500 boundary and in-band
  501–2000 refusal; CALLBACK_NOTED mobile/ID rules; language/transfer rules; five compact outcomes;
  verified 201 and same-call 200 even with changed payload; wrong-call/malformed success uncertainty;
  no header idempotency key, same-body retry and commit-then-drop deduplication; 401-only refresh,
  definite 403 refusal and prior uncertainty precedence; no private input in logs; independent deadline.
- **Server:** all four tools to the gateway bearer, none without; no trusted
  fields in schemas; snapshot of the tool surface; whole journey over HTTP; concurrent-call isolation;
  dependency status separate from local readiness; call id in logs and no caller data.
- **Release tooling:** smoke fails on unavailable dependencies, missing auth, failure envelopes, a
  wrong tool set, and never writes; registration names four tools,
  forwards every trusted header and detects full input-schema drift (including required fields and the summary length cap).

## Try it by hand

`make demo` walks the four tools against the stubs and prints every result. For a running stack
(`make up`), point an MCP client at `http://127.0.0.1:8100/mcp/` with `Authorization: Bearer
$MCP_BEARER_TOKEN` and the headers described in `VOICE-TEAM.md`; `curl http://127.0.0.1:8100/dependencies`
shows the owner-service status.

Current call-summary evidence: [implementation hand-back](mcp-only/implementation/CALL-SUMMARY-HAND-BACK.md)
links red/green output and the final full run. HTTP privacy tests verify malformed summary arguments
never echo submitted values or unexpected field names in protocol errors or logs, and send no owner
write. Framework validation is unchanged; only summary error presentation is redacted. The 2000
outer cap and 500 in-band limit remain tested. Live service and voice acceptance are separate.

Availability evidence: [revision 6 hand-back](mcp-only/implementation/AVAILABILITY-POLICY-HAND-BACK.md).
`make bench` reports today doctor/department and future department cold/warm with successful-outcome
checks, default 0.30 s deadline, profile-read counts and no future board reads. These in-process stub
numbers omit Azure, gateway and audio latency. Real-host future benchmarking additionally needs
`BENCH_FUTURE_DATE`, a future usual working date. No live writes are part of the local reviewer run.

Review-fix evidence: [availability review hand-back](mcp-only/implementation/AVAILABILITY-REVIEW-FIX-HAND-BACK.md).
Known-name on-call queries prove zero board reads; malformed owner doctor IDs return COULD_NOT_RECORD
without reschedule writes; smoke accepts WORKING_HOURS or honest HANDOFF_REQUIRED for the hours probe.
No overnight behavior, G-1 session-choice change or optional M-7 fact expansion is tested as implemented.
