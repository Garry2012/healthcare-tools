# Opus partial review: booking write budget (commits 1–2, draft commit-3 tests)

Read-only review, 14 October 2026. Nothing was edited, rerun, committed or deployed.
Plan revision 7 SHA-256 re-checked: `fc036795e6642f685c64239ff5bed967bbde799e54dbe3a844b3c90ca4536575` (unchanged).
Branch `Garry2012/booking-write-budget`: `56698cd`, `9c06b71` on `e6b9193`; uncommitted C3 test drafts in
`test_settings.py`, `test_ops_client.py`, `test_booking.py`. Evidence read: `C1-test-fast-correction.txt`,
`C2-red.txt`, `C2-green.txt`, `C2-test-fast.txt`, `C3-red.txt`, `HAND-BACK.md`.

## Verdict

- **Commits 1 and 2: correct against the plan. No blocking finding.**
- **Floating-point correction: approved** as the single change to that comparison (ruling below).
- **Two further test corrections are required before resuming** (M2, M3); the rest are nits or pending work.

## Commits 1–2 checked against the plan

| Requirement | Evidence | Result |
|---|---|---|
| `Budget(total, exchange)`; `Deadline(budget)`; `timeout()` without argument; no global cap | `clock.py` diff | ✓ |
| Every caller migrated | `availability.py:67`, `booking.py:190/219/298`, `summary.py:109`, `ops_client.py` token and `_exchange`, `server.py:268–269`, `dev/bench.py:311` | ✓ |
| Six settings, per-kind properties, cap ≤ own total | `config.py` `read/write/summary_budget`, `_exchange_caps` | ✓ (`REQUEST_TIMEOUT_SECONDS` gone; flag pending C3 by design) |
| Dependency probe 1.0/1.0 (named correction) | `server.py:268–269`; `test_dependency_probe_has_its_own_one_second_exchange_cap` | ✓ |
| Token: unexpired token returned before the lock; refresh only absent/expired; single flight; background renewal kept | `ops_client.py` `TokenCache.get` (`if self.usable` before and after the lock), `refresh_if_due` unchanged | ✓ |
| 401 paths unchanged | `_read` and `_write` 401 branches untouched | ✓ |
| Retry semantics unchanged | `retry = attempt == 1 and _can_retry(...)` is the exact negation of the old `attempt == 2 or not _can_retry(...)` | ✓ |
| Safe write logs | `error` (known class names only, unknown names omitted by the formatter), `elapsedMs`, `remainingMs`, `retry`; new `ops_write_gateway_error`; bounded integers and bool in `SAFE_LOG_FIELDS` | ✓ |
| `durationMs` timed around the awaited operation, one `tool_result` line | `tools.py` async `observed()`; call sites pass the coroutine; `test_tool_duration_includes_awaited_service_once` advances a fake clock inside the operation and sees 125 ms | ✓ |
| No success-path work added | `elapsed_ms` is arithmetic only; logs only on failure branches | ✓ |
| Test replacement | `test_token_is_refreshed_before_it_expires` → `test_background_refresh_renews_before_token_expiry` (plan §4) | ✓ |

C1 correction suite: lint clean, 1220 passed. C2: red 17 intended failures, green 35, fast 1255 passed.

## Ruling on the floating-point correction

The three read cases build `Deadline(Budget(0.3, 0.3))` at fake time 100.0. `timeout()` returns
`min(remaining, cap)`; `remaining = (100.0 + 0.3) − 100.0 = 0.29999999999999716`, so the exchange receives the
remaining time, not the literal 0.3. Write (`cap 1 < remaining 3`) and summary (`8.0` exactly representable) are
unaffected, which is why only the read cases failed.

**Approved:** replace only that comparison with `pytest.approx(cap)` (default tolerance, ≈ 3·10⁻⁷ s for 0.3). It
cannot hide a real defect: the defects this test exists to catch (a request using another budget's cap, a token
refresh not bounded by the invocation's cap, an extra token call) differ by ≥ 0.7 s or change the counts, and the
token-count and API-count assertions before it already passed. No production change is indicated.

## Other C3 failures, individually

All 13 remaining failures are the intended missing C3 behaviour:
- `test_budget_defaults_keep_reads_fast_and_writes_independent`: write still `(0.3, 0.3)`.
- `test_only_per_budget_exchange_fields_and_voice_budget_remain`: `allow_budget_overrides` still a field.
- `test_each_budget_environment_value_changes_only_its_owner` ×6: write defaults still 0.3/0.3; `WRITE_DEADLINE_SECONDS=4` refused by the old guard; `WRITE_EXCHANGE_TIMEOUT_SECONDS=2` refused because the write total is still 0.3.
- `test_expired_read_does_not_consume_write_or_summary_budget`: write cap still 0.3.
- `test_successful_booking_uses_own_budget_without_added_owner_calls` [0.5 × CREATE/RESCHEDULE/CANCEL]: a 0.5 s owner answer exceeds the old 0.3 cap → `UNCERTAIN`.
- `test_write_schedule_and_caller_list_share_one_total`: write cap still 0.3.

## Findings

**M1 (must apply): floating-point comparison** — as ruled above.

**M2 (must fix): the booking latency test does not prove the write budget in its zero-delay cases.**
`test_booking.py` new `test_successful_booking_uses_own_budget_without_added_owner_calls`:
- `assert Deadline(Budget(3, 1), monotonic=lambda: tick[0]).remaining() == 3` constructs a fresh deadline after the
  call; it is always true and tests nothing.
- `assert all(cap <= 1.0 for cap in caps)` also passes with the old 0.3 cap, so the three zero-delay cases passed
  under the old configuration.
Fix: capture the deadline the booking creates (the monkeypatched `booking.Deadline` factory can append it to a
list), and assert after the call that it is the write budget (`cap == 1.0`, `remaining() == 3.0 − delay`, exactly
representable), and that every recorded owner exchange cap equals `1.0` (`min(remaining, 1.0)` with remaining ≥ 2.5).

**M3 (should fix): invalid-value cases can pass for the wrong reason.**
`test_settings.py` `test_invalid_budget_totals_and_nesting_are_refused` uses `pytest.raises(ValueError)` without
`match`. `{"write_deadline_seconds": 9}` currently passes through the old override guard, not the nesting rule. Give
each case its expected message fragment (`"read <= write <= summary"` for nesting, the pydantic bound text for
`0`, `31`, `61`), so after C3 each case fails for the intended rule.

**N1 (nit):** `config.py` `_derive_deadlines` repeats the summary default `8.0` as a literal next to the field
default; in C3, when write gets its own field defaults, take both defaults from the field definitions (or one module
constant) instead of repeating numbers.

**N2 (nit):** `test_expired_read_does_not_consume_write_or_summary_budget` ends with an assertion on settings values
only; summary independence is already shown by the environment test (summary stays 8/8 when read/write change).
Drop the trivial assertion or replace it with a summary call under an expired read deadline.

**N3 (nit):** inline `import time` in `test_write_401_refresh_keeps_frozen_body_and_key`; `httpx` and the clock
imports inside the booking test; prefer module-level imports.

## Missing plan coverage still to add in C3

- Booking-level owner delay **beyond** the 1.0 s write cap: `UNCERTAIN / NO_VERIFIED_RESPONSE`, one
  `ops_write_unanswered` with `error`, `elapsedMs`, `remainingMs`, `retry`, and (when the §6 condition holds) a second
  POST with the same frozen body and key (plan §10 "Owner delay").
- Bench and external fixture migration without the flag (plan §8), and DECISIONS entry (plan §9 commit 3).
- Commits 4 and 5 and the final verification in full.

## Completed vs pending

| Completed (committed) | Pending |
|---|---|
| C1 budget model, probe correction, token policy | C3 write defaults 3.0/1.0, read rule without bypass, flag removal, bench/external migration, DECISIONS |
| C2 safe timing logs and `durationMs` | C4 docs; C5 `rollout.env` values |
| Draft C3 tests (uncommitted) | Final checks: fast, schema byte comparison, e2e, bench after + comparison, `scripts/test.sh`, residual and trace searches, scope, des-moines, plan hash |

Not ready to merge or deploy.

## Continuation prompt for Astra (copy-paste; requires Garima's go-ahead)

> Resume the booking write budget task under the same brief (`des-moines/.context/astra-booking-write-budget.md`)
> and plan revision 7 (re-check SHA-256 `fc036795…6575`). Opus reviewed commits `56698cd` and `9c06b71` (approved) and
> your draft C3 tests; see `.context/write-budget/OPUS-PARTIAL-REVIEW.md`.
>
> 1. **Test corrections only, before any production change** (keep `C3-red.txt` unchanged):
>    - M1: in `test_each_budget_uses_valid_tokens_or_single_flight_refresh`, change only the timeout comparison to
>      `pytest.approx(cap)`.
>    - M2: in `test_successful_booking_uses_own_budget_without_added_owner_calls`, remove the tautological
>      `Deadline(...).remaining() == 3` line; capture the deadline the booking creates and assert `cap == 1.0` and
>      `remaining() == 3.0 - delay`; assert every recorded exchange cap `== 1.0`.
>    - M3: add the expected `match` fragment to each case of `test_invalid_budget_totals_and_nesting_are_refused`.
>    - Add the booking-level beyond-cap test from the review's "Missing plan coverage".
>    - Nits N2–N3 optional.
> 2. Run the corrected C3 red selection **once**, explicitly including
>    `test_read_share_has_no_bypass_and_write_may_exceed_voice_share` and the new test; save as `C3-red-2.txt`.
>    Continue only if every failure is the intended missing C3 behaviour; otherwise stop and report.
> 3. Implement C3 exactly per plan §4–§5, §8, §9 (write field defaults 3.0/1.0 without repeated literals, read rule
>    without bypass, delete `ALLOW_BUDGET_OVERRIDES`, migrate `dev/bench.py` and the `test_external.py` fixture via a
>    local voice budget, DECISIONS entry). Green once, `make test-fast` once, commit.
> 4. C4 docs and C5 `rollout.env` values per plan §9, each with `make test-fast` once and a commit.
> 5. Final checks in the brief's order, each once, including `bench-after.txt` / `bench-compare.txt` and the plan hash.
>    Update `HAND-BACK.md`. Stop on any unexpected failure. No deploy, cloud, live calls, push or merge.
