# Implementation review report (1 October 2026)

Branch `Garry2012/mcp-external-api` → PR against `main`. Tested/reviewed code commit: **`e9c6bc5`**
(this report may be committed afterwards and references that SHA). Author: Claude Fable 5.1 acting as
lead implementation engineer under [FABLE-MASTER-PROMPT.md](../FABLE-MASTER-PROMPT.md). This is a
self-review plus three independent reviewer agents dispatched by the author; it is **not** the
architect's review the master prompt requests.

## Completion status

| State | Status |
|---|---|
| Code-ready | **Yes.** Four tools, independent owner clients, stubs, deploy tooling, retirement of the legacy backend; 271 tests green on a clean checkout without a database or owner source (269 hermetic + 2 process e2e); 4 `external` tests exist and were not run (no owner credentials) |
| Test-fixture-verified | **Yes.** Every acceptance area below has stub-backed tests; process-level e2e over TCP; release smoke passes against the stub processes |
| Real-service-verified | **No.** Manoj's backend (`healthcare-api`) is deployed and serves the pinned contract byte-for-byte, but refuses our unregistered client (401); Shobhit's service does not exist; only unauthenticated probes and the public contract mock were exercised |
| Production-cut-over | **No.** Nothing deployed: production configuration requires the owners' real hosts and credentials, which are not available; the voice platform still binds to the legacy REST API |
| Cloud-retired | **No destructive action executed.** Refreshed inventory and ordered action list in [AZURE-RETIREMENT-RESULTS.md](AZURE-RETIREMENT-RESULTS.md) |

## Target vs built

```
TARGET (TARGET-STATE.md)                               BUILT (this branch)
Caller ⇄ LiveKit agent ⇄ ContextForge ⇄ MCP            services/mcp: four tools over streamable HTTP; two bearers
  MCP ──HTTPS──▶ Manoj's operational API               ops_client.py: OAuth client-credentials, pooled, deadline-capped,
                                                         contract types (contract.py) pinned to the 30 Sep snapshot
  MCP ──HTTPS──▶ Shobhit's knowledge service           knowledge_client.py against knowledge_contract.py (PROVISIONAL)
  No DB / engine / fallback in MCP                     none; stubs live in dev/ (outside the image); production refuses stub hosts
  record_call_summary from the call-end lifecycle      lifecycle bearer → access.LifecycleGate (server-side)
  Legacy API + PostgreSQL retired from the repo        services/api, compose DB, migrations, seed, legacy docs removed
  Legacy Azure resources retired                       NOT DONE (gates unmet); inventory + command list prepared
```

## Reproducible checks

From a clean clone of the branch (Python 3.13, uv 0.11.21; Docker optional):

| Command | Result on `e9c6bc5` | Fixtures or real services |
|---|---|---|
| `./scripts/test.sh` | `== all suites passed` (see below) | fixtures (stubs) |
| `cd services/mcp && uv run ruff check . ../../deploy` | All checks passed | — |
| `cd services/mcp && uv run pytest tests -q -m "not e2e and not external"` | **269 passed** | in-process stubs (ASGI); the clients' own `asyncio.timeout` caps every exchange; one real-TCP dribbling-server test |
| `cd services/mcp && uv run pytest tests -q -m e2e` | **2 passed** | real processes over TCP (stubs + adapter), release smoke |
| `uv build --project services/mcp` | sdist + wheel | — |
| `docker build services/mcp` then `import frontdesk_stubs` / `import pytest` inside the image | both **absent** (image 80 MB) | — |
| `docker build -f services/mcp/dev/Dockerfile services/mcp` (stubs image for `make up`) | builds | — |
| production container with `OPS_BASE_URL` pointing at the contract mock | refuses to start (`points at a stub/mock endpoint`) | — |
| `make demo` | all four tools walked; outcomes AVAILABILITY, CALLBACK_REQUIRED, CLARIFICATION_NEEDED, NOTED, FOUND, ANSWERED, ROUTING_REQUIRED, STORED | stubs |
| `deploy/azure/deploy.sh rollouts/demo-hospital --dry-run` | full plan printed, no az login | — |
| `cd services/mcp && OPS_E2E_BASE_URL=… OPS_E2E_CLIENT_ID=… OPS_E2E_CLIENT_SECRET=… uv run pytest tests -m external` (4 tests) | **not run** (no owner credentials); without the variables the tests fail, they do not skip | real services — blocked |
| Smoke against a deployed adapter | **not run** (nothing deployed) | — |

Skipped/deselected: none silently. The `external` suite is run by `scripts/test.sh` only when `OPS_E2E_BASE_URL`
is set, and the script prints that it was not run otherwise; inside the suite one write-journey test is skipped
unless `OPS_E2E_ALLOW_WRITES=1` names a designated synthetic tenant (writes are never made to a real tenant).

## Requirement → code → test → evidence

| Area (master prompt table) | Code | Tests | State |
|---|---|---|---|
| Surface: exactly four tools, three conversational + controlled call-end | `tools.py`, `access.py`, `server.py` (`BearerAuth`), `prompt.SCHEMA_VERSION`, `cli.py schema` | `test_server.py` (three/one/none per principal, snapshot `tests/contracts/mcp-tools.snapshot.json`), `test_summary.py` gate tests, `test_e2e_processes.py` | fixture-verified; gateway/LiveKit discovery not verified (no gateway deployed) |
| Availability: windows/sessions, profile+board overlay, LATE/CANCELLED/NOT_CONFIRMED/UNKNOWN/ON_CALL, date/timezone/expiry, pagination/incompleteness, no slots | `availability.py`, `outcomes.py`, `cache.py`, `clock.py` | `test_availability.py` (31 cases) | fixture-verified |
| UNKNOWN: today/future/stale/missing → name/number, callback wording, summary-only; board failure → service error | `availability.py` (`_finish`, `Callback`), `summary.py` (CALLBACK_NOTED rules), `prompt.py` rule 4 | `test_availability.py::test_unknown_*`, `test_a_failed_board_*`, `test_summary.py::test_callback_*` | fixture-verified |
| Lookup: department ids, free-text match + clarification, explicit ISO dates, unsupported input | `availability.py::_resolve`, `_requested_date` | `test_availability.py` (ambiguous, bounded search, not found, department by name/id, unmatched, dates) | fixture-verified; real search semantics are Manoj's |
| Identity: override attempts, missing verification, number formats, family restriction, concurrent isolation | `context.py`, `identity.py`, `booking.py` | `test_context.py` (absent verification = unverified), `test_booking.py::test_list_cancel_reschedule_need_an_authorised_number` (incl. bare number), `test_a_dictated_number_never_reaches_a_lookup_or_change` (other-number/family refused), `test_server.py::test_the_model_cannot_supply_identity_or_lifecycle_fields`, `test_concurrent_calls_keep_their_own_identity` | fixture-verified; verification policy agreement open; delegated family access not implemented by design |
| Routing: named doctor + symptoms reaches Shobhit; blocks writes; changed context, missing/slow/malformed/outage never clear | `availability.py::routing`, `booking.py::_routing`, `knowledge_client.py` | `test_availability.py::test_routing_*`, `test_booking.py::test_create_waits_for_a_current_routing_clearance`, `test_the_callers_reason_reaches_routing_before_a_create`, `test_knowledge.py::test_the_trusted_turn_travels_with_the_question` | fixture-verified against the PROVISIONAL contract only |
| Mutations: success, validation/conflict, same-intent replay, changed payload/target, uncertain commit, dropped response, duplicate/concurrent, malformed success, auth rejection, total deadline, server-side board check | `booking.py`, `ops_client.py::_write` | `test_booking.py` (35 cases), `test_ops_client.py` (43 cases incl. real-TCP deadline) | fixture-verified; replay TTL/precedence with Manoj open |
| Summaries: call-end access, metadata after disconnect, frozen replay, 200/201, 500 chars, language, hang-up outcome, failed persistence | `summary.py`, `access.py` | `test_summary.py` (26 cases) | fixture-verified |
| Transport: independent pools/auth, token expiry/single-flight, mock/backend base paths, bounded retries, cancellation uncertainty, local readiness vs dependency status | `ops_client.py`, `knowledge_client.py`, `config.py`, `server.py` | `test_ops_client.py`, `test_settings.py`, `test_server.py::test_dependency_status_*` | fixture-verified; base-path handling also exercised against the Azure mock (bench) |
| Separation: clean checkout builds/tests without services/api, venv, PostgreSQL; no production fixtures or hidden engines | repo layout, `Dockerfile`, `.dockerignore`, `config.STUB_MARKERS`, `scripts/test.sh` | `test_stubs.py` (stubs are tables, not classifiers), `test_settings.py` (production refuses stubs), image checks in `scripts/test.sh` | verified locally and in CI definition |
| Voice: model calls the right tools with valid arguments and concise honest speech; interruptions/retries don't duplicate | `prompt.py`, `packs/healthcare.json`, operation keys | prompt policy tests in `test_server.py`; replay tests | **not verified with a model or a live call** |
| Operations: rollback, one appointment authority, scoped Azure inventory, shared-resource preservation, no obsolete references | `deploy/azure/deploy.sh`, `AZURE.md`, `AZURE-RETIREMENT-RESULTS.md` | straggler grep (no active references to the retired stack) | rollback procedure documented, **not tested**; Azure retirement **not executed** |

## Independent review and fixes

Three reviewer agents (Claude Opus; voice-safety, latency, architecture/correctness) reviewed commit
`895cd9f` read-only. The author re-graded every finding by its effect on a caller and fixed every
Critical and Important one in a single pass, each with a test that failed first (RED→GREEN) and a
green suite afterwards; Minor findings are deferred and listed. Fix commit: `e9c6bc5`.

### Fixed (Critical)

| Finding | Effect before the fix | Fix and test |
|---|---|---|
| A failure on the second write attempt after the first reached the owner was reported as definite (`COULD_NOT_RECORD`/`CONFLICT`) | A saved appointment told to the caller as "not recorded" → duplicate on callback | `ops_client._write`: once an attempt may have reached the owner, every later failure is `UncertainWrite`; `DecodingError` handled after send. `test_any_failure_after_a_sent_write_is_uncertain_not_definite` (7 cases) |
| Routing before CREATE saw only the current turn ("yes"), not the caller's relayed reason ("chest pain, my left arm is numb") | Red-flag symptom booked as a routine NOTED appointment | `reasonVerbatim` sent as `additionalText` with the routing request (PROVISIONAL contract extended); cancel/reschedule reasons routed when given. `test_the_callers_reason_reaches_routing_before_a_create` |
| Absent `X-Caller-Verification` was treated as `SIP_CALLER_ID`, which is the default accepted level | A bare number authorised LIST/CANCEL/RESCHEDULE (web/WhatsApp integrations) | Absent = unverified; `MCP_DEV_CALLER_NUMBER` only in development. `test_a_forwarded_number_without_a_verification_header_is_unverified`, `test_list_cancel_reschedule_need_an_authorised_number[bare number]` |
| The invocation deadline was not a wall-clock total: httpx applies the timeout per phase and per read chunk | A dribbling owner held a voice turn indefinitely (reproduced: 7.6 s with a 1 s budget) | `asyncio.timeout` around every exchange in both clients; token lock wait bounded. `test_the_deadline_is_a_wall_clock_total_even_against_a_dribbling_server` (real TCP) |

### Fixed (Important)

| Finding | Fix and test |
|---|---|
| UNKNOWN rule applied only when every session was UNKNOWN; unmatched session used the whole board permissively; department path ignored the session | Any UNKNOWN session in scope → callback-only; department honours the session. `test_any_unknown_session_in_scope_stops_the_journey`, `test_department_queries_honour_the_session_too` |
| Nothing server-side stopped a CREATE on an UNKNOWN date | CREATE reads the board for the visit date in parallel with routing; UNKNOWN → `CALLBACK_REQUIRED`, board failure → `COULD_NOT_RECORD`. `test_create_checks_the_board_server_side_and_refuses_an_unknown_date` (+ department, failure, overlap tests) |
| Department names matched by substring ("dentist" → ENT) | Exact normalised match or clarification. `test_department_names_match_exactly_or_ask` |
| A board with no row for the doctor made usual hours look bookable | No row = UNKNOWN (`BOARD_ENTRY_MISSING`). `test_a_board_that_omits_the_doctor_is_treated_as_unknown` |
| Profile/board waited for routing when the doctor was known; escalation waited for a slow directory read | Reads overlap routing and are cancelled on escalation. `test_known_doctor_reads_overlap_the_routing_check`, `test_an_escalating_routing_decision_is_not_delayed_by_a_slow_directory` |
| Token fetched lazily inside a caller's turn; lock wait unbounded | Warm at start-up, background refresher, bounded wait. `test_token_is_warmed_at_startup_and_refreshed_in_the_background`, `test_waiting_for_the_token_lock_is_bounded_by_the_callers_deadline` |
| Default deadlines (2 s/4 s/1.5 s) exceeded the 1 s turn budget | 1.2 s read, 2.5 s write, 0.8 s per exchange. `test_default_deadlines_fit_inside_a_one_second_turn_budget` |
| Write key included the target, so a retry with a changed doctor created a second appointment | Key = sha256(tenant\|call\|action\|operation). `test_a_changed_target_under_the_same_operation_is_a_conflict_not_a_second_appointment` |
| Only the caller's name was protected from the 500-character truncation | `requestedDate` and `doctorId` in the protected prefix. `test_callback_essentials_survive_truncation_as_structured_prefix` |
| `search_knowledge` forwarded only the model's question | Trusted turn travels with the question. `test_the_trusted_turn_travels_with_the_question` |
| Transient summary failure returned a terminal `RECORD_FAILED` | `RETRY_SAME_PAYLOAD` for transient reasons, `RECORD_FAILED` only for AUTH; documented in LIVEKIT.md. `test_transient_summary_failures_tell_the_platform_to_retry` |
| The SDK re-validated every result against a 6 KB output schema (~16 ms CPU per call) | Results returned as `CallToolResult` via `ToolResult(meta=…)` with explicit output schemas; schema version 2026-10-01.2. `test_results_carry_an_output_schema_and_structured_content_without_sdk_revalidation` |
| Unauthenticated `/dependencies?refresh=1` drove owner traffic per hit | Single-flight, 5 s minimum interval. `test_dependency_refresh_is_single_flight_and_throttled` |
| Stubs image did not build (`.dockerignore` excluded `dev/`), so `make up` was broken | `dev/Dockerfile.dockerignore`; built in `scripts/test.sh` |
| `pytest -m external` selected nothing, yet docs claimed real-service suites | `tests/test_external.py` (fails without credentials, never skips). `test_an_external_suite_exists_for_owner_designated_services` |
| Family/other-number restriction untested | `test_a_dictated_number_never_reaches_a_lookup_or_change` |
| `transferredTo` validated as an id (rejects "Front desk"); availability `date` accepted `20261005` | Length-only validation; strict ISO regex. `test_transferred_to_is_free_text_up_to_64_characters`, `test_dates_are_today_or_explicit_iso[20261005]` |

### Deferred (Minor, not fixed)

- `_department` gather without `return_exceptions` can leave a sibling task running until its own timeout.
- Directory cache lookups are not single-flight at TTL expiry; `TokenCache.invalidate()` may discard a token another call just refreshed; a token margin ≥ `expires_in` would refresh on every call.
- No response-size cap; the contract's `findAppointments` has no `limit` parameter.
- The bench includes client-side schema checking and shares the server's event loop; session set-up is not timed separately ("warm" refers to the token).
- Trusted utterance cut at 1,000 characters before routing.
- `register.py` drift check compares parameter names only; a rotated `auth_token` is not pushed on the already-registered path.
- `CONFIRMED_BY_DESK` collapsed into `NOTED`; an action/status mismatch is not treated as UNCERTAIN.
- Test-quality notes: the overlap tests assert timing, not interleaving; the slow-write test asserts the outcome; the summary 409 path is unreachable with the stub's callId precedence.

### Reviewer items set aside (rulings)

- A fully CANCELLED session today still returns `OFFER_APPOINTMENT_REQUEST` for another date (product decision; recorded as a question for the owner).
- Board `note` text typed by hospital staff is passed to the model (owner data, not upstream error prose).
- English callback wording is fixed pending a localisation agreement.
- Rejecting an over-long summary would lose the callback at call end; the structured prefix approach was chosen instead.

## Remaining risks

- Everything owner-facing is proven against fixtures that encode our reading of the contract; Manoj's
  real validation, replay and search semantics may differ (open dependencies 1, 5).
- The routing gate makes availability and CREATE unusable until Shobhit's service exists and the voice
  platform forwards `X-Turn-Context`; this is by design (no local clearance) but it is a hard
  dependency for any live use (open dependencies 2, 3).
- Latency targets are unproven; the only real-network numbers come from a laptop to the contract mock.
- The legacy API still serves the deployed voice platform; retirement waits on cutover.

## Where things are

- Rulings taken during implementation and in the fix pass are listed in the PR description.
- Evidence: [evidence/](evidence/) (bench JSON); Azure inventory and Log Analytics extracts in
  [AZURE-RETIREMENT-RESULTS.md](AZURE-RETIREMENT-RESULTS.md); latency in [LATENCY-RESULTS.md](LATENCY-RESULTS.md);
  dependencies in [OPEN-DEPENDENCIES.md](OPEN-DEPENDENCIES.md).
