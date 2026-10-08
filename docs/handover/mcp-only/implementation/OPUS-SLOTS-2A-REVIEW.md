# Opus review: slots plan phase 2a (typed transport and scripted fixtures)

Reviewed 8 October 2026.

| | |
|---|---|
| **Commit reviewed** | `d61867ec05e0f989c72f903a4a73791108ea366e`, on `Garry2012/slots-phase-1a-1b` |
| **Base** | `07615ce` |
| **HEAD** | still `d61867e` (no later commits) |
| **Workspace** | untracked `OPUS-SLOTS-1A-1B-REVIEW.md` and `temp/`, both preserved |

**Scope:**
- `git diff 07615ce..d61867e`: 7 files, +600/−23.
- I read all seven changed files and the relevant callers in full.

**Not done:** no code changes, commits, pushes, merges or deployments; no owner API calls; no credentials loaded; nothing changed in Azure. This report is uncommitted.

**Verdict: APPROVED WITH MINOR NOTES. Phase 2b can begin.**
- The phase is correct, in scope and well tested.
- The four minor notes are about fixture robustness and one test gap.
- None of them affects production code or any later phase's design.

## 1. Findings

### Critical

None.

### Important

None.

### Minor

**M-1: the stub crashes on a contract-valid capabilities object without `blockMinutes`** (`dev/frontdesk_stubs/ops.py:306`)
- **Trigger:**
  1. Script `{"capabilities": {"availability": {}, "slots": {"enabled": false}, "appointments": {}}}`. The contract makes `slots.blockMinutes` optional, and our own `SlotCapabilities` model agrees (`contract.py:156`).
  2. Request an unscripted `GET /availability/doc_garima/slots`.
- **Result:** 500, from a `KeyError` on `state.capabilities["slots"]["blockMinutes"]`. Reproduced in a disposable process.
- **Impact:** test fixtures only, not production. A future test scripting a minimal capability object gets a confusing 500 instead of a disabled plan.
- **Correction:** for the unscripted plan, take `blockMinutes` from the capabilities fixture when present, otherwise from the stub default (`default_capabilities()["slots"]["blockMinutes"]`). One line; no new state.

**M-2: HTTP `writeOutcomes` items are no longer normalised** (`ops.py:522`)
- **Change:** phase 1b converted `int(item["status"])`. Phase 2a now `extend`s the raw JSON items.
- **Trigger:**
  - `{"writeOutcomes": {"/appointments": [{"status": "409", "code": "SLOT_FULL"}]}}` makes the next POST return 500 (reproduced).
  - An item with neither `code` nor `slotTime` is consumed silently, as if nothing had been scripted.
- **Impact:** fixture input handling only, through the scenario endpoint used by process tests and demos.
- **Correction:** convert each HTTP item into exactly one of the two typed shapes, `{status:int, code}` or `{slotTime}`, and reject anything else with a 400 from `/__stub/scenario`. Keep the in-process typed path as is.

**M-3: a success item is consumed by a request the handler rejects, and nothing documents or asserts that** (`ops.py:359`, `tests/test_stubs.py:547`)
- **Behaviour:** `outcome = scripted.pop(0)` runs before the handler. A scripted `{slotTime}` is therefore used up by a request that then fails body validation (400). The next valid write gets no `slotTime`. Probe: after the rejected request, the queue is `{'/appointments': []}`.
- **Assessment:** it is a reasonable fixture rule ("one scripted item per write that reaches the owner's decision point"). But the brief only specified the success-path behaviour, and `test_success_fixture_does_not_turn_a_handler_rejection_into_success` checks only that the rejection carries no `slotTime`.
- **Impact:** a later test author could write "invalid then valid" and wrongly expect the moved `slotTime` on the second request.
- **Correction:** pin the chosen rule. Either assert that the queue is consumed, plus a one-line comment beside `pop(0)`, or pop success items only after a successful commit. I recommend asserting the current rule, because it treats both item shapes the same way.

**M-4: no field-parity test for the inline session schema** (`tests/test_contract.py:220`)
- **Gap:** `test_slot_model_fields_match_the_contract_required_properties` covers `SlotPlan` and `SlotBlock`. `SlotSession` is defined inline in the contract (`SlotPlan.properties.sessions.items`), so it is not compared.
- **Impact:** if the owner renamed or added a required session field, only the example-based tests would notice, and only if an example changed.
- **Correction:** add a third case reading `SlotPlan.properties.sessions.items`. `session` is nullable in our model on purpose (G-11), so assert names and required-ness, not types.

### Pre-existing (not introduced by 2a): `reject_next_create` (`ops.py:83, 398–399`)

- **Origin:** a scripted 400 `VALIDATION_FAILED` with field details, CREATE only. It dates from `e9c6bc50` (1 October) and is used by `test_booking.py:211, 760`.
- **Overlap:** it now overlaps the scripted write-outcome queue's error items. The queue has no `details` field, which is the only reason the old field is still needed. I missed this overlap in the 1a/1b review.
- **Optional later cleanup:** add optional `details` to error items, migrate the two callers and delete `reject_next_create`. Not a 2a defect and not required for 2b.

## 2. Requirement coverage

### 2.1 Models (`contract.py:115–161, 176`)

| Requirement | Result |
|---|---|
| `SlotBlock`, `SlotSession`, `SlotPlan`, `Capabilities` as briefed | **Met.** `Capabilities` models only `slots` (`SlotCapabilities`: `enabled` required, `blockMinutes` optional). `availability`/`appointments` are kept through `extra="allow"`: `model_extra` equals the raw sections in both capability examples. |
| Existing ApproxTime pattern reused | **Met.** `Field(pattern=APPROX_TIME_PATTERN)` on `start`, `end` and `slotTime`. The pattern guarantees zero-padded `HH:MM`, so direct string comparison is chronological. No second parser. |
| `start < end`; non-negative counts; `available ≤ capacity` | **Met.** `ge=0` on the three counts; `_consistent` at `:124`. |
| Ordered, non-overlapping blocks; adjacency accepted | **Met.** `_ordered` at `:139` rejects `previous.end > following.start`, so reversed, duplicate and overlapping blocks are all rejected. `end == next.start` passes (tested). |
| No `booked + available == capacity` rule | **Met.** Absent. Both live captures (5/0/0 closed blocks) pass. |
| Empty/null labels accepted and preserved | **Met.** `session: str \| None` is required but nullable. `""`, `None` and `"  Morning  "` round-trip unchanged (tested). |
| `Appointment.slotTime` optional and validated | **Met.** Present, absent and `null` accepted; `9:00`, `24:00` and `11:60` rejected. |
| Contract examples and live captures | **Met, strongly.** All four slot examples and both capability examples are tested with concrete per-block values **and** full round-trip equality (`model_dump(mode="json") == raw`). Both inline live captures match the evidence file exactly: I extracted the JSON from `manoj-slots-live-20261007.txt` and compared it, `True`/`True`. |
| Plan-level checks deferred to 2b | **Met.** No doctor/date match, label uniqueness or cross-session overlap in the models. |

### 2.2 Client (`ops_client.py:371–377`)

| Requirement | Result |
|---|---|
| Existing transport, auth, deadlines, parsing | **Met.** Both methods are one-line `_read` + `_parse`, following `get_doctor`. |
| Invalid id fails before any HTTP, including the token | **Met.** `_path_id` runs while the path is built, before `_read`. The test asserts `up.requests == []`, token request included. |
| Date passed through unchanged | **Met.** Tested with `today` and an ISO date. |
| Error classes | **Met.** 400/404 → `Rejected` (status and code kept, owner text not exposed); 503/timeout → `Unavailable` (`UPSTREAM`/`TIMEOUT`); missing required facts and every invariant violation → `Malformed`. One request each, so no new retry. |
| No startup process, no production caller | **Met.** `grep` finds `get_capabilities`/`get_slots` only at their definitions in `src/` and `dev/`; callers exist only in tests. Vulture output is empty. |

### 2.3 Stub (`dev/frontdesk_stubs/ops.py`)

| Requirement | Result |
|---|---|
| Capabilities default complete, disabled, resettable | **Met.** `default_capabilities()`; it conforms to the overlay schema; scriptable in-process and over HTTP; `reset()` restores it (tested). |
| Slot plans scripted by doctor and date; unscripted plans complete and disabled | **Met.** `set_slots`/scenario `slots`. The default plan has the requested doctor, the resolved date, `enabled false`, `blockMinutes` and `sessions []`. Even with enabled capabilities, nothing is synthesised (tested). See M-1 for the missing-`blockMinutes` crash. |
| "today" uses the facility clock and shared date resolution | **Met.** `requested_date` was extracted from `/availability` and reused, so there is one resolver. A test at UTC 20:30 gives the India date 2 October. |
| Auth, failure injection, malformed responses, 400/404 | **Met.** 401 without or with a forged token; read scope suffices; `fail_next` and `malformed_next` apply; unknown doctor → 404; bad date → 400. All conform to the overlay. |
| No computation | **Met.** No schedule, capacity or `bookable` derivation. |
| One FIFO per exact path, error `{status, code}` and success `{slotTime}` | **Met.** `ErrorWriteOutcome`/`SuccessWriteOutcome` TypedDicts in the one existing queue. |
| Success runs the handler; `slotTime` reaches the stored appointment, the response and replay | **Met.** `ops.py:363–364` sets it only when `status < 300`, before idempotency storage and before `commit_then`. Tested for CREATE and RESCHEDULE, in-process and over HTTP, including commit-then-504 and a same-key replay returning the stored appointment with `slotTime`. See M-3 on consumption. |
| Error ordering, auth, path isolation, reset, `commit_then` | **Met.** The error position is unchanged from 1b. The mixed FIFO (400 → success → 409) is tested end to end. |
| `fail_next` unchanged | **Met.** Same tuple and position. |
| All old tuple callers migrated; no shim or parallel queue | **Met.** `grep` finds no tuple-shaped `write_outcomes`; the three `test_booking.py` and two `test_stubs.py` callers were updated mechanically, assertions unchanged. |
| Ordinary unscripted writes unchanged | **Met.** No `slotTime` on default writes (asserted in the RESCHEDULE setup); all 609 earlier tests still pass. |

### 2.4 Scope

- **Only phase 2a was implemented.** No changes to reader, policy, services, outcomes, pack text, prompt, auth configuration or VOICE-TEAM.
- **Public schema unchanged.** `make schema` is byte-identical to the snapshot.
- **Test changes:** existing booking-test assertions are unchanged; only the fixture item shape changed.
- **Cosmetic:** the trailing blank line at the end of `contract.py` was removed.

## 3. Verification

| Command | Result |
|---|---|
| `make test-fast` | `All checks passed!` (ruff); **671 passed, 11 deselected, 2 warnings** (existing Authlib deprecations). |
| `make schema > /tmp/review2a-schema.json`, then `cmp` with `tests/contracts/mcp-tools.snapshot.json` | **Byte-identical.** |
| `env -u OPS_E2E_BASE_URL ./scripts/test.sh` | **Exit 0.** Lint passed; hermetic 671 passed; process e2e **2 passed**; sdist and wheel built; production and development-stub images built (Docker available; the script prints "skipped" only without it); "external gates not run: no profile loaded"; "all suites passed". |
| `grep` for `get_capabilities\|get_slots` in `src/`, `dev/` | Definitions only (`ops_client.py:371, 374`). |
| `grep` for tuple-shaped `write_outcomes` | None. |
| Live-capture equality against the evidence file | Both `True`. |
| Disposable stub probes (no repository change) | M-1: 500. M-2: 500. M-3: queue empty after the handler rejection. |
| TDD evidence | `slots-2a-model-red.txt`: 27 failed before the models, `model-green` 39 passed. `client-red`: 20 failed, `client-green` 20 passed. `stub-red`: 24 failed, including the three migrated booking tests, `stub-green` 25 passed. `slots-2a-fast.txt`/`full.txt` match my runs. `slots-2a-vulture.txt` is empty. All consistent with test-first work. |

Astra's numbers are confirmed: 671 hermetic, 2 process, package and both images.

**Not run:**
- the external gates (`test_external*`), as instructed;
- any live owner call;
- any deployment or Azure check.

## 4. Deferred and out of scope (correctly not in 2a)

- **Phase 2b:** reader-level plan checks (doctor/date match, unique normalised labels, cross-session overlap → `Malformed` at stage `slots`); `DoctorFacts.slots`; the selected-doctor `/slots` read in the parallel step; removing the AVAILABILITY on-call early return; the B-6 detail helper.
- **Phase 4a:** the department `/capabilities` read with its AVAILABILITY guard.
- **Phases 3a-1/3a-2/3b:** all policy, output and schema work.
- **Optional cleanup:** the pre-existing `reject_next_create` overlap (above).

## 5. For Garima

Phase 2a is good. Astra added three things:
- **Data types** for Manoj's slot settings and slot plans. Bad data, such as overlapping blocks or more free seats than capacity, is rejected.
- **Two read methods** for Manoj's API. They are not used by the live tools yet; that is phase 2b.
- **Fake-Manoj test answers** for slot settings and slot plans. The scripted "write answers" list can now also return a successful booking at a moved time.

**Checks:**
- Manoj's own examples and **the two real responses we captured from his live system** fit the new types exactly. I compared them against the saved evidence file.
- All tests pass: 671 fast tests, the process tests, the package build and both Docker images.
- The tools' schema is unchanged.
- I found no production problems.

**Four small notes.** All are about the fake test server or one missing test, not the real code:
- Two unusual fake-server inputs cause a crash instead of a clear error.
- One fixture rule should be stated and pinned by a test.
- One schema-matching test is missing.

Astra can fix these in a small follow-up commit or as part of 2b. **Phase 2b can start.**
