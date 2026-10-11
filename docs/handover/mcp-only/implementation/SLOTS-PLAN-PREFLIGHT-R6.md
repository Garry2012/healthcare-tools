# Slots plan revision 6 — delta pre-flight

Reviewed 8 October 2026 against code HEAD `21c135115834c126ade5c0791a8867a0d0e2b1d7`.
Plan: `SLOTS-PLAN.md`, revision 6, SHA-256 `6076c752561ef63831cf520413497452fb43dc6180ebf21a6bfaba76a08e9067`.
Scope: revision 6 changes and the R5 finding rows only. D-1–D-6 are accepted, including the clarified D-2 label rule and D-6 time scope. No production code or tests changed; no live owner requests.

**Result:** the earlier named/unlabelled booking and missing-hours formatting fixes are workable. One other UNKNOWN scope path still permits a write and needs a plan correction. This is not a request to reverse the approved passed-time decision.

References below use `plan` for `SLOTS-PLAN.md`, `src` for `services/mcp/src/frontdesk_mcp/`, and `tests` for `services/mcp/tests/`.

## 1. Finding-by-finding assessment

| R5 finding | Status | Evidence and conclusion |
|---|---|---|
| B1(a): a supplied name could book through an unlabelled block | **Resolved** | Plan:200–205 remembers the containing block's session and compares its normalized label before Write. This closes both the sole unlabelled open row and real Morning plus unlabelled open row cases. HEAD retains these rows at `src/availability_policy.py:219–220`; its current booking path reaches Write in both probes. The new step 5 rejects both as TIME_OUTSIDE_SESSION. UNKNOWN still wins before that check: a named Morning with an unlabelled UNKNOWN already returns callback from the whole-scope check (`:225,285–286`); an unnamed time-matched Morning with unlabelled UNKNOWN returns callback at `:296,306–310`. Plan:305,308 requires policy and CREATE/RESCHEDULE no-write coverage. |
| B1(b): passed time inside a bounded blockless UNKNOWN window | **Resolved for the original finding; another scope gap remains** | Plan:33,198,305 explicitly chooses TIME_OUTSIDE_SESSION for the bounded past-time mixed-day example and callback for unbounded uncertainty. HEAD's `_contains_time:273–278` and no-match branch `:297–301` implement that original example. No change to that ruling is requested. However the **matched** branch drops a labelled, unbounded UNKNOWN that could contain the time. See blocking R6-B1. |
| B2: one-day refusal without hours could not serialize | **Resolved** | Plan:177,188,255–256 explicitly allows future null start/end and today's existing nullable board times. `src/outcomes.py:60–67` forwards bounds without parsing them; `src/availability.py:39–48` formats all facts. Process-local nullable-model probes serialized both UNKNOWN and CANCELLED through those real formatters for both bases. `_contains_time:273–274` safely returns false for absent bounds; the resulting scope issue is R6-B1, not a null parsing exception. One-day metadata must be forwarded in 3a as specified; see section 3. |
| S1: owner SLOT_FULL falsely implied another open time | **Resolved** | Plan:269 distinguishes local checked alternatives from an owner race, requires a new availability check before offering another time after an owner rejection, and forbids inferring alternatives from the code. Plan:308 pins no alternatives on the definite owner rejection. No new retry policy or schema is needed. |
| S2: legacy future output rows and NO_USUAL_SCHEDULE wording | **Resolved** | Plan:187 states scope when nonempty, otherwise all rows. This reproduces `src/availability_policy.py:235–250`, including no-profile/no-usual early exits. A 60-case no-slot comparison matched the **entire** DoctorDecision, including output rows and alternatives. Plan:304 now distinguishes no day facts from a one-day UNKNOWN. Read plan:183's other-weekday statement subject to the explicit output selection at :187. |
| S3: shared blank-session type and boundary coverage | **Resolved** | Plan:212 places SessionChoice in outcomes, already imported by availability and booking (`src/availability.py:10–11`, `src/booking.py:22–23`). Outcomes imports contract, knowledge_contract and policy, none of which imports these services: no cycle is introduced. Unchanged `src/tools.py:117–119,149–154` constructs the request models. Process-local substituted models preserved each model schema and the complete registered MCP schema; calls through the actual registered tools delivered None to both service boundaries. Plan:306 and phase 3b include permanent direct-model and MCP coverage. |

## 2. Blocking R6-B1 — matched time drops a labelled UNKNOWN with missing bounds

**Location:** plan:198 (“unchanged code”); `src/availability_policy.py:293–301`, especially :296.

**Concrete caller outcome:** today, at 10:00, a caller selects 10:30 without naming a session. There is an open Morning block from 10:00 to 12:00, plus a distinct session labelled Extra whose status is UNKNOWN, with no blocks and no supplied start/end. The second session has no facts excluding 10:30. Under the approved D-6 wording, it could be the session containing the caller's time and requires callback.

Instead, the proposed reused flow does this:

1. Whole-day combination sees an open candidate and UNKNOWN; without a named session it produces APPOINTMENT_REQUEST with a choice (`policy:189–198`).
2. Morning matches 10:30. Extra does not, because `_contains_time` returns false when either bound is missing (`:273–274`). Its blockless evidence still uses that fallback under plan:198.
3. The matched branch retains additional **unlabelled** rows only (`:296`). Extra has a label and is discarded. The unbounded fallback at :298 runs only when **nothing** matched.
4. Step 4 sees only Morning. Step 5 finds its OPEN block and permits Write. There is no name mismatch to stop it.

This is not an out-of-hours or passed-time example. The caller's time is still ahead, and the UNKNOWN row has insufficient hours to rule it out. Unique slot labels/non-overlapping blocks do not reject this payload: Extra has no blocks to overlap. The same hole applies to a future one-day UNKNOWN session with no blocks, now explicitly representable under R6.

Actual HEAD probes using constructed SessionDecision facts:

```text
Matched Morning + labelled blockless UNKNOWN (None, None) -> Write None
Matched Morning + labelled blockless UNKNOWN ('10:00', None) -> Write None
Matched Morning + labelled blockless UNKNOWN (None, '12:00') -> Write None
Matched Morning + unlabelled UNKNOWN -> Callback BOARD_UNKNOWN
Unmatched time + labelled unbounded UNKNOWN -> Callback BOARD_UNKNOWN
Past time + bounded UNKNOWN + Evening open -> NotAvailable TIME_OUTSIDE_SESSION
Named Morning + unlabelled UNKNOWN -> Callback BOARD_UNKNOWN
Future matched + labelled blockless UNKNOWN -> Write None
```

These execute the **current scope flow**, not a slots implementation. The plan's new block-membership branch would still match Morning, and its blockless fallback would still exclude Extra, so the lost UNKNOWN persists into the new final block check.

Minimal reproduction from `services/mcp` (no service requests):

```python
from datetime import datetime
from zoneinfo import ZoneInfo
from frontdesk_mcp import availability_policy as p, contract

now = datetime(2026, 10, 1, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
doctor = contract.DoctorSummary(id="d", name="Doctor", active=True,
                               departments=[], attendanceType="REGULAR")
facts = p.DoctorFacts(doctor)
open_row = p.SessionDecision("Morning", p.Basis.LIVE_BOARD, "IN",
    p.Decision.APPOINTMENT_REQUEST, None, "10:00", "12:00")
unknown = p.SessionDecision("Extra", p.Basis.LIVE_BOARD, "UNKNOWN",
    p.Decision.CALLBACK_REQUIRED, p.Reason.BOARD_UNKNOWN, None, None)
rows = (open_row, unknown)
kind, reason, choice = p._combine(rows, False)
decision = p.DoctorDecision(facts, kind, reason, p.Basis.LIVE_BOARD,
                           rows, choice, (open_row,))
result = p.decide_booking(decision, session=None, preferred_time="10:30", now=now)
assert isinstance(result, p.Write)  # reproduces the unsafe proposed reuse
```

**Required plan change:** define how slot-enabled time selection retains unresolved blockless UNKNOWN rows whose missing bounds do not exclude the time, including when another session matches. Changing only `_contains_time` as currently specified is insufficient. Keep this in the existing scope flow; do not add a second booking matrix. Preserve the approved bounded passed-time result and the no-slots legacy path.

Required red-first coverage: matched open block plus a differently labelled UNKNOWN with neither bound, each single missing bound that could contain the time, future one-day UNKNOWN, and the unlabelled controls; policy plus CREATE and RESCHEDULE must prove callback and no write. Keep the existing out-of-scope bounded UNKNOWN tests to prove unrelated sessions do not force callback. This fits the files already assigned to 3b and needs no schema change.

## 3. Null bounds, formatting and schema checks

Repository searches for bound reads and parsing found scheduling consumers in `availability_policy.py` and forwarding in `outcomes.py`. The contract's usual-schedule hours stay non-null; the output widening does not widen owner input validation.

- `_window:181–185` already handles an absent end.
- `_contains_time:272–278` guards both missing bounds before parsing.
- Booking's no-match branch `:298` recognizes either missing bound; its legacy time-verification branch `:314–315` also guards them. R6-B1 concerns scope retention, not unsafe parsing.
- `session_out:60–67` and `doctor_out:39–48` pass bounds straight through. Making UsualSessionOut fields nullable is sufficient to remove the formatting failure. Today BoardSessionOut is already nullable.
- **Required implementation detail already implied by the plan:** the formatter must emit `oneDay=true`, the slot status and `onRequestedDate=true` for dated one-day facts in phase 3a. HEAD computes `requested.weekday in s.days` at `outcomes.py:66`, which would be false for `days=()`. Merely widening start/end and relying on default metadata is insufficient. Plan:188,255 specifies the correct target; no further product decision is missing.
- The VOICE table test (`tests/test_server.py:409–439`) compares parsed schema shape, not string-only assumptions. It accepts nullable union shapes once the table and snapshot are updated together. Keep start/end **required but nullable** unless the plan explicitly changes their defaults. Both availability and booking reference UsualSessionOut, so both tables must be regenerated in 3a.

Process-local model probes (no files changed):

```text
USUAL_SCHEDULE UNKNOWN : doctor_out/session_out serialize null bounds; membership safely false
USUAL_SCHEDULE CANCELLED : doctor_out/session_out serialize null bounds; membership safely false
LIVE_BOARD UNKNOWN : doctor_out/session_out serialize null bounds; membership safely false
LIVE_BOARD CANCELLED : doctor_out/session_out serialize null bounds; membership safely false
R6 C-5 no-slot full DoctorDecision equality: 60/60 (includes sessions, alternatives, reasons).
AvailabilityRequest : blank -> None; non-string/long rejected; model schema identical
BookingRequest : blank -> None; non-string/long rejected; model schema identical
Full registered MCP schema identical after process-local request-model substitutions: True
Unchanged registered MCP tools forward blank session as None through substituted request models:
[('availability', None), ('booking', None)]
```

The MCP boundary probe used the actual registered tools with service methods replaced in memory to capture the request; no owner calls occurred. The nullable probe isolates bounds; it does not implement or certify the future one-day metadata or slots behavior. Permanent implementation tests remain required.

## 4. Phasing assessment

| Phase | Exact footprint | Assessment |
|---|---|---|
| 3a | `src/availability_policy.py`, `src/availability.py`, `src/outcomes.py`, `tests/test_availability_policy.py`, `tests/test_availability.py`, `src/prompt.py`, `tests/contracts/mcp-tools.snapshot.json`, `src/packs/healthcare.json`, `docs/handover/VOICE-TEAM.md`: **9 files** | Viable as a green standalone commit after 2b. Includes nullable hours, one-day formatter metadata, all final defaults/descriptions/enums and VOICE rows. Appointment defaults allow booking formatting to wait until 3b. The unchanged schema/VOICE tests derive expectations from models and snapshot and need no test-file edit merely to allow the new shapes. New slot-enabled booking behavior remains deferred; no deployment of this intermediate state. |
| 3b | `src/availability_policy.py`, `src/booking.py`, `src/availability.py`, `src/outcomes.py`, `tests/test_availability_policy.py`, `tests/test_booking.py`, `tests/test_availability.py`, `tests/test_server.py`: **8 files** | Viable after 3a, including R6-B1 and its policy/service tests. SessionChoice belongs in outcomes; no tools.py change or new module required. Outcomes changes here are input normalization and remaining booking formatting only, with no output shape/default/description change. |

The new fixes do not require any public schema beyond 3a. D-1 remains achievable: compare the complete generated surface after every subsequent commit. This is a dependency assessment, **not** a claim that future implementation commits have already passed tests. No changes to resolved phase assignments are proposed.

## 5. New issues and verification

- **Blocking:** R6-B1, labelled blockless UNKNOWN dropped when another session matches the time.
- **Should change:** none additional in the R6 delta.
- **Nit:** none requiring another design round. The one-day metadata forwarding and both VOICE tables are implementation checkpoints within the existing plan.

Fresh baseline verification:

```text
$ make test-fast
cd services/mcp && uv run ruff check . ../../deploy && uv run pytest tests -q -m "not e2e and not external"
All checks passed!
599 passed, 11 deselected, 2 warnings in 32.52s
```

The warnings are the existing Authlib deprecations. Read-only code inspection and process-local probes above supplemented the suite. No slots code exists yet. No Docker build, process-e2e run, live Manoj request, external-owner test, deployment, Azure change, ContextForge refresh or voice latency measurement was performed. Untracked plan, impact document, saved live evidence and `temp/` were preserved. This report is the only file to commit; no push, merge or deploy.

**Verdict: needs revision 7 — R6-B1 only: preserve a potentially relevant labelled, blockless UNKNOWN when another session matches the requested time, with policy and CREATE/RESCHEDULE no-write tests.**
