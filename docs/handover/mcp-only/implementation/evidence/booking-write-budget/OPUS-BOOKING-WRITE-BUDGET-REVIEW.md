# Opus review: booking write budget implementation

Review only, 14 October 2026. Not committed. Nothing was fixed, committed, pushed, merged or deployed.

- **Reviewed range:** `e6b91930d55db7ea98a2285ffe2b8c5eba810f33..f8618825b369a9bc3f21e86763a24b8aefc38663`
  (`56698cd`, `9c06b71`, `a1c6968`, `1bfbf74`, `f861882`), branch `Garry2012/booking-write-budget`, clean worktree.
- **Governing plan:** revision 7, SHA-256 `fc036795e6642f685c64239ff5bed967bbde799e54dbe3a844b3c90ca4536575` (re-checked).
- **Read:** full diff (28 files), brief, resume prompt, `OPUS-PARTIAL-REVIEW.md`, `HAND-BACK-FINAL.md`,
  `bench-compare.txt`, `bench-assessment.txt` and the saved check outputs.

## Verdict: CHANGES REQUIRED (one small configuration correction)

The production code, tests and budget model are sound and match the plan. One configuration-wiring defect (M-1)
creates a second, overriding source for the six budget values in the local stack. It is a small change to
`deploy/docker-compose.yml`, `.env.example` and one README sentence. **Deployment readiness is not established**: the
live canary measurement, the voice team's LiveKit timeout confirmation (D5), merge and deployment approvals remain open.

## Findings

### M-1 (Medium): local compose duplicates the six budget values and overrides `rollout.env`

- **Where:** `deploy/docker-compose.yml:33–38` (six `environment:` entries with defaults `0.30/0.30/3.0/1.0/8.0/8.0`);
  `.env.example:25–30`; `services/mcp/README.md` "Local compose forwards the six settings from .env".
- **Trigger:** the service loads `rollouts/demo-hospital/rollout.env` through `env_file` (`docker-compose.yml:12`), but
  Compose gives `environment:` precedence over `env_file:`.
- **Impact:** (1) tuning a value in `rollout.env`, the documented single place (D4, plan §4), has no effect in the local
  stack, because the compose default silently replaces it; (2) lowering `VOICE_RESPONSE_BUDGET_SECONDS` locally
  (e.g. 0.8 → share 0.10) makes the stack refuse to start, because compose still sends an explicit
  `READ_DEADLINE_SECONDS=0.30`; (3) the values now live in four places (code defaults, `rollout.env`, compose,
  `.env.example`), against "one source of truth". Azure is unaffected (`deploy.sh` reads `rollout.env`).
- **Correction:** delete the six budget entries from the compose `environment:` block (the rollout file already
  supplies them); delete the six lines from `.env.example` (or leave one comment pointing to `rollout.env`); change the
  README sentence to say local compose takes them from `rollout.env`. No code or test change; `make test-fast` once.

### L-1 (Low): lowering the write total below 1.0 s alone fails at startup

- **Where:** `config.py` `write_exchange_timeout_seconds` default `1.0` with `_exchange_caps`.
- **Trigger:** `WRITE_DEADLINE_SECONDS=0.8` without `WRITE_EXCHANGE_TIMEOUT_SECONDS`.
- **Impact:** startup refuses with "write exchange cap must not exceed its total deadline". Correct per plan §5 rule 2,
  and the message is clear, but an operator tuning only the total will hit it.
- **Correction (doc only, optional in the same change):** one line in the `rollout.env` budget comment and README:
  "a write total below 1.0 s also needs a matching `WRITE_EXCHANGE_TIMEOUT_SECONDS`".

### O-1 (Observation, deployment gate): three p99 increases in the stub benchmark

- **Evidence:** `bench-compare.txt`: department 73.8 → 97.0 ms, future-warm department 37.1 → 68.3 ms, on-call slots
  76.1 → 77.6 ms; every p50 equal or better; 13 of 14 p95 better, one +0.2 ms; owner calls identical in all 14
  scenarios; 700/700 verified both runs.
- **Assessment:** at 50 samples `percentile(…, 99)` is the single maximum, so each "p99" is one sample from one run.
  The read-path code changes are a `Budget` object, an earlier `usable` return in `TokenCache.get` and two
  `time.monotonic()` reads: microseconds, not tens of milliseconds, and identical for the scenarios whose p99 fell
  sharply (slots-today 198 → 44 ms). I find no mechanism for a regression and judge it tail jitter, **but it is not
  proven**. Under L7 ("unexplained regression blocks deployment"), I recommend one paired `make bench --samples 200`
  (base and branch, same machine) before deployment, or Garima's explicit acceptance of this interpretation.
  It does not block merge review.

### Nits (no action required)

- Inline imports remain in some new tests (`test_booking.py` new tests import `httpx`/`Deadline` locally;
  `test_write_401_refresh_keeps_frozen_body_and_key` imports `time` locally). Review N3 was optional.

## Requirement coverage (code and evidence)

| Requirement | Evidence | Result |
|---|---|---|
| Reads 0.30/0.30 default; writes 3.0/1.0; summaries 8.0/8.0 | `config.py` fields and `_derive_deadlines` (defaults from `model_fields`, no repeated literals); `test_budget_defaults_keep_reads_fast_and_writes_independent` | ✓ |
| Six values independently configurable from the environment | `test_each_budget_environment_value_changes_only_its_owner` (6 cases) | ✓ |
| Explicit read must fit the voice share; caps ≤ totals; read ≤ write ≤ summary | `_read_fits_voice_share`, `_exchange_caps`, `_deadlines_nest`; invalid-value tests with exact `match` (M3) | ✓ |
| One `Budget` model; every `Deadline` carries its cap; no global fallback | `clock.py`; all constructions: `availability.py:67`, `booking.py:190/219/298`, `summary.py:109`, `ops_client.py:144`, `server.py:269`, `dev/bench.py:318`; no other `Deadline(` in source | ✓ |
| Write deadline covers schedule re-check, caller lookup, auth and retry; never reset or extended | one `Deadline` per write invocation passed through `_schedule_gate` / `_reschedule_gate` / `_write`; `test_write_schedule_and_caller_list_share_one_total` (same object); booking test asserts exactly one deadline with `remaining() == 3.0 − delay` | ✓ |
| `REQUEST_TIMEOUT_SECONDS`, `ALLOW_BUDGET_OVERRIDES` removed, no compatibility path | residual search (my run and `residual.txt`): no matches outside excluded history; `test_only_per_budget_exchange_fields_and_voice_budget_remain` | ✓ |
| Unexpired token used immediately (even inside margin); missing/expired single-flight; 401 unchanged; background renewal | `TokenCache.get` (usable before and after the lock); token matrix ×9 (read/write/summary × valid/absent/expired, 3 concurrent callers, one refresh); `test_write_401_refresh_keeps_frozen_body_and_key` (two POSTs, same body and key, one token call); `test_background_refresh_renews_before_token_expiry` | ✓ |
| Retry arithmetic with auth time and the 0.05 s floor; same body/key; honest `UNCERTAIN` | `test_retry_boundaries_include_auth_schedule_and_floor` (8 cases on exact binary values for both boundaries); `test_create_beyond_exchange_cap_retries_frozen_write_then_is_uncertain` (two POSTs, same body/key, exact warning fields 1000/2000/True then 1000/1000/False) | ✓ |
| Timer starts before the awaited service; one `tool_result`; privacy-safe | async `observed()` (`tools.py`); `test_tool_duration_includes_awaited_service_once` (fake clock advanced inside the operation, 125 ms, one record); safe fields are bounded integers, a bool, and exception names from the httpx-derived known set (`server.py:64–69`) | ✓ |
| Schema byte-identical, version 2026-10-11.2 | my run: `make schema` = snapshot; snapshot and `prompt.py` unchanged since base | ✓ |
| Docs and decision | DECISIONS entry supersedes AR-06; `CLAUDE.md`, README, `PLAN.md` gate 3, `VOICE-TEAM.md` §8 consistent; no current doc still promises 0.30 s writes | ✓ |
| `rollout.env` values (D4) | six values present | ✓ (local precedence: M-1) |

### Latency L1–L7

| # | Evidence | Result |
|---|---|---|
| L1 ceiling only | `_exchange` returns on receipt; booking test with an immediate stub: clock unchanged, `asyncio.sleep` forbidden | ✓ |
| L2 no new calls, checks, sleeps, polling | owner-path lists asserted in the booking test; bench owner calls identical in all 14 scenarios | ✓ |
| L3 no success-path retry | exactly one POST on success; retries only in failure branches | ✓ |
| L4 reads unchanged | read defaults 0.30/0.30; read scenario medians unchanged or better | ✓ |
| L5 same owner calls on success, no token call | booking test paths and `/auth/token` absence; token matrix "valid" | ✓ |
| L6 timing on the existing line | one `tool_result`, `durationMs`; no new success log | ✓ |
| L7 before/after benchmark | medians/p95 stable or better; three single-sample p99 increases (O-1) | ✓ for merge review; confirm before deployment |

### Earlier stops and corrections

- **C1 lint (four long lines):** authorised wrap only (`C1-lint-correction.diff`), suite then 1220 passed. ✓
- **C3 red, floating point:** `pytest.approx(cap)` on that one comparison only (`test_ops_client.py:722`). ✓
- **M2:** tautology removed; the booking test now records the booking's own deadline and requires every cap `== 1.0`.
  Proof it now tests behaviour: in `C3-red-2.txt` the zero-delay cases fail under the old 0.3 cap (they passed
  before the correction). ✓
- **M3:** each invalid case has its message; the `write 9` case failed in red-2 for the old guard's message, so it now
  proves the nesting rule. ✓
- **Beyond-cap CREATE test:** added, fails under the old configuration, passes now with exact fields. ✓
- **C3 fast, watchdog:** only the factor `.3 → 3.0` changed in `test_bench.py:140` (`C3-watchdog-correction.diff`); the
  formula in `dev/bench.py:310–311` is `max(read, write)`, so the assertion now follows the new write default. No other
  assertion touched. ✓
- **C3-red-2 classification:** 19 failures, all old-configuration behaviour (old write defaults, remaining flag and
  guard, owner answers above the old cap). ✓

## Commands I ran (once each; outputs in `write-budget/.context/opus-final-review/`)

| Command | Result |
|---|---|
| `git rev-parse HEAD`, `git status --porcelain` | `f8618825…`, clean |
| plan SHA-256 | unchanged |
| `PYTEST_ADDOPTS=--tb=short timeout -k 10 900 make test-fast` (cleared variables) | exit 0, lint clean, **1295 passed**, 13 deselected |
| `make schema` vs snapshot (`cmp`); snapshot and `prompt.py` diff vs base | byte-identical; unchanged |
| residual `git grep` for the removed settings (plan §10 exclusions) | no matches |
| contradiction search for 0.30 s write promises in current docs/code | no matches |

**Inspected, not rerun (Astra's evidence):** `test-e2e.txt` (5 passed), `test-sh.txt` (all suites, sdist/wheel,
production and stub images, exit 0), `bench-before/after.txt`, `bench-compare.txt`, `trace.txt` (no matches),
`schema.txt`, `final-preservation.txt`, `final-plan-hash-after.txt`.

## Untested areas and release gates

- No live owner, ContextForge or voice-path run (by design). Real write latency, P/A/E on the canary and whether the
  1.0 s cap has enough margin are canary questions (plan §11 step 4, D2).
- **Gate D5:** the voice team confirms LiveKit `timeout` and `client_session_timeout_seconds`.
- **O-1:** paired 200-sample bench, or Garima's explicit acceptance, before deployment.
- Before deploying: record the running revision's image digest and environment (rollback target, plan §11 step 1).
- Merge and deployment each need Garima's approval.

## Summary for Garima

**Sound:** the core change does what we planned. Bookings get their own 3-second budget with 1-second calls; reads
stay at 0.30 s; summaries are unchanged. There's one consistent budget model, the old settings are gone, a valid token
is never refreshed during a call, retries and "uncertain" answers behave exactly as before, timing is logged safely,
and the published schema is untouched. My own run of the full fast suite passed (1295 tests) and the schema is
byte-identical.

**Needs fixing (small):** the local Docker setup repeats the six budget numbers and overrides `rollout.env`, so
changing `rollout.env` wouldn't take effect locally. Removing those six lines from the compose file and `.env.example`
fixes it. Production deployment isn't affected, but it breaks the "one place to change it" rule.

**Your action:** approve that small fix (Astra, configuration only). Before deployment: decide whether to accept the
benchmark's three single-sample p99 bumps as noise or run one larger benchmark, and get the voice team's LiveKit
timeout confirmation. Deployment readiness is not established yet.
