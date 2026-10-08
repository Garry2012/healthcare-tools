# Slot-aware availability and booking: implementation plan (revision 11.3, 9 October 2026)

**Status:** being built. Phases 1a to 3b are implemented and reviewed (`OPUS-SLOTS-*-REVIEW.md`). Astra implements; Opus reviews.

**History:**
- Revision 1: initial plan.
- Revision 2: self-audit against the code.
- Revision 3: external review by Luna (keep all blocks; respect session `bookable false`).
- Revision 4: Astra's pre-flight (`SLOTS-PLAN-PREFLIGHT.md`, commit `32e8ea9`), Sol's review, and Garima's decisions D-1 to D-5.
- Revision 5: Astra's delta pre-flight (`SLOTS-PLAN-PREFLIGHT-R4.md`, commit `bcc6cf1`) and Garima's decision D-6. The separate 11-step booking matrix of revision 4 is **deleted**: slot evidence now flows through the existing `decide_booking` and `_today` structure, which already keeps unresolved rows (R4-B2). `_future` is restructured to match `_today` (R4-B3).
- Revision 6: Astra's second delta pre-flight (`SLOTS-PLAN-PREFLIGHT-R5.md`). A supplied session name must match the label of the block's session (R5-B1a); the scope of D-6 at booking time is stated (R5-B1b); a one-day session without owner hours has a defined output shape (R5-B2); the owner's `SLOT_FULL` wording, the legacy future output and the blank-session type's home are fixed (R5-S1 to S3).
- Revision 7: Astra's third delta pre-flight (`SLOTS-PLAN-PREFLIGHT-R6.md`). Booking keeps an unresolved row with unknown hours in scope even when another session matches the time (R6-B1); the one-day output metadata is spelled out.
- Revision 8: Astra's final delta pre-flight (`SLOTS-PLAN-PREFLIGHT-R7.md`). The R7 condition becomes one predicate, `_cannot_rule_out`, applied in all three existing scope filters, so a future named session also keeps an unlabelled UNKNOWN (R7-B1). The one existing test that changes intentionally is named (R7-S1).
- Revision 9: Astra's confirmation (`SLOTS-PLAN-PREFLIGHT-R8.md`, verdict ready to build) showed that revision 8's strict rule changes six deployed behaviours: Manoj drops the times of every stale entry, so a stale labelled session would block bookings in every other session each afternoon. **Garima chose D-7 (option B): a session's label is evidence.** Only an unlabelled UNKNOWN session cannot be ruled out. Deployed v0.3 behaviour and all existing tests stay unchanged; the only new retention is in `_future`'s named scope (R7-B1).
- Revision 10: Garima's decision D-8 on on-call doctors (Manoj's `AttendanceType` rule): a confirmed, usable entry is treated like any doctor's; otherwise `HANDOFF_REQUIRED`/`TRANSFER_DESK`, no longer a callback. New section C-8.
- **Revision 11:** Astra's on-call pre-flight (`SLOTS-PLAN-PREFLIGHT-R10.md`). C-8 now reads the session's confirmed status and its window/slot facts, not a decision that has lost them (B1); handoff is consumed after time selection too (B2); an on-call doctor's usual schedule is never a fact, so an unread on-call profile is no failure (B3); callback ranks before handoff (S1); the full test and document inventory and the 3a split are adopted.
- Revision 11.1: wording aligned with C-8 as listed in `SLOTS-PLAN-PREFLIGHT-R11.md` §5 (verdict ready to build). No rule changed.
- **Revision 11.2:** Garima accepted (8 October) the one added read stage for an on-call doctor asked about by name (D-8 consequence raised by the 2b reviews). Recorded in D-8 and §11, with the latency rule for build briefs. No rule changed.
- **Revision 11.3:** two gaps found by the 3a-2 review (`OPUS-SLOTS-3A2-REVIEW.md`), accepted by Garima (9 October). Neither is reachable before 4a. **P-1:** a department search (`SlotsNotRead`) applied no end-time guard, so a session whose supplied end had passed was listed as matched; C-3 step 3 now applies the same guard as step 2 (implemented in 4a). **P-2:** booking had no explicit refusal for unread slots; the booking gate now treats `SlotsNotRead` as a read failure (C-6 note; implemented in 3b). No published wording changes. **From the 3b review** (`OPUS-SLOTS-3B-REVIEW.md`, Garima 9 October): **L-1** "is it today" in C-6 step 5 uses the decision's basis, like `_contains_time` (one-line tidy-up in 4a); **L-2** the HTTP test server's shutdown wait is bounded so a stuck shutdown fails fast (one-file test-infrastructure commit T-1 after 4a); **O-1** owner question G-15. The blank-session type uses `AfterValidator` (Astra's 3b pre-check).

Section 13 maps every finding to its fix.

**This is the only plan.** `OPUS-OPS-API-040-IMPACT.md` is background (facts, owner answers, decisions); its sections 4–6 are superseded. `evidence/manoj-slots-live-20261007.txt` holds two raw live **today** slot captures with their board and profile context. It has no raw capability or future capture: label any contract-example fixtures as contract examples, not live captures.

## 0. Decisions and owner facts

**Garima's decisions:**

| # | Decision |
|---|---|
| K-1 | Update the `CLAUDE.md` rules: MCP consumes owner capacity facts and never computes capacity; with slots, NOT_CONFIRMED plus an open block can be noted; future dates use `/slots` |
| K-2 | Today, a block is bookable only while it has not ended (a guard; the owner also closes ended blocks) |
| K-3 | Departments never say "available" before a doctor's slots are read: "matches the department request; slots are checked after the caller selects the doctor" |
| K-4 | Pin the served 0.4.0 contract by hash |
| K-6 + D-2 | CREATE and RESCHEDULE **require the chosen time** (`preferredTime` / `newPreferredTime`) when slots are enabled. `session` stays **optional**: Manoj's write APIs do not accept it, and the API can return an unlabelled session. When a **non-blank** `session` is supplied, it must match (by `normalised` label) the session containing the chosen time, otherwise the request is refused. An unlabelled session never satisfies a supplied name; the agent can repeat the request without `session` (R5-B1a). **`session` is internal MCP context only and is never forwarded to Manoj** |
| K-7 + D-3 | Accept a later block returned by Manoj, and always return the actual `slotTime`. **`slotMoved` is `true` only when the returned `slotTime` is not the start of the block containing the caller's chosen time** (doctor late, or the time had passed). Choosing 10:45 and receiving the 10:30 block start is normal (`slotMoved false`). The agent always tells the caller `slotTime` |
| K-8 | If capabilities or slots cannot be read: no booking; "could not check" (availability) or "could not record" (booking) |
| D-1 | **Schema publication:** the complete final MCP schema (all new fields, defaults, descriptions, enums, next steps and VOICE-TEAM rows) is published **once**, in the first commit that changes the schema (phase 3a), and stays identical through the rest of the series. Nothing is deployed until the whole series is complete |
| D-4 | A session that exists only in Manoj's `/slots` response for the requested date (desk-added, not in the usual schedule or on the board) is **offered** only if it has at least one open, bookable block. It is presented as a **one-day session**, never as part of the regular schedule. Not offering it never erases its refusal facts (C-5) |
| D-5 | **No start-up or background capability process.** A selected doctor **always** gets a `/slots` read (in parallel with the existing reads), and `SlotPlan.enabled` says whether slots apply. **Department availability searches only** read `/capabilities` when needed, through the existing `DirectoryCache` |
| **D-6** | **UNKNOWN always means callback, with no exception, for ordinary doctors** (on-call doctors: handoff, D-8/C-8). When the board and the slot session disagree and either says UNKNOWN, the result is a callback, even if the other says CANCELLED (R4-B1). At booking time it applies to every session that **could be** the one the caller's time belongs to, as defined by D-7. A time that has already passed, or lies outside every session's known hours, is refused as `TIME_OUTSIDE_SESSION` with the open alternatives, even if an UNKNOWN session exists at another time that day (R5-B1b): a callback cannot make a passed or out-of-hours time bookable |
| **D-7** | **A session's label is evidence (option B, 8 October).** A session that **could be** the caller's target is one that contains the chosen time (blocks, else its window), **or has no label**, or, when no session contains the time, has unknown hours (the existing unbounded fallback). A **labelled** UNKNOWN session with unknown hours does not block a booking whose time or named session clearly belongs to another session: its label rules it out. Reason: Manoj erases the times of every stale entry, so the strict alternative (option A, revision 8) would turn most afternoon bookings into callbacks and change six deployed behaviours. With slots, Manoj books a time only into the session whose block contains it, so a blockless session cannot receive it |
| **D-8** | **On-call doctors (Manoj's contract, `AttendanceType`: "resolve to the front desk unless the board has a confirmed entry").** A confirmed entry is a desk-set **IN or LATE**, and it is actionable **only** when the board or slot data gives a usable time window (both bounds, not ended) or at least one open bookable slot; then the doctor is treated exactly like any other doctor. **CANCELLED** → not available. **NOT_CONFIRMED, UNKNOWN, stale, missing entries, and IN/LATE without a usable window or open slot** → **human handoff: `HANDOFF_REQUIRED`/`TRANSFER_DESK`**, reason `ON_CALL_DOCTOR`, never a callback. An on-call doctor has no usual schedule, so nothing else can make a date actionable. D-8 replaces D-6's callback for on-call doctors only (C-8). **Accepted latency consequence (Garima, 8 October):** an on-call doctor asked about by name for AVAILABILITY no longer stops after the directory search; it gets one added read group (today board ∥ slots, future profile ∥ slots), because only those reads can show a confirmed entry (§11) |
| Earlier | UNKNOWN → callback via a `CALLBACK_NOTED` summary. CANCELLED → not available. ON_CALL → always callback (**superseded by D-8**). No slot reads in department searches. B-1 (reschedule bypass when the appointment is absent from the lookup) stays as accepted |

**Manoj's answers:**

| # | Answer |
|---|---|
| G-1 | Full block → 409 `SLOT_FULL`; a time in a CANCELLED or UNKNOWN session, or outside the sessions → 400 |
| G-2 | Reschedule has the same check; a failed reschedule leaves the original unchanged |
| G-3 | NOT_CONFIRMED with a bookable block → NOTED |
| G-4 | Today, ended blocks are `bookable false`; a passed time goes to the next open block; other dates are not clock-dependent |
| G-5 | `mode` never overrides `status` |
| G-6 | `/slots` supports future dates (usual schedule, minus appointments, plus desk records) |
| G-9 | TIME_WINDOW (IN/LATE): blocks before the window are closed and blocks after it are absent; NOT_CONFIRMED uses the full usual session |
| G-10 | Future sessions are normally NOT_CONFIRMED and bookable; a desk CANCELLED makes that session unbookable; other sessions stay usable |

**Open with Manoj (designed around):**
- **G-11:** `""` is treated as an unlabelled session.
- **G-12:** session `bookable false` → stop; `true` → inspect the blocks.
- **G-13:** a time exactly at the session end is in no block, so it is refused.
- **G-14 (new):** can two slot sessions of one doctor on one date overlap in time, or share a label? Designed around: either is treated as malformed slot data (A-2), so "could not check / could not record".
- **G-15 (new, 3b review O-1):** can one doctor's board (or slots) for one date mix labelled and unlabelled sessions? Designed around by D-7: an unlabelled row stays in booking scope and its refusal decides (for example an unlabelled board row without a slot session gives `NO_OPEN_SLOT`). If Manoj confirms mixing cannot happen, nothing changes; if it can, revisit D-7 for unlabelled `NOT_AVAILABLE` rows.

## 1. Principles

1. **Facts in, decision once, format out.** Transport parses; retrieval gathers and checks the consistency of facts; **only `availability_policy.py` decides** (including which slots are open at the invocation time); services compose; `outcomes.py` formats what the policy produced and never re-applies a rule.
2. **Extend the existing flow; never write a parallel one.** Slot evidence enters through the existing `_today`, `_future`, `_combine`, `_contains_time` and `decide_booking`. No second decision table is added next to them (R4-B2).
3. **v0.3 is the same policy with no slot evidence.** `SlotPlan.enabled false` (the stub default) gives exactly today's results. The existing tests keep their business assertions (D-7), **except the on-call tests changed deliberately by D-8** (§9, listed exactly); request-path assertions change only where a `/slots` or `/capabilities` read is now expected, and each such change is intentional and listed in the hand-back.
4. **Capability is data, never a flag parameter.** It lives in `DoctorFacts.slots` and the per-session evidence.
5. **The owner computes capacity; we never do.** We read `bookable`, `available` and the block bounds, and apply our invariants: ON_CALL, UNKNOWN, CANCELLED, session flag, block not ended, consistency validation.
6. **Slots only for a selected doctor.** Departments stay session-level.

## 2. Layer A: transport (`contract.py`, `ops_client.py`, contract files, stubs)

- **A-1, the pin (complete migration, pre-flight S-1):**
  - add `contracts/manoj-openapi-20261007.yaml` (the served 0.4.0 bytes, SHA-256 `d3e93f45…6c80` per the pre-flight; re-verify) and a quoting-only overlay of exactly lines **2327, 2328, 2351, 2370, 2396, 2460** (overlay SHA per the pre-flight probe; re-verify);
  - update `contracts/README.md` and root `README.md:22`;
  - in `tests/test_contract.py`: pins, hashes, the allowed overlay lines, the error-code equality (`:71`), and the board-example path, which moved to `examples.facilityBoardMixedDay.value` (`:84`), with its date/count/time assertions;
  - `tests/test_stubs.py:22` (stub conformance) moves to the new overlay;
  - keep the 0.3.0 files as history.
- **A-2, `contract.py` and consistency checks:**
  - `ErrorCode` += `UNSUPPORTED_CAPABILITY`, `SLOT_FULL`;
  - new models: `Capabilities` (`slots.enabled`, `slots.blockMinutes`); `SlotBlock`; `SlotSession` (`session`, `status`, `bookable`, `slots`); `SlotPlan` (`doctorId`, `date`, `enabled`, `blockMinutes`, `sessions`);
  - `Appointment.slotTime: str | None` (ApproxTime);
  - **per-block and per-session invariants as model validation (pre-flight S-2):** `start < end`; non-negative counts; `available ≤ capacity`; blocks within a session strictly ordered and non-overlapping. A violation → `Malformed`. **Do not** require `booked + available == capacity`: live capture 2 has closed blocks with capacity 5, booked 0, available 0;
  - **plan-level consistency, in the reader** (B-4, beside the doctor/date check, because it needs `policy.normalised`): slot-session labels unique after `normalised(label or "")`; no block of one session overlaps a block of another session (G-14). A violation → `Malformed` at stage `slots`. This makes "the block containing a time" unique for the whole date and keeps every inconsistency on the existing read-failure path; the policy never needs a "duplicate join" failure (R4-B2.5, R4-S1).
- **A-3, `ops_client.py`:** `get_capabilities(deadline)` and `get_slots(doctor_id, date, deadline)`, using the existing `_read`/`_parse`/`_path_id` (`_path_id` before any HTTP, so `tests/test_booking.py:691` keeps its single request). No new retry or error rules.
- **A-4, stubs (`dev/frontdesk_stubs/ops.py`), fixtures not engines (pre-flight N-2):**
  - `GET /capabilities` from fixture state, slots **disabled** by default;
  - `GET /availability/{id}/slots` returning **scripted** plans (`set_slots(doctor_id, date, plan)`); when nothing is scripted, a **complete** disabled `SlotPlan` (requested `doctorId`, `date`, `enabled false`, `blockMinutes`, `sessions []`);
  - scripted write responses: `SLOT_FULL`, the 400 for a cancelled or unknown session, and a moved `slotTime`;
  - extend `reset()`/scenarios; keep auth, same-key replay and "failed reschedule leaves the original unchanged" ordering;
  - live-shaped fixtures copied from the evidence file are labelled as live captures; anything else is labelled as a contract example.

## 3. Layer B: retrieval (`schedule_reader.py`)

- **B-1, `ScheduleReader.slots(doctor_id, requested, deadline)`:** for the requested date (today or ISO), never cached; errors carry `stage = "slots"`.
- **B-2, `ScheduleReader.capabilities(deadline)`:** `DirectoryCache` key `("capabilities",)`, the same get-or-read pattern as `departments()` (`:40`), TTL `directory_cache_seconds` (default 300 s). Used **only** by `department()` for AVAILABILITY. Errors carry `stage = "capabilities"`. No start-up read, no background task, no lifecycle (D-5).
  - **Honest cache guarantee (R4-S2):** `DirectoryCache` is TTL/LRU, not single-flight (`cache.py:21–38`). Sequential searches reuse the cached value while it is fresh; concurrent cold searches may each read `/capabilities`, and eviction or TTL 0 causes extra reads. This is accepted and tested as such. No lock or task framework is added.
- **B-3, `DoctorFacts.slots`** (`availability_policy.py:70`), a defaulted field so existing constructors are unchanged:

  | Value | Meaning | Set by |
  |---|---|---|
  | `None` | No slot evidence: slots disabled (`SlotPlan.enabled false`), WORKING_HOURS (including the ON_CALL WORKING_HOURS short-cut) | `doctor()` |
  | `SlotPlan` (enabled) | Read for this doctor and date, consistency-checked | `doctor()` |
  | `SlotsNotRead()` | The facility enables slots, but they were deliberately not read | `department()` |

- **B-4, `ScheduleReader.doctor`** (`:71`), AVAILABILITY purpose: add the slots read to the **same** parallel step, on every branch:
  - today without a summary: profile ∥ board ∥ slots;
  - today with a summary (`:85`): board ∥ slots;
  - future: profile ∥ slots (the current sequential profile read becomes a gather).

  **The ON_CALL early return (`:73`) is removed for AVAILABILITY (D-8):** an on-call doctor found by name now gets the same parallel reads as any doctor (today: board ∥ slots; future: profile ∥ slots), because a confirmed entry can make them bookable. `tests/test_availability.py:523` (`["/doctors"]`) changes **intentionally** to include those reads. The early return stays for WORKING_HOURS (no reads needed: C-8). WORKING_HOURS: no slots. If `plan.enabled` is false, store `None`. Validate that `plan.doctorId` and `plan.date` match the request, plus the A-2 plan-level checks; a violation is `Malformed` (stage `slots`). An ID-only ON_CALL lookup still performs the concurrent reads before the profile reveals the attendance type (accepted).
- **B-5, `ScheduleReader.department`** (`:98`):
  - **only for `Purpose.AVAILABILITY`** (R4-S2): read cached capabilities **in parallel** with the existing search (and the board, today). WORKING_HOURS makes no capability or slot read and keeps its meaning (`test_availability.py:246`, `working_hours:261–269`);
  - slots enabled → every candidate's facts carry `SlotsNotRead()`;
  - the two match counts (`:110`, `:131`) use `policy.is_match` (C-7);
  - mock transports such as `tests/test_schedule_reader.py:36–60` must serve `/capabilities` explicitly once this path is wired (their fallback parses the last path segment as an integer).
- **B-6, one stage-to-detail helper, without changing existing outcomes (R4-S1):** today `availability._service_error:74` and `booking._schedule_gate:233` each map a read stage to a detail. Replace only that detail selection with one helper in `schedule_reader.py`: `board → BOARD_UNAVAILABLE`, `profile → PROFILE_UNAVAILABLE`, `slots → SLOTS_UNAVAILABLE`, `capabilities → CAPABILITIES_UNAVAILABLE`, `AUTH` where it applies today; each caller keeps its own fallback (`DIRECTORY_UNAVAILABLE` in availability, `PROFILE_UNAVAILABLE` in booking).
  - **New stages only:** **any** failure at stage `slots` or `capabilities` (timeout, 5xx, malformed, a `Rejected` 400/404, `UNSUPPORTED_CAPABILITY`, a consistency violation) is a **read failure**: `COULD_NOT_CHECK` (availability) or `COULD_NOT_RECORD` (booking). Never `NOT_FOUND`, `INVALID_REQUEST` or `REJECTED` (K-8). Handle these stages **before** the generic `Rejected` branches.
  - **Existing stages unchanged:** profile/appointment-lookup `Rejected` → `REJECTED` with action-specific fields (`tests/test_booking.py:808–831, 836–862`); board retry-after (`test_availability.py:100–113`, `test_booking.py:401–404`); AUTH (`test_booking.py:238–243`); malformed owner id (`:682–692`); directory `NOT_FOUND`/`DIRECTORY_REJECTED`. `_failure`'s per-action field filtering is unchanged. Owner-write rejections keep their existing mapping.

## 4. Layer C: policy (`availability_policy.py`, the only decision point)

### C-1: per-session evidence

`SessionDecision` gains:
- `evidence: SessionSlots | SlotsNotRead | None`;
- `open_slots: tuple[SlotBlock, ...] | None`, the policy-computed projection that presentation formats.

`SessionSlots` holds the matched slot session's `status`, session `bookable` flag and **all** blocks, or `SessionSlots.missing()` (read, but no slot session matched: no blocks, not bookable). The four cases are explicit:

| Case | `evidence` | `open_slots` (R4-S3) |
|---|---|---|
| Slots disabled | `None` | `None` |
| Deliberately not read (department) | `SlotsNotRead` | `None` (never serialised as "checked, empty") |
| Read, but no slot session for this row | `SessionSlots.missing()` | `()` |
| Read and matched | `SessionSlots(status, bookable, blocks)` | the OPEN blocks when the session decision is `APPOINTMENT_REQUEST`, else `()` |

### C-2: status reconciliation (one rule, D-6)

When a board row and its slot session report different statuses (two reads of one board can race), the more restrictive wins in this order: **`UNKNOWN > CANCELLED > NOT_CONFIRMED > LATE > IN`**. UNKNOWN is first, so "UNKNOWN always means callback" holds with no exception for ordinary doctors (an on-call doctor's UNKNOWN becomes a handoff in C-8; the reconciliation order is the same). The reason is `BOARD_STALE` when the board row is UNKNOWN and `isStale`, else `BOARD_UNKNOWN` (also when only the slot session says UNKNOWN). Future dates have no board: the slot status is used as is.

### C-3: one session rule in a fixed order (replaces `TODAY_STATUS`, `:168`)

`session_decision(facts)` takes a small facts record (reconciled status, `is_stale`, evidence, date kind, facility now, the row's window), not booleans:

1. **Status first:**
   - UNKNOWN → `CALLBACK_REQUIRED`/`BOARD_UNKNOWN` or `BOARD_STALE`;
   - CANCELLED → `NOT_AVAILABLE`/`CANCELLED`.

   (On-call doctors: the same steps, then C-8.)
2. **Evidence `None` (v0.3):** exactly today's rules, **including the ended-window guard** (`_today:213–214`, pinned by `test_availability_policy.py:63–66` and `test_booking.py:75–85`):
   - today: IN/LATE → `APPOINTMENT_REQUEST`, or `SESSION_ENDED` when the window has ended; NOT_CONFIRMED → `CALLBACK_REQUIRED`/`BOARD_NOT_CONFIRMED`;
   - future: usual-schedule behaviour, never the today NOT_CONFIRMED rule.
3. **`SlotsNotRead`** (department): first, today, the step 2 ended-window guard (a supplied end time that has passed → `NOT_AVAILABLE`/`SESSION_ENDED`; revision 11.3, P-1: without block facts, a supplied end is the only end evidence, and an on-call row with the same facts is already refused by C-8). Otherwise IN/LATE/NOT_CONFIRMED, and usual sessions on the requested weekday → **`SLOT_CHECK_REQUIRED`**.
4. **`SessionSlots` with session `bookable false`, or `missing()`** → `NOT_AVAILABLE`/**`NO_OPEN_SLOT`**; blocks are neither inspected nor offered.
5. **`SessionSlots` with session `bookable true`** → classify blocks (C-4); the board end-time guard does **not** apply (owner blocks are authoritative):
   - ≥1 OPEN → `APPOINTMENT_REQUEST`;
   - no blocks at all → `NO_OPEN_SLOT`;
   - all blocks CLOSED **because they ended today** → `SESSION_ENDED`;
   - otherwise → `NO_OPEN_SLOT`.

**One meaning per refusal reason (R4-B2.1–2):** `NO_OPEN_SLOT` = *this session* has no open slot. `SLOT_FULL` = the chosen time's block is full while the session has other open blocks (C-6). The answer for a session never depends on another session; there is no "refinement" step.

### C-4: one block classifier and one lookup

- `block_state(block, now | None)`:
  - `CLOSED`: `bookable false`, or, today only, `end ≤ facility now` (minute precision; `end == now` is ended);
  - `FULL`: `bookable true` and `available == 0`;
  - `OPEN`: `bookable true` and `available > 0` and not ended.
- Future dates: `now` is `None`, so no clock check (G-4). No board-window intersection (G-9).
- `block_at(blocks, t)` (`start ≤ t < end`) is the one lookup, used by `_contains_time`, booking and `expected_slot`. Thanks to the A-2 plan-level check, at most one block of the date contains `t`.

### C-5: day sessions, scope and alternatives (today and future share one shape)

Both `_today` and `_future` produce the same three things, and only the source of the rows differs:
- **day sessions**: every session relevant to the requested date, each with its decision and reason (the **facts**);
- **scope**: the day sessions selected by the optional `session` label;
- **alternatives**: the day sessions for which `is_match` holds (what may be **offered**).

The doctor decision is `_combine(scope, named)` when the scope is non-empty, as `_today` does now. Selection of facts and selection of offers are separate, so a refusal reason is never lost because the session is not offered (R4-B3).

**Unlabelled UNKNOWN in a future named scope (R7-B1, D-7):** today's named scope already keeps unlabelled rows, and booking's matched-time branch already keeps unlabelled rows; both stay exactly as they are. Only `_future`'s named scope gains one condition: it also keeps rows whose decision is **unresolved** (`CALLBACK_REQUIRED`, or `HANDOFF_REQUIRED` for an on-call doctor, C-8) and whose label is blank after `normalised` (empty or null). Such a row could be the session the caller means. The condition is limited to unresolved rows so that an unlabelled cancelled or open one-day session never refuses or redirects a named request. Retaining a row never makes it satisfy a supplied name (C-6 step 5). Labelled rows are ruled out by their label (D-7).

- **Today** (`_today`, `:207`):
  - day sessions = board rows, each joined to its slot session by `normalised(label or "")` (`null` ≡ `""`, G-11), plus slot sessions with no board row (desk-added in slots, D-4: decided by C-3, offered only when `APPOINTMENT_REQUEST`). Several board rows with the same label join the same slot session, as v0.3 already tolerates duplicate board rows; they share one block identity and never count as extra capacity;
  - **presentation of a slot-only row today (R5-B2):** basis `LIVE_BOARD`, formatted by the existing `BoardSessionOut` with the slot status, times from its first and last block (or `null` when it has no blocks, which `BoardSessionOut` already allows), no delay, note or staleness. The live board is already date-specific, so **no `oneDay` field is added to `BoardSessionOut`**;
  - a board row with no slot session gets `SessionSlots.missing()`;
  - the scope rule is unchanged (unlabelled rows stay in a named scope).
- **Future** (`_future`, `:235`), restructured to the same shape:
  - **usual-session source:** for regular and visiting doctors, the profile's usual schedule; for an on-call doctor, `()` without consulting the profile (C-8 fact 1). The two exits below apply to regular and visiting doctors only; an on-call doctor with no day sessions takes C-8's no-session handoff;
  - early exit: profile unreadable → `COULD_NOT_CHECK`/`PROFILE_UNAVAILABLE` (unchanged);
  - day sessions = usual sessions whose days include the requested weekday, each joined to a slot session by label (unjoined → `missing()` when slots are enabled), **plus** one-day sessions (slot sessions joined to no usual session on that weekday). Usual sessions with the same label on **different** weekdays are not a conflict: only that weekday's rows are joined;
  - usual sessions on other weekdays remain in the output as `NOT_USUAL_DAY` rows (unchanged);
  - no day sessions: `NO_USUAL_SCHEDULE` callback when the profile has no usual schedule (unchanged), else `NOT_AVAILABLE`/`NOT_USUAL_DAY`;
  - scope = day sessions filtered by `session` with **the existing future label rule** (unlabelled usual sessions are not retained under a named session, as today; usual labels are nullable at `contract.py:61`, so the today rule must not be borrowed), **plus unlabelled unresolved rows** (`CALLBACK_REQUIRED`, or `HANDOFF_REQUIRED` for an on-call doctor; above). Without slots every future row is `APPOINTMENT_REQUEST`, so the condition never fires and v0.3 is identical. With slots, a named Morning beside an unlabelled one-day UNKNOWN (empty or null label) keeps the UNKNOWN in scope and gives a callback, in availability and booking alike (R7-B1); an empty scope → `SESSION_NOT_USUAL` if day sessions exist and a session was named, else `NOT_USUAL_DAY` (unchanged reasons);
  - otherwise the decision is `_combine(scope, named)`. Without slots, every day session is `APPOINTMENT_REQUEST`, so v0.3 results are identical.
  - **Output rows, exactly as HEAD (R5-S2):** `DoctorDecision.sessions` is the scope when it is non-empty, and **all** rows (day sessions and other-weekday `NOT_USUAL_DAY` rows) when the scope is empty (`_future:247–250`). So with Morning on Monday and Evening on Tuesday, a successful Monday query returns only Morning; a Monday request for Evening returns both rows and `SESSION_NOT_USUAL`.
  - **A one-day session without owner hours (R5-B2):** a slot-only session with no blocks has no start or end. It stays a fact (it decides the reason) and is formatted as `UsualSessionOut` with `oneDay true`, `daysOfWeek []`, its slot `status`, and `start`/`end` **`null`**. Nothing is invented. §6 makes `UsualSessionOut.start`/`end` nullable for exactly this case.
  - Effect (ordinary doctors; on-call uses C-8): a joined UNKNOWN session → callback; a joined CANCELLED session → `CANCELLED`; a one-day UNKNOWN session on a non-usual weekday → callback, not `NOT_USUAL_DAY` and not offered.
- **WORKING_HOURS:** `_usual` also feeds `working_hours` (`:268`). It never receives date-specific evidence there. Unchanged output for regular and visiting doctors; an on-call doctor gets the C-8 handoff.

### C-6: booking (`decide_booking`, `:281`): the existing flow, extended

The current structure stays, in its current order. Only the marked steps are new:

1. Whole-scope checks: `HANDOFF_REQUIRED` → `Handoff(ON_CALL_DOCTOR)` (D-8, replacing the current ON_CALL `Callback` at `:283–284`); `CALLBACK_REQUIRED` → `Callback`; `COULD_NOT_CHECK` → `Handoff(PROFILE_UNAVAILABLE)` (only a profile failure reaches here: slot inconsistencies are read failures, A-2/B-6); `NOT_AVAILABLE` → `NotAvailable(reason, alternatives)` (N-2 preserved for `CANCELLED`, `SESSION_ENDED`, `NOT_USUAL_DAY`, `NO_OPEN_SLOT`).
2. **New:** slots apply (`facts.slots` is a `SlotPlan`) and no time was given → `TimeRequired(alternatives)` (K-6).
3. Time selection (unchanged code): the sessions that **could be** the one the time belongs to (D-7): those containing the time, plus unlabelled rows (they may be the same session); if none contains it, the unbounded rows; if there are none of those either, `TIME_OUTSIDE_SESSION` with the alternatives. A labelled UNKNOWN row with unknown hours beside a session that contains the time is ruled out by its label, exactly as deployed today (`tests/test_booking.py:433, 449, 460, 499` and `tests/test_availability.py:127, 154` stay unchanged).
   - **The only other change is inside `_contains_time`** (`:272`), which stays the single membership rule: a session whose evidence has blocks contains `t` when `block_at(blocks, t)` finds a block; any other session uses the existing window rule, including its `max(start, now)` passed-time narrowing. So an UNKNOWN afternoon with no blocks but a window containing `t` stays in scope, and an unlabelled UNKNOWN row is still retained (R4-B2.3–4). A passed time, or one outside every known window, is refused even if an UNKNOWN session exists elsewhere that day (D-6 scope, R5-B1b).
4. Combination: `_combine(sessions, True)`; **`HANDOFF_REQUIRED` → `Handoff(ON_CALL_DOCTOR)`** (B2: a usable on-call Morning beside an unlabelled unresolved on-call row must not write); `CALLBACK_REQUIRED` → `Callback`; `NOT_AVAILABLE` → `NotAvailable(session reason)`. A selected session that is entirely full answers `NO_OPEN_SLOT` here, wherever other sessions are.
5. **New, slots apply:** the block is `block_at` over the scoped `APPOINTMENT_REQUEST` sessions' blocks (unique by A-2), remembering which session it belongs to:
   - none (including `t` exactly at a session end, G-13) → `NotAvailable(TIME_OUTSIDE_SESSION)`;
   - a non-blank `session` was supplied and `normalised(block session label or "")` ≠ `normalised(session)` (this includes an unlabelled block session) → `NotAvailable(TIME_OUTSIDE_SESSION)` (D-2, R5-B1a). Unlabelled rows stay in scope at steps 3–4, so an unlabelled unresolved row still gives a callback (or, for an on-call doctor, a handoff) first; they are retained for refusal safety, never accepted as the named target;
   - `CLOSED` → `NotAvailable(TIME_OUTSIDE_SESSION)` (as v0.3 refuses a passed time);
   - `FULL` → `NotAvailable(SLOT_FULL)`;
   - `OPEN` → `Write(expected_slot = block.start)`.

   **Without slots** (unchanged): `TIME_NOT_VERIFIABLE`, the window check, `Write()`.

Notes:
- **Unread slots never book (revision 11.3, P-2).** Booking always reads slots for the selected doctor (`ScheduleReader.doctor`), so `SlotsNotRead` cannot reach the booking gate. As with `_single` (C-7), the booking gate still checks the invariant: `facts.slots` being `SlotsNotRead` → `COULD_NOT_RECORD`/`SAY_COULD_NOT_RECORD`, detail `SLOTS_UNAVAILABLE`, no write.
- With slots, `SessionRequired` is unreachable (a time is always present after step 2) and `TIME_NOT_VERIFIABLE` does not occur (blocks give complete bounds). No special casing is added for either.
- `alternatives` stay **`SessionDecision`s** (with `open_slots`), so `outcomes.session_out` keeps working. Raw blocks are never returned as alternatives.
- **Blank session (R4-B2.5, R5-S3):** a `session` that is blank after `strip()` means "no session", decided once at the input boundary. One shared type, `SessionChoice = Annotated[str | None, AfterValidator(...)]` (after, not before, so type and `max_length` are checked first and 41 spaces are rejected like any over-long input; Astra 3b pre-check, revision 11.3), lives in **`outcomes.py`** (the MCP-surface module both services already import; the pure policy stays free of Pydantic; no new file). It is the type of `AvailabilityRequest.session` (`availability.py:31`) and `BookingRequest.session` (`booking.py:47`); each field keeps its existing `Field(...)` (default, `max_length`, description). `tools.py` is **unchanged**: its parameters are passed into those request models (`tools.py:117–119`, `:148–152`), so the validator runs there. The validator turns only blank strings into `None` and leaves every other input to normal validation; default and description stay as published, and the JSON schema must not change. This changes v0.3 for `"   "` (today it scopes to unlabelled rows only; a future blank currently gives `SESSION_NOT_USUAL`). No existing test supplies a blank session; the blank **owner labels** at `tests/test_booking.py:122–132` are a different thing and stay unchanged.

### C-7: department and shared combination

- **`is_match(decision)`** = `APPOINTMENT_REQUEST` or `SLOT_CHECK_REQUIRED`. It is the single "candidate" predicate, used by:
  - `_combine` (`:189`, the positive kind in mixed sessions);
  - the alternatives of `_today` and `_future` (C-5). It no longer selects `_future`'s scope;
  - `aggregate` (`:328`);
  - both reader counts.

  It is **not** used where "confirmed capacity" is meant.
- **`_combine` mixed scope (unchanged rules):** not named and a match present → match kind, `session_choice_required`; otherwise the **unresolved** kind first (`CALLBACK_REQUIRED`, or `HANDOFF_REQUIRED` for an on-call doctor; the two never occur for the same doctor), including an unlabelled unresolved row under a named session, then NOT_AVAILABLE. The D-7 future named-scope condition and C-6 retention use the same "unresolved" meaning.
- **`aggregate`:** if the candidates are `SLOT_CHECK_REQUIRED` → new outcome **`DOCTORS_MATCHED`** with `ASK_WHICH_DOCTOR` and `bookableFound = 0`. `SearchState.matches_found` stays internal and distinct from the published `bookableFound`. WORKING_HOURS: unchanged facts, order and presentation, `bookableFound 0`; on-call doctors' facts carry the C-8 handoff decision.
- **`rank`** (`:323`): `order` becomes `APPOINTMENT_REQUEST`/`SLOT_CHECK_REQUIRED: 0`, `CALLBACK_REQUIRED: 1`, `HANDOFF_REQUIRED: 2`, `NOT_AVAILABLE: 3`, so a capped callback result always lists its callback doctors first (S1).
- **`aggregate` without matches:** a callback candidate first (unchanged); otherwise a handoff candidate → `HANDOFF_REQUIRED`/`TRANSFER_DESK`, reason `ON_CALL_DOCTOR`; otherwise NOT_AVAILABLE.
- **Single-doctor `SlotsNotRead`** is a violated retrieval invariant. `_single` maps it to `COULD_NOT_CHECK`/`SAY_COULD_NOT_CHECK` with detail `SLOTS_UNAVAILABLE`, never "available".

### C-8: on-call doctors (D-8)

On-call doctors use the **same** path as every doctor (C-1 to C-7), with two on-call facts and one function.

**Fact 1, no usual schedule (B3).** Manoj: an on-call doctor has no usual timing and the board is the only source. So for an on-call doctor the usual schedule is **never** a fact: `_future`'s usual-session source is `()` and the profile is not consulted for the date decision. Day sessions are only today's board rows (joined to slots) or, for a future date, one-day slot sessions. A deliberately unread on-call profile (department search, `schedule_reader.py:115–116`) is therefore never mistaken for `PROFILE_UNAVAILABLE`; real read failures (exceptions, `ReadFailure`) stay `COULD_NOT_CHECK`.

**Fact 2, confirmed and usable, read from the session facts (B1).** `SessionDecision` already carries the reconciled `owner_status`, `start`, `end` and `evidence`. One pure function, `on_call(s, now)`, runs on each on-call session **after** C-3 and **before** scope, alternatives and `_combine`:
- `owner_status` CANCELLED → keep the C-3 decision (`NOT_AVAILABLE`/`CANCELLED`);
- `owner_status` IN or LATE **and usable** → keep the C-3 decision unchanged. Usable = a window with both `start` and `end`, not ended (today), **or** evidence with ≥1 OPEN block. So once usable, the ordinary rules apply: a usable window with all slots full stays `NOT_AVAILABLE`/`NO_OPEN_SLOT` like any doctor; a department IN row with a usable window stays `SLOT_CHECK_REQUIRED`;
- **anything else** → `HANDOFF_REQUIRED`/`ON_CALL_DOCTOR`: NOT_CONFIRMED (even with open blocks), UNKNOWN, stale, no status (a usual-schedule row cannot occur, by fact 1), IN/LATE with a missing or ended window and no open block (including a department IN row with missing bounds).

Doctor-level exits with no session use the same result: today with no board row, and any date with no day sessions → `HANDOFF_REQUIRED`/`ON_CALL_DOCTOR`. `TIME_NOT_VERIFIABLE` cannot arise for an on-call doctor, because a kept no-slot session has both bounds.

`decide_doctor`'s ON_CALL early return (`:256–257`), `_on_call` (`:203–204`) and `decide_booking`'s reason-based ON_CALL callback (`:283–284`) are deleted. `working_hours` (`:262–263`) returns `HANDOFF_REQUIRED`/`ON_CALL_DOCTOR` for an on-call doctor (there are no usual hours to present); it is the same no-session result, not a second rule.
- **Booking:** a usable on-call session books exactly like any other (C-6). `HANDOFF_REQUIRED` is consumed at both C-6 step 1 (whole scope) and step 4 (after time selection) → `Handoff(ON_CALL_DOCTOR)` → the existing `HANDOFF_REQUIRED`/`TRANSFER_DESK` booking result (`booking.py:251–252`), with no write.
- **Availability:** `_single` maps `HANDOFF_REQUIRED` → `HANDOFF_REQUIRED`/`TRANSFER_DESK`, reason `ON_CALL_DOCTOR`, no callback metadata. Handoff is never a match (`is_match`), so it is never counted as bookable.

## 5. Layer D: services

- **D-1, `availability.py`:** `_single` (`:141`) gains the `SLOT_CHECK_REQUIRED` and `HANDOFF_REQUIRED` (C-8) entries as above. `DOCTORS_MATCHED` is mapped. Read failures go through the B-6 helper.
- **D-2, `booking.py`:**
  - **Gate return types, explicit (the `if blocked := …: return blocked` idiom is replaced, because a successful `Write` is truthy):**
    - `_schedule_gate` → `BookingResult | policy.Write` (CREATE never gets `None`);
    - `_reschedule_gate` → `BookingResult | policy.Write | None`, where `None` is only the accepted B-1 bypass (appointment absent from the lookup; `expected_slot` unknown);
    - `_create` (`:214`) and `_change` (`:281`) branch on the type and pass `expected_slot` to formatting. No wrapper result type.
  - `TimeRequired` → `INVALID_REQUEST`, `fields` = `preferredTime` (CREATE) or `newPreferredTime` (RESCHEDULE) from the gate's `action`; detail `TIME_REQUIRED`; nextStep **`ASK_WHICH_TIME`**; `sessions` with `openSlots`. The input time fields stay optional in the schema (LIST, CANCEL and slots-disabled booking are unaffected).
  - **`session` is never in the owner body** (D-2). `_OWNER_FIELDS` (`:61–77`) already excludes it; add a test that asserts this.
  - `_failure` (`:147`): a **definite** `SLOT_FULL` → `NOT_AVAILABLE`/`OFFER_OTHER_SESSION_OR_TIME`, `detail SLOT_FULL`; `UNSUPPORTED_CAPABILITY` on a write → `REJECTED` with that detail. A 4xx/5xx on a **same-key retry** stays `UNCERTAIN` (`ops_client.py:307`, unchanged).
  - **`slotTime`/`slotMoved` (K-7 + D-3):**
    - `_appointment_out` (`:86`) sets `slotTime` from the owner `slotTime`, else `expectedTime`, else `null`;
    - CREATE/RESCHEDULE set `slotMoved = (owner slotTime is present and expected_slot is known and slotTime != expected_slot)`;
    - otherwise `false`; LIST and CANCEL always `false`; a missing owner `slotTime` is never reported as moved.
  - `_written` (`:324`) passes these through for CREATE.
- **D-3, replay after capacity changes, documented and tested:**
  - a later tool invocation repeating the **same** `X-Operation-Id` after a possibly committed write runs the gate again;
  - if our own first write took the last seat, the gate refuses (`SLOT_FULL`/`NO_OPEN_SLOT`) **before** the owner's replay can be reached;
  - the intended client behaviour after `UNCERTAIN` is unchanged: transfer, not retry.
  - Record this in VOICE-TEAM and DECISIONS. No local persistence and no invented idempotency-lookup API.

## 6. Layer E: the voice contract, published once in phase 3a (D-1)

| Output | Change (type, **default** and description fixed in 3a) |
|---|---|
| `BoardSessionOut` | `openSlots: list[SlotOut] \| None = None` (`SlotOut = {start, end, available}`, from the policy's `open_slots`; `null` = not checked) |
| `UsualSessionOut` | `openSlots: list[SlotOut] \| None = None`; `status: AvailabilityStatus \| None = None` (owner slot status for future sessions); `oneDay: bool = False` (D-4: `daysOfWeek []`, `onRequestedDate true`, start/end from owner blocks); **`start`/`end` become `str \| None`, still required (no default)**, described as "null only for a one-day session whose hours the owner did not supply" (R5-B2). Usual sessions always keep their hours. The formatter emits `oneDay true`, the slot `status` and `onRequestedDate true` for one-day facts; the current `requested.weekday in s.days` (`outcomes.py:66`) would give `false` for `days ()`, so it is replaced for one-day rows in 3a. Both tools' VOICE tables are regenerated in 3a |
| `BoardSessionOut` (slot-only row today) | no new field: the existing nullable times and `status` represent it (C-5) |
| `DoctorAvailability.usualSessions` | description updated: it no longer means only "usual working hours, independent of live attendance" (`outcomes.py:79–80`); it covers the requested date's sessions, their slot status and one-day sessions |
| `Decision` | += `SLOT_CHECK_REQUIRED`, `HANDOFF_REQUIRED` (C-8) |
| `Reason.ON_CALL_DOCTOR` and the `CALLBACK_REQUIRED`/`HANDOFF_REQUIRED` outcome descriptions | rewritten for D-8: on-call without a confirmed, usable entry → transfer to the desk, not callback. VOICE-TEAM `:99, 302, 308, 605, 912, 914, 1598, 1636–1638` (tool descriptions, CALLBACK and HANDOFF outcome meanings, reason table, working-hours note); `src/prompt.py:16`; both tool descriptions in `packs/healthcare.json`; their snapshot copies. All in 3a-1 |
| `Reason` (both tools' schemas, including the nested `Callback`) | += `NO_OPEN_SLOT`, `SLOT_FULL` |
| `AvailabilityOutcome` | += `DOCTORS_MATCHED` |
| `BookingNextStep` | += `ASK_WHICH_TIME` |
| `AppointmentOut` (CREATE, RESCHEDULE, LIST, CANCEL) | += `slotTime: str \| None = None`, `slotMoved: bool = False`. The defaults let the unchanged `_appointment_out:86–89` constructor work until 3b (R4-S4) |
| Detail strings | `TIME_REQUIRED`, `SLOT_FULL`, `SLOTS_UNAVAILABLE`, `CAPABILITIES_UNAVAILABLE` |

- In 3a, in one commit: `SCHEMA_VERSION` bump, regenerated snapshot (it includes descriptions: `test_server.py:134`), `packs/healthcare.json` descriptions, and the VOICE-TEAM tables (`test_server.py:409/442`). Pack text keeps the legacy facts asserted by `test_server.py:91–96`, qualified by slots enabled/disabled.
- VOICE-TEAM facts:
  - choose a time from `openSlots`; the time is required; `session` is optional and validated;
  - `SLOT_CHECK_REQUIRED`/`DOCTORS_MATCHED` = "matches; slots checked after selection";
  - `NO_OPEN_SLOT` = that session has no open slot; `SLOT_FULL` = that time is full. **Offer only the `sessions`/`openSlots` returned in the same result.** A `SLOT_FULL` from Manoj's write (seats taken in the meantime) returns no checked alternatives: check availability again before offering another time (R5-S1). The MCP never infers alternatives from the error code;
  - a `oneDay` session with `start`/`end` `null` has no known hours: never offer a time from it (it is only ever a refusal fact);
  - always say `slotTime`; `slotMoved` means the time changed (late doctor, or the time had passed);
  - `oneDay` sessions are for that date only;
  - NOTED with NOT_CONFIRMED = "noted, the desk will confirm";
  - a same-operation retry after `UNCERTAIN` can be refused (D-3).

## 7. Layer F: rules and documents

- `CLAUDE.md` `:14, 20, 23, 24, 26` (K-1, K-2, K-6, D-2, D-5, D-6, D-8: "ON_CALL always requires callback" (`:23`) and the single on-call WORKING_HOURS callback (`:26`) are replaced; ordinary UNKNOWN and empty regular schedules keep their callback).
- `docs/handover/mcp-only/PLAN.md:31, 67–68, 77–78` (on-call rules) in addition to the lines below; a new `docs/DECISIONS.md` entry supersedes the old on-call rule.
- `docs/DECISIONS.md` (`:115, 166` and a new entry): K, D, G and the evidence model.
- `docs/handover/mcp-only/PLAN.md` (`:35, 67, 89, 126, 133, 204`).
- `contracts/README.md`, root `README.md`.
- Previous hand-backs stay historical.

## 8. Operational consumers (pre-flight S-4)

- **`tests/test_external.py`:** `:151` and `:158` submit CREATE/RESCHEDULE without a time and expect NOTED, which is now refused when slots are enabled. Choose a time from `openSlots` of synthetic owner-designated slot data. `:119` gains `DOCTORS_MATCHED`. These tests are outside `make test-fast`; **running them live needs separate authorisation.**
- **`dev/bench.py`, `tests/test_bench.py`:**
  - add slot-enabled and slot-disabled scenarios that assert useful outcomes and the observed `/slots` read before timing;
  - replace the hard-coded `10:45` with a time from `openSlots`;
  - keep the designated-tenant write gate;
  - parallel reads are not a latency guarantee: the 0.30 s budget (`config.py:59`) still needs measurement.
- **`dev/demo.py`, `tests/test_e2e_processes.py`:** update only where journeys change. `make test-fast` excludes these; run the local process tests before hand-back.
- **ContextForge:** refresh schemas after an approved release. **The voice team:** handle `DOCTORS_MATCHED`, `ASK_WHICH_TIME`, `openSlots`, `oneDay`, `slotTime` and `slotMoved` before cutover. Shobhit is unaffected. No new secret or endpoint configuration.

## 9. Tests (red first for every behaviour change)

| Area | Tests |
|---|---|
| Unchanged v0.3 | With stub slots disabled, all existing business assertions hold, except the on-call tests changed deliberately by D-8 (listed below). D-7 changes none: the six tests Astra's R8 run named for labelled-row behaviour must pass unchanged. Request-path changes are limited to the expected `/slots` read on selected-doctor paths and `/capabilities` on department AVAILABILITY paths, each intentional and listed. Whole-list equality assertions: `test_availability.py:260` (missing date) and `test_booking.py:691` (malformed doctor id) stay unchanged; `:523` (on-call found by name) changes **deliberately** in 2b (D-8: directory → board ∥ slots today, directory → profile ∥ slots future) |
| Transport | `get_slots`/`get_capabilities` parse; per-block invariants reject overlapping or negative blocks; plan-level checks reject duplicate labels and cross-session overlap; doctor/date mismatch → `Malformed`; both live captures pass; `SLOT_FULL`/`UNSUPPORTED_CAPABILITY`/`slotTime` parse; the overlay differs only on the six lines |
| Retrieval | Selected doctor: `/slots` in the same parallel step on each branch; WORKING_HOURS: no `/slots`, board or `/capabilities` (regular and visiting doctors still read the profile, `schedule_reader.py:87`; an ID-only on-call doctor reads the profile to learn its attendance type; only the known on-call summary short-cut skips it); department AVAILABILITY: zero `/slots`, `/capabilities` reused while cached (cold, warm and concurrent-cold cases asserted honestly), `SlotsNotRead` set; department WORKING_HOURS: no `/capabilities`; disabled → `None`; disabled→enabled picked up on the next selected-doctor call |
| Failures | Stage `slots`/`capabilities` with timeout, 5xx, 400, 404, malformed, inconsistency, 401/403 → `COULD_NOT_CHECK`/`COULD_NOT_RECORD` (never `NOT_FOUND`/`REJECTED`), no POST; existing profile/lookup/board/directory/AUTH outcomes unchanged (the R4-S1 anchors); other tools unaffected by a capabilities failure |
| Policy C-2/C-3 (ordinary doctors) | Both orderings, stale and fresh: board UNKNOWN + slot CANCELLED → callback (`BOARD_STALE` when stale); board CANCELLED + slot UNKNOWN → callback `BOARD_UNKNOWN`; board IN + slot UNKNOWN → callback; board IN + slot CANCELLED → `CANCELLED`; UNKNOWN with session `bookable false` → callback; flag false → no blocks offered; empty block list → `NO_OPEN_SLOT`; all ended today → `SESSION_ENDED`; legacy ended-window guard only without evidence; future without slots unchanged |
| Policy C-4/C-5 | OPEN/FULL/CLOSED incl. `end == now`; live capture 1 (blank label, no usual schedule) and capture 2 (session true, all Morning blocks closed); future: joined UNKNOWN → callback, joined CANCELLED → `CANCELLED`, wrong weekday → `NOT_USUAL_DAY`, same label on another weekday not a conflict; one-day open → offered; one-day UNKNOWN on a non-usual weekday → callback, not offered; no usual schedule: one-day open → offered, one-day UNKNOWN → its callback reason, **no day sessions at all** → `NO_USUAL_SCHEDULE`; future output rows: successful query lists only the scope, unmatched named session lists all rows (`test_availability_policy.py:188–199`, `test_availability.py:473–494`, plus a new success assertion); today: slot-only session formatted as a board row; WORKING_HOURS carries no evidence |
| Policy C-6 | Every step; no time → `TimeRequired` only after whole-scope refusals; mixed open Morning + unlabelled UNKNOWN with a Morning time → callback; open Morning + UNKNOWN afternoon without blocks, afternoon time → callback; **passed time inside an earlier blockless UNKNOWN window, another session open → `TIME_OUTSIDE_SESSION` with alternatives** (D-6 scope), labelled and unlabelled, bounded and unbounded (unbounded → callback); **matched open block beside a differently labelled blockless UNKNOWN with no start, no end, or neither → write** (D-7), today and future one-day, slots enabled and disabled; **stale labelled Morning (times erased) + Evening request → write**; unlabelled controls → callback; matched open block beside an unbounded `APPOINTMENT_REQUEST` or `NOT_AVAILABLE` row → unaffected; **named session beside a labelled UNKNOWN with unknown hours → follows the named session** (same as deployed); **future named Morning beside an unlabelled one-day UNKNOWN (empty and null label) → callback in availability and booking**, and the named-Morning control without UNKNOWN → write; selected session all full → `NO_OPEN_SLOT` with and without another open session; full block in a session with open blocks → `SLOT_FULL`; flag false with apparently open blocks → `NO_OPEN_SLOT`; named session not containing the time → `TIME_OUTSIDE_SESSION`; **a name plus a time in an unlabelled open block → `TIME_OUTSIDE_SESSION`, and the same with a real Morning row beside it**; a boundary time belongs to the next block; session-end time refused; legacy unknown-boundary cases unchanged; alternatives serialise through the real output models |
| Blank session | `AvailabilityRequest`, `BookingRequest` and MCP calls of both tools: `"   "` behaves like no session, today and future; non-string and over-long inputs still rejected; `make schema` unchanged |
| Policy C-8 (D-8) | Today, no slots: IN/LATE with both bounds → `APPOINTMENT_REQUEST`; IN/LATE missing an end, or ended → handoff. Today, slots: IN + open block → `APPOINTMENT_REQUEST`; IN with a usable window but all blocks full → `NO_OPEN_SLOT` (ordinary rule); IN with no usable window and no open block → handoff; **NOT_CONFIRMED with open blocks → handoff**; CANCELLED → `CANCELLED`; UNKNOWN, stale, no entry → handoff. Future: on-call fixture with usual hours and no slot evidence → handoff (usual hours are never a fact); one-day IN + open block → `APPOINTMENT_REQUEST`; one-day CANCELLED → `CANCELLED`; otherwise handoff. Department: IN with usable window → `SLOT_CHECK_REQUIRED`/match; IN missing bounds → handoff; future department with only on-call doctors → `HANDOFF_REQUIRED`, mixed regular/on-call with matches → only the matches are published (existing aggregate), on-call handoff not counted as bookable; without matches the handoff facts may be published; callback outranks handoff under a cap of 1 (S1). WORKING_HOURS on-call (by ID and by name) → handoff, no reads beyond today's. Booking (CREATE and RESCHEDULE): usable on-call session, time inside → `NOTED`; time outside → `TIME_OUTSIDE_SESSION`; usable Morning + unlabelled unresolved on-call row, bounded and unbounded, named and unnamed → `HANDOFF_REQUIRED`, no POST (B2). Read failure → `COULD_NOT_CHECK`/`COULD_NOT_RECORD`, not handoff |
| **Existing tests changed deliberately by D-8 (complete list, Astra R10 §4)** | `test_availability.py:116` (confirmed IN actionable; NOT_CONFIRMED → handoff, no callback metadata; rename); `:264` both parameters (WORKING_HOURS → handoff); `:518` (by-name board 500 → `COULD_NOT_CHECK`/`BOARD_UNAVAILABLE`; paths at `:523`; add a successful by-name control) **in 2b**; `test_availability_policy.py:106` both dates (today IN actionable; fix the future fixture so usual hours are not confirmation; add a WORKING_HOURS assertion); `:154` (use a genuinely unresolved regular fixture for the callback roll-up; add on-call handoff and usable on-call count cases); `test_booking.py:107` (10:45 outside the confirmed window → `TIME_OUTSIDE_SESSION`; add inside-window success and unresolved handoff cases; failed-profile part unchanged); `test_server.py:134` (snapshot, regenerated once); `test_server.py:142` (HTTP journey future on-call CREATE → `HANDOFF_REQUIRED`). Assertions are updated to the new outcome, never weakened or removed |
| Policy C-7 | Department: match + cancelled, match + UNKNOWN (incl. an unlabelled row), match + callback, selected vs unselected session, future matched vs wrong weekday, partial searches with and without matches, ranking/capping, WORKING_HOURS with slots enabled; `open_slots` is `null` for `SlotsNotRead`; **today, a supplied end time that has passed with `SlotsNotRead` → `SESSION_ENDED`, not a match** (P-1, policy and department service test, 4a) |
| Service (MCP, stubs) | CREATE/RESCHEDULE without time → `ASK_WHICH_TIME`, no POST; CREATE/RESCHEDULE with a name and a time in an unlabelled open block → no POST; future slot-only UNKNOWN with no blocks (usual schedule on another weekday) → callback, serialised with `oneDay true` and null hours; open block → `NOTED`, `slotTime`, `slotMoved false`; 10:45 → 10:30 block start, `slotMoved false`; owner moves the block → `slotMoved true`; owner omits `slotTime` → fallback, `slotMoved false`; definite `SLOT_FULL` → `NOT_AVAILABLE` with no alternatives; retry `SLOT_FULL` → `UNCERTAIN`; later same-operation invocation after our write filled the block → refused by the gate (D-3); `session` never in the owner body; slot inconsistency → no POST; LIST/CANCEL `slotMoved false`; B-1 bypass unchanged; **booking gate with `SlotsNotRead` facts → `COULD_NOT_RECORD`/`SLOTS_UNAVAILABLE`, no POST** (P-2, 3b) |
| Schema | `make schema` equals the snapshot, and the VOICE-TEAM checks pass, in **every** commit from 3a on, with an identical surface (fields, defaults, descriptions, enums) after 3a |

## 10. Phases and commits (each ≤10 files, each `make test-fast` green; hold every deployment until phase 5)

| # | Commit | Files (`src/` = `services/mcp/src/frontdesk_mcp/`, `tests/` = `services/mcp/tests/`) |
|---|---|---|
| 1a | Pin and contract validation | the two new `contracts/manoj-openapi-20261007*.yaml`, `contracts/README.md`, `src/contract.py` (ErrorCode), `tests/test_contract.py`, `tests/test_stubs.py`, root `README.md` (**7**) |
| 1b | Definite `SLOT_FULL` mapping | `src/booking.py`, `dev/frontdesk_stubs/ops.py`, `tests/test_booking.py`, VOICE-TEAM detail note, with **no** table change (**4**) |
| 2a | Typed transport and scripted fixtures | `src/contract.py`, `src/ops_client.py`, `dev/frontdesk_stubs/ops.py`, `tests/test_contract.py`, `tests/test_ops_client.py`, `tests/test_stubs.py` (**6**) |
| 2b | Selected-doctor retrieval facts, plan-level consistency checks and the B-6 detail helper; the policy still ignores evidence | `src/schedule_reader.py`, `src/availability_policy.py` (`DoctorFacts.slots`, `SlotsNotRead`, `is_match` = APPOINTMENT_REQUEST only for now), `src/availability.py`, `src/booking.py`, `tests/test_schedule_reader.py`, `tests/test_availability.py`, `tests/test_booking.py`, `tests/harness.py` only if a fixture needs it (**≤8**). Includes removing the ON_CALL early return for AVAILABILITY (the policy still decides ON_CALL as callback until 3a-2); `test_availability.py:518–523` changes here, outcome and paths (its injected board 500 now gives `COULD_NOT_CHECK`/`BOARD_UNAVAILABLE`). Not deployable |
| 3a-1 | **The complete final schema publication only**; no behaviour change | `src/availability_policy.py` (final `Decision`/`Reason` values, not yet produced), `src/outcomes.py` (all final output fields, defaults and descriptions, incl. booking fields, nullable one-day `start`/`end`, `openSlots`, `oneDay`), `src/prompt.py`, `tests/contracts/mcp-tools.snapshot.json`, `src/packs/healthcare.json`, VOICE-TEAM (**6**). Existing constructors keep working through the defaults; `test_server.py:134/409/442` pass against the final surface |
| 3a-2 | Availability policy (C-1 to C-5, C-7, C-8) and D-8 activation, including both booking handoff consumption points | `src/availability_policy.py`, `src/availability.py`, `src/outcomes.py` (formatting only), `tests/test_availability_policy.py`, `tests/test_availability.py`, `tests/test_booking.py`, `tests/test_server.py` (HTTP journey `:142`) (**7**). Schema unchanged |
| 3b | Remaining booking (C-6 steps 2, 3 and 5, D-2, D-3, the P-2 unread-slots guard) and the blank-session input type | `src/availability_policy.py`, `src/booking.py`, `src/availability.py` (`SessionChoice` on the request), `src/outcomes.py` (`SessionChoice` and formatting only: no output type, default or description change), `tests/test_availability_policy.py`, `tests/test_booking.py`, `tests/test_availability.py`, `tests/test_server.py` (**8**). `tools.py` unchanged. Schema unchanged |
| 4a | Department retrieval integration, and the P-1 ended-window guard for `SlotsNotRead` (C-3 step 3), with its first producer; the L-1 tidy-up | `src/schedule_reader.py` (capabilities, AVAILABILITY guard, `SlotsNotRead`, `CAPABILITIES_UNAVAILABLE` in the B-6 helper, one home for "stages that are always read failures"), `src/availability_policy.py` (P-1 and L-1 only), `src/availability.py` and `src/booking.py` (use that one stage rule instead of their two `!= "slots"` checks; no other change), `tests/test_schedule_reader.py`, `tests/test_availability_policy.py`, `tests/test_availability.py`, `tests/test_stubs.py` only if a stub test needs it (**≤8**) |
| T-1 | Test infrastructure (L-2): bound the HTTP test server's shutdown wait, so a stuck shutdown fails fast and visibly | `tests/conftest.py` (**1**). No production code |
| 4b | Operational consumers | `tests/test_external.py`, `tests/test_external_transport.py`, `dev/bench.py`, `tests/test_bench.py`, `dev/demo.py`, `tests/test_e2e_processes.py` (**≤6**) |
| 5 | Rules and documents | `CLAUDE.md`, `docs/DECISIONS.md`, `docs/handover/mcp-only/PLAN.md` (**3**) |

**3a-1 is "the first commit that changes the schema" (D-1).** Every "published in 3a" statement above means 3a-1; nothing after 3a-1 changes `make schema`.

**D-1 consequence, stated plainly:** from 3a to 4a the published schema describes the final surface before every behaviour is wired locally. This is staged publication on an unmerged series, **not** permission to deploy part of it. After every commit from 3a on, `make schema` output must be identical; if any commit would need a schema change, stop and report it; do not bump again silently.

## 11. Latency

| Path | v0.3 | With slots |
|---|---|---|
| Single doctor, today | profile ∥ board (or board) | + `/slots` in the same parallel step |
| Single doctor, future | profile (often cached) | profile ∥ `/slots` |
| Booking gate (CREATE) | as availability | as availability |
| RESCHEDULE | lookup → schedule reads → write | lookup → (schedule reads ∥ `/slots`) → write |
| Department | search ∥ board, or batched profiles | + cached `/capabilities` in the first parallel step (AVAILABILITY only); **no** `/slots` |
| Name lookup | directory search, then reads | unchanged order |
| On-call doctor by name, AVAILABILITY | directory search only (the old shortcut) | directory search, then **one added read group** (today board ∥ slots, future profile ∥ slots). Accepted exception (D-8, Garima 8 October); WORKING_HOURS keeps the shortcut |

Parallel does not mean free: connection-pool contention and the 0.30 s budget need the bench (section 8), including the on-call by-name path above.

**Latency rule for build briefs:** once the doctor is known, the slot read runs in the same parallel group as the other required doctor reads; no step exists only for slots. The on-call by-name group above is the only accepted added stage.

## 12. Alternatives considered and rejected

| Alternative | Why rejected |
|---|---|
| Start-up and background capability process (revisions 2–3) | Needs an owner, a lifecycle, staleness and failure rules; capability data on the hot path is unnecessary because `SlotPlan.enabled` arrives with each read (D-5) |
| A separate booking precedence matrix (revision 4) | Duplicated `decide_booking` and lost its protections for unlabelled and unbounded unresolved rows; made `SLOT_FULL` depend on other sessions (R4-B2) |
| CANCELLED outranks UNKNOWN (revision 4) | Breaks "UNKNOWN always means callback" (D-6) |
| An UNKNOWN session anywhere that day forces a callback for a passed or out-of-hours time (R5-B1b as written) | The time is not bookable whatever the desk says; a callback cannot change that. D-6 governs every session that could contain the time |
| Drop a one-day refusal row from the output (R5-B2) | The same `sessions` feed booking's time selection; hiding the row would lose its callback there. Null hours are honest; invented hours are not |
| A new `inputs.py` for the blank-session type | `outcomes.py` is already the shared MCP-surface module of both services; no new file is needed |
| Duplicate-label or overlap failures inside the policy | A pure policy cannot report a read failure honestly; the reader already rejects inconsistent owner data as `Malformed` |
| Rely on the owner alone (send the time, map 400/409) | The agent needs open slots before offering, and our invariants must hold before a write |
| Slots for every department doctor | One call per doctor; too slow for voice |
| Board-window ∩ blocks | Redundant (G-9) |
| A `slots_enabled` parameter | A flag parameter; facts belong in `DoctorFacts` |
| Option A: any UNKNOWN with unknown hours blocks every other session (revision 8) | Manoj erases the times of stale entries, so most afternoon bookings would become callbacks; six deployed behaviours would change (D-7) |
| A version bump per schema-changing commit | Several schema changes for the voice team; Garima chose one publication (D-1) |
| Forward `session` to Manoj | The write APIs do not accept it (D-2) |

## 13. Finding-to-fix map

| Source | Finding | Fixed in |
|---|---|---|
| Pre-flight B-1, Sol #1 | Capability lifecycle unspecified; "21 assertions" justification wrong | D-5: lifecycle removed (B-2, B-4); the request-log statement corrected (§9) |
| Pre-flight B-2 | Evidence variants and status conflicts | C-1, C-2 (D-6), C-3 |
| Pre-flight B-3 | `_combine`, `_future` selection | C-5, C-7 |
| Pre-flight B-4 | Booking precedence and alternative types | C-6 (existing flow extended) |
| Pre-flight B-5 | Presentation needs `now`; one-day sessions | `open_slots` from policy (C-1, C-3); D-4 one-day (C-5, E) |
| Pre-flight B-6, Sol #2 | Phasing breaks the schema checks | D-1; §6 defaults; §10 |
| Pre-flight S-1 | Incomplete 0.4.0 migration | A-1 |
| Pre-flight S-2 | Failure classes and data integrity | B-6, A-2 invariants, B-4 doctor/date and plan-level checks |
| Pre-flight S-3 | Gate return, `_written`, `slotMoved` edge cases, replay | D-2, D-3 |
| Pre-flight S-4 | External, bench, rollout | §8, §10 4b |
| Pre-flight N-1 to N-4 | Signature as data; stub fixtures; single-doctor `SlotsNotRead`; capability framework | C-3, A-4, C-7, D-5 |
| Sol #3 | Session selection | D-2 (C-6 steps 3 and 5) |
| Sol #4 | `slotMoved` meaning; D-1 "or" choice | D-3; C-7 decided (`COULD_NOT_CHECK`) |
| **R4-B1** | CANCELLED vs UNKNOWN conflict | D-6; C-2 order `UNKNOWN > CANCELLED > …`; §9 both orderings |
| **R4-B2.1–2** | `SLOT_FULL` depended on other sessions; refinement overrode the session flag | C-3 one meaning per reason; refinement step deleted |
| **R4-B2.3–4** | Unlabelled or blockless UNKNOWN lost after a time was given | C-6 keeps the existing time selection; only `_contains_time` dispatches on blocks |
| **R4-B2.5** | Non-unique time-selected session; blank session | A-2 plan-level checks (G-14); C-6 blank-session input type |
| **R4-B3** | `_future` filtered reasons away; one-day refusal facts erased | C-5 facts vs alternatives; `_future` restructured like `_today` |
| **R4-S1** | Failure helper could flatten existing outcomes; duplicate-join propagation | B-6 detail-only helper, new stages only, pinned anchors listed; duplicates are reader `Malformed` |
| **R4-S2** | WORKING_HOURS guard; cache is not single-flight | B-2, B-5 |
| **R4-S3** | Unread vs checked-empty; legacy ended-window guard | C-1 table; C-3 steps 2 and 5 |
| **R4-S4** | Nullable is not optional; descriptions in the snapshot | §6 defaults and descriptions |
| R4 §1 | Line 523 described as an ambiguous name | §9 corrected |
| **R5-B1a** | A name could book through an unlabelled open block | D-2 wording; C-6 step 5 label check; §9 no-write tests |
| **R5-B1b** | Passed-time refusal before a blockless UNKNOWN row | D-6 scope stated; C-6 step 3; §9 tests pin the intended result |
| **R5-B2** | One-day refusal row without hours could not be formatted; today's one-day marker | C-5; §6 nullable `start`/`end`; board rows need no new field |
| **R5-S1** | Owner `SLOT_FULL` does not prove other times are open | §6 VOICE wording; §9 no alternatives |
| **R5-S2** | Legacy future output rows; `NO_USUAL_SCHEDULE` wording | C-5 output rows; §9 |
| **R5-S3** | Home of the blank-session type | C-6 note (`outcomes.py`, `tools.py` unchanged); §10 3b; §9 |
| **R6-B1** | A labelled UNKNOWN with unknown hours was dropped when another session matched the time | Closed by D-7: its label rules it out; with slots Manoj cannot book into a blockless session |
| R6 §3 | One-day metadata and nullable-but-required hours | §6 `UsualSessionOut` row |
| **R7-B1** | Future named scope dropped an unlabelled one-day UNKNOWN | C-5: `_future` named scope keeps unlabelled `CALLBACK_REQUIRED` rows; §9 |
| **R7-S1** | One existing test asserts the old behaviour | Superseded by D-7: no deployed behaviour changes |
| **R8** | Strict rule changes six deployed behaviours (stale entries lose their times) | D-7 (option B); C-5; C-6 step 3; §9 |
| **Garima, on-call** | Manoj's contract allows a confirmed on-call entry; unconfirmed should be a human handoff | D-8; C-8; B-4 early return; §6; §7; §9; §10 2b/3a |
| **R10-B1** | On-call rule read a decision that had lost status and usability | C-8 fact 2: `on_call(s, now)` over the session's status, window and evidence |
| **R10-B2** | Handoff not consumed after time selection | C-6 step 4; §9 no-write tests |
| **R10-B3** | Unread on-call profile treated as a read failure | C-8 fact 1: usual schedule never a fact for on-call |
| **R10-S1** | Equal rank hid callback doctors under a cap | C-7 `rank` order |
| R10 §4–6 | Test inventory, phase split, document lines | §9 list; §10 3a-1/3a-2; §6, §7 |
| **3a-2 review P-1** | A department search listed a doctor whose supplied end time had passed as matched | C-3 step 3 end-time guard; §9 C-7; §10 4a |
| **3a-2 review P-2** | Booking policy would write on an unread-slots decision (unreachable) | C-6 note: gate refuses `SlotsNotRead`; §9 Service; §10 3b |
| **3b review L-1** | "Is it today" decided from the slot plan date in C-6 step 5 | §10 4a (use the decision's basis) |
| **3b review L-2** | HTTP test server shutdown can hang the run (pre-existing, not reproduced) | §10 T-1 |
| **3b review O-1** | Unlabelled refusal rows decide bookings (approved D-7) | G-15 owner question |
| Revision 3 audit A-1 to A-15 | Earlier self- and Luna findings | Retained; A-1's capability design replaced by D-5 |

**Remaining owner questions:** G-13, G-14, G-15 (all designed around). **Status:** phases 1a to 3b built and reviewed; schema frozen at `2026-10-08.1` (snapshot SHA-256 `3ef91e78…6c62`). **Next:** phase 4a, then T-1.
