# Front-desk MCP tools: voice-team handover

Schema version: `2026-10-11.2`

This is the single authoritative handover for calling the front-desk MCP tools.
- **Part 1** explains how to use the tools safely.
- **Part 2** is the complete reference for every field and code.
- **The schema served by `tools/list` is authoritative.** If this document and `tools/list` ever disagree, `tools/list` wins.

**Contents**
- **Part 1, Using the tools:** 1 Status · 2 Connect · 3 Request context · 4 The tools · 5 Data between calls · 6 Reading a result · 7 What a result establishes · 8 Failures, retries and uncertainty · 9 Worked examples · 10 Acceptance scenarios · 11 Changes since `2026-10-06.1`
- **Part 2, Reference:** 12 Outcome codes · 13 nextStep codes · 14 Decision, Reason and Detail codes · 15 Schedule rules · 16 Field reference

# Part 1: Using the tools

## 1. Status

- **Three tools:** `get_doctor_availability`, `manage_booking` and `record_call_summary`. All data comes from the hospital's operational service, which is owned by Manoj's team.
- **Knowledge, symptom routing and emergencies** are not handled by these tools. They are handled through Stratum's separate ContextForge registration.
- **The canary** `mcp-demo-hospital-canary` runs schema `2026-10-11.2`, deployed on 12 October 2026 (revision `--0000005`, image `01b9dcc`).
- **Slots:** the hospital (Jayashree) has capacity slots switched on, so results normally follow the "with slots" rules. Slots are still decided per doctor and date (§15): a doctor-specific result for a doctor whose slot plan for that date is disabled follows the "without slots" rules.
- **Checking the served version:** `GET /ready` returns the served `schemaVersion`. ContextForge shows the schema from its last refresh of our entries, which may be older.

## 2. Connect

- **Endpoint:** streamable HTTP at `/mcp/`. The voice agent normally reaches it through the ContextForge virtual server `frontdesk-healthcare`. Its URL and scoped access come from the ContextForge owner.
- **The direct adapter URL** is `https://<mcp-host>/mcp/`. `GET /health`, `GET /ready` and `GET /dependencies` need no authentication.
- **Authentication: two calling paths, two different credentials.**
  - **Through ContextForge (the normal path):** the voice client sends its scoped ContextForge client token in `Authorization` to ContextForge. ContextForge separately uses its stored MCP credential when it calls the front-desk MCP server. The client token is not forwarded upstream.
  - **Directly to the adapter:** only a client calling the adapter's `/mcp/` itself sends the MCP credential, as `Authorization: Bearer <MCP credential>`.
  - **No `X-Upstream-Authorization`:** the voice client must not send this header. ContextForge renames it to `Authorization` on the upstream call, replacing its stored MCP credential.
- **Never tool arguments:** credentials, the trusted caller identity (`X-Caller-Number` with `X-Caller-Verification`) and the call start time. They come only from the request context (§3).
- **Contact numbers are arguments:** `patientMobile` (CREATE) and `callerMobile` (callback summary) are numbers the caller gives. They are contact data and grant no authority.
- **The hospital (tenant)** is fixed by the deployment, not by any argument.

## 3. Request context (trusted headers)

The voice platform sets the trusted headers below; the table shows which tools need each, and `X-Call-Id` goes on every tool call. ContextForge forwards exactly these five `X-` headers to the adapter when present. `Authorization` depends on the calling path (§2).
- Header names are case-insensitive.
- A malformed value is treated as absent.
- **`X-Call-Id`:** the voice platform generates one stable value per voice call and sends it on every tool call in that call: availability, LIST, booking writes and the summary. A new voice call gets a new id. It is a trusted header, never a tool argument or a value chosen by the LLM, and it must not contain a phone number, patient details or secrets. On reads it serves only to correlate the request with the call, so a read without it still runs; leaving it out is an integration defect, because the adapter's logs for that request can no longer be tied to the call.

| Header | Format | Needed by |
|---|---|---|
| `Authorization` | ContextForge client token when calling ContextForge; MCP credential only when calling the adapter directly | every tool |
| `X-Call-Id` | 1–64 characters: ASCII letters, digits, `.`, `_`, `:` or `-` | every tool call, for correlation; required by `manage_booking` CREATE, CANCEL, RESCHEDULE and `record_call_summary` |
| `X-Operation-Id` | same syntax as `X-Call-Id`; one value per distinct confirmed write | `manage_booking` CREATE, CANCEL, RESCHEDULE |
| `X-Caller-Number` | the platform's verified caller number, for example `+919000000101` | `manage_booking` LIST, CANCEL, RESCHEDULE |
| `X-Caller-Verification` | a label in the deployment's accepted set (default `SIP_CALLER_ID`) | with `X-Caller-Number` |
| `X-Call-Started-At` | ISO 8601 timestamp with offset, for example `2026-10-01T09:55:00+05:30` | `record_call_summary` |

**What a missing header produces:**
- missing call or operation headers on a write: `OPERATION_CONTEXT_MISSING`, with detail `CALL_ID_MISSING` or `OPERATION_ID_MISSING`;
- a missing number or an unaccepted verification label on LIST, CANCEL or RESCHEDULE: `IDENTITY_UNAVAILABLE`;
- missing summary headers: `NOT_SAVED`.

**Caller authority:** permission to list, cancel or reschedule comes only from `X-Caller-Number` together with an accepted `X-Caller-Verification`. A number dictated by the caller (`patientMobile`) is contact data and gives no access.

## 4. The tools

**Formats:**
- **Enums** are upper case.
- **Dates** are `today` or `YYYY-MM-DD` on the facility calendar, never in the past. `facilityToday` in every availability result gives the reference date.
- **Times** are 24-hour `HH:MM` (`00:00`–`23:59`).
- **Mobile numbers** are exactly 10 digits, with no `+91`, spaces or dashes.
- **`null`** is accepted wherever the schema allows it. It is not accepted for `purpose`, `action`, `callerConfirmed`, `intent`, `outcome` or `summaryText`.
- **Unknown arguments** are rejected (§8).

### 4.1 `get_doctor_availability`: can a doctor take an appointment request?

- **Purpose:** whether a doctor, or a department's doctors, can take an appointment request on a date (`purpose` AVAILABILITY, the default), or their usual hours (`purpose` WORKING_HOURS).
- **Safety:** read-only and safe to repeat.
- **One request, one answer:** each request is evaluated only on its own arguments. Earlier requests are not remembered, so a different doctor or date means a new request.

| Argument | Source | When |
|---|---|---|
| `doctorId` | `doctors[].doctorId` or `choices[].doctorId` from an earlier result | gives a doctor-specific result; takes precedence over every other target |
| `doctorName` | the caller's words | used if there's no `doctorId`. One directory match gives a doctor-specific result; several return `choices`; none returns `NOT_FOUND` |
| `departmentId` / `departmentName` | `department.id` / `departmentChoices[].id`, or the caller's words | used if no doctor is given. One match gives a department result; none or several return `departmentChoices` |
| `date` | the caller's date as `today` or `YYYY-MM-DD` (`facilityToday` is the reference) | **in every AVAILABILITY request**; optional for WORKING_HOURS. Words like "tomorrow" are refused (`ASK_EXPLICIT_DATE`) |
| `purpose` | `AVAILABILITY` (default) or `WORKING_HOURS` | WORKING_HOURS returns usual hours only: no live board, no slots |
| `session` | `board[].session` or `usualSessions[].label` from an earlier result | optional; limits the answer to that session |
| `gender` | `FEMALE` or `MALE` | optional filter for name and department searches |

**Order of checks:**
1. The date is checked first.
2. Without a target, the result is `INVALID_REQUEST` with detail `TARGET_REQUIRED`.
3. Only one target is evaluated, in the order above.

**Doctor-specific versus department results:**
- **A doctor-specific AVAILABILITY result reads that doctor's slot plan for the date.**
  - If slots are enabled for that doctor and date, its sessions carry `openSlots`.
  - Otherwise the slots-disabled rules apply (§15).
- **A department result reads no slots.** With slots enabled, each doctor whose known facts for the date permit a request carries decision `SLOT_CHECK_REQUIRED`.
  - When at least one doctor has `SLOT_CHECK_REQUIRED`, the outcome is `DOCTORS_MATCHED` and only those doctors are listed. No open time is established and `bookableFound` is 0, even when only one doctor is listed.
  - When none has it, the outcome is `CALLBACK_REQUIRED`, `HANDOFF_REQUIRED` or `NOT_AVAILABLE`, from the listed doctors' decisions.
  - With slots disabled, a department result lists bookable doctors as `AVAILABILITY`; `DOCTORS_MATCHED` does not occur.
- **Department lists are capped** at 3 doctors (the configured limit), ordered by decision and then name.

### 4.2 `manage_booking`: appointment requests

Four actions: CREATE, LIST, CANCEL and RESCHEDULE. Only `action` is schema-required; the tool checks the rest and names any missing or invalid field in `fields`.

| Action | Required | Optional | Headers |
|---|---|---|---|
| CREATE | `patientName`, `patientMobile` (10 digits), `doctorId`, `visitDate` (`today` or `YYYY-MM-DD`), `callerConfirmed: true`; `preferredTime` (`HH:MM`) when the doctor has slots for that date | `session`, `reasonVerbatim`; `preferredTime` without slots | X-Call-Id, X-Operation-Id |
| LIST | none | `fromDate`, `toDate` (`YYYY-MM-DD`; `today` is refused), `status` | X-Call-Id, X-Caller-Number, X-Caller-Verification |
| CANCEL | `appointmentId`, `callerConfirmed: true` | `reasonVerbatim` | all four write and caller headers |
| RESCHEDULE | `appointmentId`, `newVisitDate`, `callerConfirmed: true`; `newPreferredTime` when the doctor has slots for that date | `session`; `newPreferredTime` without slots | all four write and caller headers |

**Rules:**
- **`callerConfirmed: true`** records the caller's agreement to the exact details being written.
- **Doctor:** CREATE needs a `doctorId`, and department-level appointments don't exist. RESCHEDULE keeps the appointment's doctor; sending `doctorId` gives `INVALID_REQUEST` / `ASK_TO_CORRECT` with detail `DOCTOR_CHANGE_UNSUPPORTED` and `fields` including `doctorId`; nothing is written.
- **RESCHEDULE scope:** only an appointment in the verified caller's own list, which starts today, can be rescheduled. Any other id, including the caller's past appointment, returns `NOT_FOUND` with no write.
- **LIST** returns the verified caller's appointments from today, unless `fromDate` is given.
- **`reasonVerbatim`** is forwarded to the hospital unchanged and is never interpreted.
- **Session label:** with slots, `session` is optional. If given, it must match the session that contains the chosen time; otherwise the result is `NOT_AVAILABLE` with detail `TIME_OUTSIDE_SESSION`.

**Order of checks for CREATE, CANCEL and RESCHEDULE.** The first failure is returned:
1. field validation (`INVALID_REQUEST`);
2. `callerConfirmed` (`CONFIRMATION_REQUIRED`);
3. call and operation headers (`OPERATION_CONTEXT_MISSING`);
4. caller identity for CANCEL and RESCHEDULE (`IDENTITY_UNAVAILABLE`);
5. the schedule check for CREATE and RESCHEDULE: `INVALID_REQUEST` with `TIME_REQUIRED` or `SESSION_REQUIRED`, `CALLBACK_REQUIRED`, `NOT_AVAILABLE`, `HANDOFF_REQUIRED`, or `COULD_NOT_RECORD` after a failed read;
6. the hospital write.

The schedule check is the same one `get_doctor_availability` applies, run again at write time. A schedule `NOT_AVAILABLE` (for example `NO_OPEN_SLOT`, `SESSION_ENDED` or `TIME_OUTSIDE_SESSION`) comes with `OFFER_OTHER_SESSION_OR_TIME` when other sessions on that date permit a request, listed in `sessions`; otherwise with `OFFER_OTHER_SESSION_OR_DATE` and no alternatives. The hospital's own `SLOT_FULL` refusal at write time comes with `OFFER_OTHER_SESSION_OR_TIME` and no `sessions`.

### 4.3 `record_call_summary`: one summary per call

- **Purpose:** stores one summary covering the whole call, including the last tool result.
- **Final:** the first accepted summary for a call is final.
- **Headers:** `X-Call-Id` and `X-Call-Started-At`.

| Field | Rule |
|---|---|
| `intent`, `outcome`, `summaryText` | Always required. `summaryText` is non-blank, at most 500 characters, and never shortened. Longer text returns `INVALID_REQUEST` with `fields: ["summaryText"]` |
| `callerMobile` | Required when `outcome` is `CALLBACK_NOTED`; exactly 10 digits |
| `appointmentId` | Optional, from `manage_booking`; refused with `CALLBACK_NOTED` |
| `transferredTo` | Only with `TRANSFERRED` or `EMERGENCY_TRANSFERRED` |
| `doctorId`, `language` | Optional. `language` `en`, `kn` or `hi` is stored; other codes are dropped |
| Caller name, symptoms, dates, sessions | Inside `summaryText` only. There are no separate fields for them, and such arguments are rejected |

## 5. Data between calls

**Where identifiers come from.** Identifiers are only ever taken from earlier results. An invented identifier matches no record.

| Argument | Comes from |
|---|---|
| `doctorId` | `doctors[].doctorId` or `choices[].doctorId` |
| `departmentId` | `department.id` or `departmentChoices[].id` |
| `session` | `board[].session` (today) or `usualSessions[].label` |
| `preferredTime` / `newPreferredTime` | a time inside a returned `openSlots` block (`start` inclusive, `end` exclusive) |
| `appointmentId` | `appointment.appointmentId` or `appointments[].appointmentId` |

**Typical chains.** Callers can supply facts in any order. A chain step is simply the next request, carrying everything it needs.
1. **Finding a time:**
   - a department request gives `DOCTORS_MATCHED` (slots enabled) with `doctors[]`; a `doctorName` with several matches gives `CLARIFICATION_NEEDED` with `choices[]`;
   - an AVAILABILITY request with the chosen `doctorId` and a date gives that doctor's sessions and `openSlots`. A `doctorName` with exactly one match gives this doctor-specific result directly;
   - CREATE with the same doctor and date, and `preferredTime` inside an open block, gives `NOTED`.
2. **Changing an appointment:** LIST gives `appointmentId`, then CANCEL or RESCHEDULE.
3. **Closing the call:** the last tool result goes into the summary:

| Tool result | Summary `outcome` | Also send |
|---|---|---|
| CREATE `NOTED` | `APPOINTMENT_NOTED` | `appointmentId`, `doctorId` |
| RESCHEDULE `NOTED` | `APPOINTMENT_RESCHEDULED` | `appointmentId` |
| CANCEL `CANCELLED` | `APPOINTMENT_CANCELLED` | `appointmentId` |
| `CALLBACK_REQUIRED` (`callback.summaryOutcome`) | `CALLBACK_NOTED` | `callerMobile`; no `appointmentId` |
| Desk handoff, after the platform transferred the call | `TRANSFERRED` | `transferredTo` |
| Desk handoff, no transfer completed, a callback was agreed and the caller gave a callback number | `CALLBACK_NOTED` | `callerMobile`; no `transferredTo` |
| Desk handoff, no transfer completed, no callback arranged | `ABANDONED` (interim, until the hospital defines a value) | what happened, in `summaryText` |
| Caller ended the call before it was settled | `ABANDONED` | |

MCP never transfers calls, so `TRANSFERRED` records the platform's own action.

## 6. Reading a result

- **`outcome`, `nextStep` and `detail`:** `outcome` is the result category. `nextStep` is the disposition code; both are codes, not wording. `detail` names the cause of a non-success result. Meanings: §12–§14.
- **`decision` versus `status`:** `decision` is MCP's verdict for a doctor or session. `status` is the hospital's own value: IN, LATE, CANCELLED, NOT_CONFIRMED or UNKNOWN on the board or slot plan, and NOTED, CONFIRMED_BY_DESK, CHANGED or CANCELLED on appointments. They are reported separately and never merged.
- **Empty versus null:**
  - `openSlots: null` means slots were not read (department result, WORKING_HOURS, or the doctor has no slots for that date);
  - `openSlots: []` means slots were read and no block is offered;
  - `usualSessions: null` means usual sessions were not fetched (today's live facts are in `board`);
  - `slotTime: null` means no time was recorded;
  - other `null` fields mean "not applicable or not supplied".
- **Counts:**
  - `totalMatches` is the directory count;
  - `bookableFound` counts doctors whose facts permit a request, and is 0 for `DOCTORS_MATCHED` and WORKING_HOURS;
  - `complete: false` means some candidates weren't checked, so absence is not established.

## 7. What a result establishes, and what it doesn't

- **`NOTED` records a request.** It is not a reservation or a confirmed time. After a `NOT_CONFIRMED` session, the desk confirms. The appointment's `status` keeps the hospital's value.
- **`DOCTORS_MATCHED` / `SLOT_CHECK_REQUIRED`** establish no open time. Open times come only from a doctor-specific AVAILABILITY result for that doctor and date.
- **WORKING_HOURS** returns usual hours, never current attendance, and offers no appointment.
- **`COULD_NOT_CHECK` and `COULD_NOT_RECORD`** mean a read or write failed. They never mean "unavailable", "full" or "no appointment".
- **`CALLBACK_REQUIRED`** means no appointment was written. The callback exists only as a `CALLBACK_NOTED` summary; MCP creates no callback task.
- **`HANDOFF_REQUIRED` and `TRANSFER_DESK`** mean desk assistance. MCP doesn't transfer calls, and these results carry no callback data.
- **`NOT_AVAILABLE` alternatives** are only the `sessions` and `openSlots` in that same result. An empty list says nothing about other times, and an owner `SLOT_FULL` rejection carries no alternatives.
- **`slotTime` and `slotMoved`:**
  - `slotTime` is the time the hospital recorded, normally the block start; choosing 10:45 in the 10:30–11:00 block gives `slotTime` 10:30 with `slotMoved: false`;
  - `slotMoved` is true only when the hospital recorded a different block;
  - LIST and CANCEL always return `slotMoved: false`.
- **`dataConfirmed`** is the hospital's profile metadata, passed through unchanged. No MCP decision uses it: `false` or `null` never means unavailable and never requires callback. Availability is given only by `decision`, `outcome` and `openSlots`.
- **Booking `NOT_FOUND` is neutral:** an unknown id, another caller's id and a past appointment all look the same.
- **Private data in results:** results never contain caller numbers, reasons or upstream error text. The only exceptions are `patientName` on the verified caller's own appointments, and the desk-written board `note` (at most 200 characters, written for callers).

## 8. Failures, retries and uncertainty

**Two kinds of failure:**
1. **`isError: true` with text and no structured result:** the arguments were rejected before the tool ran (unknown field, wrong type or enum, value too long). Repeating the same arguments fails the same way. Summary rejections deliberately name no field.
2. **A structured result** such as `INVALID_REQUEST`: the tool ran and refused, and `fields` or `detail` names what to correct.

**Writes and `X-Operation-Id`:**
- Each distinct confirmed write has its own operation id.
- Repeating with the same id and identical arguments is a safe retry: nothing is written twice. When the retry reaches the hospital and the first attempt was recorded, the hospital returns that original result.
- For CREATE and RESCHEDULE, the schedule is checked again before the hospital is called. A refused retry (for example `NOT_AVAILABLE`, because the first attempt took the last place) doesn't show whether the first attempt was recorded. LIST may help: it shows the appointment's current state (for RESCHEDULE, its current date and time; for CREATE, the new appointment only when `patientMobile` is the verified caller's number). It can't prove which attempt recorded it, because LIST results carry no call or operation id.
- CANCEL has no schedule re-check. After the usual field, confirmation, header and identity checks (§4.2), its retry is sent to the hospital with the same idempotency key.
- The same id with different arguments returns `CONFLICT`.
- A new id is a new write.

**`UNCERTAIN`:** the write may have been recorded, but no verified answer came back. The disposition is desk handoff (`SAY_UNCERTAIN_AND_TRANSFER`), not a new write under a new id. An owner rejection that arrives after an unanswered attempt also stays `UNCERTAIN`.

**`retryAfterSeconds`:** when the hospital service asks for a delay, `COULD_NOT_CHECK` and `COULD_NOT_RECORD` carry it.

**Summaries:**
- A repeat for the same call returns `ALREADY_SAVED`, even with different text; the first summary stays.
- `NOT_CONFIRMED` means saving could not be verified.
- `NOT_SAVED` means the headers were missing or invalid, or the hospital service refused the adapter's own credentials.

**Time budgets:**
- Availability and LIST have a default 0.30-second adapter deadline. Read failures return COULD_NOT_CHECK.
- Confirmed CREATE, CANCEL and RESCHEDULE have a default 3.0-second total deadline and 1.0-second per-exchange cap, including schedule checks, caller appointment lookup, authentication and any retry. Responses return when received; the ceiling adds no delay. Failures before a write can be COULD_NOT_RECORD; a sent write without a verified response is UNCERTAIN.
- Summaries retain an independent 8.0-second total and exchange cap; uncertain saving is NOT_CONFIRMED. A same-body retry happens at most once within the operation's deadline.
- Before deployment, the voice team must confirm both LiveKit timeout and client_session_timeout_seconds cover the write deadline plus gateway time and margin. The recommendation for 3-second writes is 8–10 seconds. These values are not assumed to be configured. The voice team owns any acknowledgement while waiting; filler is not a useful-result latency measurement.
- The six values in rollout.env control these ceilings. Tool schema 2026-10-11.2 is unchanged; this budget change does not require tool discovery refresh.

| Tool | Read-only | Changes data | Safe to repeat with the same arguments |
|---|---|---|---|
| `get_doctor_availability` | yes | no | yes |
| `manage_booking` | LIST only | CREATE, CANCEL, RESCHEDULE | with the same `X-Operation-Id`; the schedule is re-checked |
| `record_call_summary` | no | one summary per call | yes; a repeat returns `ALREADY_SAVED` |

## 9. Worked examples

These are real results from the development stubs: fixture data, facility date Thursday 2026-10-01 at 10:00 IST, with slots enabled. Results are trimmed to the decisive fields; "…" marks omitted fields. Headers shown are those the result depends on; every call also carries `X-Call-Id` (§3).

**Example 1: department → doctor → appointment request**

```text
get_doctor_availability {"departmentName": "General Medicine", "date": "2026-10-05"}
→ {"outcome": "DOCTORS_MATCHED", "nextStep": "ASK_WHICH_DOCTOR", "requestedDate": "2026-10-05", "bookableFound": 0,
   "doctors": [{"doctorId": "doc_arjun_menon", "decision": "SLOT_CHECK_REQUIRED", …},
               {"doctorId": "doc_garima", "decision": "SLOT_CHECK_REQUIRED",
                "usualSessions": [{"label": "Morning", "start": "09:00", "end": "12:00", "openSlots": null, …}, …]}], …}

get_doctor_availability {"doctorId": "doc_garima", "date": "2026-10-05"}
→ {"outcome": "AVAILABILITY", "nextStep": "OFFER_APPOINTMENT_REQUEST", "bookableFound": 1,
   "doctors": [{"doctorId": "doc_garima", "decision": "APPOINTMENT_REQUEST", "usualSessions": [
     {"label": "Morning", "status": "IN", "decision": "APPOINTMENT_REQUEST",
      "openSlots": [{"start": "10:30", "end": "11:00", "available": 2}], …},
     {"label": "Afternoon", "status": "NOT_CONFIRMED", "decision": "APPOINTMENT_REQUEST",
      "openSlots": [{"start": "15:00", "end": "15:30", "available": 3}], …}]}], …}

manage_booking {"action": "CREATE", "patientName": "Asha Rao", "patientMobile": "9000000101", "doctorId": "doc_garima",
                "visitDate": "2026-10-05", "callerConfirmed": true}        headers: X-Call-Id, X-Operation-Id op-1
→ {"outcome": "INVALID_REQUEST", "nextStep": "ASK_WHICH_TIME", "detail": "TIME_REQUIRED", "fields": ["preferredTime"],
   "sessions": [{"label": "Morning", "openSlots": [{"start": "10:30", "end": "11:00", "available": 2}], …}, …]}

manage_booking {… the same, "preferredTime": "10:45"}                      X-Operation-Id op-2
→ {"outcome": "NOTED", "nextStep": "SAY_REQUEST_NOTED", "appointment": {"appointmentId": "appt_0001", "status": "NOTED",
   "visitDate": "2026-10-05", "expectedTime": "10:45", "slotTime": "10:30", "slotMoved": false, …}}

manage_booking {… the same, "preferredTime": "11:10"}                      X-Operation-Id op-4
→ {"outcome": "NOT_AVAILABLE", "nextStep": "OFFER_OTHER_SESSION_OR_TIME", "detail": "SLOT_FULL", "sessions": [ …open blocks… ]}
```

- **10:45 → 10:30:** the hospital recorded the start of the 10:30–11:00 block, which isn't a move.
- **11:10:** the 11:00–11:30 block is full, so it isn't offered in `openSlots`, and a time inside it gives `SLOT_FULL`.

**Example 2: unresolved attendance → callback summary**

```text
get_doctor_availability {"doctorId": "doc_garima", "date": "today"}       (board status UNKNOWN)
→ {"outcome": "CALLBACK_REQUIRED", "nextStep": "ASK_CALLBACK_DETAILS", "detail": "BOARD_UNKNOWN", "basis": "LIVE_BOARD",
   "callback": {"reason": "BOARD_UNKNOWN", "summaryOutcome": "CALLBACK_NOTED"}, …}

record_call_summary {"intent": "AVAILABILITY", "outcome": "CALLBACK_NOTED", "callerMobile": "9000000101", "doctorId": "doc_garima",
                     "summaryText": "Caller asked for Dr. Garima today; attendance unknown. Callback requested for Morning."}
                                                                          headers: X-Call-Id, X-Call-Started-At
→ {"outcome": "SAVED"}
record_call_summary {another summary for the same call}  → {"outcome": "ALREADY_SAVED"}

get_doctor_availability {"doctorId": "doc_vikram_desai", "date": "today"}   (on-call doctor, not confirmed)
→ {"outcome": "HANDOFF_REQUIRED", "nextStep": "TRANSFER_DESK", "detail": "ON_CALL_DOCTOR", "callback": null, …}
```

**Example 3: list and reschedule**

```text
manage_booking {"action": "LIST"}                                         headers: X-Caller-Number, X-Caller-Verification
→ {"outcome": "FOUND", "nextStep": "OFFER_CHOICES",
   "appointments": [{"appointmentId": "appt_0001", "visitDate": "2026-10-05", "slotTime": "10:30", "slotMoved": false, …}]}

manage_booking {"action": "RESCHEDULE", "appointmentId": "appt_0001", "newVisitDate": "2026-10-05",
                "newPreferredTime": "15:10", "callerConfirmed": true}      + X-Call-Id, X-Operation-Id op-3
→ {"outcome": "NOTED", "nextStep": "SAY_REQUEST_NOTED",
   "appointment": {"status": "CHANGED", "expectedTime": "15:10", "slotTime": "15:00", "slotMoved": false, …}}

The same RESCHEDULE from another verified number
→ {"outcome": "NOT_FOUND", "nextStep": "SAY_NOT_FOUND"}                    (no write)
```

**Rejected before the tool runs:**

```text
get_doctor_availability {"doctorName": "Garima", "date": "tomorrow"}
→ {"outcome": "INVALID_REQUEST", "nextStep": "ASK_EXPLICIT_DATE", "detail": "DATE_FORMAT", "facilityToday": "2026-10-01", …}
get_doctor_availability {"doctorId": "doc_garima", "date": "today", "foo": 1}
→ isError: true, text "1 validation error … foo … Unexpected keyword argument", no structured result
```

## 10. Acceptance scenarios

These are the expected results for testing a client end to end. Each one matches current adapter behaviour.

| # | Situation | Expected `outcome` / `nextStep` | Key fact |
|---|---|---|---|
| 1 | Department and date, slots enabled | `DOCTORS_MATCHED` / `ASK_WHICH_DOCTOR` | `bookableFound` 0; no `openSlots` |
| 2 | The same date with a listed `doctorId` | `AVAILABILITY` / `OFFER_APPOINTMENT_REQUEST` | sessions carry `openSlots` |
| 2a | A doctor name with exactly one match, and a date | `AVAILABILITY` | doctor-specific; `openSlots` directly, with no `choices` |
| 3 | Doctor name only, no date | `INVALID_REQUEST` / `ASK_EXPLICIT_DATE` | no lookup happens |
| 4 | A name with several matches | `CLARIFICATION_NEEDED` / `ASK_WHICH_DOCTOR` | `choices[].doctorId` |
| 5 | An unknown department name | `CLARIFICATION_NEEDED` / `ASK_WHICH_DEPARTMENT` | `departmentChoices` |
| 6 | "tomorrow" as the date | `INVALID_REQUEST` / `ASK_EXPLICIT_DATE` | detail `DATE_FORMAT` |
| 7 | CREATE on a slot day without a time | `INVALID_REQUEST` / `ASK_WHICH_TIME` | `sessions` with `openSlots`; no write |
| 8 | CREATE at a time in a full block | `NOT_AVAILABLE` / `OFFER_OTHER_SESSION_OR_TIME` | detail `SLOT_FULL` |
| 9 | CREATE in a `NOT_CONFIRMED` session with an open block | `NOTED` / `SAY_REQUEST_NOTED` | a request; the desk confirms |
| 10 | Ordinary doctor UNKNOWN today | `CALLBACK_REQUIRED` / `ASK_CALLBACK_DETAILS` | no write; `callback` present |
| 11 | On-call doctor not confirmed | `HANDOFF_REQUIRED` / `TRANSFER_DESK` | no callback data |
| 12 | A cancelled session | `NOT_AVAILABLE` | reason `CANCELLED` |
| 13 | WORKING_HOURS for one doctor | `WORKING_HOURS` / `PRESENT_WORKING_HOURS` | `bookableFound` 0 |
| 14 | A write without `callerConfirmed` | `CONFIRMATION_REQUIRED` / `ASK_CONFIRMATION` | no write |
| 15 | A write without `X-Operation-Id` | `OPERATION_CONTEXT_MISSING` | no write |
| 16 | LIST without verification | `IDENTITY_UNAVAILABLE` | a dictated number gives no access |
| 17 | RESCHEDULE of another caller's or a past appointment | `NOT_FOUND` / `SAY_NOT_FOUND` | no write |
| 18 | The same operation id with different arguments | `CONFLICT` | no second write |
| 19 | A write with no verified answer | `UNCERTAIN` / `SAY_UNCERTAIN_AND_TRANSFER` | the desk handles it |
| 20 | The hospital service is slow or down | `COULD_NOT_CHECK` / `SAY_COULD_NOT_CHECK` | not "unavailable" |
| 21 | The owner records a different block | `NOTED` | `slotMoved: true` |
| 22 | A second summary for the call | `ALREADY_SAVED` | the first stays |
| 23 | `CALLBACK_NOTED` without `callerMobile` | `INVALID_REQUEST` | `fields: ["callerMobile"]` |
| 24 | An unknown argument | `isError: true` | no structured result |

## 11. Changes since schema `2026-10-06.1`

- **Slots:** `openSlots`, `oneDay` sessions, `slotTime` and `slotMoved`; `DOCTORS_MATCHED` and `SLOT_CHECK_REQUIRED` for department results; `ASK_WHICH_TIME` (a time is required with slots); `NO_OPEN_SLOT`; `SLOT_FULL`.
- **On-call doctors** without a confirmed, usable entry get `HANDOFF_REQUIRED` (desk), no longer callback.
- **Our front-desk `search_knowledge` was removed,** leaving three tools. Knowledge goes through Stratum.
- **RESCHEDULE** applies only to appointments in the verified caller's own list, from today.
- **Owner appointment times** that aren't `HH:MM` now give `UNCERTAIN` after a write and `COULD_NOT_CHECK` on LIST, never an unexpected error.
- **`2026-10-11.2`:** clearer descriptions for doctor-specific versus department results and for the choice lists. There are no wire changes.

# Part 2: Reference

## 12. Outcome codes

| Code | Tools | Meaning |
|---|---|---|
| `outcome.AVAILABILITY` | get_doctor_availability | Facts for the requested date, with each doctor's and session's decision and any required selection |
| `outcome.DOCTORS_MATCHED` | get_doctor_availability | Department result with slots enabled: the listed doctors match, but slots were not read. No open time is established, and `bookableFound` is 0 |
| `outcome.CLARIFICATION_NEEDED` | get_doctor_availability | Several doctor matches (`choices`), or a department that matched none or several (`departmentChoices`) |
| `outcome.WORKING_HOURS` | get_doctor_availability | Usual hours or attendance days; no live attendance check |
| `outcome.NOT_FOUND` | get_doctor_availability | No matching doctor name (`ASK_TO_REPHRASE`), or a department with no consultant or no doctors (`TRANSFER_DESK`) |
| `outcome.NOT_FOUND` | manage_booking | No matching appointment in the verified caller's list (unknown, another caller's, or past). Nothing is written |
| `outcome.CALLBACK_REQUIRED` | get_doctor_availability, manage_booking | Ordinary doctor with an unresolved schedule: UNKNOWN, `NOT_CONFIRMED` without slots, or no usual schedule. No write; the callback belongs only in a `CALLBACK_NOTED` summary |
| `outcome.HANDOFF_REQUIRED` | get_doctor_availability | Desk assistance: an on-call doctor without a confirmed, usable entry (`ON_CALL_DOCTOR`), or a department search that is incomplete with no match (`SEARCH_INCOMPLETE`). No callback data; MCP doesn't transfer |
| `outcome.HANDOFF_REQUIRED` | manage_booking | Desk assistance, no write: an on-call doctor without a confirmed, usable entry (`ON_CALL_DOCTOR`), or a specific time in a session with no end time (`TIME_NOT_VERIFIABLE`). No callback data; MCP doesn't transfer |
| `outcome.NOT_AVAILABLE` | get_doctor_availability, manage_booking | Valid request, but the facts exclude the requested date, session or time |
| `outcome.COULD_NOT_CHECK` | get_doctor_availability, manage_booking | A read failed. This is not an empty or negative result |
| `outcome.INVALID_REQUEST` | get_doctor_availability, manage_booking, record_call_summary | The request was refused before any write. `detail` (availability, booking) or `fields` (booking, summary) names the issue |
| `outcome.NOTED` | manage_booking | CREATE or RESCHEDULE request recorded. No time is confirmed or reserved; `appointment.status` keeps the hospital's value |
| `outcome.CHANGED` | manage_booking | Not returned by RESCHEDULE, which returns `NOTED` with the hospital's `CHANGED` in `appointment.status`. Returned only if the hospital answers a CREATE or CANCEL with status `CHANGED`, which Manoj's contract does not describe |
| `outcome.CANCELLED` | manage_booking | The hospital returned a verified cancellation |
| `outcome.FOUND` | manage_booking | The verified caller's appointments are in `appointments` |
| `outcome.REJECTED` | manage_booking | The hospital rejected the request definitively; `detail` is its code, and `fields` lists any tool arguments it named |
| `outcome.CONFLICT` | manage_booking | The same operation id was used with different arguments (`IDEMPOTENCY_CONFLICT`), or the appointment's state doesn't allow it, for example it's already cancelled (`STATE_CONFLICT`) |
| `outcome.UNCERTAIN` | manage_booking | The write may have been recorded, with no verified result. Desk handoff, not a retry; a later invocation with the same operation id re-checks the schedule and can be refused |
| `outcome.IDENTITY_UNAVAILABLE` | manage_booking | No verified caller number for LIST, CANCEL or RESCHEDULE |
| `outcome.CONFIRMATION_REQUIRED` | manage_booking | `callerConfirmed` was not true for a write |
| `outcome.OPERATION_CONTEXT_MISSING` | manage_booking | `X-Call-Id` or `X-Operation-Id` is missing or malformed for a write |
| `outcome.COULD_NOT_RECORD` | manage_booking | The write wasn't attempted or couldn't be recorded (failed schedule read, owner unavailable); `detail` names the cause |
| `outcome.SAVED` | record_call_summary | A new summary was stored for this call |
| `outcome.ALREADY_SAVED` | record_call_summary | This call already has a summary. Nothing changed, even if the new text differs |
| `outcome.NOT_CONFIRMED` | record_call_summary | Saving couldn't be verified: no answer, malformed success, call-id mismatch, transport failure, rate limit or server error |
| `outcome.NOT_SAVED` | record_call_summary | Missing or malformed `X-Call-Id`/`X-Call-Started-At`, or the hospital service definitively refused the adapter's own credentials. If an earlier send may have committed, `NOT_CONFIRMED` takes precedence |

## 13. nextStep codes

`record_call_summary` has no `nextStep`.

| Code | Tools | Meaning |
|---|---|---|
| `nextStep.OFFER_APPOINTMENT_REQUEST` | get_doctor_availability | An appointment request is possible for the returned scope; not a reservation |
| `nextStep.ASK_WHICH_DOCTOR` | get_doctor_availability | A doctor selection is needed: several name matches, a department result, or WORKING_HOURS for a department. Slot facts need a doctor-specific request, even when one doctor is listed |
| `nextStep.ASK_WHICH_DEPARTMENT` | get_doctor_availability | The department matched none or several; see `departmentChoices` |
| `nextStep.ASK_TO_REPHRASE` | get_doctor_availability | The name or department couldn't be resolved, or no target was given |
| `nextStep.ASK_EXPLICIT_DATE` | get_doctor_availability | AVAILABILITY needs `today` or `YYYY-MM-DD` that isn't in the past |
| `nextStep.PRESENT_WORKING_HOURS` | get_doctor_availability | Usual hours are returned, without an appointment offer or a date-specific claim |
| `nextStep.ASK_WHICH_SESSION` | get_doctor_availability | The doctor's sessions have different decisions; a session or time selection resolves them |
| `nextStep.ASK_WHICH_SESSION` | manage_booking | Without slots only: differing session decisions need a session or time. With slots, a mismatched session label is `TIME_OUTSIDE_SESSION` instead |
| `nextStep.ASK_CALLBACK_DETAILS` | get_doctor_availability, manage_booking | Callback applies: no appointment is written; the callback belongs in a `CALLBACK_NOTED` summary |
| `nextStep.TRANSFER_DESK` | get_doctor_availability, manage_booking | Desk assistance is the disposition; MCP doesn't transfer calls |
| `nextStep.SAY_COULD_NOT_CHECK` | get_doctor_availability, manage_booking | The requested information couldn't be checked |
| `nextStep.OFFER_OTHER_SESSION_OR_DATE` | get_doctor_availability, manage_booking | The requested session or date is unavailable; checked alternatives may be in the same result |
| `nextStep.SAY_REQUEST_NOTED` | manage_booking | The request is recorded, without a guaranteed time |
| `nextStep.SAY_CHANGED` | manage_booking | Comes only with `outcome.CHANGED` |
| `nextStep.SAY_CANCELLED` | manage_booking | A cancellation is verified |
| `nextStep.OFFER_CHOICES` | manage_booking | The verified caller's appointments are listed |
| `nextStep.SAY_NOT_FOUND` | manage_booking | No matching appointment in the verified caller's list |
| `nextStep.ASK_TO_CORRECT` | manage_booking | `fields` names arguments that need correcting |
| `nextStep.ASK_CONFIRMATION` | manage_booking | The write lacks `callerConfirmed: true` |
| `nextStep.ASK_WHICH_TIME` | manage_booking | With slots, a time is required; `sessions` carry the `openSlots` |
| `nextStep.OFFER_OTHER_SESSION_OR_TIME` | manage_booking | `sessions`/`openSlots` are the checked alternatives. An owner `SLOT_FULL` rejection carries none |
| `nextStep.SAY_UNCERTAIN_AND_TRANSFER` | manage_booking | Write completion is uncertain; desk assistance |
| `nextStep.SAY_COULD_NOT_RECORD` | manage_booking | The write couldn't be recorded |

## 14. Decision, Reason and Detail codes

| Decision | Meaning |
|---|---|
| APPOINTMENT_REQUEST | The facts permit an appointment request (not a reservation) |
| SLOT_CHECK_REQUIRED | Department result with slots enabled: the doctor matches, and the date's known facts permit a request subject to slots. No open time is established |
| CALLBACK_REQUIRED | Ordinary doctor with an unresolved schedule |
| HANDOFF_REQUIRED | Desk assistance; on-call doctor without a confirmed, usable entry |
| NOT_AVAILABLE | The facts exclude the session, date or time |
| COULD_NOT_CHECK | A required read failed; no negative claim |

| Reason | Meaning |
|---|---|
| ON_CALL_DOCTOR | On-call doctor with no confirmed, usable entry. Desk handoff, also for working hours (no usual schedule) |
| BOARD_UNKNOWN | The board or slot session status is UNKNOWN. Callback for ordinary doctors, handoff for on-call doctors |
| BOARD_STALE | The hospital marked today's row stale |
| BOARD_ENTRY_MISSING | No board entry today for this doctor |
| SESSION_NOT_ON_BOARD | The requested session isn't on today's board |
| BOARD_NOT_CONFIRMED | Ordinary attendance `NOT_CONFIRMED` without slots. With slots, an open block can instead permit a request |
| CANCELLED | The hospital cancelled this session |
| SESSION_ENDED | The session's supplied end time has passed (facility time) |
| NOT_USUAL_DAY | No usual session on that future weekday |
| SESSION_NOT_USUAL | The requested session isn't a usual session on that date |
| NO_USUAL_SCHEDULE | No usual schedule is supplied for this doctor |
| PROFILE_UNAVAILABLE | The doctor's profile couldn't be read |
| TIME_OUTSIDE_SESSION | The time is outside the known windows, or (with slots) no open or full block contains it, the block is closed or ended, or the session label doesn't match |
| SESSION_REQUIRED | Differing session decisions need a session or time selection |
| TIME_NOT_VERIFIABLE | A specific time can't be checked because the session has no end time; no write |
| SEARCH_INCOMPLETE | Some candidates are unchecked or failed; absence isn't established |
| NO_OPEN_SLOT | The session has no open block |
| SLOT_FULL | The chosen time's block is full |

| Detail | Where | Meaning |
|---|---|---|
| DATE_REQUIRED, DATE_FORMAT, PAST_DATE | availability | Date missing, not `today`/`YYYY-MM-DD`, or in the past |
| TARGET_REQUIRED | availability | No doctor or department was given |
| DEPARTMENT_UNMATCHED, DEPARTMENT_AMBIGUOUS | availability | The department matched none or several (`departmentChoices`) |
| NO_CONSULTANT, NO_DOCTORS | availability | The department has no consultant or no doctors |
| DIRECTORY_REJECTED | availability | The directory refused the query |
| DIRECTORY_UNAVAILABLE, CAPABILITIES_UNAVAILABLE | availability | The directory or slot-capability read failed; no negative claim |
| BOARD_UNAVAILABLE, PROFILE_UNAVAILABLE, SLOTS_UNAVAILABLE | availability, booking | That read failed or returned invalid data; no negative claim and no write |
| TIME_REQUIRED | booking | With slots, `preferredTime`/`newPreferredTime` is required |
| SESSION_REQUIRED | booking | Without slots, differing session decisions need a session or time |
| DOCTOR_CHANGE_UNSUPPORTED | booking | RESCHEDULE can't change the doctor |
| CALL_ID_MISSING, OPERATION_ID_MISSING | booking | With `OPERATION_CONTEXT_MISSING` |
| IDEMPOTENCY_CONFLICT, STATE_CONFLICT | booking | With `CONFLICT` |
| NO_VERIFIED_RESPONSE, MALFORMED_SUCCESS | booking | With `UNCERTAIN`: no answer, or an invalid success answer after a write attempt |
| APPOINTMENT_UNAVAILABLE | booking | The caller's appointments couldn't be read before a RESCHEDULE |
| MALFORMED | booking | The hospital's data was invalid (LIST, or an appointment with no doctor) |
| DEADLINE, TIMEOUT, TRANSPORT, AUTH, UPSTREAM | booking | Why the hospital service was unavailable (`COULD_NOT_CHECK`/`COULD_NOT_RECORD`) |
| the hospital's error code | booking | With `REJECTED`: the hospital's own code |

## 15. Schedule rules

**Which facts apply:**
- **Today** uses the live board (`basis` LIVE_BOARD) plus slots when enabled.
- **Future dates** use slots when enabled, otherwise usual hours (USUAL_SCHEDULE); attendance on a future date is never confirmed.
- **WORKING_HOURS** reads neither the board nor slots.

**Ordinary doctors** (REGULAR, VISITING):
- **UNKNOWN** always means callback, even if another source says CANCELLED.
- **CANCELLED** is `NOT_AVAILABLE`.
- **NOT_CONFIRMED:** with an open bookable block, a request is permitted and noted for desk confirmation; without slots, today's NOT_CONFIRMED means callback.
- **A supplied end time that has passed** is `SESSION_ENDED`. A missing end time is not an ended session.

**On-call doctors:**
- The ordinary rules apply only with a confirmed IN or LATE entry plus either a usable window (both times, not ended) or an open bookable block.
- Otherwise the result is `HANDOFF_REQUIRED`/`ON_CALL_DOCTOR`, without callback.
- A cancelled on-call session is `NOT_AVAILABLE`.
- WORKING_HOURS for one on-call doctor is always `HANDOFF_REQUIRED`.

**With slots** (enabled per doctor and date):
- MCP uses the hospital's capacity and never computes its own.
- A time must fall inside a returned open block: `start` inclusive, `end` exclusive.
- Today, a block can be booked only until it ends.
- `session` is optional, but if given it must match the session that contains the time.
- A `oneDay` session was added by the desk for that date only: `daysOfWeek` is empty and `onRequestedDate` is true. With null `start`/`end` it has no bookable time.

**Without slots:**
- Today's window starts at the later of the session start and the current facility time (minute precision).
- Future dates follow usual hours, and the time is optional.
- Differing session decisions need a session or time (`SESSION_REQUIRED`); equal decisions permit a day-level request.
- A specific time in a session with no end time gives `HANDOFF_REQUIRED`/`TIME_NOT_VERIFIABLE`, with no write.

**Session choices:** several sessions with the same decision need no session choice. With slots, a booking still needs a time.

**Session names: today versus other dates.** For AVAILABILITY and booking, the session shape follows the requested date; WORKING_HOURS always uses the usual-session shape.

| Request | Where sessions appear | Session name field | Based on |
|---|---|---|---|
| AVAILABILITY or booking for today | `board[]` (availability), `sessions[]` (booking) | `session` | today's board and that date's slots |
| AVAILABILITY or booking for a future date | `usualSessions[]` (availability), `sessions[]` (booking) | `label` | the usual schedule and that date's slots |
| WORKING_HOURS | `usualSessions[]` | `label` | the usual schedule only |

Today's slot-only sessions (on the slot plan but not on the board) also use the today shape: the name is in `session`, with no `label` or `oneDay` field. A non-empty name from either field can be passed back as the optional `session` argument. If the name is empty or null, omit `session`; with slots, the chosen time from `openSlots` identifies the session.

**Not supported:** sessions that cross midnight.

**Department WORKING_HOURS** includes on-call facts within the list cap. An ordinary doctor with an empty schedule gets `CALLBACK_REQUIRED`.

## 16. Field reference

These tables list each tool's top-level input and output fields, followed by the shared output types.
- Each shared type is described once, and it's identical in every tool that returns it.
- "Required" means schema-required; requirements that depend on the action are in Part 1 §4.
- Input meanings are the published descriptions.

### get_doctor_availability input

| Field | Wire type | Required | Meaning |
|---|---|---|---|
| `get_doctor_availability.input.date` | `{"anyOf":[{"maxLength":10,"type":"string"},{"type":"null"}]}` | optional | 'today' or YYYY-MM-DD; required in each AVAILABILITY request, optional for WORKING_HOURS. Other relative dates are not accepted. |
| `get_doctor_availability.input.departmentId` | `{"anyOf":[{"maxLength":64,"type":"string"},{"type":"null"}]}` | optional | Directory identifier for a selected department; optional alternative to departmentName. |
| `get_doctor_availability.input.departmentName` | `{"anyOf":[{"maxLength":100,"type":"string"},{"type":"null"}]}` | optional | Department or speciality name for directory search; optional. |
| `get_doctor_availability.input.doctorId` | `{"anyOf":[{"maxLength":64,"type":"string"},{"type":"null"}]}` | optional | Directory identifier for a selected doctor, from doctors[] or choices[]; gives a doctor-specific result and takes precedence over doctorName and department fields; optional. |
| `get_doctor_availability.input.doctorName` | `{"anyOf":[{"maxLength":100,"type":"string"},{"type":"null"}]}` | optional | Doctor name for directory search, in the caller's original wording; optional. Exactly one match gives a doctor-specific result; several matches return choices. |
| `get_doctor_availability.input.gender` | `{"anyOf":[{"enum":["FEMALE","MALE"],"type":"string"},{"type":"null"}]}` | optional | Optional doctor gender filter: FEMALE or MALE. |
| `get_doctor_availability.input.purpose` | `{"enum":["AVAILABILITY","WORKING_HOURS"],"type":"string"}` | optional | AVAILABILITY (default) checks a requested date; WORKING_HOURS returns normal working hours or attendance days, not live availability. |
| `get_doctor_availability.input.session` | `{"anyOf":[{"maxLength":40,"type":"string"},{"type":"null"}]}` | optional | Optional selected session label; limits requested-date or working-hours sessions. Blank means no selection. |

### get_doctor_availability output

| Field | Wire type | Required | Meaning |
|---|---|---|---|
| `get_doctor_availability.output.basis` | `{"anyOf":[{"$ref":"#/$defs/Basis"},{"type":"null"}]}` | optional | LIVE_BOARD for today's AVAILABILITY; USUAL_SCHEDULE for future dates and WORKING_HOURS. |
| `get_doctor_availability.output.bookableFound` | `{"type":"integer"}` | optional | Bookable doctors found among those checked; may exceed the capped list. Always zero for WORKING_HOURS. |
| `get_doctor_availability.output.callback` | `{"anyOf":[{"$ref":"#/$defs/Callback"},{"type":"null"}]}` | optional | Present only with CALLBACK_REQUIRED: the callback reason and summaryOutcome CALLBACK_NOTED. No callback task is created. |
| `get_doctor_availability.output.choices` | `{"items":{"$ref":"#/$defs/DoctorChoice"},"type":"array"}` | optional | Doctors matching a doctorName with several directory matches, capped by the configured limit; a doctorId from here gives a doctor-specific result. |
| `get_doctor_availability.output.complete` | `{"type":"boolean"}` | optional | Every directory candidate was evaluated; no failed or unchecked reads. |
| `get_doctor_availability.output.department` | `{"anyOf":[{"$ref":"#/$defs/DepartmentChoice"},{"type":"null"}]}` | optional | Resolved department (id and name) for a department request; null for doctor requests. |
| `get_doctor_availability.output.departmentChoices` | `{"items":{"$ref":"#/$defs/DepartmentChoice"},"type":"array"}` | optional | Departments with consultants, returned when departmentName or departmentId matched none or several; a departmentId from here gives a department result. |
| `get_doctor_availability.output.detail` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Machine-readable cause for a non-success result: a Reason code (Reason table) or a validation or read-failure detail (Detail table). |
| `get_doctor_availability.output.doctors` | `{"items":{"$ref":"#/$defs/DoctorAvailability"},"type":"array"}` | optional | Resolved doctors with their decisions and session facts (capped for department requests). |
| `get_doctor_availability.output.facilityToday` | `{"type":"string"}` | required | Current calendar date in the configured facility timezone (YYYY-MM-DD). |
| `get_doctor_availability.output.nextStep` | `{"enum":["OFFER_APPOINTMENT_REQUEST","ASK_WHICH_DOCTOR","ASK_WHICH_DEPARTMENT","ASK_CALLBACK_DETAILS","TRANSFER_DESK","ASK_TO_REPHRASE","SAY_COULD_NOT_CHECK","ASK_EXPLICIT_DATE","ASK_WHICH_SESSION","OFFER_OTHER_SESSION_OR_DATE","PRESENT_WORKING_HOURS"],"type":"string"}` | required | Disposition code; see nextStep codes. |
| `get_doctor_availability.output.outcome` | `{"enum":["AVAILABILITY","CLARIFICATION_NEEDED","CALLBACK_REQUIRED","NOT_FOUND","COULD_NOT_CHECK","INVALID_REQUEST","NOT_AVAILABLE","WORKING_HOURS","HANDOFF_REQUIRED","DOCTORS_MATCHED"],"type":"string"}` | required | Result category; see Outcome codes. |
| `get_doctor_availability.output.requestedDate` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Resolved availability date (YYYY-MM-DD), or null when unresolved. |
| `get_doctor_availability.output.retryAfterSeconds` | `{"anyOf":[{"type":"integer"},{"type":"null"}]}` | optional | Delay in seconds requested by the owner service after a temporary failure; null otherwise. |
| `get_doctor_availability.output.sessionMatched` | `{"anyOf":[{"type":"boolean"},{"type":"null"}]}` | optional | With a session argument: whether that label matched a session for the requested date; null without a session argument. |
| `get_doctor_availability.output.totalMatches` | `{"anyOf":[{"type":"integer"},{"type":"null"}]}` | optional | Directory count across all attendance types and decisions. |
| `get_doctor_availability.output.weekday` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Weekday of the requested date, or null when unresolved. |

### manage_booking input

| Field | Wire type | Required | Meaning |
|---|---|---|---|
| `manage_booking.input.action` | `{"enum":["CREATE","LIST","CANCEL","RESCHEDULE"],"type":"string"}` | required | Required action: CREATE, LIST, CANCEL or RESCHEDULE. |
| `manage_booking.input.appointmentId` | `{"anyOf":[{"maxLength":64,"type":"string"},{"type":"null"}]}` | optional | Required for CANCEL/RESCHEDULE: identifier of the appointment request. |
| `manage_booking.input.callerConfirmed` | `{"type":"boolean"}` | optional | Boolean declaring the caller's approval of this write; true is required for CREATE/CANCEL/RESCHEDULE. |
| `manage_booking.input.doctorId` | `{"anyOf":[{"maxLength":64,"type":"string"},{"type":"null"}]}` | optional | Required for CREATE: identifier of the selected doctor. Department-level appointments are unsupported. |
| `manage_booking.input.fromDate` | `{"anyOf":[{"maxLength":10,"pattern":"^\\d{4}-\\d{2}-\\d{2}$","type":"string"},{"type":"null"}]}` | optional | Optional LIST lower date filter in YYYY-MM-DD format; past dates are accepted. |
| `manage_booking.input.newPreferredTime` | `{"anyOf":[{"maxLength":5,"pattern":"^\\d{2}:\\d{2}$","type":"string"},{"type":"null"}]}` | optional | RESCHEDULE time in HH:MM 24-hour format; required when slots are enabled, chosen within returned openSlots. Optional when slots are disabled. |
| `manage_booking.input.newVisitDate` | `{"anyOf":[{"maxLength":10,"type":"string"},{"type":"null"}]}` | optional | Required for RESCHEDULE: 'today' or YYYY-MM-DD, on or after the facility date. |
| `manage_booking.input.patientMobile` | `{"anyOf":[{"maxLength":20,"type":"string"},{"type":"null"}]}` | optional | Required for CREATE: 10-digit contact mobile. This is contact data, not caller authority. |
| `manage_booking.input.patientName` | `{"anyOf":[{"maxLength":100,"type":"string"},{"type":"null"}]}` | optional | Required for CREATE: patient name; nonblank, at most 100 characters. |
| `manage_booking.input.preferredTime` | `{"anyOf":[{"maxLength":5,"pattern":"^\\d{2}:\\d{2}$","type":"string"},{"type":"null"}]}` | optional | CREATE time in HH:MM 24-hour format; required when slots are enabled, chosen within returned openSlots. Optional when slots are disabled; a request, not a reservation. |
| `manage_booking.input.reasonVerbatim` | `{"anyOf":[{"maxLength":500,"type":"string"},{"type":"null"}]}` | optional | Optional CREATE/CANCEL reason in the caller's original words; forwarded without interpretation. |
| `manage_booking.input.session` | `{"anyOf":[{"maxLength":40,"type":"string"},{"type":"null"}]}` | optional | Optional CREATE or RESCHEDULE session label; blank means no selection. With slots enabled, a supplied label must match the session containing the chosen time; an unlabelled session cannot match it. Internal MCP context, absent from the owner request. With slots disabled, a session or time selection resolves differing decisions. |
| `manage_booking.input.status` | `{"anyOf":[{"enum":["NOTED","CONFIRMED_BY_DESK","CHANGED","CANCELLED"],"type":"string"},{"type":"null"}]}` | optional | Optional LIST appointment-status filter. |
| `manage_booking.input.toDate` | `{"anyOf":[{"maxLength":10,"pattern":"^\\d{4}-\\d{2}-\\d{2}$","type":"string"},{"type":"null"}]}` | optional | Optional LIST upper date filter in YYYY-MM-DD format; past dates are accepted. |
| `manage_booking.input.visitDate` | `{"anyOf":[{"maxLength":10,"type":"string"},{"type":"null"}]}` | optional | Required for CREATE: 'today' or YYYY-MM-DD, on or after the facility date. |

### manage_booking output

| Field | Wire type | Required | Meaning |
|---|---|---|---|
| `manage_booking.output.appointment` | `{"anyOf":[{"$ref":"#/$defs/AppointmentOut"},{"type":"null"}]}` | optional | The appointment returned by a successful CREATE, CANCEL or RESCHEDULE. |
| `manage_booking.output.appointments` | `{"items":{"$ref":"#/$defs/AppointmentOut"},"type":"array"}` | optional | The verified caller's appointments returned by LIST (from today unless fromDate is given). |
| `manage_booking.output.callback` | `{"anyOf":[{"$ref":"#/$defs/Callback"},{"type":"null"}]}` | optional | Present only with CALLBACK_REQUIRED: the callback reason and summaryOutcome CALLBACK_NOTED. No callback task is created. |
| `manage_booking.output.detail` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Machine-readable cause for a non-success result (Reason or Detail table); null on success. |
| `manage_booking.output.fields` | `{"items":{"type":"string"},"type":"array"}` | optional | Tool argument names that were missing, invalid or rejected; owner field names are translated, and names with no tool argument are dropped. |
| `manage_booking.output.nextStep` | `{"enum":["SAY_REQUEST_NOTED","SAY_CHANGED","SAY_CANCELLED","OFFER_CHOICES","SAY_NOT_FOUND","ASK_TO_CORRECT","SAY_UNCERTAIN_AND_TRANSFER","TRANSFER_DESK","ASK_CALLBACK_DETAILS","ASK_CONFIRMATION","SAY_COULD_NOT_RECORD","SAY_COULD_NOT_CHECK","ASK_WHICH_SESSION","OFFER_OTHER_SESSION_OR_TIME","OFFER_OTHER_SESSION_OR_DATE","ASK_WHICH_TIME"],"type":"string"}` | required | Disposition code; see nextStep codes. |
| `manage_booking.output.outcome` | `{"enum":["NOTED","CHANGED","CANCELLED","FOUND","NOT_FOUND","REJECTED","CONFLICT","UNCERTAIN","IDENTITY_UNAVAILABLE","CALLBACK_REQUIRED","NOT_AVAILABLE","HANDOFF_REQUIRED","CONFIRMATION_REQUIRED","OPERATION_CONTEXT_MISSING","COULD_NOT_RECORD","COULD_NOT_CHECK","INVALID_REQUEST"],"type":"string"}` | required | Result category; see Outcome codes. |
| `manage_booking.output.retryAfterSeconds` | `{"anyOf":[{"type":"integer"},{"type":"null"}]}` | optional | Delay in seconds requested by the owner service after a temporary failure; null otherwise. |
| `manage_booking.output.sessions` | `{"items":{"anyOf":[{"$ref":"#/$defs/BoardSessionOut"},{"$ref":"#/$defs/UsualSessionOut"}]},"type":"array"}` | optional | Checked sessions with openSlots for that doctor and date, returned with ASK_WHICH_TIME, ASK_WHICH_SESSION and NOT_AVAILABLE; empty otherwise. An empty list establishes nothing about other times. |

### record_call_summary input

| Field | Wire type | Required | Meaning |
|---|---|---|---|
| `record_call_summary.input.appointmentId` | `{"anyOf":[{"maxLength":64,"type":"string"},{"type":"null"}]}` | optional | Optional identifier of the appointment request associated with the call. |
| `record_call_summary.input.callerMobile` | `{"anyOf":[{"maxLength":20,"type":"string"},{"type":"null"}]}` | optional | Callback number the caller gave; required for CALLBACK_NOTED; distinct from caller ID. |
| `record_call_summary.input.doctorId` | `{"anyOf":[{"maxLength":64,"type":"string"},{"type":"null"}]}` | optional | Optional identifier of the doctor associated with the call. |
| `record_call_summary.input.intent` | `{"enum":["AVAILABILITY","BOOKING","RESCHEDULE","CANCEL","GENERAL_INFO","LAB","INSURANCE","EMERGENCY","AMBULANCE","SYMPTOM_ROUTING","COMPLAINT","ADMIN","OTHER"],"type":"string"}` | required | Required call-intent category. |
| `record_call_summary.input.language` | `{"anyOf":[{"maxLength":16,"type":"string"},{"type":"null"}]}` | optional | Optional call language; en, kn and hi primary codes map to the operational contract. Other codes are omitted upstream. |
| `record_call_summary.input.outcome` | `{"enum":["RESOLVED_BY_AGENT","APPOINTMENT_NOTED","APPOINTMENT_CANCELLED","APPOINTMENT_RESCHEDULED","TRANSFERRED","EMERGENCY_TRANSFERRED","AMBULANCE_NUMBER_GIVEN","CALLBACK_NOTED","ABANDONED"],"type":"string"}` | required | Required hospital-facing call outcome category. |
| `record_call_summary.input.summaryText` | `{"maxLength":500,"type":"string"}` | required | Required. Summary of the whole call in plain sentences, up to 500 characters: what the caller asked, what was explained or done, and any follow-up promised. Contains all relevant information mentioned in the call, including: the caller's name, the callback phone number, the symptoms or reason the caller described, the doctor's name, the department, and the requested date, time, session and callback reason. Not a transcript. |
| `record_call_summary.input.transferredTo` | `{"anyOf":[{"maxLength":64,"type":"string"},{"type":"null"}]}` | optional | Optional destination associated with a transfer outcome. |

### record_call_summary output

| Field | Wire type | Required | Meaning |
|---|---|---|---|
| `record_call_summary.output.fields` | `{"items":{"type":"string"},"type":"array"}` | optional | Names of rejected fields; present only on INVALID_REQUEST, possibly empty when no safe field names are available. |
| `record_call_summary.output.outcome` | `{"enum":["SAVED","ALREADY_SAVED","INVALID_REQUEST","NOT_CONFIRMED","NOT_SAVED"],"type":"string"}` | required | Result category; see Outcome codes. |

### Shared output types (each described once; identical in every tool that returns it)

| Field | Wire type | Required | Meaning |
|---|---|---|---|
| `$defs.AppointmentOut.appointmentId` | `{"type":"string"}` | required | Operational appointment request identifier. |
| `$defs.AppointmentOut.department` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Owner department identifier when the owner supplies one; null otherwise. |
| `$defs.AppointmentOut.doctorId` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Operational doctor identifier. |
| `$defs.AppointmentOut.expectedTime` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Time requested for the appointment (HH:MM), as recorded by the owner; not a reservation. |
| `$defs.AppointmentOut.patientName` | `{"type":"string"}` | required | Name on the appointment request; LIST is restricted to the verified caller’s own records. |
| `$defs.AppointmentOut.slotMoved` | `{"type":"boolean"}` | optional | True only when the owner moved CREATE or RESCHEDULE to a different block, for example for a late doctor or a passed time. Choosing 10:45 and receiving its 10:30 block start is not moved. False for LIST and CANCEL. |
| `$defs.AppointmentOut.slotTime` | `{"anyOf":[{"pattern":"^([01][0-9]|2[0-3]):[0-5][0-9]$","type":"string"},{"type":"null"}]}` | optional | Time recorded for this request in HH:MM facility local time: the owner's slotTime (block start), otherwise the request's expectedTime, otherwise null. |
| `$defs.AppointmentOut.status` | `{"enum":["NOTED","CONFIRMED_BY_DESK","CHANGED","CANCELLED"],"type":"string"}` | required | Manoj's appointment status, unchanged (including CHANGED after reschedule). |
| `$defs.AppointmentOut.visitDate` | `{"type":"string"}` | required | Appointment visit date (YYYY-MM-DD). |
| `$defs.BoardSessionOut.decision` | `{"$ref":"#/$defs/Decision"}` | required | MCP decision for this session; see Decision table. Separate from the owner status. |
| `$defs.BoardSessionOut.delayMinutes` | `{"anyOf":[{"type":"integer"},{"type":"null"}]}` | optional | Board delay in minutes when supplied. |
| `$defs.BoardSessionOut.expectedEndTime` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Board expected end time in facility local time when supplied. |
| `$defs.BoardSessionOut.expectedTime` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Board expected start time (HH:MM) when supplied. |
| `$defs.BoardSessionOut.isStale` | `{"type":"boolean"}` | required | Owner-supplied board staleness flag; not an adapter-computed age threshold. |
| `$defs.BoardSessionOut.note` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Owner-authored caller-facing board note, limited to 200 characters. |
| `$defs.BoardSessionOut.openSlots` | `{"anyOf":[{"items":{"$ref":"#/$defs/SlotOut"},"type":"array"},{"type":"null"}]}` | optional | Open blocks offered for this session and date: the owner's open blocks when the session permits a request. null means slots were not checked (disabled, WORKING_HOURS, or a department search pending doctor selection); [] means checked and no block is offered (none open, or the session does not permit a request). When slots apply, CREATE or RESCHEDULE times outside these blocks are refused. |
| `$defs.BoardSessionOut.reason` | `{"anyOf":[{"$ref":"#/$defs/Reason"},{"type":"null"}]}` | optional | Reason code qualifying the decision (Reason table); null when none applies. |
| `$defs.BoardSessionOut.session` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | required | Board session label when present. |
| `$defs.BoardSessionOut.status` | `{"enum":["IN","LATE","CANCELLED","NOT_CONFIRMED","UNKNOWN"],"type":"string"}` | required | Manoj's board or slot-only session status; MCP decision is separate. |
| `$defs.Callback.reason` | `{"$ref":"#/$defs/Reason"}` | required | Required machine-readable reason for callback. |
| `$defs.Callback.summaryOutcome` | `{"const":"CALLBACK_NOTED","type":"string"}` | optional | CALLBACK_NOTED identifies the callback call-summary category. |
| `$defs.DepartmentChoice.id` | `{"type":"string"}` | required | Department directory identifier. |
| `$defs.DepartmentChoice.name` | `{"type":"string"}` | required | Department display name. |
| `$defs.DoctorAvailability.attendanceType` | `{"enum":["REGULAR","VISITING","ON_CALL"],"type":"string"}` | required | Operational attendance classification: REGULAR, VISITING or ON_CALL. |
| `$defs.DoctorAvailability.board` | `{"items":{"$ref":"#/$defs/BoardSessionOut"},"type":"array"}` | required | Today's board rows for this doctor (LIVE_BOARD); empty for future dates and WORKING_HOURS. |
| `$defs.DoctorAvailability.dataConfirmed` | `{"anyOf":[{"type":"boolean"},{"type":"null"}]}` | optional | Hospital profile confirmation metadata, passed through unchanged; null means unspecified. Not used by any MCP decision: false does not mean unavailable or callback. |
| `$defs.DoctorAvailability.decision` | `{"$ref":"#/$defs/Decision"}` | required | MCP decision for this doctor on the requested scope; see Decision table. |
| `$defs.DoctorAvailability.departments` | `{"items":{"type":"string"},"type":"array"}` | required | Department names associated with the doctor. |
| `$defs.DoctorAvailability.doctorId` | `{"type":"string"}` | required | Operational doctor identifier. |
| `$defs.DoctorAvailability.gender` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Doctor gender when the directory supplies it. |
| `$defs.DoctorAvailability.name` | `{"type":"string"}` | required | Doctor display name. |
| `$defs.DoctorAvailability.reason` | `{"anyOf":[{"$ref":"#/$defs/Reason"},{"type":"null"}]}` | optional | Reason code qualifying the doctor decision (Reason table); null when none applies. |
| `$defs.DoctorAvailability.sessionChoiceRequired` | `{"type":"boolean"}` | optional | Whether differing session decisions require a session choice. |
| `$defs.DoctorAvailability.usualSessions` | `{"anyOf":[{"items":{"$ref":"#/$defs/UsualSessionOut"},"type":"array"},{"type":"null"}]}` | required | Requested-date sessions (with slot facts when read) and desk-added one-day sessions for future dates, or usual working hours for WORKING_HOURS; null when not fetched (today's live board is in board). |
| `$defs.DoctorChoice.departments` | `{"items":{"type":"string"},"type":"array"}` | required | Department names associated with the doctor. |
| `$defs.DoctorChoice.doctorId` | `{"type":"string"}` | required | Operational doctor identifier. |
| `$defs.DoctorChoice.gender` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Doctor gender when the directory supplies it. |
| `$defs.DoctorChoice.name` | `{"type":"string"}` | required | Doctor display name. |
| `$defs.SlotOut.available` | `{"minimum":0,"type":"integer"}` | required | Remaining places reported by the owner for this block; MCP does not compute capacity or reserve a place. |
| `$defs.SlotOut.end` | `{"pattern":"^([01][0-9]|2[0-3]):[0-5][0-9]$","type":"string"}` | required | Open block end in HH:MM facility local time, exclusive. |
| `$defs.SlotOut.start` | `{"pattern":"^([01][0-9]|2[0-3]):[0-5][0-9]$","type":"string"}` | required | Open block start in HH:MM facility local time, inclusive. |
| `$defs.UsualSessionOut.daysOfWeek` | `{"items":{"type":"string"},"type":"array"}` | required | Weekday codes for a usual session; empty for a desk-added one-day session. |
| `$defs.UsualSessionOut.decision` | `{"$ref":"#/$defs/Decision"}` | required | MCP decision for this session; see Decision table. Separate from the owner status. |
| `$defs.UsualSessionOut.end` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | required | Session end in facility local time. null only for a one-day session whose hours the owner did not supply. Such a session has no bookable time. |
| `$defs.UsualSessionOut.label` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | required | Usual or one-day session label, possibly null. |
| `$defs.UsualSessionOut.onRequestedDate` | `{"anyOf":[{"type":"boolean"},{"type":"null"}]}` | required | Whether the session belongs to the requested date; true for a one-day session, null when no date was supplied. |
| `$defs.UsualSessionOut.oneDay` | `{"type":"boolean"}` | optional | A session the desk added for the requested date only; not part of the regular schedule. |
| `$defs.UsualSessionOut.openSlots` | `{"anyOf":[{"items":{"$ref":"#/$defs/SlotOut"},"type":"array"},{"type":"null"}]}` | optional | Open blocks offered for this session and date: the owner's open blocks when the session permits a request. null means slots were not checked (disabled, WORKING_HOURS, or a department search pending doctor selection); [] means checked and no block is offered (none open, or the session does not permit a request). When slots apply, CREATE or RESCHEDULE times outside these blocks are refused. |
| `$defs.UsualSessionOut.reason` | `{"anyOf":[{"$ref":"#/$defs/Reason"},{"type":"null"}]}` | optional | Reason code qualifying the decision (Reason table); null when none applies. |
| `$defs.UsualSessionOut.start` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | required | Session start in facility local time. null only for a one-day session whose hours the owner did not supply. Such a session has no bookable time. |
| `$defs.UsualSessionOut.status` | `{"anyOf":[{"enum":["IN","LATE","CANCELLED","NOT_CONFIRMED","UNKNOWN"],"type":"string"},{"type":"null"}]}` | optional | Owner's slot status for this session on the requested date; null when slots were not checked. |
