# Opus review: phase 4a (department capabilities, P-1, L-1, shared stage rule)

- **Commit:** `5c139ea521d6109d7bfd01aa374c86193c22854c`, "Integrate department capabilities and match counts"
- **Base:** `12edc3b`
- **Branch:** `Garry2012/slots-phase-1a-1b` (HEAD = review commit)
- **Inputs:**
  - brief `.context/attachments/Ca5XZ4/astra-build-slots-4a.md` (byte-identical to `.context/astra-build-slots-4a.md`)
  - `SLOTS-PLAN.md` revision 11.3
  - `.context/astra-prompt-booking-b2-m1.md`
  - `OPUS-SLOTS-3A2-REVIEW.md` (P-1)
  - `OPUS-SLOTS-3B-REVIEW.md` (L-1, L-2/T-1)
  - `.context/slots-4a-handback.md` and its preserved logs
  - the complete `git diff 12edc3b 5c139ea`, with callers traced
- **Scope of approval:** this intermediate commit only. It is not deployable before phase 5.

## Verdict

**APPROVED. Phase 4a meets the brief. T-1 may begin and should come next, before 4b** (see L-2).

- **Scope:** seven files (four source, three test).
- **Schema:** byte-identical.
- **Tests:** exactly one existing assertion changed, the approved one, plus the reader fixture's explicit `/capabilities` route.
- **Defects:** none in the implementation.
- **Test-infrastructure stall:** it recurred in Astra's runs. That is not a 4a defect, but it raises T-1's priority.

## 1. Findings

### L-2 (carried, now recurring): the HTTP test server sometimes hangs while shutting down (Low for product; Medium for verification reliability; T-1, not 4a)

- **Evidence (Astra's preserved logs):**
  - `.context/slots-4a-testsh-interrupted.txt`: faulthandler at 60 s;
  - `.context/slots-4a-testsh-interrupted-2.txt`: stalled at `tests/test_server.py::test_log_lines_carry_the_call_id_not_the_caller`.

  Both traces end in `tests/test_server.py:50` (`served`) → `tests/conftest.py:58` (`serving`, `await task` on the uvicorn server). This is the same location as the 3b stall (`slots-3b-interrupted-green.txt`).
- **Not caused by 4a:** the stalled test reads selected-doctor availability by name, then booking LIST. It makes no department or capabilities call. `conftest.py`, `test_server.py`, the server and the transports are unchanged in 4a (diff empty).
- **My reproduction attempts:**
  - `tests/test_server.py` × 12 in a row → 48 passed each (12.8–13.6 s);
  - full `test.sh` and two `make test-fast` runs → no stall.

  **Not reproduced.** Across both phases Astra has now seen three stalls, all inside full-suite runs, always at the same teardown await.
- **Assessment:** an intermittent, unbounded wait for the uvicorn server task to finish. The root cause is still unproven (possibly a lingering streamable-HTTP session). It does not affect production code paths, but it can stall CI and local verification indefinitely.
- **Correction (T-1, as planned; do not fold into 4a):**
  - bound the wait in `serving` (for example `asyncio.wait_for(task, timeout_graceful_shutdown + small margin)`, then cancel the task and report it);
  - add a test that a stuck shutdown fails fast and visibly;
  - when it fires, log which connection or task kept the server alive.

  Do T-1 **before 4b**, which adds more process and bench runs.

### N-1: `department()` uses "is there a board?" to mean "today's availability" (nit, optional)

- **Where:** `schedule_reader.py`, `department()`: `if board is not None:` selects the today branch.
- **Why it is correct:** `board` is read only for AVAILABILITY today.
- **Why mention it:** the branch condition reads data presence rather than intent; the old code said `purpose == AVAILABILITY and requested.kind == TODAY`.
- **No behaviour impact.** Optional: if this function is touched again, branch on the same explicit condition used to schedule the board read.

### Observations (no action)

- **O-1:** `_candidate` gained a `slots` argument. It carries `SlotsNotRead` or `None` as data into `DoctorFacts`; it is not a behaviour flag, so it complies with "no flag parameters".
- **O-2:** `test_department_slot_reads_remain_deferred` keeps its name while now asserting that `/capabilities` **is** read. The name stays accurate for `/slots` (still deferred), so no change is needed.

## 2. Review areas

### Capabilities retrieval and cache

| Check | Result | Evidence |
|---|---|---|
| Existing `DirectoryCache`, key `("capabilities",)`, TTL and LRU | **Pass** | `ScheduleReader.capabilities`: the same get-or-read pattern as `departments()`; `cache.py` unchanged |
| No start-up or background process, lock or single-flight promise | **Pass** | Only on-demand reads inside `department()` |
| Warm reuse, concurrent cold, TTL 0, expiry and eviction tested honestly | **Pass** | `test_department_sequential_capability_cache_reuse_and_zero_ttl`; `test_concurrent_cold_department_searches_may_each_read_capabilities` (a barrier forces both reads in flight; asserts 2 reads); `test_capability_cache_expiry_and_eviction_refetch_current_owner_flag` (injected cache clock, owner flag changes, eviction by another entry) |
| Failures get `stage="capabilities"` and are not cached | **Pass** | `except READ_ERRORS: exc.stage = "capabilities"; raise` before `cache.set`. `test_capability_failure_is_not_cached_and_other_tool_paths_do_not_depend_on_it`: failure, then success, 2 reads |

### Department retrieval

| Check | Result | Evidence |
|---|---|---|
| Today: search ∥ board ∥ capabilities in one gather | **Pass** | One `reads` dict, one `asyncio.gather`. `test_department_capabilities_share_first_parallel_step_and_mark_every_candidate` (concurrency proven) |
| Future: search ∥ capabilities, then the existing profile batches | **Pass** | Same gather; the batch loop is unchanged apart from passing `slots` and the counts |
| Failure precedence: search → board → capabilities | **Pass** | Dict insertion order plus "first exception raised". `test_department_existing_failure_precedes_capability_failure` |
| Enabled → `SlotsNotRead` on every candidate (today, on-call, profile-read) | **Pass** | Today `DoctorFacts(..., slots=slots)`; future on-call `DoctorFacts(d, slots=slots)`; `_candidate(..., slots)`. Asserted per candidate in the parallel-step test |
| Disabled → previous behaviour | **Pass** | `slots=None`. Every existing department test passes unchanged against the stub default (disabled); only the one approved path assertion changed |
| Both counts and the batch stopping condition use `is_match` | **Pass** | `found = sum(policy.is_match(...))` today; `found += policy.is_match(...)` in the loop that feeds `found >= doctor_choice_limit`. `test_enabled_department_match_counts_stop_at_the_same_profile_batch` |
| No `/slots` from departments | **Pass** | Asserted in the service tests and the parallel-step test |
| WORKING_HOURS: no capabilities or board read, unchanged | **Pass** | The `reads` dict adds board and capabilities only for AVAILABILITY. The existing `test_working_hours_never_reads_slots_or_capabilities` is unchanged and green; the new `test_department_working_hours_ignores_enabled_capabilities_and_keeps_on_call_facts` |

### Failure mapping

| Check | Result | Evidence |
|---|---|---|
| One definition of the "always a read failure" stages | **Pass** | `READ_FAILURE_STAGES = frozenset({"slots", "capabilities"})` in `schedule_reader.py`, used by `availability._service_error` and `booking._schedule_gate`. Both old `!= "slots"` checks are gone |
| Capability timeout, 5xx, 400, 404, malformed, `UNSUPPORTED_CAPABILITY`, 401/403 → never `NOT_FOUND`/`INVALID_REQUEST`/availability | **Pass** | `test_capability_failures_are_read_failures_not_directory_answers`, today and future: all `COULD_NOT_CHECK`/`CAPABILITIES_UNAVAILABLE`, `retryAfterSeconds` kept for `Unavailable` |
| Retry and caller AUTH rules intact; other stages unchanged | **Pass** | The availability and booking diffs change only the stage test; the detail map only gains one key. Existing directory, profile, board and booking rejection tests are unchanged and green |
| Other tools independent of capabilities | **Pass** | A selected doctor (`doctor()`) never reads capabilities; booking, summary and knowledge unaffected. Asserted in the not-cached test |

### Policy and presentation

| Check | Result | Evidence |
|---|---|---|
| P-1: an ended supplied window with `SlotsNotRead` is not a match today | **Pass** | `session_decision`: `SlotsNotRead` → `_ended_today` → `SESSION_ENDED` before `SLOT_CHECK_REQUIRED`. Service test `test_enabled_department_does_not_match_ended_window_beside_a_match`; the 3a-2 reproduction is now green |
| One end comparison; precedence kept | **Pass** | `_ended_today` is shared by steps 2 and 3. Step 1 (UNKNOWN/CANCELLED) comes first; the legacy today NOT_CONFIRMED → callback still precedes the ended check when there is no evidence (equivalent rewrite). `test_department_unread_end_guard_keeps_status_and_date_precedence` |
| Future dates and exact boundaries | **Pass** | `_ended_today` requires `TODAY`; `_window` (strict `>`) unchanged. `test_unread_end_guard_does_not_invent_an_end_or_change_exact_boundary` (missing end, `end == now`) |
| L-1 | **Pass** | Step 5 uses `decision.basis == Basis.LIVE_BOARD`. Same results (the reader validates the plan date); all 3b booking tests green |
| `DOCTORS_MATCHED`/`ASK_WHICH_DOCTOR`, `bookableFound 0`, `openSlots null` | **Pass** | `test_enabled_department_returns_matches_without_claiming_capacity` (cancelled, UNKNOWN labelled and unlabelled, NOT_CONFIRMED) |
| Mixed statuses, unlabelled UNKNOWN, session selection, weekdays, incomplete, ranking and capping, on-call | **Pass** | `..._keeps_unknown_scope_when_session_is_selected`, `..._future_department_uses_requested_weekday`, `..._partial_matches_are_ranked_and_capped`, `..._partial_search_without_matches_is_handoff`, `..._callback_ranks_before_cancelled_with_a_cap`, `..._on_call_requires_a_usable_confirmed_window` |

### Scope and test quality

- **Untouched (diff empty):** `cache.py`, `ops_client.py`, `contract.py`, `tools.py`, `outcomes.py`, `prompt.py`, pack, `config.py`, `identity.py`, stubs, `conftest.py`, `harness.py`, `test_stubs.py`, `test_server.py`, `test_booking.py`, snapshot, `deploy/`, `docs/`.
- **Clean code:** no new sequential REST call, duplicate policy, dead code or production flag parameter.
- **Removed test lines:**
  - the approved department assertion (`"/capabilities" not in` → `in`);
  - the `run_search` signature line, which gained an optional `capabilities` document and an explicit `/capabilities` route (B-5 note).

  Nothing else was removed.
- **Real paths:** service tests use the stub's existing `/__stub/scenario` and real `ScheduleReader`/`OpsClient`. Fault injection is at the HTTP transport boundary; no internal mocks.
- **Red evidence:** see §3.

## 3. Commands run (independently, at `5c139ea`)

| Command | Result |
|---|---|
| `make test-fast` (via `rtk proxy`) | **1,093 passed**, 11 deselected, 2 Authlib deprecation warnings (pre-existing) |
| `make schema > .context/opus-slots-4a-schema.json` (via `rtk proxy`) | Exit 0; **64,111 bytes**; `schemaVersion` `2026-10-08.1` |
| `cmp .context/opus-slots-4a-schema.json services/mcp/tests/contracts/mcp-tools.snapshot.json` (`/usr/bin/cmp`) | **Exit 0**; SHA-256 `3ef91e78ccfc8b730c540244f8e390bb1ca2bdc74576a8cc4207f93ecc7d6c62` |
| `env -u OPS_E2E_BASE_URL ./scripts/test.sh` | **Exit 0**. Lint clean; hermetic 1,093 passed; process e2e **2 passed**; package built; production and stubs images built; external gates not run (no profile); "all suites passed"; no stall. Log: `.context/opus-slots-4a-testsh.log` |
| `git diff 12edc3b 5c139ea --check` | Exit 0 |
| Independent red: base `12edc3b` source plus the three final test modules, in a temporary detached worktree (removed afterwards) | **50 failed, 375 passed**. This matches Astra's recorded initial red exactly |
| `tests/test_server.py` × 12 (faulthandler 45 s) | 48 passed every run; the L-2 stall was not reproduced |

## 4. Not tested

- **External systems:** live Manoj capabilities and slots, the mock/live external gates, ContextForge, the voice agent and real latency. There were no live calls.
- **Latency:** the cold `/capabilities` read adds parallel work to the first department step. Its real cost under connection-pool contention is for the 4b bench.
- **L-2 root cause:** not established.

## 5. Scope and next steps

- **Within 4a:** yes. No T-1 (`conftest.py` untouched), no 4b consumers, no phase 5 documents, no schema or wording change.
- **Next: T-1.** The test-server shutdown bound, one file, no production code. Do it before 4b.
- **Then 4b:**
  - the external tests that send CREATE/RESCHEDULE without a time;
  - the bench with on-call by-name, slot-enabled and department capability paths;
  - the demo.
- **Then phase 5:** `CLAUDE.md`, `DECISIONS.md`, `PLAN.md`.

## Plain-English summary for Garima

Astra's phase 4a work is correct and stays inside the seven planned files. The published schema is unchanged. My own runs all pass: 1,093 tests, the 2 process tests and the full script with both Docker images.

What 4a does, confirmed:
- department searches read Manoj's slot settings once, cached, in the same first step as the other reads (no extra wait);
- with slots on, the answer is "doctors matched" with 0 bookable and no slot times;
- a doctor whose session already ended today is no longer listed as matched (P-1 fixed);
- a failed settings read always says "could not check", never "not found";
- the "is it today?" tidy-up is done, and the rule about which failed reads always mean "could not check" now lives in one place.

No bugs. One thing to act on: the test server froze again in two of Astra's full runs, in the same shutdown spot as last time. It isn't caused by 4a, and I couldn't make it happen in 12 tries, but it has now happened three times. So the small fix (T-1, which makes it fail quickly instead of hanging) should be the next step, before 4b.
