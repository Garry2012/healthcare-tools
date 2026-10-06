# Opus review: manage_booking against real-world scenarios, 6 October 2026

**Scope:** `manage_booking` on `main` at `36336aa` (deployed canary image): `booking.py`, the booking path of
`availability_policy.py`, `ops_client.py` writes, `tools.py` registration, `context.py` headers, against the
pinned contract `manoj-openapi-20260930.yaml`.

**Method:** 40 caller scenarios run through the real MCP server (streamable HTTP, trusted headers, gateway
bearer) against the in-process development stubs, with the facility clock fixed per scenario. Scratch harness
only (`/tmp/mb/`); no repository code, tests or deployment changed. Stub behaviour follows the pinned contract
except where noted.

## Verdict

The write discipline is solid: confirmation, call/operation context, idempotent replay, uncertain-write
handling, caller authority and the neutral not-found all behave correctly. **Three real-world gaps** remain;
two are common caller situations.

| # | Severity | Finding |
|---|---|---|
| B-1 | Minor (downgraded) | Rescheduling an appointment dated **before today** skips the schedule policy entirely. **Accepted by Garima, 6 Oct: no change.** Reachable only if the agent lists with a past `fromDate` and then skips or misuses availability |
| B-2 | Minor (downgraded) | A **preferred time that has already passed today** is accepted and recorded. Needs an agent mistake (for example copying the session start); layer-1 fix (refuse a time before now today, no schema change, no latency) under discussion; Manoj's slot work may supersede it |
| B-3 | Important (decision) | A **chosen session is validated but never recorded**; a session-only request reaches the desk as date-only. **Garima, 6 Oct: session-only requests are not acceptable; the voice agent must always take a specific time.** No tool change: waiting for Manoj's slot work |
| M-1 | Minor | Owner rejection `fields` use Manoj's names (`mobile`), not the tool's argument names |
| M-2 | Minor | Cancelling an already-cancelled appointment returns `CONFLICT`/`TRANSFER_DESK` |
| G-1 | Pending decision | Morning ended + Evening open still forces `SESSION_REQUIRED` (unchanged, known) |

## Findings

### B-1 (important): reschedule of a past appointment bypasses the policy

**Scenario:** the caller missed yesterday's appointment with an ON_CALL doctor and asks to move it to next
Monday.

**Observed (S11):** `NOTED`, the appointment is changed to 2026-10-05 with the ON_CALL doctor; no callback.
The same request for a future appointment correctly returns `CALLBACK_REQUIRED`/`ON_CALL_DOCTOR` (S12).

**Root cause:** `booking._reschedule_gate` finds the current appointment with `find_appointments(mobile)`
and no `from`. The contract defaults `from` to **today**, so an earlier appointment is not in the list, and
`current is None` returns `None` ("preserve the owner's neutral NOT_FOUND"), which lets the write proceed
**without** the schedule gate. The owner then reschedules it. The same bypass admits a non-working day, a
cancelled or ended session, or `TIME_OUTSIDE_SESSION`.

**Fix where the rule lives (`_reschedule_gate`):** look the appointment up with an explicit `from` that covers
past appointments (contract allows any date), and **never write when the current appointment cannot be found**:
return `NOT_FOUND` instead of proceeding unchecked. Test: past ON_CALL appointment → `CALLBACK_REQUIRED`, no
POST `/reschedule`; past REGULAR appointment to a non-working day → `NOT_AVAILABLE`/`NOT_USUAL_DAY`, no POST.
Open question for Manoj: may a past appointment be rescheduled at all?

### B-2 (important): a time that has already passed today is accepted

**Scenario:** at 10:30 the caller says "can I come at 9:15?" (Meera's Morning session is 09:00–11:00, IN).

**Observed (S3):** `NOTED` with `expectedTime: 09:15` for today.

**Root cause:** today's window check compares only the session **end** with now (`_window`); the
`preferredTime` check in `decide_booking` uses the session start and end, never the facility time. A session
that is still open admits any time inside it, including times already gone.

**Fix where the rule lives (policy):** for today, the bookable window of a session starts at
`max(session start, facility now)`. A preferred time before now is outside the window and returns the existing
`NOT_AVAILABLE`/`TIME_OUTSIDE_SESSION` with alternatives; no new reason or schema change. `decide_booking`
needs the facility `now` (it already reaches `decide_doctor`). Tests: 10:30, preferred 09:15 →
`TIME_OUTSIDE_SESSION`, no write; preferred 10:45 → `NOTED`; future dates unaffected.

### B-3 (important, needs a decision): the chosen session is not recorded

**Scenario:** the caller wants Dr Meera "this evening" and gives no time. The agent sends `session: "Evening"`.

**Observed (S1, S2):** `NOTED`; the stored appointment has the date and doctor only (`expectedTime` null, no
session). The desk cannot tell Morning from Evening. The session survives only if the agent writes it into the
call summary.

**Root cause:** Manoj's `AppointmentCreate` and reschedule bodies have **no session field**; `expectedTime` is
the only time-of-day field. MCP validates `session` against the policy and then has nowhere to send it.

**Options (Garima to choose):**
1. Ask Manoj to add an optional `session` to create and reschedule (cleanest; contract change).
2. Require a `preferredTime` whenever the doctor has more than one session that day (tool refuses
   session-only requests in that case; the agent asks for a time, matching the earlier decision that the agent
   asks for a time within the chosen slot).
3. Accept it and rely on the call summary (linked by `callId`), documenting that the appointment record is
   date-level only.

### M-1 (minor): owner field names leak into `fields`

**Observed (S17):** owner `400 VALIDATION_FAILED` for `mobile` returns `fields: ["mobile"]`. The tool argument
is `patientMobile`; the agent cannot map it. Other pairs: `expectedTime`→`preferredTime`,
`newExpectedTime`→`newPreferredTime`, `reason`→`reasonVerbatim`. **Fix in `booking._failure`:** translate owner
field names to tool argument names; drop names with no tool equivalent (for example `callerMobile`, `callId`).

### M-2 (minor): already-cancelled appointment

**Observed (S13b/c):** cancel again, or reschedule a cancelled appointment → `CONFLICT`/`TRANSFER_DESK`,
`STATE_CONFLICT`. Safe, but a simple "it is already cancelled" becomes a desk transfer. LIST already returns
`status: CANCELLED`, so the agent can avoid it. The stub returns 409; **confirm Manoj's real response**
(409, or 200 with the unchanged record) before changing anything.

## Scenarios that behave correctly

| Area | Scenarios |
|---|---|
| Today, live board | Two open sessions, time in Evening → `NOTED` (S5); time in the gap → `TIME_OUTSIDE_SESSION` + open alternatives (S6); ended session chosen → `SESSION_ENDED` + Evening offered (S6b); all ended → `SESSION_ENDED` (S6c); NOT_CONFIRMED session → `CALLBACK_REQUIRED` (S7); cancelled doctor → `NOT_AVAILABLE`/`CANCELLED` (S9) |
| Future, usual schedule | ON_CALL → `CALLBACK_REQUIRED` (S8); Sunday → `NOT_USUAL_DAY` (S10); time between usual sessions → `TIME_OUTSIDE_SESSION` with both sessions (S10b); past date → `PAST_DATE` (S10c); unknown doctor → `NOT_FOUND`, no write (S10d) |
| Reschedule / cancel | Future ON_CALL → callback (S12); to a non-working day → `NOT_USUAL_DAY` (S12b); doctor change → `DOCTOR_CHANGE_UNSUPPORTED` (S12c); cancel → `CANCELLED` (S13a); another caller's appointment → neutral `NOT_FOUND` (S14); new date in the past → `PAST_DATE` (S21) |
| Idempotency | Second booking reusing one operation id → `CONFLICT`/`IDEMPOTENCY_CONFLICT` (S15); exact retry → same appointment, one record (S16); owner commits then 500 → `UNCERTAIN`, same-key retry → `NOTED`, one record (S24) |
| Identity | Number withheld, foreign number, unverified → `IDENTITY_UNAVAILABLE` (S18, S19, S19b); LIST default and `fromDate` filter (S20) |
| Validation | `24:00` → `preferredTime` refused (S22); missing operation id → `OPERATION_CONTEXT_MISSING` (S23); 11-digit mobile → `patientMobile` refused (S23b); unknown argument → rejected before the tool runs |

## Notes, no change requested

- **G-1 (S4):** at 12:00 Morning has ended and Evening is open; without a session or time the tool returns
  `SESSION_REQUIRED` listing both. Still awaiting Garima's decision.
- **Duplicate requests:** a second CREATE for the same patient, doctor and date with a new operation id makes a
  second record. MCP keeps no state by design; whether Manoj de-duplicates is undocumented.
- **LIST includes CANCELLED** appointments by default; the agent can filter with `status`.
- **Department-level appointments** created by staff have no `doctorId`; rescheduling one by voice returns
  `COULD_NOT_RECORD` with detail `MALFORMED`. Safe; the detail name is misleading.
- **Latency not proven:** CREATE performs a schedule read and the write inside one 0.30 s write deadline;
  RESCHEDULE adds an appointment lookup. Only a live measurement can show this fits.

## Recommendation

Fix B-1 and B-2 before callers can reschedule or book same-day by voice; both are root-cause changes at the
rule's home with no schema change. Decide B-3 (option 1 needs Manoj). M-1 and M-2 can follow.
