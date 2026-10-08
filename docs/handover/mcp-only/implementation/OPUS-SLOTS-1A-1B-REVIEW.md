# Opus review: slots plan phases 1a and 1b

Reviewed 8 October 2026. Branch `Garry2012/slots-phase-1a-1b`, baseline `2e0473a`, HEAD `f69d902`.

Scope: `git diff 2e0473a..f69d902`. I read the affected files in full and traced their callers. No code was changed, nothing was pushed, merged or deployed, and no owner API was called. The only network access was the public contract download I had already made on 8 October, used for byte comparison. This report is left uncommitted.

**Verdict: APPROVED** (after re-review of `07615ce`, section 9). The original verdict was CHANGES REQUIRED for F-1 only; the code was correct from the start.

## 1. Commits

| Commit | Files | Assessment |
|---|---|---|
| `9d7c2f1` docs | `SLOTS-PLAN.md`, `OPUS-OPS-API-040-IMPACT.md`, `evidence/manoj-slots-live-20261007.txt` | Unchanged approved documents. `temp/` not committed. |
| `1be470a` phase 1a | 9 files (two contract YAML files, `contracts/README.md`, root `README.md`, `mcp-only/README.md`, `PLAN.md`, `contract.py`, `test_contract.py`, `test_stubs.py`) | Exactly the permitted nine. |
| `f69d902` phase 1b | 5 files (`VOICE-TEAM.md`, `dev/frontdesk_stubs/ops.py`, `booking.py`, `test_booking.py`, `test_stubs.py`) | Exactly the permitted five. |

## 2. Contract pin (phase 1a)

| Check | Result | Evidence |
|---|---|---|
| Original SHA-256 | **Verified** | `manoj-openapi-20261007.yaml` = `d3e93f45…6c80`, and byte-identical (`cmp`) to my independent download of 8 October. |
| Overlay SHA-256 | **Verified** | `manoj-openapi-20261007.test-overlay.yaml` = `1217015d…ff2f`. |
| Quoting-only, six lines | **Verified** | Both files have 2,509 lines. A line-by-line comparison changes exactly {2327, 2328, 2351, 2370, 2396, 2460}, and each changed line equals the original once `"` is removed. The source's literal `: null` fragments are preserved inside the quotes. |
| `ErrorCode` | **Verified** | `contract.py:30–33` adds only `UNSUPPORTED_CAPABILITY` and `SLOT_FULL`, in the owner's order (`VALIDATION_FAILED … IDEMPOTENCY_CONFLICT, UNSUPPORTED_CAPABILITY, SLOT_FULL, RATE_LIMITED, INTERNAL`). |
| Other literals | **Unchanged and passing** | I compared `AvailabilityStatus`, `AppointmentStatus`, `AttendanceType`, `CallIntent`, `CallOutcome`, `SummaryLanguage`, `MOBILE_PATTERN` and `APPROX_TIME_PATTERN` with 0.4.0. All are identical; the existing equality tests pass untouched. |
| Board example | **Faithful** | `test_contract.py:84–93` reads `examples.facilityBoardMixedDay.value`: date `2026-10-07`, 6 items. Both UNKNOWN entries are asserted exactly (`doc_006` stale, `Afternoon`, times dropped; `doc_014` not stale, no session, no times). LATE is asserted with delay 30, `11:00`–`12:30`. Nothing is weaker than the 0.3.0 assertions. |
| Active references | **Moved** | Root `README.md:22`, `mcp-only/README.md:36`, `PLAN.md:35`, `contracts/README.md`, `test_contract.py`, `test_stubs.py:22`. |
| Remaining `20260930` references | **Historical** | `contracts/README.md:33, 44, 62` (the historical 0.3.0 section, now headed as such); `OPUS-MANAGE-BOOKING-REVIEW.md:5`, `OPUS-OPS-API-040-IMPACT.md:8`, `evidence/live-ops-discovery-20261002.json:5`, `call-summary-evidence/11-removal-audit.txt:65–66` and `CALL-SUMMARY-PLAN.md:11` are dated evidence. |
| `ErrorBody` parsing | **Correct dependency** | `ops_client._rejection` (`:77–82`) validates against `ErrorCode`. Before 1a, an owner `SLOT_FULL` would have failed validation and become `Rejected(status, None)`. 1a is therefore the prerequisite for 1b, as the plan ordered. |

## 3. Booking behaviour (phase 1b)

| Check | Result | Evidence |
|---|---|---|
| Rule location | **Once, in `booking._failure`** | `booking.py:157–159` is one branch beside `NOT_FOUND`, `IDEMPOTENCY_CONFLICT` and `CONFLICT`. Existing branches and the per-action field translation are unchanged. No client change was needed. |
| First-attempt `409 SLOT_FULL`, CREATE and RESCHEDULE | **Verified** | `test_booking.py:865–885` runs through the real service, client and stub. It checks `NOT_AVAILABLE`/`OFFER_OTHER_SESSION_OR_TIME`/`SLOT_FULL`, `sessions == []`, `fields == []`, `appointment is None`, exactly one POST to the write path, and owner appointments unchanged (RESCHEDULE leaves the original untouched, G-2). |
| No inferred alternative | **Verified** | The branch builds no `sessions`, and the tests assert they are empty. |
| Unanswered attempt, then same-key `SLOT_FULL` | **Verified `UNCERTAIN`** | `test_booking.py:888–923`: attempt 1 raises `ReadTimeout`, and attempt 2 gets the scripted 409. The result is `UNCERTAIN`/`SAY_UNCERTAIN_AND_TRANSFER`/`NO_VERIFIED_RESPONSE`. Both attempts carry the same idempotency key and body, and nothing is stored. This path stays in `ops_client.py:307`, unchanged. The test uses the existing `h.ops.http._transport` pattern (`test_booking.py:787, 818`). |
| `UNSUPPORTED_CAPABILITY` | **Generic `REJECTED`** | `test_booking.py:926–933`: `REJECTED`/`ASK_TO_CORRECT`/`UNSUPPORTED_CAPABILITY`, no fields, no write. |
| Owner text | **Never surfaced** | `_rejection` keeps only status, code and fields. Every new test asserts the scripted message is absent from the result JSON and `caplog`. |

## 4. Stub design

| Check | Result | Evidence |
|---|---|---|
| One queue, in-process and over HTTP | **Verified** | `OpsStubState.write_outcomes: dict[path, list[(status, ErrorCode)]]` (`ops.py:58`). It is consumed in `write()` (`:303–305`) and extended by `stub_scenario` `writeOutcomes` (`:463–464`). |
| Order | **Verified** | It runs after authentication (401), scope (403), `fail_next`, JSON parsing, and idempotency replay and conflict checks (`ops.py:285–302`), then before the handler. `test_stubs.py:359–383` proves 401, 403, replay, conflict and `GET` leave the queue untouched. |
| FIFO, path isolation, reset | **Verified** | FIFO: `test_stubs.py:378–381` (`SLOT_FULL` then `UNSUPPORTED_CAPABILITY`). Exact-path isolation and `fail_next` precedence: `:386–396`. Reset: `ops.py:94`, `test_stubs.py:398–400`. |
| Contract conformance | **Verified** | `test_stubs.py:341–353` validates scripted errors against the overlay's `Error` schema. An invalid code (`NOT_A_CONTRACT_CODE`) raises `jsonschema.ValidationError`, so the conformance test detects it. |
| `fail_next` | **Unchanged** | Same tuple shape and callers. No second infrastructure-failure mechanism, and no capacity logic. |
| Rejections are not stored for replay | **Consistent** | Only `status < 300` is stored (`ops.py:308–309`), as before. A later request with the same key is handled normally (`test_stubs.py:382–383`). |

## 5. Quality and scope

- **No later-phase work:** no slot models, transport methods, reader or policy changes, schema change or version bump. `make schema` is byte-identical to `tests/contracts/mcp-tools.snapshot.json`.
- **VOICE-TEAM** (`:629–634`, `:937`) no longer promises alternatives: "offer only those returned; if none are returned … check availability again". It also states that the owner's rejection proves nothing about other times, and that a rejection after an unanswered attempt stays `UNCERTAIN`.
- **Code hygiene:** no dead code, duplicated rule or weakened test. The five-to-six overlay rename and the board-example update keep or strengthen their assertions.
- **The tests are behavioural:** each new booking test fails without the branch. The recorded red shows `REJECTED … SLOT_FULL` before the mapping and `NOTED` before the fixture existed. Each test asserts owner state and request counts, not just the returned envelope.

## 6. Findings

### F-1 — Minor, **required**: `docs/handover/mcp-only/PLAN.md:35` pairs the 0.4.0 pin with 0.3.0 facts

- **Scenario:** a reviewer reads the target plan's "What the published contract changes" paragraph. It now links `manoj-openapi-20261007.yaml` with SHA `d3e93f45…`, but still says the snapshot "identifies itself as `0.3.0-draft`", "has 20 paths and 23 operations", and (`:37`) "No slot endpoint was added". All three are false for the linked file: it is `0.4.0-draft`, has 33 paths, and contains `/capabilities` and `/availability/{doctorId}/slots`.
- **Impact:** documentation only, with no runtime effect. But it is the active target plan, and it now contradicts the pinned contract and `contracts/README.md`.
- **Cause:** my build prompt asked for "path and SHA only" on this line. Astra followed it exactly. The instruction was wrong, not the implementation.
- **Evidence:** `sed -n 35,37p docs/handover/mcp-only/PLAN.md`; parsing the overlay gives `openapi 3.0.3`, `0.4.0-draft`, 33 paths.
- **Smallest coherent correction (one docs commit, one file):**
  1. Restore this paragraph's link and SHA to the 0.3.0 snapshot it describes (`manoj-openapi-20260930.yaml`, `b8f28271…`).
  2. Add one sentence before it: "Current pin: 0.4.0, `contracts/manoj-openapi-20261007.yaml`, SHA-256 `d3e93f45…6c80` (see `contracts/README.md`); the paragraph below describes the 30 September 0.3.0 snapshot."

  Phase 5 rewrites the rest of `PLAN.md` as planned.

### N-1 — Nit, optional: `tests/test_contract.py:29` docstring

- **Issue:** it says "the original's six defects do not [parse]". In fact the original parses (`yaml.safe_load` succeeds); each defect splits a description into a bogus key, which `test_the_original_defect_is_real_and_the_overlay_fixes_it` checks correctly.
- **Correction:** say "the original's six defects parse into bogus keys". This wording predates the branch (the "five" version had it too).

### N-2 — Later phase (2a), not a defect: shape and position of the scripted write outcome

- **Today:** the queue is error-only, `(status, ErrorCode)`, and returns before the handler.
- **What 2a needs:** phase 2a adds a moved `slotTime`, which is a *successful* write that must still commit through the handler and be stored for replay. 2a must therefore extend this same queue's item type to error or success, and apply success items after the handler commits. It must not add a parallel queue.
- **Side effect today:** a scripted error is returned even for a body the owner would reject earlier (missing fields, unknown appointment). No current test relies on that, so it does not mask anything. 2a can decide whether to move error items after body validation.
- **Action:** record this in the 2a prompt. Nothing is needed now; the instruction was to add nothing 2a needs.

### N-3 — Nit, optional: duplicated RESCHEDULE setup

`test_booking.py:868–876` and `:895–903` repeat the same create-then-reschedule setup. A small local helper would remove it. It is not required.

## 7. Independent verification

| Command | Result |
|---|---|
| `make test-fast` | `All checks passed!` (ruff) and **609 passed, 11 deselected, 2 warnings** (the existing Authlib deprecations). |
| `make schema` against the snapshot | **Byte-identical** (`cmp`). |
| `env -u OPS_E2E_BASE_URL ./scripts/test.sh` | **Exit 0.** Lint passed; hermetic suites 609 passed; process e2e **2 passed**; package build built the sdist and wheel; the production and development-stub image builds ran with Docker available (the script prints "skipped" only without Docker) and completed; "external gates not run: no profile loaded"; "all suites passed". |
| TDD evidence | `slots-1a-red.txt`: the `ErrorCode` equality failed before the literal change. `slots-1b-fixture-red.txt`: `NOTED` before the scripted queue existed. `slots-1b-mapping-red.txt`: `REJECTED … SLOT_FULL` before the mapping. `slots-1b-green.txt`: 10 passed. All consistent with test-first work. |

Astra's claims (609 hermetic tests, 2 process tests, package and both image builds) are confirmed.

**Not run:** the external gates (`test_external*`), by instruction, and any live owner call or deployment.

## 8. For Garima

Astra's code for both phases is correct and clean.
- **Manoj's new contract is pinned exactly.** The file matches the one I downloaded myself, byte for byte, and only the six known broken lines are fixed, in the test copy.
- **"Slot full" is handled properly.** When Manoj says a slot is full, the caller is told "not available, offer another time". No alternatives are invented and nothing is booked. If our first attempt got no answer, the result stays "uncertain".
- **All tests pass,** including the full build. The tool schema is unchanged.

One thing must be fixed before merging. A paragraph in `PLAN.md` now points to the new contract but still describes the old one ("0.3.0", "no slot endpoint"). That came from my prompt, which told Astra to change only the file name and fingerprint. It's a one-paragraph documentation fix. Astra fixed it in `07615ce`, which I checked (section 9), so this is now approved.

## 9. Re-review of `07615ce` (F-1 fix)

- **Scope:** `07615ce` changes one file, `docs/handover/mcp-only/PLAN.md` (+3/−1).
- **Fix:** line 35 now names the current pin (0.4.0, `manoj-openapi-20261007.yaml`, `d3e93f45…6c80`, with a link to `contracts/README.md`). It states that the paragraph which follows describes the historical 30 September 0.3.0 snapshot. That paragraph links `manoj-openapi-20260930.yaml` with its own SHA (`b8f28271…`, re-verified with `shasum`), and its "0.3.0-draft, 20 paths" and "no slot endpoint" statements are true again for the file they describe.
- **Checks:** `uv run pytest tests/test_contract.py`: 12 passed. No code changed, so the earlier full verification (section 7) still holds.
- **Deferred:** N-1 and N-3 (optional) and N-2 (phase 2a) stay as recorded.

**F-1 resolved. Final verdict: APPROVED.**
