# Opus review: slots plan phase 2b

Reviewed 8 October 2026.

| | |
|---|---|
| **Branch** | `Garry2012/slots-phase-1a-1b` |
| **Base** | `ffed9f2` |
| **Commit A** | `e1792f5`, "Validate scripted slot capabilities before mutation" |
| **Commit B** | `8779ac4`, "Read selected doctor slots with consistent failure handling" (review head) |
| **HEAD** | `8779ac4` (not moved) |

**Scope:** `git diff ffed9f2..8779ac4`. I reviewed both commits separately and traced every affected path through the services, reader, HTTP client, contract models and stubs.

**Not done:** no production fixes, commits, pushes, merges or deployments; no owner API calls; nothing changed in Azure. `temp/` is preserved. A temporary worktree used to test commit A on its own was removed afterwards. This report is uncommitted.

**Verdict: APPROVED for phase 2b. Phase 3a-1 may begin.**
- There are no blockers. Two optional nits and one wording conflict in my own brief are recorded below.
- This approves an intermediate, undeployed phase only. It says nothing about production readiness.

## 1. Findings

### Blockers

None.

### Brief wording conflict (mine, not a defect): on-call by-name latency

- **The conflict:** the 2b brief asked for two things at once. It removed the on-call early return for AVAILABILITY (D-8, plan B-4), and it said "no new sequential round trip on any path". Both cannot hold.
  - Before, a doctor known to be on-call, found by name, returned straight after the directory search (`/doctors` only).
  - Now, that path adds **one read group** after the search: board ∥ slots today, or profile ∥ slots for a future date.
  - `test_availability.py:518–533` pins both the new paths and the outcomes.
- **Which rule wins:** D-8 does. It was approved in revision 10 and confirmed by the R10/R11 pre-flights, and it requires these reads, because a confirmed on-call entry can make the doctor bookable. The "no new sequential round trip" wording should have excluded this path. Every other selected-doctor path gains only a request **inside** its existing parallel step.
- **Intermediate cost:** until 3a-2 switches on C-8, the policy still answers "callback" for on-call doctors. In this undeployed state the extra read is therefore pure latency.
- **Disclosure:** the hand-back (`slots-2b-handback.md` §"Latency") reports this accurately.
- **Action:** none in code. Measure this path in the 4b bench.

### Minor

None.

### Nits (optional, introduced here)

**N-1: the on-call callback test lost one assertion** (`tests/test_availability.py:530`)
- **Old test** (`ffed9f2`, `test_today_on_call_by_name_needs_no_board_read`): asserted `result.callback.model_dump() == {"reason": "ON_CALL_DOCTOR", "summaryOutcome": "CALLBACK_NOTED"}`.
- **New test:** `test_on_call_by_name_still_returns_callback_after_successful_slot_reads` keeps `(outcome, detail) == ("CALLBACK_REQUIRED", "ON_CALL_DOCTOR")` but checks only `callback.summaryOutcome`.
- **Impact:** a wrong `callback.reason` would no longer be caught on this path. Other callback tests still cover the reason in general.
- **Correction:** restore the full `model_dump()` equality in the new test.

**N-2: `read_failure_detail` treats the `"AUTH"` reason as if it were a read stage** (`schedule_reader.py:18–21`, `booking.py:239–240`)
- **What happens:** booking passes `stage = "AUTH"` when an `Unavailable` has reason AUTH, and the helper's table contains an `"AUTH"` key. The result is correct: booking keeps AUTH precedence, and availability, which never had an AUTH detail, is unchanged. But a reason is mixed into the stage vocabulary.
- **Correction:** keep the AUTH check in booking, `detail = "AUTH" if … else read_failure_detail(stage, "PROFILE_UNAVAILABLE")`, and drop the `"AUTH"` key from the helper's table.

### Observation (pre-existing, not a finding)

`doctor()` keeps the existing `gather(..., return_exceptions=True)` pattern (`schedule_reader.py:107–111`). A fast profile failure therefore waits for the slower board or slot read, bounded by the invocation deadline, before it is reported. This was already true for profile ∥ board and is unchanged in kind.

## 2. Commit A: stub validation (`e1792f5`, 2 files)

| Requirement | Result | Evidence |
|---|---|---|
| Invalid capabilities rejected before **any** mutation | **Pass** | `ops.py:541–545`: `CAPABILITIES.validate_python` runs together with `WRITE_OUTCOMES` before the first state change. The test sends every scenario key at once (`failNext`, `malformedNext`, `commitThen`, the delays, `boards`, `slots`, `writeOutcomes`) and asserts that each is unchanged after the 400. |
| `slots.enabled` strict bool | **Pass** | `Annotated[bool, Field(strict=True)]`. `"false"` and `0` are rejected (tested). |
| `blockMinutes` strict positive int, optional | **Pass** | `NotRequired[Annotated[int, Field(strict=True, ge=1)]]`. `None`, `"30"`, `0`, `-1`, `1.5` and `True` are rejected (tested). An omitted value still gives the default 30 (the `f10ec14` test passes). |
| Owner sections kept | **Pass** | `extra="allow"` on both TypedDicts. `test_http_capabilities_keep_unconsumed_owner_sections` round-trips nested owner facts unchanged. |
| Same `TypeAdapter`/TypedDict convention | **Pass** | It mirrors `WRITE_OUTCOMES`; there is no second validation style. |
| In-process assignment still unvalidated | **Pass** | `state.capabilities = …` bypasses the adapter. |
| Errors do not echo input | **Pass** | Fixed message: "Invalid writeOutcomes or capabilities fixture". |
| Valid on its own | **Pass** | In an isolated worktree at `e1792f5`: `make test-fast` → 703 passed; the schema is byte-identical. |

## 3. Commit B: retrieval and consistency (`8779ac4`, 9 files)

| Requirement | Result | Evidence |
|---|---|---|
| One uncached slot read per selected-doctor AVAILABILITY check, ISO date including today | **Pass** | `schedule_reader.py:77–92` passes `requested.value.isoformat()`. `test_selected_doctor_slot_reads_start_together` asserts `{"date": <ISO>}`. `test_selected_slots_are_uncached…` gives two reads → two `/slots` requests and one cached profile read. |
| Doctor/date identity, unique labels, cross-session overlap, including disabled plans | **Pass** | All checks run **before** `plan.enabled` is examined (`:80–89`). `test_slot_consistency_is_checked_before_disabled_plan_is_discarded` covers each issue with `enabled` false and true, and asserts `Malformed` with `stage == "slots"`. |
| `null` and `""` collide; adjacent blocks accepted | **Pass** | `policy.normalised(session.session or "")`. Fixture `blank` (`""` and `None`) is rejected; the adjacent 10:30–11:00 and 11:00–11:30 blocks across sessions in `slot_plan()` are accepted. |
| One shared overlap rule, within-session check not weakened | **Pass** | `contract.ordered_slot_blocks` (`contract.py:133`) is used by `SlotSession._ordered` (`:146`) and by the reader over all blocks sorted by start (`schedule_reader.py:87`). The predicate is the exact negation of the old one (`end <= start` versus `end > start`). All 2a model tests pass unchanged. |
| Enabled plan reaches `DoctorFacts` unchanged; disabled becomes `None` | **Pass** | `DoctorFacts.slots: SlotPlan \| None = None` (`availability_policy.py:74`). A scripted plan (with sessions reversed on purpose) round-trips exactly. |
| Today without summary: profile ∥ board ∥ slots | **Pass** | A barrier test where any sequential read would hang until the deadline. |
| Today with summary: board ∥ slots | **Pass** | Same barrier test. |
| Future: profile ∥ slots | **Pass** | Same barrier test. |
| Failure precedence profile → board → slots | **Pass** | Insertion-ordered `reads` dict, then the first exception in that order (`:100–111`). Tested with all three failing (profile wins) and with board + slots failing (board wins). |
| Cancellation stops all reads, no write | **Pass** | `test_cancelled_create_cancels_all_owner_reads_without_writing` now waits for profile, board **and** slots to start, cancels, and asserts each was cancelled and nothing was written. |
| Every slot failure → read failure | **Pass** | Tested in both services: timeout, 503, 400, 404, malformed, `UNSUPPORTED_CAPABILITY`, 401, 403. Availability: `stage == "slots"` skips the NOT_FOUND/INVALID_REQUEST branches (`availability.py:76`) → `COULD_NOT_CHECK`/`SLOTS_UNAVAILABLE`. Booking: a slots `Rejected` no longer reaches `_failure` (`booking.py:236–237`) → `COULD_NOT_RECORD`. Never `NOT_FOUND`, `INVALID_REQUEST` or `REJECTED`. |
| Booking AUTH precedence; `retryAfterSeconds` kept | **Pass** | 401/403 at the slot stage → booking detail `AUTH`; 503 with `Retry-After: 4` → `retryAfterSeconds == 4` in both services. |
| Helper keeps each caller's fallback and old non-slot behaviour | **Pass** | Fallbacks `DIRECTORY_UNAVAILABLE` (availability) and `PROFILE_UNAVAILABLE` (booking). `test_legacy_availability_rejection_and_auth_details_stay_unchanged` pins the five legacy outcomes. All R4-S1 anchors pass unchanged: `test_booking.py` 238–243, 401–404, 682–692 and 808–862; `test_availability.py` 100–113. |
| Bad or failed slot reads block CREATE and RESCHEDULE | **Pass** | Every inconsistency × {today, future} and every failure kind × {CREATE, RESCHEDULE}: no POST, owner appointments unchanged. Retry, identity and idempotency code are untouched. |
| WORKING_HOURS and department unchanged | **Pass** | WORKING_HOURS returns before any slot read (`:96–100`); by name it is still `["/doctors"]`, by ID `["/doctors/<id>"]`. Department: no `/slots` and no `/capabilities`, today and future. |
| LIST, CANCEL, summary and knowledge don't touch slots | **Pass** | `test_non_scheduling_actions_never_read_slots`. |
| Successful on-call lookups still give a callback | **Pass** | `CALLBACK_REQUIRED`/`ON_CALL_DOCTOR`, today and future (see N-1). |
| The on-call board-failure test matches the brief | **Pass** | It now gives `COULD_NOT_CHECK`/`BOARD_UNAVAILABLE`, with paths `["/doctors", "/availability", "/availability/doc_vikram_desai/slots"]`, plus a successful control. |
| Other business assertions not weakened | **Pass** | Every removed test line in both commits belongs to the on-call test the brief changed (N-1) or to the cancellation test, which was widened. |
| Policy still ignores slot facts | **Pass** | `test_enabled_slot_facts_do_not_change_{availability,booking}_policy_yet`: a scripted `morningCancelled` plan leaves the result identical, and CREATE and RESCHEDULE are still `NOTED`. |
| No later-phase changes | **Pass** | No policy rules, `SessionDecision` fields, `SlotsNotRead`/`is_match` (deferred as briefed), outputs, prompt, pack, VOICE-TEAM or configuration. The schema is byte-identical. |
| File counts | **Pass** | A: 2. B: 9 (`schedule_reader.py`, `availability_policy.py`, `availability.py`, `booking.py`, `contract.py`, `harness.py`, `test_schedule_reader.py`, `test_availability.py`, `test_booking.py`). |

**Code quality:**
- `doctor()` replaces three hand-written branches with one ordered gather. That is less code, and the precedence is still explicit.
- `harness.py` gains shared fixtures (`slot_plan`, `inconsistent_slot_plan`, `slot_failure`), each labelled as synthetic contract-shaped data.
- No dead code (vulture empty), no duplicated rule, and no change to security or authentication.
- The `Malformed` messages in `slots()` are never logged; availability logs only the exception type and the detail.

## 4. Verification

| Check | Command | Result |
|---|---|---|
| Commit A on its own | isolated `git worktree` at `e1792f5`: `make test-fast`, then `make schema` and `cmp` | **703 passed**; schema **byte-identical**. Worktree removed. |
| Commit B (HEAD) | `make test-fast` | `All checks passed!`; **794 passed, 11 deselected, 2 warnings** (existing Authlib deprecations). |
| Schema | `make schema > /tmp/rv2b-b-schema.json`, then `cmp` with the snapshot | **Byte-identical.** |
| Focused tests | `pytest test_schedule_reader.py test_availability.py test_booking.py test_stubs.py -k "slot or on_call or capabilit or legacy or cancelled_create or non_scheduling"` | **135 passed.** |
| Full script | `env -u OPS_E2E_BASE_URL ./scripts/test.sh` | **Exit 0.** Lint passed; hermetic 794 passed; process e2e **2 passed**; package built; production and stub images built (Docker available); "external gates not run"; "all suites passed". |
| TDD evidence | Commit A | Red: 13 failed, 2 passed. Green: 15 passed. |
| | Commit B | Red: 74 failed, 16 passed. Green: 90, then 97 in the final version. |
| | Overall | The failures are for the intended reasons: slot failures and inconsistencies were ignored, slots were not read, and the shared helper didn't exist yet. `slots-2b-vulture.txt` is empty. |

**Not run:** the external gates, live owner calls, deployment, and any real voice-path latency measurement.

## 5. Requirement checklist

| Requirement | Status |
|---|---|
| A: validate before mutation; strict types; owner sections kept; same convention; in-process bypass; no echo of input | pass |
| B: one uncached ISO slot read per selected-doctor check | pass |
| B: identity, label uniqueness and overlap checks, including disabled plans | pass |
| B: one overlap rule | pass |
| B: three concurrent read groups | pass |
| B: failure precedence | pass |
| B: cancellation | pass |
| B: every slot failure is a read failure in both services | pass |
| B: AUTH and retry-after preserved | pass |
| B: legacy failures unchanged | pass |
| B: no write after a bad or failed slot read | pass |
| B: WORKING_HOURS, department and non-scheduling paths unchanged | pass |
| B: on-call outcome and changed test as briefed | pass (N-1 nit) |
| B: policy still ignores slots | pass |
| B: no later-phase changes; file limits | pass |
| Latency: no new sequential trip except on-call by name, as D-8 requires | pass, with the brief conflict recorded above |
| Live latency | not verified (not run) |

## 6. Optional cleanup

N-1 and N-2 above. Either can be folded into the 3a-1 commit or into a separate small commit. Neither blocks 3a-1.

## 7. For Garima

Phase 2b is correct and approved. **Phase 3a-1 can start.**

**What it does:**
- When a doctor is chosen, the tools now read that doctor's slots at the same time as the existing reads. Tests prove the reads really run together.
- Bad slot data, or a failed slot read, means "could not check" or "could not record". No booking is ever written in that case, and every existing error answer is unchanged.
- The answers the caller hears haven't changed yet, as planned. The tool schema is identical.
- **Commit A** also makes the fake Manoj server refuse invalid slot settings cleanly. That was Sol's point.

**One thing to know (my wording, not Astra's code):** my prompt said both "remove the on-call shortcut" and "add no extra waiting anywhere", which contradict each other for on-call doctors found by name. Your D-8 rule needs that read, so it now happens: one extra parallel read for that case. We'll measure it in the phase 4b benchmark.

**Two optional small tidy-ups:**
- restore one dropped check in an on-call test;
- simplify how the "AUTH" error detail is chosen.

**Checks:** 794 fast tests, the process tests, the package build and both Docker images all passed. Commit A also passes on its own.
