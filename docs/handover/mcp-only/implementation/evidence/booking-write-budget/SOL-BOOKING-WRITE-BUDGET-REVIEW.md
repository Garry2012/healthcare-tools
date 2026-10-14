# SOL independent review: booking write budgets

Review only, 14 October 2026. This report is uncommitted. No implementation, test, schema, cloud, gateway or live-service change was made.

## Verdict

**APPROVED FOR MERGE REVIEW.**

Reviewed range:

`e6b91930d55db7ea98a2285ffe2b8c5eba810f33..dff06f2313d5e4245999e9a1d54259fafc4accf2`

Branch and HEAD matched the brief. There were no tracked worktree changes before review; the two existing untracked Opus reports were preserved. The revision-7 plan hash matched `fc036795e6642f685c64239ff5bed967bbde799e54dbe3a844b3c90ca4536575`.

I found no code or configuration defect that must be corrected before merge review. The final M-1 configuration correction is effective, and L-1 is documented correctly.

**Deployment readiness is not established.** Real canary/voice timing, the voice-platform timeout confirmation, rollback-state recording and Garima's separate merge/deploy approvals remain open. The local p99 observation below also needs explicit acceptance or a larger paired benchmark before deployment.

## Findings

### O-1 — non-blocking merge observation; deployment latency gate remains open

- **Where:** `.context/write-budget/bench-compare.txt`; plan revision 7, L7 and deployment steps 2/6.
- **Trigger:** comparing the recorded 50-sample base and branch stub runs.
- **Observed:** three p99 values increased: department `73.8 → 97.0 ms`, future-warm department `37.1 → 68.3 ms`, and on-call slots `76.1 → 77.6 ms`.
- **Practical impact:** none is demonstrated in production, but these runs cannot prove that the real gateway/voice path has no tail-latency regression.
- **Evidence:** all 14 p50 values were equal or better; 13 of 14 p95 values improved and one increased by `0.2 ms`; 11 p99 values improved; all 700 samples in each run were verified; every owner-call path/count was identical. With 50 samples, the benchmark's p99 is the single maximum sample. The changed common read-path work is budget-object selection, a usable-token fast path and timing arithmetic; the data shows no broad shift correlated with those changes.
- **Assessment:** the three maxima are consistent with local scheduling/transport jitter, but their cause was not measured and “noise” is not proven. This does not identify an implementation correction. Before deployment, either run the proposed paired larger benchmark on the same machine or have Garima explicitly accept this limited local-stub evidence and rely on the required canary/voice measurement.

No blocker, high, medium or low implementation finding was found.

## End-to-end requirement coverage

### Budget model and configuration

- `Budget(total, exchange)` is frozen and every production `Deadline` carries its own exchange cap. `Deadline.timeout()` has no argument or global fallback.
- Availability and appointment LIST create `Deadline(settings.read_budget)`; defaults are `0.30/0.30`.
- CREATE, CANCEL and RESCHEDULE create `Deadline(settings.write_budget)`; defaults are `3.0/1.0`.
- Call summary creates `Deadline(settings.summary_budget)`; defaults remain `8.0/8.0`.
- The dependency probe uses an explicit `1.0/1.0` budget. Background token renewal uses an independent `TOKEN_REFRESH_TIMEOUT_SECONDS` value as both total and cap.
- Settings validation enforces positive bounded values, each exchange cap no greater than its total, explicit reads within the voice allocation, and `read <= write <= summary`.
- `REQUEST_TIMEOUT_SECONDS` and `ALLOW_BUDGET_OVERRIDES` have no active code/config/document references outside the plan's approved historical exclusions. There is no compatibility branch.
- Schema-affecting files are unchanged across the reviewed range. The committed snapshot is 59,466 bytes, SHA-256 `bf0b18b949f07659e64d15a1647b1c658338826952b883e3db5a428d67c7aa5b`; `SCHEMA_VERSION` remains `2026-10-11.2`.

### M-1 and L-1

- **M-1 RESOLVED.** The six operation-budget variables are absent from Compose's higher-precedence `environment:` block and from `.env.example`; they are assigned only in `rollouts/demo-hospital/rollout.env` for the local/deployment configuration path. Compose still passes the three voice-allocation variables separately.
- I rendered Compose with `WRITE_DEADLINE_SECONDS=9.9` deliberately exported in the shell. The result still contained the rollout value `3.0`, proving the shell/Compose layer no longer overrides `rollout.env`; this is stronger than merely observing matching defaults.
- `deploy/azure/deploy.sh` reads all `rollout.env` entries and includes them in `--replace-env-vars`, so the deployment source is the same rollout file. Deployment tooling was inspected only, never executed.
- **L-1 ADDRESSED.** `rollout.env` and the service README both state that lowering the write total below `1.0 s` also requires lowering `WRITE_EXCHANGE_TIMEOUT_SECONDS`, matching startup validation.

### Booking correctness and failure handling

- CREATE performs its schedule check and POST with one write deadline.
- RESCHEDULE performs the verified-caller appointment lookup, doctor schedule check and POST with the same single deadline object.
- CANCEL creates one write deadline and uses it for its POST. LIST remains on a separate read deadline.
- The write body and idempotency key are constructed once and reused. No retry branch rebuilds or mutates them.
- A failure known to occur before dispatch remains definite/unavailable. Once an attempt may have reached the owner, later failure is `UncertainWrite`; 502/504 and owner 5xx remain uncertain. A refused/inconclusive second attempt cannot overwrite the uncertainty of the first.
- 401 handling preserves the same frozen body and key for the authenticated repeat. Persistent auth refusal remains an operator/auth failure; 403 is not retried.
- Retry eligibility still consumes preflight, authentication and exchange time from the same deadline. The test matrix correctly pins both sides of:
  - hanging exchange: `P + 2.5A <= 0.5` for `E=1`;
  - instant failure: `P + A <= 2.95` and `P + 2.5A <= 3.0`;
  - the `0.05 s` minimum floor.
- The booking-level beyond-cap test proves two identical POSTs, `UNCERTAIN/NO_VERIFIED_RESPONSE`, and retry logs `true` then `false` with the expected remaining time.

### Token behaviour

- Any unexpired token returns before acquiring the refresh lock, including inside the refresh margin and while a background refresh holds the lock.
- Missing or expired tokens wait under the invocation deadline and use the existing single-flight lock; only one caller refreshes and waiting callers recheck usability.
- The background refresher retains proactive renewal inside the margin with its independent timeout.
- The 401 path invalidates, refreshes once and repeats the authenticated request; tests pin two POSTs with the same body/key for the successful write case.
- Normal successful requests with a usable token make no token-endpoint call. This avoids the latency regression that an own-cap port of the old margin rule would have introduced.

### Latency L1–L7

| Rule | Independent assessment |
|---|---|
| L1: ceiling only | Met. `asyncio.timeout` caps waiting and returns immediately on a response; no sleep to consume unused budget. |
| L2: no new calls/waits | Met in the diff. No new REST call, polling loop, sleep or sequential scheduling step was added. Recorded owner-call counts are identical in all 14 scenarios. |
| L3: no success retry | Met. Retry branches are reached only after transport/write failure; success returns directly. Booking tests pin one POST and no token call with a usable token. |
| L4: reads unchanged | Met by configuration and callers: availability/LIST remain `0.30/0.30`. The benchmark does not show a broad read regression. |
| L5: same successful booking work | Met. CREATE/RESCHEDULE/CANCEL use the existing gates and owner calls; only their budget object changes. |
| L6: one timed result log | Met. Shared async `observed()` starts the monotonic timer before awaiting the service coroutine and adds `durationMs` to the existing single `tool_result`; no new success log exists. |
| L7: before/after measurement | Locally covered, with O-1's limitation. Real backend/gateway/voice latency remains an external deployment gate. |

Timing fields are bounded integers and `retry` is strictly boolean in the JSON formatter. Error logging uses known exception class names and route templates; it does not log exception messages, bodies, query strings, names, mobiles, reasons or tokens. Whole-tool `durationMs` is correctly documented as combined service time, not isolated POST time.

### Tests, corrections and scope

- The C1/C2 red runs failed for missing Budget/token/probe and timing/logging behavior respectively, then passed after implementation.
- The corrected C3 red run is meaningful: it failed on old write defaults, the remaining bypass, independent setting ownership, precise nesting validation, booking caps, the shared reschedule deadline and the beyond-cap retry. It did not merely mirror production expressions.
- The earlier floating-point correction uses `pytest.approx` only where a `0.3` remaining calculation is not exactly representable. Count/path assertions still detect wrong calls or wrong budgets.
- The formerly tautological booking assertion was replaced with capture of the actual booking-created deadline; zero-delay cases now failed red under the old `0.3` cap.
- The invalid-setting cases match the intended validation error, preventing an obsolete guard from satisfying the test accidentally.
- The benchmark watchdog correction changes only the expected factor from the old `0.3` write total to `3.0`; the production watchdog calculation already uses `max(read, write)`.
- No existing unrelated assertion was weakened. The 28 changed files are attributable to the budget model, callers, logging, configuration/docs and their tests; no tool output schema, owner contract, auth, tenant, caller-verification or deployment mechanism was changed.

## Independent commands and results

Run by this reviewer:

| Command/check | Result |
|---|---|
| `git rev-parse HEAD`, branch/status, plan SHA-256 | Exact expected HEAD/branch; no tracked changes; plan hash exact. |
| `git diff --check e6b9193..dff06f2` | Clean. |
| Full base-to-HEAD diff, commit/file inventory, all `Deadline(` / `.timeout(` call sites | Inspected; six commits, 28 changed files, no unaccounted production caller. |
| `make test-fast` with prohibited variables cleared | **Unavailable before tests ran:** uv could not initialize `/Users/garima/.cache/uv` because the review sandbox denied access. Exit 2. Preserved in `.context/sol-budget-review/test-fast.txt`. Per the brief, it was not retried and no further test suite was run. |
| Compose render using `.env.example` placeholders | Exit 0; resolved budgets `0.30/0.30/3.0/1.0/8.0/8.0`. Saved as `.context/sol-budget-review/compose-config.txt`. |
| Compose precedence probe with shell `WRITE_DEADLINE_SECONDS=9.9` | Exit 0; rendered value remained rollout `3.0`, with the other five rollout values unchanged. Saved as `.context/sol-budget-review/compose-precedence-probe.txt`. |
| Active residual search for removed variables with plan exclusions | No matches (`git grep` exit 1, expected). Saved as `.context/sol-budget-review/residual.txt`. |
| Snapshot/prompt comparison against base; snapshot size/hash/version | Both files unchanged; 59,466 bytes; hash/version as above. This is source stability, not a fresh schema generation. |

Because the first independent test command hit an infrastructure permission error, I did **not** claim an independent passing suite and did not rerun it with a workaround.

## Historical evidence inspected, not independently rerun

- Astra final evidence: Ruff clean; 1,295 hermetic tests; five process tests; byte-identical generated schema; package, wheel, production image and stub image builds; residual/trace checks; des-moines and plan preservation.
- M-1 evidence: Compose rendering, source-location search and 1,295 fast tests.
- Before/after benchmark: 700/700 verified in each run, same 14 scenarios, same owner-call counts, detailed percentiles quoted in O-1.
- Opus partial, full and M-1 reviews were read after the governing briefs and were checked against the actual diff rather than adopted as conclusions.

## Remaining uncertainties and external gates

1. Decide O-1 before deployment: paired larger local benchmark or Garima's explicit acceptance of the limited tail evidence.
2. Record the currently working canary's immutable image digest and full non-secret environment/secret references for rollback.
3. Confirm the voice platform's MCP timeouts cover the 3-second write plus gateway/margin (the plan recommends 8–10 seconds; that recommendation is not a measured requirement).
4. After an approved deployment, run authorised synthetic CREATE/LIST/RESCHEDULE/CANCEL journeys, inspect `durationMs` and any failure timing, and decide whether the initial 1-second exchange cap needs tuning.
5. Measure the real backend → MCP → gateway → voice path. Local stubs do not prove production latency.
6. Merge and deployment remain separate Garima approvals. No ContextForge schema refresh is required because the tool schema did not change.

## Plain-English summary for Garima

The implementation is structurally sound: reads stay fast, bookings get their own configurable 3-second total/1-second call cap, summaries stay at 8 seconds, and one deadline follows each booking through all checks and retries. The old global timeout and bypass are gone, tokens are no longer refreshed unnecessarily during a call, uncertainty and idempotency safety remain intact, and the final Compose fix makes `rollout.env` the real configuration source.

I found nothing that needs a code fix before merge review. I could not independently start the test suite because this sandbox could not access uv's cache; I preserved that failure and relied on code inspection plus the already-recorded successful test/build evidence without pretending I reran it. Deployment still needs your latency decision, the voice timeout confirmation, rollback capture and real canary/voice tests.
