# Opus review: phase 3b (slot booking gates and blank-session input)

- **Commit:** `0d9689c4a18b4c27a9b586c6a27a81bb96be2c6b`, "Implement slot booking gates and session validation"
- **Base:** `ef68962abb3ab74e8ed0b4419d429ee17bfa6a05`
- **Branch:** `Garry2012/slots-phase-1a-1b` (HEAD = review commit)
- **Inputs:**
  - `.context/astra-build-slots-3b.md` (including the approved AfterValidator correction)
  - `SLOTS-PLAN.md` revision 11.3 (uncommitted; preserved)
  - `.context/astra-prompt-booking-b2-m1.md`
  - `OPUS-SLOTS-3A2-REVIEW.md`
  - `OPUS-SLOTS-3A1-W2-REVIEW.md`
  - `.context/slots-3b-handback.md` and its linked evidence
  - the complete `git diff ef68962 0d9689c`, with callers traced
- **Scope of approval:** this intermediate commit only. It is not deployable before phase 5.

## Verdict

**APPROVED. Phase 4a may begin.**

- **Scope:** eight files (four source, four test), matching the brief and plan C-4/C-6, D-2, D-3, P-2 and the blank-session note.
- **Schema:** byte-identical.
- **Tests:** no existing test line was removed or changed.
- **Defects:** none in the implementation. Two Low items (one optional cleanup, one pre-existing test-infrastructure flake) and two observations are listed below. None blocks 4a.

## 1. Findings

### L-1: step 5 decides "today" from the slot plan's date, while the rest of the policy uses the date kind or basis (Low, optional cleanup)

- **Where:** `availability_policy.py`, `decide_booking` step 5: `block_state(block, now if decision.facts.slots.date == now.date() else None)`.
- **Effect:** none today. The reader rejects a plan whose `date` differs from the requested date (2b, `schedule_reader.slots`), so this always agrees with `RequestedDate.kind`. The hand-back discloses it.
- **Why mention it:** "is this today?" now has a third expression, beside `DateKind` (`_evaluate_session`) and `Basis.LIVE_BOARD` (`_contains_time`'s passed-time narrowing).
- **Smallest correction (optional, any later touch of this function):** use `decision.basis == Basis.LIVE_BOARD`, the signal `_contains_time` already uses in the same function.

### L-2: intermittent stall when the HTTP test server shuts down (Low, pre-existing test infrastructure; not a 3b defect)

- **Evidence:** Astra's preserved trace `.context/slots-3b-interrupted-green.txt`. After 523 passing tests (about 90% of the run), faulthandler fired at 60 s inside `pytest_asyncio` `async_finalizer` → `tests/test_server.py:50` (`served`) → `tests/conftest.py:58` (`serving`, `await task`) → `uvicorn.Server.serve` / `capture_signals`. In other words, the hang is in the teardown of a test server after its test ran, not in 3b code.
- **Not changed by 3b:** `conftest.py` and the `served` fixture. The diff over `tests/conftest.py` is empty, and `test_server.py` gained only appended tests.
- **Reproduction attempt:** 8 consecutive runs of `tests/test_server.py` → 48 passed each (13.2–13.9 s). Plus two full hermetic runs (`make test-fast`, `test.sh`) → 1,016 passed. **Not reproduced.**
- **Assessment:** an intermittent uvicorn shutdown wait (the graceful shutdown is 2 s, but `await task` itself is unbounded), probably a lingering streamable-HTTP connection. Its root cause is unknown, and Astra disclosed it honestly.
- **Recommended correction (separate, tracked; not 3b):** bound the fixture's `await task` (for example `asyncio.wait_for` a little above `timeout_graceful_shutdown`, then cancel), so a stuck shutdown fails fast and visibly instead of hanging the run. If it recurs, record the client that keeps the connection open.

### Observations (approved trade-offs, no action in 3b)

- **O-1: unlabelled rows still take part in booking refusals (D-7, as deployed).**
  - **Behaviour:** without a supplied session, step 3 keeps every unlabelled row next to the matched session. A named request also keeps them in scope. `_combine(…, True)` then lets an unlabelled refusal decide.
  - **New source of such refusals:** with slots, an unlabelled **board** row with no matching slot session is `NO_OPEN_SLOT` (C-3 step 4).
  - **Example:** a labelled Morning booking that would otherwise write is refused if the board also carries an unlabelled row with no slot session.
  - **Approved:** this is approved plan behaviour (C-6 step 3 "unchanged code"; D-7 "both stay exactly as they are"). It only bites when the board mixes labelled and unlabelled rows for one doctor and date, which the live captures do not show.
  - **What to do:** revisit only if Manoj's data shows mixed labels (worth adding to the G-11 follow-up).
- **O-2: the D-3 replay test changes capacity by editing the plan dict after `set_slots`** (`test_booking.py:1170`). This relies on the stub keeping a reference to that dict rather than a copy. It works, and is acceptable for a fixture. If the stub ever copies scripted plans, call `set_slots` again in the test instead.

## 2. Review areas

### SessionChoice (Garima-approved AfterValidator)

| Check | Result | Evidence |
|---|---|---|
| 40 spaces → no session | **Pass** | Probe on both models: `None` |
| 41 spaces rejected exactly like 41 letters | **Pass** | Both give `string_too_long`, on both models |
| `"  Morning  "` passed through unchanged | **Pass** | Returned as `'  Morning  '` |
| Non-string rejected | **Pass** | `5` → `string_type` |
| `""` and `None` | **Pass** | Both `None` |
| Both request models and real MCP calls covered | **Pass** | Tests `test_availability_session_*`, `test_booking_session_*`, `test_blank_*_session_*`, `test_mcp_blank_sessions_are_unselected_for_both_tools`, `test_mcp_session_invalid_values_never_reach_owner_reads` |
| Field constraints and `tools.py` unchanged | **Pass** | Both fields keep `Field(default=None, max_length=40[, description])`; `tools.py` diff empty; schema byte-identical |

One home: `outcomes.SessionChoice` (`_blank_session` and an `Annotated` type), used by `availability.py:31` and `booking.py:47`.

### Booking policy (`decide_booking`)

| Check | Result | Evidence |
|---|---|---|
| Step order: whole scope (step 1) → `TimeRequired` (step 2) → time selection (step 3) → `_combine` and refusals (step 4) → block (step 5) | **Pass** | Step 2 sits directly after the step 1 exits. Step 5 runs only after the `HANDOFF`, `CALLBACK` and `NOT_AVAILABLE` returns. Tests `test_slot_booking_requires_time_only_after_whole_scope_refusal`, `test_slot_booking_missing_time_does_not_replace_whole_scope_failures` |
| `block_at`: one half-open lookup | **Pass** | `block_at` (`start ≤ t < end`) is used by `_contains_time` and step 5, nowhere else. Test `test_slot_block_lookup_is_half_open_and_boundary_belongs_to_next` (boundary and session end) |
| `_contains_time` dispatch | **Pass** | `SessionSlots` with blocks uses `block_at`; otherwise the unchanged window rule, with its `max(start, now)` narrowing |
| Step 5 table: none / label mismatch / CLOSED → `TIME_OUTSIDE_SESSION`; FULL → `SLOT_FULL`; OPEN → `Write(expected_slot=block.start)`; only scoped `APPOINTMENT_REQUEST` sessions with `SessionSlots` | **Pass** | Matches plan C-6 step 5 and `block_state` (the one classifier) |
| Session-level reasons before block reasons (W-2 table) | **Pass** | Tests: `test_slot_booking_selected_session_precedes_block_reason`, `test_full_session_precedes_open_sibling_when_selected_by_name_or_time`, `test_slot_booking_full_named_session_does_not_depend_on_other_sessions`. The existing `test_named_evening_never_books_a_full_labelled_morning_block` is unchanged, plus the new N-1 variant `test_named_evening_ignores_full_morning_block_even_when_morning_has_open_blocks` |
| Named request cannot book through an unlabelled block | **Pass** | Step 5 label check (`normalised(s.label or "") != normalised(session)`). Policy and service tests, with and without a real Morning, both actions, no POST |
| UNKNOWN, D-6 and D-7 scope; slots disabled unchanged | **Pass** | Steps 3 and 4 are unchanged except the dispatch. Step 2 and step 5 are gated by `isinstance(facts.slots, SlotPlan)`, so the legacy path is identical. Tests for D-6 passed blockless windows, D-7 labelled exclusion, the stale labelled Morning, unlabelled UNKNOWN retention, and the unbounded fallback |
| Today and future clock handling | **Pass** (L-1) | Future blocks are classified with `now=None`. Today uses the minute rule in `block_state` |
| `SessionRequired` and `TIME_NOT_VERIFIABLE` with slots | **Pass** | Neither is reachable when slots apply (step 2 guarantees a time; step 5 returns before the legacy checks). No special-casing was added, as the brief required |

### Service integration (`booking.py`)

| Check | Result | Evidence |
|---|---|---|
| Both callers branch explicitly on `BookingResult` vs `Write` | **Pass** | `_create`: `isinstance(schedule, outcomes.BookingResult)`. `_change`: the same, then `isinstance(schedule, policy.Write)`. The truthy `blocked :=` idiom is gone |
| `None` only for the B-1 bypass | **Pass** | `_reschedule_gate` returns `None` only when the appointment is absent from the lookup. Test `test_reschedule_lookup_bypass_keeps_expected_slot_unknown` |
| P-2 guard prevents a write | **Pass** | `_schedule_result` (a static seam holding the gate's existing post-read mapping, not a copy) checks `SlotsNotRead` before the policy. Both CREATE and RESCHEDULE reach it through `_schedule_gate`. See the assessment below |
| `TimeRequired`: action-specific field and formatted alternatives | **Pass** | `preferredTime` for CREATE, `newPreferredTime` for RESCHEDULE; `ASK_WHICH_TIME`/`TIME_REQUIRED`; `sessions` via `session_out` with `openSlots`. Service and HTTP tests (`test_mcp_slots_require_time_then_publish_owner_block`), no POST |
| `slotTime` fallback and `slotMoved` | **Pass** | `_appointment_out`: `slotTime = owner slotTime or expectedTime` (null when both are absent); `slotMoved` only when the owner's slot is present, an expected slot is known, and they differ. CREATE passes `expected_slot` through `_written`; RESCHEDULE passes it explicitly; LIST, CANCEL and B-1 pass none. Tests cover 10:45 → 10:30 not moved, a moved block, a missing owner slot, LIST/CANCEL and B-1 |
| Session never forwarded | **Pass** | `_OWNER_FIELDS` is unchanged; the test asserts the owner body for both actions |
| Same operation repeated: capacity rechecked before owner replay | **Pass** | `test_same_operation_invocation_rechecks_changed_capacity_before_owner_replay`: second call → `SLOT_FULL` or `NO_OPEN_SLOT`, no owner write path, appointments unchanged (O-2) |
| Definite rejection and uncertain-write semantics | **Pass** | `_failure` and `ops_client.py` unchanged. Existing 1b tests are untouched and green |

**P-2 test adequacy:**
- **What is proved:** the pure call proves that the gate's own mapping refuses `SlotsNotRead` before any policy runs. Both booking callers already return on any `BookingResult` from that gate before building a write body; many existing refusal tests assert "no POST" through the same branch.
- **What is not proved, and why that is acceptable:** an end-to-end service test is not possible without mocking the reader, because `ScheduleReader.doctor` never produces `SlotsNotRead`. That impossibility is itself the invariant. The seam is the right proof here.

### Quality and scope

- **Deletions:** none in the four test modules (`grep '^-'` count is 0). The hand-back's prefix audit agrees.
- **Duplicated rules:** none. `block_at` and `block_state` are single homes; there is one P-2 guard shape (mirroring `_single`).
- **Removed unused parameter:** `_written`'s old `step` parameter (it was overwritten inside the function, so it was dead) is removed, with both callers updated. This is in scope, because the signature changed for `expected_slot` anyway.
- **No added reads, retries, flags or compatibility paths.**
- **Untouched (diff empty):** `tools.py`, `schedule_reader.py`, `ops_client.py`, `contract.py`, `identity.py`, `config.py`, stubs, `harness.py`, `conftest.py`, snapshot, `deploy/`, `docs/`.
- **Out-of-phase work:** no 4a (capabilities, P-1), 4b or 5 work.
- **Corrected fixtures:** five new service tests first used an empty board, which the stub turns into an unlabelled stale UNKNOWN entry, so the callback correctly won. Astra changed only those new fixtures to explicit fresh IN rows, with assertions unchanged. That is correct: the original fixture was testing the wrong situation. Astra's corrected-fixture baseline (5 failed on old code) is labelled as retrospective, separate from the initial red.

## 3. Commands run (independently, at `0d9689c`)

| Command | Result |
|---|---|
| `make test-fast` (via `rtk proxy`) | **1,016 passed**, 11 deselected, 2 Authlib deprecation warnings (pre-existing) |
| `make schema > .context/opus-slots-3b-schema.json` (via `rtk proxy`) | Exit 0; **64,111 bytes** (`stat`); `schemaVersion` `2026-10-08.1` |
| `cmp .context/opus-slots-3b-schema.json services/mcp/tests/contracts/mcp-tools.snapshot.json` (`/usr/bin/cmp`) | **Exit 0**; SHA-256 `3ef91e78ccfc8b730c540244f8e390bb1ca2bdc74576a8cc4207f93ecc7d6c62` |
| `env -u OPS_E2E_BASE_URL ./scripts/test.sh` | **Exit 0**. Lint clean; hermetic 1,016 passed; process e2e **2 passed**; package built; production and stubs images built; external gates not run (no profile); "all suites passed". Log: `.context/opus-slots-3b-testsh.log` |
| `git diff ef68962 0d9689c --check` | Exit 0 |
| `tests/test_server.py` × 8 (faulthandler 60 s) | 48 passed every time; the L-2 stall was not reproduced |
| Independent red: base `ef68962` source plus the four final test modules, in a temporary detached worktree (removed afterwards) | **77 failed, 502 passed**. Astra's initial red was 71 failed / 492 passed before supplementary tests. The difference matches the 16 supplementary cases plus the five corrected fixtures (some of which pass on base by design, as pins) |
| `SessionChoice` probe (both request models, seven inputs) | As in §2 |

## 4. Not tested

- **External systems:** the mock/live external gates, live owner APIs, ContextForge, the voice agent and latency. There were no live calls. The bench and external tests that submit untimed CREATE/RESCHEDULE are 4b.
- **Department path:** `SlotsNotRead` produced by the reader, and the P-1 guard (4a).
- **L-2 root cause:** not established.

## 5. Scope and next phase

- **Within 3b:** yes. Eight files exactly; no 4a, 4b or 5 work; the frozen schema is intact.
- **Phase 4a may begin:**
  - department capabilities read and `SlotsNotRead` production;
  - `is_match` in the reader counts;
  - the P-1 ended-window guard (plan 11.3, C-3 step 3), with its policy and department service tests;
  - the schema stays byte-identical.
- **Before 4a starts:** commit the plan revision 11.3 and the review reports, so the brief is built on saved docs.

## Plain-English summary for Garima

Astra's phase 3b work is correct and stays inside the eight planned files. The published schema is unchanged. My own runs all pass: 1,016 tests, the 2 process tests and the full script.

Booking now uses the slots properly:
- if no time is given, it asks for one and lists the open slots;
- a time in a full slot gives "slot full", and a closed or wrong-session slot gives "outside session";
- an open slot is booked, and the result reports the real slot time and whether Manoj moved it;
- your Evening at 10:00 cases, both versions, give "outside session";
- if the same request is repeated after the last place went, it is refused before Manoj is called again;
- the safety guard against booking with unread slots is in place;
- a blank session name is treated as none, while a 41-space session is rejected, as you approved.

There are no bugs. Two small notes:
1. **Small tidy-up (optional):** one place decides "is this today?" slightly differently from the rest of the code. The result is the same.
2. **Test run that froze once (old, not caused by this phase):** Astra reported it honestly. It happened while a test server was shutting down, in test setup code this phase didn't touch. I couldn't make it happen again in 10 runs. I suggest a later small fix so it fails quickly instead of hanging.

Phase 4a can start. Please commit the plan and review reports first.
