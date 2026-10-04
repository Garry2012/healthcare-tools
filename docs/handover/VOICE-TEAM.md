# MCP tool interface

Schema version: `2026-10-04.1`

## Endpoint and transport

Streamable HTTP at `/mcp/` on the configured MCP host. The direct URL is the deployment's
`MCP_PUBLIC_URL`; for example, `https://<mcp-host>/mcp/`. The ContextForge virtual-server URL is a
separate gateway endpoint supplied by its owner. This document does not assert which revision is deployed.

## Authentication

| Scope | Direct MCP bearer | Accessible tools |
|---|---|---|
| Conversation / gateway | MCP_BEARER_TOKEN | get_doctor_availability, manage_booking, search_knowledge |
| Call-end lifecycle | MCP_LIFECYCLE_BEARER_TOKEN | record_call_summary only |

The HTTP header is `Authorization: Bearer <credential>`. The server enforces these scopes.
A ContextForge client authenticates with gateway-issued scoped access; its upstream MCP bearer is
separate. Credentials, caller authority and lifecycle context are not tool arguments.

## Trusted request headers

| Header | Meaning and format |
|---|---|
| X-Call-Id | Platform call identifier: 1–64 ASCII letters, digits, dots, underscores, colons or hyphens. Required for booking writes and summaries. |
| X-Caller-Number | Trusted caller number under the configured calling-code rule. With accepted verification, authorizes LIST/CANCEL/RESCHEDULE. Distinct from contact fields. |
| X-Caller-Verification | Verification label in ACCEPTED_CALLER_VERIFICATION; default SIP_CALLER_ID. A number alone does not establish authority. |
| X-Operation-Id | Confirmed-write identifier with the same 1–64 character syntax as call ID. Required for CREATE/CANCEL/RESCHEDULE. Same call/action/operation identifies the same payload; changed payload conflicts. |
| X-Call-Started-At | ISO timestamp with timezone offset; required for record_call_summary. |

Malformed identifiers/timing are treated as absent. Header names are case-insensitive. Tenant and
principal derive from deployment configuration and authentication, not model arguments.

The tables below describe the pinned wire schema, including nested `$defs` types. “Required” means
schema-required; action-specific requirements appear in the meaning column. Optional fields can have
server defaults; the schema remains authoritative for those defaults. Existing callback text fields
are described without reproducing their spoken content. Outcomes and nextStep are returned codes,
not implementation instructions for the calling application.

## get_doctor_availability

Doctor or department working hours qualified by the live availability board for a date. Applies to directory and availability queries. IN, LATE, CANCELLED, NOT_CONFIRMED and UNKNOWN are board statuses; usual hours are independent of live attendance. Ambiguous directory matches return choices. CALLBACK_REQUIRED means the board is UNKNOWN and no appointment can be recorded; callback contact details are recorded in a call summary with CALLBACK_NOTED. A mixed result can contain individual doctors with journey=CALLBACK_ONLY.

### Parameters

| Field path | Type / constraints (JSON Schema) | Presence | Meaning |
|---|---|---|---|
| `get_doctor_availability.input.date` | `{"maxLength":10,"type":"string"}` | required | Required date: 'today' or YYYY-MM-DD. Other relative dates are not accepted. |
| `get_doctor_availability.input.departmentId` | `{"anyOf":[{"maxLength":64,"type":"string"},{"type":"null"}]}` | optional | Directory identifier for a selected department; optional alternative to departmentName. |
| `get_doctor_availability.input.departmentName` | `{"anyOf":[{"maxLength":100,"type":"string"},{"type":"null"}]}` | optional | Department or speciality name for directory search; optional. |
| `get_doctor_availability.input.doctorId` | `{"anyOf":[{"maxLength":64,"type":"string"},{"type":"null"}]}` | optional | Directory identifier for a selected doctor; optional alternative to doctorName. |
| `get_doctor_availability.input.doctorName` | `{"anyOf":[{"maxLength":100,"type":"string"},{"type":"null"}]}` | optional | Doctor name for directory search, in the caller's original wording; optional. |
| `get_doctor_availability.input.gender` | `{"anyOf":[{"enum":["FEMALE","MALE"],"type":"string"},{"type":"null"}]}` | optional | Optional doctor gender filter: FEMALE or MALE. |
| `get_doctor_availability.input.session` | `{"anyOf":[{"maxLength":40,"type":"string"},{"type":"null"}]}` | optional | Optional session label, such as morning or evening, restricting the board scope. |

### Output fields

| Field path | Type / constraints (JSON Schema) | Presence | Meaning |
|---|---|---|---|
| `get_doctor_availability.output.callback` | `{"anyOf":[{"$ref":"#/$defs/Callback"},{"type":"null"}]}` | optional | Existing callback metadata associated with UNKNOWN availability. |
| `get_doctor_availability.output.choices` | `{"items":{"$ref":"#/$defs/DoctorChoice"},"type":"array"}` | optional | Ambiguous doctor-directory matches. |
| `get_doctor_availability.output.complete` | `{"type":"boolean"}` | optional | Whether the returned match list is complete. |
| `get_doctor_availability.output.department` | `{"anyOf":[{"$ref":"#/$defs/DepartmentChoice"},{"type":"null"}]}` | optional | Resolved department object; within AppointmentOut, the operational department identifier. |
| `get_doctor_availability.output.departmentChoices` | `{"items":{"$ref":"#/$defs/DepartmentChoice"},"type":"array"}` | optional | Ambiguous department-directory matches. |
| `get_doctor_availability.output.detail` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Machine-readable reason for a non-success result; optional. |
| `get_doctor_availability.output.doctors` | `{"items":{"$ref":"#/$defs/DoctorAvailability"},"type":"array"}` | optional | Resolved doctors with usual hours and live board information. |
| `get_doctor_availability.output.facilityToday` | `{"type":"string"}` | required | Current calendar date in the configured facility timezone (YYYY-MM-DD). |
| `get_doctor_availability.output.nextStep` | `{"enum":["OFFER_APPOINTMENT_REQUEST","ASK_WHICH_DOCTOR","ASK_WHICH_DEPARTMENT","ASK_CALLBACK_DETAILS","TRANSFER_DESK","ASK_TO_REPHRASE","SAY_COULD_NOT_CHECK","ASK_EXPLICIT_DATE"],"type":"string"}` | required | Machine-readable disposition code, defined below. |
| `get_doctor_availability.output.outcome` | `{"enum":["AVAILABILITY","CLARIFICATION_NEEDED","CALLBACK_REQUIRED","NOT_FOUND","COULD_NOT_CHECK","INVALID_REQUEST"],"type":"string"}` | required | Result category, defined below. |
| `get_doctor_availability.output.requestedDate` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Resolved availability date (YYYY-MM-DD), or null when unresolved. |
| `get_doctor_availability.output.retryAfterSeconds` | `{"anyOf":[{"type":"integer"},{"type":"null"}]}` | optional | Upstream retry delay in seconds when supplied; optional. |
| `get_doctor_availability.output.sessionMatched` | `{"anyOf":[{"type":"boolean"},{"type":"null"}]}` | optional | Whether the requested session matched; null when not evaluated. |
| `get_doctor_availability.output.totalMatches` | `{"anyOf":[{"type":"integer"},{"type":"null"}]}` | optional | Known match count, or null. |
| `get_doctor_availability.output.weekday` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Weekday of the requested date, or null when unresolved. |
| `get_doctor_availability.output.$defs.BoardSessionOut.delayMinutes` | `{"anyOf":[{"type":"integer"},{"type":"null"}]}` | optional | Board delay in minutes when supplied. |
| `get_doctor_availability.output.$defs.BoardSessionOut.expectedEndTime` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Board expected end time in facility local time when supplied. |
| `get_doctor_availability.output.$defs.BoardSessionOut.expectedTime` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Board expected start time or requested appointment time; not a guaranteed reservation. |
| `get_doctor_availability.output.$defs.BoardSessionOut.expired` | `{"type":"boolean"}` | required | Today-only end-time expiry; false for CANCELLED/UNKNOWN, missing end time or a date other than today. |
| `get_doctor_availability.output.$defs.BoardSessionOut.isStale` | `{"type":"boolean"}` | required | Owner-supplied board staleness flag; not an adapter-computed age threshold. |
| `get_doctor_availability.output.$defs.BoardSessionOut.note` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Owner-authored caller-facing board note, limited to 200 characters. |
| `get_doctor_availability.output.$defs.BoardSessionOut.session` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | required | Board session label when present. |
| `get_doctor_availability.output.$defs.BoardSessionOut.status` | `{"enum":["IN","LATE","CANCELLED","NOT_CONFIRMED","UNKNOWN"],"type":"string"}` | required | Board attendance status or appointment request status, according to its containing type and enum. |
| `get_doctor_availability.output.$defs.Callback.ask` | `{"type":"string"}` | optional | Existing server-provided callback-name/number text field; retained response compatibility. |
| `get_doctor_availability.output.$defs.Callback.say` | `{"type":"string"}` | optional | Existing server-provided callback acknowledgement text field; retained response compatibility. |
| `get_doctor_availability.output.$defs.Callback.summaryOutcome` | `{"const":"CALLBACK_NOTED","type":"string"}` | optional | CALLBACK_NOTED identifies the callback call-summary category. |
| `get_doctor_availability.output.$defs.DepartmentChoice.id` | `{"type":"string"}` | required | Department directory identifier. |
| `get_doctor_availability.output.$defs.DepartmentChoice.name` | `{"type":"string"}` | required | Doctor or department display name, according to its containing type. |
| `get_doctor_availability.output.$defs.DoctorAvailability.attendanceType` | `{"enum":["REGULAR","VISITING","ON_CALL"],"type":"string"}` | required | Operational attendance classification: REGULAR, VISITING or ON_CALL. |
| `get_doctor_availability.output.$defs.DoctorAvailability.board` | `{"items":{"$ref":"#/$defs/BoardSessionOut"},"type":"array"}` | required | Date/session-specific board rows. |
| `get_doctor_availability.output.$defs.DoctorAvailability.dataConfirmed` | `{"anyOf":[{"type":"boolean"},{"type":"null"}]}` | optional | Owner confirmation metadata; null means unspecified. |
| `get_doctor_availability.output.$defs.DoctorAvailability.departments` | `{"items":{"type":"string"},"type":"array"}` | required | Department names associated with the doctor. |
| `get_doctor_availability.output.$defs.DoctorAvailability.doctorId` | `{"type":"string"}` | required | Operational doctor identifier. |
| `get_doctor_availability.output.$defs.DoctorAvailability.gender` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Doctor gender when available. |
| `get_doctor_availability.output.$defs.DoctorAvailability.journey` | `{"enum":["APPOINTMENT_REQUEST","CALLBACK_ONLY","DESK"],"type":"string"}` | required | APPOINTMENT_REQUEST: request path available; CALLBACK_ONLY: UNKNOWN board; DESK: desk disposition. |
| `get_doctor_availability.output.$defs.DoctorAvailability.name` | `{"type":"string"}` | required | Doctor or department display name, according to its containing type. |
| `get_doctor_availability.output.$defs.DoctorAvailability.unknownSessions` | `{"items":{"type":"string"},"type":"array"}` | optional | Session labels with UNKNOWN availability. |
| `get_doctor_availability.output.$defs.DoctorAvailability.usualSessions` | `{"anyOf":[{"items":{"$ref":"#/$defs/UsualSessionOut"},"type":"array"},{"type":"null"}]}` | required | Usual schedule, independent of live attendance; null when no profile was fetched. |
| `get_doctor_availability.output.$defs.DoctorChoice.departments` | `{"items":{"type":"string"},"type":"array"}` | required | Department names associated with the doctor. |
| `get_doctor_availability.output.$defs.DoctorChoice.doctorId` | `{"type":"string"}` | required | Operational doctor identifier. |
| `get_doctor_availability.output.$defs.DoctorChoice.gender` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Doctor gender when available. |
| `get_doctor_availability.output.$defs.DoctorChoice.name` | `{"type":"string"}` | required | Doctor or department display name, according to its containing type. |
| `get_doctor_availability.output.$defs.UsualSessionOut.daysOfWeek` | `{"items":{"type":"string"},"type":"array"}` | required | Weekday codes for the usual session. |
| `get_doctor_availability.output.$defs.UsualSessionOut.end` | `{"type":"string"}` | required | Usual session end time in facility local time. |
| `get_doctor_availability.output.$defs.UsualSessionOut.label` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | required | Usual schedule session label. |
| `get_doctor_availability.output.$defs.UsualSessionOut.onRequestedDate` | `{"type":"boolean"}` | required | Whether the usual session applies to the requested weekday. |
| `get_doctor_availability.output.$defs.UsualSessionOut.start` | `{"type":"string"}` | required | Usual session start time in facility local time. |

### Outcomes and nextStep meanings

| Code | Meaning |
|---|---|
| `get_doctor_availability.outcome.AVAILABILITY` | Directory/schedule/board data are returned. Individual doctors can still have journey=CALLBACK_ONLY. |
| `get_doctor_availability.outcome.CLARIFICATION_NEEDED` | Multiple directory matches require a doctor or department selection. |
| `get_doctor_availability.outcome.CALLBACK_REQUIRED` | The relevant board is UNKNOWN; an appointment write is not submitted. Callback details belong to a CALLBACK_NOTED summary. |
| `get_doctor_availability.outcome.NOT_FOUND` | No matching doctor or department was found. |
| `get_doctor_availability.outcome.COULD_NOT_CHECK` | A read could not be completed; this is not an empty or negative result. |
| `get_doctor_availability.outcome.INVALID_REQUEST` | Request validation failed; fields or detail identify the issue when available. |
| `get_doctor_availability.nextStep.OFFER_APPOINTMENT_REQUEST` | An appointment request is possible for the returned scope; this is not a reservation. |
| `get_doctor_availability.nextStep.ASK_WHICH_DOCTOR` | Multiple doctor matches require a selection. |
| `get_doctor_availability.nextStep.ASK_WHICH_DEPARTMENT` | Multiple department matches require a selection. |
| `get_doctor_availability.nextStep.ASK_CALLBACK_DETAILS` | UNKNOWN availability corresponds to callback contact details and a call summary. |
| `get_doctor_availability.nextStep.TRANSFER_DESK` | Desk assistance is the returned disposition; MCP does not execute a telephone transfer. |
| `get_doctor_availability.nextStep.ASK_TO_REPHRASE` | The supplied name, department or question could not resolve the request. |
| `get_doctor_availability.nextStep.SAY_COULD_NOT_CHECK` | The requested information could not be checked. |
| `get_doctor_availability.nextStep.ASK_EXPLICIT_DATE` | An accepted calendar-date value is required. |

## manage_booking

CREATE, LIST, CANCEL or RESCHEDULE an appointment request. Writes require callerConfirmed=true and trusted call/operation headers. CREATE requires patientName, patientMobile, doctorId or departmentId, and visitDate. LIST/CANCEL/RESCHEDULE require verified caller identity. NOTED means a request is recorded, not a confirmed or reserved time. UNCERTAIN means the write may have committed without a verified result. CALLBACK_REQUIRED means the live board is UNKNOWN and the write was not submitted.

### Parameters

| Field path | Type / constraints (JSON Schema) | Presence | Meaning |
|---|---|---|---|
| `manage_booking.input.action` | `{"enum":["CREATE","LIST","CANCEL","RESCHEDULE"],"type":"string"}` | required | Required action: CREATE, LIST, CANCEL or RESCHEDULE. |
| `manage_booking.input.appointmentId` | `{"anyOf":[{"maxLength":64,"type":"string"},{"type":"null"}]}` | optional | Required for CANCEL/RESCHEDULE: identifier of the appointment request. |
| `manage_booking.input.callerConfirmed` | `{"type":"boolean"}` | optional | Boolean declaring the caller's approval of this write; true is required for CREATE/CANCEL/RESCHEDULE. |
| `manage_booking.input.departmentId` | `{"anyOf":[{"maxLength":64,"type":"string"},{"type":"null"}]}` | optional | CREATE department identifier when no individual doctor is selected. |
| `manage_booking.input.doctorId` | `{"anyOf":[{"maxLength":64,"type":"string"},{"type":"null"}]}` | optional | CREATE doctor identifier; doctorId or departmentId is required, but not both. |
| `manage_booking.input.fromDate` | `{"anyOf":[{"maxLength":10,"pattern":"^\\d{4}-\\d{2}-\\d{2}$","type":"string"},{"type":"null"}]}` | optional | Optional LIST lower date filter in YYYY-MM-DD format; past dates are accepted. |
| `manage_booking.input.newPreferredTime` | `{"anyOf":[{"maxLength":5,"pattern":"^\\d{2}:\\d{2}$","type":"string"},{"type":"null"}]}` | optional | Optional RESCHEDULE preferred time in HH:MM 24-hour format. |
| `manage_booking.input.newVisitDate` | `{"anyOf":[{"maxLength":10,"pattern":"^\\d{4}-\\d{2}-\\d{2}$","type":"string"},{"type":"null"}]}` | optional | Required for RESCHEDULE: new date in YYYY-MM-DD format, today or later in facility time. |
| `manage_booking.input.patientMobile` | `{"anyOf":[{"maxLength":20,"type":"string"},{"type":"null"}]}` | optional | Required for CREATE: 10-digit contact mobile. This is contact data, not caller authority. |
| `manage_booking.input.patientName` | `{"anyOf":[{"maxLength":100,"type":"string"},{"type":"null"}]}` | optional | Required for CREATE: patient name; nonblank, at most 100 characters. |
| `manage_booking.input.preferredTime` | `{"anyOf":[{"maxLength":5,"pattern":"^\\d{2}:\\d{2}$","type":"string"},{"type":"null"}]}` | optional | Optional CREATE preferred time in HH:MM 24-hour format; a request, not a reserved time. |
| `manage_booking.input.reasonVerbatim` | `{"anyOf":[{"maxLength":500,"type":"string"},{"type":"null"}]}` | optional | Optional CREATE/CANCEL reason in the caller's original words; forwarded without interpretation. |
| `manage_booking.input.session` | `{"anyOf":[{"maxLength":40,"type":"string"},{"type":"null"}]}` | optional | Optional CREATE board session label restricting the selected doctor's availability scope. |
| `manage_booking.input.status` | `{"anyOf":[{"enum":["NOTED","CONFIRMED_BY_DESK","CHANGED","CANCELLED"],"type":"string"},{"type":"null"}]}` | optional | Optional LIST appointment-status filter. |
| `manage_booking.input.toDate` | `{"anyOf":[{"maxLength":10,"pattern":"^\\d{4}-\\d{2}-\\d{2}$","type":"string"},{"type":"null"}]}` | optional | Optional LIST upper date filter in YYYY-MM-DD format; past dates are accepted. |
| `manage_booking.input.visitDate` | `{"anyOf":[{"maxLength":10,"pattern":"^\\d{4}-\\d{2}-\\d{2}$","type":"string"},{"type":"null"}]}` | optional | Required for CREATE: visit date in YYYY-MM-DD format, today or later in facility time. |

### Output fields

| Field path | Type / constraints (JSON Schema) | Presence | Meaning |
|---|---|---|---|
| `manage_booking.output.appointment` | `{"anyOf":[{"$ref":"#/$defs/AppointmentOut"},{"type":"null"}]}` | optional | Single appointment request returned by a write. |
| `manage_booking.output.appointments` | `{"items":{"$ref":"#/$defs/AppointmentOut"},"type":"array"}` | optional | Appointment requests belonging to the verified caller. |
| `manage_booking.output.callback` | `{"anyOf":[{"$ref":"#/$defs/Callback"},{"type":"null"}]}` | optional | Existing callback metadata associated with UNKNOWN availability. |
| `manage_booking.output.detail` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Machine-readable reason for a non-success result; optional. |
| `manage_booking.output.fields` | `{"items":{"type":"string"},"type":"array"}` | optional | Names of request fields rejected or requiring correction. |
| `manage_booking.output.nextStep` | `{"enum":["SAY_REQUEST_NOTED","SAY_CHANGED","SAY_CANCELLED","OFFER_CHOICES","SAY_NOT_FOUND","ASK_TO_CORRECT","SAY_UNCERTAIN_AND_TRANSFER","TRANSFER_DESK","ASK_CALLBACK_DETAILS","ASK_CONFIRMATION","SAY_COULD_NOT_RECORD","SAY_COULD_NOT_CHECK"],"type":"string"}` | required | Machine-readable disposition code, defined below. |
| `manage_booking.output.outcome` | `{"enum":["NOTED","CHANGED","CANCELLED","FOUND","NOT_FOUND","REJECTED","CONFLICT","UNCERTAIN","IDENTITY_UNAVAILABLE","CALLBACK_REQUIRED","CONFIRMATION_REQUIRED","OPERATION_CONTEXT_MISSING","COULD_NOT_RECORD","COULD_NOT_CHECK","INVALID_REQUEST"],"type":"string"}` | required | Result category, defined below. |
| `manage_booking.output.retryAfterSeconds` | `{"anyOf":[{"type":"integer"},{"type":"null"}]}` | optional | Upstream retry delay in seconds when supplied; optional. |
| `manage_booking.output.$defs.AppointmentOut.appointmentId` | `{"type":"string"}` | required | Operational appointment request identifier. |
| `manage_booking.output.$defs.AppointmentOut.department` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Resolved department object; within AppointmentOut, the operational department identifier. |
| `manage_booking.output.$defs.AppointmentOut.doctorId` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Operational doctor identifier. |
| `manage_booking.output.$defs.AppointmentOut.expectedTime` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Board expected start time or requested appointment time; not a guaranteed reservation. |
| `manage_booking.output.$defs.AppointmentOut.patientName` | `{"type":"string"}` | required | Name on the appointment request; LIST is restricted to the verified caller’s own records. |
| `manage_booking.output.$defs.AppointmentOut.status` | `{"enum":["NOTED","CONFIRMED_BY_DESK","CHANGED","CANCELLED"],"type":"string"}` | required | Board attendance status or appointment request status, according to its containing type and enum. |
| `manage_booking.output.$defs.AppointmentOut.visitDate` | `{"type":"string"}` | required | Appointment visit date (YYYY-MM-DD). |
| `manage_booking.output.$defs.Callback.ask` | `{"type":"string"}` | optional | Existing server-provided callback-name/number text field; retained response compatibility. |
| `manage_booking.output.$defs.Callback.say` | `{"type":"string"}` | optional | Existing server-provided callback acknowledgement text field; retained response compatibility. |
| `manage_booking.output.$defs.Callback.summaryOutcome` | `{"const":"CALLBACK_NOTED","type":"string"}` | optional | CALLBACK_NOTED identifies the callback call-summary category. |

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
| `manage_booking.outcome.UNCERTAIN` | A write may have committed, but its result could not be verified. |
| `manage_booking.outcome.IDENTITY_UNAVAILABLE` | Verified caller authority is unavailable for appointment lookup or modification. |
| `manage_booking.outcome.CALLBACK_REQUIRED` | The relevant board is UNKNOWN; an appointment write is not submitted. Callback details belong to a CALLBACK_NOTED summary. |
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
| `manage_booking.nextStep.ASK_CALLBACK_DETAILS` | UNKNOWN availability corresponds to callback contact details and a call summary. |
| `manage_booking.nextStep.ASK_CONFIRMATION` | The write lacks callerConfirmed=true. |
| `manage_booking.nextStep.SAY_COULD_NOT_RECORD` | The requested write could not be recorded. |
| `manage_booking.nextStep.SAY_COULD_NOT_CHECK` | The requested information could not be checked. |

## search_knowledge

One knowledge-service request for hospital information or symptom-to-department routing. It does not read availability or change appointments. ANSWERED and CLARIFICATION_NEEDED carry owner-provided text in answer.text. Routing results carry text only in routing.speak, when present. TRANSFER_EMERGENCY means the knowledge service decided the caller needs emergency help; TRANSFER_DESK means desk assistance; CHECK_AVAILABILITY identifies a department in routing.department. NO_ANSWER is an owner decision; COULD_NOT_CHECK is a service failure.

### Parameters

| Field path | Type / constraints (JSON Schema) | Presence | Meaning |
|---|---|---|---|
| `search_knowledge.input.language` | `{"maxLength":16,"type":"string"}` | required | Required nonblank language code, up to 16 characters; forwarded unchanged to the knowledge service. |
| `search_knowledge.input.question` | `{"maxLength":500,"type":"string"}` | required | Required original question, untranslated and unsummarised; nonblank, maximum 500 characters. |

### Output fields

| Field path | Type / constraints (JSON Schema) | Presence | Meaning |
|---|---|---|---|
| `search_knowledge.output.answer` | `{"anyOf":[{"$ref":"#/$defs/Speech"},{"type":"null"}]}` | optional | Knowledge-service answer or clarification text; null on routing results. |
| `search_knowledge.output.destination` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Optional knowledge-service destination identifier. |
| `search_knowledge.output.detail` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Machine-readable reason for a non-success result; optional. |
| `search_knowledge.output.nextStep` | `{"enum":["SPEAK_ANSWER","SAY_NO_ANSWER_AND_OFFER_DESK","ASK_CLARIFICATION","TRANSFER_DESK","TRANSFER_EMERGENCY","CHECK_AVAILABILITY","SAY_COULD_NOT_CHECK","ASK_TO_REPHRASE"],"type":"string"}` | required | Machine-readable disposition code, defined below. |
| `search_knowledge.output.outcome` | `{"enum":["ANSWERED","NO_ANSWER","CLARIFICATION_NEEDED","ROUTING_REQUIRED","COULD_NOT_CHECK","INVALID_REQUEST"],"type":"string"}` | required | Result category, defined below. |
| `search_knowledge.output.routing` | `{"anyOf":[{"$ref":"#/$defs/Routing"},{"type":"null"}]}` | optional | Knowledge-service routing decision and associated optional metadata. |
| `search_knowledge.output.sourceId` | `{"anyOf":[{"type":"string"},{"type":"null"}]}` | optional | Optional knowledge-service source identifier. |
| `search_knowledge.output.$defs.Routing.decision` | `{"enum":["ROUTE_DEPARTMENT","DESK_TRANSFER","EMERGENCY_TRANSFER"],"type":"string"}` | required | ROUTE_DEPARTMENT, DESK_TRANSFER or EMERGENCY_TRANSFER from the knowledge service. |
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

## record_call_summary

CALLBACK_NOTED requires a caller-provided 10-digit callerMobile and rejects appointmentId and
transferredTo. transferredTo is valid only for TRANSFERRED or EMERGENCY_TRANSFERRED. Caller names,
requested dates/times and symptoms are part of summaryText, not separate parameters. Accepted text
is sent unchanged; blank or 501–2,000 characters returns INVALID_REQUEST. The outer 2,000-character
argument cap retains framework validation above that limit. No truncation or prefix is applied.

Trusted summary context consists of X-Call-Id and X-Call-Started-At. No duration is sent upstream.
The invocation and per-exchange limit is SUMMARY_DEADLINE_SECONDS (default 8 s, configurable above
0 through 60 s), covering OAuth and any same-request retry. This is separate from the 0.30 s budget
of the other three tools; it is not a sub-second response guarantee.

Store one summary per call, covering the whole conversation. The first accepted summary for a call is final. Call identity and start time come from trusted headers. One intent and outcome represent the call; other results are described in summaryText. CALLBACK_NOTED records callback details and creates no appointment or callback task. SAVED: a new summary was stored. ALREADY_SAVED: a summary for this call is already stored and nothing was changed, including when the submitted text differs. INVALID_REQUEST: input validation failed; fields identifies rejected fields. NOT_CONFIRMED: persistence is unverified or temporarily unavailable. NOT_SAVED: trusted call context is missing or invalid, or the operational service refused credentials.

### Parameters

| Field path | Type / constraints (JSON Schema) | Presence | Meaning |
|---|---|---|---|
| `record_call_summary.input.appointmentId` | `{"anyOf":[{"maxLength":64,"type":"string"},{"type":"null"}]}` | optional | Optional identifier of the appointment request associated with the call. |
| `record_call_summary.input.callerMobile` | `{"anyOf":[{"maxLength":20,"type":"string"},{"type":"null"}]}` | optional | Callback number the caller gave; required for CALLBACK_NOTED; distinct from caller ID. |
| `record_call_summary.input.doctorId` | `{"anyOf":[{"maxLength":64,"type":"string"},{"type":"null"}]}` | optional | Optional identifier of the doctor associated with the call. |
| `record_call_summary.input.intent` | `{"enum":["AVAILABILITY","BOOKING","RESCHEDULE","CANCEL","GENERAL_INFO","LAB","INSURANCE","EMERGENCY","AMBULANCE","SYMPTOM_ROUTING","COMPLAINT","ADMIN","OTHER"],"type":"string"}` | required | Required call-intent category. |
| `record_call_summary.input.language` | `{"anyOf":[{"maxLength":16,"type":"string"},{"type":"null"}]}` | optional | Optional call language; en, kn and hi primary codes map to the operational contract. Other codes are omitted upstream. |
| `record_call_summary.input.outcome` | `{"enum":["RESOLVED_BY_AGENT","APPOINTMENT_NOTED","APPOINTMENT_CANCELLED","APPOINTMENT_RESCHEDULED","TRANSFERRED","EMERGENCY_TRANSFERRED","AMBULANCE_NUMBER_GIVEN","CALLBACK_NOTED","ABANDONED"],"type":"string"}` | required | Required hospital-facing call outcome category. |
| `record_call_summary.input.summaryText` | `{"maxLength":500,"type":"string"}` | required | Required. Summary of the whole call in plain sentences, up to 500 characters: what the caller asked, what was explained or done, and any follow-up promised. Contains all relevant information mentioned in the call, including: the caller's name, the callback phone number, the symptoms or reason the caller described, the doctor's name, the department, and the requested date and time. Not a transcript. |
| `record_call_summary.input.transferredTo` | `{"anyOf":[{"maxLength":64,"type":"string"},{"type":"null"}]}` | optional | Optional destination associated with a transfer outcome. |

### Output fields

| Field path | Type / constraints (JSON Schema) | Presence | Meaning |
|---|---|---|---|
| `record_call_summary.output.fields` | `{"items":{"type":"string"},"type":"array"}` | optional | Names of rejected fields; present only on INVALID_REQUEST, possibly empty when no safe field names are available. |
| `record_call_summary.output.outcome` | `{"enum":["SAVED","ALREADY_SAVED","INVALID_REQUEST","NOT_CONFIRMED","NOT_SAVED"],"type":"string"}` | required | Result category, defined below. |

The wire result contains only outcome, plus fields for INVALID_REQUEST. No summary text, callback
number, stored-summary contents or diagnostics are returned. ALREADY_SAVED does not mean the newly
submitted wording was stored. Summaries use callId deduplication without an Idempotency-Key header;
bookings retain their separate operation keys.

### Outcome meanings

| Code | Meaning |
|---|---|
| `record_call_summary.outcome.SAVED` | A new summary was stored, verified by a valid 201 response for this call. |
| `record_call_summary.outcome.ALREADY_SAVED` | A valid 200 returned this call's existing summary; nothing changed, even if the new input differs. |
| `record_call_summary.outcome.INVALID_REQUEST` | Local validation or the owner's definite 400 rejected the request; fields contains safe field names. |
| `record_call_summary.outcome.NOT_CONFIRMED` | Persistence is unverified or temporarily unavailable, including unanswered writes, malformed success, call-ID mismatch, transport failures, rate limits and server failures. |
| `record_call_summary.outcome.NOT_SAVED` | Trusted call ID/start is missing or malformed, or credentials were definitely refused. A previous possibly committed send takes precedence and remains NOT_CONFIRMED. |
