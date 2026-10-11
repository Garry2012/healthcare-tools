# Opus review: phase 3a-1 W-1 correction

- **Commit:** `96a02109c8ea31a15de77a62472366f0c1640caa`, "Clarify session refusal precedence in slot descriptions"
- **Base:** `6254f3a9978a548c4633b5695669ff526f14c4d6`
- **Branch:** `Garry2012/slots-phase-1a-1b` (HEAD = review commit)
- **Inputs:**
  - brief `.context/attachments/oCkP6H/astra-fix-slots-3a1-w1.md` (byte-identical to `.context/astra-fix-slots-3a1-w1.md`)
  - `OPUS-SLOTS-3A1-WORDING-REVIEW.md`
  - `SLOTS-PLAN.md` C-3, C-5 and C-6
  - `.context/slots-3a1-w1-handback.md`
  - `git diff 6254f3a..96a0210`
  - the current policy code (`availability_policy.py`)
- **Scope of approval:** this staged wording correction only. It is not production readiness, and nothing is deployed.

## Verdict

**CHANGES REQUIRED: one low-severity sentence (W-2).** The defect is in the wording **I** supplied, not in Astra's work.

- **Astra's commit:** implements the approved brief exactly. Three files, one sentence in four places, description only, all checks green.
- **W-1:** resolved for every booking without a supplied session label. The sentence states that the session reason (NO_OPEN_SLOT, SESSION_ENDED) comes before the block reasons (SLOT_FULL, TIME_OUTSIDE_SESSION).
- **W-2:** a booking that supplies a session label but chooses a time inside a **different, labelled** session. The sentence keys the precedence on "the session containing the time", but the code and plan key it on the **selected** (scoped) session. In that case the description predicts the wrong reason.
- **Why raise it now:** D-1 freezes these descriptions in 3a-1, and the fix is one sentence.
- **If Garima prefers to accept W-2** as a documented limitation (both answers are refusals with the same checked alternatives), this commit can be approved as is.

## 1. Findings

### W-2: precedence is keyed on "the session containing the time", not the selected session (Low, frozen text; introduced by the reviewer's W-1 wording)

- **Where:**
  - `services/mcp/src/frontdesk_mcp/packs/healthcare.json:19`;
  - snapshot `:813`;
  - `docs/handover/VOICE-TEAM.md:625` (generated copy) and `:1666` (reason row).
- **Text:** "With slots, when **the session containing the time** is not bookable or has no open block, its session reason applies (NO_OPEN_SLOT or SESSION_ENDED); only otherwise is a full containing block SLOT_FULL and a closed or ended one TIME_OUTSIDE_SESSION."
- **Evidence (code, unchanged by 3a-2 per C-6 "the current structure stays"):**
  - **Today's scope:** with a supplied label, `_today` drops every other *labelled* row before booking sees it (`availability_policy.py:224–225`: keep rows with no label or a matching label).
  - **Time selection:** `decide_booking` narrows by time only when **no** session was supplied (`:298`). With a label, the time is checked only against the scoped sessions (`:321–322` → `TIME_OUTSIDE_SESSION`).
  - **Plan:** C-6 step 5 looks the block up "over the **scoped** `APPOINTMENT_REQUEST` sessions' blocks"; a block outside them is "none" → `TIME_OUTSIDE_SESSION`.
  - **Future dates:** the future label rule likewise excludes other labelled usual sessions (C-5).
- **Failing case:** booking with `session="Evening"` (Evening has open blocks) and `preferredTime=10:00`, where 10:00 lies in Morning's blocks:

| Morning at 10:00 | Plan / code result | Description predicts |
|---|---|---|
| Full, and Morning has no open block | `TIME_OUTSIDE_SESSION` (Morning is out of scope) | `NO_OPEN_SLOT` (the session containing the time has no open block) |
| Full, and Morning has other open blocks | `TIME_OUTSIDE_SESSION` | Ambiguous: `SLOT_FULL` by this sentence, `TIME_OUTSIDE_SESSION` by the preceding label-mismatch clause |

- **All cases without a session label match the plan.** Time selection makes the containing session the scope (`:298–301`).
- **Smallest correction (text only; same three files; replace the W-1 sentence in `healthcare.json:19` and `VOICE-TEAM.md:1666`, then regenerate the snapshot and `:625`):**

  > With slots, the selected session is the supplied one, otherwise the one containing the time. When it is not bookable or has no open block, its session reason applies (NO_OPEN_SLOT or SESSION_ENDED); otherwise a time in one of its full blocks is SLOT_FULL, and a time in none of its open or full blocks is TIME_OUTSIDE_SESSION.

- **Checked against every case (C-3 steps 4–5, C-6 steps 1–5, code `:224–225`, `:298–322`):**

| Request | Plan / code | Proposed sentence |
|---|---|---|
| No label; time in a full block; that session has no open block | `NO_OPEN_SLOT` (step 4) | `NO_OPEN_SLOT` ✓ |
| No label; time in a full block; that session has another open block | `SLOT_FULL` (step 5) | `SLOT_FULL` ✓ |
| No label; time in a closed or ended block; the session has another open block | `TIME_OUTSIDE_SESSION` | `TIME_OUTSIDE_SESSION` ✓ |
| No label; every block of the session has ended | `SESSION_ENDED` (C-3 step 5) | Session reason ✓ |
| No label; time in a session flagged not bookable | `NO_OPEN_SLOT` (C-3 step 4) | Session reason ✓ |
| No label; time in no block | `TIME_OUTSIDE_SESSION` (step 3) | Covered by the preceding clause "no block contains the time" ✓ |
| "Evening" (open); time in a full labelled Morning | `TIME_OUTSIDE_SESSION` | `TIME_OUTSIDE_SESSION` ✓ |
| "Evening" with no open block; time anywhere | `NO_OPEN_SLOT` (step 1, whole scope) | Session reason ✓ |
| "Evening" (open); time in Evening's full block, with others open | `SLOT_FULL` | `SLOT_FULL` ✓ |
| "Evening" (open); time in an open block of a retained *unlabelled* row | `TIME_OUTSIDE_SESSION` (step 5 label check) | `TIME_OUTSIDE_SESSION` ✓ |

- **Known residual (pre-existing design, not this wording):** with a supplied label, a retained unlabelled row with its own refusal (a callback, or a full unlabelled session) can decide the result first. That comes from `_combine(…, named=True)` (`:200–205`), deliberately kept by D-7 and R4-B2.3–4. The general clause "NOT_AVAILABLE means the selected session/time is unavailable" covers it, so no change is needed here.

### Confirmed intact (no change requested)

- **SLOT_FULL meaning lines unchanged, and the withdrawn qualifier not reinstated:**
  - "SLOT_FULL means that time is full" and "an owner SLOT_FULL write rejection carries none": one each in the pack, snapshot and guide;
  - `VOICE-TEAM.md:666, 1671, 1699`: unchanged;
  - "while its session has an open block": 0 occurrences anywhere.
- **F-1 intact:** "[] means checked and no block is offered (none open, or the session does not permit a request)" appears 1× in the pack, 5× in the snapshot (the tool description plus four field descriptions) and 5× in the guide. The guide prose at `:1688–1690` is also unchanged.
- **N-1 intact:** "SLOT_CHECK_REQUIRED when doctors match:" appears 1× each in the pack, snapshot and guide.

## 2. Requirement checklist

| # | Requirement | Result | Evidence |
|---|---|---|---|
| 1 | Exact approved replacement; session precedence over block reasons | **Pass** for the exact text. **W-2** for named-session precision | The word diff shows only "A full containing block is SLOT_FULL." replaced by the brief's sentence, character for character (my script: the old description with that one substitution equals the new one) |
| 2 | Consistent in the booking description, snapshot, copied guide description and guide reason row | **Pass** | `healthcare.json:19`, snapshot `:813`, `VOICE-TEAM.md:625` and `:1666`. The pack description equals the snapshot's `/tools/1/description`; the guide contains the full description, and the sentence appears 2× in it (`:625`, `:1666`) |
| 3 | General SLOT_FULL definitions unchanged; no withdrawn qualifier | **Pass** | Counts above |
| 4 | Exactly three files | **Pass** | `git diff --name-only 6254f3a..96a0210` lists `VOICE-TEAM.md`, `packs/healthcare.json`, `mcp-tools.snapshot.json`; 4 insertions, 4 deletions |
| 5 | Only `/tools/1/description` differs; stripped snapshots identical | **Pass** | Recursive removal of `description`/`title` only, defaults kept: equal. My canonical (`sort_keys`) SHA-256 is `6181894f…653c` on both sides (Astra's `3a89413d…` uses a different serialisation). Exactly one changed leaf: `/tools/1/description` (`manage_booking`) |
| 6 | No field, type, default, enum, constraint, policy, formatter, test, instruction, version, config or deploy change; `outcomes.py` untouched | **Pass** | `git diff --quiet` over `outcomes.py` and the test source (excluding contracts): no diff. `schemaVersion` stays `2026-10-08.1`; `instructions` are equal |
| 7 | Factual wording; F-1 and N-1 intact | **Pass** | The sentence states a mapping, not an agent instruction; the facts-only test passes inside the 794. F-1/N-1 counts above |

## 3. Commands run (independently, at `96a0210`)

| Command | Result |
|---|---|
| `make test-fast` (via `rtk proxy`) | **794 passed**, 11 deselected, 2 Authlib deprecation warnings (pre-existing); ruff clean |
| `make schema > .context/opus-slots-3a1-w1-schema.json` (via `rtk proxy`, so the output was not filtered) | Exit 0; **64,031 bytes** (`stat`), the same size as the snapshot |
| `cmp .context/opus-slots-3a1-w1-schema.json services/mcp/tests/contracts/mcp-tools.snapshot.json` | **Exit 0**, byte-identical. Both SHA-256 `cc4068e9…4988`, matching Astra's claim |
| `env -u OPS_E2E_BASE_URL ./scripts/test.sh` | **Exit 0**. Lint clean; hermetic 794 passed; process e2e 2 passed; sdist and wheel built; production and stubs images built; external gates not run (no profile); "all suites passed". Log: `.context/opus-slots-3a1-w1-testsh.log` |
| `git grep -n "A full containing block is SLOT_FULL" -- services/ docs/handover/VOICE-TEAM.md` | No matches, **exit 1** (as expected) |
| Stripped snapshot comparison and string counts (Python over `git show` of both revisions) | As in the checklist |

- **Truncation guard:** schema output went through `rtk proxy`, and the file size was confirmed with `stat` (a filtered `wc -c` printed `0`, which was a wrapper artefact). `/usr/bin/cmp` exit 0 and identical SHA-256 values confirm the full file.

## 4. Not verified

- External gates (mock/live), live owner APIs, ContextForge and voice behaviour: out of scope, and there were no live calls.
- Runtime slot behaviour: not implemented until 3a-2. W-2 was checked against the current `decide_booking`/`_today` code, whose structure C-6 keeps, and against the plan, not against executing slot policy.
- Astra's red/green snapshot-test evidence: accepted as reported. The independent byte comparison is the meaningful check.

## 5. Answers

- **APPROVED or CHANGES REQUIRED:** **CHANGES REQUIRED** (W-2 only: one sentence, text-only, same three files). Astra's commit is an exact implementation of the brief. If Garima accepts W-2 as a limitation instead, approve `96a0210` as is.
- **W-1:** resolved for requests without a session label. With a supplied label, precedence follows the selected session, which W-2 corrects.
- **Phase 3a-2:** may begin once the W-2 sentence is committed and re-checked: same proof, and only `/tools/1/description` may differ from `96a0210`. If Garima accepts W-2, it may begin now. 3a-2 must keep the schema byte-identical either way, and its brief will carry the existing note that a C-8 handoff session has `open_slots == ()`.
- **Production readiness:** not claimed. Schema `2026-10-08.1` is staged, not deployed; the canary stays on `2026-10-06.1`.
