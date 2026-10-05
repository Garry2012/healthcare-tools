# Opus review: availability review fixes (228f0a0..6733ffe), 6 October 2026

**Scope:** the actual code and test changes in eight commits, checked against:
- `OPUS-AVAILABILITY-POLICY-REVIEW.md` (the original findings);
- `.context/attachments/vZTsdU/astra-fix-prompt-availability-review.md` (the requested fixes and the code-quality rules);
- `AVAILABILITY-REVIEW-FIX-HAND-BACK.md`.

This is a review only. No code, commit, merge or deployment. Tree at review: HEAD `6733ffe`, only untracked `temp/` (preserved).

## Verdict

**All requested fixes are present in the code and proven by tests. I found no defects.**
- **Held back as instructed:** G-1, M-7 and overnight behaviour are unchanged.
- **Code quality:** the changes are made where each rule lives (`_future`, `working_hours`, `decide_booking`, `aggregate`, `ScheduleReader.doctor`). No special-case patches, no duplicated logic.
- **Remaining items:** two documentation nits and one informational note.

**Ready to merge:** yes, once the two nits are fixed or accepted. **Ready to deploy:** no; the external prerequisites below still apply.

**Counts:** Critical 0 · Important 0 · Minor 0 · Nits 2 · Info 1.

## Verification commands

| Command | Result |
|---|---|
| `git rev-parse --short HEAD; git status --short` | `6733ffe`; `?? temp/` only |
| `make test-fast` at 6733ffe | **547 passed**, 11 deselected, exit 0 |
| `make -s schema` vs snapshot (`cmp`) | **identical** (schema `2026-10-06.1`) |
| Fast suite at each commit (detached temporary worktree, removed) | 76661b5 540 · 53f03d2 540 · b874f24 543 · 0d89e1f 544 · 5601879 546 · b7c5a30 547 · ee73b37 547 · 6733ffe 547: **all green** |
| Files per commit | 7, 7, 10, 10, 5, 6, 9, 5: **all ≤10** |
| My earlier scratch probes (`/tmp/probe_policy.py`, `/tmp/probe2.py`) re-run against 6733ffe | I-1 fixed; G-1 and overnight unchanged (details below) |

## Fix-by-fix verification

| Item | Code | Test proof | Verdict |
|---|---|---|---|
| **I-1** future SESSION_NOT_USUAL hides same-day sessions | `availability_policy.py` `_future`: every usual session is decided once (on the requested weekday → APPOINTMENT_REQUEST; otherwise NOT_AVAILABLE/NOT_USUAL_DAY). Alternatives and selection come from that one tuple. The not-selected branch returns the per-session facts. `decide_booking` returns `NotAvailable(decision.reason, decision.alternatives)` for a NOT_AVAILABLE doctor, so booking keeps SESSION_NOT_USUAL. `availability._single` `sessionMatched` checks only board sessions, or usual sessions on the requested weekday | Policy: `test_future_unmatched_session_keeps_each_weekdays_facts_and_booking_reason`. HTTP: `test_future_unmatched_session_exposes_the_days_actual_alternatives` (Morning/Afternoon APPOINTMENT_REQUEST with `onRequestedDate=true`, `sessionMatched=false`, no `/availability`, GET-only) and `test_future_session_label_on_another_weekday_does_not_match` (Tuesday "Evening" → `NOT_AVAILABLE/NOT_USUAL_DAY`, `onRequestedDate=false`). The existing booking SESSION_NOT_USUAL test stays green. Probe: Monday Evening → Morning APPOINTMENT_REQUEST, Evening NOT_AVAILABLE/NOT_USUAL_DAY | ✓ Fixed at the rule's home |
| **On-call working hours** (Garima's rule) | `working_hours` uses the shared `_on_call(...)` (reason ON_CALL_DOCTOR). `_single` maps every purpose through one decision table; only WORKING_HOURS with hours becomes `WORKING_HOURS`/`PRESENT_WORKING_HOURS`. So on-call and empty schedules get `CALLBACK_REQUIRED` + `callback{reason, summaryOutcome}`. `bookableFound` is zero for WORKING_HOURS (single and department via `ResultOutcome.bookable_found`) | `test_working_hours_on_call_uses_the_full_callback_result` (by id and by name), `test_working_hours_empty_schedule_uses_the_full_callback_result`, `test_working_hours_department_keeps_on_call_facts_without_bookable_count` (no profile read for the on-call doctor), and the extended `test_working_hours_need_no_date…` (`PRESENT_WORKING_HOURS`, `bookableFound=0`) | ✓ |
| **Aggregate/rank clean-up** (supporting change) | `SearchState.bookable_found` was renamed `matches_found`, because the batched search also counts working-hours matches. `aggregate` now returns the `candidates` to list plus `bookable_found`; `rank` only orders and caps. "Which doctors to list" now has one home instead of being split between `rank` and the service | `test_department_rollup…` updated to `rank(result.candidates)`; the department handoff still lists nothing (candidates empty) | ✓ Cleaner than before (closes the old split) |
| **M-2** on-call by name, today: no board read | `ScheduleReader.doctor` returns `DoctorFacts(summary)` for an ON_CALL summary **before** any date branch, so it covers today, future and working hours in one place. The old future-only branch is removed | `test_today_on_call_by_name_needs_no_board_read` (board failure injected, `ops_paths == ["/doctors"]`, callback returned) | ✓ |
| **M-3** booking `InvalidIdentifier` | `booking._schedule_gate` catches `InvalidIdentifier` with the other read failures → `COULD_NOT_RECORD`/`PROFILE_UNAVAILABLE`. The unused `noqa` import in tests is removed | `test_reschedule_malformed_owner_doctor_id_cannot_escape_as_protocol_error` (`../departments`, `invalid/id`): no reschedule POST, GET-only, the id is not echoed | ✓ |
| **M-4** stale test names | Four tests renamed to describe what they assert (`test_availability.py:109,116,148,187`) | n/a | ✓ |
| **M-5** consumer change note | `VOICE-TEAM.md:352-366` adds "Changes in schema 2026-10-05.1" and "…2026-10-06.1" (journey→decision; removed fields; `purpose`/`date`; `departmentId` removed; overnight limitation; working-hours changes; I-1; G-1 pending) | n/a | ✓ (see N-1) |
| **M-6** smoke accepts handoff | `smoke.py:64-65` adds `HANDOFF_REQUIRED` to the WORKING_HOURS probe | `test_smoke_probes_working_hours…` is parameterised for WORKING_HOURS and HANDOFF_REQUIRED | ✓ |
| **Overnight** (documentation only) | `DECISIONS.md:156-157`, `VOICE-TEAM.md:358` ("sessions crossing midnight are unsupported"), `CLAUDE.md:26`. No code change to `_window` | Probe: still `SESSION_ENDED` at 21:00/23:00 (unchanged, unsupported) | ✓ |
| **G-1 unchanged** | `_combine` and the booking `SessionRequired` path are untouched | Probe: Morning ended + Evening IN → doctor `APPOINTMENT_REQUEST` with `sessionChoiceRequired=true`; booking without a session → `SessionRequired` (as before) | ✓ Held back as instructed |
| **M-7 unchanged** | `_today` is untouched: a named session missing from the board still gives `SESSION_NOT_ON_BOARD` with `board=[]` | Existing `test_any_unknown_session_in_scope_stops_the_journey` asserts `board == []` | ✓ Held back as instructed |
| **Schema** | `SCHEMA_VERSION 2026-10-06.1`; adds nextStep `PRESENT_WORKING_HOURS`; removes reason `NO_REGULAR_HOURS`; description texts updated; snapshot and VOICE-TEAM regenerated | `make schema` identical | ✓ |

## Code-quality check (against the prompt's rules)

- **Root-cause fixes at the rule's home:**
  - I-1 in `_future` (one per-session decision tuple, with no second filter elsewhere);
  - on-call in `working_hours` via the shared `_on_call`;
  - M-2 in `ScheduleReader.doctor` (one early return, with the duplicate branch removed);
  - the listing rule moved into `aggregate`.
- **No patches:** no test-only `if`s, flags, copy-paste, TODOs or dead code. The one special case in `_single` (WORKING_HOURS with hours → `PRESENT_WORKING_HOURS`) is the defined behaviour of that purpose, not a workaround.
- **Unused things removed:** the `NO_REGULAR_HOURS` reason, the future-only on-call branch, and the unused test import.
- **Tests:** assert results and owner requests at the boundary (the stub request log, GET-only, no `/availability`). No tests were weakened. The changed assertions follow the approved renames (`matches_found`, `ON_CALL_DOCTOR`).

## Nits and info

| # | Where | Note | Suggested change |
|---|---|---|---|
| N-1 | `VOICE-TEAM.md:363`, `DECISIONS.md:152` | Says `ON_CALL_DOCTOR` "replaces the **unused** NO_REGULAR_HOURS reason". In schema 2026-10-05.1 it **was** emitted (on-call working hours), so a consumer built on 2026-10-05.1 could have used it | Reword to "replaces NO_REGULAR_HOURS (emitted in 2026-10-05.1 for on-call working hours)" |
| N-2 | `availability_policy.py` `decide_booking` | A side effect of the I-1 shortcut isn't written down: booking against a doctor whose decision is NOT_AVAILABLE now always reports the doctor's own reason. **Example:** every session today ended or cancelled, plus a `preferredTime`. Before: `TIME_OUTSIDE_SESSION`. Now: `SESSION_ENDED`/`CANCELLED` (the probe shows the overnight case also reports `SESSION_ENDED`). Behaviour (NOT_AVAILABLE, no write) is unchanged, and the reason is arguably more accurate | Mention it in the hand-back or DECISIONS; optionally add one test pinning `SESSION_ENDED` for that case |
| I-1 (info) | `aggregate` | Department WORKING_HOURS where every doctor is on call (search complete) returns `WORKING_HOURS` with on-call facts and **no** callback object. A single on-call doctor returns `CALLBACK_REQUIRED`. This is the approved rule (`CLAUDE.md:26`: "Department hours keep on-call facts within the cap"); noted so it isn't mistaken for an inconsistency | None |

## Still not verified / deployment prerequisites (unchanged)

- `./scripts/test.sh` (image builds, process e2e) and `make bench` were not re-run in this review. The hand-back's `22-full.txt` records a full run.
- Live usual-schedule data, real latency, ContextForge rediscovery and the manual output-schema check: all external.
- **G-1 still needs Garima's decision.**
