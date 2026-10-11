# Opus review: fixes for the phase 2a minor findings

Reviewed 8 October 2026.

| | |
|---|---|
| **Commit reviewed** | `f10ec14db061391d5b3e496e3de68c1a464adc81` ("Fix phase 2a review notes"), on `Garry2012/slots-phase-1a-1b` |
| **Base** | `d61867e` |
| **HEAD** | `f10ec14` (not moved) |

**Scope:**
- `git diff d61867e..f10ec14`: `dev/frontdesk_stubs/ops.py`, `tests/test_stubs.py`, `tests/test_contract.py`, `SLOTS-2A-MINOR-FIXES-HANDBACK.md`.
- I read each change in context, together with `write()`, `stub_scenario` and the existing queue tests.

**Not done:** no implementation edits, commits, pushes, merges or deployments; no owner API calls; no credentials; nothing changed in Azure. The untracked review reports and `temp/` are preserved, and this report is uncommitted.

**Verdict: APPROVED. Phase 2b can begin.**

## 1. Findings M-1 to M-4

### M-1: missing `blockMinutes` → **Resolved**

- **Fix:** `ops.py:312–313`. An unscripted plan now takes `state.capabilities["slots"].get("blockMinutes", default_capabilities()["slots"]["blockMinutes"])`. The fallback reuses the one default, so there is no second constant. An explicit value is still honoured: the earlier test with `blockMinutes: 20` (`test_slots_default_is_complete_disabled_and_never_calculated`) still passes unchanged.
- **New test:** `test_stubs.py:562` scripts a contract-valid `{"slots": {"enabled": false}}` (validated against the overlay first). It asserts the complete disabled plan with `blockMinutes 30`, which conforms to `SlotPlan`.
- **Check:** my earlier reproduction (a 500) now returns 200.

### M-2: HTTP `writeOutcomes` validation → **Resolved**

The two scripted-answer shapes and the checks on them (`ops.py:55–66`, validation at `:527–530`):

| Shape | Type | Rules |
|---|---|---|
| Error answer | `ErrorWriteOutcome` (TypedDict) | `status` must be an int in 400–599; `code` must be a contract `ErrorCode`; no extra fields allowed |
| Success answer | `SuccessWriteOutcome` (TypedDict) | `slotTime` must match the HH:MM pattern; no extra fields allowed |

Both are checked by one `TypeAdapter(dict[str, list[Error | Success]])`.

| Requirement | Evidence |
|---|---|
| `"409"` becomes 409 | Pydantic lax int parsing. `test_stubs.py:575` scripts `{"status": "409"}`, gets a real 409 `SLOT_FULL`, then the success item commits `slotTime 11:00`. My probe: a whitespace-padded `" 409 "` and `409.0` coerce to 409. `409.5`, `True` and lower-case codes are rejected. |
| Exactly one of the two shapes | `extra="forbid"` on both TypedDicts makes the union exclusive. The parametrised test at `:588–609` rejects `{}`, a status only, a code only, bad and null status, 200 and 600, a non-contract code, mixed error and success fields, null and invalid `slotTime`, extra fields, and non-object items. My probe: a non-object `writeOutcomes` (`[]`, `"x"`, `null`) is also rejected. |
| No partial state change | Validation runs **before** any scenario mutation (`:527–530` precede the `failNext` loop). The test sends a valid `failNext` entry, a valid path and an invalid path together, then asserts that both `write_outcomes` and `fail_next` are unchanged. |
| The adapter is appropriate and small | One module-level adapter over the existing typed shapes, with no new classes beyond the constraints. Lax coercion of numeric strings is right for a scenario endpoint. |
| In-process assignment still allows deliberately bad fixtures | Assignment bypasses the adapter, so `test_scripted_write_outcomes_are_checked_against_the_owner_contract[NOT_A_CONTRACT_CODE]` still exercises the conformance check. |
| One FIFO per path; the rest unchanged | Validated items are `extend`ed into the same per-path list. `fail_next`, authentication, idempotent replay, the success-commit path (`:369–370`) and `commit_then` are untouched. All earlier queue tests pass. |

### M-3: queue consumption → **Resolved (rule documented and pinned)**

- **Comment:** `ops.py:366` states the rule: one item per write that reaches the owner's decision, including a handler rejection; a replay consumes none. That matches the code: the `pop(0)` sits after the replay and conflict return and before the handler.
- **Test:** `test_stubs.py:547` now asserts the queue is empty after the handler's rejection, and that the **next valid write** returns 201 with no `slotTime`, conforming to `Appointment`.
- **Unchanged behaviour:** a 401 or 403 consumes nothing, and neither does a same-key replay. The 1b test `test_scripted_write_queue_over_http_keeps_auth_replay_fifo_and_read_boundaries` passes unchanged.
- **Sensitivity:** the recorded mutation (`pop(0)` replaced by indexing) makes this test fail (`.context/slots-2a-minors-m3-mutation.txt`). That failure is in a disposable process, not a product failure.

### M-4: `SlotSession` field parity → **Resolved**

- **Test:** `test_contract.py:219–225` adds a `SlotSession` case. It reads the real inline schema, `SlotPlan.properties.sessions.items`, and asserts that model field names equal the contract's `required` and `properties`, and that every field is required.
- **Null label still allowed:** `session: str | None` has no default, so it is still required. `test_slot_session_accepts_adjacent_blocks_and_null_label_without_normalising` passes unchanged.
- **Sensitivity:** the recorded mutation (removing `bookable`) makes the test fail (`m4-mutation.txt`).

## 2. New findings

**Critical:** none. **Important:** none. **Minor:** none.

**Nit (optional, pre-existing): duplicate time pattern.** `SuccessWriteOutcome` uses the stub's own `APPROX_TIME` regex (`ops.py:34`), which duplicates `contract.APPROX_TIME_PATTERN` byte for byte. The stub already imports from `frontdesk_mcp.contract`, so it could reuse the constant and delete the duplicate. The duplicate existed before this commit; the fix only reused it.

**Pre-existing, out of scope:** apart from `writeOutcomes`, the other `stub_scenario` keys (`failNext`, `commitThen`, `slots`, `capabilities`) are still applied without validation. A malformed `failNext` item can 500 after earlier keys were applied. Not introduced here, and not required for 2b. `reject_next_create` stays deferred, as instructed.

## 3. Verification

| Command | Result |
|---|---|
| `make test-fast` | `All checks passed!`; **689 passed, 11 deselected, 2 warnings** (existing Authlib deprecations). |
| `make schema > /tmp/review2af-schema.json`, then `cmp` with `tests/contracts/mcp-tools.snapshot.json` | **Byte-identical.** |
| `env -u OPS_E2E_BASE_URL ./scripts/test.sh` | **Exit 0.** Lint passed; hermetic 689 passed; process e2e **2 passed**; sdist and wheel built; production and development-stub images built (Docker available); "external gates not run: no profile loaded"; "all suites passed". |
| Adapter probe (disposable process) | Coercion and rejection exactly as listed under M-2. |
| Hand-back evidence | **Red:** 17 failed before the fix (M-1 one case, M-2 sixteen); M-3 and M-4 were coverage additions that passed immediately, as expected for already-correct behaviour. **Green:** 21 passed. **Mutations:** M-3 and M-4 each make their test fail. **Full and fast logs:** 689 and 2 passed, matching my runs. **Vulture:** empty. |

**Not run:** the external gates, any live owner call, any deployment.

## 4. For Garima

Astra fixed all four small notes correctly, and I checked the code, not just the tests:
- **Slot setup without a block length:** the fake Manoj server no longer crashes. It falls back to its normal 30 minutes.
- **Checking scripted answers:** the fake server now checks every scripted answer it is sent. `"409"` written as text is accepted as 409. Anything malformed is refused with a clear error, and nothing is half-applied.
- **The "used up" rule:** a scripted answer is used up by a request even if that request is rejected. This is now written in the code and pinned by a test, and the next booking doesn't inherit it.
- **Session fields:** a test now checks our session fields against Manoj's contract.

**All checks pass:** 689 fast tests, the process tests, the package build and both Docker images. The tool schema is unchanged. No new problems.

**Verdict: approved. Phase 2b can begin.**
