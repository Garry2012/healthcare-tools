# Opus review: get_doctor_availability (892e537..228f0a0), 5 October 2026

**Scope:**
- `get_doctor_availability` and everything it depends on:
  - `tools.py` and `AvailabilityRequest`;
  - `availability.py`, `availability_policy.py`, `schedule_reader.py`;
  - `config.py`, the cache and clock, and the ops client paths it uses;
  - `outcomes.py`, `prompt.py` and `packs/healthcare.json`;
  - the snapshot and `VOICE-TEAM.md`;
  - fixtures, tests, the bench and the read-only smoke.
- Booking only where shared code could regress it.

**Authority:** revision 6 of `AVAILABILITY-POLICY-PLAN.md`, plus `astra-revision-6-update.md`. Approved decisions are not reopened.

**Method:** I read the code, not the hand-back. The policy was probed directly with scratch scripts outside the repository. Tests were run locally against the in-repo stubs only. No real services, credentials, edits, commits or deployments.

Tree at review: HEAD `228f0a0`; only untracked `temp/` (preserved).

## Verdict

The tool is well built and largely follows revision 6:
- one pure policy;
- one shared reader;
- today reads only the live board and future dates never do;
- on-call is always callback;
- deterministic name ordering and bounded batches;
- the owner `status` and MCP `decision` are separate;
- `totalMatches`, `bookableFound` and `complete` carry distinct meanings;
- no knowledge calls, no writes.

I found **one important defect**: on a future date, asking for a session that isn't usual that day marks the doctor's real sessions on that day as "not available", which gives the caller wrong facts.

The overnight-session issue (I-2) is downgraded to minor, because Garima confirmed on 6 October 2026 that **overnight sessions are currently unsupported**.

There is also **one plan gap** to decide (D4 vs R6-2: an ended or cancelled session forcing a session choice), and seven minor items.

**Counts:** Critical 0 · Important 1 · Minor 8 · Plan gap needing a decision 1 · External acceptance gaps 2.

---

## Important defects

### I-1. Future `SESSION_NOT_USUAL` reports the doctor's same-day sessions as not available

- **Where:** `availability_policy.py:240-244` (`_future`); surfaced by `availability.py:39-48` (`doctor_out` emits `d.sessions`, never `alternatives`).
- **Trigger:**
  - The doctor's usual schedule is Morning MON 09:00–12:00 and Evening TUE 17:00–19:00.
  - The caller asks `{"date": "<a Monday>", "doctorId": …, "session": "Evening"}`.
- **Actual (reproduced):**
  - doctor `decision = NOT_AVAILABLE`, `reason = SESSION_NOT_USUAL`;
  - `usualSessions` = **Morning: NOT_AVAILABLE/SESSION_NOT_USUAL** (with `onRequestedDate = true`) and Evening: NOT_AVAILABLE/SESSION_NOT_USUAL;
  - nextStep `OFFER_OTHER_SESSION_OR_DATE`.
- **Expected:**
  - the doctor result `NOT_AVAILABLE`/`SESSION_NOT_USUAL` is correct;
  - but Monday Morning is a usual session that day and should be reported as `APPOINTMENT_REQUEST` (normal hours, not confirmed), so the agent can offer it;
  - only the requested Evening should be `NOT_AVAILABLE`/`SESSION_NOT_USUAL`;
  - other-day sessions should be `NOT_AVAILABLE`/`NOT_USUAL_DAY` with `onRequestedDate = false`.
- **Impact:** the agent is told the doctor has nothing that day, says "not available Monday", and may push the caller to another date, when Monday morning is the usual session. The `onRequestedDate = true` + `NOT_AVAILABLE` pair is self-contradictory. `sessionMatched` (`availability.py:154-155`) also becomes `true`, because a Tuesday "Evening" label matched.
- **Fix:** in `_future`, decide **each usual session independently**:
  - on the requested weekday and matching the named session (or none named) → `APPOINTMENT_REQUEST`;
  - on the weekday but not the named session → `APPOINTMENT_REQUEST` (shown as an alternative);
  - not on the weekday → `NOT_AVAILABLE`/`NOT_USUAL_DAY`.

  The doctor-level decision stays as it is now. Compute `sessionMatched` only against sessions on the requested weekday.
- **Regression test:** a policy test plus an HTTP test for the trigger above:
  - Monday Morning has decision `APPOINTMENT_REQUEST` and `onRequestedDate = true`;
  - Tuesday Evening has `NOT_AVAILABLE`/`NOT_USUAL_DAY`;
  - the doctor has `NOT_AVAILABLE`/`SESSION_NOT_USUAL`;
  - `sessionMatched` is `false`.

  The existing test `test_availability_policy.py:121` asserts only the reason, which is why this passed.

### I-2. Overnight board sessions: **downgraded to Minor** (out of scope)

Garima confirmed on 6 October 2026: overnight sessions are currently unsupported. This is therefore not a defect in scope. The remaining recommendation:
- record "overnight sessions are unsupported" in DECISIONS and VOICE-TEAM as a known limitation;
- optionally, a defensive guard in `_window` that treats `expectedEndTime < expectedTime` as an unreliable end (`UNKNOWN_END`), so unexpected data can never produce a false `SESSION_ENDED`.

The original analysis follows for reference.

- **Where:** `availability_policy.py:177-182` (`_window`), used at `:209`; also the window checks in `decide_booking` (`:279`, `:301`).
- **Trigger:** today's board row `IN`, `expectedTime = "22:00"`, `expectedEndTime = "02:00"` (a night session; the contract's `ApproxTime` allows it, and nothing requires `end > start`).
- **Actual (reproduced):**
  - at 21:00 facility time, and again at 23:00, the session is `NOT_AVAILABLE`/`SESSION_ENDED`, because `now.time() > 02:00`;
  - a booking for 23:30 gives `NOT_AVAILABLE`/`TIME_OUTSIDE_SESSION` with no alternatives.
- **Expected:** a session can't be called ended on a comparison that ignores midnight. The approved rule is "ended only when a supplied end time has passed" and "do not guess".
- **Impact:** a doctor confirmed `IN` for the night session is reported as finished, and night appointment requests are refused. This only matters if the hospital publishes sessions that cross midnight; there's no fixture for one.
- **Smallest coherent fix:** inside `_window` (the one place end times are interpreted), treat `expectedEndTime < expectedTime` as an end time that **cannot be compared reliably**. Return `UNKNOWN_END`, so the session is never `SESSION_ENDED`, and a specific requested time goes to the existing `HANDOFF_REQUIRED`/`TIME_NOT_VERIFIABLE` path.
  - This invents no overnight semantics.
  - Owner clarification on overnight sessions can refine it later (external gap E-3).
- **Regression test:** the row above at 21:00 and at 23:00 gives `APPOINTMENT_REQUEST` (not ended); a booking at 23:30 gives `HANDOFF_REQUIRED`/`TIME_NOT_VERIFIABLE`, with zero writes.

---

## Plan gap needing Garima's decision (not a code defect)

### G-1. An ended or cancelled session forces a "which session?" choice (D4 vs R6-2)

- **Where:** `availability_policy.py:185-196` (`_combine`), `:288-290` (`decide_booking` → `SessionRequired`).
- **Trigger:** today at 13:00 with Morning `IN` 09:00–12:00 (ended) and Evening `IN` 17:00 (no end), and no session named. The same applies to Morning `CANCELLED` + Evening `IN`.
- **Actual (reproduced):**
  - availability: `decision = APPOINTMENT_REQUEST`, `sessionChoiceRequired = true`, nextStep `ASK_WHICH_SESSION`;
  - booking without a session: `INVALID_REQUEST`/`SESSION_REQUIRED`, listing the ended Morning as a choice.
- **Why it's a gap:**
  - R6-2 says a choice is required whenever in-scope sessions have **different decisions**, and the code follows it literally.
  - D4 (Garima) is about one session available and another **unknown or unconfirmed**: callback only if the caller picks the unresolved one.
  - A `NOT_AVAILABLE` session (cancelled or ended) can't be chosen, so asking the caller to choose adds a turn and offers a non-option.
- **Recommendation:**
  - require a choice only when bookable **and** `CALLBACK_REQUIRED` sessions coexist;
  - `NOT_AVAILABLE` sessions are reported but never force a choice;
  - a booking with no session or time lands in the bookable session(s).
- **Tests if approved:** Morning `CANCELLED` + Evening `IN` → `OFFER_APPOINTMENT_REQUEST`, booking `NOTED`. The plan's §6 listed this case, but **no test exists for it**.

---

## Minor findings

| # | Where | Finding | Fix |
|---|---|---|---|
| M-1 (owner rule reconfirmed 6 Oct: on-call always gets callback) | `availability.py:142-145`, `availability_policy.py:257-265` | `WORKING_HOURS` for an on-call doctor or an empty schedule returns `decision = CALLBACK_REQUIRED` and nextStep `ASK_CALLBACK_DETAILS`, but **no `callback` object** (`_single` adds it only when `outcome == "CALLBACK_REQUIRED"`). A doctor with hours gets nextStep `OFFER_APPOINTMENT_REQUEST` and `bookableFound = 1`, although no date was checked. The agent gets an inconsistent signal (collect callback, but no `summaryOutcome`), and "offer appointment" from a non-availability answer | **On-call (required by Garima's rule):** a single-doctor `WORKING_HOURS` question about an on-call doctor must use the callback flow: `outcome = CALLBACK_REQUIRED`, nextStep `ASK_CALLBACK_DETAILS`, `callback = {reason: ON_CALL_DOCTOR, summaryOutcome: CALLBACK_NOTED}` (the same as availability). **Others:** an empty schedule follows the same callback shape; a doctor with hours gets a neutral nextStep, not `OFFER_APPOINTMENT_REQUEST`; don't count working hours in `bookableFound`. Tests: on-call `WORKING_HOURS` by id and by name → `CALLBACK_REQUIRED` with a callback object |
| M-2 | `schedule_reader.py:83-84` | Today's doctor-by-name path reads the board even when `summary.attendanceType == "ON_CALL"`, whose answer is fixed. That's an avoidable owner round trip on a 0.30 s budget, with no behaviour difference | Return `DoctorFacts(summary)` for on-call before the board read (the same as the future branch at `:85-86`). Add a test: on-call by name today → zero `/availability` |
| M-3 | `booking.py` `_schedule_gate` | Catches `Unavailable`/`Malformed`/`Rejected` but not `InvalidIdentifier`. A RESCHEDULE whose owner appointment carries a `doctorId` that fails the client's path-id check (malformed upstream data) would surface as a protocol error instead of `COULD_NOT_RECORD` | Add `InvalidIdentifier` to the handled read errors there (the availability side already uses `READ_ERRORS`). Add a test with a malformed upstream `doctorId` |
| M-4 | `tests/test_availability.py:109,116,148,187` | Test names state the old behaviour while asserting the new: `…profile_failure_still_reports_the_board` asserts `COULD_NOT_CHECK`; `…on_call…is_offered_otherwise_desk` asserts callback; `…unmatched_session_without_any_unknown_is_availability` asserts `CALLBACK_REQUIRED`; `…reports_incompleteness_instead_of_pretending` asserts `complete is True`. Misleading for maintainers | Rename to describe the asserted behaviour |
| M-5 | `docs/handover/VOICE-TEAM.md` | The published interface lists the new fields, but has **no consumer change note** for the breaking changes: `journey` → `decision`; `CALLBACK_ONLY`/`DESK` removed; `expired`, `unknownSessions` and `callback.ask`/`say` removed; `date` optional plus `purpose`; `manage_booking.departmentId` removed. Only `CONTEXTFORGE.md:162` mentions some of them | Add a short "Changes in schema 2026-10-05.1" section to VOICE-TEAM |
| M-6 | `deploy/azure/smoke.py:64-65` | The new read-only `WORKING_HOURS` department probe accepts `WORKING_HOURS`/`CLARIFICATION_NEEDED`/`NOT_FOUND` only. On a fresh revision with a cold cache, a slow owner can legitimately yield `HANDOFF_REQUIRED`/`SEARCH_INCOMPLETE`, failing the release gate for an honest answer | Accept `HANDOFF_REQUIRED` in that probe's set, or warm the cache once before it |
| M-7 | `availability_policy.py:215-218` | Today with a named session that isn't on the board gives `CALLBACK_REQUIRED`/`SESSION_NOT_ON_BOARD` with `board = []`. Bookable sessions that day (computed as `alternatives`) are never shown, so the agent can't mention, for example, Morning `IN`. The callback is the approved result; this only concerns the facts shown | Optional: emit the other in-scope board sessions as facts. No behaviour change |

---

## External acceptance gaps (not code defects)

- **E-1:** live `usualSchedule` population in Manoj's directory is unverified. If it's empty, every future and working-hours answer is callback or `NO_USUAL_SCHEDULE`, by design.
- **E-2:** output-schema propagation to ContextForge stays a **manual** post-deployment check. `register.py` verifies names and input schemas only, and the docs now say so correctly (`CONTEXTFORGE.md`).

---

## Requirement checklist (verified in code and tests)

| Requirement | Result |
|---|---|
| Doctor and department targets; `AVAILABILITY` requires a date in-band (`DATE_REQUIRED`); `WORKING_HOURS` allows none | ✓ `availability_policy.py:145-161`, `availability.py:59-62`; tests `test_availability.py:246-256` |
| "today"/strict ISO in facility timezone; past and invalid dates | ✓ `resolve_date`; midnight test `test_availability.py:74`, reader test `:131` |
| Owner `status` unchanged, `decision`/`reason` separate | ✓ `outcomes.py` `BoardSessionOut.status` enum unchanged in the snapshot; `session_out` maps `owner_status` |
| IN/LATE/CANCELLED/NOT_CONFIRMED/UNKNOWN/stale/missing mapping | ✓ `TODAY_STATUS`, stale → `BOARD_STALE`, missing → `BOARD_ENTRY_MISSING`/`SESSION_NOT_ON_BOARD` |
| End only when a supplied end time has passed; no invented times | ✓ except overnight (I-2) |
| ON_CALL always callback | ✓ first rule; department on-call not read |
| Future/working hours: zero `GET /availability` | ✓ reader branches; tests `test_availability.py:97,251`, `test_schedule_reader.py:47`; the bench rejects a future board read |
| Usual hours never presented as confirmed | ✓ pack text and `basis = USUAL_SCHEDULE` (I-1 concerns which sessions are shown, not confirmation wording) |
| Session-selection rules | ✓ R6-2 as written; see G-1 |
| Department: name order, bounded batches, only bookable when any exist, empty on handoff, counts distinct, no false "not available" | ✓ `schedule_reader.py:98-137`, `rank`/`aggregate`; tests cover early stop, later batch, failed read, deadline, headroom, on-call no reads, cache, truncation, 20 shuffled orders, warm progress |
| One policy and one reader; obsolete code removed | ✓ `board_scope.py` deleted; no duplicate profile cache (`BookingService` uses the shared reader) |
| No knowledge calls, routing gate or transcript header; no writes | ✓ availability path is GET-only by construction; knowledge forbidden by test `test_availability.py:422-446` |
| One invocation deadline; batches cancelled; no background requests | ✓ one `Deadline(read_deadline)`; `asyncio.timeout` around `gather`, whose cancellation waits for its children; the per-exchange cap stays in the ops client |
| Bench success requires the intended outcome | ✓ `measure` returns a timing only for expected outcomes; future-cold/warm modes; the local bench no longer overrides the in-call budget |
| Contracts | ✓ no owner behaviour invented (limit=100 is the contract maximum); ContextForge wording accurate |
| Schema and docs agree with code | ✓ snapshot equals `make schema`; VOICE-TEAM generated; M-5 change note missing |
| Auth and privacy | ✓ unchanged; no new logging of caller data |

**Red/green evidence:** `availability-policy-evidence/` contains real failing runs (for example `01-policy-red.txt`, `07-availability-red.txt`, `29-time-gap-red.txt`) and passing reruns. The gaps are I-1 (only the reason was asserted) and G-1's untested cancelled + IN case.

## Commands run and results

| Command | Result |
|---|---|
| `git rev-parse --short HEAD; git status --short` | `228f0a0`; `?? temp/` only |
| `make test-fast` (at 228f0a0) | **537 passed**, 11 deselected, exit 0 |
| `make -s schema` vs `tests/contracts/mcp-tools.snapshot.json` (`cmp`) | **identical** |
| Fast suite at each of the 15 commits (detached temporary worktree, removed) | **All green:** 491 → 504 → 508 → 510 → 512 → 525 → 532 → 533 → 534 → 535 → 535 → 535 → 537 → 537 → 537 passed |
| Policy probes (`/tmp/probe_policy.py`, `/tmp/probe2.py`, scratch, outside repo) | Reproduced I-1, I-2 and G-1; confirmed the no-end-time handoff, the end-only handoff, and that mixed + time 18:00 → callback is correct |
| Files per commit | 5–10, all ≤10 |

## Not verified

- `./scripts/test.sh` (images and process e2e) was not run in this review.
- `make bench` was not run, so its numbers aren't reproduced here.
- Live owner data (usual schedules), real ContextForge behaviour and real latency.
- Booking beyond the shared-code paths.

## Readiness

- **Ready to merge: not yet.** Fix I-1 (small, contained in `_future`, with a regression test) and decide G-1. Record the overnight limitation (I-2). The minor items can go in the same pass or a follow-up.
- **Ready to deploy: no.** It needs the merge-blocking fixes, plus E-1 (one live usual-schedule check), the smoke adjustment (M-6), the ContextForge rediscovery and manual output-schema check (E-2), and Garima's explicit deployment approval.
