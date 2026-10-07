# Slots plan revision 4: delta pre-flight

**Verdict: needs revision 5 — resolve R4-B1, R4-B2 and R4-B3 below; incorporate the bounded clarifications R4-S1–S4 before building.**

Reviewed 8 October 2026 against HEAD `32e8ea9cb141397b41c2fe184f215c5d87bc0fa7`. The implementation remains the PR16 code reviewed previously. This is a report-only review: no code, tests, other documents, owner APIs, Azure resources or deployment were changed. No external network call was made for this pass; the test suite uses local fixtures and transports.

## Scope and fixed decisions

The only plan is `SLOTS-PLAN.md` revision 4. D-1 through D-5 are accepted, not reopened: publish the final schema once in 3a; require time for slot-enabled writes and validate optional session without forwarding it; compare actual slot time with the containing block start; offer open one-day sessions; use per-doctor slot reads and department-only cached capabilities, without a capability lifecycle.

Inputs under `docs/handover/mcp-only/implementation/`, left unchanged:

| Input | SHA-256 |
|---|---|
| `SLOTS-PLAN.md` | `674d910740d71fd028170f53765c5dffe0b3ae820e1804ee292e64d584c85cba` |
| `OPUS-OPS-API-040-IMPACT.md` | `b27d6217be28167d89f8228a6ee5d05d9480fc166565e707bc4ee67aa19a6828` |
| `evidence/manoj-slots-live-20261007.txt` | `6be6de05a346adccdd23a3f00e4b8f72cff2b66219d785169e7ecc2ee12ab4bd` |

Read the impact document's facts and decisions; its superseded sections 4–6 are not implementation authority. Sol's separate original review was not found in the supplied files or repository search. The Sol rows below assess **the four findings as transcribed in revision 4 section 13**, including #4's two parts; they do not claim verification of an unavailable original review. The previously downloaded public contract was inspected locally where relevant; its hash remains the baseline evidence, not a new live observation.

Source abbreviations: `src/` means `services/mcp/src/frontdesk_mcp/`; `tests/` means `services/mcp/tests/`; `plan:` means revision 4 line numbers. “Resolved” below means resolved **in the proposed design**, not implemented or runtime-verified.

## 1. Finding-by-finding result

| Earlier finding | Status | Evidence and disposition |
|---|---|---|
| B-1 capability lifetime/startup | **Resolved** | Plan:83,92–100 removes capability startup entirely. `src/server.py:182` and `src/tools.py:61` contain only the existing client/token lifecycle; no capability task exists to remove. Shared cache already exists (`tools.py:53–57`, `cache.py:14–38`). No Services/server lifecycle or harness request filtering is required. Clarify WORKING_HOURS and cache concurrency as R4-S2. |
| B-2 evidence and precedence | **Partly resolved** | Plan:108–147 distinguishes disabled, unread, missing and matched evidence, and carries stale/clock facts. However C-2's cancellation precedence contradicts the unconditional UNKNOWN claim; see R4-B1. The C-6 mixed-scope consequences remain R4-B2. |
| B-3 combination and future selection | **Partly resolved** | Plan:198–208 names all match consumers, including `_combine`, reader counts and rank. But replacing the APPOINTMENT_REQUEST predicate in `src/availability_policy.py:243–249` does not preserve future UNKNOWN/CANCELLED refusals; the named-scope exception in `_combine:193–199` must also remain. See R4-B2/B3. |
| B-4 booking order/alternatives | **Partly resolved** | Plan:175–194 adds an explicit matrix and keeps alternatives as SessionDecision objects, compatible with `src/booking.py:247,255`. Steps 3/8/10 still disagree for full blocks, and steps 5–7 can lose unresolved session facts. See R4-B2. |
| B-5 clock/provenance/output | **Partly resolved** | Policy-computed `open_slots` removes clock logic from `src/outcomes.py:60`. Plan:167,236 supplies a one-day representation and owner bounds. Future selection still needs R4-B3; unread versus empty projection needs R4-S3. No new clock in the formatter is necessary. |
| B-6 green commits/schema phasing | **Resolved** | D-1 and plan:294–301 publish all enums, output fields, pack text, snapshot and VOICE rows in 3a. This fits `tests/test_server.py:134,409,442`; every listed commit is ≤10 files. Explicit defaults and complete descriptions are needed in 3a, as R4-S4 explains. There is no remaining need for a second version bump. |
| S-1 complete contract migration | **Resolved** | Plan:61–66 includes root README, the second overlay consumer `tests/test_stubs.py:22`, and the moved board example in `tests/test_contract.py:84`. No new defect found in this delta; the six-line overlay was established by the first pre-flight. |
| S-2 failures/data integrity | **Partly resolved** | Plan:71 and :97 add consumer checks and doctor/date validation. Both real captures pass the new numeric/order checks. New-stage failures are specified, but preserving existing profile/directory rejection semantics and propagating duplicate-join failures needs R4-S1; cross-session ambiguity remains R4-B2/B3. |
| S-3 Write propagation/moved time/replay | **Resolved** | Plan:214–229 names the truthy-Write problem, all gate callers, `_written`, missing time and LIST/CANCEL cases. `src/booking.py:214,281,304–328` supports this minimal change. Replay after capacity changes is explicitly documented, without local state. Missing owner slotTime intentionally yields slotMoved=false even when expectedTime is used for display. |
| S-4 external tests/bench/rollout | **Resolved** | Plan:260–268,298 includes external journeys, outcome-aware benchmarks, process journeys and schema refresh, with no unapproved live execution. It retains the latency qualification; parallel reads are not a measured success guarantee. |
| N-1 facts-based signature | **Resolved** | Plan:129 gives the session rule a facts record including stale/evidence/date/clock information. That fits `src/availability_policy.py:70–99,207–217` without behavioural flag parameters. |
| N-2 fixtures, not engine | **Resolved** | Plan:73–78 scripts reads and write outcomes; existing `dev/frontdesk_stubs/ops.py:45,136,281,453` provides the pattern. Disabled fallback must be a complete SlotPlan, including requested doctor/date/blockMinutes, not just the two-field shorthand. |
| N-3 single-doctor unread invariant | **Resolved** | Plan:208 chooses COULD_NOT_CHECK/SAY_COULD_NOT_CHECK/SLOTS_UNAVAILABLE, removing the unsafe AVAILABILITY alternative. Add it to `src/availability.py:141–147`; no new result schema is needed. |
| N-4 unnecessary capability framework | **Resolved** | D-5 reuses `src/cache.py:14` and the `src/schedule_reader.py:40–45` get-or-read pattern. No second cache, refresh worker or startup process is planned. |
| Sol #1 lifecycle/request assertions | **Resolved** | Same evidence as B-1. Three exact assertions can remain unchanged; their accurate identities are listed below. |
| Sol #2 schema phasing | **Resolved** | Same evidence as B-6. One complete publication is feasible with defaults fixed in 3a. |
| Sol #3 session selection | **Partly resolved** | Optional, non-forwarded session and the time-match rule are explicit (plan:25,181,216). `_OWNER_FIELDS` already excludes session (`src/booking.py:61–77`). Scope, multiple matches and refusal priority still need R4-B2. |
| Sol #4 moved-time meaning / unsafe fallback choice | **Resolved** | Plan:219–224 compares owner slotTime to block start, not the caller's interior time; 10:45→10:30 is false. Plan:208 chooses a failure for unread single-doctor facts. These fit `_appointment_out:86`, `_written:324` and `_single:141`. |

### Request assertions and D-5: corrected evidence

The three whole-list equalities are:

| Assertion | Actual case | Why it can stay unchanged |
|---|---|---|
| `tests/test_availability.py:260`, `ops_paths() == []` | Missing required availability date | `AvailabilityService.get:60–63` returns before retrieval. |
| `tests/test_availability.py:523`, `ops_paths() == ["/doctors"]` | **On-call doctor found by name**, not an ambiguous name | `ScheduleReader.doctor:73–74` returns on the supplied ON_CALL summary before any slot/board/profile read. |
| `tests/test_booking.py:691`, `ops_paths() == ["/appointments"]` | Malformed doctor ID from the appointment lookup | Profile and new slot methods must both use `_path_id` before HTTP (`src/ops_client.py:64–67,367–368`). Keep deterministic profile-first error selection and the existing PROFILE_UNAVAILABLE detail. |

**Correction to my first report:** I incorrectly labelled line 523 as an ambiguous-name case. Revision 4 repeats that label. The equality count was correct; the case description was not. Preserve the on-call shortcut. Ambiguous-name tests exist separately at `tests/test_availability.py:175–192`.

No broad request-log rewrite is justified. `tests/harness.py:54–57,77–80` should continue recording all owner requests. Successful selected-doctor availability/booking paths gain slots; department availability gains capabilities; local validation, ambiguous selection, named ON_CALL shortcut and WORKING_HOURS do not. ID-only ON_CALL lookup still performs concurrent reads before the profile reveals attendance type, as revision 4 acknowledges. Mock HTTP responders such as `tests/test_schedule_reader.py:36–60` must explicitly serve capabilities when that department path is wired: the current fallback tries to parse the final path component as an integer.

## 2. Remaining blocking findings

### R4-B1 — cancellation precedence and the absolute UNKNOWN promise conflict

C-2 at plan:125 chooses CANCELLED over UNKNOWN in either direction. C-3 then returns NOT_AVAILABLE/CANCELLED. Section 9 simultaneously promises UNKNOWN will **never** become NOT_AVAILABLE. Literal evaluation of the written rules gives:

```text
Literal r4 C-2/C-3: board UNKNOWN + slots CANCELLED -> NOT_AVAILABLE/CANCELLED
Literal r4 C-2/C-3: board CANCELLED + slots UNKNOWN -> NOT_AVAILABLE/CANCELLED
Literal r4 C-2/C-3: board UNKNOWN + slots IN -> CALLBACK_REQUIRED/BOARD_UNKNOWN
```

Cancellation not becoming stale is supported by the previously downloaded 0.4.0 contract (line 416). That fact does not by itself specify reconciliation of two racing responses or create an exception to the product's absolute UNKNOWN wording. The proposed priority never authorizes a write from these conflicts, but it changes what the caller is told and whether a callback summary is requested.

**Required revision:** make the stated invariant, reconciliation rule and tests agree. Either explicitly record the cancellation-conflict exception to UNKNOWN callback, or preserve the unconditional UNKNOWN rule. D-1–D-5 do not decide this conflict, so this is not reopening those decisions. Test both response orderings, with stale and non-stale UNKNOWN; never rely on which HTTP read finishes first.

### R4-B2 — the booking matrix still loses scope and disagrees on FULL

The matrix cannot yet replace `decide_booking` coherently. These are consequences of the written rows, not claims that unimplemented slot code has run:

1. **FULL differs depending on another session.** A single full session is a whole-scope NO_OPEN_SLOT, so step 3 refines it to SLOT_FULL. Add an unrelated open session: `_combine` yields a match, step 3 is skipped, and step 8 returns the selected full session's NO_OPEN_SLOT before step 10 can return SLOT_FULL. This violates the stated full-block behaviour.
2. **Step 3 can override the session flag.** Session `bookable=false` produces NO_OPEN_SLOT. An inconsistent retained block with `bookable=true, available=0` then qualifies for step 3's FULL refinement, even though C-3 says that session's blocks must not be inspected or offered. Scope/session matching also has not yet run at step 3.
3. **An unlabelled UNKNOWN can disappear.** Current `decide_booking:294–306` retains unlabelled unresolved rows beside the time-selected row and combines them. With no selected session, a day containing a bookable Morning plus unlabelled UNKNOWN is initially APPOINTMENT_REQUEST, but booking returns callback. The new matrix checks only the block's session at step 7; if the warning row has no blocks, a Morning OPEN block can reach step 11. Giving a time must not discard an unscopable warning.
4. **No block does not necessarily mean outside a known session.** A mixed day can have a known Morning block and an UNKNOWN afternoon with no block evidence. Steps 5/6 return TIME_OUTSIDE_SESSION before the callback rule at step 7. The current logic preserves unresolved/unbounded rows (`:298–306`); absence of capacity evidence must not turn them into verified unavailability.
5. **The time-selected session is not always unique.** A-2 rejects overlap within each session, not between differently labelled sessions. `block_at(session_slots,t)` is a per-session lookup. The matrix does not specify how to obtain “the” session when two contain the time, or how the optional session resolves that ambiguity. Do not add a first-match guess. Normalize whitespace before deciding whether a session argument is non-empty: current `bool(session)` and `_today:219–225` distinguish `"   "` from no selection.

Local diagnostic evidence:

```text
Current mixed open + unlabelled UNKNOWN with time: APPOINTMENT_REQUEST -> Callback/BOARD_UNKNOWN
Only full session -> step 3: SLOT_FULL
Same full session, other session open -> step 8: NO_OPEN_SLOT
Session flag false, inconsistent FULL block -> step 3: SLOT_FULL
```

The first line executes HEAD policy. The remaining lines execute only the literal matrix branches in a disposable Python process; they are design counterexamples, not integration-test output.

**Required revision:** retain all relevant refusal evidence while selecting scope; explicitly preserve unlabelled UNKNOWN and named-scope callback priority; make FULL refinement consistent at whole-scope and selected-session levels and conditional on a usable session; define non-unique/absent block handling. Reuse one block lookup and one scope/combination rule. Keep CANCELLED, SESSION_ENDED and NOT_USUAL_DAY whole-scope precedence and existing legacy tests unchanged. These corrections need no additional public enum beyond the planned surface if existing failure/clarification envelopes are used deliberately.

### R4-B3 — future selection still filters away reasons before aggregation

C-5 correctly adds the weekday join and no-usual-schedule exception. But C-7 says to use `is_match` in the current alternatives/selection code. At HEAD, `_future:243–250` selects **only alternatives**, and no selection means NOT_USUAL_DAY or SESSION_NOT_USUAL. If a joined session's decision is UNKNOWN callback, CANCELLED, SESSION_ENDED or NO_OPEN_SLOT, it is not a match and its reason can be lost. This is more than replacing the predicate.

A local diagnostic temporarily substituted the result of `_usual` in memory, leaving the existing `_future` control flow untouched:

```text
Current future selection after injected session CALLBACK_REQUIRED/BOARD_UNKNOWN: NOT_AVAILABLE/NOT_USUAL_DAY
Current future selection after injected session NOT_AVAILABLE/CANCELLED: NOT_AVAILABLE/NOT_USUAL_DAY
```

This demonstrates the existing consumer that the revised plan must replace, not a failure of slot code that does not yet exist.

D-4's offer filter has a related consequence: suppose usual hours exist only on another weekday, while an unjoined slot-only session for the requested date is UNKNOWN. Dropping it because it has no open blocks leaves only NOT_USUAL_DAY facts. **Not offering a one-day session must not mean erasing its refusal evidence.** The same distinction matters when one slot-only session is cancelled and another is open. No-usual-schedule with no offered sessions may retain the explicitly chosen NO_USUAL_SCHEDULE callback, but it is not a general excuse to discard status elsewhere.

**Required revision:** separate selection of relevant session facts from selection of bookable alternatives. Combine the former to preserve callback/cancellation/full reasons, and use `is_match` only to select/count candidates. Retain D-4's open-only offering and WORKING_HOURS isolation. Also define duplicate labels after weekday filtering: repeated labels on different weekdays are not necessarily ambiguous, whereas multiple eligible rows for the same label/date are. Keep `_usual`'s use in `working_hours:268` free of slot/date-specific mutations.

## 3. Eleven-step booking walkthrough

| Step | Delta assessment against HEAD |
|---|---|
| 1 | Existing ON_CALL/whole-scope callback checks at `policy:283–286` are reusable. They do not alone protect mixed days; R4-B2 must preserve unresolved rows after time selection. |
| 2 | Existing Handoff at `:287–288` always carries PROFILE_UNAVAILABLE. New join-consistency failures need the explicit R4-S1 treatment, not a misleading profile failure. |
| 3 | Existing N-2 early refusal at `:289–290` is reusable. The new refinement needs session-flag/scope guards and must agree with step 8. |
| 4 | TimeRequired after whole-scope refusals is coherent. It does not require making the shared input time fields globally schema-required: LIST/CANCEL and disabled-slot behaviour remain valid. |
| 5 | Optional session checking is required by D-2 and stays internal. Define normalization, search scope and multiple block matches; no first-match selection. |
| 6 | Same result as step 5 when no block exists; these two rows do not intrinsically contradict each other and can share one guard. They must not override unresolved UNKNOWN evidence. |
| 7 | Correct for the selected block's UNKNOWN session but incomplete for UNKNOWN rows with no blocks and unlabelled unresolved rows. |
| 8 | Correct for cancellation/session flag refusal. It currently swallows the NO_OPEN_SLOT→SLOT_FULL distinction on mixed days. |
| 9 | CLOSED→TIME_OUTSIDE_SESSION is coherent once higher-priority scope/status/whole-session refusals have survived. |
| 10 | FULL→SLOT_FULL is coherent, but unreachable for an all-full selected session under the current step 8. |
| 11 | OPEN→Write(expected_slot=block.start) is coherent only after the preceding scope checks. No owner request body should contain session. |

## 4. Should change — bounded clarifications

### R4-S1 — limit the new failure treatment to the intended reads

The B-6 helper can centralize **detail selection** without flattening all failures into one outcome. Existing tests explicitly pin profile-read 400s to REJECTED with action-specific fields: `tests/test_booking.py:836–862` tests CREATE and RESCHEDULE. Appointment-lookup rejections are also pinned at `:808–831`. Other regression anchors are board retry-after (`test_availability.py:100–113`, `test_booking.py:401–404`), AUTH (`test_booking.py:238–243`), and malformed owner ID (`:682–692`). Unknown-name NOT_FOUND (`test_availability.py:197–199`) is an empty search result, not a transport rejection.

Revision 4 explicitly changes slots/capabilities failures, so preserve those old profile/directory/lookup behaviours unless separately approved. Put the new-stage handling ahead of generic Rejected handling; do not change `_failure`'s action-specific field filtering. Preserve the DIRECTORY_UNAVAILABLE fallback currently used by `src/availability.py:76–85`; it is missing from B-6's listed detail strings. State AUTH precedence separately for each existing path rather than accidentally changing legacy availability detail during helper extraction.

Also specify how C-5 duplicate-join failures cross the pure policy/service boundary. Today policy COULD_NOT_CHECK becomes `Handoff(PROFILE_UNAVAILABLE)` at `policy:287–288`, then HANDOFF_REQUIRED at `booking.py:251–252`; it is not the read-failure COULD_NOT_RECORD promised by K-8. Choose a typed failure propagation using the existing SLOTS_UNAVAILABLE detail and apply it consistently to availability and booking, without inventing a new public reason after 3a. Add no-write tests for duplicate joins.

### R4-S2 — purpose guard and the real cache guarantee

Plan:98–100 reads capabilities in `department()` without explicitly limiting it to AVAILABILITY, while plan:280 promises WORKING_HOURS is unaffected by capability failure. Add that purpose guard explicitly. Existing department WORKING_HOURS tests (`test_availability.py:246`) and `working_hours:261–269` should keep their meaning and make no capability/slot call.

`DirectoryCache` is a TTL/LRU cache, not a single-flight cache (`cache.py:21–38`, `schedule_reader.py:40–45`). Concurrent cold requests can each read capabilities; LRU eviction or TTL=0 can also cause additional reads. Phrase “once per TTL” as sequential reuse while cached, and test cold/warm/concurrent cases honestly. D-5 does not require adding a task/locking framework. This is an expected limitation to measure, not a request to reintroduce startup discovery.

### R4-S3 — unread is not an empty checked result; preserve legacy boundaries

Plan:147 says `open_slots` is empty for non-APPOINTMENT_REQUEST and None “without evidence.” Explicitly say **None for both disabled and SlotsNotRead**, and an empty tuple for checked-but-blocked evidence. A department result should not serialize an unread slot list as though it had been checked and found empty. Keep the full evidence for refusal decisions.

Retain the legacy ended-window guard (`policy:213–214`) only where it still applies. C-3's evidence-None branch lists the old status table but does not mention that guard. Tests `test_availability_policy.py:63–66` and `test_booking.py:75–85` pin it. Conversely, do not let the old board end-time guard overrule slot evidence; the plan deliberately uses owner blocks rather than a second window intersection.

### R4-S4 — freeze defaults and descriptions as well as field names in 3a

The D-1 approach is feasible. Specify `AppointmentOut.slotTime = None` from 3a (and compatible defaults for other new optional fields), so the unchanged `_appointment_out:86–89` constructor remains valid until 3b. Pydantic nullable does **not** imply optional:

```text
slotTime: str | None without default -> required; legacy constructor fails
slotTime: str | None = None -> legacy constructor succeeds: {'slotTime': None}
```

Choose the final type/default/description surface in 3a and keep it fixed. `DoctorAvailability.usualSessions` currently says “Usual working hours, independent of live attendance” (`outcomes.py:79–80`), which will no longer describe future one-day sessions/status. Update that description in 3a too. The snapshot equality at `test_server.py:134` includes descriptions even though the VOICE table shape comparison strips them. Pack text changes must retain accurate legacy facts required by `test_server.py:91–96`, qualified by slots-enabled/disabled behaviour.

## 5. Phasing and exact files

All declared footprints are within ten files. There is **no arithmetic reason to split them further**. The lists below are valid bounded assignments; the implementation must not create needless edits merely to touch every listed file. Future green commits cannot be certified by tests on today's code. The following is dependency analysis, conditioned on the corrections above and tested defaults, not a claim to have executed unimplemented phases.

Abbreviations: `src/`, `tests/` as above; `dev/` = `services/mcp/dev/`; `contracts/` = `docs/handover/mcp-only/contracts/`; `VOICE` = `docs/handover/VOICE-TEAM.md`.

| Commit | Exact file list | Count / independent-green assessment |
|---|---|---|
| 1a | `contracts/manoj-openapi-20261007.yaml`; `contracts/manoj-openapi-20261007.test-overlay.yaml`; `contracts/README.md`; `src/contract.py`; `tests/test_contract.py`; `tests/test_stubs.py`; `README.md` | **7. Feasible.** Pin/overlay/example/assertion consumers move together. ErrorCode does not directly expand MCP output literals. |
| 1b | `src/booking.py`; `dev/frontdesk_stubs/ops.py`; `tests/test_booking.py`; VOICE | **4. Feasible.** Definite SLOT_FULL is a detail string using existing outcome/nextStep literals. Leave same-key retry uncertainty unchanged; no schema change. |
| 2a | `src/contract.py`; `src/ops_client.py`; `dev/frontdesk_stubs/ops.py`; `tests/test_contract.py`; `tests/test_ops_client.py`; `tests/test_stubs.py` | **6. Feasible.** Methods/fixtures are not yet active on service paths. New owner Appointment.slotTime does not automatically change separate AppointmentOut. |
| 2b | `src/schedule_reader.py`; `src/availability_policy.py`; `src/availability.py`; `src/booking.py`; `tests/test_schedule_reader.py`; `tests/test_availability.py`; `tests/test_booking.py`; `tests/harness.py` | **8 maximum. Feasible with R4-S1.** Activate selected-doctor slot retrieval and facts while policy ignores them; stub default disabled. Keep department capability consumption/SlotsNotRead activation in 4a as listed there. No lifecycle/harness filtering is needed; omit harness edits if no fixture change needs them. |
| 3a | `src/availability_policy.py`; `src/availability.py`; `src/outcomes.py`; `tests/test_availability_policy.py`; `tests/test_availability.py`; `src/prompt.py`; `tests/contracts/mcp-tools.snapshot.json`; `src/packs/healthcare.json`; VOICE | **9. Schema publication feasible with R4-S4; policy content blocked by R4-B1–B3.** Include final booking output fields and ASK_WHICH_TIME now, all Reason/Decision consumers, and final descriptions. Defaults let existing booking constructors continue working until 3b. |
| 3b | `src/availability_policy.py`; `src/booking.py`; `src/outcomes.py`; `tests/test_availability_policy.py`; `tests/test_booking.py`; `tests/test_server.py` | **6 maximum. Feasible after matrix correction.** Changes to outcomes.py must be formatting only, not types/defaults/metadata. Gate result handling and expected_slot propagation are internal. |
| 4a | `src/schedule_reader.py`; `tests/test_schedule_reader.py`; `tests/test_availability.py`; `tests/test_stubs.py` | **4. Feasible.** Wire department capabilities/facts to already-published policy. Update `test_schedule_reader.py:36–60` MockTransport for the new path; retain search-bounding assertions. Guard WORKING_HOURS. |
| 4b | `tests/test_external.py`; `tests/test_external_transport.py`; `dev/bench.py`; `tests/test_bench.py`; `dev/demo.py`; `tests/test_e2e_processes.py` | **6 maximum. Feasible.** Update changed journeys and verify observed reads/useful outcomes. `make test-fast` excludes external and e2e tests, so its success does not validate those journeys. Run local process tests before hand-back; live tests require separate authorization. |
| 5 | `CLAUDE.md`; `docs/DECISIONS.md`; `docs/handover/mcp-only/PLAN.md` | **3. Feasible.** Rules/release documentation only; final schema is already fixed. Full build/release verification occurs on the complete tree. |

There is no required additional file outside these lists for the issues identified here. Resolve policy and failure details **before** 3a so they fit existing public failure envelopes. Then 3b, 4a and 4b can change implementation/tests only and 5 can update the remaining rules. Nothing after 3a inherently needs a schema change. Verify identical `make schema` output after every later commit; don't silently add fields, defaults, descriptions or enum values.

The minimal gate change is confirmed: `_schedule_gate` returns `BookingResult | Write`; `_reschedule_gate` additionally returns None for the accepted lookup-miss bypass. `_create` and `_change` branch explicitly on result type, carry expected_slot into formatting, and preserve None's existing bypass meaning. No wrapper result framework is needed. The plan's broader union is harmless, but None is not a successful CREATE gate result. CANCEL has no gate comparison; LIST/CANCEL keep slotMoved=false.

## 6. Live-shaped data checks and verification evidence

Parsed the two saved raw slot payloads with Python's JSON decoder and checked every block's bounds, non-negative capacity/booked/available, available≤capacity, and within-session ordering/non-overlap. Actual result:

```text
Capture 1: PASS; 1 sessions, 3 blocks; all A-2 numeric/order checks pass
Capture 2: PASS; 2 sessions, 5 blocks; all A-2 numeric/order checks pass
```

Capture 1's empty label and absent usual schedule are not model-validation errors. Capture 2's Morning session flag true with every block closed is also valid input. **Do not add booked+available=capacity as an invariant:** the captured closed blocks have capacity 5, booked 0, available 0. At the recorded capture times all Morning blocks have ended; Evening's two blocks remain open. These checks establish compatibility with A-2, not execution of future model validators or new policy code.

Executed against unchanged HEAD:

```sh
make test-fast
```

Actual output, with repetitive progress dots omitted:

```text
cd services/mcp && uv run ruff check . ../../deploy && uv run pytest tests -q -m "not e2e and not external"
All checks passed!
599 passed, 11 deselected, 2 warnings in 32.53s
```

Warnings are the existing Authlib deprecations. This includes the current schema snapshot and both VOICE table checks. In-memory diagnostics above do not modify source files. One initial diagnostic used dataclasses.replace on a Pydantic row and failed with TypeError; it was corrected to model_copy and rerun successfully. No finding relies on that diagnostic mistake.

Not run: new slot implementation/tests (not written), external APIs, Docker builds, process-e2e suite, Azure, ContextForge or real voice latency. No merge, push or deploy. Existing untracked plan/background/evidence and `temp/` are preserved; only this report is committed.

**Verdict: needs revision 5 — reconcile UNKNOWN versus cancellation (R4-B1), complete booking scope/FULL precedence (R4-B2), and preserve future refusal evidence (R4-B3); incorporate R4-S1–S4 without changing fixed D-1–D-5.**
