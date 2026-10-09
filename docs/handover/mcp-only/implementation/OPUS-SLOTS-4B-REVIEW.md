# Opus review: phase 4b (slot-aware operational consumers)

- **Commit reviewed:** `c16033b` ("Update slot-aware operational consumers"), base `6c8b90c`.
- **HEAD:** still `c16033b`, so there were no later commits to separate out.
- **Scope:** 7 files.
  - `deploy/azure/smoke.py`;
  - `services/mcp/dev/bench.py`, `services/mcp/dev/demo.py`;
  - `services/mcp/tests/test_bench.py`, `test_deploy.py`, `test_e2e_processes.py`, `test_external.py`.

  I confirmed (`git diff --quiet`) that there is no change to `src/`, the stubs, `conftest.py`, `harness.py`, `gates.py`, `pyproject.toml`, `uv.lock`, `docs/`, `deploy/environments`, `deploy.sh` or the `Dockerfile`. The schema is unchanged. `test_external_transport.py` needed no change, because it calls the real smoke.
- **Inputs read:**
  - the brief (identical to the attachment);
  - SLOTS-PLAN §8–11 and the T-4 review;
  - the code-quality standard;
  - the design note, the hand-back and every evidence file listed in the request.
- **Code read:** the full diff, the complete `bench.py`, `availability_policy.aggregate`, `outcomes.AvailabilityResult`/`DoctorAvailability`, the stub's scenario controls and fixtures, `gates.assert_authenticated_write_tenant`, and the original process fixture.

## 1. Verdict: CHANGES REQUIRED (one small test-only fix)

- **Everything else is sound,** and the consumers agree with the implementation:
  - the external gates, the smoke, the bench, the demo and the process journey;
  - no shortcut around the HTTPS gate, and no second server in one process;
  - nothing silently turns into a day-level write.
- **One Medium finding must be fixed before acceptance:** the new process test depends on the wall clock (M-1).
- **Five Low findings are optional.**
- **The `HANDOFF_REQUIRED` question is Garima's decision.** It is not a defect (§6).

## 2. Findings (most severe first)

### M-1 (Medium): the new process test fails at certain times of day

**Where:** `tests/test_e2e_processes.py:106–139`.

**What the test does:** it runs against real processes on the **system clock**. It reads the stub's `today`, then scripts:
- one desk block from 00:00 to 23:59;
- a board entry, IN, from 00:00 to 23:59.

It then asserts that availability today offers a block, and that booking it gives `NOTED`.

**When it fails:**
- **In the last minute of the clinic's day (23:59 to 00:00 IST):** the block and the window have ended, since a block is closed when its end equals now. Nothing is offered, so `assert offered` fails.
- **When a run crosses midnight in the clinic's timezone:** `today` was captured before the date changed. The adapter then asks about a new date that has no board and no slots, so the test fails.

This test is part of `./scripts/test.sh`, the release gate. IST midnight is 05:30 in Garima's timezone (AEDT), so the window is about one minute a day plus the test's few seconds. When it happens, it is a certain failure, not random.

**Why it is Medium and must be fixed now:**
- It is a known time-dependent test, against the testing rule ("no order-dependent tests… use freezegun or equivalent").
- It arrives straight after four investigation phases spent removing one intermittent failure.
- Astra disclosed it honestly, but disclosure does not make it acceptable in the release gate.

**The cause is partly my brief:** it asked for "availability today", which forces a dependence on the clock when the processes run on the system clock.

**Smallest fix (one file, no stub change):**
- Run the booking part of the journey on the **fixed future usual day `2099-01-05`.** It is a Monday; `doc_garima`'s usual Morning is Monday, Thursday and Friday; and the existing journey already uses that date. Script `slots: {doc_garima: {"2099-01-05": harness.slot_plan(date="2099-01-05")}}`.
- Assert:
  - `openSlots` in `usualSessions`;
  - `INVALID_REQUEST`/`ASK_WHICH_TIME` with no `POST /appointments`;
  - then `NOTED` with `slotTime`.

  Nothing then depends on the clock.
- Keep the today board **only** for the release-smoke step. The smoke accepts every healthy department outcome, so in the edge minute it passes through a different accepted outcome instead of failing.
- Acceptance of `DOCTORS_MATCHED` stays proven, without any clock dependence, by `test_smoke_accepts_slot_matches_but_not_unknown_outcomes`.

### L-1 (Low): a failed availability read is reported as "no open block"

**Where:** `test_external.py:156–164` (`open_time`).

If the availability read fails (for example `COULD_NOT_CHECK`), `result.doctors` is empty, and the test fails with `BLOCKED: the owner-designated date has no open block`. The test does fail, and nothing is written. The message just hides the real cause.

**Fix:** include `result.outcome` and `result.detail` in the failure message.

### L-2 (Low): a preparation failure is reported as 50 failed samples

**Where:** `bench.py:323–325` and `:359–361`.

When preparation finds no open block, the bench reports `samples: N, rejected_or_failed: N` with the label `NO_OPEN_BLOCK`. That is honest (it is not counted as success, and not listed as "writes disabled"), but **no** booking call was made.

**Fix:** report `samples: 0`, with the preparation failure shown on its own.

### L-3 (Low): on a real host with slots enabled, part of the accepted set can never count

**Where:** `bench.py:311–315`.

`availability_known_doctor` and `availability_name_search` keep `CALLBACK_REQUIRED` in their accepted set, but now also require open blocks. A callback therefore can never count. The behaviour is conservative and harmless, but the report's `expected_outcomes` is misleading.

**Fix:** drop `CALLBACK_REQUIRED` from those two sets when slots are enabled.

### L-4 (Low): subprocesses can be left running after a timeout

**Where:**
- `test_bench.py:102, 143` (new);
- `:75` (pre-existing);
- `test_e2e_processes.py:61–63` (pre-existing).

**What happens:**
- `asyncio.wait_for(process.communicate(), timeout=30)` cancels the wait on timeout but never kills the child. A hung `dev/bench.py` or `dev/demo.py` would outlive the test.
- In the process fixture, if `mcp.wait(timeout=10)` raises, the stubs process is never terminated.

On an assertion failure the child has already exited, so this matters only on a timeout. The pattern is copied from existing code.

**Fix:** on timeout, call `process.kill()` and then `await process.wait()`; terminate both processes before waiting on either.

### L-5 (Low): the bench itself does not enforce two of the cache checks

`department_cache_modes` (`bench.py:202–224`) requires `/capabilities` on cold samples. It does **not** reject `/capabilities` on warm samples, or profile reads on warm future samples. Those are only reported. `test_bench.py` asserts them for the stub run, so a regression in the adapter's cache would be caught there. A real-host run (where owner calls are not recorded) cannot check them anyway.

**Fix:** none needed. Note it in the bench docstring if desired.

## 3. Requirement by requirement

| Brief item | Status | Evidence |
|---|---|---|
| Files: at most 8, one commit, extra files justified | **Met** (7) | `git show --stat`; smoke and `test_deploy` justified, transport file unchanged |
| Nothing forbidden changed; schema unchanged | **Met** | I ran `git diff --quiet` over the protected paths; schema byte-identical |
| No owner calls | **Met** | External runs were local stub processes on loopback only |
| No two `serving()` blocks in sequence | **Met** | `bench.py:304` (one block, both modes); demo uses one block; process tests use separate processes |
| Pre-check 1 (owner paths) | **Met, and correct** | Selected doctors read `/slots` in **both** modes, because the slots response carries `enabled`; departments read `/capabilities` and never fan out to `/slots`; future dates never read the board. The bench and its tests agree |
| Pre-check 2 (switching mode within one server) | **Met** | Slots are not cached; department capabilities sit in `DirectoryCache` (300 s). Clearing the bench's own local cache when it switches modes is consistent with the brief: it is local, disclosed in the JSON (`fixture_mode_transition`), and does not reset any flag or touch production configuration |
| Pre-check 3 (healthy `HANDOFF_REQUIRED`) | **Met; boundary kept** | Astra showed that `aggregate` (`availability_policy.py:517–518`) returns `HANDOFF_REQUIRED/ON_CALL_DOCTOR` for a complete search. No accepted set gained it (§6) |
| Pre-check 4 (fixtures) | **Met** | `harness.slot_plan`, with an unlabelled on-call block that joins Vikram's unlabelled board entry |
| A: department set adds only `DOCTORS_MATCHED` | **Met** | `test_external.py:120–121` |
| A: capabilities read after the HTTPS/tenant gate; `slots_path` recorded | **Met** | `:146–148`, after `_write_gate` |
| A: enabled CREATE uses a time from the returned `openSlots` for that date; missing time is refused with no write | **Met** | `:156–176`; `INVALID_REQUEST/ASK_WHICH_TIME` plus a successful before/after LIST and `assert_no_new_appointment` |
| A: RESCHEDULE takes its time from the destination date | **Met** | `open_time(move_date)` |
| A: disabled journey, negative test, caller verification, operation ids, summary replay | **Intact** | The AST proof in `slots-4b-scope-proof.json`, plus my reading |
| A: no silent day-level write | **Met** | No block means `pytest.fail` (L-1 is the message wording only) |
| A: local verification | **Met as expected** | 3 passed and 6 `BLOCKED` in each mode. The write journeys stop at the HTTPS gate (`gates.py:29`); the stub's opaque token has no tenant claim, which was reported and not invented |
| B: smoke adds only `DOCTORS_MATCHED`; still read-only; test through FastMCP | **Met** | `smoke.py:23–24`; `test_deploy.py:92–116` (a valid match passes, an unknown outcome fails, and writes fail the test) |
| B: process test runs the real smoke against slots enabled | **Met** | It was red before the smoke change (`slots-4b-red-process.txt`), then green |
| C: one server; explicit watchdog in the report; scales with samples | **Met** | `bench.py:300–304`; `test_bench.py:130–131` |
| C: slots-disabled scenarios unchanged; forbidden paths enforced | **Met** | `measure` rejects department `/slots`, selected-doctor `/capabilities` and future board reads (`:99–106`) |
| C: the five slots-enabled scenarios with their required paths | **Met** | Recounted from the 750-sample JSON in the hand-back; `test_bench.py:92–133` |
| C: a useful outcome (non-empty `openSlots`) is required | **Met** | `open_blocks` check (`:315`, `:346–352`) |
| C: booking time taken from returned blocks, no fallback | **Met** | `prepare_booking` (`:155–180`); the boundary test proves that an offered 10:50 is chosen and an empty list is refused |
| C: no claim about production latency | **Met** | The boundary string, the `note` and the hand-back say "fixture timings only" |
| C: the write gate is unchanged | **Met** | `selected_scenarios` is unchanged (AST proof) |
| D: demo has three or four new calls in the existing server, using returned slots | **Met** | `demo.py:98–112` (three calls); output asserted by `test_demo_shows_slots_missing_time_and_selected_time` |
| D: process journey; existing journeys and counts unchanged; isolation | **Met, apart from M-1** | The fixture is now function-scoped (a fresh pair of processes per test), and the existing bodies are byte-unchanged |

## 4. The midnight test limitation

See M-1. It is **Medium** and must be corrected before acceptance. The recorded run passing does not change that: the failure is deterministic inside its window. The fix is small, stays within the same file, and removes the clock dependence completely.

## 5. How valid the measurements are, and the limits of the external write coverage

**Bench:**
- **What counts as a sample:** only the intended outcome **and**, in stub mode, every required owner request seen for that call id. Attribution through the call-id context variable is safe under concurrency.
- **Operation ids** are unique per scenario and sample (`bench-{name}-{i}-op`).
- **What it does not include:** session setup and the untimed preparation are outside the per-call timings and are reported separately.
- **Watchdog arithmetic:** `samples × workload_scenarios × max(read, write deadline) + 30 s`. With 50 samples that is 50 × 15 × 0.30 + 30 = 255 s for the stub run.
  - It is a genuine upper bound, because each tool call is bounded by its deadline.
  - Per-sample MCP session setup is local and small. With 750 samples at about 10 ms each, it stays inside the 30 s margin.
  - The test checks that `workload_scenarios` equals the number of scenarios reported.
  - Real host: up to 50 × 9 × 4.0 + 30 = 1,830 s.
- **What it proves:** these are fixture timings. They say nothing about the 0.30 s live budget or voice latency, and the bench says so itself.
- **Real host:** this path was not run. Its mode label comes from a single read of capabilities. Owner calls are not recorded there (`owner_calls_verified: false`). A failed preparation is labelled as a failure (L-2), not as omitted.
  - **Side effect worth knowing:** a slots-enabled write bench against a live synthetic tenant books 50 times into the same block. That could fill it, and the later samples would then honestly report a refusal.

**External writes:** the changed positive journey (slots enabled **and** disabled) has **never run**. The HTTPS gate correctly blocks it locally, and it must stay that way.
- **Risk:** moderate. The new code is short and uses only service calls the hermetic booking tests already cover. But field paths such as `doctor.board[].openSlots` and `appointment.slotTime` have only been exercised through the stub and the MCP layers.
- **Its first real run is the authorised live run on Manoj's synthetic tenant.** That run needs:
  - a slots-enabled tenant;
  - open blocks on both journey dates;
  - the UNKNOWN-today fixture for the negative test.
- If the tenant has slots disabled, only the day-level branch is exercised, and the run must report `slots_path=disabled`.

## 6. Owner decisions (separate from the code findings)

**Should the smoke and external gates accept a healthy `HANDOFF_REQUIRED` from a department search for today?**

`aggregate` returns `HANDOFF_REQUIRED/ON_CALL_DOCTOR` (`availability_policy.py:517–518`) when:
- a complete department search has no matches;
- no doctor needs a callback;
- some doctor is an on-call doctor without a confirmed usable entry (D-8).

`HANDOFF_REQUIRED/SEARCH_INCOMPLETE` (`:503–504`) is a degraded read and a different case. The `detail` field tells them apart.

**Astra kept the boundary:** only `DOCTORS_MATCHED` was added.

**Practical effect today:** if the live smoke department (`MCP_E2E_DEPARTMENT`, default General Medicine) is ever made up only of unconfirmed on-call doctors, the release smoke and external line 121 will **fail a healthy deployment** and block the release.

**My recommendation:** if you want to cover that case, accept `HANDOFF_REQUIRED` **only with `detail == "ON_CALL_DOCTOR"`**, never bare, so that `SEARCH_INCOMPLETE` still fails. Alternatively, choose a smoke department that always has regular doctors, and change nothing.

**Still owner-dependent, unchanged:**
- the authorised live synthetic-tenant run (above);
- the knowledge host;
- deployed-adapter credentials;
- the live bench against the 0.30 s budget;
- the ContextForge schema refresh;
- the voice team's handling of `DOCTORS_MATCHED`, `ASK_WHICH_TIME`, `openSlots`, `oneDay`, `slotTime` and `slotMoved`.

## 7. Commands I ran

| Command | Result |
|---|---|
| `timeout -k 10 300 uv run pytest tests/test_bench.py tests/test_deploy.py tests/test_e2e_processes.py -q -p no:cacheprovider` (`services/mcp`) | **56 passed** in 13.27 s (`.context/opus-4b-focused.txt`) |
| `timeout -k 10 600 make test-fast` | **1,133 passed**, 12 deselected, 2 Authlib warnings, in 52.85 s, exit 0 (`.context/opus-4b-fast.txt`) |
| `make schema` to a file, then `stat`, `shasum -a 256` and `cmp` | 64,111 bytes, `3ef91e78…6c62`, version `2026-10-08.1`, **byte-identical** |
| `git diff --check 6c8b90c c16033b` | clean |
| `git diff --quiet 6c8b90c c16033b --` over the protected paths | no change |
| `uv run ruff check . ../../deploy/azure/smoke.py` | All checks passed |
| `python3 -c "date(2099,1,5).weekday"` | Monday (supports the M-1 fix) |

**Astra's results that I inspected but did not rerun:**
- `./scripts/test.sh` (1,133 hermetic, 3 process tests, builds);
- `make demo` and `make bench` (750 of 750 samples across 15 scenarios; I recounted the JSON in the hand-back);
- the local external runs (3 passed and 6 `BLOCKED` in each mode; I read both logs);
- Vulture (4 findings remain, all in unchanged test bodies; the baseline had 8, and none is new).

**On the order of the red runs:**
- The consumer, smoke, demo and process reds were written first and are preserved.
- The two bench boundary reds were run against the base `bench.py` **after** the first draft. As Astra states, they are supplementary evidence, not test-first evidence.

**Not run by me:** any external gate (no owner calls), the real-host bench, Azure.

## 8. Readiness

**Phase 4b:**
- **Accept it after M-1 is fixed.** That is a one-file test change: move the booking journey to `2099-01-05`.
- **L-1 to L-4 may go in the same commit** if you want them; each is small.
- **Re-review:** only the diff of that fix.

**Phase 5** (`CLAUDE.md`, `DECISIONS.md`, `PLAN.md`) can start once the M-1 fix is approved. Answering the `HANDOFF_REQUIRED` question first would let phase 5 record the decision. Release stays held through phase 5, and the live synthetic-tenant run needs separate authorisation.

## 9. Plain-English summary for Garima

**What's sound:** everything that uses the tools has been updated correctly.
- **External checks:** they accept the new department result, and with slots on they book only a time the system actually offered. They never fall back to a day-only booking.
- **Release smoke:** it no longer rejects a healthy slot-enabled deployment.
- **Bench:** it checks the right reads in both modes, books only offered times, and runs on a single server, so the T-4 flag problem can't happen.
- **Demo:** it shows the new behaviour.
- Nothing in production, the schema, the stubs or the shared test setup changed.

**What needs fixing (small):** one new process test uses today's real date with a block running from 00:00 to 23:59, so it fails if run in the last minute before midnight India time (about 05:30 your time). Moving that booking check to a fixed future date fixes it completely.

**What needs your decision:** if the release check's department ever contains only on-call doctors who haven't confirmed, the system correctly says "transfer to desk", but the release check currently treats that as a failure. You can accept that specific healthy case, or keep the smoke pointed at a department with regular doctors.

**Still waiting on others:** the changed live booking test has never run. That is correct (it needs Manoj's HTTPS test tenant and your authorisation), and it is the first thing to run once those are in place.
