# Opus impact review and revised plan: Operations API 0.4.0 slots, revision 2 (7 October 2026)

**Status:** plan only. Nothing is implemented. Revision 2 replaces revision 1 using Manoj's answers relayed by Garima on 7 October 2026.

**Sources:**
- served `openapi.yaml` (labelled `0.4.0-draft`) and `versions/openapi-0.3.0.yaml`;
- live `/openapi.json`;
- the pinned `manoj-openapi-20260930.yaml`;
- code at `1132666`.

The served 0.3.0 equals our pin except for the server URL. The 0.4.0 file still contains the unquoted-description YAML defect in `Error.message` that our test overlay works around.

## 1. Confirmed facts (Manoj) and product decisions (Garima)

| # | Confirmed |
|---|---|
| G-1 | **With a time:**<ul><li>the block containing that time is checked;</li><li>free → created, with `slotTime`;</li><li>full → `409 SLOT_FULL`, nothing created;</li><li>no automatic move, **except** when the doctor is late and the requested block has passed: then the next open block in the same session is used and returned in `slotTime`.</li></ul>A time in a CANCELLED or UNKNOWN session, or outside the doctor's sessions, → `400`, nothing created.<br>**Without a time:** the earliest block of the day with capacity; whole day full → `409 SLOT_FULL` |
| G-2 | RESCHEDULE does the same block check on the new date. Full → `409 SLOT_FULL`, and the original appointment stays unchanged |
| G-3 | `NOT_CONFIRMED` = the desk has not updated that date, so the usual schedule applies. If the slots response says bookable, the request is accepted as `NOTED`. `UNKNOWN` and `CANCELLED` are never bookable |
| G-5 | Jayashree enables `SESSION` and `TIME_WINDOW`. `mode` never overrides `status`; it only says which time fields to expect and how to present them |
| G-6 (dates) | `/slots` supports future dates: generated from the usual schedule, reduced by existing appointments, with desk records (for example leave) applied on top. `/availability` follows the same future-date rule |
| G-4 (answered 7 Oct) | **Today:** any block whose end time has passed returns `bookable: false`. **A request for a passed time goes to the next open block.** Other dates are not affected by the current clock |
| G-9 (answered 7 Oct) | **IN or LATE with TIME_WINDOW:** blocks **before** the window are returned `bookable: false`; blocks **after** the window are **not returned**. **NOT_CONFIRMED:** the full usual session applies |
| G-10 (answered 7 Oct) | Future sessions normally return `NOT_CONFIRMED` and bookable. If the desk marks the doctor **CANCELLED**, that session becomes unbookable and booking returns **400**. Other sessions that day remain usable |
| Endpoint use | For a selected doctor's booking decision, `/availability/{doctorId}/slots` is sufficient (it carries session status and capacity). `/availability` is needed only for presentation details (expected time, end time, delay, note). Both read the same board |

| Product decision (Garima, for MCP2) |
|---|
| Collect the **selected session and a slot time from the slots response** before CREATE or RESCHEDULE. Never submit a slot-enabled booking without a time |
| `NOT_CONFIRMED` with a bookable block and capacity → allow a `NOTED` request; the agent says "noted, the desk will confirm", never "confirmed". **Not** a global remap of NOT_CONFIRMED |
| `UNKNOWN` → no booking; collect name and callback number; `record_call_summary` with `CALLBACK_NOTED` (unchanged) |
| `CANCELLED` → no booking; offer another session, doctor or date (unchanged) |
| No slot reads across a department search: resolve or choose the doctor first, then read that doctor's slots |

**Update, 7 October 2026 (Garima):** **G-8 answered: 0.4.0 is stable.** K-4 is unblocked: pin the served 0.4.0 file by hash (with a quoting overlay for the remaining YAML defect).

**Live read-only access check (Opus, 7 October 2026, 13:09 IST, with Garima's approval).** Our canary's machine client (Key Vault `ops-client-id`/`ops-client-secret`) was used. Reads only; no secrets printed or stored.

| Call | Result |
|---|---|
| `POST /auth/token` | 200 (no `scope` returned in the token response) |
| `GET /capabilities` | **200**: `supportedModes [SESSION, TIME_WINDOW]`, `defaultMode SESSION`, `stalenessThresholdHours 4`, `slots.enabled true`, `blockMinutes 30`, `verification MOBILE_MATCH`, `confirmation DESK_ONLY` |
| `GET /availability/{id}/slots?date=today` | **200** |
| `GET /availability/{id}/slots?date=<future working day>` | **200** |
| `GET /availability?doctorId=…&date=<future>` | 200: pre-filled usual sessions, `NOT_CONFIRMED`, `mode SESSION`, `remainingCapacity`/`totalCapacity` null |

**Access is confirmed.**

Observations to carry into the design:

- **O-1, future slots:** sessions carry `status NOT_CONFIRMED`, `bookable true`, blocks of 30 minutes with `capacity 5` (`patientsPerHour` is null on these doctors, so 5 is the owner's default). Consistent with Manoj's G-10 answer (future default NOT_CONFIRMED and bookable; a desk CANCELLED makes that session unbookable).
Raw captures (re-run at 14:35 IST at Garima's request, because the 13:09 run printed only an extracted summary and did not log the doctor ID) are in `evidence/manoj-slots-live-20261007.txt`:

| Capture | doctorId | Date | Shape |
|---|---|---|---|
| 1 | `a540cc21-8b1a-43e3-8296-43d5fe156278` (the first REGULAR doctor in `GET /doctors?limit=25`, the same selection as the 13:09 run) | `today` → `2026-10-07` | **No usual schedule.** One desk board entry (`session null`, IN, 10:30–12:00, source DESK) defines the window. Slots: one session `session: ""`, `status IN`, **`bookable true`**, 3 blocks, **all `bookable false, available 0, booked 0`** |
| 2 | `62476883-f54e-4a3a-878f-81782f48f6d7` | `today` → `2026-10-07` | Usual Morning 10:30–12:00 and Evening 18:30–19:30. Morning: `NOT_CONFIRMED`, **`bookable true`**, 3 blocks **all `bookable false, available 0`**. Evening: `NOT_CONFIRMED`, `bookable true`, 2 blocks `bookable true, available 5` |

- **O-2, ended blocks (now confirmed by Manoj's G-4 answer):** in both captures every block that had ended (12:00 < 14:35) was `bookable false, available 0` with `booked 0`, so the blocks were closed by time, not capacity. (At 13:09, capture 1's first block showed `booked 4`; at 14:35, `booked 0`. Booked counts change as appointments change.)
- **O-3, session-level `bookable` is not enough (reproduced on both a no-schedule and a usual-schedule doctor):** a session reports `bookable true` while every block in it is `bookable false`. The session flag appears to reflect the session's status only. The policy must decide from blocks (any block `bookable` with `available > 0`), never from the session flag alone. Ask Manoj to confirm the intended meaning (G-12).
- **O-4, empty session label explained:** capture 1's `session: ""` corresponds to a board entry with `session: null` for a doctor with no usual schedule. Our matching treats a blank label as unlabelled; confirm that `""` is the slots encoding of "no label" (G-11).
- **O-5:** capacity numbers appear only on `/slots`, never on the board (`remainingCapacity` null), consistent with "use `/slots` for booking decisions".

**Resolved since revision 2:**
- G-4, G-9 and G-10 (Manoj);
- access (live check);
- G-8 (0.4.0 stable);
- the late-doctor move (Garima, K-7: accept it and always return the actual `slotTime`).

**Still open (Manoj):**
- **G-11:** does an empty label (`""`) mean "no label"?
- **G-12:** is session-level `bookable` only the status, with blocks authoritative?
- **G-13:** does a time exactly at the session end map to its last block?

**Implications of the G-4, G-9 and G-10 answers (for `SLOTS-PLAN.md`):**

| # | Implication |
|---|---|
| P-1 | **G-4 widens the automatic move.** Manoj moves **any** request for a passed time today to the next open block, not only when the doctor is late (G-1 described only the late case). Our policy refuses a time in an ended block before writing, so in practice the owner's move happens only in a race (the block ends between our check and the write) or for a late doctor. Either way K-7 applies: accept it and return the actual `slotTime` with `slotMoved`. The voice contract should say that the time can move for **either** reason |
| P-2 | **G-4 makes our "block has not ended" check a guard, not the source of truth.** Keep it (K-2): it stops us from asking the owner for a time the caller should not have been offered, and it keeps our answer and the owner's in step. Future dates: no clock check, matching Manoj |
| P-3 | **G-9 means the slot data already reflects a TIME_WINDOW.** Blocks before the window come back closed, and blocks after it are absent. The planned "board window **and** slot block" intersection (`SLOTS-PLAN.md` C-2) is therefore redundant. It can be dropped in favour of **blocks only**, which removes a rule rather than adding one |
| P-4 | **G-9 for NOT_CONFIRMED:** the full usual session applies, so the slots for an unconfirmed session cover the usual hours. This is consistent with C-1 (NOT_CONFIRMED with open blocks → note the request; the desk confirms) |
| P-5 | **G-10:** a future CANCELLED session is unbookable and booking returns 400, while other sessions that day stay usable. This is consistent with C-1/C-4 (session-level CANCELLED → `NOT_AVAILABLE`; the other sessions are decided independently). Our gate refuses before the owner's 400, so the 400 should stay unreachable in normal use |

## 2. Impact on the current code (unchanged from revision 1, now confirmed)

- **I-1 (live now):** `contract.ErrorCode` (`contract.py:30`) is a strict literal list, so a `409 SLOT_FULL` parses as `Rejected(409, None)` and `manage_booking` returns `REJECTED`/`ASK_TO_CORRECT`/`REJECTED`. Reproduced.
- **I-2 (live now):** a session-only CREATE sends no `expectedTime`, so Manoj books the earliest free block of the **day**, possibly in the wrong session.
- **I-3:** today, a NOT_CONFIRMED session is a callback in our policy (`TODAY_STATUS`, `availability_policy.py:168`), while Manoj accepts a booking if its block is bookable. Pre-fill makes every unconfirmed usual session NOT_CONFIRMED, so without a change the agent can book today only after the desk confirms.
- **I-4:** the response `expectedTime` is the block start (`slotTime`). Our `AppointmentOut.expectedTime` already passes it through, so no new output field is needed to tell the caller the block start.
- New fields (`mode`, capacity fields, `availabilityMode`, `slotTime`) parse safely because models use `extra="allow"`.

## 3. Contradictions found against the current code and rules

**Decided by Garima on 7 October 2026:**
- K-1, K-2, K-6, K-7 and K-8 as recommended;
- K-3 as "matches the department request; slots checked after selection", never "available";
- K-7 with the actual `slotTime` always returned.

The implementation plan is `SLOTS-PLAN.md`.

| # | Contradiction | Needs |
|---|---|---|
| K-1 | **`CLAUDE.md` rules conflict with the decisions:**<ul><li>"No … slot, capacity … logic";</li><li>"Today UNKNOWN/NOT_CONFIRMED require callback";</li><li>"future dates … never read the board".</li></ul>With slots, we consume owner-computed capacity (we compute none), NOT_CONFIRMED can be bookable, and future slot reads include desk records | Garima to approve the rewording: "MCP consumes owner capacity facts; it never computes capacity". Rules updated in the same change |
| K-2 | **B-2 (strict "time ≥ now") vs block semantics.** With slots, the time sent is a **block start**. During the current block (10:30–11:00 at 10:40) its start is already past, so B-2 would refuse the only open block. The rule must become "the block has not ended" | **Decided (K-2).** G-4 confirms that the owner closes ended blocks, so our check is a guard (P-2) |
| K-3 | **Department view vs doctor view.** Department search stays session-level (no slots), so a NOT_CONFIRMED doctor shows as callback there but bookable after the doctor is selected. The two answers about the same doctor disagree | Decision: in slot-enabled facilities, should department results treat IN/LATE/NOT_CONFIRMED sessions as "check slots after choosing" rather than callback? (affects `aggregate`, counts and outcome wording) |
| K-4 | **C-1 is blocked by contract pinning.** Adding `SLOT_FULL` to `contract.ErrorCode` fails `test_contract.py`, which pins our literals to the 0.3.0 snapshot. So C-1 needs a 0.4.0 pin, and pinning waits on G-8. Precedent: we pinned `0.3.0-draft` by **hash** ("the draft version alone does not identify a revision; pin the hash") | **Resolved 7 Oct:** G-8 answered (0.4.0 stable), so pin the served 0.4.0 file by hash with a new quoting overlay |
| K-5 | **TIME_WINDOW with slots.** For a doctor with a usual schedule whose desk entry narrows the window (`expectedTime`/`expectedEndTime`), the spec only says a board entry defines the window when there is **no** usual schedule. Do blocks outside a narrowed window become non-bookable? If not, the board window and slot bookability can disagree | **Resolved by G-9:** blocks before the window are closed and blocks after it are not returned, so slots already reflect the window (P-3) |
| K-6 | **B-3 was "leave it, instruction only".** The G-7 decision now requires the tool to refuse slot-enabled writes without a time. That reverses the earlier "no tool change" | Garima's confirmation (implied by the MCP2 decision) |
| K-7 | **Late-doctor move vs our time check.** We validate the caller's chosen block before writing; the owner may still return a later `slotTime`. The response time can differ from what the caller agreed | Open product decision. The plan only guarantees that the actual time is surfaced |
| K-8 | **Capability read failure** (403 if scopes are missing, or a timeout). Whether the tool falls back to the v0.3 session path or refuses to book is undefined | Access is now verified (both endpoints 200), so this is only about runtime failures (timeout, 5xx, a later scope change). Decision still needed |
| K-9 | **Documentation drift.** `contracts/README.md` and `PLAN.md` say "there is no slot endpoint"; `VOICE-TEAM.md` describes NOT_CONFIRMED as callback-only | Updated with the change |

## 4. Revised plan, by layer

Each layer owns one concern. Slot awareness enters as **facts** (transport → retrieval) and is decided once (policy). Services compose; presentation only formats. No condition is bolted onto the v0.3 path: the v0.3 path is the same policy with no capacity evidence.

### Layer A: transport (`contract.py`, `ops_client.py`, contract files, stubs)

- **A-1:** `contract.ErrorCode` gains `SLOT_FULL` and `UNSUPPORTED_CAPABILITY`. *(Blocked by K-4.)*
- **A-2:** new types mirroring the 0.4.0 schemas we use: `Capabilities`, `SlotPlan`, `SlotSession`, `SlotBlock`. Only fields we read are typed; extras are allowed.
- **A-3:** `OpsClient.get_capabilities()` and `OpsClient.get_slots(doctor_id, date)`: read paths with the existing deadline, 401 refresh and error mapping. No new retry rules.
- **A-4:** re-pin and overlay per K-4. Update the `test_contract.py` hashes and literal checks. Update `dev/frontdesk_stubs` to model pre-fill, `/capabilities`, `/slots`, `SLOT_FULL` and the 400 for a cancelled or unknown session (fixtures, not engines).

### Layer B: retrieval (`schedule_reader.py`)

- **B-1:** read capabilities once and cache them with the existing `DirectoryCache` pattern (TTL from settings). Failure behaviour per K-8.
- **B-2:** `DoctorFacts` (`availability_policy.py:70`) gains `slots: SlotPlan | None`. `ScheduleReader.doctor` (`schedule_reader.py:71`) reads slots for a **single doctor** when the facility enables them, **in parallel** with the reads it already makes. Today: profile (cached) + board + slots. Future: profile (cached) + slots. One sequential round trip, as now. Slots are never cached (capacity changes).
- **B-3:** `ScheduleReader.department` (`:98`) is unchanged. No slot reads in department searches.

### Layer C: policy (`availability_policy.py`, the only place decisions are made)

- **C-1, session decision from status plus capacity evidence (the rule's home):**
  - Replace the `TODAY_STATUS` lookup (`:168`) with one function: `(owner status, capacity evidence or None) → (decision, reason)`.
  - With **no** capacity evidence (slots disabled), it returns exactly today's table, so the v0.3 behaviour is unchanged.
  - With evidence:
    - IN/LATE/NOT_CONFIRMED and a bookable block with seats → `APPOINTMENT_REQUEST`;
    - seats exhausted → `NOT_AVAILABLE` with a new reason (for example `SESSION_FULL`);
    - UNKNOWN → `CALLBACK_REQUIRED`;
    - CANCELLED → `NOT_AVAILABLE`.
  - ON_CALL stays a callback before any of this (`decide_doctor`, `:253`).
- **C-2, future dates:**
  - When slot facts are present, `_future` (`:235`) builds sessions from the slot plan (which already applies desk records such as leave) instead of the bare usual schedule.
  - The same C-1 function decides each session. Without slots, today's usual-schedule logic is unchanged. *(Needs K-1 approval.)*
- **C-3, booking:**
  - With slots, `decide_booking` (`:281`) validates the chosen time against **blocks**: the block containing the time must exist, belong to the selected session, be bookable and have `available > 0`.
  - `_contains_time` (`:272`) becomes the single block or window membership rule. The today guard changes from "start ≥ now" to "block not ended" *(K-2, G-4)*.
  - Without slots, the current session-window logic is unchanged.
  - `SessionRequired`, `TIME_NOT_VERIFIABLE` and the whole-scope precedence (N-2) keep their meaning.
- **C-4, time required:** with slots enabled, a write without a time is a policy outcome (refused with the session's open blocks as choices), not a transport error. *(K-6.)*
- **C-5, department:** `aggregate` (`:328`) changes only if Garima decides K-3.
- **C-6:** `working_hours` is unchanged (usual hours, never capacity).

### Layer D: services (`availability.py`, `booking.py`)

- **D-1, availability (single doctor):** pass the slot facts to the policy and the open blocks to presentation. Department path unchanged.
- **D-2, booking gate** (`_schedule_gate`, `booking.py:227`; `_reschedule_gate`, `:304`): uses the same reader and policy. No separate slot check in the service.
- **D-3, `_failure`** (`booking.py:147`): `SLOT_FULL` → `NOT_AVAILABLE` / `OFFER_OTHER_SESSION_OR_TIME`, `detail: "SLOT_FULL"`. If the gate's slot read is available in the invocation, its other open blocks become `sessions` alternatives. The owner's `400` for a cancelled or unknown session stays `REJECTED` (our gate should prevent it).
- **D-4, late-doctor move:** compare the returned `expectedTime` with the requested one and expose that it changed. Whether to accept it stays open *(K-7)*.

### Layer E: presentation and the voice contract (`outcomes.py`, pack text, schema, VOICE-TEAM)

- **E-1:** `BoardSessionOut` / `UsualSessionOut` (`outcomes.py:38`, `:48`) gain a compact `openSlots: [{start, end, available}]` (bookable blocks with seats only, to keep voice payloads small). Present only when the facility enables slots.
- **E-2:** a new reason (`SESSION_FULL`) and the `SLOT_FULL` detail value; a "time changed" indicator per D-4. **Schema change → `SCHEMA_VERSION` bump** and VOICE-TEAM change notes.
- **E-3:** voice wording facts in descriptions and VOICE-TEAM:
  - `NOTED` with owner status `NOT_CONFIRMED` means "noted; the desk will confirm";
  - tell the caller the returned `expectedTime` (block start);
  - choose a time from `openSlots`.
- Presentation formats; it decides nothing.

### Layer F: rules and documents

- `CLAUDE.md` (K-1), `DECISIONS.md`, `contracts/README.md`, `PLAN.md` (K-9), VOICE-TEAM.

## 5. Phasing

| Phase | Content | Depends on |
|---|---|---|
| 0 | Decisions K-1 to K-8 and the answers to G-4, G-8, G-9, G-10 and access: **done 7 Oct**. Remaining: G-11, G-12, G-13 (designed around) | Manoj |
| 1 | A-1, A-4 (pin) and D-3: `SLOT_FULL` handled meaningfully. Small, fixes a live defect | K-4 |
| 2 | A-2, A-3, B-1, B-2; C-1 to C-4; D-1, D-2, D-4: slot facts and slot-aware policy for single-doctor availability and booking | Phase 1 |
| 3 | E-1 to E-3, F; C-5 if decided: voice contract, schema bump, documents | Phase 2, K-3 |

## 6. Latency

- Single doctor today: the slots read runs in parallel with the board read; future: in parallel with the cached profile. No extra sequential round trip.
- Booking gate: the same reads.
- Department search: unchanged.
- One new start-up or cached read (`/capabilities`).

## 7. Questions to send Manoj

| # | Question |
|---|---|
| G-4 | **Answered 7 Oct:** see section 1 |
| Access | Do our machine-client scopes permit `GET /capabilities` and `GET /availability/{doctorId}/slots`? |
| G-8 | Is the served `0.4.0-draft` the stable 0.4.0 contract (so we can pin it by hash)? Will the `Error.message` YAML defect be fixed? |
| G-9 | **Answered 7 Oct:** see section 1 |
| G-10 | **Answered 7 Oct:** see section 1 |
| G-13 | Does a time exactly at a session's end (for example 12:00 for 10:30–12:00) map to its last block? |
| G-11 | Does `session: ""` (empty string) on `/slots` mean "no session label", the same as an absent label on `/availability`? (O-4) |
| G-12 | A session can report `bookable: true` while all its blocks are `bookable: false` (O-3). Is session-level `bookable` meant to reflect the day's status only, with blocks authoritative for capacity and time? |
