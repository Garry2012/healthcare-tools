# Plan: correct doctor availability (today = live board, future = usual schedule)

**Revision 6 (final for approval), 5 October 2026.** Plan only. No code, commit, merge or deploy until Garima approves.
Base: `Garry2012/garry2012/mcp-target-required` at `caccbc6`. It contains the unmerged call-summary work; merge that first.

Revision 4:
- applies U1–U7;
- defines behaviour for sessions without `expectedEndTime`;
- keeps four tools;
- gives department future reads bounded concurrency with a deterministic partial result.

Revision 5 (Garima's corrections):
- (1) a specific requested time in a session with no `expectedEndTime` goes to the **front-desk handoff**, never to a request or a callback;
- (2) future department searches run **bounded batches until enough matches, all checked, or the deadline**, with explicit complete and incomplete outcomes.

Both use one new outcome, `HANDOFF_REQUIRED`, paired with the existing `TRANSFER_DESK` next step.

Revision 6 (fixes for Astra's pre-flight findings):
- (1) Manoj's session `status` is kept unchanged; our result is a separate `decision` field (with `reason`) on sessions and doctors;
- (2) a session choice is required only when in-scope sessions have **different** decisions;
- (3) department results list only bookable doctors when any exist, and the counts are explicit (`totalMatches`, `bookableFound`, `complete`);
- (4) gateway verification is stated accurately: `register.py` checks input schemas only, so output schemas are a manual acceptance check.

There are no open behavioural decisions left (section 7).

## 0. Business rules (all decided)

**Today (live board)**
- The live board is for **today only** and authoritative. Never replace `UNKNOWN` or `NOT_CONFIRMED` with the usual schedule.
- Statuses:
  - `IN`: bookable.
  - `LATE`: bookable; delay and expected time reported.
  - `CANCELLED`: not available.
  - `NOT_CONFIRMED`: callback.
  - `UNKNOWN` (stale or missing): callback.
- A session counts as ended **only when `expectedEndTime` is present and has passed** in facility time. With no end time it is never treated as ended.
- Its status is still reported (for example `IN` from 10:30, end not given).
- If the caller asks for a **specific time** in a session with no end time, the time cannot be validated: **no request, no callback → front-desk handoff** (`HANDOFF_REQUIRED` / `TIME_NOT_VERIFIABLE`, `TRANSFER_DESK`).

**Future dates**
- Never call the live board. Use the usual schedule ("normal working hours / attendance days, not confirmed").
- Usual day: request `NOTED`.
- No usual schedule: callback.
- `VISITING` doctors are treated like `REGULAR`, with the same "attendance not confirmed" wording.

**Doctors and departments**
- **ON_CALL doctors:** always callback, never available, never booked, even with `IN` on today's board. This differs from the owner contract and is recorded.
- **No department-level appointment requests.** Department questions lead to choosing a doctor. Every MCP-created appointment has a `doctorId`.

**Working hours**
- Answered by `get_doctor_availability` through a separate, deterministic **working-hours purpose** that reads only the usual schedule and never touches today's decision. There are still four tools.

**Booking choices**
- Mixed sessions with none selected: `INVALID_REQUEST` / `SESSION_REQUIRED`.
- A time outside the session: `NOT_AVAILABLE` / `TIME_OUTSIDE_SESSION`.

**Callback**
- Facts plus `CALLBACK_REQUIRED`; LiveKit collects the name and phone; `record_call_summary` stores them.
- The phone goes in `callerMobile`; everything else goes in `summaryText`. This is a known limitation.

**Confirmation**
- Never "confirmed" unless trusted data says so; created requests are `NOTED`.

---

## 1. Current problem and root cause

1. **Every date reads the board** (`availability.py:88`, `booking.py:216-219`, `booking.py:350-352`).
   - Unwritten future boards return `UNKNOWN`, and `CLAUDE.md:23`'s "UNKNOWN board (today or later)" forces a callback for every future date.
2. **Only `UNKNOWN` blocks** (`board_scope.py:38-39`):
   - `NOT_CONFIRMED` is bookable, or `DESK` for on-call doctors;
   - `CANCELLED`-only rows are bookable (a defect);
   - on-call doctors with `IN` are bookable;
   - ended sessions stay bookable.
3. **The usual schedule never answers future dates.** It only feeds a profile-dependent "missing promised row" rule (`board_scope.py:60`).
4. **Department-level appointment requests are written** (department branch of `booking._board_gate`, `body["department"]`).
5. **Directory lists follow Manoj's arbitrary page order** (`limit=directory_page_size`, no local ordering). Which doctors appear is not deterministic when a department exceeds the page.
6. **The decision logic is spread** across `_overlay`, `_finish`, `_board_gate`, `board_scope` and `outcomes.Callback`.
   - The cached profile read is duplicated (`AvailabilityService.profile`, `BookingService._profile`).
   - So is date parsing (`_requested_date`, `booking._iso`).

**Root cause:** no single policy decides "which date kind and purpose → which data source → which status and attendance means what". The fix is one pure policy module plus one shared retrieval component.

**Recorded contract differences (DECISIONS):**
- (a) `GET /availability` accepts "a given date's" position, but Tarun confirmed the board is today only.
- (b) `AttendanceType.ON_CALL` says "front desk unless the board has a confirmed entry", but D9/U4 say always callback.
- Manoj is asked to document both.

---

## 2. Owner API used (inspected; no contract edits)

| Need | Operation | Notes |
|---|---|---|
| Doctor by name, or a department's doctors (+ gender) | `GET /doctors?query=&department=&gender=&limit=&offset=` → `DoctorSummary` | Has `attendanceType` and `departments`; no schedule; `limit` max 100 |
| Usual schedule | `GET /doctors/{id}` → `usualSchedule[]` (`label?`, `daysOfWeek`, `start`, `end`, all but `label` required) | "Never today's position". Cached by `DirectoryCache` (300 s) |
| Departments | `GET /departments` | Cached |
| Today's board | `GET /availability?date=today&doctorId=` or `&department=` | `expectedTime`/`expectedEndTime` optional |
| Create | `POST /appointments` | We always send `doctorId` |
| Reschedule | `POST /appointments/{id}/reschedule` | Doctor unchanged |

---

## 3. Target behaviour

### 3a. Inputs of `get_doctor_availability` (four-tool surface kept)

| Parameter | Change |
|---|---|
| `purpose` | **New**, `AVAILABILITY` (default) or `WORKING_HOURS` |
| `date` | Now optional in the schema. **Required for `AVAILABILITY`**: missing → `INVALID_REQUEST` / `DATE_REQUIRED`. Optional for `WORKING_HOURS` (only marks `onRequestedDate`; never reads the board) |
| `doctorId`, `doctorName`, `departmentName`, `departmentId`, `session`, `gender` | Unchanged |

### 3b. Date (facility timezone; one resolver for availability and booking)

| Input | Result |
|---|---|
| `"today"`, or the ISO date equal to the facility's today | `TODAY` |
| A later ISO date | `FUTURE` |
| An earlier ISO date | `INVALID_REQUEST` / `PAST_DATE` |
| Anything else ("tomorrow", "05/10", "2026-02-30", "2026-1-5", empty) | `INVALID_REQUEST` / `DATE_FORMAT` (relative dates out of scope) |

### 3c. Doctor decision for `AVAILABILITY` (first matching rule wins)

| # | Condition | Doctor decision | Reason |
|---|---|---|---|
| 1 | `attendanceType = ON_CALL` (any date, any board status) | `CALLBACK_REQUIRED` | `ON_CALL_DOCTOR` |
| 2 | **TODAY:** scope the board rows (named session, else all; unlabelled rows always in scope), classify each row (3d), combine (3f) | | |
| 3 | **FUTURE:** usual sessions for that weekday (3e), combine (3f) | | |

### 3d. Today: per board row (`basis = LIVE_BOARD`; no profile involved in the decision)

| Row (Manoj `status`) | Session decision | Reason |
|---|---|---|
| `IN`, `expectedEndTime` absent or not yet passed | `APPOINTMENT_REQUEST` | none |
| `LATE`, `expectedEndTime` absent or not yet passed | `APPOINTMENT_REQUEST` (delay and expected time) | none |
| `IN`/`LATE`, `expectedEndTime` **present and passed** | `NOT_AVAILABLE` | `SESSION_ENDED` |
| `CANCELLED` | `NOT_AVAILABLE` | `CANCELLED` |
| `NOT_CONFIRMED` | `CALLBACK_REQUIRED` | `BOARD_NOT_CONFIRMED` |
| `UNKNOWN`, `isStale=true` | `CALLBACK_REQUIRED` | `BOARD_STALE` |
| `UNKNOWN`, `isStale=false` | `CALLBACK_REQUIRED` | `BOARD_UNKNOWN` |
| No row for the doctor | `CALLBACK_REQUIRED` | `BOARD_ENTRY_MISSING` |
| Named session: no labelled row and no unlabelled row | `CALLBACK_REQUIRED` | `SESSION_NOT_ON_BOARD` |

**Missing `expectedEndTime` (decided, revision 5):**
- **Availability:** the session is **never** treated as ended. It is reported with its live status and `expectedEndTime: null`, and the tool description says the end time was not given.
- **Booking, no specific time** (the caller picks the session only): validated by the session decision alone → `NOTED` if the decision is `APPOINTMENT_REQUEST`.
- **Booking, with a specific `preferredTime`:** the time cannot be validated without an end time, whatever `expectedTime` says. Result: `HANDOFF_REQUIRED` / `TIME_NOT_VERIFIABLE`, nextStep `TRANSFER_DESK`. No write and no callback.
- **Future dates:** usual sessions always have `start` and `end` (required in the contract), so future times are always validatable.

### 3e. Future: usual schedule (`basis = USUAL_SCHEDULE`; board never called)

| Usual schedule (after the session filter) | Doctor decision | Reason |
|---|---|---|
| ≥1 session that weekday | `APPOINTMENT_REQUEST`: normal working hours (`REGULAR`) or attendance days (`VISITING`), **not confirmed**; several sessions are all listed, and no choice is required (3f) | none |
| Has sessions, none that weekday | `NOT_AVAILABLE` | `NOT_USUAL_DAY` |
| Named session not usual that weekday | `NOT_AVAILABLE` | `SESSION_NOT_USUAL` |
| Empty schedule | `CALLBACK_REQUIRED` | `NO_USUAL_SCHEDULE` |
| Profile read failed or timed out | `COULD_NOT_CHECK` | `PROFILE_UNAVAILABLE` |

### 3f. Combining sessions (today and future alike)

| In-scope sessions (by **decision**) | Doctor decision | `sessionChoiceRequired` |
|---|---|---|
| One session, or several sessions **all with the same decision** (for example Morning `IN` + Evening `IN`, or two usual future sessions) | that decision | **no**: every session is listed with its times, and the request covers the day (Manoj's appointment has no session field, only an optional expected time) |
| Different decisions, ≥1 bookable, none named (D4) | `APPOINTMENT_REQUEST` | **yes** (callback only if an unconfirmed or unknown session is chosen) |
| Different decisions, none bookable, ≥1 callback | `CALLBACK_REQUIRED` | no |
| All `NOT_AVAILABLE` | `NOT_AVAILABLE` | no |

`SESSION_REQUIRED` (booking) uses the same test: it applies only when the sessions in scope have different decisions and no session or time selects one.

### 3g. `WORKING_HOURS` purpose (deterministic; never reads the board)

| Target | Result |
|---|---|
| One doctor, schedule present | `outcome = WORKING_HOURS`, `basis = USUAL_SCHEDULE`, `usualSessions` (each with `onRequestedDate` if a date was given), described as normal working hours or attendance days, not today's availability |
| One doctor, `ON_CALL` | `WORKING_HOURS` with `reason = NO_REGULAR_HOURS`, empty `usualSessions` |
| One doctor, empty schedule | `WORKING_HOURS` with `reason = NO_USUAL_SCHEDULE` |
| Several name matches | `CLARIFICATION_NEEDED` / `ASK_WHICH_DOCTOR` (choices capped, 3h) |
| Department | The candidate doctors' usual hours through the same bounded reader as future departments (3h); `ON_CALL` listed with `NO_REGULAR_HOURS` |
| Profile failure | `COULD_NOT_CHECK` (a single doctor) or per-doctor `COULD_NOT_CHECK` (a department) |

### 3h. Lists, ranking and bounded reads (departments, name matches)

**Candidate list (deterministic, not owner order):**
- one `GET /doctors?department=…&gender=…&limit=100` (the contract maximum);
- sorted locally by `(name.casefold(), id)`;
- if `total > 100`: `complete = false`.

The name search uses the same sort.

**Today, department:** that list ∥ one department board read. On-call status comes from `DoctorSummary`. **No profile reads.**

**Future or `WORKING_HOURS`, department: bounded batched search (revision 5):**
1. **Decided without a profile:** `ON_CALL` candidates are callback, `NO_REGULAR_HOURS` for working hours. They are never read.
2. **The remaining candidates are read in sorted order, in batches of `PROFILE_BATCH_SIZE` (default 3).**
   - Within a batch, reads run concurrently. That is the only concurrency, so in-flight requests are never more than the batch size (validated ≤ `OPS_POOL_MAX_CONNECTIONS`).
   - Batches run one after another.
   - Cached profiles resolve without I/O.
3. **Stop conditions, checked after each batch:**
   - (a) **enough matches:** `APPOINTMENT_REQUEST` doctors ≥ `DOCTOR_CHOICE_LIMIT` (for `WORKING_HOURS`, doctors with hours ≥ the limit);
   - (b) **all candidates checked;**
   - (c) **deadline:** the whole search runs inside the invocation's read deadline (`asyncio.timeout`). A new batch is not started with less than `MIN_BATCH_HEADROOM_SECONDS` (default 0.05 s) left. When the deadline fires, the in-flight batch is cancelled and its doctors count as unchecked.
4. **Completeness:**
   - `complete = true` only if every candidate was read successfully (or decided without a read) and the list was ≤ 100.
   - A failed read counts as unchecked, never as "not available".
5. **Result rule:** a pure function of (sorted candidates, per-candidate read result, which candidates were reached). It never depends on completion order inside a batch: the whole batch is collected, then ranked by name order.
6. **Outcomes (`AVAILABILITY` purpose)**, in precedence order:

   | Search state | `outcome` | `nextStep` | Notes |
   |---|---|---|---|
   | ≥1 match (complete or not) | `AVAILABILITY` | `ASK_WHICH_DOCTOR` | `doctors[]` = **only bookable doctors** (the first `DOCTOR_CHOICE_LIMIT` in name order); counts as defined below |
   | No match, search incomplete (deadline or failed reads) | `HANDOFF_REQUIRED` | `TRANSFER_DESK` | `reason = SEARCH_INCOMPLETE`; never claims `NOT_AVAILABLE` |
   | No match, complete, ≥1 callback doctor (on-call or no usual schedule) | `CALLBACK_REQUIRED` | `ASK_CALLBACK_DETAILS` | D6/D9 |
   | No match, complete, all `NOT_AVAILABLE` | `NOT_AVAILABLE` | `OFFER_OTHER_SESSION_OR_DATE` | each doctor's usual days included |

   For `WORKING_HOURS`, the same precedence: some hours → `WORKING_HOURS` (incomplete flagged); none and incomplete → `HANDOFF_REQUIRED`/`SEARCH_INCOMPLETE`; none and complete → `WORKING_HOURS` with reasons (`NO_REGULAR_HOURS`/`NO_USUAL_SCHEDULE`).
7. **Cache effect:** completed reads are cached, so a repeated question reaches further.

**Which doctors are listed (department results, revision 6):**
- **≥1 bookable doctor:** `doctors[]` contains **only bookable doctors** (decision `APPOINTMENT_REQUEST`), in name order, at most `DOCTOR_CHOICE_LIMIT` (**default 3**). On-call, callback, not-available and unchecked doctors are not listed; they are only counted. A caller who names an on-call doctor gets that doctor's callback through a doctor-specific query.
- **No bookable doctor** (outcome `CALLBACK_REQUIRED` or `NOT_AVAILABLE`): `doctors[]` lists the callback and not-available doctors as facts, ranked `CALLBACK_REQUIRED` → `NOT_AVAILABLE`, then by name, at most `DOCTOR_CHOICE_LIMIT`, so the agent can explain (for example their usual days).
- **`HANDOFF_REQUIRED`:** `doctors[]` is empty.
- **Name-search choices** (`CLARIFICATION_NEEDED`) use the same name order and cap.

**Counts (explicit meanings, stated in the tool description):**

| Field | Meaning | Not |
|---|---|---|
| `totalMatches` (existing, meaning unchanged) | How many doctors the directory lists for this department or name search: every attendance type and every decision | **Not** the number of bookable doctors |
| `bookableFound` (new) | How many bookable doctors were found among the doctors checked. Can be larger than `doctors[]` (capped list). When `complete=false` there may be more | Not a promise that no others exist |
| `complete` (existing) | `true` only when every listed doctor was evaluated (≤100 listed, no unchecked or failed reads) | |

Voice use: "I found `bookableFound` doctors who can see you, for example …". Offer more only when `bookableFound > len(doctors)` or `complete=false`, never because `totalMatches` is larger.

### 3i. `get_doctor_availability` outcomes (`AVAILABILITY` purpose)

| Situation | `outcome` | `nextStep` |
|---|---|---|
| One doctor `APPOINTMENT_REQUEST` | `AVAILABILITY` | `ASK_WHICH_SESSION` if a session choice is required, else `OFFER_APPOINTMENT_REQUEST` |
| One doctor `CALLBACK_REQUIRED` (including on-call) | `CALLBACK_REQUIRED` | `ASK_CALLBACK_DETAILS` |
| One doctor `NOT_AVAILABLE` | `NOT_AVAILABLE` | `OFFER_OTHER_SESSION_OR_DATE` |
| One doctor `COULD_NOT_CHECK` | `COULD_NOT_CHECK` | `SAY_COULD_NOT_CHECK` |
| Department, ≥1 doctor bookable (regular/visiting; on-call never bookable) | `AVAILABILITY` | **`ASK_WHICH_DOCTOR`** (never booked at department level); only bookable doctors are listed (3h) |
| Department, none bookable, ≥1 callback (including on-call) | `CALLBACK_REQUIRED` | `ASK_CALLBACK_DETAILS` |
| Department, all `NOT_AVAILABLE` | `NOT_AVAILABLE` | `OFFER_OTHER_SESSION_OR_DATE` |
| Department future, no match and search incomplete (3h) | `HANDOFF_REQUIRED` / `SEARCH_INCOMPLETE` | `TRANSFER_DESK` |
| Department today, board read failed | `COULD_NOT_CHECK` | `SAY_COULD_NOT_CHECK` |

Unchanged from today:
- name ambiguity → `CLARIFICATION_NEEDED`/`ASK_WHICH_DOCTOR`; no name match → `NOT_FOUND`;
- department ambiguity or no match → `CLARIFICATION_NEEDED`/`ASK_WHICH_DEPARTMENT`;
- `NO_CONSULTANT`/`NO_DOCTORS` → `NOT_FOUND`/`TRANSFER_DESK`;
- whole-call read failure → `COULD_NOT_CHECK`.

### 3j. `manage_booking` (CREATE and RESCHEDULE's new date use the same policy)

**`departmentId` is removed from the input. `doctorId` is required for CREATE.** RESCHEDULE uses the existing appointment's `doctorId`. An upstream appointment with no `doctorId` is malformed owner data, handled by the existing `Malformed` path (`COULD_NOT_RECORD`). No other handling.

| Decision | Result | `nextStep` |
|---|---|---|
| Lands in an `APPOINTMENT_REQUEST` session (and time) | write → `NOTED` | `SAY_REQUEST_NOTED` |
| Mixed sessions, none selected | `INVALID_REQUEST` `fields=["session"]` / `SESSION_REQUIRED` + `sessions[]`; no write | `ASK_WHICH_SESSION` |
| `CALLBACK_REQUIRED` session, or on-call doctor | `CALLBACK_REQUIRED` + `callback.reason`; no write | `ASK_CALLBACK_DETAILS` |
| `NOT_AVAILABLE` session, or not a usual day | `NOT_AVAILABLE` + reason + bookable `sessions[]` for that date; no write | `OFFER_OTHER_SESSION_OR_TIME` if alternatives exist, else `OFFER_OTHER_SESSION_OR_DATE` |
| Time outside a session window (today: `expectedTime`–`expectedEndTime` both present; future: usual `start`–`end`) | `NOT_AVAILABLE` / `TIME_OUTSIDE_SESSION` + alternatives; no write | as above |
| A specific `preferredTime` in a today session with **no `expectedEndTime`** | `HANDOFF_REQUIRED` / `TIME_NOT_VERIFIABLE`; no write, no callback | `TRANSFER_DESK` |
| Profile or board read failure | `COULD_NOT_RECORD` (as now) | `SAY_COULD_NOT_RECORD` |

**Booking reads:**
- **TODAY:** the doctor's profile (attendance type, cached) **and** the doctor's board, awaited together. Both are required inputs; there is no race.
- **FUTURE:** the profile only.

LIST and CANCEL are unchanged.

### 3k. Callback storage (unchanged schema)

| Detail | Field |
|---|---|
| Callback marker | `outcome = CALLBACK_NOTED` |
| Intent | `intent = BOOKING`/`AVAILABILITY` |
| Phone | `callerMobile` (**required, validated**) |
| Doctor | `doctorId` |
| Name, doctor/department, date/session, callback reason | `summaryText` |

**Known limitation (DECISIONS, VOICE-TEAM):** those `summaryText` details are not enforced. Summary quality is tested when LiveKit is integrated; structured fields come later only if needed.

The availability and booking `callback` object becomes `{reason, summaryOutcome: "CALLBACK_NOTED"}`. The spoken `ask`/`say` are removed.

---

## 4. Architecture: one policy, one reader, thin services

```
tools.py ─► availability.py / booking.py      orchestration + presentation only
              ├─► schedule_reader.py          every owner read, cache, bounded fan-out, typed failures (I/O)
              └─► availability_policy.py      every decision (pure, no I/O)
```

### 4a. `availability_policy.py` (new; replaces and deletes `board_scope.py`)

```python
class Purpose(StrEnum): AVAILABILITY, WORKING_HOURS
class DateKind(StrEnum): TODAY, FUTURE
class Basis(StrEnum): LIVE_BOARD, USUAL_SCHEDULE
class Decision(StrEnum): APPOINTMENT_REQUEST, CALLBACK_REQUIRED, NOT_AVAILABLE, COULD_NOT_CHECK   # ours; never Manoj's status
class Reason(StrEnum): ON_CALL_DOCTOR, BOARD_UNKNOWN, BOARD_STALE, BOARD_ENTRY_MISSING, SESSION_NOT_ON_BOARD,
                       BOARD_NOT_CONFIRMED, CANCELLED, SESSION_ENDED, NOT_USUAL_DAY, SESSION_NOT_USUAL,
                       NO_USUAL_SCHEDULE, NO_REGULAR_HOURS, PROFILE_UNAVAILABLE, TIME_OUTSIDE_SESSION,
                       SESSION_REQUIRED, TIME_NOT_VERIFIABLE, SEARCH_INCOMPLETE
class DateError(StrEnum): DATE_FORMAT, PAST_DATE, DATE_REQUIRED

RequestedDate(value, kind, weekday)
SessionDecision(label, basis, owner_status, decision, reason, start, end, delay_minutes, note)  # owner_status = Manoj's IN/LATE/... (today) or None (usual)
DoctorDecision(doctor, decision, reason, basis, sessions, session_choice_required)
BookingDecision = Write | SessionRequired(sessions) | Callback(reason) | NotAvailable(reason, alternatives)
                | Handoff(reason)                                   # TIME_NOT_VERIFIABLE
SearchState(bookable_found, checked, complete)                    # 3h result of the batched search

resolve_date(text | None, facility_now, purpose) -> RequestedDate | DateError | None
TODAY_STATUS: Mapping[AvailabilityStatus, tuple[Decision, Reason | None]]       # the single status table
decide_doctor(facts, requested, *, session, now) -> DoctorDecision            # 3c–3f
working_hours(facts, requested | None) -> WorkingHours                        # 3g
decide_booking(decision, *, session, preferred_time) -> BookingDecision       # 3j
rank(decisions, limit) -> RankedList                                          # 3h voice order + cap
aggregate(decisions, search: SearchState) -> ResultOutcome                    # result roll-up incl. SEARCH_INCOMPLETE
```

- `decide_doctor` is three small, flat functions (`_on_call`, `_today`, `_future`). The status meaning lives only in `TODAY_STATUS`.
- The end-time rules in 3d are one function (`_window`) used by both session classification and the time check. It returns `ENDED | OPEN | UNKNOWN_END`; `decide_booking` maps a specific time plus `UNKNOWN_END` to `Handoff(TIME_NOT_VERIFIABLE)`.

### 4b. `schedule_reader.py` (new): the only retrieval component, shared by both services

- **Owns:** the cached departments and profiles (moved from both services), directory search with local sorting, today's board, and the **bounded fan-out**:
  - sorted candidates read in sequential batches of `PROFILE_BATCH_SIZE`, concurrent within a batch;
  - a stop predicate supplied by the policy (enough matches);
  - the overall deadline via `asyncio.timeout`, with the `MIN_BATCH_HEADROOM_SECONDS` rule and cancellation;
  - per-candidate result `Profile | ReadFailure | Unchecked`.

  The reader never decides availability. It asks the policy's predicate whether to continue.
- **Returns** typed `DoctorFacts` / `DepartmentFacts`. Whole-call failures raise the existing service errors; per-doctor failures are values.
- **Reads per request:**

  | Request | Reads |
  |---|---|
  | Doctor id, TODAY | profile ∥ board (both awaited) |
  | Doctor name, TODAY | search, then board (attendance from the summary) |
  | Doctor, FUTURE / `WORKING_HOURS` | profile |
  | Department, TODAY | list ∥ board |
  | Department, FUTURE / `WORKING_HOURS` | list, then batched profiles until stop |

### 4c. Thin services

- **`availability.py`:** validate the purpose and date, resolve the target (typed `DoctorTarget | DepartmentTarget | Choices | NotFound`), the reader, the policy, then present.
- **`booking.py`:** keeps validation, the write gate and idempotency. CREATE and RESCHEDULE use the reader, `decide_doctor` and `decide_booking`.
- **Deleted:**
  - `_requested_date`, `_board`, `_overlay`, `_finish`, `_expired`;
  - the dict prefetch;
  - `_match_department`'s duplicate cache use;
  - `_board_gate`;
  - `BookingService._profile`;
  - the department CREATE and department reschedule branches;
  - the date part of `_iso`;
  - `board_scope.py`.

### 4d. Output schemas (`outcomes.py`)

**`get_doctor_availability` result:**
- **Kept:** every current field.
- **Added:** `basis`, `bookableFound`; outcomes `NOT_AVAILABLE`, `WORKING_HOURS`, `HANDOFF_REQUIRED` (with the existing `TRANSFER_DESK`); nextSteps `ASK_WHICH_SESSION`, `OFFER_OTHER_SESSION_OR_DATE`. The `totalMatches` and `complete` descriptions state the meanings in 3h.
- **`doctors[]`:**
  - **kept:** `doctorId`, `name`, `departments`, `attendanceType`, `gender`, `dataConfirmed`, `board`, `usualSessions`;
  - **added:** `decision`, `reason`, `sessionChoiceRequired`;
  - **per session:** `BoardSessionOut` keeps `status` (**Manoj's** `IN`/`LATE`/`CANCELLED`/`NOT_CONFIRMED`/`UNKNOWN`, unchanged) and adds `decision`, `reason`; `UsualSessionOut` adds `decision`, `reason`.
- **Filled per purpose:**

  | Field | Filled for |
  |---|---|
  | `board` | TODAY only |
  | `usualSessions` | FUTURE and `WORKING_HOURS` only (today's availability never returns usual hours) |

- **Renamed:** doctor `journey` → `decision` (four values), `CALLBACK_ONLY` → `CALLBACK_REQUIRED`. `decision` is our result, `status` is always Manoj's; the two words are never reused for each other.
- **Removed:** `DESK`, `unknownSessions`, `Callback.ask`/`say`, the `expired` flag (replaced by `decision=NOT_AVAILABLE`/`reason=SESSION_ENDED`).
- **Added to `Callback`:** `reason`.

**`get_doctor_availability` input:** `purpose` added; `date` optional in the schema (rules 3a).

**`manage_booking`:**
- **input:** `departmentId` removed;
- **output:** outcomes `NOT_AVAILABLE`, `HANDOFF_REQUIRED` (with the existing `TRANSFER_DESK`); nextSteps `ASK_WHICH_SESSION`, `OFFER_OTHER_SESSION_OR_TIME`, `OFFER_OTHER_SESSION_OR_DATE`; `sessions[]` (alternatives); `callback.reason`.

**`record_call_summary`:** schema unchanged; only the `summaryText` description gains "session" and "callback reason".

### 4e. Configuration (`config.py`, `.env.example`, rollout docs)

| Setting | Default | Purpose |
|---|---|---|
| `DOCTOR_CHOICE_LIMIT` | 3 | Doctors returned per list |
| `PROFILE_BATCH_SIZE` | 3 | Profiles read concurrently per batch (the only concurrency); validated ≤ `OPS_POOL_MAX_CONNECTIONS` |
| `MIN_BATCH_HEADROOM_SECONDS` | 0.05 | Do not start a batch with less time left in the read deadline |

Existing settings are reused: the read deadline (0.30 s), `DIRECTORY_CACHE_SECONDS` (300). The defaults are confirmed or tuned by the bench before release (section 6).

### 4f. Text and server facts

- **`packs/healthcare.json`, availability:**
  - the purposes;
  - today = live board, with per-status meanings and the end-time rule;
  - on-call → callback;
  - future = normal working hours/attendance, not confirmed;
  - departments lead to choosing a doctor;
  - the meanings of `totalMatches`, `bookableFound` and `complete` (3h), and of `status` (Manoj's) vs `decision` (ours).
- **`packs/healthcare.json`, booking:** `doctorId` required; `NOT_AVAILABLE`, `SESSION_REQUIRED` and `TIME_OUTSIDE_SESSION`.
- **`summaryText`:** + session and callback reason.
- **`prompt.py`:** update the `CALLBACK_REQUIRED` sentence; add "future dates use usual working hours, not confirmed availability"; bump `SCHEMA_VERSION`.

### 4g. Removed outright

- `board_scope.py`
- future-date board calls
- department CREATE and department reschedule paths
- the profile-based missing-row rule
- `DESK`
- `unknownSessions`
- `expired`
- spoken callback scripts
- the duplicate caches and date parsers
- the "today or later" rule text

There are no flags, dual paths or legacy-compatibility code or tests.

---

## 5. Affected files and integrations

| Area | Files |
|---|---|
| New | `availability_policy.py`, `schedule_reader.py`, `tests/test_availability_policy.py`, `tests/test_schedule_reader.py` |
| Deleted | `board_scope.py` |
| Changed (src) | `availability.py`, `booking.py`, `outcomes.py`, `tools.py` (shared reader; availability parameters `purpose`, optional `date`; booking without `departmentId`), `config.py`, `packs/healthcare.json`, `prompt.py` |
| Generated | `tests/contracts/mcp-tools.snapshot.json`, `docs/handover/VOICE-TEAM.md` |
| Fixtures and tooling | `dev/frontdesk_stubs/ops.py` and `data/demo_hospital.json` (usual schedules incl. VISITING; an ON_CALL doctor in a mixed department; an empty-schedule doctor; a department with more doctors than several batches (matches early, late, none, and slow profiles); boards for all five statuses, stale, missing, multi-session, and rows without `expectedEndTime`; a request log; per-profile delay control), `dev/demo.py`, `dev/bench.py` (department future cold/warm, doctor today), `.env.example` |
| Deploy and gateway | `deploy/azure/smoke.py` (`AVAILABILITY_OK` + `NOT_AVAILABLE`, `WORKING_HOURS`; a read-only `WORKING_HOURS` probe; **four** tools), `deploy/azure/deploy.sh` (no change: the new settings have defaults), `deploy/contextforge/register.py` (no code change; still four tools). **ContextForge:** after deployment, rerun `register.py`. Its drift check compares tool names and **input** schemas only (`register.py:83-101`), so the changed `get_doctor_availability` and `manage_booking` inputs trigger the refresh. It **cannot verify output schemas**. Output-schema propagation is a **manual acceptance step**: list the tools through the voice virtual server and compare each `outputSchema` with `make schema`. No change to `register.py` (whether ContextForge stores output schemas is unconfirmed). Then refresh the virtual server's and the voice agent's tool caches; the passthrough headers are unchanged |
| Tests | `test_availability.py`, `test_booking.py` (department CREATE tests deleted, not adapted), `test_server.py` (schema, interface completeness), `test_e2e_processes.py`, `test_external.py` (future create on a usual working day; the unknown-date gate becomes today `UNKNOWN`/`NOT_CONFIRMED`), `test_deploy.py`, `test_stubs.py`, `test_bench.py`, `test_settings.py` (new settings validation) |
| Docs | `CLAUDE.md` (replace the today-or-later and shared-scope rules; add the on-call, department, working-hours and end-time rules; four tools unchanged), `README.md`, `services/mcp/README.md`, `docs/DECISIONS.md` (new entry: all rules, the D14 limitation, contract differences (a) and (b)), `docs/architecture/TARGET.md`, `docs/handover/{VOICE-TEAM,CONTEXTFORGE,TESTING,OWNER-INTEGRATION-MESSAGES}.md`, `mcp-only/PLAN.md` |
| Report, don't edit | `.claude/agents/voice-safety-reviewer.md` (old "today or later" rule) |

---

## 6. Tests and verification

Tests come first (red, then green). The policy gets table-driven unit tests; the reader gets fan-out tests with stub delays and a controlled clock; services get HTTP-boundary tests. Mocks only at HTTP and clock.

| Group | Cases |
|---|---|
| Today's five statuses | `IN`/`LATE` bookable (`LATE` with delay and expected time); `CANCELLED` → `NOT_AVAILABLE`; `NOT_CONFIRMED`/`UNKNOWN` → callback; no writes for the last three |
| Stale/missing | `BOARD_STALE`, `BOARD_ENTRY_MISSING`, `SESSION_NOT_ON_BOARD` |
| End time | `expectedEndTime` passed → `SESSION_ENDED`; **absent** → never ended at any clock time, status still reported; booking with **no** specific time in that session → `NOTED`; booking **with** `preferredTime` in that session (before, inside or after `expectedTime`) → `HANDOFF_REQUIRED`/`TIME_NOT_VERIFIABLE`/`TRANSFER_DESK`, zero writes, no callback object |
| Multiple sessions | Morning `IN` + Evening `UNKNOWN`: no session → `ASK_WHICH_SESSION`; Evening → callback; Morning → bookable; booking with no session → `SESSION_REQUIRED`, no write. Morning `IN` + Evening `IN` → `OFFER_APPOINTMENT_REQUEST`, `sessionChoiceRequired=false`, booking with no session → `NOTED`. Morning `CANCELLED` + Evening `IN`; unlabelled `UNKNOWN` in scope. Every board session keeps Manoj's `status` unchanged alongside our `decision` |
| On-call (U4) | Today `IN` → `CALLBACK_REQUIRED`/`ON_CALL_DOCTOR`, no write; future → callback; `WORKING_HOURS` → `NO_REGULAR_HOURS`; mixed department (regular `IN` + on-call) → `AVAILABILITY`/`ASK_WHICH_DOCTOR` listing **only** the regular doctor, with `bookableFound=1` and `totalMatches` counting both; only on-call → `CALLBACK_REQUIRED`; no profile read for on-call candidates |
| Visiting (U7) | Future on an attendance day → bookable, "attendance not confirmed" wording asserted in the pack text; other day → `NOT_USUAL_DAY` |
| Future, no board call | Usual day → `AVAILABILITY`, `basis=USUAL_SCHEDULE`, `board=[]`, zero `/availability` requests; several usual sessions that day → all listed, `OFFER_APPOINTMENT_REQUEST`, `sessionChoiceRequired=false`; a named session filters to it; `NOT_USUAL_DAY`; `SESSION_NOT_USUAL`; empty → callback; profile failure → `COULD_NOT_CHECK` |
| Working hours (U1) | By id and by name; date given → `onRequestedDate`; zero board calls; on a date whose board is `UNKNOWN`, the `WORKING_HOURS` result is identical to the result with no board at all; `AVAILABILITY` without a date → `DATE_REQUIRED` |
| Batched department search (U5, revision 5) | **Matches in the first batch** → stop, no further profile requests (stub counter), `AVAILABILITY`/`ASK_WHICH_DOCTOR`; **matches only in a later batch** → keeps going and returns them; **every doctor checked, none match** → `NOT_AVAILABLE`, `complete=true`; **deadline before all checked, no match** → `HANDOFF_REQUIRED`/`SEARCH_INCOMPLETE`/`TRANSFER_DESK`, never `NOT_AVAILABLE`; **deadline after some matches** → those doctors, `complete=false`; a failed read with no match → `HANDOFF_REQUIRED`; only on-call doctors → `CALLBACK_REQUIRED` with zero profile reads; in-flight requests never exceed `PROFILE_BATCH_SIZE`; no batch starts with less than `MIN_BATCH_HEADROOM_SECONDS` left; total time ≤ read deadline + scheduling tolerance (controlled clock and stub delays); owner order shuffled → identical output over 20 runs; a warm cache → the full search completes; `WORKING_HOURS` department follows the same precedence |
| Lists and counts (U3, revision 6) | With bookable doctors: only bookable listed, cap 3, name order. Without: callback then not-available listed, cap 3. Handoff: empty list. `totalMatches` = directory count (all types and decisions); `bookableFound` ≥ `len(doctors)`; 5 bookable found → 3 listed, `bookableFound=5`; stopped at the limit → `complete=false`; `total > 100` → `complete=false`; name-search choices use the same cap and order. The pack text states the three meanings (asserted) |
| Latency | `make bench`: doctor today; department today; department future cold and warm (p50/p95), reported against the 0.30 s share; a slow-but-healthy profile within the deadline is used, one beyond it gives `COULD_NOT_CHECK` |
| Booking, accidental changes | Zero `POST /appointments` for `NOT_CONFIRMED`, `UNKNOWN`, `CANCELLED`, ended, on-call, `SESSION_REQUIRED`, `NOT_USUAL_DAY`, `TIME_OUTSIDE_SESSION`, `TIME_NOT_VERIFIABLE` and no schedule; `NOTED` for `IN`/`LATE` (a specific time only when the window is known) and usual future days; `departmentId` refused by the schema; the existing LIST/CANCEL, idempotency, `callerConfirmed`, verification and UNCERTAIN suites stay green unchanged |
| Timezone boundaries | Clock at 23:59 and 00:00 `Asia/Kolkata` with UTC on the other date; the board is called only for facility TODAY; client timezone irrelevant; the end-time comparison uses facility time |
| Invalid dates | `PAST_DATE`; `DATE_FORMAT` (`2026-02-30`, `05/10/2026`, `tomorrow`, `2026-1-5`, empty); `DATE_REQUIRED`; the same through `visitDate`/`newVisitDate` |
| Callback flow | `callback = {reason, summaryOutcome}`, no `ask`/`say`; HTTP `record_call_summary` `CALLBACK_NOTED` without `callerMobile` → `INVALID_REQUEST`; with it → `SAVED`, and the stub receives `callerMobile`, `doctorId` and the unchanged `summaryText` |
| Schema/interface | Snapshot (four tools); VOICE-TEAM matches; every outcome, nextStep, decision, reason and purpose value is described; `BoardSessionOut.status` enum and meaning unchanged from the current snapshot; kept fields keep their meaning |
| Removal proof | Zero `board_scope`, `unknownSessions`, `CALLBACK_ONLY`, `DESK`, `expired`, `ask=`/`say=`, `_board_gate`, `SESSION_ROW_MISSING`, booking `departmentId` or "today or later" outside historical reports |

**Verification:**
- `make test-fast` per commit (≤10 files);
- `./scripts/test.sh`;
- `make schema` equals the snapshot;
- `uvx vulture`;
- `make bench`;
- the latency and voice-safety reviewers with this policy supplied;
- after a separately approved deployment: `register.py` (input-schema drift → refresh), the manual output-schema comparison through the virtual server, then Garima's probes for General Medicine/Gynaecology today and future, and Dr. Shreyas's working hours.

**Commits** (each green on its own):
1. Policy + reader (with fan-out) + availability.
2. Booking (department paths removed; `board_scope` deleted).
3. Stub, demo, e2e and external tests.
4. Smoke and bench.
5. Docs and config docs.
6. Evidence.

---

## 7. Decision record (complete)

| # | Decision | Status |
|---|---|---|
| D1 | Today `IN`/`LATE` → `NOTED` request; `LATE` reports delay and expected time | Decided |
| D2 | Today `CANCELLED` → session `NOT_AVAILABLE`; other sessions separate | Decided |
| D3 | Ended only when `expectedEndTime` is present and passed (facility time); absent → never ended, status reported; a specific time in such a session → front-desk handoff (`HANDOFF_REQUIRED`/`TIME_NOT_VERIFIABLE`), no request, no callback | Decided (revision 5) |
| D4 | Mixed sessions → ask which session; callback only if an unconfirmed/unknown one is chosen | Decided |
| D5 | Future usual day → `NOTED`, not confirmed | Decided |
| D6 | Future, no usual schedule → callback | Decided |
| D7 | No department-level requests; departments lead to choosing a doctor; `doctorId` required | Decided |
| D8 | Future board entries never read | Decided |
| D9/U4 | ON_CALL → always callback, even with today `IN`; owner-contract difference recorded | Decided |
| D10/U1 | Today = board only; working hours via the `purpose=WORKING_HOURS` path of the same tool; four tools kept | Decided |
| D11 | Structured callback facts; no spoken scripts; name/phone collection is a voice-team acceptance item | Decided |
| D12 | `NOT_AVAILABLE` for valid but unavailable requests | Decided |
| D13 | Relative dates out of scope | Decided |
| D14 | Current summary schema; phone in `callerMobile`, the rest in `summaryText`; known limitation | Decided |
| D15 | Swagger "given date" vs today only recorded; Manoj asked to document | Decided |
| D16 | Normalised exact session matching | Decided |
| D17 | Time outside a known session window → `NOT_AVAILABLE`/`TIME_OUTSIDE_SESSION`, with alternatives | Decided |
| U2 | No department-only appointments exist (greenfield); a missing upstream `doctorId` is just malformed data | Decided |
| U3 | `DOCTOR_CHOICE_LIMIT` = 3, configurable; `totalMatches` returned | Decided |
| U5 | Batched search: sorted candidates, batches of 3, continue until enough matches, all checked, or deadline; no match and incomplete → handoff; matches and incomplete → return them flagged | Decided (revision 5; defaults tuned by the bench) |
| R6-1 | Manoj's session `status` kept unchanged; our result is `decision` (+ `reason`) on sessions and doctors | Decided (revision 6) |
| R6-2 | Session choice only when in-scope sessions have different decisions | Decided (revision 6) |
| R6-3 | Department lists: only bookable doctors when any exist; otherwise callback/not-available facts; `totalMatches` = directory count, `bookableFound` = bookable found, `complete` = all evaluated | Decided (revision 6) |
| R6-4 | Gateway check covers input schemas only; output schemas verified manually at acceptance | Decided (revision 6) |
| U6 | No session selected among mixed → `INVALID_REQUEST`/`SESSION_REQUIRED` | Decided |
| U7 | VISITING treated like REGULAR for future; "attendance not confirmed" | Decided |

**No open behavioural decisions remain.**

Implementation-time confirmations (not decisions):
- `PROFILE_BATCH_SIZE` (3) and `MIN_BATCH_HEADROOM_SECONDS` (0.05) are confirmed or tuned by the bench and reported in the hand-back;
- one live check that Manoj's doctors have `usualSchedule` populated. If not, every future answer is a callback, by design.

## 8. Risks and dependencies

- **Empty live usual schedules (Medplum).** Every future answer and working-hours answer would then be callback or `NO_USUAL_SCHEDULE`. Check one doctor before release.
- **Cold-cache department future.** Within 0.30 s only a few batches fit. The first call may return fewer matches (`complete=false`), or a handoff when no match was reached yet. Repeated calls reach further thanks to the cache. Measured by the bench.
- **Breaking schema changes** (`purpose`, optional `date`, removed fields, `departmentId` removed). Acceptable now because LiveKit isn't integrated; needs ContextForge rediscovery and coordination with the call-summary cutover.
- **Stale reviewer agent:** needs Garima's approval to update.
- **Owner items** (non-blocking for local work): `calls.write`, the test tenant, Manoj documenting contract differences (a) and (b).
