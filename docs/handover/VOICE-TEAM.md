# MCP tool interface

Schema version: `2026-10-08.1`

## Endpoint and transport

Streamable HTTP at `/mcp/` on the configured MCP host. The direct URL is the deployment's
`MCP_PUBLIC_URL`; for example, `https://<mcp-host>/mcp/`. The ContextForge virtual-server URL is a
separate gateway endpoint supplied by its owner; the voice agent normally calls tools through it.

Deployed: Azure canary `mcp-demo-hospital-canary`, image `frontdesk-mcp:36336aa`, schema `2026-10-06.1`
(6 October 2026). This document describes schema `2026-10-08.1` for the slots release; the canary still runs
`2026-10-06.1` until that release is deployed. `GET /ready` returns the served `schemaVersion`;
`tools/list` describes the contract actually deployed.

## Authentication

| Scope | Direct MCP bearer | Accessible tools |
|---|---|---|
| Gateway | MCP_BEARER_TOKEN | get_doctor_availability, manage_booking, search_knowledge, record_call_summary |

The HTTP header is `Authorization: Bearer <credential>`. All four tools use gateway authentication.
A ContextForge client authenticates with gateway-issued scoped access; its upstream MCP bearer is
separate. Credentials, caller authority and call start time are not tool arguments.

## Trusted request headers

| Header | Meaning and format |
|---|---|
| X-Call-Id | Platform call identifier: 1–64 ASCII letters, digits, dots, underscores, colons or hyphens. Required for booking writes and summaries. |
| X-Caller-Number | Trusted caller number under the configured calling-code rule. With accepted verification, authorizes LIST/CANCEL/RESCHEDULE. Distinct from contact fields. |
| X-Caller-Verification | Verification label in ACCEPTED_CALLER_VERIFICATION; default SIP_CALLER_ID. A number alone does not establish authority. |
| X-Operation-Id | Confirmed-write identifier with the same 1–64 character syntax as call ID. Required for CREATE/CANCEL/RESCHEDULE. Same call/action/operation identifies the same payload; changed payload conflicts. |
| X-Call-Started-At | ISO timestamp with timezone offset; required for record_call_summary. |

Malformed identifiers/timing are treated as absent. Header names are case-insensitive. Tenant comes from deployment configuration; access is authenticated by the gateway bearer, not model arguments.

## Calling contract

These interface facts apply to every tool.

1. **The live schema is `tools/list`.** The MCP server publishes each tool's exact input schema, output
   schema and description. The input schemas below are copied from the pinned snapshot for schema
   `2026-10-08.1`. If `tools/list` and this document disagree, `tools/list` wins.
2. **Unknown arguments are rejected.** An unknown argument (for example `doctorName` on
   `manage_booking`, or `callerName` on `record_call_summary`) is rejected before the tool runs, even
   though the published schema does not explicitly declare this boundary rule.
3. **Optional fields may be absent.** `null` is accepted where the schema type includes `null`.
   `purpose`, `callerConfirmed`, `action`, `intent`, `outcome`, `question`, `language` and `summaryText`
   do not accept `null`.
4. **Formats are exact.** Enums are upper case. Dates are `today` or `YYYY-MM-DD` (facility calendar,
   not in the past); `tomorrow`, `next Monday` and similar are refused. `facilityToday` in an availability
   result supplies the facility date reference. Times are 24-hour `HH:MM`
   (`00:00`–`23:59`). Mobiles are exactly 10 digits, with no `+91`, spaces or dashes.
5. **Identifiers refer to owner records.** `doctorId` comes from `doctors[].doctorId` or
   `choices[].doctorId`; `departmentId` from `department.id` or `departmentChoices[].id`; `session` from
   `board[].session` or `usualSessions[].label`; `appointmentId` from `appointment.appointmentId` or
   `appointments[].appointmentId`. Fabricated identifiers do not establish a matching owner record.
6. **Two kinds of failure.**
   - `isError: true` with a text message and no structured result: the arguments were rejected before the
     tool ran (unknown field, wrong type, enum mismatch, value over `maxLength`; `summaryText` over 500
     characters is the exception and returns `INVALID_REQUEST`). An identical retry fails the same way. For `record_call_summary` the message is deliberately generic and
     does not name the field.
   - A normal structured result with `outcome` such as `INVALID_REQUEST`: the tool ran and refused the
     request. `fields` (booking, summary) or `detail` (availability) names what to correct.
7. **`outcome` and `nextStep` identify the result and disposition.** Every structured result has `outcome`; all except
   `record_call_summary` also have `nextStep`. The meanings are in each tool's tables below.
8. **Trusted headers come from the platform on the MCP request.** They are not tool
   arguments. Which tool needs which header:

| Tool and action | Authorization | X-Call-Id | X-Operation-Id | X-Caller-Number + X-Caller-Verification | X-Call-Started-At |
|---|---|---|---|---|---|
| get_doctor_availability | required | not used | not used | not used | not used |
| search_knowledge | required | not used | not used | not used | not used |
| manage_booking CREATE | required | required | required | not used | not used |
| manage_booking LIST | required | not used | not used | required | not used |
| manage_booking CANCEL, RESCHEDULE | required | required | required | required | not used |
| record_call_summary | required | required | not used | not used | required |

Missing write headers return `OPERATION_CONTEXT_MISSING`; missing or unverified caller identity returns
`IDENTITY_UNAVAILABLE`; missing summary headers return `NOT_SAVED`. Each distinct confirmed write
has its own `X-Operation-Id`. An identical retry has the same id; different arguments with that id
return `CONFLICT`. `UNCERTAIN` has desk handoff as its disposition, not retry. A later invocation with
the same operation id re-runs the schedule check and can be refused; refusal does not prove that the
earlier write failed. A new operation id identifies another write, not a replay of the uncertain write.

| Tool | Read-only | Changes data | Safe to retry with the same arguments |
|---|---|---|---|
| get_doctor_availability | yes | no | yes |
| search_knowledge | yes | no | yes |
| manage_booking | LIST only | CREATE, CANCEL, RESCHEDULE | same `X-Operation-Id` and identical arguments; a fresh schedule check can refuse the retry |
| record_call_summary | no | stores one summary per call | yes; a repeat returns `ALREADY_SAVED` |

The tables below describe the pinned wire schema, including nested `$defs` types. “Required” means
schema-required; action-specific requirements appear in the meaning column. Optional fields can have
server defaults; the schema remains authoritative for those defaults. Callback metadata contains reason and summaryOutcome only, with no spoken script. Outcomes and nextStep are returned codes,
not implementation instructions for the calling application.

## get_doctor_availability

Doctor or department availability for today or an explicit future date; WORKING_HOURS returns usual hours without board or slot checks. Today is LIVE_BOARD: status is Manoj's IN, LATE, CANCELLED, NOT_CONFIRMED or UNKNOWN; decision is the separate MCP result. With slots enabled, a selected doctor's date is checked against slots: openSlots lists the owner's open blocks when the session permits a request; [] means checked and no block is offered (none open, or the session does not permit a request), null means not checked. For ordinary doctors, UNKNOWN always requires callback, even if another source says CANCELLED; NOT_CONFIRMED with an open bookable block permits a request, noted for desk confirmation. CANCELLED is NOT_AVAILABLE; no open slot is NOT_AVAILABLE/NO_OPEN_SLOT. A supplied passed end time means NOT_AVAILABLE/SESSION_ENDED; a missing end time is not an ended session. An ON_CALL doctor needs a confirmed IN/LATE entry with a usable window or open block; otherwise HANDOFF_REQUIRED means desk assistance, without callback metadata. A cancelled on-call session remains NOT_AVAILABLE. Future dates rely on slots when enabled, including desk-added oneDay sessions for that date only; a one-day session with null hours has no bookable time. With slots disabled, IN/LATE permit a request today, ordinary NOT_CONFIRMED/UNKNOWN require callback, and future regular/visiting hours describe usual attendance days, attendance not confirmed. Several sessions with the same decision require no session choice; differing decisions may require one. Department searches with slots enabled return DOCTORS_MATCHED and SLOT_CHECK_REQUIRED when doctors match: doctors match the request, not yet available; slot availability is known after a doctor-specific check, with bookableFound=0 for these matches. With slots disabled, department AVAILABILITY lists bookable doctors when any exist; otherwise callback, handoff or unavailable facts. Results are capped by the configured limit. totalMatches is the directory count across all types and decisions; bookableFound counts bookable doctors found among those checked, potentially more than the returned list; complete means every directory candidate was evaluated, not that every doctor's slots were read. An incomplete search with no match is HANDOFF_REQUIRED/SEARCH_INCOMPLETE, not unavailability. WORKING_HOURS with hours returns PRESENT_WORKING_HOURS for one doctor and always bookableFound=0; an empty ordinary schedule returns CALLBACK_REQUIRED, while an on-call doctor requires HANDOFF_REQUIRED. Department WORKING_HOURS keeps on-call handoff facts within the list limit. Callback details are stored only in record_call_summary as CALLBACK_NOTED. Ambiguous names return choices.

### How to call

| Query | Parameters |
|---|---|
| Target (exactly one kind) | `doctorId`, else `doctorName`, else `departmentId` or `departmentName`. If several are sent, the first in this order is used. None returns `INVALID_REQUEST` with detail `TARGET_REQUIRED`. |
| Availability on a date | `purpose` omitted (or `AVAILABILITY`) and `date` = `today` or `YYYY-MM-DD`. Without `date`: `INVALID_REQUEST`/`ASK_EXPLICIT_DATE`, detail `DATE_REQUIRED`. Other words: `DATE_FORMAT`. Past dates: `PAST_DATE`. |
| Usual working hours | `purpose` = `WORKING_HOURS`; `date` optional. No live-board or slot read. An on-call doctor has no usual hours and requires desk handoff. |
| One session only | `session` = a label returned earlier (`board[].session` or `usualSessions[].label`). |
| Female or male doctor | `gender` = `FEMALE` or `MALE`. |
| After `ASK_WHICH_DOCTOR` / `ASK_WHICH_DEPARTMENT` | The chosen `doctorId` or `departmentId` identifies the target of a subsequent check for the same `date` and `purpose`. |
| Before booking | `doctors[].doctorId` identifies the doctor. With slots enabled, the booking time belongs to that doctor's returned `openSlots`; `session` is optional and a supplied nonblank label must match that time's session. `sessionChoiceRequired` identifies unresolved session decisions. |

### Input schema (exact)

```json
{
  "properties": {
    "date": {
      "anyOf": [
        {
          "maxLength": 10,
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "'today' or YYYY-MM-DD; required for AVAILABILITY, optional for WORKING_HOURS. Other relative dates are not accepted."
    },
    "departmentId": {
      "anyOf": [
        {
          "maxLength": 64,
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Directory identifier for a selected department; optional alternative to departmentName."
    },
    "departmentName": {
      "anyOf": [
        {
          "maxLength": 100,
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Department or speciality name for directory search; optional."
    },
    "doctorId": {
      "anyOf": [
        {
          "maxLength": 64,
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Directory identifier for a selected doctor; optional alternative to doctorName."
    },
    "doctorName": {
      "anyOf": [
        {
          "maxLength": 100,
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Doctor name for directory search, in the caller's original wording; optional."
    },
    "gender": {
      "anyOf": [
        {
          "enum": [
            "FEMALE",
            "MALE"
          ],
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Optional doctor gender filter: FEMALE or MALE."
    },
    "purpose": {
      "default": "AVAILABILITY",
      "description": "AVAILABILITY (default) checks a requested date; WORKING_HOURS returns normal working hours or attendance days, not live availability.",
      "enum": [
        "AVAILABILITY",
        "WORKING_HOURS"
      ],
      "type": "string"
    },
    "session": {
      "anyOf": [
        {
          "maxLength": 40,
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Optional selected session label; limits requested-date or working-hours sessions. Blank means no selection."
    }
  },
  "type": "object"
}
```

### Parameters

| Field path | Type / constraints (JSON Schema) | Presence | Meaning |
|---|---|---|---|
| `get_doctor_availability.input.date` | `{"anyOf":[{"maxLength":10,"type":"string"},{"type":"null"}]}` | optional | 'today' or YYYY-MM-DD; required for AVAILABILITY, optional for WORKING_HOURS. Other relative dates are not accepted. |
| `get_doctor_availability.input.departmentId` | `{"anyOf":[{"maxLength":64,"type":"string"},{"type":"null"}]}` | optional | Directory identifier for a selected department; optional alternative to departmentName. |
| `get_doctor_availability.input.departmentName` | `{"anyOf":[{"maxLength":100,"type":"string"},{"type":"null"}]}` | optional | Department or speciality name for directory search; optional. |
| `get_doctor_availability.input.doctorId` | `{"anyOf":[{"maxLength":64,"type":"string"},{"type":"null"}]}` | optional | Directory identifier for a selected doctor; optional alternative to doctorName. |
| `get_doctor_availability.input.doctorName` | `{"anyOf":[{"maxLength":100,"type":"string"},{"type":"null"}]}` | optional | Doctor name for directory search, in the caller's original wording; optional. |
| `get_doctor_availability.input.gender` | `{"anyOf":[{"enum":["FEMALE","MALE"],"type":"string"},{"type":"null"}]}` | optional | Optional doctor gender filter: FEMALE or MALE. |
| `get_doctor_availability.input.purpose` | `{"enum":["AVAILABILITY","WORKING_HOURS"],"type":"string"}` | optional | AVAILABILITY (default) checks a requested date; WORKING_HOURS returns normal working hours or attendance days, not live availability. |
| `get_doctor_availability.input.session` | `{"anyOf":[{"maxLength":40,"type":"string"},{"type":"null"}]}` | optional | Optional selected session label; limits requested-date or working-hours sessions. Blank means no selection. |

### Output fields

| Field path | Type / constraints (JSON Schema) | Presence | Meaning |
|---|---|---|---|
| `get_doctor_availability.output.basis` | `{"anyOf":[{"$ref":"#/$defs/Basis"},{"type":"null"}]}` | optional | Source used for this answer: LIVE_BOARD for today, USUAL_SCHEDULE for future dates or working hours. |
| `get_doctor_availability.output.bookableFound` | `{"type":"integer"}` | optional | Bookable doctors found among those checked; may exceed the capped list. Always zero for WORKING_HOURS. |
| `get_doctor_availability.output.callback` | `{"anyOf":[{"$ref":"#/$defs/Callback"},{"type":"null"}]}` | optional | Callback reason and call-summary category; no separate callback action. |
| `get_doctor_availability.output.choices` | `{"items":{"$ref":"#/$defs/DoctorChoice"},"type":"array"}` | optional | Ambiguous doctor-directory matches. |
| `get_doctor_availability.output.complete` | `{"type":"boolean"}` | optional | Every directory candidate was evaluated; no failed or unchecked reads. |
| `get_doctor_availability.output.department` | `{"anyOf":[{"$ref":"#/$defs/DepartmentChoice"},{"type":"null"}]}` | optional | Resolved department object; within AppointmentOut, the operational department identifier. |
| `get_doctor_availability.output.departmentChoices` | `{"items":{"$ref":"#/$defs/DepartmentChoice"},"type":"array"}` | optional | Ambiguous department-directory matches. |
| `get_doctor_availability.output.detail` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Machine-readable reason for non-success outcomes. |
| `get_doctor_availability.output.doctors` | `{"items":{"$ref":"#/$defs/DoctorAvailability"},"type":"array"}` | optional | Resolved doctors with requested-date session facts or usual working hours, plus slot facts when checked. |
| `get_doctor_availability.output.facilityToday` | `{"type":"string"}` | required | Current calendar date in the configured facility timezone (YYYY-MM-DD). |
| `get_doctor_availability.output.nextStep` | `{"enum":["OFFER_APPOINTMENT_REQUEST","ASK_WHICH_DOCTOR","ASK_WHICH_DEPARTMENT","ASK_CALLBACK_DETAILS","TRANSFER_DESK","ASK_TO_REPHRASE","SAY_COULD_NOT_CHECK","ASK_EXPLICIT_DATE","ASK_WHICH_SESSION","OFFER_OTHER_SESSION_OR_DATE","PRESENT_WORKING_HOURS"],"type":"string"}` | required | Machine-readable disposition code, defined below. |
| `get_doctor_availability.output.outcome` | `{"enum":["AVAILABILITY","CLARIFICATION_NEEDED","CALLBACK_REQUIRED","NOT_FOUND","COULD_NOT_CHECK","INVALID_REQUEST","NOT_AVAILABLE","WORKING_HOURS","HANDOFF_REQUIRED","DOCTORS_MATCHED"],"type":"string"}` | required | Result category, defined below. |
| `get_doctor_availability.output.requestedDate` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Resolved availability date (YYYY-MM-DD), or null when unresolved. |
| `get_doctor_availability.output.retryAfterSeconds` | `{"anyOf":[{"type":"integer"},{"type":"null"}]}` | optional | Upstream retry delay in seconds when supplied; optional. |
| `get_doctor_availability.output.sessionMatched` | `{"anyOf":[{"type":"boolean"},{"type":"null"}]}` | optional | Whether the requested session matched; null when not evaluated. |
| `get_doctor_availability.output.totalMatches` | `{"anyOf":[{"type":"integer"},{"type":"null"}]}` | optional | Directory count across all attendance types and decisions. |
| `get_doctor_availability.output.weekday` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Weekday of the requested date, or null when unresolved. |
| `get_doctor_availability.output.$defs.BoardSessionOut.decision` | `{"$ref":"#/$defs/Decision"}` | required | MCP decision, distinct from owner status: APPOINTMENT_REQUEST, SLOT_CHECK_REQUIRED, CALLBACK_REQUIRED, HANDOFF_REQUIRED, NOT_AVAILABLE or COULD_NOT_CHECK. Decision meanings are listed below. |
| `get_doctor_availability.output.$defs.BoardSessionOut.delayMinutes` | `{"anyOf":[{"type":"integer"},{"type":"null"}]}` | optional | Board delay in minutes when supplied. |
| `get_doctor_availability.output.$defs.BoardSessionOut.expectedEndTime` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Board expected end time in facility local time when supplied. |
| `get_doctor_availability.output.$defs.BoardSessionOut.expectedTime` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Board expected start time or requested appointment time; not a guaranteed reservation. |
| `get_doctor_availability.output.$defs.BoardSessionOut.isStale` | `{"type":"boolean"}` | required | Owner-supplied board staleness flag; not an adapter-computed age threshold. |
| `get_doctor_availability.output.$defs.BoardSessionOut.note` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Owner-authored caller-facing board note, limited to 200 characters. |
| `get_doctor_availability.output.$defs.BoardSessionOut.openSlots` | `{"anyOf":[{"items":{"$ref":"#/$defs/SlotOut"},"type":"array"},{"type":"null"}]}` | optional | Open blocks offered for this session and date: the owner's open blocks when the session permits a request. null means slots were not checked (disabled, WORKING_HOURS, or a department search pending doctor selection); [] means checked and no block is offered (none open, or the session does not permit a request). When slots apply, CREATE or RESCHEDULE times outside these blocks are refused. |
| `get_doctor_availability.output.$defs.BoardSessionOut.reason` | `{"anyOf":[{"$ref":"#/$defs/Reason"},{"type":"null"}]}` | optional | Machine-readable reason for this decision; null when no qualification applies. |
| `get_doctor_availability.output.$defs.BoardSessionOut.session` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | required | Board session label when present. |
| `get_doctor_availability.output.$defs.BoardSessionOut.status` | `{"enum":["IN","LATE","CANCELLED","NOT_CONFIRMED","UNKNOWN"],"type":"string"}` | required | Manoj's board or slot-only session status; MCP decision is separate. |
| `get_doctor_availability.output.$defs.Callback.reason` | `{"$ref":"#/$defs/Reason"}` | required | Required machine-readable reason for callback. |
| `get_doctor_availability.output.$defs.Callback.summaryOutcome` | `{"const":"CALLBACK_NOTED","type":"string"}` | optional | CALLBACK_NOTED identifies the callback call-summary category. |
| `get_doctor_availability.output.$defs.DepartmentChoice.id` | `{"type":"string"}` | required | Department directory identifier. |
| `get_doctor_availability.output.$defs.DepartmentChoice.name` | `{"type":"string"}` | required | Doctor or department display name, according to its containing type. |
| `get_doctor_availability.output.$defs.DoctorAvailability.attendanceType` | `{"enum":["REGULAR","VISITING","ON_CALL"],"type":"string"}` | required | Operational attendance classification: REGULAR, VISITING or ON_CALL. |
| `get_doctor_availability.output.$defs.DoctorAvailability.board` | `{"items":{"$ref":"#/$defs/BoardSessionOut"},"type":"array"}` | required | Date/session-specific board rows. |
| `get_doctor_availability.output.$defs.DoctorAvailability.dataConfirmed` | `{"anyOf":[{"type":"boolean"},{"type":"null"}]}` | optional | Owner confirmation metadata; null means unspecified. |
| `get_doctor_availability.output.$defs.DoctorAvailability.decision` | `{"$ref":"#/$defs/Decision"}` | required | MCP decision, distinct from owner status: APPOINTMENT_REQUEST, SLOT_CHECK_REQUIRED, CALLBACK_REQUIRED, HANDOFF_REQUIRED, NOT_AVAILABLE or COULD_NOT_CHECK. Decision meanings are listed below. |
| `get_doctor_availability.output.$defs.DoctorAvailability.departments` | `{"items":{"type":"string"},"type":"array"}` | required | Department names associated with the doctor. |
| `get_doctor_availability.output.$defs.DoctorAvailability.doctorId` | `{"type":"string"}` | required | Operational doctor identifier. |
| `get_doctor_availability.output.$defs.DoctorAvailability.gender` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Doctor gender when available. |
| `get_doctor_availability.output.$defs.DoctorAvailability.name` | `{"type":"string"}` | required | Doctor or department display name, according to its containing type. |
| `get_doctor_availability.output.$defs.DoctorAvailability.reason` | `{"anyOf":[{"$ref":"#/$defs/Reason"},{"type":"null"}]}` | optional | Machine-readable reason for this decision; null when no qualification applies. |
| `get_doctor_availability.output.$defs.DoctorAvailability.sessionChoiceRequired` | `{"type":"boolean"}` | optional | Whether differing session decisions require a session choice. |
| `get_doctor_availability.output.$defs.DoctorAvailability.usualSessions` | `{"anyOf":[{"items":{"$ref":"#/$defs/UsualSessionOut"},"type":"array"},{"type":"null"}]}` | required | Requested-date sessions with their slot status and desk-added one-day sessions, or usual working hours for WORKING_HOURS. null when these session facts were not fetched. |
| `get_doctor_availability.output.$defs.DoctorChoice.departments` | `{"items":{"type":"string"},"type":"array"}` | required | Department names associated with the doctor. |
| `get_doctor_availability.output.$defs.DoctorChoice.doctorId` | `{"type":"string"}` | required | Operational doctor identifier. |
| `get_doctor_availability.output.$defs.DoctorChoice.gender` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Doctor gender when available. |
| `get_doctor_availability.output.$defs.DoctorChoice.name` | `{"type":"string"}` | required | Doctor or department display name, according to its containing type. |
| `get_doctor_availability.output.$defs.SlotOut.available` | `{"minimum":0,"type":"integer"}` | required | Remaining places reported by the owner for this block; MCP does not compute capacity or reserve a place. |
| `get_doctor_availability.output.$defs.SlotOut.end` | `{"pattern":"^([01][0-9]|2[0-3]):[0-5][0-9]$","type":"string"}` | required | Open block end in HH:MM facility local time, exclusive. |
| `get_doctor_availability.output.$defs.SlotOut.start` | `{"pattern":"^([01][0-9]|2[0-3]):[0-5][0-9]$","type":"string"}` | required | Open block start in HH:MM facility local time, inclusive. |
| `get_doctor_availability.output.$defs.UsualSessionOut.daysOfWeek` | `{"items":{"type":"string"},"type":"array"}` | required | Weekday codes for a usual session; empty for a desk-added one-day session. |
| `get_doctor_availability.output.$defs.UsualSessionOut.decision` | `{"$ref":"#/$defs/Decision"}` | required | MCP decision, distinct from owner status: APPOINTMENT_REQUEST, SLOT_CHECK_REQUIRED, CALLBACK_REQUIRED, HANDOFF_REQUIRED, NOT_AVAILABLE or COULD_NOT_CHECK. Decision meanings are listed below. |
| `get_doctor_availability.output.$defs.UsualSessionOut.end` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | required | Session end in facility local time. null only for a one-day session whose hours the owner did not supply. Such a session has no bookable time. |
| `get_doctor_availability.output.$defs.UsualSessionOut.label` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | required | Usual or one-day session label, possibly null. |
| `get_doctor_availability.output.$defs.UsualSessionOut.onRequestedDate` | `{"anyOf":[{"type":"boolean"},{"type":"null"}]}` | required | Whether the session belongs to the requested date; true for a one-day session, null when no date was supplied. |
| `get_doctor_availability.output.$defs.UsualSessionOut.oneDay` | `{"type":"boolean"}` | optional | A session the desk added for the requested date only; not part of the regular schedule. |
| `get_doctor_availability.output.$defs.UsualSessionOut.openSlots` | `{"anyOf":[{"items":{"$ref":"#/$defs/SlotOut"},"type":"array"},{"type":"null"}]}` | optional | Open blocks offered for this session and date: the owner's open blocks when the session permits a request. null means slots were not checked (disabled, WORKING_HOURS, or a department search pending doctor selection); [] means checked and no block is offered (none open, or the session does not permit a request). When slots apply, CREATE or RESCHEDULE times outside these blocks are refused. |
| `get_doctor_availability.output.$defs.UsualSessionOut.reason` | `{"anyOf":[{"$ref":"#/$defs/Reason"},{"type":"null"}]}` | optional | Machine-readable reason for this decision; null when no qualification applies. |
| `get_doctor_availability.output.$defs.UsualSessionOut.start` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | required | Session start in facility local time. null only for a one-day session whose hours the owner did not supply. Such a session has no bookable time. |
| `get_doctor_availability.output.$defs.UsualSessionOut.status` | `{"anyOf":[{"enum":["IN","LATE","CANCELLED","NOT_CONFIRMED","UNKNOWN"],"type":"string"},{"type":"null"}]}` | optional | Owner's slot status for this session on the requested date; null when slots were not checked. |

### Outcomes and nextStep meanings

| Code | Meaning |
|---|---|
| `get_doctor_availability.outcome.AVAILABILITY` | Requested-date facts are returned, with each doctor/session decision and any required selection. |
| `get_doctor_availability.outcome.DOCTORS_MATCHED` | Doctors match the department request; their slots have not been checked. Slot availability is known only after a doctor-specific check. This is not an availability claim; bookableFound is zero. |
| `get_doctor_availability.outcome.CLARIFICATION_NEEDED` | Multiple directory matches require a doctor or department selection. |
| `get_doctor_availability.outcome.CALLBACK_REQUIRED` | An ordinary doctor has an unresolved schedule: UNKNOWN, or NOT_CONFIRMED with slots disabled, or no usual schedule. No appointment write; callback details belong only to a CALLBACK_NOTED summary. On-call doctors have desk handoff as their disposition. |
| `get_doctor_availability.outcome.NOT_FOUND` | No matching doctor or department was found. |
| `get_doctor_availability.outcome.COULD_NOT_CHECK` | A read could not be completed; this is not an empty or negative result. |
| `get_doctor_availability.outcome.INVALID_REQUEST` | Request validation failed; fields or detail identify the issue when available. |
| `get_doctor_availability.outcome.NOT_AVAILABLE` | Valid request, but the selected schedule or session is unavailable. |
| `get_doctor_availability.outcome.WORKING_HOURS` | Normal working hours or attendance days; no live attendance check. |
| `get_doctor_availability.outcome.HANDOFF_REQUIRED` | Desk assistance is the disposition for an on-call doctor without a confirmed, usable entry, or incomplete search/time validation. No callback metadata; MCP does not perform the telephone transfer. |
| `get_doctor_availability.nextStep.OFFER_APPOINTMENT_REQUEST` | An appointment request is possible for the returned scope; this is not a reservation. |
| `get_doctor_availability.nextStep.ASK_WHICH_DOCTOR` | Doctor selection is required; a department match with slots enabled needs a doctor-specific slot check even when only one match is returned. |
| `get_doctor_availability.nextStep.ASK_WHICH_DEPARTMENT` | Multiple department matches require a selection. |
| `get_doctor_availability.nextStep.ASK_CALLBACK_DETAILS` | Callback policy requires contact details and a call summary; no appointment is written. |
| `get_doctor_availability.nextStep.TRANSFER_DESK` | Desk assistance is the returned disposition; MCP does not execute a telephone transfer. |
| `get_doctor_availability.nextStep.ASK_TO_REPHRASE` | The supplied name, department or question could not resolve the request. |
| `get_doctor_availability.nextStep.SAY_COULD_NOT_CHECK` | The requested information could not be checked. |
| `get_doctor_availability.nextStep.ASK_EXPLICIT_DATE` | An accepted calendar-date value is required. |
| `get_doctor_availability.nextStep.ASK_WHICH_SESSION` | Sessions have different decisions; a session selection is required. |
| `get_doctor_availability.nextStep.OFFER_OTHER_SESSION_OR_DATE` | The requested session or date is unavailable; alternatives may be returned. |
| `get_doctor_availability.nextStep.PRESENT_WORKING_HOURS` | Usual hours are returned for presentation, without an appointment offer or date-specific availability claim. |

### Examples

Examples come from the development stubs (facility date 2026-10-01, Thursday, 10:00); names and
identifiers are fixtures, with slots disabled. The new optional fields are shown at their defaults.
Slots-enabled behaviour is described above and will be activated in the complete release.

**1. Doctor today, two sessions with different decisions**

Arguments:

```json
{
  "doctorName": "garima",
  "date": "today"
}
```

Structured result:

```json
{
  "outcome": "AVAILABILITY",
  "nextStep": "ASK_WHICH_SESSION",
  "facilityToday": "2026-10-01",
  "requestedDate": "2026-10-01",
  "weekday": "THU",
  "department": null,
  "doctors": [
    {
      "doctorId": "doc_garima",
      "name": "Dr. Garima",
      "departments": [
        "General Medicine"
      ],
      "attendanceType": "REGULAR",
      "gender": "FEMALE",
      "dataConfirmed": null,
      "usualSessions": null,
      "board": [
        {
          "session": "Morning",
          "status": "IN",
          "expectedTime": "09:10",
          "expectedEndTime": "12:00",
          "delayMinutes": null,
          "note": null,
          "isStale": false,
          "decision": "APPOINTMENT_REQUEST",
          "reason": null,
          "openSlots": null
        },
        {
          "session": "Afternoon",
          "status": "NOT_CONFIRMED",
          "expectedTime": "15:00",
          "expectedEndTime": "17:00",
          "delayMinutes": null,
          "note": null,
          "isStale": false,
          "decision": "CALLBACK_REQUIRED",
          "reason": "BOARD_NOT_CONFIRMED",
          "openSlots": null
        }
      ],
      "decision": "APPOINTMENT_REQUEST",
      "reason": null,
      "sessionChoiceRequired": true
    }
  ],
  "choices": [],
  "departmentChoices": [],
  "complete": true,
  "totalMatches": null,
  "bookableFound": 1,
  "basis": "LIVE_BOARD",
  "sessionMatched": null,
  "callback": null,
  "detail": null,
  "retryAfterSeconds": null
}
```

`sessionChoiceRequired` is true: Morning permits a request, Afternoon needs a callback. The session selection remains unresolved in this slots-disabled example.

**2. Usual working hours, no date**

Arguments:

```json
{
  "doctorName": "garima",
  "purpose": "WORKING_HOURS"
}
```

Structured result:

```json
{
  "outcome": "WORKING_HOURS",
  "nextStep": "PRESENT_WORKING_HOURS",
  "facilityToday": "2026-10-01",
  "requestedDate": null,
  "weekday": null,
  "department": null,
  "doctors": [
    {
      "doctorId": "doc_garima",
      "name": "Dr. Garima",
      "departments": [
        "General Medicine"
      ],
      "attendanceType": "REGULAR",
      "gender": "FEMALE",
      "dataConfirmed": true,
      "usualSessions": [
        {
          "label": "Morning",
          "daysOfWeek": [
            "MON",
            "THU",
            "FRI"
          ],
          "start": "09:00",
          "end": "12:00",
          "onRequestedDate": null,
          "decision": "APPOINTMENT_REQUEST",
          "reason": null,
          "openSlots": null,
          "status": null,
          "oneDay": false
        },
        {
          "label": "Afternoon",
          "daysOfWeek": [
            "MON",
            "THU",
            "FRI"
          ],
          "start": "15:00",
          "end": "17:00",
          "onRequestedDate": null,
          "decision": "APPOINTMENT_REQUEST",
          "reason": null,
          "openSlots": null,
          "status": null,
          "oneDay": false
        }
      ],
      "board": [],
      "decision": "APPOINTMENT_REQUEST",
      "reason": null,
      "sessionChoiceRequired": false
    }
  ],
  "choices": [],
  "departmentChoices": [],
  "complete": true,
  "totalMatches": null,
  "bookableFound": 0,
  "basis": "USUAL_SCHEDULE",
  "sessionMatched": null,
  "callback": null,
  "detail": null,
  "retryAfterSeconds": null
}
```

**3. Callback required**

Arguments:

```json
{
  "doctorName": "kiran",
  "date": "today"
}
```

Structured result:

```json
{
  "outcome": "CALLBACK_REQUIRED",
  "nextStep": "ASK_CALLBACK_DETAILS",
  "facilityToday": "2026-10-01",
  "requestedDate": "2026-10-01",
  "weekday": "THU",
  "department": null,
  "doctors": [
    {
      "doctorId": "doc_kiran_hegde",
      "name": "Dr. Kiran Hegde",
      "departments": [
        "Urology"
      ],
      "attendanceType": "REGULAR",
      "gender": "MALE",
      "dataConfirmed": null,
      "usualSessions": null,
      "board": [
        {
          "session": "Evening",
          "status": "UNKNOWN",
          "expectedTime": null,
          "expectedEndTime": null,
          "delayMinutes": null,
          "note": null,
          "isStale": true,
          "decision": "CALLBACK_REQUIRED",
          "reason": "BOARD_STALE",
          "openSlots": null
        }
      ],
      "decision": "CALLBACK_REQUIRED",
      "reason": "BOARD_STALE",
      "sessionChoiceRequired": false
    }
  ],
  "choices": [],
  "departmentChoices": [],
  "complete": true,
  "totalMatches": null,
  "bookableFound": 0,
  "basis": "LIVE_BOARD",
  "sessionMatched": null,
  "callback": {
    "reason": "BOARD_STALE",
    "summaryOutcome": "CALLBACK_NOTED"
  },
  "detail": "BOARD_STALE",
  "retryAfterSeconds": null
}
```

`CALLBACK_NOTED` summaries require the callback number; no appointment or separate callback task is created.

**4. Date missing**

Arguments:

```json
{
  "doctorName": "garima"
}
```

Structured result:

```json
{
  "outcome": "INVALID_REQUEST",
  "nextStep": "ASK_EXPLICIT_DATE",
  "facilityToday": "2026-10-01",
  "requestedDate": null,
  "weekday": null,
  "department": null,
  "doctors": [],
  "choices": [],
  "departmentChoices": [],
  "complete": true,
  "totalMatches": null,
  "bookableFound": 0,
  "basis": null,
  "sessionMatched": null,
  "callback": null,
  "detail": "DATE_REQUIRED",
  "retryAfterSeconds": null
}
```

**5. Unknown argument (rejected before the tool runs)**

Arguments:

```json
{
  "doctorName": "garima",
  "date": "today",
  "foo": "x"
}
```

Result (`isError: true`, text content; no structured result):

```text
1 validation error for call[get_doctor_availability]
foo
  Unexpected keyword argument [type=unexpected_keyword_argument, input_value='x', input_type=str]
    For further information visit https://errors.pydantic.dev/2.13/v/unexpected_keyword_argument
```

## manage_booking

Appointment request operations: CREATE, LIST, CANCEL and RESCHEDULE. Writes require callerConfirmed=true and trusted call/operation headers. CREATE requires patientName, patientMobile, doctorId and visitDate; department-level appointments are unsupported. LIST/CANCEL/RESCHEDULE require verified caller identity. With slots enabled, CREATE requires preferredTime and RESCHEDULE requires newPreferredTime: the time belongs within returned openSlots. Missing time returns TIME_REQUIRED/ASK_WHICH_TIME with choices. session is optional; a supplied nonblank label must match the session containing that time. Blank means no selection; session is internal MCP context, absent from the owner request. Today uses the live board and slots; future dates rely on slots when enabled. Ordinary UNKNOWN requires CALLBACK_REQUIRED and no write; NOT_CONFIRMED with an open bookable block can be NOTED: noted, the desk will confirm. ON_CALL without a confirmed IN/LATE entry and a usable window or open block requires HANDOFF_REQUIRED/TRANSFER_DESK without callback metadata; cancelled sessions are NOT_AVAILABLE. With slots disabled, today uses the board and future regular/visiting dates follow usual hours, attendance not confirmed; time is optional, differing decisions without session/time selection yield SESSION_REQUIRED/ASK_WHICH_SESSION, and a specific time without a known end yields HANDOFF_REQUIRED/TIME_NOT_VERIFIABLE. NOTED records a create or reschedule request, not a confirmed or reserved time; appointment.status preserves the owner status. slotTime is the time recorded for this request: the owner's slotTime (block start), otherwise expectedTime, otherwise null. slotMoved is true only if the owner returned a different block, such as for a late doctor or passed time; choosing 10:45 and receiving its 10:30 block start is not moved. CALLBACK_REQUIRED means no write and callback facts belong only in a call summary. NOT_AVAILABLE means the selected session/time is unavailable; NO_OPEN_SLOT means the session has no open slot, SLOT_FULL means that time is full, and TIME_OUTSIDE_SESSION means outside known bounds or, with slots, no block contains the time, the containing block is closed or ended, or a supplied session label does not match its session. A full containing block is SLOT_FULL. Checked alternatives are the sessions/openSlots in this result; an owner SLOT_FULL write rejection carries none and establishes no availability at other times. UNCERTAIN means a write may have committed without a verified result; desk handoff is the disposition, not retry. A later invocation with the same operation id re-runs the schedule check and can be refused; refusal does not prove the earlier write failed.

### How to call

Required fields per action (beyond `action`). The schema marks only `action` as required; the tool checks
the rest and returns `INVALID_REQUEST` with `fields` naming each missing or malformed field.

| Action | Required | Optional | Unsupported or inapplicable | Headers |
|---|---|---|---|---|
| CREATE | `patientName`, `patientMobile` (10 digits), `doctorId`, `visitDate` (`today` or `YYYY-MM-DD`), `callerConfirmed: true`; `preferredTime` (`HH:MM`) when slots enabled | `session`, `reasonVerbatim`; `preferredTime` when slots disabled | `departmentId`, `doctorName` (unknown fields) | X-Call-Id, X-Operation-Id |
| LIST | none | `fromDate`, `toDate` (`YYYY-MM-DD`; `today` is refused), `status` | write fields | X-Caller-Number, X-Caller-Verification |
| CANCEL | `appointmentId`, `callerConfirmed: true` | `reasonVerbatim` | | X-Call-Id, X-Operation-Id, X-Caller-Number, X-Caller-Verification |
| RESCHEDULE | `appointmentId`, `newVisitDate` (`today` or `YYYY-MM-DD`), `callerConfirmed: true`; `newPreferredTime` (`HH:MM`) when slots enabled | `session`; `newPreferredTime` when slots disabled | `doctorId` (returns `INVALID_REQUEST`, detail `DOCTOR_CHANGE_UNSUPPORTED`) | X-Call-Id, X-Operation-Id, X-Caller-Number, X-Caller-Verification |

For CREATE, CANCEL and RESCHEDULE, checks run in this order and the first failure is returned: field validation (`INVALID_REQUEST`) →
`callerConfirmed` (`CONFIRMATION_REQUIRED`) → call and operation headers (`OPERATION_CONTEXT_MISSING`) →
caller identity for CANCEL/RESCHEDULE (`IDENTITY_UNAVAILABLE`) → schedule policy for CREATE/RESCHEDULE
(`INVALID_REQUEST` with `SESSION_REQUIRED` or `TIME_REQUIRED`, `CALLBACK_REQUIRED`, `NOT_AVAILABLE`,
`HANDOFF_REQUIRED`, or `COULD_NOT_RECORD` after a failed read) → owner write.

- `callerConfirmed: true` represents the caller's agreement to the exact write details.
- With slots disabled, today's booking window starts at the later of session start and facility now
  (strict, minute precision); future dates follow usual hours. With slots enabled, the time belongs within
  returned `openSlots`; today, ended blocks have no bookable time.
- Booking rejection `fields` contain tool argument names only; owner names are translated and names without a tool argument are dropped.
- With slots enabled, `preferredTime` / `newPreferredTime` is required; `session` stays optional. A supplied
  nonblank label must match the session containing the chosen time. An unlabelled session cannot match
  a supplied name. A request for an unlabelled session has no session label; blank means no selection.
- `ASK_WHICH_TIME` means a time is required when slots apply; `sessions` carry `openSlots`.
  Booking `ASK_WHICH_SESSION` is a slots-disabled result. With slots enabled, a supplied session label
  that does not match the chosen time's session is refused as `TIME_OUTSIDE_SESSION`.
- `appointment.slotTime` is the time recorded for the request: the owner's `slotTime` (block start),
  otherwise the request's `expectedTime`, otherwise `null`. `slotMoved` means the owner recorded CREATE
  or RESCHEDULE in a different block (for example a late doctor or passed time). A chosen 10:45 recorded
  at its 10:30 block start is not moved. LIST and CANCEL have `slotMoved: false`.
- `NOTED` after a `NOT_CONFIRMED` session means "noted, the desk will confirm". NOT_CONFIRMED is a
  session status, not a new appointment status; NOTED is not a reserved or confirmed time.
- For `NOT_AVAILABLE`, `sessions` contains the checked alternatives on that date, when any exist
  (`OFFER_OTHER_SESSION_OR_TIME`). An empty list establishes no availability at other times; that
  information requires a new availability check. `OFFER_OTHER_SESSION_OR_DATE` means the requested
  session or date is unavailable.
- Booking `detail: SLOT_FULL` means the chosen time's block is full. An owner's definite write rejection
  returns empty `sessions` and `fields`; it establishes no availability at other times. Checked
  alternatives require a new availability result. A rejection after an unanswered write attempt
  remains `UNCERTAIN`, with desk handoff as the disposition.
- `patientMobile` is contact data only. Permission to list, cancel or reschedule comes from the trusted
  caller-number headers, not a dictated number.

### Input schema (exact)

```json
{
  "properties": {
    "action": {
      "description": "Required action: CREATE, LIST, CANCEL or RESCHEDULE.",
      "enum": [
        "CREATE",
        "LIST",
        "CANCEL",
        "RESCHEDULE"
      ],
      "type": "string"
    },
    "appointmentId": {
      "anyOf": [
        {
          "maxLength": 64,
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Required for CANCEL/RESCHEDULE: identifier of the appointment request."
    },
    "callerConfirmed": {
      "default": false,
      "description": "Boolean declaring the caller's approval of this write; true is required for CREATE/CANCEL/RESCHEDULE.",
      "type": "boolean"
    },
    "doctorId": {
      "anyOf": [
        {
          "maxLength": 64,
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Required for CREATE: identifier of the selected doctor. Department-level appointments are unsupported."
    },
    "fromDate": {
      "anyOf": [
        {
          "maxLength": 10,
          "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Optional LIST lower date filter in YYYY-MM-DD format; past dates are accepted."
    },
    "newPreferredTime": {
      "anyOf": [
        {
          "maxLength": 5,
          "pattern": "^\\d{2}:\\d{2}$",
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "RESCHEDULE time in HH:MM 24-hour format; required when slots are enabled, chosen within returned openSlots. Optional when slots are disabled."
    },
    "newVisitDate": {
      "anyOf": [
        {
          "maxLength": 10,
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Required for RESCHEDULE: 'today' or YYYY-MM-DD, on or after the facility date."
    },
    "patientMobile": {
      "anyOf": [
        {
          "maxLength": 20,
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Required for CREATE: 10-digit contact mobile. This is contact data, not caller authority."
    },
    "patientName": {
      "anyOf": [
        {
          "maxLength": 100,
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Required for CREATE: patient name; nonblank, at most 100 characters."
    },
    "preferredTime": {
      "anyOf": [
        {
          "maxLength": 5,
          "pattern": "^\\d{2}:\\d{2}$",
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "CREATE time in HH:MM 24-hour format; required when slots are enabled, chosen within returned openSlots. Optional when slots are disabled; a request, not a reservation."
    },
    "reasonVerbatim": {
      "anyOf": [
        {
          "maxLength": 500,
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Optional CREATE/CANCEL reason in the caller's original words; forwarded without interpretation."
    },
    "session": {
      "anyOf": [
        {
          "maxLength": 40,
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Optional CREATE or RESCHEDULE session label; blank means no selection. With slots enabled, a supplied label must match the session containing the chosen time; an unlabelled session cannot match it. Internal MCP context, absent from the owner request. With slots disabled, a session or time selection resolves differing decisions."
    },
    "status": {
      "anyOf": [
        {
          "enum": [
            "NOTED",
            "CONFIRMED_BY_DESK",
            "CHANGED",
            "CANCELLED"
          ],
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Optional LIST appointment-status filter."
    },
    "toDate": {
      "anyOf": [
        {
          "maxLength": 10,
          "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Optional LIST upper date filter in YYYY-MM-DD format; past dates are accepted."
    },
    "visitDate": {
      "anyOf": [
        {
          "maxLength": 10,
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Required for CREATE: 'today' or YYYY-MM-DD, on or after the facility date."
    }
  },
  "required": [
    "action"
  ],
  "type": "object"
}
```

### Parameters

| Field path | Type / constraints (JSON Schema) | Presence | Meaning |
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

### Output fields

| Field path | Type / constraints (JSON Schema) | Presence | Meaning |
|---|---|---|---|
| `manage_booking.output.appointment` | `{"anyOf":[{"$ref":"#/$defs/AppointmentOut"},{"type":"null"}]}` | optional | Single appointment request returned by a write. |
| `manage_booking.output.appointments` | `{"items":{"$ref":"#/$defs/AppointmentOut"},"type":"array"}` | optional | Appointment requests belonging to the verified caller. |
| `manage_booking.output.callback` | `{"anyOf":[{"$ref":"#/$defs/Callback"},{"type":"null"}]}` | optional | Callback reason and call-summary category; no separate callback action. |
| `manage_booking.output.detail` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Machine-readable reason for a non-success result; optional. |
| `manage_booking.output.fields` | `{"items":{"type":"string"},"type":"array"}` | optional | Request fields that were invalid or rejected. |
| `manage_booking.output.nextStep` | `{"enum":["SAY_REQUEST_NOTED","SAY_CHANGED","SAY_CANCELLED","OFFER_CHOICES","SAY_NOT_FOUND","ASK_TO_CORRECT","SAY_UNCERTAIN_AND_TRANSFER","TRANSFER_DESK","ASK_CALLBACK_DETAILS","ASK_CONFIRMATION","SAY_COULD_NOT_RECORD","SAY_COULD_NOT_CHECK","ASK_WHICH_SESSION","OFFER_OTHER_SESSION_OR_TIME","OFFER_OTHER_SESSION_OR_DATE","ASK_WHICH_TIME"],"type":"string"}` | required | Machine-readable disposition code, defined below. |
| `manage_booking.output.outcome` | `{"enum":["NOTED","CHANGED","CANCELLED","FOUND","NOT_FOUND","REJECTED","CONFLICT","UNCERTAIN","IDENTITY_UNAVAILABLE","CALLBACK_REQUIRED","NOT_AVAILABLE","HANDOFF_REQUIRED","CONFIRMATION_REQUIRED","OPERATION_CONTEXT_MISSING","COULD_NOT_RECORD","COULD_NOT_CHECK","INVALID_REQUEST"],"type":"string"}` | required | Result category, defined below. |
| `manage_booking.output.retryAfterSeconds` | `{"anyOf":[{"type":"integer"},{"type":"null"}]}` | optional | Upstream retry delay in seconds when supplied; optional. |
| `manage_booking.output.sessions` | `{"items":{"anyOf":[{"$ref":"#/$defs/BoardSessionOut"},{"$ref":"#/$defs/UsualSessionOut"}]},"type":"array"}` | optional | Returned session alternatives and their checked openSlots when available; no reservation or invented capacity. |
| `manage_booking.output.$defs.AppointmentOut.appointmentId` | `{"type":"string"}` | required | Operational appointment request identifier. |
| `manage_booking.output.$defs.AppointmentOut.department` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Resolved department object; within AppointmentOut, the operational department identifier. |
| `manage_booking.output.$defs.AppointmentOut.doctorId` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Operational doctor identifier. |
| `manage_booking.output.$defs.AppointmentOut.expectedTime` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Board expected start time or requested appointment time; not a guaranteed reservation. |
| `manage_booking.output.$defs.AppointmentOut.patientName` | `{"type":"string"}` | required | Name on the appointment request; LIST is restricted to the verified caller’s own records. |
| `manage_booking.output.$defs.AppointmentOut.slotMoved` | `{"type":"boolean"}` | optional | True only when the owner moved CREATE or RESCHEDULE to a different block, for example for a late doctor or a passed time. Choosing 10:45 and receiving its 10:30 block start is not moved. False for LIST and CANCEL. |
| `manage_booking.output.$defs.AppointmentOut.slotTime` | `{"anyOf":[{"pattern":"^([01][0-9]|2[0-3]):[0-5][0-9]$","type":"string"},{"type":"null"}]}` | optional | Time recorded for this request in HH:MM facility local time: the owner's slotTime (block start), otherwise the request's expectedTime, otherwise null. |
| `manage_booking.output.$defs.AppointmentOut.status` | `{"enum":["NOTED","CONFIRMED_BY_DESK","CHANGED","CANCELLED"],"type":"string"}` | required | Manoj's appointment status, unchanged (including CHANGED after reschedule). |
| `manage_booking.output.$defs.AppointmentOut.visitDate` | `{"type":"string"}` | required | Appointment visit date (YYYY-MM-DD). |
| `manage_booking.output.$defs.BoardSessionOut.decision` | `{"$ref":"#/$defs/Decision"}` | required | MCP decision, distinct from owner status: APPOINTMENT_REQUEST, SLOT_CHECK_REQUIRED, CALLBACK_REQUIRED, HANDOFF_REQUIRED, NOT_AVAILABLE or COULD_NOT_CHECK. Decision meanings are listed below. |
| `manage_booking.output.$defs.BoardSessionOut.delayMinutes` | `{"anyOf":[{"type":"integer"},{"type":"null"}]}` | optional | Board delay in minutes when supplied. |
| `manage_booking.output.$defs.BoardSessionOut.expectedEndTime` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Board expected end time in facility local time when supplied. |
| `manage_booking.output.$defs.BoardSessionOut.expectedTime` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Board expected start time or requested appointment time; not a guaranteed reservation. |
| `manage_booking.output.$defs.BoardSessionOut.isStale` | `{"type":"boolean"}` | required | Owner-supplied board staleness flag; not an adapter-computed age threshold. |
| `manage_booking.output.$defs.BoardSessionOut.note` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Owner-authored caller-facing board note, limited to 200 characters. |
| `manage_booking.output.$defs.BoardSessionOut.openSlots` | `{"anyOf":[{"items":{"$ref":"#/$defs/SlotOut"},"type":"array"},{"type":"null"}]}` | optional | Open blocks offered for this session and date: the owner's open blocks when the session permits a request. null means slots were not checked (disabled, WORKING_HOURS, or a department search pending doctor selection); [] means checked and no block is offered (none open, or the session does not permit a request). When slots apply, CREATE or RESCHEDULE times outside these blocks are refused. |
| `manage_booking.output.$defs.BoardSessionOut.reason` | `{"anyOf":[{"$ref":"#/$defs/Reason"},{"type":"null"}]}` | optional | Machine-readable reason for this decision; null when no qualification applies. |
| `manage_booking.output.$defs.BoardSessionOut.session` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | required | Board session label when present. |
| `manage_booking.output.$defs.BoardSessionOut.status` | `{"enum":["IN","LATE","CANCELLED","NOT_CONFIRMED","UNKNOWN"],"type":"string"}` | required | Manoj's board or slot-only session status; MCP decision is separate. |
| `manage_booking.output.$defs.Callback.reason` | `{"$ref":"#/$defs/Reason"}` | required | Required machine-readable reason for callback. |
| `manage_booking.output.$defs.Callback.summaryOutcome` | `{"const":"CALLBACK_NOTED","type":"string"}` | optional | CALLBACK_NOTED identifies the callback call-summary category. |
| `manage_booking.output.$defs.SlotOut.available` | `{"minimum":0,"type":"integer"}` | required | Remaining places reported by the owner for this block; MCP does not compute capacity or reserve a place. |
| `manage_booking.output.$defs.SlotOut.end` | `{"pattern":"^([01][0-9]|2[0-3]):[0-5][0-9]$","type":"string"}` | required | Open block end in HH:MM facility local time, exclusive. |
| `manage_booking.output.$defs.SlotOut.start` | `{"pattern":"^([01][0-9]|2[0-3]):[0-5][0-9]$","type":"string"}` | required | Open block start in HH:MM facility local time, inclusive. |
| `manage_booking.output.$defs.UsualSessionOut.daysOfWeek` | `{"items":{"type":"string"},"type":"array"}` | required | Weekday codes for a usual session; empty for a desk-added one-day session. |
| `manage_booking.output.$defs.UsualSessionOut.decision` | `{"$ref":"#/$defs/Decision"}` | required | MCP decision, distinct from owner status: APPOINTMENT_REQUEST, SLOT_CHECK_REQUIRED, CALLBACK_REQUIRED, HANDOFF_REQUIRED, NOT_AVAILABLE or COULD_NOT_CHECK. Decision meanings are listed below. |
| `manage_booking.output.$defs.UsualSessionOut.end` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | required | Session end in facility local time. null only for a one-day session whose hours the owner did not supply. Such a session has no bookable time. |
| `manage_booking.output.$defs.UsualSessionOut.label` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | required | Usual or one-day session label, possibly null. |
| `manage_booking.output.$defs.UsualSessionOut.onRequestedDate` | `{"anyOf":[{"type":"boolean"},{"type":"null"}]}` | required | Whether the session belongs to the requested date; true for a one-day session, null when no date was supplied. |
| `manage_booking.output.$defs.UsualSessionOut.oneDay` | `{"type":"boolean"}` | optional | A session the desk added for the requested date only; not part of the regular schedule. |
| `manage_booking.output.$defs.UsualSessionOut.openSlots` | `{"anyOf":[{"items":{"$ref":"#/$defs/SlotOut"},"type":"array"},{"type":"null"}]}` | optional | Open blocks offered for this session and date: the owner's open blocks when the session permits a request. null means slots were not checked (disabled, WORKING_HOURS, or a department search pending doctor selection); [] means checked and no block is offered (none open, or the session does not permit a request). When slots apply, CREATE or RESCHEDULE times outside these blocks are refused. |
| `manage_booking.output.$defs.UsualSessionOut.reason` | `{"anyOf":[{"$ref":"#/$defs/Reason"},{"type":"null"}]}` | optional | Machine-readable reason for this decision; null when no qualification applies. |
| `manage_booking.output.$defs.UsualSessionOut.start` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | required | Session start in facility local time. null only for a one-day session whose hours the owner did not supply. Such a session has no bookable time. |
| `manage_booking.output.$defs.UsualSessionOut.status` | `{"anyOf":[{"enum":["IN","LATE","CANCELLED","NOT_CONFIRMED","UNKNOWN"],"type":"string"},{"type":"null"}]}` | optional | Owner's slot status for this session on the requested date; null when slots were not checked. |

### Outcomes and nextStep meanings

| Code | Meaning |
|---|---|
| `manage_booking.outcome.NOTED` | Appointment request recorded; no time is confirmed or reserved. |
| `manage_booking.outcome.CHANGED` | The owner returned a verified appointment change. |
| `manage_booking.outcome.CANCELLED` | The owner returned a verified cancellation. |
| `manage_booking.outcome.FOUND` | Verified-caller appointment requests are returned. |
| `manage_booking.outcome.NOT_FOUND` | No matching verified-caller appointment was found. |
| `manage_booking.outcome.REJECTED` | The owner rejected the request. |
| `manage_booking.outcome.CONFLICT` | The owner reported an operation or idempotency conflict. |
| `manage_booking.outcome.UNCERTAIN` | A write may have committed without a verified result; desk handoff is the disposition, not retry. A later invocation with the same operation id re-runs the schedule check and can be refused. |
| `manage_booking.outcome.IDENTITY_UNAVAILABLE` | Verified caller authority is unavailable for appointment lookup or modification. |
| `manage_booking.outcome.CALLBACK_REQUIRED` | An ordinary doctor has an unresolved schedule: UNKNOWN, or NOT_CONFIRMED with slots disabled, or no usual schedule. No appointment write; callback details belong only to a CALLBACK_NOTED summary. On-call doctors have desk handoff as their disposition. |
| `manage_booking.outcome.NOT_AVAILABLE` | Valid request, but the selected schedule or session is unavailable. |
| `manage_booking.outcome.HANDOFF_REQUIRED` | Desk assistance is the disposition for an on-call doctor without a confirmed, usable entry, or incomplete search/time validation. No callback metadata; MCP does not perform the telephone transfer. |
| `manage_booking.outcome.CONFIRMATION_REQUIRED` | callerConfirmed is not true for the requested write. |
| `manage_booking.outcome.OPERATION_CONTEXT_MISSING` | Trusted call or operation identity required for the write is absent or invalid. |
| `manage_booking.outcome.COULD_NOT_RECORD` | The write could not be recorded; detail identifies the failure when available. |
| `manage_booking.outcome.COULD_NOT_CHECK` | A read could not be completed; this is not an empty or negative result. |
| `manage_booking.outcome.INVALID_REQUEST` | Request validation failed; fields or detail identify the issue when available. |
| `manage_booking.nextStep.SAY_REQUEST_NOTED` | The appointment request is recorded without a guaranteed time. |
| `manage_booking.nextStep.SAY_CHANGED` | An appointment change is verified. |
| `manage_booking.nextStep.SAY_CANCELLED` | An appointment cancellation is verified. |
| `manage_booking.nextStep.OFFER_CHOICES` | Verified-caller appointment choices are available. |
| `manage_booking.nextStep.SAY_NOT_FOUND` | No matching verified-caller appointment was found. |
| `manage_booking.nextStep.ASK_TO_CORRECT` | Request fields need correction. |
| `manage_booking.nextStep.SAY_UNCERTAIN_AND_TRANSFER` | Write completion is uncertain and desk assistance is the disposition; no telephone transfer is executed by MCP. |
| `manage_booking.nextStep.TRANSFER_DESK` | Desk assistance is the returned disposition; MCP does not execute a telephone transfer. |
| `manage_booking.nextStep.ASK_CALLBACK_DETAILS` | Callback policy requires contact details and a call summary; no appointment is written. |
| `manage_booking.nextStep.ASK_CONFIRMATION` | The write lacks callerConfirmed=true. |
| `manage_booking.nextStep.SAY_COULD_NOT_RECORD` | The requested write could not be recorded. |
| `manage_booking.nextStep.SAY_COULD_NOT_CHECK` | The requested information could not be checked. |
| `manage_booking.nextStep.ASK_WHICH_SESSION` | Slots-disabled booking only: differing session decisions require a session selection. With slots enabled, a mismatched supplied session label is TIME_OUTSIDE_SESSION instead. |
| `manage_booking.nextStep.ASK_WHICH_TIME` | A time is required for CREATE or RESCHEDULE when slots apply; sessions carry the openSlots for preferredTime or newPreferredTime. |
| `manage_booking.nextStep.OFFER_OTHER_SESSION_OR_TIME` | sessions/openSlots are the checked alternatives. An owner SLOT_FULL write rejection carries none; availability at other times requires a new check. |
| `manage_booking.nextStep.OFFER_OTHER_SESSION_OR_DATE` | The requested session or date is unavailable; alternatives may be returned. |

### Examples

Examples come from the development stubs (facility date 2026-10-01, Thursday, 10:00); names and
identifiers are fixtures, with slots disabled. The new optional fields are shown at their defaults.
Slots-enabled behaviour is described above and will be activated in the complete release.

**1. CREATE recorded**

Arguments:

```json
{
  "action": "CREATE",
  "patientName": "Lakshmi Rao",
  "patientMobile": "9000000101",
  "doctorId": "doc_garima",
  "visitDate": "2026-10-02",
  "preferredTime": "09:30",
  "reasonVerbatim": "ಜ್ವರ ಮೂರು ದಿನದಿಂದ",
  "callerConfirmed": true
}
```

Structured result:

```json
{
  "sessions": [],
  "outcome": "NOTED",
  "nextStep": "SAY_REQUEST_NOTED",
  "appointment": {
    "appointmentId": "appt_0001",
    "status": "NOTED",
    "visitDate": "2026-10-02",
    "expectedTime": "09:30",
    "doctorId": "doc_garima",
    "department": null,
    "patientName": "Lakshmi Rao",
    "slotTime": null,
    "slotMoved": false
  },
  "appointments": [],
  "fields": [],
  "callback": null,
  "detail": null,
  "retryAfterSeconds": null
}
```

`NOTED` means the request is recorded; the time is not confirmed or reserved.

**2. LIST the verified caller's appointments**

Arguments:

```json
{
  "action": "LIST"
}
```

Structured result:

```json
{
  "sessions": [],
  "outcome": "FOUND",
  "nextStep": "OFFER_CHOICES",
  "appointment": null,
  "appointments": [
    {
      "appointmentId": "appt_0001",
      "status": "NOTED",
      "visitDate": "2026-10-02",
      "expectedTime": "09:30",
      "doctorId": "doc_garima",
      "department": null,
      "patientName": "Lakshmi Rao",
      "slotTime": null,
      "slotMoved": false
    }
  ],
  "fields": [],
  "callback": null,
  "detail": null,
  "retryAfterSeconds": null
}
```

**3. CREATE without caller confirmation**

Arguments:

```json
{
  "action": "CREATE",
  "patientName": "A",
  "patientMobile": "9000000101",
  "doctorId": "doc_garima",
  "visitDate": "2026-10-02"
}
```

Structured result:

```json
{
  "sessions": [],
  "outcome": "CONFIRMATION_REQUIRED",
  "nextStep": "ASK_CONFIRMATION",
  "appointment": null,
  "appointments": [],
  "fields": [],
  "callback": null,
  "detail": null,
  "retryAfterSeconds": null
}
```

**4. CREATE when sessions differ and none was chosen**

Arguments:

```json
{
  "action": "CREATE",
  "patientName": "A",
  "patientMobile": "9000000101",
  "doctorId": "doc_garima",
  "visitDate": "today",
  "callerConfirmed": true
}
```

Structured result:

```json
{
  "sessions": [
    {
      "session": "Morning",
      "status": "IN",
      "expectedTime": "09:10",
      "expectedEndTime": "12:00",
      "delayMinutes": null,
      "note": null,
      "isStale": false,
      "decision": "APPOINTMENT_REQUEST",
      "reason": null,
      "openSlots": null
    },
    {
      "session": "Afternoon",
      "status": "NOT_CONFIRMED",
      "expectedTime": "15:00",
      "expectedEndTime": "17:00",
      "delayMinutes": null,
      "note": null,
      "isStale": false,
      "decision": "CALLBACK_REQUIRED",
      "reason": "BOARD_NOT_CONFIRMED",
      "openSlots": null
    }
  ],
  "outcome": "INVALID_REQUEST",
  "nextStep": "ASK_WHICH_SESSION",
  "appointment": null,
  "appointments": [],
  "fields": [
    "session"
  ],
  "callback": null,
  "detail": "SESSION_REQUIRED",
  "retryAfterSeconds": null
}
```

This slots-disabled result leaves the session unresolved; `"session": "Morning"` identifies the morning choice.

**5. Mobile in the wrong format**

Arguments:

```json
{
  "action": "CREATE",
  "patientName": "A",
  "patientMobile": "+919000000101",
  "doctorId": "doc_garima",
  "visitDate": "today"
}
```

Structured result:

```json
{
  "sessions": [],
  "outcome": "INVALID_REQUEST",
  "nextStep": "ASK_TO_CORRECT",
  "appointment": null,
  "appointments": [],
  "fields": [
    "patientMobile"
  ],
  "callback": null,
  "detail": null,
  "retryAfterSeconds": null
}
```

The accepted mobile format is 10 digits without `+91`.

**6. Unknown argument (rejected before the tool runs)**

Arguments:

```json
{
  "action": "CREATE",
  "doctorName": "garima"
}
```

Result (`isError: true`, text content; no structured result):

```text
1 validation error for call[manage_booking]
doctorName
  Unexpected keyword argument [type=unexpected_keyword_argument, input_value='garima', input_type=str]
    For further information visit https://errors.pydantic.dev/2.13/v/unexpected_keyword_argument
```

## search_knowledge

One knowledge-service request for hospital information or symptom-to-department routing. It does not read availability or change appointments. ANSWERED and CLARIFICATION_NEEDED carry owner-provided text in answer.text. Routing results carry text only in routing.speak, when present. TRANSFER_EMERGENCY means the knowledge service decided the caller needs emergency help; TRANSFER_DESK means desk assistance; CHECK_AVAILABILITY identifies a department in routing.department. NO_ANSWER is an owner decision; COULD_NOT_CHECK is a service failure.

### How to call

Both fields are required. `question` contains the caller's original wording, untranslated and
unsummarised, at most 500 characters. `language` is the caller's language code (`en`, `kn` or `hi`).

**Provisional:** the knowledge service contract is still being agreed with its owner. The input fields are
not expected to change; output fields may. The version at the top of this document will change if they do.

### Input schema (exact)

```json
{
  "properties": {
    "language": {
      "description": "Required nonblank language code, up to 16 characters; forwarded unchanged to the knowledge service.",
      "maxLength": 16,
      "type": "string"
    },
    "question": {
      "description": "Required original question, untranslated and unsummarised; nonblank, maximum 500 characters.",
      "maxLength": 500,
      "type": "string"
    }
  },
  "required": [
    "question",
    "language"
  ],
  "type": "object"
}
```

### Parameters

| Field path | Type / constraints (JSON Schema) | Presence | Meaning |
|---|---|---|---|
| `search_knowledge.input.language` | `{"maxLength":16,"type":"string"}` | required | Required nonblank language code, up to 16 characters; forwarded unchanged to the knowledge service. |
| `search_knowledge.input.question` | `{"maxLength":500,"type":"string"}` | required | Required original question, untranslated and unsummarised; nonblank, maximum 500 characters. |

### Output fields

| Field path | Type / constraints (JSON Schema) | Presence | Meaning |
|---|---|---|---|
| `search_knowledge.output.answer` | `{"anyOf":[{"$ref":"#/$defs/Speech"},{"type":"null"}]}` | optional | Knowledge-service answer or clarification text. |
| `search_knowledge.output.destination` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Optional knowledge-service destination identifier. |
| `search_knowledge.output.detail` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Machine-readable reason for a non-success result; optional. |
| `search_knowledge.output.nextStep` | `{"enum":["SPEAK_ANSWER","SAY_NO_ANSWER_AND_OFFER_DESK","ASK_CLARIFICATION","TRANSFER_DESK","TRANSFER_EMERGENCY","CHECK_AVAILABILITY","SAY_COULD_NOT_CHECK","ASK_TO_REPHRASE"],"type":"string"}` | required | Machine-readable disposition code, defined below. |
| `search_knowledge.output.outcome` | `{"enum":["ANSWERED","NO_ANSWER","CLARIFICATION_NEEDED","ROUTING_REQUIRED","COULD_NOT_CHECK","INVALID_REQUEST"],"type":"string"}` | required | Result category, defined below. |
| `search_knowledge.output.routing` | `{"anyOf":[{"$ref":"#/$defs/Routing"},{"type":"null"}]}` | optional | The owner's routing decision over the caller's words. |
| `search_knowledge.output.sourceId` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Optional knowledge-service source identifier. |
| `search_knowledge.output.$defs.Routing.decision` | `{"enum":["ROUTE_DEPARTMENT","DESK_TRANSFER","EMERGENCY_TRANSFER"],"type":"string"}` | required | Knowledge owner routing decision, distinct from schedule decisions. |
| `search_knowledge.output.$defs.Routing.department` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Department name returned by the knowledge service; compatible with availability departmentName. |
| `search_knowledge.output.$defs.Routing.speak` | `{"anyOf":[{"$ref":"#/$defs/Speech"},{"type":"null"}]}` | optional | Optional knowledge-service text associated with a routing decision; not duplicated in answer. |
| `search_knowledge.output.$defs.Speech.language` | `{"type":"string"}` | required | Language of the knowledge-service text. |
| `search_knowledge.output.$defs.Speech.text` | `{"type":"string"}` | required | Knowledge-service text, preserved unchanged. |

### Outcomes and nextStep meanings

| Code | Meaning |
|---|---|
| `search_knowledge.outcome.ANSWERED` | The knowledge service returned answer text. |
| `search_knowledge.outcome.NO_ANSWER` | The knowledge service explicitly returned no answer. |
| `search_knowledge.outcome.CLARIFICATION_NEEDED` | Knowledge-service clarification text is returned in answer.text. |
| `search_knowledge.outcome.ROUTING_REQUIRED` | The knowledge service returned a department, desk or emergency decision. |
| `search_knowledge.outcome.COULD_NOT_CHECK` | A read could not be completed; this is not an empty or negative result. |
| `search_knowledge.outcome.INVALID_REQUEST` | Request validation failed; fields or detail identify the issue when available. |
| `search_knowledge.nextStep.SPEAK_ANSWER` | Answer text is available in answer.text. |
| `search_knowledge.nextStep.SAY_NO_ANSWER_AND_OFFER_DESK` | The knowledge service has no answer; desk assistance is the disposition. |
| `search_knowledge.nextStep.ASK_CLARIFICATION` | Knowledge-service clarification text is available in answer.text. |
| `search_knowledge.nextStep.TRANSFER_DESK` | Desk assistance is the returned disposition; MCP does not execute a telephone transfer. |
| `search_knowledge.nextStep.TRANSFER_EMERGENCY` | The knowledge service decided the caller needs emergency help; MCP does not execute a transfer. |
| `search_knowledge.nextStep.CHECK_AVAILABILITY` | routing.department contains the department name associated with the knowledge decision. |
| `search_knowledge.nextStep.SAY_COULD_NOT_CHECK` | The requested information could not be checked. |
| `search_knowledge.nextStep.ASK_TO_REPHRASE` | The supplied name, department or question could not resolve the request. |

### Examples

Examples come from the development stubs (facility date 2026-10-01, Thursday, 10:00); names and
identifiers are fixtures. Live values differ; field names and shapes do not.

**1. Hospital information**

Arguments:

```json
{
  "question": "ಪಾರ್ಕಿಂಗ್ ಇದೆಯಾ",
  "language": "kn"
}
```

Structured result:

```json
{
  "outcome": "ANSWERED",
  "nextStep": "SPEAK_ANSWER",
  "answer": {
    "text": "ಹೌದು. ನೆಲಮಾಳಿಗೆಯಲ್ಲಿ ಉಚಿತ ಪಾರ್ಕಿಂಗ್ ಇದೆ; ಮುಖ್ಯ ದ್ವಾರದ ಪಕ್ಕದ ರಸ್ತೆಯಿಂದ ಒಳಗೆ ಬನ್ನಿ.",
    "language": "kn"
  },
  "sourceId": "kb_parking",
  "destination": null,
  "routing": null,
  "detail": null
}
```

**2. Emergency routing**

Arguments:

```json
{
  "question": "Dr Garima, I have chest pain",
  "language": "en"
}
```

Structured result:

```json
{
  "outcome": "ROUTING_REQUIRED",
  "nextStep": "TRANSFER_EMERGENCY",
  "answer": null,
  "sourceId": "routing-0",
  "destination": null,
  "routing": {
    "decision": "EMERGENCY_TRANSFER",
    "speak": {
      "text": "This may be an emergency. I am connecting you to the emergency desk now.",
      "language": "en"
    },
    "department": null
  },
  "detail": null
}
```

`TRANSFER_EMERGENCY` is the knowledge service's decision. MCP does not transfer the call.

## record_call_summary

Stores one summary per call, covering the whole conversation. The first accepted summary for a call is final. Call identity and start time come from trusted headers. One intent and outcome represent the call; other results are described in summaryText. CALLBACK_NOTED records callback details and creates no appointment or callback task. SAVED: a new summary was stored. ALREADY_SAVED: a summary for this call is already stored and nothing was changed, including when the submitted text differs. INVALID_REQUEST: input validation failed; fields identifies rejected fields. NOT_CONFIRMED: persistence is unverified or temporarily unavailable. NOT_SAVED: trusted call context is missing or invalid, or the operational service refused credentials.

### How to call

One summary covers the whole call, including the last tool result. The first accepted summary is final.

| Field | Rule |
|---|---|
| `intent`, `outcome`, `summaryText` | Always required. `summaryText` is nonblank, at most 500 characters, and is never shortened by MCP; longer text returns `INVALID_REQUEST` with `fields: ["summaryText"]`. |
| `callerMobile` | Required when `outcome` is `CALLBACK_NOTED`. When sent, exactly 10 digits. |
| `appointmentId` | Optional identifier returned by manage_booking; rejected with CALLBACK_NOTED. |
| `transferredTo` | Only with `TRANSFERRED` or `EMERGENCY_TRANSFERRED`; refused with any other outcome. |
| `doctorId`, `language` | Optional. `language` `en`, `kn` or `hi` is stored; other codes are dropped. |
| Caller name, symptoms, dates, sessions | These facts belong within summaryText. There are no separate fields for them; any such argument is rejected. |

Headers: X-Call-Id and X-Call-Started-At (ISO timestamp with offset). Without them the result is
`NOT_SAVED` and nothing is sent.

### Input schema (exact)

```json
{
  "properties": {
    "appointmentId": {
      "anyOf": [
        {
          "maxLength": 64,
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Optional identifier of the appointment request associated with the call."
    },
    "callerMobile": {
      "anyOf": [
        {
          "maxLength": 20,
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Callback number the caller gave; required for CALLBACK_NOTED; distinct from caller ID."
    },
    "doctorId": {
      "anyOf": [
        {
          "maxLength": 64,
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Optional identifier of the doctor associated with the call."
    },
    "intent": {
      "description": "Required call-intent category.",
      "enum": [
        "AVAILABILITY",
        "BOOKING",
        "RESCHEDULE",
        "CANCEL",
        "GENERAL_INFO",
        "LAB",
        "INSURANCE",
        "EMERGENCY",
        "AMBULANCE",
        "SYMPTOM_ROUTING",
        "COMPLAINT",
        "ADMIN",
        "OTHER"
      ],
      "type": "string"
    },
    "language": {
      "anyOf": [
        {
          "maxLength": 16,
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Optional call language; en, kn and hi primary codes map to the operational contract. Other codes are omitted upstream."
    },
    "outcome": {
      "description": "Required hospital-facing call outcome category.",
      "enum": [
        "RESOLVED_BY_AGENT",
        "APPOINTMENT_NOTED",
        "APPOINTMENT_CANCELLED",
        "APPOINTMENT_RESCHEDULED",
        "TRANSFERRED",
        "EMERGENCY_TRANSFERRED",
        "AMBULANCE_NUMBER_GIVEN",
        "CALLBACK_NOTED",
        "ABANDONED"
      ],
      "type": "string"
    },
    "summaryText": {
      "description": "Required. Summary of the whole call in plain sentences, up to 500 characters: what the caller asked, what was explained or done, and any follow-up promised. Contains all relevant information mentioned in the call, including: the caller's name, the callback phone number, the symptoms or reason the caller described, the doctor's name, the department, and the requested date, time, session and callback reason. Not a transcript.",
      "maxLength": 500,
      "type": "string"
    },
    "transferredTo": {
      "anyOf": [
        {
          "maxLength": 64,
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Optional destination associated with a transfer outcome."
    }
  },
  "required": [
    "intent",
    "outcome",
    "summaryText"
  ],
  "type": "object"
}
```

### Parameters

| Field path | Type / constraints (JSON Schema) | Presence | Meaning |
|---|---|---|---|
| `record_call_summary.input.appointmentId` | `{"anyOf":[{"maxLength":64,"type":"string"},{"type":"null"}]}` | optional | Optional identifier of the appointment request associated with the call. |
| `record_call_summary.input.callerMobile` | `{"anyOf":[{"maxLength":20,"type":"string"},{"type":"null"}]}` | optional | Callback number the caller gave; required for CALLBACK_NOTED; distinct from caller ID. |
| `record_call_summary.input.doctorId` | `{"anyOf":[{"maxLength":64,"type":"string"},{"type":"null"}]}` | optional | Optional identifier of the doctor associated with the call. |
| `record_call_summary.input.intent` | `{"enum":["AVAILABILITY","BOOKING","RESCHEDULE","CANCEL","GENERAL_INFO","LAB","INSURANCE","EMERGENCY","AMBULANCE","SYMPTOM_ROUTING","COMPLAINT","ADMIN","OTHER"],"type":"string"}` | required | Required call-intent category. |
| `record_call_summary.input.language` | `{"anyOf":[{"maxLength":16,"type":"string"},{"type":"null"}]}` | optional | Optional call language; en, kn and hi primary codes map to the operational contract. Other codes are omitted upstream. |
| `record_call_summary.input.outcome` | `{"enum":["RESOLVED_BY_AGENT","APPOINTMENT_NOTED","APPOINTMENT_CANCELLED","APPOINTMENT_RESCHEDULED","TRANSFERRED","EMERGENCY_TRANSFERRED","AMBULANCE_NUMBER_GIVEN","CALLBACK_NOTED","ABANDONED"],"type":"string"}` | required | Required hospital-facing call outcome category. |
| `record_call_summary.input.summaryText` | `{"maxLength":500,"type":"string"}` | required | Required. Summary of the whole call in plain sentences, up to 500 characters: what the caller asked, what was explained or done, and any follow-up promised. Contains all relevant information mentioned in the call, including: the caller's name, the callback phone number, the symptoms or reason the caller described, the doctor's name, the department, and the requested date, time, session and callback reason. Not a transcript. |
| `record_call_summary.input.transferredTo` | `{"anyOf":[{"maxLength":64,"type":"string"},{"type":"null"}]}` | optional | Optional destination associated with a transfer outcome. |

### Output fields

| Field path | Type / constraints (JSON Schema) | Presence | Meaning |
|---|---|---|---|
| `record_call_summary.output.fields` | `{"items":{"type":"string"},"type":"array"}` | optional | Names of rejected fields; present only on INVALID_REQUEST, possibly empty when no safe field names are available. |
| `record_call_summary.output.outcome` | `{"enum":["SAVED","ALREADY_SAVED","INVALID_REQUEST","NOT_CONFIRMED","NOT_SAVED"],"type":"string"}` | required | Result category, defined below. |

### Outcomes and nextStep meanings

| Code | Meaning |
|---|---|
| `record_call_summary.outcome.SAVED` | A new summary was stored, verified by a valid 201 response for this call. |
| `record_call_summary.outcome.ALREADY_SAVED` | A valid 200 returned this call's existing summary; nothing changed, even if the new input differs. |
| `record_call_summary.outcome.INVALID_REQUEST` | Local validation or the owner's definite 400 rejected the request; fields contains safe field names. |
| `record_call_summary.outcome.NOT_CONFIRMED` | Persistence is unverified or temporarily unavailable, including unanswered writes, malformed success, call-ID mismatch, transport failures, rate limits and server failures. |
| `record_call_summary.outcome.NOT_SAVED` | Trusted call ID/start is missing or malformed, or credentials were definitely refused. A previous possibly committed send takes precedence and remains NOT_CONFIRMED. |

### Examples

Examples come from the development stubs (facility date 2026-10-01, Thursday, 10:00); names and
identifiers are fixtures. Live values differ; field names and shapes do not.

**1. Appointment call saved**

Arguments:

```json
{
  "intent": "BOOKING",
  "outcome": "APPOINTMENT_NOTED",
  "doctorId": "doc_garima",
  "appointmentId": "appt_0001",
  "language": "en",
  "summaryText": "Lakshmi Rao (9000000101) has had fever for three days and asked for Dr. Garima, General Medicine. Appointment request noted for 2026-10-02, Morning session, preferred 09:30; told it is a request, not a confirmed time."
}
```

Structured result:

```json
{
  "outcome": "SAVED"
}
```

**2. Callback call saved**

Arguments:

```json
{
  "intent": "AVAILABILITY",
  "outcome": "CALLBACK_NOTED",
  "callerMobile": "9000000101",
  "doctorId": "doc_kiran_hegde",
  "language": "kn",
  "summaryText": "Lakshmi Rao, 9000000101, asked for Dr. Kiran Hegde this evening; board UNKNOWN; callback promised."
}
```

Structured result:

```json
{
  "outcome": "SAVED"
}
```

**3. Second summary for the same call**

Arguments:

```json
{
  "intent": "BOOKING",
  "outcome": "APPOINTMENT_NOTED",
  "summaryText": "second attempt"
}
```

Structured result:

```json
{
  "outcome": "ALREADY_SAVED"
}
```

Nothing was changed; the first summary stays.

**4. CALLBACK_NOTED without callerMobile**

Arguments:

```json
{
  "intent": "AVAILABILITY",
  "outcome": "CALLBACK_NOTED",
  "summaryText": "x"
}
```

Structured result:

```json
{
  "outcome": "INVALID_REQUEST",
  "fields": [
    "callerMobile"
  ]
}
```

**5. Unknown argument (rejected before the tool runs)**

Arguments:

```json
{
  "intent": "AVAILABILITY",
  "outcome": "RESOLVED_BY_AGENT",
  "summaryText": "x",
  "callerName": "A"
}
```

Result (`isError: true`, text content; no structured result):

```text
Invalid call summary arguments. Check required fields, types and limits.
```

## Availability policy reason codes

These codes describe owner facts or an incomplete check; they are not clinical routing decisions.

| Reason | Meaning |
|---|---|
| ON_CALL_DOCTOR | On-call doctor has no confirmed, usable entry; desk assistance is the disposition, without callback metadata. Working hours also require handoff because on-call doctors have no usual schedule. |
| BOARD_UNKNOWN | Owner board or slot session status is UNKNOWN; ordinary doctors require callback, on-call doctors require handoff. |
| BOARD_STALE | Owner marks today's row stale. |
| BOARD_ENTRY_MISSING | Today has no board entry for this doctor. |
| SESSION_NOT_ON_BOARD | Requested session is absent from today's board. |
| BOARD_NOT_CONFIRMED | Ordinary attendance is NOT_CONFIRMED with slots disabled. With enabled slots an open bookable block can instead permit a request. |
| CANCELLED | Owner cancelled this session. |
| SESSION_ENDED | Supplied end time has passed in facility time. |
| NOT_USUAL_DAY | Usual schedule has no session on this future weekday. |
| SESSION_NOT_USUAL | Requested session is not a usual session on that future date. |
| NO_USUAL_SCHEDULE | No usual schedule is supplied for this doctor. |
| PROFILE_UNAVAILABLE | Required profile could not be read. |
| TIME_OUTSIDE_SESSION | Requested time is outside known windows; with slots, no block contains the time, the containing block is closed or ended, or a supplied session label does not match its session. A full containing block is SLOT_FULL. |
| SESSION_REQUIRED | Differing session decisions need a session/time selection. |
| TIME_NOT_VERIFIABLE | Specific time cannot be checked against an incomplete window. |
| SEARCH_INCOMPLETE | Some candidates remain unchecked or failed; absence is not established. |
| NO_OPEN_SLOT | This session has no open slot. |
| SLOT_FULL | The chosen time's block is full. Checked alternatives are sessions/openSlots in the same result; an owner write rejection carries none. |

AVAILABILITY is date-specific and requires a target and date. WORKING_HOURS permits no date and
returns usual hours, never current attendance. Date errors are DATE_REQUIRED, DATE_FORMAT and PAST_DATE.
Same-decision sessions require no session selection; with slots enabled a booking time is still required.
Future REGULAR/VISITING dates use slot facts when enabled and usual hours otherwise, attendance not
confirmed. `status` retains Manoj's value, while `decision` is MCP's.

| Decision | Meaning |
|---|---|
| APPOINTMENT_REQUEST | Supplied facts permit an appointment request, not a reservation. |
| SLOT_CHECK_REQUIRED | Doctor matches the request; slots have not been checked. Slot availability is known only after a doctor-specific check. |
| CALLBACK_REQUIRED | Ordinary unresolved schedule; callback details belong to a summary only. |
| HANDOFF_REQUIRED | Desk assistance is the disposition; an on-call doctor has no confirmed, usable entry. No callback metadata. |
| NOT_AVAILABLE | Facts exclude the requested session/date/time. |
| COULD_NOT_CHECK | A required read failed; no negative availability claim. |

`openSlots` lists the owner's open blocks when the session permits a request. `openSlots: null` means
not checked (disabled, WORKING_HOURS or department selection pending); `[]` means checked and no block
is offered (none open, or the session does not permit a request). When slots apply, CREATE or RESCHEDULE
times outside the returned blocks are refused. A `oneDay` session was desk-added for this requested date, not part of the regular
schedule: `daysOfWeek` is empty and `onRequestedDate` is true. Null `start`/`end` mean the owner supplied
no hours; such a session has no bookable time. Today's slot-only sessions use the date-specific board format without
an extra oneDay field.

| Detail | Meaning |
|---|---|
| TIME_REQUIRED | With slots enabled, preferredTime (CREATE) or newPreferredTime (RESCHEDULE) is required; ASK_WHICH_TIME includes sessions with openSlots. |
| SLOT_FULL | The chosen time's block is full; checked alternatives are sessions/openSlots in this result. An owner write rejection carries none. |
| SLOTS_UNAVAILABLE | Required slot facts could not be obtained or validated; no booking is submitted. |
| CAPABILITIES_UNAVAILABLE | Required department capability facts could not be obtained or validated; availability could not be checked. |

Callback names, requested dates/sessions and reason may be placed in summaryText, but their presence
is not enforced; callerMobile remains required for CALLBACK_NOTED. Summary-quality acceptance belongs
to voice integration. No new headers or credentials are introduced by this policy.

## Changes in schema 2026-10-05.1

- Doctor `journey` became `decision`; owner board `status` remained unchanged.
- CALLBACK_ONLY/DESK decisions, `expired`, `unknownSessions`, and `callback.ask`/`say` were removed.
- `purpose` was added; `date` became schema-optional, required in-band for AVAILABILITY.
- `manage_booking.departmentId` was removed; CREATE requires a doctor.
- Known limitation: sessions crossing midnight are unsupported.

## Changes in schema 2026-10-06.1

- In this older release, working hours for a single on-call doctor or empty schedule used the full
  CALLBACK_REQUIRED result, including reason and summaryOutcome. The on-call rule is superseded by
  HANDOFF_REQUIRED in the slots release; ordinary empty schedules still require callback. ON_CALL_DOCTOR
  replaced NO_REGULAR_HOURS (emitted in schema 2026-10-05.1 for on-call working hours).
- A single doctor with hours returns WORKING_HOURS/PRESENT_WORKING_HOURS, without an appointment offer.
  bookableFound is always zero for WORKING_HOURS, including department queries; schedule matches still
  bound the profile search. Department hours include on-call facts within the existing capped list.
- Future-session mismatches preserve same-day alternatives; sessionMatched checks the requested weekday.
- When the doctor is unavailable for the whole requested scope, booking reports the doctor's own reason
  (CANCELLED, SESSION_ENDED, NOT_USUAL_DAY or SESSION_NOT_USUAL), even when a preferred time was given;
  TIME_OUTSIDE_SESSION applies only when the doctor has bookable sessions and the chosen time falls outside them.
- The existing mixed-session choice rule remains unchanged pending a separate decision (G-1).

Schema 2026-10-06.1 is deployed (canary image `frontdesk-mcp:36336aa`, 6 October 2026). A gateway that
discovered 2026-10-05.1 retains an older schema until rediscovery; registration verifies input schemas
only, so it does not establish output-schema compatibility through the voice virtual server.


## Changes in schema 2026-10-08.1 (slots release, not yet deployed)

- Published the complete slot response contract: openSlots, oneDay, nullable required session hours,
  owner slot status, slotTime/slotMoved, DOCTORS_MATCHED, SLOT_CHECK_REQUIRED, HANDOFF_REQUIRED as a
  decision, NO_OPEN_SLOT, SLOT_FULL and ASK_WHICH_TIME.
- Descriptions and this guide specify the final release behaviour. Publication alone does not activate
  it; no partial phase is approved for deployment. The canary remains on schema 2026-10-06.1.
- ContextForge discovery can retain the previous schema until refreshed after deployment. Voice
  integration compatibility depends on both input and output schemas exposed by the virtual server.
