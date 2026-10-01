# Testing: locally, and what to expect

No database and no owner source are needed. The owner services are replaced at the HTTP boundary by
the development stubs in `services/mcp/dev/frontdesk_stubs` (contract-shaped fixtures with a fixed
clock, scripted board, injected failures and commit-then-drop scenarios). Stub-backed results prove
the adapter; they are not evidence about Manoj's or Shobhit's services.

| Command | What runs | Time | Needs |
|---|---|---|---|
| `make test-fast` | ruff; hermetic suites: contract snapshot/overlay/types, settings and production guards, trusted context and identity, operational and knowledge clients, stubs validated against the OpenAPI schemas, the four tools, the assembled server over HTTP (uvicorn) | ~10 s | uv |
| `make test-e2e` | `python -m frontdesk_stubs` and `frontdesk-mcp serve` as real processes over TCP; the release smoke; a full journey with trusted headers and the lifecycle bearer | ~5 s | uv |
| `./scripts/test.sh` (= `make test`) | all of the above plus the source/wheel build and, with a Docker daemon, the production image (asserting it contains neither stubs nor dev dependencies) | ~1–2 min | uv (+ Docker) |
| `OPS_E2E_MODE=mock\|live OPS_E2E_BASE_URL=… OPS_E2E_CLIENT_ID=… OPS_E2E_CLIENT_SECRET=… ./scripts/test.sh` | additionally the `external` gates: `tests/test_external.py` (owner API reads; the deterministic create→list→reschedule→cancel→summary journey and the negative UNKNOWN case only with `OPS_E2E_ALLOW_WRITES=1`, `OPS_E2E_WRITE_TENANT`, `OPS_E2E_DOCTOR_ID`, `OPS_E2E_UNKNOWN_DATE` on a designated synthetic live tenant; knowledge with `KNOWLEDGE_E2E_*`) and `tests/test_external_transport.py` (the deployed adapter over real MCP transport with `MCP_E2E_URL`, `MCP_E2E_BEARER`, `MCP_E2E_LIFECYCLE_BEARER`). A missing input fails the test with `BLOCKED: …`; nothing skips silently. Report which layer ran | — | owner test tenant and machine credentials; a deployed adapter |

Expect `== all suites passed`. CI runs `./scripts/test.sh` on every pull request and on `main`.

The hermetic suites run at a fixed moment (Thursday 1 October 2026, 10:00 IST) through an injected
clock, so a result never depends on when you run it.

## What the suites cover

- **Availability:** multiple windows and sessions preserved; LATE without double delay; CANCELLED
  visible; expectedEndTime expiry in facility time on the requested date; midnight weekday; UNKNOWN
  (stale, missing, future) → callback-only; board failure → COULD_NOT_CHECK; profile failure with a good
  board; ON_CALL; session scoping; ambiguity and incompleteness; department queries with one board call;
  no consultant; routing decisions from the trusted turn; routing outage/malformed/missing/slow never
  clear; directory/profile cached, board not.
- **Booking:** NOTED with frozen body and target-free key; confirmation; call/operation context; routing gate
  over the trusted turn plus `reasonVerbatim` before a create (and for a cancel/reschedule reason); live-board
  check before a create (UNKNOWN date → callback-only, board failure → COULD_NOT_RECORD) overlapping routing;
  same-intent replay; changed payload or target → conflict; concurrent same intent; validation before any call;
  owner rejection; lost response → UNCERTAIN then reconciliation by the same key; any failure after a sent
  attempt → UNCERTAIN; unavailable, malformed, auth; trusted number only (bare number unverified, dictated
  number never used); stricter verification policy; neutral not-found for another caller's appointment.
- **Knowledge:** verbatim answers, clarification, desk routing, no answer; failures never answers.
- **Summaries:** trusted timing; frozen body; replay; CALLBACK_NOTED rules; 500 characters without
  losing name/number; language mapping; transfer field rules; hang-up outcomes; failed persistence;
  lost response; wrong scope; independence from the knowledge service; lifecycle access gate.
- **Server:** three tools to the gateway bearer, one to the lifecycle bearer, none without; no trusted
  fields in schemas; snapshot of the tool surface; whole journey over HTTP; concurrent-call isolation;
  dependency status separate from local readiness; call id in logs and no caller data.
- **Release tooling:** smoke fails on unavailable dependencies, missing auth, failure envelopes, a
  wrong tool set or a leaky lifecycle boundary, and never writes; registration names four tools,
  forwards every trusted header and detects schema drift.

## Try it by hand

`make demo` walks the four tools against the stubs and prints every result. For a running stack
(`make up`), point an MCP client at `http://127.0.0.1:8100/mcp/` with `Authorization: Bearer
$MCP_BEARER_TOKEN` and the headers described in `LIVEKIT.md`; `curl http://127.0.0.1:8100/dependencies`
shows the owner-service status.
