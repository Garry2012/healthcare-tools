# Implementation review report (1 October 2026)

Branch `Garry2012/mcp-external-api` → PR #11 against `main`. Tested code commit after the architect's
re-review pass: **`d1ec197`** (earlier passes: `e9c6bc5` self-review fixes, `04e282b` AR-01..08, `4af9628` follow-ups; reports
may be committed afterwards and reference the code SHA). Author: Claude Fable 5.1 acting as
lead implementation engineer under [FABLE-MASTER-PROMPT.md](../FABLE-MASTER-PROMPT.md). This is a
self-review plus three independent reviewer agents dispatched by the author; it is **not** the
architect's review the master prompt requests.

## Architect correction pass (ARCHITECT-REVIEW.md, AR-01 … AR-08)

All eight findings are addressed in commit `04e282b`; each has a regression test that failed before the
change and passes after. Environments: all tests below are fixture/mock based unless stated; see
"Environments tested" for exactly what reached a network.

| Finding | Resolution | Regression tests |
|---|---|---|
| AR-01 silent truncation of the trusted utterance | `context.py`: no truncation; `UTTERANCE_MAX` = 4,000 as an agreed size limit; an oversized, malformed or missing context sets `turn_failure` and every routed tool returns ROUTING_UNAVAILABLE with that detail (never clearance) | `test_context.py::test_a_long_trusted_utterance_is_preserved_whole`, `::test_an_oversized_turn_context_is_refused_not_truncated`; `test_booking.py::test_the_decisive_tail_of_a_long_utterance_still_blocks_the_create` (the architect's 1,177-char probe), `::test_an_oversized_turn_context_refuses_the_write` |
| AR-02 symptom routing through `search_knowledge` | `knowledge.py`: the owner's routing decision over the trusted turn (plus the question) runs concurrently with the answer call and is awaited first; EMERGENCY/DESK/CLARIFY → ROUTING_REQUIRED (answer discarded), ROUTE_DEPARTMENT/CONTINUE → answer returned with `routing`; missing turn or routing failure → ROUTING_UNAVAILABLE. Clinical reasoning stays in Shobhit's service (PROVISIONAL contract) | `test_knowledge.py::test_a_danger_sign_in_the_trusted_turn_routes_before_any_answer`, `::test_department_routing_is_returned_with_the_answer`, `::test_clarification_from_routing_takes_precedence`, `::test_plain_faq_is_answered_once_routing_clears`, `::test_knowledge_without_a_routing_decision_is_not_an_answer[…]`, `::test_answer_service_problems_are_could_not_check_never_an_answer[…]` |
| AR-03 session filter dropped sessionless UNKNOWN rows | `availability.py::_department`: a row without a session label (the owner's UNKNOWN/missing shape) stays in scope; only labelled rows for other sessions exclude a doctor | `test_availability.py::test_department_session_query_keeps_a_sessionless_unknown_row`, `::test_department_session_query_with_a_missing_row_is_unknown_too`, `::test_doctor_session_query_with_a_sessionless_stale_row_is_unknown`, `::test_a_doctor_who_simply_lacks_the_session_is_not_unknown` |
| AR-04 booking scope inconsistent with availability | `booking.py`: CREATE accepts `session`; scope = chosen session → window holding `preferredTime` → whole day; UNKNOWN in scope → CALLBACK_REQUIRED; unresolved scope with mixed statuses → `CLARIFICATION_NEEDED` / `ASK_WHICH_SESSION` listing the day's sessions (no slot engine) | `test_booking.py::test_create_scope_follows_the_session_the_caller_chose` (journey from the availability result), `::test_create_without_a_session_resolves_scope_from_the_preferred_time_or_asks`, `::test_unknown_in_an_unrelated_session_does_not_block_a_scoped_create` |
| AR-05 upgrade of an existing Container App | `deploy/azure/deploy.sh`: the update branch runs `identity assign`, `registry set` and `secret set` (all five Key Vault references) before `update --replace-env-vars`; legacy secrets stay until retirement; `DEPLOY_ASSUME_EXISTING=1` makes a dry run exercise the upgrade path | `test_deploy.py::test_upgrading_an_existing_app_attaches_the_new_secrets_before_switching_env` (dry run of the upgrade path; not run against Azure) |
| AR-06 deadlines did not enforce the voice budget | `config.py`: `VOICE_RESPONSE_BUDGET_SECONDS` (1.0) − `RESERVED_STAGE_SECONDS` (0.65) derives the read deadline (0.35 s) and per-exchange cap; write ≤ 0.6 s; explicit values are diagnostic overrides; a budget that leaves < 0.1 s is refused. Slow multi-stage and uncertain-write paths tested with injected delays | `test_settings.py::test_tool_deadlines_derive_from_the_voice_budget`; existing `test_booking.py::test_total_deadline_bounds_a_slow_write`, `test_availability.py::test_routing_problems_never_become_clearance[slow]`, `test_ops_client.py::test_the_deadline_is_a_wall_clock_total_even_against_a_dribbling_server` |
| AR-07 benchmark counted refused calls as successes | `dev/bench.py`: sends `X-Caller-Verification`; each scenario declares its intended outcomes and the owner paths it must hit; a sample counts only when both are observed (stub mode records owner calls); other outcomes are reported as `rejected_or_failed` with their labels | rerun: all six scenarios 50/50 ok with owner calls verified (`evidence/bench-stubs-c1-verified-outcomes-20261001.json`) |
| AR-08 vacuous external assertions | `tests/test_external.py` rewritten: `or True` removed; `OPS_E2E_MODE=mock|live` required; a missing input fails with `BLOCKED: …`; deterministic positive journey create→list→reschedule→cancel→summary→replay only with `OPS_E2E_ALLOW_WRITES=1` on `OPS_E2E_WRITE_TENANT` (live only); negative UNKNOWN-date case separate; `tests/test_external_transport.py` adds the deployed-adapter gate (smoke + trusted-header forwarding over real MCP transport) | run against the public contract mock (`OPS_E2E_MODE=mock`): 3 read gates PASSED; write/knowledge/transport gates reported BLOCKED (see "Environments tested") |

Reconciled with the architect's own actions: three legacy jobs deleted and two generated test secrets created in the
shared vault (rejected by the live backend); recorded in AZURE-RETIREMENT-RESULTS.md and OPEN-DEPENDENCIES.md, not repeated.

## Architect follow-up (PR #11 at 17d86b1): five corrections

| Item | Resolution | Regression evidence |
|---|---|---|
| 1 UNKNOWN in doctor-specific session filtering | `availability.py` doctor path keeps unlabelled rows next to the matched session (same rule as the department path) | `test_availability::test_doctor_session_query_keeps_an_unlabelled_unknown_row_next_to_a_matched_session`; journey `test_booking::test_availability_and_create_agree_when_an_unlabelled_unknown_row_is_present` (both CALLBACK_REQUIRED, no write, callback wording) |
| 2 Budget: 0.6 s write + 0.65 s reserved > 1 s | Every in-call tool (read and confirmed write) gets budget − reserved − gateway overhead = 1.0 − 0.65 − 0.05 = **0.30 s**; overrides above the share are refused unless `ALLOW_BUDGET_OVERRIDES=true` (tests/bench/external runs set it explicitly). Short deadlines are not evidence that successful responses meet the target; live measurement still required | `test_settings::test_every_in_call_tool_deadline_fits_the_voice_budget_including_the_gateway`, `::test_tool_deadlines_derive_from_the_voice_budget` |
| 3 One configuration mechanism | `deploy/environments/{mock,live}.env` (non-secret: OPS_BASE_URL, mode, secret *names*, subscription `4e1c…`, `healthcare-rg`, env/ACR/vault/identity) loaded by `scripts/env.sh <profile>` for deploy, external gates and bench; `live.env` is blank → refused with "awaiting live integration"; `deploy.sh --profile` required, subscription checked, no RG default/creation; dummy-credential replacement documented (`deploy/environments/README.md`) | `test_deploy::test_deployment_targets_only_the_profiles_resource_group_and_never_creates_one`, `::test_the_live_profile_is_refused_while_its_base_url_is_blank_and_mock_cannot_deploy`, `::test_upgrading_an_existing_app_…` |
| 4 Assertions | `tests/gates.py` predicates: LIST must be FOUND/NOT_FOUND before inspection; negative case compares a successful baseline; transport test split into header-forwarding (COULD_NOT_CHECK tolerated) and backend-lookup (FOUND/NOT_FOUND only) | `test_gate_assertions.py` (4 tests prove COULD_NOT_CHECK, IDENTITY_UNAVAILABLE, ROUTING_UNAVAILABLE and a created appointment cannot pass); `test_external.py`, `test_external_transport.py` use the predicates |
| 5 Cleanup plan | Resource-ID inventory with ownership evidence (createdBy/tags/names), consumers, shared flag, disposition and prerequisites; voice-team secrets removed from our list; shared server/environment/registry/vault/identity (also used by Manoj's apps) retained; `frontdesk` data disposition requires owner-confirmed inventory; nothing executed | `AZURE-RETIREMENT-RESULTS.md` |

## Re-review (three fresh reviewers on 745c99b) and third fix pass

Commit `d1ec197`. Findings re-graded by effect; everything Important fixed with a failing-first test; Minors deferred.

| Finding (reviewer) | Resolution | Regression evidence |
|---|---|---|
| In-call per-exchange cap (0.30 s) also throttled the after-call summary write and the background/start-up token refresh (latency 1–2, safety 7, arch 1) | `Deadline(cap=…)`: summaries use their own 8 s budget/cap; token refresh has `TOKEN_REFRESH_TIMEOUT_SECONDS` (5 s); the in-call cap applies only to in-call tools | `test_ops_client::test_summary_writes_use_their_own_cap_not_the_in_call_share`, `::test_background_token_refresh_has_its_own_timeout`, `test_summary::test_a_slow_but_healthy_owner_still_stores_the_summary` |
| Usable token waited behind a refresh lock (latency 3) | returned without waiting while a refresh is in flight | `::test_a_usable_token_is_returned_without_waiting_for_a_refresh_in_progress` |
| Same-key retry impossible under the 0.30 s budget (latency 4, safety 8) | threshold = max(50 ms, 1.5 × first attempt) | `::test_same_key_retry_happens_when_the_first_attempt_failed_instantly` |
| 5xx on the first attempt of a sent write reported definite (safety 3) | any 5xx after a write left → UNCERTAIN; 429 stays definite | `::test_a_5xx_on_a_sent_write_is_uncertain_even_on_the_first_attempt`, updated `test_server_errors_after_a_write_was_sent_are_uncertain` |
| Override guard read the raw env string (latency 7, arch 4) | after-validator on the parsed bool | `test_settings::test_budget_override_flag_is_parsed_as_a_boolean_from_the_environment` |
| Equal bearers allowed in staging (safety 11) | distinct outside development | `::test_lifecycle_and_gateway_bearers_must_differ_outside_development` |
| 200 on `/call-summaries` for a different summary reported as DONE (safety 5) | intent/outcome(/callerMobile) compared → CONFLICT `CALL_ID_ALREADY_USED` | `test_summary::test_a_200_for_a_different_summary_under_the_same_call_id_is_a_conflict_not_done` |
| Department CREATE ignored session/time; time outside the chosen window accepted; whole-day/unmatched scope answered differently from availability (safety 1, arch 2) | one shared rule `board_scope.py` for availability, CREATE and RESCHEDULE; department scope per doctor; time outside window → INVALID; unresolved scope with any UNKNOWN → callback in both tools (ASK_WHICH_SESSION removed) | `test_booking::test_department_create_uses_the_same_session_scope_as_availability`, `::test_a_preferred_time_outside_the_chosen_session_window_is_rejected`, `::test_unresolved_scope_with_any_unknown_is_callback_for_create_as_for_availability` |
| Missing row for a session the profile lists today treated as "no such session" (safety 2) | missing promised row = UNKNOWN (`SESSION_ROW_MISSING`) in availability and CREATE (profile read for the scope rule) | `test_availability::test_a_missing_row_for_a_usual_session_today_is_unknown`, `test_booking::test_a_missing_row_for_a_usual_session_today_is_unknown_for_create_too` |
| RESCHEDULE skipped the board (safety 4) | gate on the new date for the appointment's doctor/department (LIST → board) | `test_booking::test_reschedule_checks_the_board_for_the_new_date`, `::test_reschedule_of_an_unknown_appointment_is_still_the_owners_neutral_not_found` |
| Profile failure + no board row → NOT_FOUND (safety 9, arch 7) | COULD_NOT_CHECK `PROFILE_UNAVAILABLE` | `test_availability::test_profile_failure_with_no_board_row_is_could_not_check_not_not_found` |
| Single-match search waited for routing before profile/board (latency 6) | profile ∥ board start inside the prefetch | `test_availability::test_single_match_search_starts_profile_and_board_before_routing_finishes` |
| `eval` swallowed env.sh's refusal; blank profile values overwrote exports; script created shared infra; bash 3.2 quoting; in-place upgrade of the live app (arch 3, 6, 11, 12) | `deploy.sh` unsets inherited values, stops on profile failure, requires the shared resources, checks the subscription (simulated in dry runs), messages without apostrophes; `live.env` targets `mcp-demo-hospital-canary` | `test_deploy.py` (profile/RG/infra/subscription/eval tests) |
| External negative test unchanged, availability gate counted as passed without a knowledge host, `except … pass` (arch 5, 10, 17) | gate predicates applied; availability gate BLOCKED without a knowledge host; `contextlib.suppress` warm-up | `tests/test_external.py`, `tests/test_gate_assertions.py` |
| Bench attribution and claims (latency 5, arch 9) | owner calls attributed by call id, knowledge routing verified, over-budget count, CREATE scenario, credentials from the profile's `OPS_E2E_*` | `evidence/bench-stubs-c5-rereview-20261001.json` (7 scenarios, c=5, 0 rejected, 0 over 300 ms) |
| `.env.example`/compose missing the new settings; exported profile URL repointed `make up` (arch 13) | settings documented; compose reads `COMPOSE_*` | `docker compose config` |
| Stale report statements (arch 8, 14, 15) | corrected in this report, LIVEKIT, ONBOARDING, AZURE, TESTING | — |
| `patientName` in results and board `note` to the model (safety 6, 10) | documented exceptions in CLAUDE.md (verified caller's own appointments; desk-authored note) — policy ruling, not a code change | — |

Deferred (Minor): pool/connect-phase timeout reported as UNCERTAIN; cancellation hygiene of background tasks; wall-clock timing thresholds in three tests (loosened once); whether a 4,000-character base64 header survives every gateway; the knowledge contract remains provisional.

## Environments tested

| Layer | Endpoint | Auth | What ran | Result |
|---|---|---|---|---|
| In-process stubs | ASGI, no network | stub client credentials | hermetic suites, bench | 319 passed; bench 7/7 scenarios 30/30 at c=5 with owner + routing calls verified, 0 over 300 ms |
| Real processes over TCP | `127.0.0.1` stubs + adapter | stub credentials, gateway and lifecycle bearers | `pytest -m e2e`, release smoke | 2 passed |
| **Public contract mock (Prism)** | `https://healthcare-contract-mock.icytree-6543aaa9.centralindia.azurecontainerapps.io` (no `/api/v1`), selected by `eval "$(scripts/env.sh mock)"` | `POST /auth/token` issues the example token for any client credentials; `401` without a bearer; any bearer accepted on reads | `pytest -m external` at `4af9628`: token issuance + departments/doctors/board reads, absent-bearer refusal, availability tool (ROUTING_UNAVAILABLE without a knowledge host); writes/knowledge/transport gates report BLOCKED | 3 PASSED, 6 BLOCKED (the fixture now warms the mock first; a first attempt that overlapped the full test script hit its cold start and was rerun) — **mock verification only: static example bodies, no state** |
| **Live backend** | `https://healthcare-api.icytree-6543aaa9.centralindia.azurecontainerapps.io/api/v1` | registered machine client required | unauthenticated probes only (`401 Missing bearer token`, `401 Invalid client credentials`); served OpenAPI hash `6f827be1…` differs from the pin `b8f28271…` in the `servers` entry only (evidence file kept) | **not verified** (no registered credentials); status: awaiting live integration |
| Knowledge service | — | — | — | **BLOCKED** (no contract/host) |
| Deployed adapter transport | — | — | `test_external_transport.py` | **BLOCKED** (adapter not deployed with the new image) |

## Completion status

| State | Status |
|---|---|
| Code-ready | **Yes.** Four tools, independent owner clients, stubs, deploy tooling, retirement of the legacy backend; 321 tests green on a clean checkout without a database or owner source (319 hermetic + 2 process e2e); 9 `external` gate tests exist: 3 passed against the public contract mock (mock mode), 6 report BLOCKED without registered live credentials, a knowledge host or a deployed adapter |
| Test-fixture-verified | **Yes.** Every acceptance area below has stub-backed tests; process-level e2e over TCP; release smoke passes against the stub processes |
| Real-service-verified | **No.** Manoj's backend (`healthcare-api`) is deployed and serves the pinned contract (differing only in the `servers` entry), but refuses our unregistered client (401); Shobhit's service does not exist; only unauthenticated probes and the public contract mock were exercised |
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

| Command | Result (latest tested commit) | Fixtures or real services |
|---|---|---|
| `./scripts/test.sh` | `== all suites passed` (see below) | fixtures (stubs) |
| `cd services/mcp && uv run ruff check . ../../deploy` | All checks passed | — |
| `cd services/mcp && uv run pytest tests -q -m "not e2e and not external"` | **319 passed** | in-process stubs (ASGI); the clients' own `asyncio.timeout` caps every exchange; one real-TCP dribbling-server test |
| `cd services/mcp && uv run pytest tests -q -m e2e` | **2 passed** | real processes over TCP (stubs + adapter), release smoke |
| `uv build --project services/mcp` | sdist + wheel | — |
| `docker build services/mcp` then `import frontdesk_stubs` / `import pytest` inside the image | both **absent** (image 80 MB) | — |
| `docker build -f services/mcp/dev/Dockerfile services/mcp` (stubs image for `make up`) | builds | — |
| production container with `OPS_BASE_URL` pointing at the contract mock | refuses to start (`points at a stub/mock endpoint`) | — |
| `make demo` | all four tools walked; outcomes AVAILABILITY, CALLBACK_REQUIRED, CLARIFICATION_NEEDED, NOTED, FOUND, ANSWERED, ROUTING_REQUIRED, STORED | stubs |
| `deploy/azure/deploy.sh rollouts/demo-hospital --profile <test profile> --dry-run` (see `tests/test_deploy.py`; the committed `live` profile is blank, `mock` is refused) | full plan printed, no az login | — |
| `eval "$(scripts/env.sh mock)"; export OPS_E2E_CLIENT_ID=x OPS_E2E_CLIENT_SECRET=x; cd services/mcp && uv run pytest tests -m external` (9 gates) | 3 PASSED (mock reads), 6 FAILED with `BLOCKED: …` (writes need a live synthetic tenant; knowledge host; deployed adapter) | public contract mock — **mock only** |
| `eval "$(scripts/env.sh live)"` … | **cannot run**: the live profile is blank until Manoj supplies the base URL; registered credentials also missing | live backend — awaiting live integration |
| Smoke against a deployed adapter | **not run** (nothing deployed) | — |

Skipped/deselected: none silently. The `external` gates run via `scripts/test.sh` only when `OPS_E2E_BASE_URL`
is set (the script prints that they were not run otherwise); inside them a missing input is a FAILED test
labelled `BLOCKED`, never a skip. Writes run only on a designated synthetic live tenant (`OPS_E2E_ALLOW_WRITES=1`,
`OPS_E2E_WRITE_TENANT`), never on the mock (stateless) and never on a hospital tenant.

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
| Summaries: call-end access, metadata after disconnect, frozen replay, 200/201 (200 for a different summary → CONFLICT), 500 chars, language, hang-up outcome, failed persistence | `summary.py`, `access.py` | `test_summary.py` | fixture-verified; **the platform's actual call-end invocation is unverified** (no platform access) |
| Transport: independent pools/auth, token expiry/single-flight, mock/backend base paths, bounded retries, cancellation uncertainty, local readiness vs dependency status | `ops_client.py`, `knowledge_client.py`, `config.py`, `server.py` | `test_ops_client.py`, `test_settings.py`, `test_server.py::test_dependency_status_*`, `test_external.py` (mock mode: token + reads + absent-bearer refusal) | fixture-verified; token issuance and reads verified against the public contract mock (no `/api/v1`); live backend not verified |
| Separation: clean checkout builds/tests without services/api, venv, PostgreSQL; no production fixtures or hidden engines | repo layout, `Dockerfile`, `.dockerignore`, `config.STUB_MARKERS`, `scripts/test.sh` | `test_stubs.py` (stubs are tables, not classifiers), `test_settings.py` (production refuses stubs), image checks in `scripts/test.sh` | verified locally and in CI definition |
| Voice: model calls the right tools with valid arguments and concise honest speech; interruptions/retries don't duplicate | `prompt.py`, `packs/healthcare.json`, operation keys, budget-derived deadlines | prompt policy tests in `test_server.py`; replay tests; `test_external_transport.py` (deployed-adapter gate, BLOCKED) | **not verified with a model or a live call; deployed transport gate BLOCKED** |
| Operations: rollback, one appointment authority, scoped Azure inventory, shared-resource preservation, no obsolete references, cost | `deploy/azure/deploy.sh`, `AZURE.md`, `AZURE-RETIREMENT-RESULTS.md` | straggler grep (no active references to the retired stack); `test_deploy.py` (profile/RG/subscription guards, upgrade path, dry run only) | rollback procedure documented, **not tested**; Azure retirement **not executed**; **no cost evidence** (no Cost Management query) |

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
| Default deadlines (2 s/4 s/1.5 s) exceeded the 1 s turn budget | first reduced to 1.2 s/2.5 s/0.8 s, later derived from the voice budget (AR-06, follow-up 2: 0.30 s). `test_default_deadlines_fit_inside_a_one_second_turn_budget` |
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
