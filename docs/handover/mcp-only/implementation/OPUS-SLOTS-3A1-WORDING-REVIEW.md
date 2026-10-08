# Opus review: phase 3a-1 wording correction

- **Commit:** `6254f3a9978a548c4633b5695669ff526f14c4d6`, "Clarify offered slots and booking refusal descriptions"
- **Base:** `6379670cea59eb17556f6a28494cbb296e544b79`
- **Branch:** `Garry2012/slots-phase-1a-1b` (HEAD = review commit)
- **Inputs:**
  - `.context/astra-fix-slots-3a1-wording.md`
  - `OPUS-SLOTS-3A1-REVIEW.md` (F-1, F-2, N-1)
  - `SLOTS-PLAN.md` revision 11.2, C-1 and C-3 to C-8
  - `.context/astra-build-slots-3a1.md`, Brief revision 2
  - `.context/slots-3a1-wording-handback.md`
  - `git diff 6379670..6254f3a`
- **Scope of approval:** this staged schema correction only. It is not production readiness: the slots behaviour is still unimplemented (3a-2 onwards), and nothing is deployed.

## Verdict

**CHANGES REQUIRED.** There is one wording finding, W-1, and the fix is small and text-only.

- **F-1:** resolved.
- **N-1:** resolved.
- **F-2:** only partly resolved. The new SLOT_FULL sentence is unconditional, but session-level refusals (C-3 step 5, C-6 step 4) come first.
  - The error comes from **my own F-2 correction text** in `OPUS-SLOTS-3A1-REVIEW.md:60`. Astra applied it faithfully.
  - I raise it now because D-1 freezes these descriptions in 3a-1. Correcting them later would mean a new schema publication.

**Phase 3a-2 may begin once W-1 is committed and re-checked.** That re-check is the same text-only proof, and should take minutes.

Everything else is clean: four files, description values only, stripped schema identical, and all suites green.

## 1. Findings

### W-1: block-level reasons are stated without the session-level precedence (Minor, frozen text, blocking for the freeze)

- **Where:**
  - `services/mcp/src/frontdesk_mcp/packs/healthcare.json:19` (booking description);
  - its generated copies: snapshot `:813` and `VOICE-TEAM.md:625`;
  - the `VOICE-TEAM.md:1666` reason row.
- **Text:** "…TIME_OUTSIDE_SESSION means outside known bounds or, with slots, no block contains the time, the containing block is closed or ended, or a supplied session label does not match its session. **A full containing block is SLOT_FULL.**"
- **Why it is wrong:** under the plan, the block-level reasons apply only when the time's session still has an open block. Otherwise, the session reason decides at C-6 step 4, before step 5 ever looks up the block:

| Chosen time lands in… | Description predicts | Plan result |
|---|---|---|
| A FULL block; the session has no OPEN block (all full, or full plus closed) | `SLOT_FULL` | `NO_OPEN_SLOT`: C-3 step 5 "otherwise → NO_OPEN_SLOT"; C-6 step 4 "A selected session that is entirely full answers `NO_OPEN_SLOT` here" |
| An ended block today; every block of the session has ended | `TIME_OUTSIDE_SESSION` | `SESSION_ENDED` (C-3 step 5) |
| A closed (`bookable false`) block; the session has no OPEN block | `TIME_OUTSIDE_SESSION` | `NO_OPEN_SLOT` (C-3 step 5) |
| A block of a session flagged `bookable false` | `TIME_OUTSIDE_SESSION` (closed block) | `NO_OPEN_SLOT` (C-3 step 4) |

- **Why it matters:** the plan's own definition (C-3 note) is "`SLOT_FULL` = the chosen time's block is full **while the session has other open blocks**". The previous text ("no open block contains the time") was imprecise the other way, and my correction fixed one overlap but stated block reasons as absolute. Once 3a-2 implements C-6, the frozen description would contradict real results in these cases.
- **Introduced:** in this commit, by the reviewer-supplied wording, not by Astra.
- **Smallest correction (text only, three files: pack, snapshot, guide; brief `.context/astra-fix-slots-3a1-w1.md`):**
  - In `packs/healthcare.json:19` and the `VOICE-TEAM.md:1666` row, replace "A full containing block is SLOT_FULL." with:

    > With slots, when the session containing the time is not bookable or has no open block, its session reason applies (NO_OPEN_SLOT or SESSION_ENDED); only otherwise is a full containing block SLOT_FULL and a closed or ended one TIME_OUTSIDE_SESSION.

  - Then:
    - regenerate the snapshot and the copied guide description at `:625`;
    - repeat the stripped-snapshot proof (only `/tools/1/description` may differ from `6254f3a`);
    - run `make test-fast`, `make schema` with a byte comparison, and `test.sh`.
- **Not required, and withdrawn on reflection:**
  - Leave the `SLOT_FULL` meaning lines at `VOICE-TEAM.md:666, 1671, 1699` and "SLOT_FULL means that time is full" as they are. An earlier draft of this review suggested appending "while its session has an open block" to them.
  - That qualifier would be false for an owner `SLOT_FULL` write rejection, where a race filled the block and the session's other blocks are unknown. "The chosen time's block is full" is true in both cases; only the converse (every full block is SLOT_FULL) was wrong.
  - The `SESSION_ENDED` row at `:1661` ("Supplied end time has passed") covers block ends, which are supplied end times, so leave it too.

### Observations (no change requested)

- **O-1 (accepted):** "the owner's open blocks" in the F-1 text uses "open" in the C-4 sense: bookable, `available > 0` and, today, not ended. That is the natural reading, and the `[]` clause carries the important distinction, so I recommend no change.
- **O-2 (accepted):** in the N-1 text, "…when doctors match: doctors match the request, not yet available" is slightly redundant. It is correct, so no change.
- **O-3 (cosmetic, introduced here):** the reflow left `VOICE-TEAM.md:1691` at 129 characters. The base paragraph already had lines of 102 and 116 characters. No test enforces width, and no action is needed.

## 2. Requirement checklist

| # | Requirement | Result | Evidence |
|---|---|---|---|
| 1 | **F-1:** `[]` = checked, no blocks offered (no capacity, or the session does not permit a request); consistent in the field description, availability description, snapshot and guide | **Pass** | `outcomes.py:47–52` (`_OPEN_SLOTS_DESCRIPTION`); `healthcare.json:6`; snapshot `:11, 201, 556, 1179, 1374`; guide `:101, 268, 300, 927, 942, 1688–1690`. Same meaning everywhere; matches C-1 (`()` unless `APPOINTMENT_REQUEST`), C-3 step 4 and the C-8 handoff |
| 2 | **F-2:** TIME_OUTSIDE_SESSION vs SLOT_FULL under the complete C-6 precedence | **Fail (W-1)** | Step 5 cases are correct. Step 4 session reasons (NO_OPEN_SLOT, SESSION_ENDED) are not reflected, and "A full containing block is SLOT_FULL" is unconditional |
| 3 | **N-1:** department DOCTORS_MATCHED/SLOT_CHECK_REQUIRED conditional on matches | **Pass** | `healthcare.json:6` "…when doctors match:"; the no-match path is the C-7 aggregate (callback, handoff, NOT_AVAILABLE) |
| 4 | Exactly four files | **Pass** | `git diff --name-only 6379670..6254f3a` lists `docs/handover/VOICE-TEAM.md`, `outcomes.py`, `packs/healthcare.json`, `mcp-tools.snapshot.json` |
| 5 | No field, type, default, enum, constraint, policy, formatter, test, auth, config or deploy change; instructions and version unchanged | **Pass** | Word diff: only description strings change. The `outcomes.py` change is confined to the `_OPEN_SLOTS_DESCRIPTION` literal. The test-source diff is empty. `schemaVersion` stays `2026-10-08.1` in both; `instructions` are equal |
| 6 | Independent stripped comparison (description/title removed recursively, defaults kept) | **Pass** | Equal. My SHA-256 of the canonical (`sort_keys`) stripped JSON is `6181894f…653c` for both. Astra's hash differs only because of a different serialisation. Exactly six changed leaf paths, all descriptions: `/tools/{0,1}/description` and `/tools/{0,1}/outputSchema/$defs/{BoardSessionOut,UsualSessionOut}/properties/openSlots/description` |
| 7 | Facts not scripts; wording and instruction-length tests unchanged and passing; guide matches the snapshot; obsolete wording absent | **Pass** (apart from W-1 content) | No imperative wording added. Tests pass inside the 794. `git grep` for "no open block contains", "checked with no open", "Owner's open blocks" and "contains the open blocks" finds nothing in `services/` or `VOICE-TEAM.md` at `6254f3a` |

## 3. Commands run (independently, at `6254f3a`)

| Command | Result |
|---|---|
| `make test-fast` | Exit 0. Ruff "All checks passed!"; **794 passed**, 11 deselected, 2 Authlib deprecation warnings (pre-existing) |
| `make schema > .context/opus-slots-3a1-wording-schema.json` then `cmp … services/mcp/tests/contracts/mcp-tools.snapshot.json` | Exit 0 / exit 0 (**byte-identical**, 63,822 bytes, SHA-256 `e30c8bc8…0ce6`, matching Astra's claim). See the tooling note below |
| `env -u OPS_E2E_BASE_URL ./scripts/test.sh` | **Exit 0**. Results: install (frozen); lint; hermetic **794 passed**; process e2e **2 passed**; package sdist and wheel built; production and stubs images built; external gates not run (no profile loaded); "all suites passed". The log is in `.context/opus-slots-3a1-wording-testsh.log` |
| Stripped snapshot comparison (Python, `git show` of both revisions) | Equal; six description-only leaf differences (above) |
| `git diff --word-diff` over the four files | Only the recorded passages change |

- **Tooling note:** the first `make schema` run went through the local `rtk` output filter. It truncated stdout to 5,038 bytes, so `cmp` reported a difference at line 51. Re-running via `rtk proxy make schema` produced the full 63,822 bytes, byte-identical to the snapshot. This was a local wrapper artefact, not a repository defect.

## 4. Not verified

- External gates (mock/live profiles), live owner APIs, ContextForge and voice behaviour. None are in scope, and there were no live calls.
- Runtime slot behaviour. It is not implemented until 3a-2; the descriptions were checked against the plan, not against executing policy.
- Astra's red/green snapshot-test evidence. I accepted it as reported; for a wording-only change, the independent byte comparison is the meaningful check.

## 5. Answers

- **APPROVED or CHANGES REQUIRED:** **CHANGES REQUIRED** (W-1 only: a text-only follow-up in three of the same files).
- **F-1:** resolved.
- **F-2:** partly resolved. The step 5 distinctions are right, but the step 4 session-reason precedence is missing (W-1).
- **N-1:** resolved.
- **Phase 3a-2:** may begin once the W-1 correction is committed and its stripped-snapshot proof shows only `/tools/1/description` changed. The 3a-2 brief will keep the earlier note that a C-8 handoff session has `open_slots == ()`.
- **Production readiness:** not claimed. The schema `2026-10-08.1` is staged and not deployed; the canary remains on `2026-10-06.1`.
