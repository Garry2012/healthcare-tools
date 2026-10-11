# Slots plan revision 7 — final delta pre-flight

Reviewed 8 October 2026 against HEAD `9243ca6` (production source unchanged).
Plan SHA-256: `3b84cdb6c638e457bf439f6494db68886232ce1a1cdf33adfb26041a133abff5`.
Scope: R7's matched-branch condition, remaining UNKNOWN paths, one-day metadata and phase 3b. Fixed decisions were not reopened. Only this report changes.

References: `plan` = `SLOTS-PLAN.md`; `policy` = `services/mcp/src/frontdesk_mcp/availability_policy.py`; other source/test paths below are relative to `services/mcp/`.

## Results

| Check | Result | Evidence |
|---|---|---|
| R6-B1: labelled blockless UNKNOWN with missing bounds beside a matching open session | **Resolved** | Plan:199–203 adds CALLBACK_REQUIRED + no blocks + either missing bound to the existing matched-branch retention rule. Process-local probes applying this condition to HEAD's booking function returned callback for all 12 assembled-fact combinations: today/future basis, blocks/no blocks on the open neighbour, and neither/start/end missing on UNKNOWN. These are policy probes; future no-slot UNKNOWN and partly bounded one-day rows are robustness inputs, not claims that current retrieval produces them. |
| Unlabelled and passed-time controls; other unbounded decisions | **Preserved** | The additional condition leaves the unlabelled rule intact. Unlabelled UNKNOWN still callbacks. A bounded past UNKNOWN window plus unrelated open Evening still gives TIME_OUTSIDE_SESSION. Labelled unbounded APPOINTMENT_REQUEST and NOT_AVAILABLE neighbours remain excluded when another session matches, so they do not introduce a handoff/refusal. Plan:201 correctly limits the addition to CALLBACK_REQUIRED. |
| Existing expectations affected by the intentional v0.3 safety fix | **One test changes, not zero** | `tests/test_booking.py:449–457`, `test_create_without_a_session_resolves_scope_from_the_preferred_time_or_asks`. Its mixed board includes labelled Afternoon UNKNOWN with neither bound (`:426–430`). The morning-time request changes from NOTED to CALLBACK_REQUIRED/BOARD_UNKNOWN; appointment count changes from 1 to 0. A full hermetic run with only the proposed condition substituted in memory produced exactly this one failing test, with 598 passing. See R7-S1. |
| Other UNKNOWN path before a write | **Not resolved** | A future named-session filter can discard an unlabelled one-day UNKNOWN before booking sees it. The new matched-branch rule cannot recover it. See blocking R7-B1. |
| Required nullable hours and one-day metadata | **Resolved** | Plan:260 expressly keeps start/end required without defaults, adds the one-day status/marker, and replaces `requested.weekday in s.days` for one-day facts with onRequestedDate=true. This addresses `src/outcomes.py:38–45,65–67`. Both tools' VOICE tables and the snapshot are assigned to 3a (`plan:260,270,324`). No further schema decision is needed. |
| Phase 3b: eight files and no schema change | **Viable** | Plan:325 includes policy, booking, availability, outcomes and their four specified test files. The scope condition and both review findings fit the existing policy/booking test allocation. One-day model/formatter metadata stays in 3a. No additional field, enum, default or description is required after 3a. Future green commits still require implementation-time verification. |

## Blocking R7-B1 — future named scope loses an unlabelled UNKNOWN

**Location:** plan:182–190, especially :186; current future label rule at `policy:244`; booking bypass of time narrowing for a supplied session at `policy:293`.

Concrete future-date input:

- Usual Morning session, 10:00–12:00, with a matching slot session and an OPEN block at 10:00–12:00.
- A second slot session with an empty/unlabelled name, status UNKNOWN and no blocks. It has no usual-schedule match and therefore becomes a one-day fact with no hours under C-5.
- Caller requests **Morning at 10:30**.

This is permitted by the proposed consumer checks: slot labels are distinct, the UNKNOWN row has no block to overlap, and empty blocks are allowed. Its unknown label and hours provide no evidence excluding the caller's target. Today the unlabelled UNKNOWN would be retained for refusal safety. C-6 step 5 expressly promises that protection before the name check (plan:207).

For a future date, however, plan:186 applies the existing strict future label filter to the day facts. It retains Morning and removes the unlabelled UNKNOWN. The doctor decision is APPOINTMENT_REQUEST. A supplied session bypasses booking's time-narrowing branch, and even if the new matched-branch condition ran, the discarded row would no longer exist in `DoctorDecision.sessions`. The remaining Morning block passes both time and label checks, so the planned flow permits a write.

The following probe constructed the planned post-reconciliation day facts, applied C-5's exact future label predicate, and ran HEAD's booking function with R7's new condition substituted **in memory**:

```text
R7 future named Morning + unlabelled one-day UNKNOWN:
  scoped labels= ['Morning'] -> Write
Same facts with today scope -> Callback
New final block/name guard also accepts Morning OPEN block.
```

The decisive selection is reproducible with the two SessionDecision facts above:

```python
future_scope = tuple(s for s in rows
    if not name or p.normalised(s.label or "") == p.normalised(name))
today_scope = tuple(s for s in rows
    if not name or not p.normalised(s.label or "")
    or p.normalised(s.label) == p.normalised(name))
```

This is a plan-flow probe, not a claim that HEAD already supports future slot responses. Current `_future` has only usual-schedule facts; the problem appears when new dated UNKNOWN evidence is passed through its old label filter.

**Required plan correction:** preserve potentially relevant unlabelled UNKNOWN slot evidence in future named scope before combining decisions. Keep the legacy no-slot usual-label behavior; retaining refusal evidence must not make an unlabelled open session satisfy a supplied name. No second booking matrix or new public schema is needed. Add future policy and CREATE/RESCHEDULE no-write tests for named Morning plus unlabelled one-day UNKNOWN, covering empty and null normalized fact labels, alongside the passing named-Morning control without UNKNOWN. Include availability output so its offer agrees with booking's refusal.

## Should change R7-S1 — document the one intentional legacy test change

The R7 addition is a deliberate v0.3 behavior change, as plan:202 says. But plan:60 and :304 still promise that all existing business assertions stay unchanged. The test listed above directly asserts the old unsafe behavior.

With only the proposed condition applied in memory, the full suite reports:

```text
FAILED tests/test_booking.py::test_create_without_a_session_resolves_scope_from_the_preferred_time_or_asks
tests/test_booking.py:452:
    assert inside_morning.outcome == "NOTED"
E   AssertionError: assert 'CALLBACK_REQUIRED' == 'NOTED'
1 failed, 598 passed, 11 deselected, 2 warnings in 30.69s
```

Running all three requests in that same existing test without its early failing assertion confirms the complete new expectations:

```text
Existing test journey with proposed condition:
[('CALLBACK_REQUIRED', 'BOARD_UNKNOWN'),
 ('CALLBACK_REQUIRED', 'BOARD_UNKNOWN'),
 ('INVALID_REQUEST', 'SESSION_REQUIRED')]
Appointment count: 0
```

List this test as an intentional change in the plan and hand-back. Update its first outcome and final appointment-count assertions during implementation; assert callback details and no write. Do not weaken or remove the test. The named-session control `test_create_scope_follows_the_session_the_caller_chose` and bounded unrelated-UNKNOWN control `test_unknown_in_an_unrelated_session_does_not_block_a_scoped_create` passed unchanged in the substituted run. No other existing hermetic test expectation changed for this isolated condition.

## Verification and limits

Fresh unchanged-code baseline:

```text
$ make test-fast
All checks passed!
599 passed, 11 deselected, 2 warnings in 31.52s
```

The second full hermetic run used `inspect.getsource(policy.decide_booking)` and replaced only the matched-branch predicate in the Python process before calling `pytest.main`. HEAD has no slot evidence, so every row is the no-block case for that isolated experiment. No source or test file was edited. This run intentionally exposed the legacy assertion above; it is not an implementation test pass.

Additional process-local policy probe results:

```text
R6-B1 assembled-fact probes: 12 / 12 -> Callback BOARD_UNKNOWN
Labelled unbounded IN neighbour -> Write
Labelled unbounded CANCELLED neighbour -> Write
Unlabelled UNKNOWN control -> Callback
Approved bounded past-time control -> TIME_OUTSIDE_SESSION
```

The warnings are existing Authlib deprecations. Slot behavior, future one-day retrieval and the final new schema are not implemented yet. No live API call, Docker build, process-e2e run, Azure operation, push, merge or deployment was performed. Untracked plan, impact document, saved evidence and `temp/` remain untouched. Only this report is committed.

**Verdict: needs revision 8 — R7-B1: retain future unlabelled UNKNOWN refusal evidence before named-session filtering; R7-S1: explicitly account for the one existing booking test's deliberate behavior change.**
