# Slots plan revision 10 — on-call delta pre-flight

Reviewed 8 October 2026 against HEAD `115885a`.
Plan SHA-256: `fef5fc430cb1d3d2cc96a0c01464f0d4b249197af3adfae62ced1034c685bd33`.
Scope: D-8/C-8 only and its consequences for consumers, tests, documentation and commits. D-1–D-7, including the revision 9 label decision, are accepted and not re-reviewed. Only this report changes.

References: `plan` means `SLOTS-PLAN.md`; `policy` means `services/mcp/src/frontdesk_mcp/availability_policy.py`; `src/` and `tests/` below are relative to `services/mcp/`.

## 1. Results

| Check | Result | Evidence |
|---|---|---|
| One on-call policy function | **Possible, but the specified inputs lose required facts** | `on_call(decision, reason, usable)` at plan:240 cannot distinguish IN + open block from NOT_CONFIRMED + open block; both leave C-3 with APPOINTMENT_REQUEST and usable=true (plan:153–158). D-8 requires different results. Department SLOT_CHECK_REQUIRED has the same status-loss problem. See B1. |
| Deleting old branches | **Removal sites identified; consumer handling incomplete** | Remove `policy:203–204`, `:256–257`, and the ON_CALL callback at `:283–284`. Replace the remaining `_on_call` use in `working_hours:262–263` as plan:246 says. Session decisions must be adjusted before alternatives/scope/combination, and no-session exits must use the same rule. C-6 needs the new handoff check both before and after time selection; see B2. |
| New Decision.HANDOFF_REQUIRED | **Appropriate representation** | Public outcomes already contain HANDOFF_REQUIRED, but nested DoctorDecision/SessionDecision currently cannot represent it. The new enum keeps facts, aggregation, formatting and booking consistent. Reusing CALLBACK_REQUIRED or COULD_NOT_CHECK would misrepresent D-8 and require reason/type exceptions across consumers. See section 3. |
| Reader and future department | **Partly specified** | Removing the name-summary shortcut for AVAILABILITY is correct and retains the WORKING_HOURS shortcut. But future department on-call facts deliberately have profile=None (`src/schedule_reader.py:115–116`); the retained `_future:236–237` returns PROFILE_UNAVAILABLE before the proposed no-day handoff. See B3. |
| No-slot usable windows | **Sound for IN/LATE, once B1 is addressed** | Both bounds plus not-ended prevents admission of the cases that currently cause TIME_NOT_VERIFIABLE (`policy:314–315`). Missing/ended bounds become ON_CALL_DOCTOR handoff; ordinary doctors retain their existing behavior. With enabled slots the final C-6 block branch must continue to bypass the legacy unknown-board-boundary check. |
| Legacy test impact | **10 failing cases, 8 test functions** | Full hermetic in-memory experiment: 589 passed, 10 failed, 11 deselected. Complete list in section 4. A generic rollup test and HTTP journey contain on-call assertions; the snapshot test also changes. No unrelated ordinary-doctor behavioral failure was observed. |
| Independent green phases | **Needs corrected assignments** | 2b's name-query test injects a board failure, so its outcome changes as well as its request list. 3a also needs `tests/test_server.py`, making the supplied list 11 files. Split final schema publication from behavior as detailed below; no second schema publication is needed. |
| Current docs | **Named locations are necessary but incomplete** | Include copied tool descriptions, HANDOFF outcome rows, prompt text and target-plan rules as listed in section 6. R10 itself retains contradictory old on-call/no-exception statements that must be qualified for D-8. |

## 2. Blocking findings

### B1 — the on-call function cannot implement D-8 from its proposed inputs

Plan:39 requires desk-confirmed IN/LATE **and** a usable window or open slot. Plan:240–244 operates on a decision that has already discarded the distinction between IN and NOT_CONFIRMED.

Concrete slot-enabled inputs:

```text
IN + enabled open block -> C3 APPOINTMENT_REQUEST -> C8 (APPOINTMENT_REQUEST, None)
NOT_CONFIRMED + enabled open block -> C3 APPOINTMENT_REQUEST -> C8 (APPOINTMENT_REQUEST, None)
```

Both call the proposed function with the same `(decision, reason, usable)`. Its first rule keeps both, so the second can reach booking even though D-8 expressly requires handoff. An absent desk status on a usual-schedule fact has the same problem: the literal no-slot substitution admitted the synthetic on-call usual-hours fixture for a future date without any confirmed entry. The test fixture is atypical, but normal working hours must not supply confirmation.

Two related usability cases also need alignment:

- **Department IN with missing bounds and slots deliberately unread:** C-3 produces SLOT_CHECK_REQUIRED. C-8:242 keeps it just because status is IN/LATE, even though neither a usable window nor an observed open block exists. The same signature cannot even verify the stated status qualifier. D-8 requires handoff in this case.
- **Confirmed IN with a usable board window, but enabled slots all full/flag false/empty:** D-8's window-or-open-slot condition is met, so normal slot policy should apply (for example NOT_AVAILABLE/NO_OPEN_SLOT). C-8:241 instead requires an open block whenever slot evidence exists, and :244 changes the refusal to handoff. Section 9 repeats that contrary expectation. “Treated like any other doctor” does not mean a valid window bypasses capacity; it means preserve the ordinary capacity refusal once D-8's confirmation/usability requirement is satisfied.

**Required revision:** retain the confirmed owner status and the relevant window/slot facts until the single on-call rule runs. The existing session facts already carry this information; no second on-call policy or service-level special case is needed. State and test D-8's AND/OR rule explicitly, including the department case. Preserve true read failures. This is an implementation of fixed D-8, not a request for a new owner decision.

### B2 — handoff must be checked after time selection, not just before it

Plan:204 adds the whole-scope HANDOFF_REQUIRED check. Plan:208 still lists only CALLBACK_REQUIRED and NOT_AVAILABLE after `_combine(sessions, True)`. C-8's general statement that handoff maps to Handoff needs an explicit application here too.

Concrete no-slot probe at 10:00:

- Morning IN, 10:00–12:00, usable: APPOINTMENT_REQUEST.
- Unlabelled UNKNOWN, also with known 10:00–12:00 bounds: C-8 changes it to HANDOFF_REQUIRED/ON_CALL_DOCTOR.
- Caller gives 10:30 without a session name.

Whole-day combination finds the open candidate and asks for a choice. Time selection retains both the matching and unlabelled rows. Updated `_combine` produces HANDOFF_REQUIRED, but HEAD's post-combination branch (`policy:306–318`) has no such case. Both windows are known, so it returns Write. The new enabled-slot step could similarly pick Morning's OPEN block if handoff falls through.

Actual isolated probe, updating combination while leaving the numbered C-6 post-selection handling unchanged:

```text
Updated combine + unchanged C6 step 4 + bounded unlabelled handoff: Write
```

**Required revision:** explicitly return `Handoff(ON_CALL_DOCTOR)` after scoped combination as well as at the whole-scope check. Put both into the same phase that starts producing the new Decision. Add CREATE and RESCHEDULE no-write tests for mixed usable + unresolved on-call sessions, with bounded and unbounded unresolved rows, plus named/unlabelled cases. This adds no second on-call rule: it consumes the policy decision.

### B3 — deliberately unread future on-call profiles are mistaken for failures

The department reader returns `DoctorFacts(on_call_summary)` without fetching a profile (`src/schedule_reader.py:115–116`). Removing the early attendance return in `decide_doctor` sends that fact into `_future`. Its first branch (`policy:236–237`; retained at plan:189) is PROFILE_UNAVAILABLE. The no-day exit never runs.

Actual HEAD functions on precisely that reader-produced fact:

```text
Intentionally unread on-call future department profile -> COULD_NOT_CHECK PROFILE_UNAVAILABLE
Existing aggregate on that sole doctor -> NOT_AVAILABLE
```

Adding a handoff branch to aggregate does not help because this fact never became a handoff; aggregate excludes COULD_NOT_CHECK candidates. This contradicts plan:247's explicit future-department handoff.

**Required revision:** distinguish a deliberately unread on-call profile from a failed read, and route the former through the shared on-call no-evidence rule before the generic missing-profile failure exit. Keep actual profile/board/slot exceptions as read failures. The reader already distinguishes thrown read errors/ReadFailure from its deliberately constructed on-call DoctorFacts, so no synthetic profile or extra REST request is necessary. Add future department tests with only on-call doctors and a mixed regular/on-call result.

## 3. Decision consumers and smaller alternatives

| Consumer | Required treatment |
|---|---|
| `_combine`, `policy:189–200` | Add handoff to unresolved outcomes before NOT_AVAILABLE; retain the existing unselected-positive choice behavior. C-8 must run before combination so an on-call doctor never mixes callback and handoff merely because some rows were adjusted late. |
| D-7 future named filter | Broaden only its unlabelled unresolved condition to include HANDOFF_REQUIRED (plan:232). The older CALLBACK-only wording at plan:181,193 must be updated so implementers do not lose an unlabelled on-call UNKNOWN. Labelled-row D-7 behavior stays fixed. |
| Booking | Consume handoff at both whole and selected scope. Remove the reason-based ON_CALL callback check. Existing `src/booking.py:251–252` already formats policy.Handoff correctly; no new booking envelope is required. |
| `rank` / `aggregate` | Add the new decision everywhere. Callback-first aggregate is specified, but equal rank for callback and handoff can hide the callback candidate when the result is capped; see S1. Preserve existing incomplete-search and WORKING_HOURS behavior. |
| `_single` / `doctor_out` / `session_out` | Map handoff to HANDOFF_REQUIRED/TRANSFER_DESK, omit callback metadata, and serialize the new nested enum. Formatters already forward decision/reason. Slots, one-day metadata and null hours remain as previously planned. |
| Reader counts / C-7 `is_match` | Handoff is never a match. Only policy-approved APPOINTMENT_REQUEST or SLOT_CHECK_REQUIRED counts. Unusable on-call department rows must not reach the second value (B1). |

**Representation trade-off:** a new Decision value is the smallest truthful representation across the existing shared policy and nested public facts. A no-schema alternative could carry CALLBACK_REQUIRED/ON_CALL_DOCTOR and special-case its presentation and every consumer, or overload COULD_NOT_CHECK. Both conflate distinct meanings, spread attendance handling, and risk restoring callback behavior. The final schema is already changing once in 3a, so there is no benefit in those exceptions.

One pure on-call function remains feasible: consume facts before they lose status/usability, apply the resulting decision before scope/alternatives, and use it for no-evidence exits. A thin invocation at WORKING_HOURS is necessary, not a parallel scheduling rule. Deleting `_on_call` without replacing its working-hours caller would leave a dangling reference; the plan already names that replacement.

### S1 — callback-first aggregation can return only handoff doctors after capping

Plan:234 assigns both callback and handoff rank 1. Aggregate selects callback first but returns all resolved candidates (`policy:339–341`); `availability.py:129` then ranks and caps them by decision rank/name.

```text
Callback aggregate, doctor_choice_limit=1:
  Z Regular = CALLBACK_REQUIRED
  A Oncall  = HANDOFF_REQUIRED
Proposed equal rank returns only A Oncall.
```

The top-level callback would then be accompanied solely by a doctor requiring transfer. Make ranking/candidate selection honor the declared callback priority, and test a mixed department with a small cap. No schema change is needed.

## 4. Complete existing-test impact observed

The in-memory experiment added the new enum and its consumers, removed the AVAILABILITY reader shortcut, applied C-8's literal decision/usability conversion on legacy facts, and changed WORKING_HOURS. It included the intended post-selection Handoff consumption to test business impact; B2 separately tests what happens if the numbered plan's omission is followed. It did not implement slot transport, change test files, regenerate the snapshot, or quietly repair B1/B3.

| Existing test | Cases / observed change / required action |
|---|---|
| `tests/test_availability.py:116` — `test_on_call_doctor_requires_callback_regardless_of_board_status` | 1. Fixture's confirmed usable IN becomes APPOINTMENT_REQUEST. Its subsequent NOT_CONFIRMED check must become HANDOFF_REQUIRED/TRANSFER_DESK with no callback metadata. Rename the blanket-callback expectation. |
| `tests/test_availability.py:264` — `test_working_hours_on_call_uses_the_full_callback_result` | 2 parameters (ID/name). Both become HANDOFF_REQUIRED/TRANSFER_DESK, reason ON_CALL_DOCTOR, callback=None; still no board read. |
| `tests/test_availability.py:518` — `test_today_on_call_by_name_needs_no_board_read` | 1. This test injects `/availability` 500. Once the read is enabled it returns COULD_NOT_CHECK/BOARD_UNAVAILABLE, **not** a policy callback/handoff. Change the failure assertion and paths in 2b; add a successful name-query control. |
| `tests/test_availability_policy.py:106` — `test_on_call_is_callback_even_when_board_says_in` | 2 dates. Today confirmed usable IN should be actionable. Future fixture also supplies ordinary hours despite ON_CALL; the literal C-8 conversion made it actionable without confirmation, demonstrating B1. Fix the fixture/coverage to distinguish confirmed future slots from no desk evidence, rather than approving that accidental result. WORKING_HOURS handoff also needs an assertion. |
| `tests/test_availability_policy.py:154` — `test_department_rollup_and_counts_do_not_list_callback_as_bookable` | 1. Despite its generic name, its “callback” fixture is an on-call doctor with a usable IN row. It becomes a bookable candidate. Use a genuinely unresolved regular fixture for the generic callback assertion; add explicit callback-versus-on-call-handoff and usable-on-call count cases. |
| `tests/test_booking.py:107` — `test_on_call_and_failed_profile_never_reach_a_write` | 1. Existing CREATE asks 10:45; the confirmed on-call fixture has a different usable window, so it becomes NOT_AVAILABLE/TIME_OUTSIDE_SESSION, not callback. Add inside-window success and unresolved handoff cases. Its subsequent ordinary failed-profile assertion remains COULD_NOT_RECORD with no write. |
| `tests/test_server.py:134` — `test_tool_schemas_match_the_pinned_snapshot` | 1. Expected generic artifact failure: the new Decision changes both tools' nested output schemas. Regenerate the final snapshot in the single schema publication; do not weaken the equality assertion. |
| `tests/test_server.py:142` — `test_the_whole_journey_over_http` | 1. The future on-call CREATE at :150–155 becomes HANDOFF_REQUIRED instead of CALLBACK_REQUIRED. This is a real on-call expectation in a broader HTTP journey, missing from the plan's test inventory and phase 3a file list. |

**Total: 10 parametrized cases in 8 functions.** These include two generically named behavioral tests whose fixtures/actions are on-call, plus one generic schema check. No unrelated ordinary-doctor behavioral failure appeared. `tests/test_schedule_reader.py` had no failing expectation in this isolated run; its on-call profile-skip assertions remain valid. References to on-call in a test file are not the same as changed assertions.

Path impact: the known failing exact path assertion is `test_availability.py:523`. Today name-selected on-call changes from directory-only to directory → board ∥ slots; future name selection changes to directory → profile ∥ slots. WORKING_HOURS name selection still skips board/slots/profile. ID-selected on-call already read profile/board today; it adds slots through the general selected-doctor change. Existing missing-date and invalid-doctor-ID path assertions remain unchanged.

## 5. Corrected phasing

**2b remains at 7–8 files:** `src/schedule_reader.py`, `src/availability_policy.py`, `src/availability.py`, `src/booking.py`, `tests/test_schedule_reader.py`, `tests/test_availability.py`, `tests/test_booking.py`, optional `tests/harness.py`. Remove the AVAILABILITY shortcut here, retaining the old callback policy until the behavior phase. Successful reads still reach the old callback; the injected 500 does not. Updating only :523's request list cannot make the phase green: update the same test's outcome too. No schema change is required in 2b.

The listed 3a has ten files but additionally needs `tests/test_server.py:155`. Simply adding it yields **11**, violating the commit limit. A clean split avoids moving tests artificially or weakening assertions:

**3a-1 — final schema publication, 6 files:**

1. `src/availability_policy.py` — final enum/type surface only; do not activate new on-call behavior yet.
2. `src/outcomes.py` — all final output fields/defaults/descriptions, including one-day and appointment fields.
3. `src/prompt.py`
4. `tests/contracts/mcp-tools.snapshot.json`
5. `src/packs/healthcare.json`
6. `docs/handover/VOICE-TEAM.md`

Existing behavior remains operational in this undeployed intermediate commit, while schema/VOICE equality checks see the complete final surface. Required nullable start/end remain populated by existing constructors; new fields have the planned defaults. This is the already-approved staged publication, not authorization to deploy it.

**3a-2 — availability policy and D-8 activation, 7 files:**

1. `src/availability_policy.py` — C-1–C-5/C-7/C-8, no-session handling, both booking handoff consumption points.
2. `src/availability.py`
3. `src/outcomes.py` — formatting only, no schema changes.
4. `tests/test_availability_policy.py`
5. `tests/test_availability.py`
6. `tests/test_booking.py`
7. `tests/test_server.py` — HTTP journey's on-call assertion.

**3b retains its 8 files** from plan:345 for the remaining chosen-time/block booking work and shared session input type. No enum, field, default or description may change after 3a-1. Both proposed 3a commits are independently testable once B1–B3 are resolved. They are a corrected dependency plan, not claims of executed green implementation commits.

## 6. Documentation completeness

The named VOICE rows at :302,912,1598,1636–1638 are correct targets. Also update:

- `docs/handover/VOICE-TEAM.md:99,605`: copied availability/booking descriptions explicitly say on-call callback.
- The HANDOFF_REQUIRED outcome meanings at :308,914: include unresolved on-call attendance, not only incomplete search/time validation.
- `src/prompt.py:16`, both descriptions in `src/packs/healthcare.json`, and their generated snapshot copies.
- `CLAUDE.md:23` (always callback) and :26 (single on-call working-hours callback). Keep ordinary UNKNOWN and empty regular schedules distinct from the on-call exception.
- Current target `docs/handover/mcp-only/PLAN.md:31,67–68,77–78`, not only the approximate lines named in R10. Add a new DECISIONS entry superseding the old on-call rule; historical hand-backs remain historical.

R10 itself needs aligned wording: plan:65 and :323 still say all legacy business assertions stay unchanged; :323 still says the on-call directory-only assertion is unchanged; :325 still promises the ON_CALL shortcut makes no slots read. B-3:101's ON_CALL shortcut must be qualified as WORKING_HOURS only. C-5's callback-only unresolved wording must include on-call handoff. These are D-8 consequences, not reopened D-7 decisions.

## 7. Verification evidence and limits

Fresh baseline:

```text
$ make test-fast
All checks passed!
599 passed, 11 deselected, 2 warnings in 31.56s
```

Full hermetic experiment (`PYTHONPATH=dev uv run python -`, process-local source substitution, then `pytest.main` with `-m "not e2e and not external"`):

```text
FAILED test_availability.py::test_on_call_doctor_requires_callback_regardless_of_board_status
FAILED test_availability.py::test_working_hours_on_call_uses_the_full_callback_result[target0]
FAILED test_availability.py::test_working_hours_on_call_uses_the_full_callback_result[target1]
FAILED test_availability.py::test_today_on_call_by_name_needs_no_board_read
FAILED test_availability_policy.py::test_on_call_is_callback_even_when_board_says_in[today]
FAILED test_availability_policy.py::test_on_call_is_callback_even_when_board_says_in[2026-10-05]
FAILED test_availability_policy.py::test_department_rollup_and_counts_do_not_list_callback_as_bookable
FAILED test_booking.py::test_on_call_and_failed_profile_never_reach_a_write
FAILED test_server.py::test_tool_schemas_match_the_pinned_snapshot
FAILED test_server.py::test_the_whole_journey_over_http
10 failed, 589 passed, 11 deselected, 2 warnings in 30.81s
```

The two warnings are existing Authlib deprecations. This measures proposed legacy impact; it does not certify slots or the incomplete C-8 rule. Direct probes separately demonstrated B1/B2/B3 and the ranking issue. No source/test file was changed, no snapshot was regenerated, and no owner API was called. No Docker/process-e2e/external/voice-latency run, Azure change, push, merge or deployment occurred. Existing untracked plan, impact document, saved evidence and `temp/` were preserved.

**Verdict: needs revision 11 — B1: preserve status and implement D-8's usable-window/open-slot rule; B2: consume handoff after scoped combination; B3: handle deliberately unread future on-call profiles; S1: preserve callback priority under result capping; incorporate the complete test/doc inventory and corrected phase split.**
