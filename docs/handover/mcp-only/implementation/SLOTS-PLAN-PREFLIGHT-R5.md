# Slots plan revision 5: delta pre-flight

Reviewed 8 October 2026 against HEAD `bcc6cf11a56cb56135b14bba7554d21617ab12e7`. **Verdict: needs revision 6**, for the remaining booking-scope gaps (R5-B1) and representation of one-day refusal facts (R5-B2). Most revision 4 findings are resolved.

This pass checks only the requested revision 5 changes. D-1–D-6 are fixed, including UNKNOWN-first reconciliation. No implementation, tests, other documents, external API calls, push, merge or deployment were performed. Only this report is committed. The current fast suite was run against local fixtures.

Plan reviewed: `docs/handover/mcp-only/implementation/SLOTS-PLAN.md`, SHA-256 `f3e4fe8c33f493ae574e4ca502ace4e58280143f3ab84d143bc6724f5d98d325`. The background and saved live-capture hashes remain those recorded in the R4 report. Those untracked files and `temp/` are preserved.

References: `plan:` denotes revision 5; `src/` denotes `services/mcp/src/frontdesk_mcp/`; `tests/` denotes `services/mcp/tests/`. “Resolved” refers to the plan, not an implemented feature. Probes below were disposable Python processes; they did not modify repository code.

## 1. Finding-by-finding assessment

| R4 finding | Status | Evidence |
|---|---|---|
| B1 cancellation/UNKNOWN contradiction | **Resolved** | D-6 and plan:132 put UNKNOWN first in both response orderings. Stale reason is tied specifically to a stale UNKNOWN board row. This fits the existing status-first handling at `src/availability_policy.py:210–214` without changing the fixed decision. |
| B2.1 FULL changed with another open session | **Resolved for policy decisions** | Plan:154,192–200 deliberately removes refinement: an entirely full session is NO_OPEN_SLOT; a full block within a session that still has open blocks is SLOT_FULL. The existing whole-scope and selected-scope refusals at `policy:289–290,306–312` now agree. Owner-write SLOT_FULL still needs the wording correction R5-S1. |
| B2.2 refinement overrode session flag | **Resolved** | No refinement remains. Session flag false becomes NO_OPEN_SLOT at plan:147 and is returned before the final block step. Retaining full block evidence does not authorize a write or override that refusal. |
| B2.3 unlabelled UNKNOWN lost beside an open match | **Resolved for the reported matched-time case** | Reusing `policy:294–297,306–310` retains the unlabelled row when a Morning time matches a Morning session. The exact open Morning + unlabelled UNKNOWN counterexample returns callback. The no-match fallback has a related remaining edge case, R5-B1(b). |
| B2.4 blockless UNKNOWN became TIME_OUTSIDE_SESSION | **Partly resolved** | Plan:194's window fallback preserves a blockless UNKNOWN afternoon when the chosen time is inside its still-future window. The same `_contains_time` also applies `max(start, now)` (`policy:276–278`), so it can exclude an UNKNOWN window whose requested time has already passed. See R5-B1(b). |
| B2.5 unique session selection / blank session | **Partly resolved** | A-2 guarantees unique blocks in the raw slot plan. The BeforeValidator can preserve the schema. But a supplied name still does not have to match an unlabelled bookable session retained by `_today:219–220`; C-6's reused flow can write through it. See R5-B1(a). |
| B3 future selection discarded reasons | **Partly resolved** | Plan:167–185 separates day facts, scope and alternatives and combines the actual scope. This fixes loss of UNKNOWN/CANCELLED decisions and preserves no-slots decision/reason behaviour, including nullable labels. Empty-block one-day refusal rows cannot yet be formatted through the prescribed output model; R5-B2. Preserve the conditional legacy output list as R5-S2 describes. |
| S1 failure mapping / inconsistent joins | **Resolved for the declared validation scope** | Plan B-6 makes the helper detail-only and explicitly handles new stages before generic Rejected. A-2 puts slot-plan inconsistencies on the existing Malformed/stage-slots path. Old profile/lookup rejection and AUTH anchors are retained. Duplicate board rows are now explicitly tolerated and no longer declared malformed; that is a deliberate design change, not a missing policy exception. |
| S2 purpose guard / cache guarantee | **Resolved** | B-2/B-5 explicitly exclude WORKING_HOURS and state the real TTL/LRU behaviour, including concurrent cold reads. This fits `src/cache.py:21–38` and `src/schedule_reader.py:98–136`. No lifecycle or single-flight mechanism is needed. |
| S3 unread projection / legacy ended guard | **Resolved** | Plan:125–128 distinguishes None from checked-empty. Plan:143–152 retains the legacy ended-window rule only without slot evidence. Presentation needs no clock or duplicate rule. |
| S4 defaults / descriptions in 3a | **Resolved for the listed fields; final surface pending R5-B2** | Section 6 now fixes defaults and the usualSessions description in 3a. `AppointmentOut.slotTime=None` permits the unchanged constructor at `src/booking.py:86–89` until 3b. The new one-day refusal shape must also be settled before the single publication. |

## 2. Booking-flow checks

### What reuse fixes

The new structure is simpler than revision 4's separate matrix. It reuses the actual scope combination, keeps callback before write, and makes full-session policy refusals consistent. Local probes constructed the relevant SessionDecision facts and exercised **HEAD's existing scope/refusal flow**; they did not execute a new slot implementation:

```text
All-full session, alone -> NotAvailable NO_OPEN_SLOT
Same all-full session plus other open session -> NotAvailable NO_OPEN_SLOT
Flag-false session (same NO_OPEN_SLOT decision) -> NotAvailable NO_OPEN_SLOT
Open morning plus unlabelled UNKNOWN -> Callback BOARD_UNKNOWN
UNKNOWN afternoon without blocks, known window -> Callback BOARD_UNKNOWN
```

Thus the original all-full, false-flag, matching Morning/unlabelled UNKNOWN and afternoon-window examples are covered by reuse. A session with both FULL and OPEN blocks remains APPOINTMENT_REQUEST until the final chosen-block step, where SLOT_FULL is coherent. All-slot-disabled behaviour can stay on the existing path except for the explicitly approved blank-session normalization.

### Blocking R5-B1 — two scope cases are still not covered by “unchanged code”

**(a) A named session can use an unlabelled open block.** `_today:219–220` intentionally retains unlabelled rows even under a named request, and `decide_booking:293` only performs time-based narrowing when `not session`. If the only row is an unlabelled IN session and the caller supplies `session="Morning"`, scope contains that unlabelled row, combination succeeds, and the proposed final block lookup finds its OPEN block. Nothing compares the row's normalized label with Morning. The plan's statement that the final lookup will be empty for a mismatched name is therefore false for this case.

Actual HEAD probe:

```text
HEAD named Morning, only unlabelled IN row: APPOINTMENT_REQUEST labels= [None] Write
```

With a matching enabled-slot payload, the planned final block check also succeeds; it does not fix the name mismatch. This violates fixed D-2. It also occurs with a genuine Morning row plus an unlabelled open row when the chosen time belongs only to the latter.

**Required revision:** distinguish retaining unlabelled facts for refusal safety from accepting them as the caller's named target. Require the final block's session to satisfy the supplied non-blank label before Write, while retaining unlabelled UNKNOWN callback priority. Use the existing normalized-label rule; do not scope away unresolved rows to make the match succeed. Add CREATE and RESCHEDULE no-write tests for a name plus an unlabelled open block, alongside the existing unlabelled UNKNOWN cases.

**(b) The window fallback can still drop blockless UNKNOWN.** Plan:194 explicitly sends sessions without blocks through the existing window rule. That rule narrows today's start to facility now (`policy:276–278`). At 10:00, take an UNKNOWN session with a supplied 09:00–10:00 window and no blocks, an unrelated open Evening session, and chosen time 09:30 with no session name. The doctor-level decision initially has an available candidate. Time selection finds no match, both rows are bounded, and `policy:298–300` returns TIME_OUTSIDE_SESSION before combining the UNKNOWN row. The same effect is possible for a bounded unlabelled UNKNOWN row when no session matches the time.

Actual HEAD scope probe:

```text
UNKNOWN blockless earlier window, other session open -> NotAvailable TIME_OUTSIDE_SESSION
```

This is an inherited scope issue, not evidence that revision 5 already changed production. It matters because the new plan expressly reuses that branch and promises D-6 with no exception. The existing whole-scope callback check does not catch this mixed day.

**Required revision:** make the distinction between identifying the session containing the caller's time and checking whether that time is bookable explicit for slot-enabled evidence with no blocks. Preserve relevant UNKNOWN evidence before the time-eligibility refusal. Keep the legacy no-slot branch and its passed-time tests unchanged; this does not require reinstating the discarded eleven-step matrix. Add slot-enabled bounded/unbounded, labelled/unlabelled UNKNOWN tests with a past time and another open session.

## 3. Future and one-day sessions

The revised `_future` decision structure is implementable. For no-slot input, day sessions are the existing APPOINTMENT_REQUEST alternatives, so filtering day sessions by the existing future label comparison produces the same selected scope. Empty-profile, wrong-weekday and unmatched-label exits retain their meanings. Unlike today's rule, a nullable usual label is not retained under a different named future request. A local comparison of the literal r5 no-slot decision/reason rules against HEAD, covering six schedules, two dates and five label choices, produced:

```text
Literal r5 no-slots future decision/reason cases: 60/60 agree with HEAD (includes nullable labels)
```

This checks decisions/reasons, not a new implementation's complete serialized results. Formatting requires the distinctions below.

### Blocking R5-B2 — refusal-only one-day sessions have no defined serializable shape

Revision 5 correctly retains one-day UNKNOWN/CANCELLED facts even when they cannot be offered. A slot session is permitted to have an empty block list; neither A-2 nor the owner model gives it session-level start/end. For a future date, a slot-only UNKNOWN row therefore has no usual hours and no block bounds. C-5 puts it in the day scope and returns callback, but `availability.doctor_out:41` formats **every** `DoctorDecision.sessions` entry. `outcomes.session_out:65–67` constructs UsualSessionOut, whose start/end remain required strings (`outcomes.py:41–42`). Section 6 does not change those fields or define how to omit a refusal-only row from presentation while preserving its decision.

Actual formatter probe on that shape:

```text
Future one-day empty-block formatting rejects: [(('start',), 'string_type'), (('end',), 'string_type')]
```

**Required revision before 3a:** define the public representation of a one-day refusal with no bounds. Either make unknown bounds representable in the final schema, or explicitly preserve those facts in policy while specifying a response representation that does not attempt to format an invented schedule. Do not fabricate times or discard the callback/cancellation decision. Add a full service/serialization test for a future slot-only UNKNOWN with no blocks, including a profile whose usual schedule is on another weekday.

For **today**, BoardSessionOut already permits absent expectedTime/expectedEndTime, so the same empty-block row can be represented without a bounds change. However plan:175 says a slot-only row is “marked one-day,” while section 6 only adds `oneDay` to UsualSessionOut. State whether today's dated LIVE_BOARD presentation itself is the marker or whether BoardSessionOut will carry oneDay too. Fix that decision in 3a; do not discover an additional field after publication.

## 4. Should change — narrow wording and proof gaps

### R5-S1 — owner SLOT_FULL does not prove another time remains open

The new local **Reason** meanings are internally consistent after scope selection: NO_OPEN_SLOT means no open block in that session; locally detected SLOT_FULL means a selected FULL block while that session has an OPEN alternative. But plan:233 also forwards a definite owner-write rejection as detail SLOT_FULL. The owner may reject after concurrent bookings have taken **all** remaining seats; its error does not establish that another time is open. The response detail is the same wire string, so the blanket VOICE statement in section 6 (“SLOT_FULL … other times in the session are open”) is not universally true.

Keep the owner error mapping. Qualify the caller guidance: offer only supplied, checked alternatives; an owner SLOT_FULL rejection requires a fresh availability check before claiming another time is open. Do not recompute seats or infer alternatives from the error code. This is a documentation correction within the planned 3a publication, not a new error schema or retry policy.

### R5-S2 — preserve conditional legacy output, not just reason codes

Plan:181 says other-weekday usual rows remain in the output “unchanged.” HEAD does that only on a refusal with no selected session (`policy:247–248`); successful future requests return only selected day sessions (`:249–250`). With Morning on Monday and Evening on Tuesday, a successful Monday query currently returns only Morning, while a Monday request for Evening returns both rows and SESSION_NOT_USUAL. The new scope/alternatives structure can preserve this exactly, but the plan should say so. `tests/test_availability_policy.py:188–199` and `tests/test_availability.py:473–494` already pin the unmatched case; add a successful-output assertion as well.

Section 9's shorthand “no usual schedule + one-day open → offered, else NO_USUAL_SCHEDULE” also needs alignment with C-5: an existing one-day UNKNOWN fact should yield its callback reason, not be treated as **no day facts**. Reserve NO_USUAL_SCHEDULE for the stated absence case. This is wording/test-expectation alignment, not a new decision request.

### R5-S3 — identify the shared input type's home and cover both boundaries

The BeforeValidator design is feasible without changing input JSON schema. The validator must accept arbitrary raw input, normalize only blank strings to None and let existing Pydantic validation reject wrong types. Keep maxLength, default and descriptions as published. A local probe using the installed Pydantic and FastMCP versions returned:

```text
Pydantic alias schemas equal: True
FastMCP parameter schemas equal: True
Input str accepted= True
Input NoneType accepted= True
Input int rejected
Input list rejected
Input str rejected
```

The last input was a 41-character nonblank string; the first was spaces. This is a framework-level alias probe, not a modified registered production tool. Run the actual complete schema equality test after implementation.

No existing scheduling test supplies `session="   "`: repository search found blank **owner labels** at `tests/test_booking.py:122–132`, which are different and must remain unchanged. Existing None/named-session tests remain valid. Add new tests for AvailabilityRequest, BookingRequest and MCP calls for both tools, proving blank behaves like None for today and future. Do not claim existing test expectations must be rewritten. The current future blank argument returns SESSION_NOT_USUAL in a matching-day example; converting it to None intentionally returns APPOINTMENT_REQUEST.

Choose one home for the shared annotation. It is not named in the phase list. A small shared input module is an option; do not put duplicate validators in two services or introduce a dependency from a service into tools.py, which imports both services already. An existing lower-level module is also feasible if its responsibility fits.

## 5. Phasing delta

No need to revisit resolved phases 1a/1b/2a/4a/4b/5. The requested changed footprints remain under ten files. Future green commits are a dependency assessment, not something today's tests can certify.

| Phase | Exact files / assessment |
|---|---|
| 2b | `src/schedule_reader.py`, `src/availability_policy.py`, `src/availability.py`, `src/booking.py`, `tests/test_schedule_reader.py`, `tests/test_availability.py`, `tests/test_booking.py`, optionally `tests/harness.py`: **7–8**. Can be green with complete disabled-slot fixtures from 2a, new-stage handling before Rejected, and unchanged old-stage semantics. Plan-level validation belongs here; no policy failure enum is required. |
| 3a | Existing **9-file** assignment remains viable. The listed defaults permit `_appointment_out` to remain unchanged until 3b. Finalize R5-B2's representation, SLOT_FULL wording, one-day descriptions and blank-session input description here, together with the snapshot and VOICE tables. Otherwise the promise of no later schema change cannot be certified. |
| 3b | The supplied list has **8** files: `src/availability_policy.py`, `src/booking.py`, `src/availability.py`, `src/tools.py`, `src/outcomes.py`, `tests/test_availability_policy.py`, `tests/test_booking.py`, `tests/test_server.py`. It can fit the booking corrections and a shared validator without a schema change, but the type's home must be explicit. |

**Concrete corrected 3b list if a dedicated shared type module is chosen (10):**

1. `services/mcp/src/frontdesk_mcp/availability_policy.py`
2. `services/mcp/src/frontdesk_mcp/booking.py`
3. `services/mcp/src/frontdesk_mcp/availability.py`
4. `services/mcp/src/frontdesk_mcp/tools.py`
5. `services/mcp/src/frontdesk_mcp/outcomes.py` — formatting only
6. `services/mcp/src/frontdesk_mcp/inputs.py` — proposed new filename, shared session annotation only
7. `services/mcp/tests/test_availability_policy.py`
8. `services/mcp/tests/test_booking.py`
9. `services/mcp/tests/test_server.py`
10. `services/mcp/tests/test_availability.py`

This is an optional concrete allocation, not a file created by this review. Reusing a suitable existing module instead can reduce the count. No extra snapshot, pack, prompt or VOICE edit belongs in 3b: final descriptions must already land in 3a. Validator behaviour can change with an identical schema, as the local framework probe demonstrates. Compare the complete `make schema` result after every commit from 3a, not just enum or property names.

## 6. Validation and limits

Both saved real slot captures were rechecked for the new invariants: normalized labels are unique; block bounds/counts are valid; blocks are ordered and do not overlap within or across sessions. Adjacent endpoints are allowed by the half-open membership rule. Unique slot labels plus non-overlapping positive intervals makes `block_at` unique **in the raw slot plan**. Several board or same-weekday usual rows can still refer to the same slot session, so consume that unique block identity rather than treating joined copies as additional capacity.

```text
Capture 1: PASS numeric/order/unique-label/cross-session-overlap checks; 3 blocks
Capture 2: PASS numeric/order/unique-label/cross-session-overlap checks; 5 blocks
```

These validations cover the declared consumer invariants, not every conceivable inconsistency. G-14 remains explicitly designed around, not an owner answer. Duplicate board labels are tolerated by the revised plan, so they are not evidence of a missing Malformed branch.

B-6 remains compatible with the existing regression anchors: profile and appointment-lookup 400s (`test_booking.py:808–862`), board retry-after (`test_availability.py:100–113`, `test_booking.py:401–404`), AUTH (`test_booking.py:238–243`), malformed owner ID (`:682–692`), and directory failures. The plan explicitly puts slots/capabilities stage handling first in both services; code has not been changed yet.

Executed:

```sh
make test-fast
```

Actual output, progress dots omitted:

```text
cd services/mcp && uv run ruff check . ../../deploy && uv run pytest tests -q -m "not e2e and not external"
All checks passed!
599 passed, 11 deselected, 2 warnings in 31.91s
```

Warnings are existing Authlib deprecations. The current snapshot and VOICE-table tests passed. New slots code/tests do not exist yet. Docker builds, process-e2e suite, external owners, Azure, ContextForge and voice latency were not tested in this report-only pass. No public contract re-download or live API call was needed.

**Verdict: needs revision 6 — close R5-B1's named/unlabelled and blockless-UNKNOWN scope gaps, define R5-B2's one-day refusal representation before 3a, and incorporate R5-S1–S3. Fixed D-1–D-6 remain unchanged.**
