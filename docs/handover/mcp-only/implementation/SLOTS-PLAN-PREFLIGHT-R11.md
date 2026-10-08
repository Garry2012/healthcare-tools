# Slots plan revision 11 — confirmation pre-flight

Reviewed 8 October 2026 against HEAD `8ca3298c736ed7513b7fe56e6edd6f73823a21db`.
Plan SHA-256: `bc3835b0ce8bdbb1bdded12a74cb2322bd2c4b7c8cd4a1564d290136efbc60dd`.
Scope: R10's on-call findings and the R11 corrections only. D-1–D-8 are fixed. No source/test/other documentation changes; only this report.

References: `plan` = `SLOTS-PLAN.md`; `policy` = `services/mcp/src/frontdesk_mcp/availability_policy.py`; source/test paths below are relative to `services/mcp/`.

## 1. Results

| Finding/check | Result | Evidence |
|---|---|---|
| B1: lost confirmation/usability facts | **Resolved** | Plan:245–248 uses owner_status, window and evidence before scope/alternatives. The five prepared post-C3 fact probes below distinguish IN from NOT_CONFIRMED with identical open capacity, reject unread department capacity without a window, and preserve NO_OPEN_SLOT once a confirmed usable window meets D-8. |
| B2: handoff after time selection | **Resolved** | Both checks are explicit at plan:205,209,253. Eight actual service/client/stub journeys—CREATE/RESCHEDULE × named/unnamed × bounded/unbounded unlabelled UNKNOWN—returned HANDOFF_REQUIRED/ON_CALL_DOCTOR and made no appointment write. Existing `src/booking.py:251–252` consumes policy.Handoff for both actions. |
| B3: deliberately unread future profile | **Resolved** | Plan:243 selects an empty usual source for on-call doctors without consulting profile, then uses the no-session outcome at :250. A source condition before the regular profile guard at `policy:236–240` is sufficient. Future department-only on-call returned handoff; mixed results retained regular matches and did not count on-call handoff as bookable. An injected board 500 still returned COULD_NOT_CHECK. The future on-call fixture with supplied usual hours now hands off rather than treating those hours as confirmation. |
| S1: capped callback priority | **Resolved** | Plan:235 assigns callback rank 1 and handoff rank 2. Actual aggregate/rank probes returned callback doctor “Z Regular” ahead of handoff doctor “A Oncall” under limit=1, despite lexical order. |
| Legacy impact inventory | **Confirmed exactly** | Full in-memory substitution: **10 failed, 589 passed, 11 deselected**. Exactly the eight functions/ten cases listed in plan:338; no extra failing test. See section 3. The snapshot failure is expected because the experiment leaves the tracked snapshot unchanged. |
| Phasing | **Viable as assigned** | 2b ≤8 files; 3a-1 6; 3a-2 7; 3b 8 (plan:350–353). The reader-only 2b probe verifies both the old policy after a successful read and the new failure path. Final schema definitions/defaults/descriptions all fit 3a-1; subsequent work need not change the surface. Future implementation commits still require their own green checks. |
| Leftover wording | **Minor corrections remain** | No unqualified “all legacy assertions unchanged” requirement remains: plan:66,329 explicitly exempts D-8. Some older general paragraphs still say callback where the on-call exception requires handoff, and one retrieval-test sentence incorrectly suppresses regular profile reads. Exact corrections are listed in section 5; the authoritative C-8 behavior is now clear. |

## 2. Targeted proof

Prepared post-C3 SessionDecision probes through the proposed `on_call(s, now)` rule:

```text
B1 IN open -> APPOINTMENT_REQUEST None
B1 NOT_CONFIRMED open -> HANDOFF_REQUIRED ON_CALL_DOCTOR
B1 Department IN missing bounds -> HANDOFF_REQUIRED ON_CALL_DOCTOR
B1 Department IN usable window -> SLOT_CHECK_REQUIRED None
B1 IN usable window all full -> NOT_AVAILABLE NO_OPEN_SLOT
B1 future on-call with usual hours -> HANDOFF_REQUIRED ON_CALL_DOCTOR
```

The first five are isolated policy probes over constructed slot evidence, not implemented slot retrieval. They establish that the revised rule has the information needed to implement D-8 without local capacity calculation or another on-call decision branch. It retains the reconciled status; NOT_CONFIRMED cannot borrow confirmation from available capacity.

Service probes used the existing BookingService/AvailabilityService, clients and in-process owner stubs, with only the proposed policy/reader/mapping substitutions in memory:

```text
B2 actual CREATE/RESCHEDULE, bounded/unbounded, named/unnamed:
  8 /8 handoff and no write
B3 only on-call future department: HANDOFF_REQUIRED ON_CALL_DOCTOR
B3 mixed future department: AVAILABILITY lists ordinary matches, handoff not counted
B3 actual on-call board failure: COULD_NOT_CHECK BOARD_UNAVAILABLE
S1 mixed department capped at 1: CALLBACK_REQUIRED Z Regular
```

For each RESCHEDULE case, a valid on-call appointment was first created against a confirmed usable Morning window in the local stub. The unresolved row was then added; the request log was cleared before the tested operation. Every tested CREATE/RESCHEDULE returned handoff; there was no subsequent owner POST other than any token exchange. The matrix exercises both whole-scope and post-time-selection exits. No real owner data was read or written.

In a mixed department with matches, existing aggregate behavior publishes the matches, not every internal doctor fact. Thus on-call handoff facts are correctly excluded from the returned bookable list; the plan's “regular facts plus on-call handoff” should not be read as requiring publication of nonmatches alongside positive candidates. A department without matches can publish the handoff facts.

Fact 1 fits one source selection in `_future`: on-call uses `()`; regular/visiting validates and reads the profile's usual schedule. Actual reader exceptions still exit before policy, and deliberate absence is not a fabricated successful profile. No new profile fetch or synthetic schedule is required. No-slot actionable on-call sessions necessarily have both bounds, so the ordinary TIME_NOT_VERIFIABLE branch cannot apply to them; unresolved rows are consumed as handoff first.

## 3. Complete existing-test inventory and suite output

| Existing function | Cases |
|---|---:|
| `tests/test_availability.py:116` — `test_on_call_doctor_requires_callback_regardless_of_board_status` | 1 |
| `tests/test_availability.py:264` — `test_working_hours_on_call_uses_the_full_callback_result` | 2 (ID/name) |
| `tests/test_availability.py:518` — `test_today_on_call_by_name_needs_no_board_read` | 1 |
| `tests/test_availability_policy.py:106` — `test_on_call_is_callback_even_when_board_says_in` | 2 (today/future) |
| `tests/test_availability_policy.py:154` — `test_department_rollup_and_counts_do_not_list_callback_as_bookable` | 1 |
| `tests/test_booking.py:107` — `test_on_call_and_failed_profile_never_reach_a_write` | 1 |
| `tests/test_server.py:134` — `test_tool_schemas_match_the_pinned_snapshot` | 1 |
| `tests/test_server.py:142` — `test_the_whole_journey_over_http` | 1 |

The two generically named behavioral tests contain on-call fixtures/actions. The generic schema test detects the new output enum. No unrelated ordinary-doctor test failed, including the six D-7 labelled-row regression functions.

Fresh unchanged-code baseline:

```text
$ make test-fast
All checks passed!
599 passed, 11 deselected, 2 warnings in 31.71s
```

Full hermetic in-memory C-8 run (`PYTHONPATH=dev uv run python -`, then `pytest.main` with `-m "not e2e and not external"`):

```text
10 failed, 589 passed, 11 deselected, 3 warnings in 30.59s
```

All ten failures were the old expected outcomes or the unchanged schema snapshot above. No test file was modified to hide them. Two warnings were existing Authlib deprecations; the extra warning was pytest's assertion-rewrite warning for already imported anyio, caused by running service probes before pytest in the same process. It was not an application failure.

## 4. Phase confirmation

| Phase | Assessment |
|---|---|
| 2b, ≤8 files | Reader-only probe below confirms the successful-read policy remains callback until 3a-2; the injected 500 already becomes COULD_NOT_CHECK and needs both outcome/path updates at `test_availability.py:518–523`. The successful-name control and WORKING_HOURS shortcut are compatible. Slot fixtures/expected added paths still land through the planned transport work. |
| 3a-1, 6 files | Final enums/output fields/defaults/descriptions, prompt, pack, snapshot and VOICE tables can publish without activating D-8. Existing constructors supply the required start/end fields; nullable does not make them optional. Added defaulted fields do not require the new formatter behavior yet. Existing behavior assertions stay on the old path; generated schema/VOICE tests use the newly published surface. |
| 3a-2, 7 files | Policy, availability mapping, output formatting and the four assigned test files cover D-8 activation, both booking handoff checks and the HTTP journey expectation. `src/booking.py` already handles Handoff, so it is not an extra file here. No schema change is needed. |
| 3b, 8 files | Remaining time/block gate behavior, returned slot formatting and session normalization use the previously published surface. Its file list remains sufficient. |

Reader-only process-local 2b experiment, without slots implemented:

```text
Successful read, old policy:
  CALLBACK_REQUIRED ON_CALL_DOCTOR ['/doctors', '/availability']
Injected board 500:
  COULD_NOT_CHECK BOARD_UNAVAILABLE ['/doctors', '/availability']
WORKING_HOURS shortcut:
  CALLBACK_REQUIRED ['/doctors']
```

The additional `/slots` path belongs to the planned 2a/2b transport integration; these outputs isolate the removal of the on-call shortcut. This review verifies dependencies and existing constructors, not future commits that do not exist. Implementation must still run `make test-fast` for each commit and compare the full generated schema after every commit from 3a-1. No later phase requires an additional schema element for the R11 corrections.

## 5. Remaining wording corrections and severity

**Blocking:** none found in this confirmation scope.

**Should change while preparing implementation; no new design decision required:**

- **Plan:194** still says the future named scope adds only unlabelled CALLBACK_REQUIRED rows. Make it say **unresolved** (callback or handoff), consistent with the explicit rule at :182 and :233. Literal callback-only filtering would reintroduce the already-resolved on-call named-scope omission; :182 is the authoritative definition for implementation/tests.
- **Plan:38,140,198,212 and generic UNKNOWN test wording** retain “callback/no exception” prose. Qualify it with “ordinary doctors; on-call uses C-8,” or say unresolved where both apply. D-8 at :40 explicitly supersedes the general callback result; no status-precedence change is requested. The historical “ON_CALL always callback” row at :41 is already labelled superseded and can remain historical.
- **Plan:190–193** should explicitly refer to the regular/visiting profile path and C-8's source exception. This avoids reading the generic missing-profile/no-schedule exits before the on-call source condition.
- **Plan:199,234** “WORKING_HOURS unchanged” means normal-hours presentation/department aggregation, not the on-call decision. Qualify that wording with D-8.
- **Plan:331** currently says WORKING_HOURS, including the on-call shortcut, makes no profile read. Regular/visiting WORKING_HOURS needs a profile (`src/schedule_reader.py:87`); ID-only on-call also reads the profile to discover attendance type. Only the already-known on-call summary shortcut skips it. All WORKING_HOURS paths avoid board/slots/capabilities as previously specified. Correct the sentence rather than removing required profile retrieval.

The explicit C-8 facts, both C-6 handoff checks, corrected rank, test inventory and phase split now provide a coherent implementation direction. The residual sentences should be aligned with those rules; they do not require another architecture review round.

No code/test files, snapshot or existing plan were changed. No Docker/process-e2e/external/voice-latency run, owner API call, Azure operation, push, merge or deployment occurred. Existing untracked plan, impact document, saved evidence and `temp/` were preserved. Only this report is committed.

**Verdict: ready to build — apply the explicit R11 rules and align the leftover wording listed above during implementation preparation.**
