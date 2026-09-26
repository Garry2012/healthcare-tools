# Front-Desk Voice Agent — Implementation Guide

> **Status: historical design rationale (v1 names).** `openapi.yaml` in this folder is the
> normative contract. Since v2 the API and tools use domain-neutral names; read this guide
> with this mapping:
>
> | v1 (here) | current |
> |---|---|
> | doctor, `doctorId`, `doc_*` ids | resource, `resourceId`, `res_*` ids |
> | department | category |
> | appointment, `/agent/appointments` | booking, `/agent/bookings` |
> | patient, `patient{…}`, `patientName` | customer, `customer{…}`, `customerName` |
> | `manage_appointment` | `manage_booking` (+ `search_knowledge`, a third tool) |
> | `NO_OPD` | `NOT_OFFERED` |
>
> Part 1's reasoning (why the agent never computes dates, why identity comes from headers,
> why failures are never "none available") still holds.

Companion to `openapi.yaml` in this folder. Two halves: **Part 1** is for anyone
(hospital, product, voice team). **Part 2** is for the people building it (backend,
MCP, LiveKit agent). Read Part 1 even if you are an engineer; it is where the design
decisions are.

Everything in `docs/review-fable/` is background evidence for this design and can be
archived. This folder is the specification.

---

## Part 1 — In plain terms

### What the hospital does today, in one paragraph

A patient phones. Reception knows which doctors normally sit when (the printed
schedule), knows what is different today or this week (Dr. X has surgery Thursday,
Dr. Y is on leave), knows what is happening right now (Dr. Z has just arrived, is
running twenty minutes late, has left), and knows how many people are already waiting.
From those four things reception answers "is the doctor there", "till what time",
"can I come at five", "how many ahead", and writes the patient's name and number in a
register. When a doctor cancels, reception goes down the register and phones everyone.

### The four things, named

| Reception's knowledge | In the system | Who writes it | How often |
|---|---|---|---|
| The printed schedule | **Schedule template** — "Dr. Garima: Mon, Thu, Fri; 09:00–12:00 and 15:00–17:00" | Admin, once; edited rarely | Rarely |
| What is different on a date | **Schedule exception** — "Thursday 1 Oct afternoon: unavailable (surgery)", "Sunday 27th: extra session 10–12" | Desk or doctor's office, as soon as known — today **or weeks ahead** | Whenever reality changes |
| What is happening right now | **Live board** — "arrived", "20 min late", "left", "list full" | Desk, during the day | Several times a day |
| The register | **Appointments**, each holding one **slot** | The agent (on the phone) or the desk | Every booking |

**Availability is not a fifth thing.** It is what you get when you lay the four on top
of each other for a given date. Nobody types availability; the system computes it every
time somebody asks. That is the single most important decision in this design, and it
is why "today" and "future" are the same question.

### Today versus future — why there is no difference

Ask "Dr. Garima, tomorrow evening" and the system takes tomorrow's template sessions,
removes or moves anything an exception says, and shows the slots that are still free.
Ask "Dr. Garima, now" and it does exactly the same for today, then also lays the live
board on top: she has arrived, she is late, she has left. A future session simply has
no board yet. One endpoint, one shape, one tool; the date is just a parameter.

### Slots — what "booking" means here

Most Indian OPD runs on tokens: you arrive, pay, get a number, wait your turn. The old
design said "an appointment is noted, never confirmed" and reserved nothing, so the
agent could never say whether there was room. This design gives every session a
**capacity** (from the template: fixed number, or patients-per-hour × hours) and splits
it into **slots**:

- In a **sequence** session (token OPD), a slot is a *position* — "you are 4th, expect
  around 15:30–15:50". The window is computed by the server; the agent just reads it.
- In a **timed** session (specialist clinic, scan), a slot is a *time* — "15:30 to 15:45".

Booking takes one slot atomically. If two callers want the same slot in the same second,
one gets it and the other is offered the next. A share of each session
(`walkInReservePercent`) is never offered by phone, so walk-ins still get seen. The
hospital sets these numbers; where it has not yet, the system uses a default and **says
so** (`capacitySource: DEFAULT`) so nobody mistakes a guess for a rule.

### Certainty — what the agent may promise

Three words, and they are never blurred:

- **Expected** — this is the template; the doctor usually sits then.
- **Not confirmed** — the desk has flagged "we are checking with the doctor".
- **Confirmed** — the desk has confirmed with the doctor. Only this may be spoken as
  "confirmed" (a real caller asked "8:30 is confirmed, right?" and reception said yes;
  the agent must be able to say that truthfully or not at all).

Fees follow the same rule: a fee has `confirmed: true` or the agent does not quote it.

### Languages — why a list of synonyms is not enough

Callers speak English, Kannada, Hindi and switch mid-sentence. Speech-to-text may
deliver Kannada script, romanised Kannada ("charma vaidya"), or an English translation
with the proper nouns wrecked ("zoologist" for urologist — a real transcript). Adding
"skin doctor" as an alias helps only for that one phrase in that one language.

So the design puts **understanding on the server, not in the prompt**:

1. The agent sends the caller's words **as heard**, plus which language the speech
   engine detected. It never translates a doctor's name or picks an id.
2. The server keeps a **lexicon** — hospital-approved terms in any language and script,
   each pointing at a department, a doctor, a day part ("ಸಂಜೆ", "shaam", "evening" →
   EVENING), an emergency red flag, or a transfer destination (lab, pharmacy).
3. The server normalises (Unicode, case, **transliteration** of Indic scripts to
   Latin), then matches: exact lexicon → doctor-name **phonetic** match over the
   transliterated form and known spelling variants → **semantic** match for symptom and
   department phrases with a multilingual sentence model → confidence.
4. Below a confidence threshold it does not guess; it returns a **clarification** with
   two or three options, each with the hospital's approved wording in the caller's
   language, and the agent asks.
5. Every answer carries `localizedNames`, so the agent speaks "ಡಾ. ಗರಿಮಾ", not a
   machine transliteration.

Add a language: add lexicon rows and localized names. No code, no new tool, no new
prompt logic. Whether LiveKit runs a cascade (STT → LLM → TTS) or a speech-to-speech
model changes nothing here: both produce a text tool call, and the server does the same
work on it.

### The permutations, and where each one goes

| Caller opens with | What happens | Transcript |
|---|---|---|
| A doctor's name | Phonetic resolve → slots for that doctor | 182, 198, 201, 230 |
| A department ("any paediatrician") | Lexicon → all doctors in it → soonest slots | 180, 186, 189, 257 |
| A problem ("thyroid doctor", "head pain") | Red-flag check first; then **only** the hospital's approved symptom→department rows; anything else → clarify or transfer | 207, 236, 223 |
| A red flag ("chest pain") | `TRANSFER_EMERGENCY` before anything else | 225 |
| Two doctors with one surname | `CLARIFY: WHICH_DOCTOR`, both offered with their departments | workbook: Ashok G N / Ashok N |
| A wrecked word ("zoologist") | Phonetic + semantic → `CLARIFY: CONFIRM_INTERPRETATION` "urologist?" | 223 |
| Something that is not a consultation (lab report, vaccine, ultrasound) | `TRANSFER_DESK` with the destination | 210, 234, 243, 250 |
| "Anyone available right now?" | No name, no department → all sessions today with `presence` present/arriving | 226, 236 |
| "Lady doctor" | Preference filter; if gender unknown for a doctor it is returned as unknown, never excluded silently | 207 |
| A requested doctor who has left / is full / is on leave | `unavailable[]` with the reason and the **next bookable** session; `alternatives[]` in the same department | 178, 193, 202, 212 |
| "When is my appointment / is he coming?" | One call returns the booking **and** the doctor's live state today | 204, 219 |
| Cancel / move | Checked on caller number **and** patient name; a mismatch looks exactly like "not found" | none observed; required |

### What the desk must do for any of this to be true

Keep the template right. Enter exceptions **as soon as they are known**, not on the
day. Mark arrived / late / left / full on the board. That is the whole ask; everything
the agent says is derived from those three habits.

### When a doctor cancels — the outbound loop

Entering an exception that removes a session does three things at once: the session
disappears from availability, every appointment in it becomes `NEEDS_RESCHEDULE`, and
one **notification** per appointment is created with the structured facts (doctor, old
session, suggested alternatives). Today the desk works that list by phone and marks each
one delivered. Later an SMS or an outbound voice bot works the same list. Nothing about
the API changes when that day comes.

---

## Part 2 — Technical

### 2.1 Bounded contexts and aggregates

| Context | Aggregate root | Invariants |
|---|---|---|
| Directory | `Doctor`, `Department`, `LexiconEntry` | A doctor belongs to ≥ 1 department. Unapproved lexicon entries are never used by the resolver. |
| Scheduling | `ScheduleTemplate` (per doctor), `ScheduleException`, `BoardEntry` | Exceptions never mutate the template. Board facts are per session, per day, and expire at day end. |
| Availability | `SessionInstance` (**computed, never persisted as truth**; may be cached per request only) | Derived strictly by the algorithm in `getAvailability`'s description. |
| Booking | `Appointment` | Exactly one appointment per slot; a slot id encodes session + position/time so uniqueness is a DB constraint, not application logic. |
| Notification | `Notification` | Created only by domain events (exception created, template changed, desk message). |
| Agent facade | none — an application service over the others | Free text in; ids never accepted from the model; identity only from headers. |

**Slot id** = `slot_<sessionId>_<position or HHMM>`; **session id** =
`ses_<doctorId>_<date>_<n>`. Both deterministic, so an offered slot can be re-derived
and validated at booking time without a server-side "option cache".

### 2.2 The availability algorithm (authoritative in the YAML, repeated here)

```
sessions(doctor, date):
  base      = template.sessions where date.weekday ∈ daysOfWeek and template effective on date
  apply exceptions overlapping date, in creation order:
      UNAVAILABLE       -> remove matching session(s)
      TIME_CHANGE       -> start/end := newStart/newEnd, status := CHANGED
      CAPACITY_CHANGE   -> capacity.total := newCapacity
      EXTRA_SESSION     -> add session(newStart,newEnd,newCapacity), status := CHANGED
      TIMING_PENDING    -> timingCertainty := NOT_CONFIRMED
      TIMING_CONFIRMED  -> timingCertainty := CONFIRMED
  if date == today: overlay board(sessionId): presence, expectedStart, delayMinutes,
      sessionEnded, capacityState, lastArrivalTime, timingConfirmed
  capacity.total   = FIXED value | PER_HOUR value × hours | tenant default (capacitySource=DEFAULT)
  walkInReserve    = ceil(total × walkInReservePercent / 100)
  slots            = positions 1..(total − walkInReserve)   [SEQUENCE]
                   | start..end step slotMinutes            [TIMED]
  mark slot.available = no appointment in {BOOKED, CONFIRMED_BY_DESK, RESCHEDULED, ARRIVED} holds it
  expectedWindow(position) = start + (position−1)/patientsPerHour ± tolerance   [SEQUENCE]
  arriveBy         = min(board.lastArrivalTime, end − lastArrivalOffsetMinutes)
  bookable=false when: status CANCELLED | presence LEFT | sessionEnded | capacityState FULL
                     | remaining == 0 | now > arriveBy (today) | bookingPolicy ∈ {DESK_ONLY, NO_OPD}
  if doctor.dataConfirmed == false: timingCertainty = min(timingCertainty, EXPECTED)
```

Never cache across requests. Cost is trivial: one template, a handful of exceptions,
one board row and one indexed appointment query per doctor-date.

### 2.3 Resolver pipeline (server-side NLU, deterministic where it matters)

```
input: utterance, language, doctorName?, department?, symptomText?, when?
1 red-flag: normalise(utterance) ∩ lexicon[RED_FLAG, approved]  -> TRANSFER_EMERGENCY (stop)
2 service:  ∩ lexicon[SERVICE_TRANSFER]                        -> TRANSFER_DESK(destination)
3 doctor:   normalise(doctorName or utterance) -> transliterate -> Double Metaphone
            over doctor.name + nameVariants + lexicon[DOCTOR]  -> candidates with score
4 dept:     lexicon[DEPARTMENT] exact/normalised; else lexicon[SYMPTOM_ROUTE] (approved only);
            else multilingual sentence-embedding similarity to department localizedNames
            (threshold tenant-configured; below threshold => no match, never a guess)
5 when:     expression -> dates via a rule set in facility tz ("today", "tomorrow", weekday
            names, "next <weekday>", day-part words from lexicon[DAY_PART]); explicit dates win
6 decide:   0 doctors & 0 depts -> NO_SERVICE (+suggestions)
            >1 doctors above threshold, not same person -> CLARIFY WHICH_DOCTOR
            doctor found but not in stated dept -> CLARIFY CONFIRM_INTERPRETATION
            1 doctor or 1 dept -> compute sessions for the date range -> OFFER_SLOTS
            requested doctor has no bookable session -> results (with unavailable[]) + alternatives
```

Normalise = NFC → lower → strip honorifics ("Dr", "ಡಾ", "डॉ") → transliterate Indic scripts
to Latin (ICU or `indic-transliteration`). Phonetic = Double Metaphone on the Latin form.
Semantic = a multilingual sentence-embedding model (e.g. LaBSE-class) over department
names and approved symptom phrases; store vectors with the lexicon. All thresholds are
tenant config. Log every resolution with confidence for lexicon mining (`source:
TRANSCRIPT_MINED`, unapproved until the hospital approves).

### 2.4 Identity and disclosure

- `X-Caller-Number` (E.164, from SIP) and `X-Call-Id` are set by the MCP layer from the
  LiveKit job context. The tool input schema **does not contain them**; the model cannot
  supply or override them.
- `patient.phone` is dictated and read back; it is a *contact* number, stored separately
  from `callerNumber`. Lookup, cancel and reschedule match **either** number **and** the
  spoken patient name. Mismatch = neutral 404.
- Landline or withheld caller: `LIST` may accept a spoken `phone` (read-only,
  `identityBasis: SPOKEN_NUMBER`); `CANCEL`/`RESCHEDULE` on a spoken number are refused
  by default (tenant policy).
- Two patients on one number and no name given → `NAME_REQUIRED`, no names disclosed.
- `confirmationCode` (4 digits, per appointment) gives a caller a spoken handle for a
  later call without exposing ids; it is a convenience, not an authentication factor.

### 2.5 Concurrency, idempotency, failure

- Booking is `INSERT appointment (slot_id UNIQUE) … ON CONFLICT → 409 SLOT_UNAVAILABLE`
  with `currentSlots` recomputed. Reschedule is the same insert plus release in one
  transaction.
- `Idempotency-Key` required on every agent POST; store `(key, request-hash, response)`
  for 24 h; replay → 200 + `Idempotent-Replay: true`; same key different body → 409
  `IDEMPOTENCY_CONFLICT`. The MCP layer derives the key as
  `sha256(callId | action | patient.name normalised | slotId)`, so two patients in one
  call get two keys and a retry after a dropped packet gets the same one.
- Writes complete or roll back within 5 s. On timeout the MCP layer retries **once**
  with the same key, then returns `COULD_NOT_RECORD` — never "not booked", never a
  fresh key.
- Reads: 429/5xx → `COULD_NOT_CHECK` in the tool result. The agent says it could not
  check and transfers. It never says "no doctor available" on a failure.

### 2.6 MCP layer — answer to "can Opus build it from the OpenAPI alone?"

**Yes, with this file, and no separate specification is needed** — because the
agent-facing surface (`tag: Agent`, five operations) was designed to *be* the tool
surface. What each option gives:

| Approach | What you get | Verdict |
|---|---|---|
| `FastMCP.from_openapi(spec, client, route_maps=[RouteMap(tags={"Agent"}, mcp_type=TOOL), RouteMap(mcp_type=EXCLUDE)])` | Five tools, one per Agent operation, generated. Names = operationIds. | Works mechanically. Weak points: header injection needs a `mcp_component_fn`/middleware; five tools not two; tool descriptions come from `summary`. Good for a day-one spike. |
| **Hand-written FastMCP 2.14.x server with two tools** (`find_availability`, `manage_appointment(action=…)`), each a ~30-line wrapper calling the Agent operation with headers injected from LiveKit job context | Exactly the surface a small conversational model handles best; injected identity; stable names. This is the pattern already used in `.context/ref-utility-tools` (decorator-registered tools, descriptions in JSON). | **Recommended.** The mapping is the `x-mcp-tools` block at the top of the YAML. |
| ContextForge `integration_type: REST` tools pointing straight at the backend | One tool per endpoint; arguments mapped to path/query/**headers from model arguments**. ContextForge cannot inject `X-Caller-Number` from call context, and its OpenAPI service only extracts schemas — it does not create tools from a spec. | **Not for the agent path.** Use ContextForge as what it is: the registry/proxy that federates the FastMCP server (`integration_type: MCP`), adds auth, observability and rate limits. No business logic in it — consistent with the fork's stated role. |

Tool ↔ REST mapping (also in the YAML `x-mcp-tools`):

| MCP tool | `action` | REST operation | Injected from call context | Model-visible inputs |
|---|---|---|---|---|
| `find_availability` | — | `POST /agent/availability-search` | `X-Call-Id`, `X-Caller-Number` | `utterance`, `language`, `doctorName?`, `department?`, `symptomText?`, `when?`, `preferences?` |
| `manage_appointment` | `BOOK` | `POST /agent/appointments` | + `Idempotency-Key` | `slotId`, `patient{name, phone, relationToCaller?}`, `reasonVerbatim?`, `language`, `requestTimingConfirmation?` |
| `manage_appointment` | `LIST` | `GET /agent/appointments` | `X-Call-Id`, `X-Caller-Number` | `patientName?`, `phone?`, `from?`, `to?` |
| `manage_appointment` | `CANCEL` | `POST /agent/appointments/{id}/cancel` | + `Idempotency-Key` | `appointmentId`, `patientName`, `reasonVerbatim?` |
| `manage_appointment` | `RESCHEDULE` | `POST /agent/appointments/{id}/reschedule` | + `Idempotency-Key` | `appointmentId`, `patientName`, `newSlotId` |

The tool returns the REST body unchanged (it already is the outcome envelope: `outcome`
is the field the agent branches on). On transport failure the wrapper returns
`{ "outcome": "COULD_NOT_CHECK" | "COULD_NOT_RECORD", "retryAfterSeconds": n }`.

### 2.7 LiveKit agent contract (what the prompt owns, what it does not)

The prompt owns: greeting, language, collecting name and phone with read-back, asking
the clarification question the tool hands it, phrasing `timingCertainty` /
`presence` / `arriveBy` / `expectedWindow` in the caller's language, and the emergency
check as a **second** line of defence (the server's red-flag lexicon is the first).

The prompt does **not** own: date arithmetic (send `when.expression`), symptom→department
mapping (send `symptomText`), doctor-name correction (send it as heard), id generation,
fee values, or any decision about whether a slot is free.

Turn budget: one `find_availability` per caller question, one `manage_appointment` per
patient action. Follow-ups such as "till what time?", "how much?", "which position am
I?" are answered from the previous result with **zero** tool calls.

### 2.8 Build order for a two-week pilot

1. **Data:** load doctors, departments, templates from the hospital's sheet; every row
   `dataConfirmed=false` until signed. Load the red-flag list and the symptom routes the
   hospital has approved; nothing else in `SYMPTOM_ROUTE`.
2. **Backend (Python or Node, relational DB):** Directory + Scheduling tables;
   `getAvailability` engine; Booking with the unique slot constraint; idempotency store;
   Agent facade; lexicon + resolver (start with exact + transliteration + phonetic;
   add the embedding step once the lexicon has content).
3. **Desk web app:** board buttons (arrived / late / left / full), exception entry with
   date range, notification work-list. This is what creates the truth.
4. **MCP:** FastMCP server with the two tools; register in ContextForge as an MCP
   gateway; header injection from LiveKit context.
5. **Replay:** all 72 substantive transcripts as scripted dialogues against a seeded
   backend; score per call: correct facts, uncertainty preserved, no wrong-patient
   write, no unsupported "confirmed", no "unavailable" on a failed check.
6. **Pilot** in a limited window with lookup/cancel/reschedule enabled only after the
   hospital signs the identity policy.

### 2.9 Tenant configuration (nothing hospital-specific in code)

`timezone`, `phoneFormat`, `currency`, `dayPartRanges`, `defaultCapacity`,
`lastArrivalOffsetMinutes`, `walkInReservePercent` default, `resolverThresholds`,
`disclosurePolicy`, `cancelOnSpokenNumber`, `deskFollowUpListEnabled`,
`transferDestinations` (lab, pharmacy, insurance, emergency), `supportedLanguages`.
