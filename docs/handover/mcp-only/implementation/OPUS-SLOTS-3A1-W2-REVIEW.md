# Opus review: phase 3a-1 W-2 correction

- **Commit:** `44894dd39a4d0dce532c43f330fe188fb1afaab9`, "Clarify selected session in slot descriptions"
- **Base:** `96a02109c8ea31a15de77a62472366f0c1640caa`
- **Branch:** `Garry2012/slots-phase-1a-1b` (HEAD = review commit)
- **Inputs:**
  - brief `.context/attachments/lpuoPI/astra-fix-slots-3a1-w2.md` (byte-identical to `.context/astra-fix-slots-3a1-w2.md`)
  - `OPUS-SLOTS-3A1-W1-REVIEW.md`
  - `.context/slots-3a1-w2-handback.md`
  - `SLOTS-PLAN.md` C-3, C-5 and C-6
  - `availability_policy.py`
  - `tests/test_booking.py`
- **Scope of approval:** this staged wording correction only. It is not deployment or production readiness.

## Verdict

**APPROVED.**

- **W-2:** resolved, with no new findings.
- **Phase 3a-2:** may begin.

## 1. W-2 resolved: wording against current code and planned policy

**New sentence** (`packs/healthcare.json:19`, snapshot `:813`, `VOICE-TEAM.md:625` and `:1666`):

> With slots, the selected session is the supplied one, otherwise the one containing the time. When it is not bookable or has no open block, its session reason applies (NO_OPEN_SLOT or SESSION_ENDED); otherwise a time in one of its full blocks is SLOT_FULL, and a time in none of its open or full blocks is TIME_OUTSIDE_SESSION.

### Currently executable (slots disabled; no slot policy exists yet)

The first clause of the sentence ("the selected session is the supplied one, otherwise the one containing the time") already describes the deployed scoping:

- **Named session:** `_today` keeps only rows with a matching or blank label (`availability_policy.py:224–225`). Other labelled sessions are never considered.
- **Time narrowing:** `decide_booking` narrows by time **only when no session was supplied** (`:298–306`). With a supplied session, the time is checked only against the scoped sessions (`:321–322` → `TIME_OUTSIDE_SESSION`).
- **Pinned by a test:** `test_a_preferred_time_outside_the_chosen_session_window_is_rejected` (`tests/test_booking.py:499–503`). With `session="Morning"` and `preferredTime="15:30"`, the result is `NOT_AVAILABLE`/`TIME_OUTSIDE_SESSION`, even though the other labelled session (Afternoon, UNKNOWN, `MIXED_BOARD :426–430`) would otherwise give a callback. Morning's own state decides; the other session's state does not.

The rest of the sentence begins "With slots", so it describes **planned** behaviour, not anything executable now. Passing tests prove only the schema and text. They do **not** prove the slot policy exists; that arrives in 3a-2.

### Planned 3a-2 policy (SLOTS-PLAN C-3 steps 4–5, C-5 scope, C-6 steps 1–5)

- **Named session:** C-6 step 5 looks up the block "over the **scoped** `APPOINTMENT_REQUEST` sessions' blocks". A block in another labelled session is "none" → `TIME_OUTSIDE_SESSION`. C-5 keeps the same label scoping for today and for future dates (other labelled usual sessions are excluded).
- **No session named:** step 3 selects the session(s) containing the time. Step 4 applies that session's reason (`NO_OPEN_SLOT`/`SESSION_ENDED`) before step 5 classifies the block.

| Case | Plan result | New sentence |
|---|---|---|
| **"Evening" (open blocks); 10:00 in labelled Morning, Morning full with no open block** | `TIME_OUTSIDE_SESSION` (Morning out of scope) | Selected = Evening, which has open blocks; 10:00 is in none of Evening's blocks → `TIME_OUTSIDE_SESSION` ✓ |
| **"Evening" (open); 10:00 in a full Morning block, Morning has other open blocks** | `TIME_OUTSIDE_SESSION` | `TIME_OUTSIDE_SESSION` ✓. Morning's capacity is irrelevant |
| "Evening" with no open block; any time | `NO_OPEN_SLOT` (step 1, whole scope) | Session reason ✓ |
| "Evening" (open); time in Evening's full block, with others open | `SLOT_FULL` | `SLOT_FULL` ✓ |
| "Evening" (open); time in an open block of a retained unlabelled row | `TIME_OUTSIDE_SESSION` (step 5 label check) | Not in Evening's blocks → `TIME_OUTSIDE_SESSION` ✓ |
| No name; time in a full block; that session has no open block | `NO_OPEN_SLOT` | Session reason ✓ |
| No name; time in a full block; the session has others open | `SLOT_FULL` | `SLOT_FULL` ✓ |
| No name; time in a closed or ended block; the session has others open | `TIME_OUTSIDE_SESSION` | Not in its open or full blocks → `TIME_OUTSIDE_SESSION` ✓ |
| No name; every block of the session ended today | `SESSION_ENDED` | Session reason ✓ |
| No name; time in a session flagged not bookable | `NO_OPEN_SLOT` (C-3 step 4) | Session reason ✓ |
| No name; time in no block | `TIME_OUTSIDE_SESSION` (step 3) | No selected session. The preceding clause "no block contains the time" covers it ✓ |

**Residual, unchanged and accepted:** with a supplied label, a retained **unlabelled** row with its own refusal (callback, full) can decide first, through `_combine(…, named=True)` (`:200–205`). This is deliberate (D-7, R4-B2.3–4), already recorded in `OPUS-SLOTS-3A1-W1-REVIEW.md` §1, and covered by "NOT_AVAILABLE means the selected session/time is unavailable". It is not a finding.

## 2. Requirement checklist

| # | Requirement | Result | Evidence |
|---|---|---|---|
| 1 | W-2 resolved: a supplied session determines scope; the time selects only without one; Evening/10:00-in-Morning → `TIME_OUTSIDE_SESSION` whatever Morning's capacity | **Pass** | §1 |
| 2 | Exact approved replacement, consistent in the pack, snapshot, guide copy and guide reason row | **Pass** | On the raw file text at both revisions, `old.replace(OLD_SENTENCE, NEW_SENTENCE) == new` holds for all three files: pack 1→1, snapshot 1→1, guide 2→2 at `:625` and `:1666`. The pack description equals the snapshot `/tools/1/description`, and the guide contains the full description |
| 3 | Exactly three files; every change is the replacement; SLOT_FULL meanings, F-1 and N-1 unchanged | **Pass** | `git diff --name-only`: `VOICE-TEAM.md`, `packs/healthcare.json`, `mcp-tools.snapshot.json`. Unchanged counts: "SLOT_FULL means that time is full" 1/1/1; owner-rejection clause 1/1/1; guide `:666, 1671, 1699` SLOT_FULL lines 1 each; withdrawn qualifier "while its session has an open block" 0 everywhere; F-1 `[]` text 1/5/5; N-1 "when doctors match:" 1/1/1 |
| 4 | One changed leaf; stripped snapshots identical; no logic, test, field, type, default, enum, constraint, instruction, version, config or deploy change | **Pass** | Recursive removal of `description`/`title` only, defaults kept: equal. Canonical SHA-256 `6181894f…653c` on both sides, the same stripped hash as 6379670, 6254f3a and 96a0210, so the schema structure is unchanged since 3a-1. Exactly one changed leaf: `/tools/1/description` (`manage_booking`). `schemaVersion` stays `2026-10-08.1`; `instructions` are equal. `git diff --quiet` over `services/mcp/src` and `services/mcp/tests`, excluding the pack and contracts: no diff |
| 5 | Commands (below) | **Pass** | Section 3 |
| 6 | Facts, not scripts | **Pass** | The sentence states a mapping from facts to reasons, with no agent instruction. The facts-only and instruction-length tests pass unchanged inside the 794 |

## 3. Commands run (independently, at `44894dd`)

| Command | Result |
|---|---|
| `make test-fast` (via `rtk proxy`) | **794 passed**, 11 deselected, 2 Authlib deprecation warnings (pre-existing); ruff clean |
| `make schema > .context/opus-slots-3a1-w2-schema.json` (via `rtk proxy`, so the output was not filtered) | Exit 0; **64,111 bytes** (`stat`), the same as the snapshot |
| `cmp .context/opus-slots-3a1-w2-schema.json services/mcp/tests/contracts/mcp-tools.snapshot.json` (`/usr/bin/cmp`) | **Exit 0**, byte-identical. Both SHA-256 `3ef91e78…6c62` |
| `env -u OPS_E2E_BASE_URL ./scripts/test.sh` | **Exit 0**. Lint clean; hermetic 794 passed; process e2e **2 passed**; sdist and wheel built; production and stubs images built; external gates not run (no profile); "all suites passed". Log: `.context/opus-slots-3a1-w2-testsh.log` |
| `git diff --check 96a0210..44894dd` | **Exit 0**, no whitespace errors |
| `git grep -n "the session containing the time is not bookable" -- services/ docs/handover/VOICE-TEAM.md` | No matches, **exit 1** (as expected) |
| Stripped comparison, exact-substitution and count checks (Python over `git show` of both revisions) | As in the checklist |

## 4. Not tested

- **Slot policy:** none of the "With slots" behaviour runs yet. It was checked against SLOTS-PLAN C-3, C-5 and C-6; 3a-2 must implement it and pin these cases with tests.
  - **Recommendation for the 3a-2 brief:** pin the named-session case "Evening open, time in a full labelled Morning → TIME_OUTSIDE_SESSION" alongside the C-6 step tests.
- **External services:** the mock/live external gates, live owner APIs, ContextForge and voice behaviour. These are out of scope, and there were no live calls.
- **Astra's red/green evidence:** accepted as reported. The independent byte and stripped comparisons are the meaningful checks.

## 5. Answers

- **APPROVED or CHANGES REQUIRED:** **APPROVED.**
- **W-2:** resolved.
- **Phase 3a-2:** may begin.
  - **Freeze:** schema `2026-10-08.1` with snapshot SHA-256 `3ef91e78…6c62` is the frozen publication (D-1). 3a-2 and later phases must keep `make schema` byte-identical to it.
  - **3a-2 brief:** carries the existing note (a C-8 handoff session has `open_slots == ()`) and the named-session test above.
- **Production readiness:** not claimed. The schema is staged and not deployed; the canary stays on `2026-10-06.1`, and the slot behaviour is unimplemented until 3a-2 onwards.
