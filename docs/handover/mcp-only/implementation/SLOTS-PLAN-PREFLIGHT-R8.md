# Slots plan revision 8 — confirmation pre-flight

Reviewed 8 October 2026 against HEAD `33afd2b`.
Plan SHA-256: `9b1a19afe428ed59270cbbbc9699e29bd156832feb787661a86d9a82cbcb83ff`.
Scope: R8's shared retention predicate, its three scope uses, legacy impact and phasing. Only this report changes. No implementation or live owner requests.

References: `plan` means `SLOTS-PLAN.md`; `policy` means `services/mcp/src/frontdesk_mcp/availability_policy.py`; other source/test paths are relative to `services/mcp/`.

## 1. Results

| Check | Result | Evidence |
|---|---|---|
| R7-B1: future named Morning beside an unlabelled one-day UNKNOWN | **Resolved** | Plan:177–180,194 retains the row before `_combine`, for both empty and null normalized fact labels. Assembled slot-fact probes give CALLBACK_REQUIRED for named availability and Callback for booking. Morning without UNKNOWN remains APPOINTMENT_REQUEST/Write. This closes the loss at the old future label filter (`policy:244`) identified in R7. |
| Named/unnamed booking consistency, today and future | **Pass for the uncertainty cases** | 36 assembled-fact probes: two bases, three UNKNOWN labels (null/empty/Extra), three missing-bound combinations, two request scopes. All bookings callback. Four Morning-only controls write, as do four controls with a labelled, bounded UNKNOWN at an unrelated time. Availability's existing unnamed mixed-session choice is distinguished below. |
| Complete legacy test impact | **Six existing tests change** | Full hermetic run with the predicate substituted at all three sites: **6 failed, 593 passed, 11 deselected**. All six failures follow from the declared safety change. Exact list and downstream assertions are in section 2. The plan's expectation of only one affected test is incorrect, but it explicitly allows this review to extend that list (`plan:208,310`). |
| Future v0.3 | **Unchanged** | Repeated the 60-case comparison across six usual schedules, two future dates and five label choices. Complete DoctorDecision values agree with HEAD, including sessions, alternatives and reasons. No future no-slot row is CALLBACK_REQUIRED within the filtered day facts, so the added predicate does not fire. |
| Remaining UNKNOWN loss before a write | **None found within this delta review** | Named scope retains `_cannot_rule_out` rows before the whole-scope callback check; unnamed matching-time scope retains them before its callback check. A bounded, labelled row with no matching time is excluded under the approved scope rule. No-match/unbounded fallback, whole-scope refusals, status precedence and final block/name checks remain as specified. This is evidence for the reviewed cases, not certification of unimplemented slot code. |
| Phasing and public schema | **Ready with corrected phase assignment below** | Put the helper and all three scope uses into 3a as one coherent policy change. Add `tests/test_booking.py` to 3a: **10 files**. Keep 3b's **8 files** for the remaining booking work. The predicate introduces no schema field/default/description; the full final schema still publishes once in 3a. |

### Availability response distinction

The final callback-or-write decision agrees for the reviewed named and unnamed booking requests. The preceding availability responses are not identical: existing `_combine` (`policy:193–198`, retained by plan C-7) presents a mixed unnamed scope as a session choice. `src/availability.py:142–144` maps that to ASK_WHICH_SESSION; naming Morning then gives callback if the unresolved row cannot be excluded.

```text
Availability scope None : APPOINTMENT_REQUEST choice=True ; booking=Callback
Availability scope 'Morning' : CALLBACK_REQUIRED choice=False ; booking=Callback
```

The unnamed availability response does not authorize a write; it asks the caller to choose. This is the retained mixed-session behavior, not another UNKNOWN dropped before a write. Do not describe this review as proving identical availability envelopes. If immediate callback for the unnamed availability query were desired too, that would change the retained C-7 combination rule; R8 does not request that redesign.

## 2. Complete list of changed existing tests

| Existing test | Required expectation update under R8 |
|---|---|
| `tests/test_availability.py:127` — `test_any_unknown_session_in_scope_stops_the_journey` | Named Morning now returns CALLBACK_REQUIRED / ASK_CALLBACK_DETAILS / BOARD_STALE, retaining Morning and stale Afternoon facts (`:142`). The later unmatched-name request still callbacks with sessionMatched=false, but now retains Afternoon and reports BOARD_STALE instead of empty board / SESSION_NOT_ON_BOARD (`:145`). The unnamed mixed-choice and named-Afternoon assertions remain valid. |
| `tests/test_availability.py:154` — `test_department_queries_honour_the_session_too` | Night still returns CALLBACK_REQUIRED, but reasons differ per doctor: `doc_anil_sharma` retains SESSION_NOT_ON_BOARD; `doc_ravi_sharma` retains its unresolved stale row and reports BOARD_STALE. Replace the all-doctors SESSION_NOT_ON_BOARD assertion at :164 with exact per-doctor reasons. |
| `tests/test_booking.py:433` — `test_create_scope_follows_the_session_the_caller_chose` | Both named-Morning availability and CREATE now callback with BOARD_UNKNOWN (`:441,443`); the labelled Afternoon row has no known hours. Assert their agreement, callback metadata and no write. The test's old docstring/claim that this fixture permits Morning needs updating. Keep a separate bounded unrelated-session control to prove naming still disambiguates known sessions. |
| `tests/test_booking.py:449` — `test_create_without_a_session_resolves_scope_from_the_preferred_time_or_asks` | As recorded in R7: Morning time becomes CALLBACK_REQUIRED / BOARD_UNKNOWN; appointment count becomes zero (`:452,457`). The 15:30 callback and no-time SESSION_REQUIRED expectations remain unchanged in the disabled-slot path. |
| `tests/test_booking.py:460` — `test_unknown_in_an_unrelated_session_does_not_block_a_scoped_create` | This fixture is **not bounded at the adapter boundary**. The stale-board stub removes expectedTime and expectedEndTime (`dev/frontdesk_stubs/ops.py:226–235`), despite their presence in the scripted input. It therefore callbacks with BOARD_STALE instead of NOTED (`:468`). Preserve that stale-data safety assertion; add a separate fresh explicit UNKNOWN with known unrelated bounds to preserve the test's original disambiguation coverage. Do not weaken the stub to make stale hours look trustworthy. |
| `tests/test_booking.py:499` — `test_a_preferred_time_outside_the_chosen_session_window_is_rejected` | MIXED_BOARD also contains labelled, unbounded UNKNOWN. R8 retains it in named scope, so whole-scope callback now wins: CALLBACK_REQUIRED / BOARD_UNKNOWN instead of NOT_AVAILABLE / TIME_OUTSIDE_SESSION (`:502`). No-write remains true. Preserve a separate outside-window test without potentially relevant unresolved evidence. |

These are all changed test functions found in the complete isolated-condition run. Several assertions within a failing function need updating, including assertions after its first failure; direct service probes above and below cover those later values. Tests should gain the approved safety assertions and retain their useful bounded/outside-window controls, not be removed or weakened. No expectation changes were observed in other existing hermetic tests for this isolated predicate.

## 3. Corrected phase assignment

The named-scope changes affect availability immediately and belong with C-5 in 3a. They also affect booking through its existing whole-scope check (`policy:285–286`), so delaying all booking-test updates until 3b would make 3a fail. Moving the entire small helper plus all three uses together avoids a temporary split in the safety rule.

**3a — 10 files:**

1. `services/mcp/src/frontdesk_mcp/availability_policy.py` — C-1–C-5/C-7 plus `_cannot_rule_out` and all three scope uses.
2. `services/mcp/src/frontdesk_mcp/availability.py`
3. `services/mcp/src/frontdesk_mcp/outcomes.py`
4. `services/mcp/tests/test_availability_policy.py`
5. `services/mcp/tests/test_availability.py`
6. `services/mcp/tests/test_booking.py` — six-test impact includes four functions here; add red-first policy/service safety controls.
7. `services/mcp/src/frontdesk_mcp/prompt.py`
8. `services/mcp/tests/contracts/mcp-tools.snapshot.json`
9. `services/mcp/src/frontdesk_mcp/packs/healthcare.json`
10. `docs/handover/VOICE-TEAM.md`

Keep the required nullable hours, one-day formatter metadata, complete final defaults/descriptions and both tools' tables in 3a. Update voice guidance/examples that imply naming Morning can bypass an unresolved row with no hours; that document is already in this phase. The scope predicate itself changes no wire shape.

**3b — 8 files, same list:**

1. `services/mcp/src/frontdesk_mcp/availability_policy.py` — remaining C-6 time/block gate behavior.
2. `services/mcp/src/frontdesk_mcp/booking.py`
3. `services/mcp/src/frontdesk_mcp/availability.py`
4. `services/mcp/src/frontdesk_mcp/outcomes.py` — SessionChoice and formatting only, no schema change.
5. `services/mcp/tests/test_availability_policy.py`
6. `services/mcp/tests/test_booking.py`
7. `services/mcp/tests/test_availability.py`
8. `services/mcp/tests/test_server.py`

This is a viable dependency split, not a claim that future commits have been built. Run each commit's checks; keep the generated schema byte-for-byte stable after 3a. No deployment of intermediate phases.

## 4. Evidence and limits

Fresh unchanged-code baseline:

```text
$ make test-fast
All checks passed!
599 passed, 11 deselected, 2 warnings in 31.61s
```

For legacy-impact verification, a Python process obtained the three HEAD functions with `inspect.getsource`, added the predicate at their existing filters, and called `pytest.main(['tests', '-q', '-m', 'not e2e and not external', '--tb=short'])`. HEAD has no slot evidence, so all rows are no-block cases. No source or test file was edited. All failures were behavioral assertions, not setup failures:

```text
FAILED tests/test_availability.py::test_any_unknown_session_in_scope_stops_the_journey
FAILED tests/test_availability.py::test_department_queries_honour_the_session_too
FAILED tests/test_booking.py::test_create_scope_follows_the_session_the_caller_chose
FAILED tests/test_booking.py::test_create_without_a_session_resolves_scope_from_the_preferred_time_or_asks
FAILED tests/test_booking.py::test_unknown_in_an_unrelated_session_does_not_block_a_scoped_create
FAILED tests/test_booking.py::test_a_preferred_time_outside_the_chosen_session_window_is_rejected
6 failed, 593 passed, 11 deselected, 2 warnings in 31.05s
```

Additional process-local probes:

```text
Future v0.3 complete DoctorDecision equality: 60 / 60
Potentially relevant UNKNOWN, named/unnamed today/future:
  36 / 36 booking callbacks; all named availability callbacks
Morning-only controls: 4/4 availability APPOINTMENT_REQUEST and booking Write
Bounded unrelated UNKNOWN controls: 4/4 Write
Mixed booking Morning 10:45 : CALLBACK_REQUIRED BOARD_UNKNOWN
Mixed booking Morning 15:30 : CALLBACK_REQUIRED BOARD_UNKNOWN
Mixed booking None 10:45 : CALLBACK_REQUIRED BOARD_UNKNOWN
Mixed booking None None : INVALID_REQUEST SESSION_REQUIRED
Mixed appointments: 0
Stale unrelated booking: CALLBACK_REQUIRED BOARD_STALE
```

The slot-fact probes model the proposed membership/scope flow; they are not an implemented reader or live-service test. Future partly bounded one-day rows are robustness inputs, not claims that the current owner returns those fields. The actual emitted future one-day empty-block row has both bounds absent. A first supplementary booking probe used an invalid synthetic operation ID and hit OPERATION_CONTEXT_MISSING; it was corrected to valid `probe-N` IDs before recording the mixed-booking results above.

The two suite warnings are existing Authlib deprecations. No Docker build, process-e2e run, external-owner call, voice latency test, Azure operation, push, merge or deployment occurred. Untracked plan, impact document, saved live evidence and `temp/` were preserved.

## 5. Severity and verdict

- **Blocking:** none found in this confirmation scope.
- **Should change during implementation:** use the complete six-test impact list and corrected 3a/3b assignment above; both fit the existing file limits and declared safety decision. No further product decision or schema revision is needed.
- **Nit:** none requiring another plan round.

**Verdict: ready to build — apply the six intentional legacy-test changes and the corrected phase assignment recorded above.**
