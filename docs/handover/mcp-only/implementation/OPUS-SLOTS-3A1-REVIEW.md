# Opus review: slots plan phase 3a-1 (final schema publication)

Reviewed 8 October 2026.

| | |
|---|---|
| **Commit reviewed** | `6379670cea59eb17556f6a28494cbb296e544b79`, "Publish final slots MCP schema without policy changes" |
| **Branch** | `Garry2012/slots-phase-1a-1b` |
| **Base** | `4aad4fd` |
| **HEAD** | `6379670` (not moved) |
| **Controlling brief** | `.context/astra-build-slots-3a1.md`, "Brief revision 2" |

**Scope:** `git diff 4aad4fd..6379670`, 7 files.

**Not done:** no code changes, commits, pushes, merges or deployments; no owner API calls. `temp/` is preserved, and this report is uncommitted.

**Verdict: CHANGES REQUIRED, one small wording fix (F-1) before the schema freezes.**
- Everything else is correct, in scope and fully verified.
- F-1 only changes description text. It blocks because D-1 forbids any schema change after this commit, so an inaccurate description published now would be permanent.
- Once F-1 is fixed and re-verified, phase 3a-2 may begin.
- Approving this staged schema says nothing about production readiness. The commit is not deployable.

## 1. Findings

### Blocker

**F-1: `openSlots` "[] means checked with no open block" contradicts the plan's projection rule** (introduced here)

**Where it appears:**
- `services/mcp/src/frontdesk_mcp/outcomes.py:47–51` (`_OPEN_SLOTS_DESCRIPTION`, used by both session types);
- its snapshot copies;
- `packs/healthcare.json:6` (the availability description: "openSlots contains the open blocks; [] means checked with no open blocks");
- `docs/handover/VOICE-TEAM.md:101, 1688–1689`, and the generated table rows at `:268, 300, 927, 942`.

**Why it is wrong:** plan C-1 (`SLOTS-PLAN.md:138`) says `open_slots` holds *the OPEN blocks only when the session decision is `APPOINTMENT_REQUEST`, otherwise `()`*. The published text says `[]` means the owner has no open block, and calls `openSlots` "the owner's open blocks". These differ whenever the owner reports open blocks but the session does not permit a request:

| Case (all approved rules) | Owner data | Decision | `openSlots` per plan | Published meaning |
|---|---|---|---|---|
| On-call doctor, NOT_CONFIRMED with open blocks (D-8, C-8) | open blocks | `HANDOFF_REQUIRED` | `[]` | "no open block": **false** |
| Session flag `bookable false` with inconsistent block flags (C-3 step 4: blocks "neither inspected nor offered") | blocks marked open | `NOT_AVAILABLE`/`NO_OPEN_SLOT` | `[]` | "no open block": **false** |

**Impact:** the voice team would be told, permanently, that `[]` proves no capacity exists. In these cases it actually means no block is **offered**, because the session doesn't permit a request.

**Evidence:** the plan table at `:133–138` against the text at `outcomes.py:47–51` and `healthcare.json:6`.

**Smallest coherent correction:** one description fix, propagated to its copies; no code or test logic changes. Suggested fact wording:
> "Open blocks offered for this session and date: the owner's open blocks when the session permits a request. null means slots were not checked (disabled, WORKING_HOURS, or a department search pending doctor selection); [] means checked and no block is offered (none open, or the session does not permit a request). When slots apply, CREATE or RESCHEDULE times outside these blocks are refused."

- Apply the same meaning in `healthcare.json:6` ("openSlots lists the offered open blocks; [] means checked with none offered…") and in VOICE-TEAM `:1688–1689`.
- Regenerate the snapshot and the VOICE table rows.
- Files: the same set already in this commit.
- **Note for the 3a-2 brief:** when C-8 turns a session into a handoff, its `open_slots` must be `()`, consistent with this wording.

### Minor (fix in the same edit; it is also frozen text)

**F-2: "no open block contains the time" also covers a FULL block** (introduced here)

- **Where:** `packs/healthcare.json:19` (booking description) and `VOICE-TEAM.md:1666`.
- **Why it is imprecise:** the booking description says `TIME_OUTSIDE_SESSION` means "…with slots, no open block contains the time". A **full** block is not open, so this literally includes the full case. But plan C-6 step 5 returns `SLOT_FULL` for a full block, and `TIME_OUTSIDE_SESSION` only for no block or a closed or ended block. The `SLOT_FULL` clause in the same text partly resolves this, but the two statements overlap.
- **Correction:** "…with slots, no block contains the time, or the containing block is closed or ended, or a supplied session label does not match its session; a full containing block is SLOT_FULL."

### Optional nit

**N-1:** "Department searches with slots enabled return DOCTORS_MATCHED and SLOT_CHECK_REQUIRED" (`healthcare.json:6`) reads as unconditional. Per C-7 it applies when doctors match. A department with no match still gives callback, handoff or NOT_AVAILABLE, as the next sentence implies for the slots-disabled case. Suggested: "…return DOCTORS_MATCHED for matching doctors (SLOT_CHECK_REQUIRED)…". Fold it into the F-1 edit if convenient.

## 2. Complete schema publication

| Requirement | Result | Evidence |
|---|---|---|
| `SlotOut` {start, end, available} | **Pass** | `outcomes.py`: HH:MM pattern; `available ≥ 0`; factual descriptions. |
| `openSlots` on both session types, default `null` | **Pass** | `BoardSessionOut`, `UsualSessionOut`. |
| `UsualSessionOut.status=null`, `oneDay=false` | **Pass** | |
| `start`/`end` nullable but required | **Pass** | Snapshot: `anyOf [string, null]`, no `default`, still in `required` (checked for both tools). |
| `AppointmentOut.slotTime` (HH:MM or null, default null) and `slotMoved` (default false) | **Pass** | |
| `Decision` gains `SLOT_CHECK_REQUIRED` and `HANDOFF_REQUIRED` | **Pass** | `availability_policy.py`, enum only. |
| `Reason` gains `NO_OPEN_SLOT` and `SLOT_FULL` in both tools, `Callback` included | **Pass** | Snapshot `$defs.Reason` in both tools (11 references). |
| `DOCTORS_MATCHED`, `ASK_WHICH_TIME` | **Pass** | |
| Version `2026-10-08.1` | **Pass** | |
| Input types, defaults, constraints and annotations unchanged | **Pass** | Old and new snapshots compared after stripping `description`/`title`: all four tools' input schemas and annotations identical. Only input descriptions changed. |
| Nothing later phases need is missing | **Pass** | Checked against 3a-2, 3b and 4a: `TimeRequired` uses the existing `fields`/`sessions` plus `ASK_WHICH_TIME`; slot-only rows today fit `BoardSessionOut` (`status`, `isStale` false, nullable times); one-day rows fit `UsualSessionOut` (`daysOfWeek []`, `onRequestedDate`, nullable hours); handoff uses the existing `HANDOFF_REQUIRED`/`TRANSFER_DESK`; the new detail strings are free text. **Only F-1 and F-2 need text changes before the freeze.** |

## 3. No premature behaviour

| Requirement | Result | Evidence |
|---|---|---|
| Only enum declarations in `availability_policy.py` | **Pass** | 4 added lines. |
| `rank`, `_single`, `session_out`, `doctor_out`, `_appointment_out` unchanged | **Pass** | `availability.py` and `booking.py` are not in the diff; `outcomes.py` changes only models and descriptions. |
| No producer of new values; no slot policy, time requirement, session normalisation or moved-time logic | **Pass** | The new fields stay at their defaults. |
| No filtering, shim, endpoint, configuration, retry or idempotency change | **Pass** | |
| Additive serialised fields versus regression | **Pass** | The only behaviour-visible difference is the approved `null`/`false` fields, shown in the VOICE-TEAM slots-disabled examples (`openSlots: null`). |

## 4. The approved test exception

**Pass.** The only test-source change is `test_availability.py:41`, in `test_known_doctor_today_returns_every_window_and_every_board_session`. It is the exact approved replacement: the `patientsPerHour` exclusion is kept, and the comment plus `all(b.openSlots is None for b in doctor.board)` is added. Every other assertion is unchanged, and `test_server.py` is untouched.

## 5. Meanings and factual wording

| Requirement | Result |
|---|---|
| `null`/`[]` meaning of `openSlots` | **Fail: F-1** |
| Department matches are not confirmed availability (K-3) | **Pass** ("match the request, not yet available"; `bookableFound=0`). See N-1. |
| Ordinary unresolved schedule → callback; on-call → handoff without callback metadata | **Pass** (D-6, D-8; instructions, both tools, VOICE `:312, 318, 960, 962, 1654–1655, 1684`) |
| One-day sessions date-specific; null hours mean no bookable time | **Pass** |
| `slotTime` fallback owner → `expectedTime` → `null` | **Pass** (field, booking description, instructions) |
| `slotMoved` (10:45 → 10:30 not moved; false for LIST/CANCEL) | **Pass** |
| `ASK_WHICH_SESSION` slots-disabled only; mismatched label → `TIME_OUTSIDE_SESSION` | **Pass** (VOICE `:654–655`, booking description). See F-2 for the `TIME_OUTSIDE_SESSION` text. |
| `ASK_WHICH_TIME` with returned `openSlots` | **Pass** |
| Owner `SLOT_FULL` rejection carries no alternatives | **Pass** ("establishes no availability at other times") |
| `UNCERTAIN`: desk handoff, not retry; a same-operation re-run can be refused | **Pass**, including "refusal does not prove the earlier write failed" |
| `NOTED` is a request; NOT_CONFIRMED can be noted for desk confirmation | **Pass** |
| Instructions under 1,000 characters with required facts | **Pass** (965 characters; both text tests pass unchanged) |
| Facts, not scripts | **Pass**. The earlier imperative 1b paragraphs are restated as facts (`OFFER_OTHER_SESSION_OR_TIME` row, `SLOT_FULL` rows). A search for "offer only", "check availability again", "tell the caller" and "say" finds only a historical changelog line. |
| "Store" → "Stores" | **Pass**, wording only (summary tool description). |

## 6. Documentation and deployment honesty

| Requirement | Result |
|---|---|
| Field tables and input blocks match the snapshot | **Pass** (`test_server.py:409/442` pass) |
| New outcomes, decisions, reasons and the four detail strings documented | **Pass** (`:1697–1698` and the reason/decision tables) |
| Examples clearly slots-disabled, with the new defaults visible | **Pass** |
| Historical on-call callback wording marked as superseded | **Pass** (`:1717–1718`) |
| Canary statement stays `2026-10-06.1`; `2026-10-08.1` explicitly not deployed | **Pass** (`:11–13`, `:1734–1745`, "Publication alone does not activate it") |
| No contradictions across the whole guide | **Pass** apart from F-1 and F-2 |

## 7. Verification

| Check | Result |
|---|---|
| `env -u OPS_E2E_BASE_URL ./scripts/test.sh` | **Exit 0.** Lint passed; hermetic **794 passed, 11 deselected**; process e2e **2 passed**; package built; production and stub images built (Docker available); "external gates not run"; "all suites passed". |
| `make schema > /tmp/r3a1-schema.json`, then `cmp` with the snapshot | **Byte-identical.** |
| Snapshot structure (Python comparison against `4aad4fd`) | Inputs and annotations unchanged except descriptions; nullable-but-required hours; `Reason` extended in both tools. |
| Footprint | 7 files, exactly the brief's list. |
| TDD evidence | **Baseline:** `before` 794 passed. **First round:** `red` 2 failed (snapshot and table checks), `green-schema` 4 passed, `after` 3 failed (the conflict Garima resolved). **Revision 2:** `r2-red` 3 failed, `r2-green` 3 passed, `r2-fast` 794 passed. **Other:** `full.txt` "all suites passed"; `slots-3a1-vulture.txt` empty. Consistent. |
| Instruction length | 965 characters. |

**Not verified:** live voice behaviour, ContextForge schema refresh, deployment. External gates were not run (by design).

## 8. Checklist

| Area | Status |
|---|---|
| Complete schema publication | pass |
| No premature behaviour | pass |
| Exact test exception | pass |
| Final meanings: `openSlots` `[]` | **fail (F-1)** |
| Final meanings: `TIME_OUTSIDE_SESSION` precision | minor (F-2) |
| Final meanings: all other items | pass |
| Factual wording; instruction limit | pass |
| Documentation and deployment honesty | pass |
| Verification (tests, schema, full script, vulture) | pass |
| Production readiness | not assessed (not deployable by design) |

**Blockers:** F-1 only.

**Optional cleanup:** F-2 (recommended in the same edit, since it is also frozen text) and N-1.

**Verdict:** CHANGES REQUIRED for phase 3a-1, limited to the description fix above.

**Phase 3a-2:** may begin once the F-1 correction (with F-2 and N-1 if adopted) is committed, the snapshot and VOICE tables are regenerated, and `make test-fast` plus the byte-for-byte schema comparison pass. A short re-review of that one commit is enough.

## 9. For Garima

Astra published the complete final schema correctly. All required fields and values are there; tool behaviour is unchanged; the one approved test change is exactly as agreed; descriptions read as facts; and VOICE-TEAM.md clearly says this is not deployed yet. All checks pass: 794 tests, the process tests, the package build and both Docker images, and the schema matches the snapshot exactly.

**One description must be corrected before the schema freezes:**
- **The problem:** it says an empty `openSlots` list means "Manoj has no open slots". Under our rules, the list can also be empty when Manoj has open slots that we deliberately don't offer, such as for an unconfirmed on-call doctor (your D-8).
- **Why it matters now:** after this commit the schema can never change, so the wording must be right now.
- **The fix:** a few sentences of wording, then the generated files are regenerated. No code logic changes.

A second, smaller wording overlap ("outside session" versus "slot full") is best fixed in the same edit. Once that commit is in, phase 3a-2 can begin.
