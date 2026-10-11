# Opus review: phase 3a-2 (availability policy, D-8 activation)

- **Commit:** `ef68962abb3ab74e8ed0b4419d429ee17bfa6a05`, "Apply slot evidence and confirmed on-call availability"
- **Base:** `44894dd39a4d0dce532c43f330fe188fb1afaab9`
- **Branch:** `Garry2012/slots-phase-1a-1b` (HEAD = review commit)
- **Inputs:**
  - brief `.context/attachments/JtjdbN/astra-build-slots-3a2.md` (byte-identical to `.context/astra-build-slots-3a2.md`)
  - `SLOTS-PLAN.md` revision 11.2
  - `.context/astra-prompt-booking-b2-m1.md`
  - `OPUS-SLOTS-3A1-W2-REVIEW.md`
  - `.context/slots-3a2-handback.md`
  - `git diff 44894dd..ef68962`
  - the full post-commit `availability_policy.py`
  - the live evidence file
- **Scope of approval:** this intermediate commit only. It is not deployable before phase 5.

## Verdict

**APPROVED for phase 3a-2. Phase 3b may begin.**

- **The implementation** follows the brief and plan C-1 to C-5, C-7, C-8 and C-6 steps 1 and 4. It stays inside the seven files and the frozen schema.
- **No implementation defects.**
- **Two plan-level gaps** came out of this review. Neither is reachable yet: both need `SlotsNotRead`, which nothing produces until 4a.
  - **P-1 (Medium):** decide before 4a.
  - **P-2 (Low):** carry into the 3b brief.
  - Neither is Astra's error; both follow the plan text as written.

## 1. Findings (most severe first)

### P-1: a department search lists a doctor whose session has already ended as "matched" (Medium, plan gap; reachable from 4a)

- **Where:** `availability_policy.py:242–243` (`session_decision` step 3), implementing SLOTS-PLAN C-3 step 3 literally.
- **Rule today:** the ended-window guard (`:239–240`) runs only for evidence `None` (C-3 step 2). Step 3 maps every IN/LATE/NOT_CONFIRMED row with `SlotsNotRead` to `SLOT_CHECK_REQUIRED`, whatever its supplied end time.
- **Reproduction** (pure policy run; board Morning IN 09:00–12:00, facility time 14:00):

  ```text
  REGULAR  slots=None          -> NOT_AVAILABLE SESSION_ENDED   (v0.3, unchanged)
  REGULAR  slots=SlotsNotRead  -> SLOT_CHECK_REQUIRED           (department search once 4a produces SlotsNotRead)
  ON_CALL  slots=SlotsNotRead  -> HANDOFF_REQUIRED ON_CALL_DOCTOR
  ```

- **Effect after 4a:**
  - With slots enabled, a today department search lists a regular doctor whose session ended hours ago under `DOCTORS_MATCHED`. With slots disabled, the same facts say `SESSION_ENDED`.
  - When the caller selects that doctor, the slot read then gives `SESSION_ENDED` (Manoj closes ended blocks, G-4). That is one wasted turn and a misleading "matches".
  - It is also inconsistent: the on-call doctor with the same row is refused, because C-8 checks "not ended".
- **Requirement:** K-3 ("matches the department request"); D-6 scope ("a passed time is refused"); C-3 one meaning per reason.
- **Smallest coherent correction (plan 11.3, then code):**
  - Apply the existing supplied-end guard to `SlotsNotRead` as well. Both lack block facts, so a supplied passed end time is the only end evidence.
  - In `session_decision`, the guard moves from inside the `evidence is None` branch to cover `evidence is None or SlotsNotRead`, before step 3.
  - Add one policy test for today and one for 4a's department path.
- **Decision for Garima:** confirm this rule, and I add it to the plan. It is best implemented in 4a, with its first producer and a department test.

### P-2: `decide_booking` would write on a `SLOT_CHECK_REQUIRED` decision (Low, latent; carry into 3b)

- **Where:** `availability_policy.py:416–455`. Step 1 handles `HANDOFF`, `CALLBACK`, `COULD_NOT_CHECK` and `NOT_AVAILABLE` only. A `SLOT_CHECK_REQUIRED` scope falls through to `Write()`.
- **Reproduction:** board IN 13:00–18:00 with `SlotsNotRead`, `preferred_time="15:00"` → `Write()`.
- **Not reachable:** booking always reads through `ScheduleReader.doctor`, which sets a `SlotPlan` or `None`, never `SlotsNotRead`. Only `department()` will produce it (4a), and booking never uses that.
- **Why record it:** booking is the one path that writes. The plan guards the same invariant on the availability side (`_single` returns `COULD_NOT_CHECK`/`SLOTS_UNAVAILABLE`, `availability.py:142–144`), but not in the pure booking policy.
- **Smallest correction (3b, no 3a-2 change):**
  - in the 3b brief, the booking gate treats `facts.slots` being `SlotsNotRead` as the same invariant failure: `COULD_NOT_RECORD`/`SLOTS_UNAVAILABLE`, no write;
  - one policy test proves it.

### Coverage notes (Low, no change required in 3a-2)

- **N-1:** the W-2 pin (`test_named_evening_never_books_a_full_labelled_morning_block`, `test_booking.py:1079`) covers a Morning with **no** open block. The variant where Morning has other open blocks (`SLOT_FULL` must still not apply under a named Evening) is not pinned. Add it in 3b, where the block lookup arrives.
- **N-2:** `_window` (unchanged legacy) uses second precision (`now.time() > end`) for on-call usability, while blocks use minute precision (`end ≤ now`). It only differs within the end minute. This is consistent with the brief, which asked for block expiry only; no action.

## 2. Requirement checklist

| Area | Requirement | Result | Evidence |
|---|---|---|---|
| Evidence | Disabled / unread / unmatched / matched distinguished | **Pass** | `SessionSlots`, `SessionSlots.missing()`, `SlotsNotRead`, `None` (`:73–86`); `_evidence` (`:321–324`); `open_slots` stays `None` unless the evidence is `SessionSlots` (`:275–278`) |
| Reconciliation | UNKNOWN > CANCELLED > NOT_CONFIRMED > LATE > IN | **Pass** | `reconcile_status` (`:214–217`), one ordered tuple; 5×5 table × stale test (`test_availability_policy.py:253–261`) |
| BOARD_STALE | Only for a stale UNKNOWN **board** row | **Pass** | `_evaluate_session:269` passes `owner_status == "UNKNOWN" and is_stale` from the pre-reconciliation board status. The contract states stale entries are UNKNOWN with times dropped (overlay `:466–468`) |
| C-3 order | Status → no evidence (legacy, including the ended guard) → unread → flag false/missing → blocks | **Pass** (see P-1 for the plan gap at step 3) | `session_decision:230–252`; flag false gives `NO_OPEN_SLOT` without inspecting blocks |
| C-4 | Minute precision, `end ≤ now` closed; future ignores the clock | **Pass** | `_block_ended:220–221`, `block_state:224–227`. Future passes `now=None` (`:247`, `:272`). Tests include `end == now` and `second=59` (`:295–300`) |
| Legacy | Unchanged without evidence, except D-8 | **Pass** | Without slots, future scope = day sessions = old alternatives; reasons and output rows identical. The six R8 D-7 tests are unchanged (no removed lines outside the brief's list) |
| Joining | Normalised labels, null ≡ "", duplicate board rows, slot-only today rows | **Pass** | `_slot_sessions:315–318`, `_today:333–349`, `_slot_only:327–330`. Test `:306` (blank and duplicate); live capture 1 (board `null` ↔ slot `""`) |
| Future | Usual vs one-day, null hours, other-weekday rows, scope or all rows | **Pass** | `_future:358–388`. Join uses only requested-weekday labels; one-day rows `one_day=True`; `NOT_USUAL_DAY` rows are not evaluated. Exits: `NO_USUAL_SCHEDULE` only when there is no usual schedule and no day sessions |
| D-7 | Future named scope keeps unlabelled unresolved rows | **Pass** | `:380–381`. Availability and booking tests for null and "" labels (`test_availability.py`, `test_booking.py:1097`) |
| W-2 | Named Evening (open) + 10:00 in a full labelled Morning → `TIME_OUTSIDE_SESSION`, no POST | **Pass** (N-1 variant for 3b) | `test_booking.py:1079`. The fixture puts 10:45 inside the single full Morning block 10:30–11:00 |
| D-8 | IN/LATE actionable only when usable; otherwise handoff; CANCELLED kept | **Pass** | `on_call:255–262`, applied after C-3 and before scope (`:273–274`), on the reconciled status |
| D-8 | Usual hours never count for on-call; an unread on-call profile is not `PROFILE_UNAVAILABLE` | **Pass** | `_future:359–360` checks ON_CALL before `profile is None`. Tests `:428`, `:437` |
| D-8 | Empty or unmatched scope, and WORKING_HOURS → handoff | **Pass** | `_empty_scope:307–312`, used by today, future and `working_hours:397–398` |
| D-8 | Handoff sessions expose `open_slots=()` | **Pass** | `open_slots` is computed after `on_call` (`:275–278`). Service test `test_on_call_handoff_does_not_publish_owner_open_slots` (`test_availability.py:667–677`) |
| C-7 | One `is_match`; `DOCTORS_MATCHED` with `bookableFound 0`; callback before handoff | **Pass** | `is_match:282`, used in `_combine`, both alternatives and `aggregate`. `aggregate:473–483` (`DOCTORS_MATCHED` keeps the default `bookable_found=0`). `rank:460–461`. Cap test `:469` |
| `_single` | `SlotsNotRead` → `COULD_NOT_CHECK`/`SLOTS_UNAVAILABLE`; no unreachable `SLOT_CHECK_REQUIRED` entry | **Pass** | `availability.py:142–150`. The map adds only `HANDOFF_REQUIRED` |
| Presentation | One date predicate; formatter only formats | **Pass** | `on_requested_date:290–291` is used by `outcomes.session_out` and `_single`'s `sessionMatched`. `session_out` maps `open_slots` to `SlotOut`, `owner_status` to `status`, `one_day` to `oneDay`, and re-applies no rule |
| Booking | Only the two handoff points changed; both actions refuse unresolved on-call; failures stay failures | **Pass** | `decide_booking:418–419`, `:444–445`. The old reason-based ON_CALL branch is gone. Tests at `test_booking.py:1031–1077`, CREATE and RESCHEDULE, bounded and unbounded, named and unnamed. Read failure → `COULD_NOT_RECORD`/`BOARD_UNAVAILABLE` |
| Boundaries | `booking.py`, `schedule_reader.py`, `ops_client.py`, pack, prompt, snapshot and docs unchanged; no reads, auth, retry or idempotency change | **Pass** | `git diff --quiet` over those paths: no diff. No request-path assertion changed (none removed; `count(...slots) == 2/1` kept) |
| Dead code | `TODAY_STATUS`, `_on_call` and the ON_CALL booking callback removed; no new unused code | **Pass** | `git grep` at `ef68962`: no matches (exit 1). Vulture (below) flags only Pydantic fields and enum members |
| Test changes | Only the brief's list; assertions updated, not weakened | **Pass** | Changed: 4 in `test_availability.py`, 2 in `test_availability_policy.py`, 2 in `test_booking.py`, 1 in `test_server.py` (journey line `:155` only). Each now asserts the D-8 or slot outcome, including `callback is None` |
| Live captures | Both, with board and profile context | **Pass** | `test_availability_policy.py:320–346`. Board rows and usual schedules match `evidence/manoj-slots-live-20261007.txt:5–63, 66–131` (capture 1: blank labels, no usual schedule, board IN 10:30–12:00; capture 2: Morning NOT_CONFIRMED with null times, Evening 18:30–19:30), at the capture time 14:35 |
| Schema | Byte-identical; no field, default, enum, description, instruction or version change | **Pass** | 64,111 bytes, SHA-256 `3ef91e78…6c62`; snapshot untouched |

## 3. Commands run (independently)

| Command | Result |
|---|---|
| `make test-fast` (via `rtk proxy`) | **894 passed**, 11 deselected, 2 Authlib deprecation warnings (pre-existing) |
| `make schema > .context/opus-slots-3a2-schema.json` (via `rtk proxy`) | Exit 0; **64,111 bytes** (`stat`) |
| `cmp .context/opus-slots-3a2-schema.json services/mcp/tests/contracts/mcp-tools.snapshot.json` (`/usr/bin/cmp`) | **Exit 0**, byte-identical; SHA-256 `3ef91e78ccfc8b730c540244f8e390bb1ca2bdc74576a8cc4207f93ecc7d6c62` |
| `env -u OPS_E2E_BASE_URL ./scripts/test.sh` | **Exit 0**. Lint clean; hermetic **894 passed**; process e2e **2 passed**; package built; production and stubs images built; external gates not run (no profile); "all suites passed". Log: `.context/opus-slots-3a2-testsh.log` |
| `git diff --check 44894dd..ef68962` | Exit 0 |
| Dead code: `uv run --with vulture==2.14 vulture` over `src/frontdesk_mcp` (60% confidence), filtered to the touched files | No unused function or class. Only Pydantic model fields, `model_config`, enum members (`SLOT_FULL` arrives in 3b; `SESSION_REQUIRED` pre-existing) and `SearchState.checked` (pre-existing) |
| Independent red check: base `44894dd` source plus the four new test files, in a temporary detached worktree (`/tmp/opus-3a2-red`, removed afterwards) | **111 failed, 346 passed**. This matches Astra's retrospective baseline exactly |
| Policy probes for P-1 and P-2 (pure functions, no I/O) | Outputs quoted in §1 |

**Red-first evidence:**
- **Astra's initial red:** 101 failed / 346 passed before source edits. That is accepted as reported (the run log was not re-executable at that point in history).
- **Astra's retrospective baseline:** 111 failed. This includes supplementary tests added during self-review, and the hand-back clearly labels it as distinct from the initial red.
- **My independent run:** reproduces the 111.
- **Expected passes on base:** some new tests are pins that pass on base by design, for example the W-2 named-Evening test, which the window rule already decides. That is expected.

## 4. Coverage gaps and not tested

- **Not reachable yet:** P-1 and P-2, until 4a. No department `SlotsNotRead` path runs through the reader yet; department tests construct it directly, as the brief instructed.
- **Booking with slots enabled is intermediate** (C-6 steps 2, 3 and 5 are 3b). Only the two handoff points, the session-level refusal (`test_enabled_slots_refuse_cancelled_session_before_booking`) and the W-2 pin are covered. Passing tests do not prove block-level booking.
- **External systems:** external gates (mock/live), live owner APIs, ContextForge and the voice agent are not exercised, and there were no live calls.
- **Latency:** not measured; no reads were added. The on-call by-name added group comes from 2b and is measured in the 4b bench.

## 5. Scope and next phase

- **Within 3a-2:** yes. Seven files exactly; no 3b work (`TimeRequired`, `block_at`, block lookup, `expected_slot`, `SessionChoice`) and no 4a work (reader capabilities, `SlotsNotRead` production, reader counts).
- **Deliberate deviations,** both as the brief asked and recorded in the hand-back:
  - `block_at` deferred to 3b;
  - no `SLOT_CHECK_REQUIRED` entry in `_single`.
- **Phase 3b may begin.**
  - **3b brief:** carries P-2 (booking refuses `SlotsNotRead`) and N-1 (W-2 variant with Morning open blocks), plus the D-1 freeze (SHA `3ef91e78…6c62`).
  - **P-1:** needs Garima's confirmation, then a plan 11.3 note, implemented in 4a.

## Plain-English summary for Garima

Astra's phase 3a-2 work is correct, stays inside the seven files, and doesn't change the frozen schema. All checks pass when I run them myself: 894 tests, the 2 process tests, and the full script including both Docker images.

The new behaviour works as designed:
- the stricter status wins when the board and slots disagree;
- a "not bookable" session offers nothing;
- an on-call doctor is bookable only with a confirmed, usable entry, and otherwise goes to the desk (never a callback);
- a desk handoff never shows open slots;
- your Evening at 10:00 example stays "outside session".

I found two gaps in our plan, not in Astra's code. Neither can happen yet:
1. **Ended sessions in department searches (needs your decision before phase 4a):** once department searches use slots, a doctor whose session ended earlier today would be listed as "matched" instead of "session ended". I recommend applying the existing "end time has passed" check there too.
2. **Booking guard (for the 3b brief):** the booking rule doesn't explicitly refuse a doctor whose slots were never read. That can't happen today, because booking always reads the slots, but it should refuse as a safety guard. I'll put it in the 3b prompt.

Phase 3b can start. Nothing here is production-ready until phase 5.
