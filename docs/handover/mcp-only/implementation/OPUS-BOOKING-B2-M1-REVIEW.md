# Opus review: booking B-2 and M-1 fixes (84103b0..b1ce587), 6 October 2026

**Scope:**
- `84103b0`: docs only (VOICE-TEAM calling guide, manage_booking review);
- `b1ce587`: the B-2 and M-1 fix.

Checked against `.context/attachments/13cLXu/astra-prompt-booking-b2-m1.md` and `BOOKING-B2-M1-HAND-BACK.md`. Review only: no code, commit, push, merge or deployment. Tree at review: HEAD `b1ce587`, only untracked `temp/`.

## Verdict

**Both fixes are correct, made at the rule's home, and proven by tests. No blocking defects.**

- One minor finding (M-1 translation ignores the action, so a LIST rejection could be mislabelled).
- One nit (the opt-in live write benchmark now depends on the time of day).
- One informational note.

Schema, authentication, idempotency, B-1, B-3, M-2 and G-1 are unchanged.

**Counts:** Critical 0 · Important 0 · Minor 1 · Nit 1 · Info 1.

## Verification

| Check | Result |
|---|---|
| `make test-fast` at `b1ce587` | **590 passed**, 11 deselected, exit 0 |
| `make -s schema` vs snapshot (`cmp`) | **identical** (`2026-10-06.1`) |
| `git diff 84103b0 b1ce587` on `tests/contracts`, `prompt.py`, `packs/`, `server.py`, `context.py`, `ops_client.py`, `identity.py`, `tools.py` | **no changes** (schema, auth, headers, transport, idempotency key and retry paths untouched) |
| My 36 real-world scenarios from the manage_booking review, re-run against `b1ce587` and diffed against the pre-fix run | **Only S3 and S17 changed**, as intended; every other outcome is identical (including B-1 S11, M-2 S13b/c, G-1 S4, idempotency S15/S16/S24, identity S18/S19) |
| Exact owner bodies | CREATE (`test_booking.py:50`), RESCHEDULE (`:308`) and CANCEL (`:313`) body assertions pass unchanged, so the refactored body construction sends identical payloads |
| Hand-back red evidence | Present for both items (old code wrote 09:15; returned `expectedTime` instead of `preferredTime`) |
| Commits | `84103b0` 2 files (docs, my content unchanged); `b1ce587` 10 files |

## B-2: past time today

| Requirement | Code | Evidence | Verdict |
|---|---|---|---|
| One rule for "time inside a session" | `availability_policy.py:272` `_contains_time` replaces both former comparisons (matching at `:294`, final check at `:316`). No third comparison | `test_booking_window_uses_facility_minute_only_for_today` | ✓ |
| Today only | The window start becomes `max(start, now)` only when `s.basis == Basis.LIVE_BOARD`; usual-schedule sessions are untouched. No flag parameter | Same test, `day="2026-10-05"` → `Write` for all times | ✓ |
| Minute precision | `now.time().replace(second=0, microsecond=0)` | `now=10:30:40`, preferred `10:30` → `Write` | ✓ |
| Comparison style | `time.fromisoformat`, matching `_window` | Read | ✓ |
| Unknown boundaries unchanged | The final check still hands off on `UNKNOWN_END` or `start is None` before `_contains_time` runs; the `matched`/`unbounded` branch is unchanged | `test_booking_window_keeps_unknown_boundaries_unverifiable` (12 cases) | ✓ |
| CREATE and RESCHEDULE | `now` is captured once in `_create`/`_change` and passed through `_reschedule_gate` → `_schedule_gate` → `decide_booking`. The duplicate `local_now` in `_schedule_gate` is removed | `test_mcp_create_respects_todays_current_minute` (no POST on refusal, one `/availability` read); `test_mcp_reschedule_refuses_a_passed_time_today` (no POST `/reschedule`; stored time unchanged); my scenario S3 → `NOT_AVAILABLE`/`TIME_OUTSIDE_SESSION`/`OFFER_OTHER_SESSION_OR_TIME` | ✓ |
| Callers of the changed signature | `decide_booking` has one production caller (`booking.py:233`); all 12 test calls updated | grep | ✓ |

## M-1: rejection field names

| Requirement | Code | Evidence | Verdict |
|---|---|---|---|
| One source of truth shared with the request bodies | `booking.py:61` `_OWNER_FIELDS` drives both `_write_body` (CREATE, CANCEL, RESCHEDULE) and the translation in `_failure` (`:151`) | The exact-body tests above pass unchanged; translation tests cover `mobile`, `expectedTime`, `newExpectedTime`, `reason`, identical names, `callerMobile`, `callId`, unknown names and duplicates | ✓ |
| Only actionable names | The translated set is intersected with `BookingRequest.model_fields`; `detail` keeps the owner code; owner message text is not echoed | `test_owner_create_rejection_names_only_actionable_tool_arguments`, `test_owner_change_rejection_names_the_tool_argument` | ✓ (see F-1) |
| Summary untouched | Same principle as `summary.py:111`; no refactor | Read | ✓ |

## Fixture changes

- `preferredTime` `09:30` → `10:45` in `CREATE`, `test_gate_assertions.py:49` and `test_server.py:158`.
- The harness clock is 10:00 IST, so 09:30 is now correctly refused. 10:45 sits inside the same open Morning window (09:00–12:00, including `MIXED_BOARD`), so each test still asserts what it did before: an in-window time today is noted, the frozen body carries it, and the scope resolves to Morning.
- `test_server.py:153` (future date, 09:30) is rightly left unchanged.
- No assertion was weakened or removed.

## Findings

### F-1 (minor): translation uses all actions' names, so a LIST rejection can name the wrong argument

**Where:** `booking.py:151`

```python
names = {owner: tool for mapping in _OWNER_FIELDS.values() for owner, tool in mapping.items()}
```

The translation flattens every action's mapping and ignores which action failed. LIST is not in `_OWNER_FIELDS`. Its owner query parameters are `mobile` (the **trusted caller number** from headers), `from`, `to` and `status`.

**Reproduction:**
```python
svc = booking.BookingService.__new__(booking.BookingService)
svc._failure(Rejected(400, "VALIDATION_FAILED", ("mobile", "from")), write=False).fields
# → ['patientMobile']
```

- A LIST rejection of the caller number tells the agent to correct `patientMobile`, which LIST does not take and the caller cannot fix.
- A `from` rejection is dropped although the tool argument `fromDate` exists.

**Likelihood:** low. LIST's mobile comes from validated headers and the dates are validated locally first, so the owner rarely rejects them.

**Fix where the rule lives:** translate with the failing action's own mapping. If LIST should translate too, give it its own `from → fromDate`, `to → toDate` entry next to where `find_appointments` builds its query. This also removes the per-call rebuild of `names`.

### F-2 (nit): the opt-in live write benchmark now depends on the time of day

**Where:** `dev/bench.py:61`

`booking_create` uses `visitDate: "today"` with a fixed `preferredTime: "10:45"`. Live mode uses `SystemClock` (`bench.py:212`). With `BENCH_ALLOW_WRITES=1` against a test tenant, the scenario now expects `NOTED` only before 10:45 facility time. It was already dependent on the live board having an open session.

Writes are opt-in and need a designated tenant. When running it, set `BENCH_VISIT_DATE` to a future date (already supported, `bench.py:241`), or document that.

### I-1 (info): a past time next to an unknown-end session hands off

**Setup:** at 10:30, Morning 09:00–11:00 is open and Evening has a start of 17:00 but no end.

**Result:** preferred `09:15` → `HANDOFF_REQUIRED`/`TIME_NOT_VERIFIABLE` rather than `TIME_OUTSIDE_SESSION`. Preferred `14:00` gives the same handoff before and after this change.

This is the existing unknown-boundary rule, which the prompt required to stay unchanged. It is safe (no write) and needs no change now. Manoj's slot work would make it moot.

## Code quality

- Rules live in one place each:
  - the time window in `_contains_time`, used by both checks;
  - names in `_OWNER_FIELDS`, used by the body and by rejections.
- The duplicate clock read is removed, and body construction is simpler (three hand-built bodies replaced by one mapping).
- No flag parameters, special cases, TODOs or commented-out code.
- The hand-back reports a vulture run on both files with no findings.
- Runtime change: about +40/−27 lines. No new I/O, retries or deadline changes, so no latency effect.

## Recommendation

**Merge-ready.**
- F-1 can be fixed now (small, same files) or accepted as low-likelihood.
- F-2 is a run-book note.
- Not deploy-ready until deployment is separately approved; the earlier external prerequisites still apply.
