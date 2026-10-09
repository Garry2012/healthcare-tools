# Opus review: the phase 4b correction (M-1, the smoke decision, L-1 to L-4)

- **Commit reviewed:** `61f9e72` ("Fix slot process journey and smoke handoff checks"), base `c16033b`.
- **HEAD:** still `61f9e72`.
- **Scope:** exactly the six approved files.
  - `services/mcp/tests/test_e2e_processes.py`;
  - `deploy/azure/smoke.py`, `services/mcp/tests/test_deploy.py`;
  - `services/mcp/tests/test_external.py`;
  - `services/mcp/dev/bench.py`, `services/mcp/tests/test_bench.py`.

  `git diff --quiet c16033b 61f9e72` confirms there is no change to `src/`, the stub source or data, `conftest.py`, `harness.py`, `gates.py`, `pyproject.toml`, `uv.lock`, `docs/`, `deploy/environments`, `deploy.sh`, the `Dockerfile`, `tests/contracts/`, `scripts/` or the `Makefile`.
- **Inputs read:**
  - the brief (identical to the attached copy);
  - `OPUS-SLOTS-4B-REVIEW.md` and the code-quality standard;
  - the design note and the hand-back;
  - every linked evidence file: the reds, the pre-check JSON, the today-process JSON, the scope proof, checks, bench, external and Vulture output.
- **Code read:** the full diff, plus `aggregate` (`availability_policy.py:501–520`), `outcomes.AvailabilityResult`, and the stub's request recording and `board_today` fallback.

## 1. Verdict: APPROVED

- Every requirement is met.
- There are no Medium or higher findings.
- Two Low observations are optional and not blockers (§3).

**The correction is accepted, and phase 5 can begin.** Deployment readiness is a separate question and is not affected by this verdict (§6).

## 2. Requirement by requirement

### M-1: process journey (`test_e2e_processes.py:115–163`)

| Requirement | Status | Evidence |
|---|---|---|
| Fixed future Monday `2099-01-05`, normal Morning and Afternoon blocks, nothing artificial | **Met** | `:117–123`: `slot_plan(date="2099-01-05")`; the second session is relabelled `Afternoon` at 15:00–15:30; Morning stays 10:30–11:00. The labels match `doc_garima`'s usual Monday schedule. No overnight, all-day or today data is scripted |
| Availability is read from `usualSessions[].openSlots` | **Met** | `:136–142`: the blocks are read by `label`, asserting Morning 10:30 and Afternoon 15:00 |
| CREATE without a time is refused, with no owner POST and no appointment | **Met** | `:143–149`: `INVALID_REQUEST`/`ASK_WHICH_TIME`, `appointments == []`, and no `POST /appointments` in the stub's request log |
| CREATE books 10:30; RESCHEDULE moves the **same** appointment to 15:00 on the **same** date | **Met** | `:150–160`: `NOTED`, `slotTime 10:30`; then a RESCHEDULE of that `appointmentId` to `2099-01-05` at 15:00 gives `NOTED`, `CHANGED`, `slotTime 15:00`. The `2099-01-12` fallback was not needed |
| One MCP client, verified caller headers, distinct operation ids sent | **Met** (sending checked by reading; see O-1) | One `Client` (`:133`) with `harness.headers(...)` (caller and verification). An httpx request hook (`:127–131`) writes the current `X-Operation-Id` onto every request; `:154` switches it to `e2e-slots-reschedule` before the RESCHEDULE |
| Today is used only by the read-only smoke, with no scripted today board | **Met** | `:163`; the scenario has no `boards` key |
| The other two process tests and their counts are unchanged | **Met** | The diff touches only the fixture teardown; the AST scope proof confirms both bodies |

### Smoke decision (approved; checked, not reopened)

| Requirement | Status | Evidence |
|---|---|---|
| Both department probes accept `HANDOFF_REQUIRED` only with `ON_CALL_DOCTOR`, `complete is True`, `TRANSFER_DESK`, and no tool, body or envelope failure | **Met** | `smoke.py:79–85`: the error, non-dict and envelope rejection runs first; then the `oncall_handoff` predicate, which is scoped to `get_doctor_availability` |
| Bare `HANDOFF_REQUIRED` no longer passes WORKING_HOURS | **Met** | `smoke.py:66` |
| Incomplete, malformed and unknown results, timeouts, authentication failures and server errors are still rejected | **Met** | `test_deploy.py:468–505`: 13 cases × 2 probes through real FastMCP, including `complete` given as `1`, `"true"`, `false` or missing. `:508–530`: timeout, 401 and 503 through the real `main()` (exit 1, no secret printed) |
| Other outcomes, knowledge, authentication, discovery and read-only behaviour are unchanged | **Met** | The diff is limited to `check_tools`. The AST proof covers `check_http`, `smoke` and `main`. A write tool fails the test if it is called |
| Today's outcome varies through the day, but acceptance stays stable | **Met, with evidence** | Pre-check A: the stub falls back to its built-in `board_today` (`ops.py:266–269`), which has relative update times, so it is never stale. Reading it with a fixed clock every minute across the day and the following midnight gave 1,202 `DOCTORS_MATCHED` and 241 `NOT_AVAILABLE` (from 20:00:01), all complete and all accepted. The real process on 9 October returned `DOCTORS_MATCHED`/`complete true` |

### The four cleanups

| Requirement | Status | Evidence |
|---|---|---|
| **L-1:** the missing-block message shows the real outcome and detail; no gate bypassed | **Met** | `test_external.py:163–164`. No fallback; the gate is unchanged |
| **L-2:** failed preparation reports 0 samples, states the failure explicitly, and exits non-zero | **Met** | `bench.py:204–205` (`summarise([])` plus `preparation_failure`); both branches use it; `:393, :397` give exit 1 through the real `__main__`. The test (`test_bench.py:215–266`) runs the real bench CLI in a child process with empty owner slot fixtures, in both starting modes. It asserts `samples 0`, no timings, not listed as omitted, **no owner POSTs** from the failed scenarios (only the two disabled-mode samples write), and exit 1 |
| **L-3:** enabled known-doctor and name-search outcomes are exactly `AVAILABILITY`, and the open-block check stays | **Met** | `bench.py:321–322`; the same child test with slots on from the start asserts `["AVAILABILITY"]`. The stub run (slots off at start) correctly keeps the old set |
| **L-4:** timed-out bench and demo children are killed and reaped; the fixture terminates both children before waiting on either, and kills and reaps a stuck one | **Met** | `_run_python` (`test_bench.py:15–26`) is used by every subprocess site and runs `sys.executable` directly, so no `uv` middle process can orphan a grandchild. `_stop_processes` (`test_e2e_processes.py:38–46`). The tests use real processes: a sleeping child is killed (`test_bench.py:192–212`); a child ignoring SIGTERM plus a cooperative sibling both end with a negative exit code (`test_e2e_processes.py:166–183`); and a test checks the order (`:186–200`) |
| Tests prove behaviour at real boundaries | **Met** | The smoke runs through a real FastMCP client and a real httpx transport. The bench runs as a real CLI child process with the real MCP server and stub. Cleanup uses real operating-system processes. Only owner fixture data is altered, which is the system boundary |

## 3. Findings

**No blocking findings.** Two optional observations:

### O-1 (Low): the switch to a new operation id is never actually checked

**Where:** `test_e2e_processes.py:127–131, 154`.

**Why the test can't catch it:**
- The stub records only the method and path (`ops.py:185`), not headers or idempotency keys.
- The adapter's write key is `sha256(tenant|call|action|operation)` (`booking.py:81–84`), so CREATE and RESCHEDULE already get different keys even with the same operation id.

So if the request hook stopped working, the test would still pass. I checked by reading that the hook does what it should: httpx request hooks run before sending and may modify headers, and `StreamableHttpTransport` passes its own arguments through to `httpx_client_factory`.

**Impact:** none on behaviour. The test simply doesn't prove that the id was sent.

**Fix:** none needed. If you want it proven, the stub would have to record the key, and that is out of scope.

### O-2 (Low, note only): the end-to-end `DOCTORS_MATCHED` proof depends on the time of day

The process smoke exercises `DOCTORS_MATCHED` end to end only before 20:00 IST. After that, the same step passes through `NOT_AVAILABLE`. Both are accepted, so the test is stable.

`DOCTORS_MATCHED` and complete `ON_CALL_DOCTOR` acceptance are proven without the clock in `test_deploy.py`. This is the trade-off Garima approved (no artificial today data). No action is needed.

## 4. How honest the red/green evidence is

**Valid red proof:**
- **Smoke:** 9 failed, 22 passed. The complete `ON_CALL_DOCTOR` case failed for AVAILABILITY, and 8 WORKING_HOURS negatives failed because bare acceptance was still in place.
- **Cleanup:** "timed-out child is still running"; the in-order teardown `('mcp','wait') != ('stubs','terminate')`; and `TimeoutExpired` (all in `slots-4b-m1-red-journey-bench-cleanup.txt`).
- **Corrected behavioural red:** 3 failed. Two were bench cases with invented sample counts (`samples 2 != 0`); the third was the future Morning block missing.
- **L-3:** its own red (`'CALLBACK_REQUIRED'` extra), deliberately captured in the first fix run.

**Not proof, and correctly disclosed as such:**
- the first run's scaffolding errors (`session` instead of `label`, a missing `dev` import path);
- the second run's fixture mistake (wiping the sessions list).

Both outputs are preserved, but they do not count as red evidence. The smoke cases that already passed before the change are labelled as kept regressions, not as manufactured reds.

**What the evidence does not show:**
- **L-1 has no red.** It changes only a message on a path the HTTPS gate stops locally. That is stated.
- **External writes are still `BLOCKED` locally** in both modes: 3 passed and 6 `BLOCKED` each, as before. The local runner now uses the stale Urology fixture for the read probe instead of the earlier all-day board, which is evidence-only.
- **Fixture bench timings** are not evidence about production latency.

## 5. Verification

**Commands I ran:**

| Command | Result |
|---|---|
| `timeout -k 10 300 uv run pytest tests/test_bench.py tests/test_deploy.py tests/test_e2e_processes.py -q -p no:cacheprovider` (`services/mcp`) | **90 passed** in 31.81 s (`.context/opus-4bm1-focused.txt`) |
| `timeout -k 10 600 make test-fast` | **1,165 passed**, 14 deselected, 2 Authlib warnings, in 91.78 s, exit 0 (`.context/opus-4bm1-fast.txt`) |
| `make schema` to a file, then `stat`, `shasum -a 256` and `cmp` against the snapshot | 64,111 bytes, `3ef91e78…6c62`, **byte-identical** |
| `uv run ruff check . ../../deploy` | All checks passed |
| `git diff --check c16033b 61f9e72` | clean |
| `git diff --quiet c16033b 61f9e72 --` over the protected paths | no change |

**Inspected but not rerun:**
- `./scripts/test.sh`: 1,165 hermetic and 5 e2e tests (3 journeys and 2 cleanup tests), the package and both images, exit 0;
- `make bench`: I recounted it: 15 scenarios, 750 of 750 samples, watchdog 255 s. The stub run keeps the slots-off set for known-doctor, which is correct;
- `make demo`;
- the local external runs: 6 failed and 3 passed in each mode, all failures being explicit `BLOCKED`;
- Vulture: 2 findings, both pre-existing (`action`, `summaryText`). The baseline had 4. The two `kwargs` findings disappeared only because Vulture matches by name, and Astra says so rather than claiming a clean-up.

**Untested:**
- the external write journey (HTTPS gate);
- live owner services, the knowledge host and Azure;
- the real-host bench and the 0.30 s budget;
- ContextForge and the voice team;
- the L-1 message on a real owner path.

## 6. Readiness

- **This correction:** **accepted.** Phase 4b is complete.
- **Phase 5** (`CLAUDE.md`, `DECISIONS.md`, `PLAN.md`) **can begin.** It should record Garima's 9 October smoke decision and the fixed-date process-journey rule.
- **Deployment:** **not ready, and not part of this verdict.** Release stays held through phase 5. It then needs, in addition:
  - Garima's merge and deploy authorisation;
  - the authorised live synthetic-tenant run of the external write journey, on Manoj's HTTPS tenant with open blocks on both dates;
  - the knowledge host and deployed-adapter credentials;
  - the ContextForge schema refresh;
  - the voice team's readiness for the new fields;
  - LOG-1, still open as a separate item.
