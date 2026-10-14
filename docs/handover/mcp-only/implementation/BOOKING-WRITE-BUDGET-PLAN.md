# Booking write budget: permanent timeout configuration (plan, revision 7)

Status: **revision 7 (14 October 2026): in-call token policy corrected so the successful path never adds an
`/auth/token` call; 401-path wording corrected. Checked against `main` again. The Astra prompt is not
prepared yet.** Planning only: no code, commit, deployment or Azure change.
Based on `main` `e6b9193` (deployed code = `01b9dcc`; `git diff 01b9dcc e6b9193 -- services deploy rollouts` is
empty). Evidence: `.context/uncertain-write-20261012/` in the des-moines workspace.

## 1. Evidence

**MCP side (Azure logs, revision `--0000005`)**
- Production ran with read total = write total = per-exchange cap = 0.30 s (no deadline variables;
  `config.py:140–155`).
- Since 11 Oct 21:49 UTC: 8 CREATE/RESCHEDULE results, 2 `NOTED`, 6 `UNCERTAIN`, each `UNCERTAIN` with one
  `ops_write_unanswered` attempt 1 and no retry.
- Call `9f201655-d483-4bb2-8567-11f464f2462d`: `ops_write_unanswered` at ≈ 22:13:54.364 UTC; result
  `UNCERTAIN / SAY_UNCERTAIN_AND_TRANSFER / NO_VERIFIED_RESPONSE` 0.3 ms later.

**Owner side (Manoj, confirmed)**
- Appointment `874e98fc-66f3-442a-a4d3-2dada574246b`, call `9f201655-…`, correlation `70e3375a0e31439882cd195049d37db5`.
- Request received 22:13:54.263 UTC; committed 22:13:54.411; response sent 22:13:54.472 (`201`, `NOTED`,
  visit 2026-10-13, slotTime 18:30). Owner processing 209 ms, of which records-store work 155 ms in four calls.
- No error, warning or slow request recorded. Exactly one `POST /appointments` arrived (no duplicate).
- Manoj does not log the `Idempotency-Key`; when supplied it is stored with the response, and an identical
  same-key retry replays the stored `201`.

**Conclusion (confirmed by both logs):** MCP stopped waiting ≈ 101 ms after Manoj received the request, before the
commit and ≈ 108 ms before the `201`. About 200 ms of the 0.30 s total had already gone on the schedule re-check,
authentication and transport before the POST reached Manoj. The owner completed normally; the MCP budget was too
short.

**With the temporary canary settings (revision `--0000006`: write 3.0 s, global cap 3.0 s, override on):**
5 of 5 synthetic CREATEs `NOTED` on the first attempt with no write warnings (all cancelled), and the latest
voice-path booking also returned `NOTED`. A separate confusing voice conversation was an agent orchestration issue,
not a timeout.

**Outside MCP:** ContextForge `tool_timeout` 60 s and `httpx_read_timeout` 120 s by default, no override among the
gateway's non-secret variables, no per-tool `timeout_ms` in `register.py`. LiveKit `MCPServerHTTP` defaults:
`timeout=5`, `client_session_timeout_seconds=5`; the voice team's actual values are a deployment gate (D5).

## 2. Owner decisions

| | Decision |
|---|---|
| D0 | **Yes.** Confirmed booking writes get their own longer, configurable budget; reads stay fast. |
| D1 | `WRITE_DEADLINE_SECONDS` initial canary value **3.0**: provisional, configurable, to be tuned from timing data. |
| D2 | `WRITE_EXCHANGE_TIMEOUT_SECONDS` separate setting, initial canary value **1.0**. Pre-flight verifies only the retry arithmetic (§6) and the test design; **post-implementation canary evidence** decides whether 1.0 s is kept or adjusted through `rollout.env`. |
| D3 | **Remove `ALLOW_BUDGET_OVERRIDES`** everywhere; tuning uses the proper variables under normal validation; bench and external checks use explicit local/test configuration. |
| D4 | Record the selected operational values explicitly in `rollouts/demo-hospital/rollout.env`. |
| D5 | Voice team confirms LiveKit timeouts cover the write deadline + gateway + margin: **deployment gate**, not an MCP assumption. |
| — | Keep temporary revision `--0000006` active until the permanent deployment: rolling it back to the original configuration would restore 0.30 s writes. After the permanent deployment, the **preferred rollback** restores the recorded `--0000006` state (image `01b9dcc` with the temporary 3-second settings, §11 step 7); deploying the older source with its `rollout.env` restores 0.30-second writes. |

## 3. Current state: who owns each timeout

| Rule | Owner today | Used by |
|---|---|---|
| Read total | `read_deadline_seconds`, derived = voice budget − reserved − gateway (0.30) | `availability.py:67`, `booking.py:190` (LIST) |
| Write total | `write_deadline_seconds`, derived = same 0.30 | `booking.py:219` (CREATE), `:298` (CANCEL, RESCHEDULE incl. schedule gate and A15 list check) |
| Summary total + cap | `summary_deadline_seconds` 8, `Deadline(…, cap=summary)` | `summary.py:109` |
| Per-exchange cap | **global** `request_timeout_seconds`, default = **read** total; applies to every `Deadline` without a cap | `ops_client.py:240` (`_exchange`), `:124` (token lock wait), `:133` ("no time to refresh"), `:157` (token refresh) |
| Background token refresh | `token_refresh_timeout_seconds` 5, `Deadline(…, cap=budget)` | `ops_client.py:150` |
| Dependency probe | constant `DEPENDENCY_CHECK_SECONDS = 1.0`, `Deadline(1.0)` without cap | `server.py:49`, `:264` |
| Over-budget bypass | `allow_budget_overrides` | `config.py:157–167`; `dev/bench.py:253`; `tests/test_external.py:59`; tests listed in §9 |

**Defects:** (1) a write's exchange cap is the *read* setting, so raising the write total alone does nothing;
(2) the global cap also limits in-call token refresh for every tool and the dependency probe (1.0 s cut to 0.30 s);
(3) two cap mechanisms (`Deadline.cap` and the global fallback argument); (4) writes are bound to the voice turn
(`CLAUDE.md`, `test_settings.py:109–143`), so a usable write budget needed the bypass flag; (5) diagnosis gaps:
no exception type or timing on `ops_write_unanswered`, no log at all on the 502/504 branch (`ops_client.py:305–306`),
no duration on `tool_result`.

**Today's in-call token behaviour (`TokenCache.get`, `ops_client.py:118–137`):** a token outside its refresh margin
is used at once; a still-valid token inside the margin is used at once only when
`deadline.remaining() < request_timeout_seconds` (`:133`). With production's 0.30/0.30 that always holds for reads
and writes, so they never refresh in-call; a summary (8 s deadline) does refresh in-call before its POST. A naive
port of `:133` to "remaining < own cap" would make a 3.0/1.0 write refresh a valid token first: one extra
sequential `/auth/token` call of up to 1.0 s on a successful booking (violates L2/L5). §4 removes that rule.

## 4. Configuration model

One concept: a **budget** = total deadline + per-exchange cap. Every `Deadline` is built from a budget, so the cap
always travels with the deadline. No global cap, no tool-specific conditionals, one owner per rule.

| Budget | Total | Exchange cap | Code default | `rollout.env` (D4) |
|---|---|---|---|---|
| Read (availability, LIST) | `READ_DEADLINE_SECONDS` | `READ_EXCHANGE_TIMEOUT_SECONDS` | total derived from the voice budget (0.30); cap = read total | 0.30 / 0.30 |
| Write (CREATE, CANCEL, RESCHEDULE incl. their schedule re-check and A15 list check) | `WRITE_DEADLINE_SECONDS` | `WRITE_EXCHANGE_TIMEOUT_SECONDS` | 3.0 / 1.0 | 3.0 / 1.0 |
| Summary | `SUMMARY_DEADLINE_SECONDS` | `SUMMARY_EXCHANGE_TIMEOUT_SECONDS` | 8.0 / = summary total | 8.0 / 8.0 |
| Background token refresh | `TOKEN_REFRESH_TIMEOUT_SECONDS` (unchanged) | same value | 5 | not set |
| Dependency probe | constant 1.0 (unchanged) | same value, explicit | 1.0 / 1.0 | not set |

- **Removed cleanly, no compatibility path:** `REQUEST_TIMEOUT_SECONDS` and `ALLOW_BUDGET_OVERRIDES` (code, tests,
  compose, `.env.example`, deployment configuration, current docs). Historical evidence files are not edited.
- **Code defaults vs `rollout.env`:** `config.py` holds the defaults (used by tests and local runs); `rollout.env`
  records the deployed values explicitly (D4). Changing a deployed value is a `rollout.env` change and redeploy:
  no code or schema change.
- **Reads stay bound to the voice turn:** an explicit `READ_DEADLINE_SECONDS` must fit the voice share; this is a
  validation rule, not a bypassable guard. Distant-laptop runs (bench, external checks) raise
  `VOICE_RESPONSE_BUDGET_SECONDS` in their own local/test configuration, so the derived share fits their network
  (§8). Writes and summaries are independent of the voice share.

**Code shape (for Astra)**
- `clock.py`: frozen `Budget(total, exchange)`; `Deadline(budget, monotonic=…)`; `Deadline.cap` is always set;
  `Deadline.timeout()` takes no argument and returns `min(remaining, cap)`. The `cap: float | None` fallback and the
  `timeout(cap)` argument are deleted.
- `config.py`: the six fields; properties `read_budget`, `write_budget`, `summary_budget` returning `Budget` (the only
  place totals and caps are paired). `_derive_deadlines` derives the read total only; each unset exchange cap takes its
  own total. `request_timeout_seconds`, `allow_budget_overrides` and `_guard_budget_overrides` are deleted; the read
  rule moves into one validator (§5).
- Callers: `availability.py:67`, `booking.py:190/219/298`, `summary.py:109` → `Deadline(settings.<kind>_budget)`;
  `ops_client.py:124/157/240` → `deadline.timeout()`; `ops_client.py:133` ("no time to refresh") is **deleted** by the
  token policy below;
  `ops_client.py:150` → `Deadline(Budget(t, t))`; `server.py:264` → `Deadline(Budget(1.0, 1.0))`;
  `dev/bench.py:253–256/311` and tests → budgets.
- **In-call token policy (one rule for every tool):** `TokenCache.get` returns any **unexpired** token immediately,
  without taking the lock or checking the refresh margin. Only an absent or expired token triggers an in-call
  refresh (single flight under the lock, bounded by `deadline.timeout()`), and the existing 401 path
  (`tokens.invalidate()` then `get`, `ops_client.py:256–259`, `:281–285`) is unchanged. Proactive renewal inside the
  margin stays with the background refresher (`refresh_if_due`, `_keep_warm`, `ops_client.py:139–152`, `:221–224`),
  which keeps using `_fresh()` and `TOKEN_REFRESH_TIMEOUT_SECONDS`. Net effect versus today: reads and writes are
  unchanged (they already used the valid token); summaries stop refreshing in-call and use the valid token too.

## 5. Validation rules (startup, clear messages)

1. Each total `> 0`; read and write `≤ 30`, summary `≤ 60` (existing bounds).
2. Each exchange cap `> 0` and `≤` its own total.
3. `READ_DEADLINE_SECONDS ≤ WRITE_DEADLINE_SECONDS ≤ SUMMARY_DEADLINE_SECONDS` (existing nesting).
4. `READ_DEADLINE_SECONDS ≤` voice share (budget − reserved − gateway); no bypass.
5. Voice share `≥ 0.1` (existing).
6. LiveKit and ContextForge limits are not visible to MCP: documented as deployment gate D5, not validated.

## 5a. Latency requirements (highest priority)

The goal is to wait long enough for Manoj's real booking response instead of returning `UNCERTAIN`, never to make a
successful request slower. Each rule below is checked against the code and has a test or benchmark (§10, §11).

| # | Requirement | Why it holds in this design (code) |
|---|---|---|
| L1 | The larger write timeout is only a **ceiling**; a response is returned the moment it arrives. | `_exchange` awaits the HTTP response under `asyncio.timeout(min(remaining, cap))` (`ops_client.py:236–249`); the deadline never waits for itself. |
| L2 | **No new owner (REST) calls, sequential checks, sleeps or polling.** | The change touches only where the cap comes from and what is logged; no call sites are added. Bench declares each scenario's expected owner paths and reports the observed owner calls (`dev/bench.py:50–66`, `:138–144`). |
| L3 | **No extra retry on the successful path.** | A retry happens only inside the failure branches of `_write` (`ops_client.py:292–304`); a `2xx` returns at `:318`. Unchanged. |
| L4 | **Availability and LIST stay on the existing fast read budget** (0.30/0.30). | Read budget defaults and the voice-share rule are unchanged (§4, §5). |
| L5 | **The successful booking path performs the same owner calls as today** (schedule re-check reads, then one POST; no `/auth/token` call while an unexpired token exists). | `booking.py:219–232`, `:298–322` unchanged apart from the budget object. |
| L6 | **Timing goes on the existing `tool_result` line**, not an extra synchronous success log. | Today each tool evaluates `await services…` **before** calling the synchronous `observed()` (`tools.py:114`, `:149`, `:173`), so a timer inside `observed()` would measure only logging and serialization. `observed()` becomes one shared **async** helper that takes the service coroutine, reads `time.monotonic()` before awaiting it and after, and writes the single existing `tool_result` line with `durationMs`. No other success log; warning fields only on failure paths. |
| L7 | **Before-and-after benchmarks** compare read and successful-write latency; **any unexplained regression blocks deployment.** | §10 verification and §11 step 2. |

## 6. Retry arithmetic for the initial values (3.0 total / 1.0 exchange)

`_write` (`ops_client.py:270–319`) measures each attempt from just before the token lookup (`started =
deadline.remaining()` at `:277`, then `tokens.get` at `:279` and the POST at `:280`) and retries once, with the same
key and frozen body, only when `remaining ≥ max(0.05, 1.5 × elapsed)` (`:321–324`). The write deadline starts before
the schedule re-check (`booking.py:219–220`, `:298–302`).

- **P** = schedule work before `_write` (CREATE: slots read, profile usually cached; RESCHEDULE: A15 list read +
  slots read), all under the same write budget and 1.0 s cap.
- **A** = token/authentication time inside attempt 1: ≈ 0 whenever an unexpired token exists (used immediately,
  §4); non-zero only when the token is absent or expired, bounded by the 1.0 s cap.
- **E** = the POST exchange time of attempt 1 (at most 1.0 s).

Retry condition after attempt 1: **3.0 − P − A − E ≥ max(0.05, 1.5 × (A + E))**.

| Attempt 1 | Condition | Retry possible when |
|---|---|---|
| POST hangs until the 1.0 s cap (E = 1.0) | 2.0 − P − A ≥ max(0.05, 1.5A + 1.5); the 1.5 term always dominates | **P + 2.5·A ≤ 0.5** (P ≤ 0.5 only when A ≈ 0) |
| Fails instantly (E ≈ 0, stale connection) | 3.0 − P − A ≥ max(0.05, 1.5A) | **both P + A ≤ 2.95 and P + 2.5·A ≤ 3.0** |
| Answered normally | — | no retry needed. Manoj measured 209 ms **inside his backend**; network and adapter time are not included, so the POST's real margin under the 1.0 s cap is unknown until the canary measures it. |

The retry gets `min(remaining, 1.0)`. When the condition fails, the result is `UNCERTAIN` without a retry: safe, but
it marks the case the tuned values should cover.

**Who confirms what:** pre-flight verifies this arithmetic against the code and that the §10 tests pin both
boundaries. Runtime values cannot be confirmed before implementation; the post-implementation canary (§11 step 4)
supplies the evidence in §7, and decides whether the 1.0 s exchange cap is kept or adjusted (D2).

## 7. Observability (privacy-safe; never changes a result)

- `ops_write_unanswered`: add `error` (exception class name from the existing safe set), `elapsedMs`,
  `remainingMs`, `retry` (bool).
- New `ops_write_gateway_error` on the 502/504 branch: `status`, `elapsedMs`.
- `ops_write_server_error` and `ops_write_retry_inconclusive`: add `elapsedMs`.
- `tool_result`: add `durationMs` for the whole invocation, timed by the shared async `observed()` helper around
  the awaited service operation (L6). No new success log.
- `SAFE_LOG_FIELDS`: `elapsedMs`, `remainingMs`, `durationMs` as integers 0–600000; `retry` as bool. `path` stays the
  route template. No bodies, names, mobiles, reasons, query strings, tokens or secrets.

**What these logs can establish (and what they cannot):**
- **Successful write:** only `durationMs` ≈ P + A + E (plus small in-process work). P, A and E are **not** separable.
  Compare it with the **3.0 s write total**, never with the 1.0 s exchange cap: one write invocation contains several
  operations (schedule reads, any token work, the POST). Because P + A ≤ `durationMs`, the hang-retry condition
  P + 2.5·A ≤ 0.5 is guaranteed whenever `durationMs` ≤ 200 ms; above that it is unproven, not ruled out. Whether
  the 1.0 s exchange cap has enough margin for the POST itself is a canary question (§11 step 4).
- **Failed attempt** (`ops_write_unanswered` and the other write warnings): `elapsedMs` = A + E of that attempt and
  `remainingMs` after it, so P = write total − `remainingMs` − `elapsedMs` for attempt 1. A and E stay combined;
  in-call token trouble shows separately through the existing `ops_token_*` warnings.
- **Reads:** `durationMs` per availability and LIST call, for the before-and-after comparison (L7).

## 8. Bench and external checks without the bypass

- `dev/bench.py`: for a real host, set `voice_response_budget_seconds = BENCH_READ_DEADLINE + reserved + gateway`
  (read total derived), and explicit write/summary totals and caps; for stubs, defaults. No production-capable flag.
- `tests/test_external.py` fixture: the same pattern (read 6.0 derived from a local voice budget; write 8.0/5.0;
  summary 12.0/12.0). These live only in the test/bench code paths.
- Unit tests that used the flag (`test_availability.py:360,452`, `test_booking.py:249,411,680`,
  `test_ops_client.py:146,369`, `test_settings.py`) switch to a voice budget or budget values that pass validation.
- Pre-flight confirms `make bench` (stub) and the external suite's collection still work.

## 9. Ordered commits (each passes `make test-fast`)

1. **Budget model.** `Budget`, budget properties, six variables, delete `REQUEST_TIMEOUT_SECONDS`, migrate every
   caller. **Intentional corrections, named in the commit message and tested:** (a) the dependency probe's effective
   per-exchange cap becomes 1.0 s (was 0.30 s through the global cap); (b) in-call token policy (§4): every tool uses an
   unexpired token immediately and refreshes in-call only when the token is absent or expired, or after the existing
   401 invalidation; the `:133` "no time to refresh" rule is deleted. Reads and writes behave as today; summaries no
   longer refresh a still-valid token before their POST. The background refresher keeps renewing. Read and write
   defaults stay 0.30/0.30 in this commit.
2. **Observability** (§7). Independent of the budget values. `observed()` in `tools.py` becomes the one shared async
   helper that awaits each tool's service coroutine between two `time.monotonic()` readings (the three call sites at
   `tools.py:114`, `:149`, `:173` pass the coroutine instead of its awaited result).
3. **Write budget and bypass removal (D0, D1, D2, D3).** Write defaults 3.0/1.0, independent of the voice share;
   read rule without bypass; delete `ALLOW_BUDGET_OVERRIDES`; migrate bench and external checks (§8); replace the
   AR-06 write assertions; DECISIONS entry (supersedes the "writes are an in-call turn" rule).
4. **Docs.** `CLAUDE.md` deadline rule, `.env.example`, `deploy/docker-compose.yml` (drop the flag), 
   `services/mcp/README.md`, `PLAN.md` gate text, `VOICE-TEAM.md` §8 "Time budgets" (writes may take up to the write
   deadline; D5 guidance). Doc only; no schema.
5. **Rollout values (D4).** The six values in a commented "operational budgets" block in
   `rollouts/demo-hospital/rollout.env`.

## 10. Test matrix (hermetic; fake clocks and stubs, no sleeps)

| Area | Tests | Files |
|---|---|---|
| Defaults | read 0.30/0.30, write 3.0/1.0, summary 8/8 | `test_settings.py` |
| Overrides | each of the six variables changes only its own budget, from the environment | `test_settings.py` |
| Invalid | cap > total; read > write; write > summary; read > voice share; flag and `REQUEST_TIMEOUT_SECONDS` no longer fields | `test_settings.py` |
| Independence | read expiry does not affect a write; write cap does not lengthen reads; summary unaffected by read/write values | `test_ops_client.py`, `test_booking.py`, `test_summary.py` |
| Owner delay | answer inside the write cap → `NOTED`; beyond it → `UNCERTAIN` with one warning carrying `error`, `elapsedMs`, `remainingMs`, `retry` | `test_ops_client.py`, `test_booking.py` |
| Retry | hang to the cap: P + 2.5·A ≤ 0.5 → one same-key retry with identical frozen body and `Idempotency-Key`; just above → no retry, `UNCERTAIN` (including a slow in-call token); instant failure: P + A ≤ 2.95 and P + 2.5·A ≤ 3.0 → retry; remaining below the 0.05 floor → no retry | `test_ops_client.py` (extend `:241`, `:491`) |
| Rejection vs uncertain | 4xx on attempt 1 → `REJECTED`; 5xx, 502, 504 after send → `UNCERTAIN` (+ gateway log) | `test_ops_client.py` (extend `:501`) |
| Actions | CREATE, RESCHEDULE (schedule gate + A15 list inside the write budget), CANCEL | `test_booking.py` |
| Token | (1) a still-valid token **inside the refresh margin** produces **no `/auth/token` call** for a read, a write (3.0/1.0 budget) and a summary; (2) a missing or expired token refreshes **exactly once** (single flight, bounded by the invocation's cap), for each budget; (3) the existing 401 path is unchanged: the first POST returns 401, the token is invalidated and refreshed once, and the same request is repeated once (**two POSTs**: the rejected one and its authenticated repeat, same frozen body and `Idempotency-Key`); for writes this occurs only on attempt 1, before any unanswered attempt has made the result uncertain; (4) background `refresh_if_due` still renews inside the margin | `test_ops_client.py` (extend `:416`) |
| Probe | `/dependencies` uses 1.0/1.0 regardless of read settings | `test_server.py` |
| Reads unchanged | availability and LIST behaviour and outcomes identical | existing suites |
| Logging | new fields pass `SAFE_LOG_FIELDS`; no private values; 502/504 now logged | `test_server.py` LOG-1 tests |
| Schema | `make schema` byte-equal to the snapshot; `SCHEMA_VERSION` unchanged | interface tests |
| Latency L1 | deterministic: fake monotonic clock and a stub that answers immediately; CREATE returns `NOTED` with the clock not advanced towards the 3.0 s ceiling and no sleep or wait call made. Real latency is measured only by the before-and-after bench | `test_booking.py`, `test_ops_client.py` |
| Latency L2/L5 | recorded owner calls for successful CREATE, RESCHEDULE, CANCEL, availability and LIST are identical before and after (same paths, same count, same order) | `test_booking.py`, `test_availability.py`, bench owner-call assertions |
| Latency L3 | a successful write makes exactly one POST and, with an unexpired token, no `/auth/token` call | `test_ops_client.py` |
| Latency L6 | one `tool_result` line per call with `durationMs`; with a fake clock advanced inside the service operation, `durationMs` includes that time (proves the timer starts before the await); no other success log line | `test_server.py` |

**Verification (each command once, output saved):** `make test-fast`;
`make schema | cmp - services/mcp/tests/contracts/mcp-tools.snapshot.json`; `make test-e2e`;
**`make bench` (stub) on `main` before the change and on the branch after it, same machine, same samples**, comparing
p50/p95/p99 for every read scenario and `booking_create`; any regression not explained by measurement noise
blocks the merge (L7);
`./scripts/test.sh` (lint, suites, package, Docker build);
`git grep -n -E "REQUEST_TIMEOUT|request_timeout|ALLOW_BUDGET_OVERRIDES|allow_budget_overrides" -- . ':!docs/handover/mcp-only/implementation/BOOKING-WRITE-BUDGET-PLAN.md' ':!docs/handover/mcp-only/implementation/*evidence*' ':!docs/handover/mcp-only/implementation/LATENCY-RESULTS.md' ':!docs/handover/mcp-only/implementation/REVIEW-REPORT.md' ':!docs/DECISIONS.md'`
returns nothing. The excluded files are this plan, historical evidence and the DECISIONS log, which name the removed
settings on purpose; the new DECISIONS entry may name them as removed, older entries are not rewritten.

## 11. Deployment and rollback

1. Independent pre-flight review (§13) → Astra → Opus code review → merge (Garima).
   **Before deploying, record the rollback target:** the running revision's image digest
   (`az containerapp revision show … --query properties.template.containers[0].image` and
   `az acr repository show -n <acr> --image frontdesk-mcp:01b9dcc --query digest`) and its full environment-variable
   list (names, plain values, secret references only), saved with the deployment evidence.
2. **Latency gate (L7):** the before-and-after stub bench from §10 shows no unexplained regression; otherwise stop.
   Then `deploy/azure/deploy.sh rollouts/demo-hospital --profile live --dry-run`, then the real deploy from `main`.
   `--replace-env-vars` (`deploy.sh:183`) replaces the container's variables with the base set plus `rollout.env`,
   removing the temporary `REQUEST_TIMEOUT_SECONDS` and `ALLOW_BUDGET_OVERRIDES`.
3. Confirm with `az containerapp show … env[].name`: the six budget variables present with the `rollout.env`
   values; neither removed variable present; `/ready` shows schema `2026-10-11.2`.
4. Synthetic journey (approved, synthetic patient): availability → CREATE → LIST → CANCEL, 3–5 runs, ideally in
   Indian working hours and with two doctors, plus one RESCHEDULE. From `durationMs`, `elapsedMs` and `remainingMs`
   collect `durationMs` for every call and the warning fields for any failed attempt (§7 says what each can show);
   the client measures the same journey with the same script as the 13 Oct baseline. Decide D2: keep 1.0 s, or tune
   `WRITE_EXCHANGE_TIMEOUT_SECONDS` / `WRITE_DEADLINE_SECONDS` in `rollout.env`.
5. **Gate D5:** voice team confirms LiveKit `timeout` and `client_session_timeout_seconds` ≥ write deadline +
   gateway + margin (recommend 8–10 s for 3.0 s writes). Then one end-to-end voice booking with the test patient,
   cancelled afterwards.
6. Log and latency check: write `durationMs` well under the 3.0 s write total; availability and LIST `durationMs` within
   the 0.30 s read budget; client-measured times for the same synthetic journey no worse than the 13 Oct
   baseline (`.context/uncertain-write-20261012/experiment-runs.txt`); no `ops_write_unanswered` in normal runs.
   Any unexplained regression blocks keeping the deployment.
7. **Rollback.** `deploy.sh` always builds the current source and pushes it as `frontdesk-mcp:$TAG`
   (`deploy.sh:99,116`), so setting `TAG` to an older value does **not** redeploy the older image and would
   overwrite that tag. Never reuse an existing tag. Two supported paths:
   - **Immutable image (preferred, fastest):** restore the recorded revision exactly:
     `az containerapp update -g healthcare-rg -n mcp-demo-hospital-canary --image <acr>.azurecr.io/frontdesk-mcp@sha256:<recorded digest> --replace-env-vars <recorded environment list>`.
     This returns to revision `--0000006`'s working state (image `01b9dcc` with its temporary write settings), not
     to the unreliable 0.30 s configuration.
   - **Verified previous commit:** a clean worktree at the recorded previous `main` commit, `deploy.sh` with its
     default tag (that commit's short SHA). It rebuilds that source; use it only when the source, not just the
     image, is the rollback target, and note that its `rollout.env` does not carry the temporary write settings.
   - **Value-only problem:** change `rollout.env`, review, merge, redeploy (no rollback needed).
   The temporary override is never reintroduced by the permanent code.
8. **Clean-up check:** no `ALLOW_BUDGET_OVERRIDES` or `REQUEST_TIMEOUT_SECONDS` in Azure, `rollout.env`,
   `.env.example`, compose or current docs; revision `--0000006`'s temporary settings gone.

**Schema and ContextForge:** settings are not part of the tool schema, so `make schema` stays byte-identical,
`SCHEMA_VERSION` stays `2026-10-11.2`, and no ContextForge refresh is needed.

## 12. Requirement traceability

| Requirement | Design | Test |
|---|---|---|
| Reads fast and independent | read budget unchanged, bound to voice share | Independence, Reads unchanged |
| No global timeout leaking | global cap deleted; cap travels with each `Deadline` | Independence, Probe, Token |
| Summaries independent and unchanged | summary budget 8/8 | Independence |
| Six settings independently configurable | §4 variables | Overrides |
| Config-only future tuning | `rollout.env` values | Overrides, deploy step 3 |
| `REQUEST_TIMEOUT_SECONDS` removed cleanly | commit 1 | Invalid, grep check |
| `ALLOW_BUDGET_OVERRIDES` removed cleanly | commit 3, docs commit 4 | Invalid, grep check |
| Idempotency, frozen body, retry identity, `UNCERTAIN` | `_write` logic unchanged | Retry, Rejection vs uncertain |
| Auth, tenant, caller, privacy | untouched; LOG-1 extended with safe integers | Logging, existing suites |
| Invalid combinations fail at startup | §5 | Invalid |
| Timing logs | §7 | Owner delay, Logging |
| Tool surface and schema unchanged | no tool changes | Schema |
| Bench and external workflows keep working | §8 | `make bench`, external collection |
| Latency L1–L7 | §5a | Latency rows, bench before/after, deploy steps 2 and 6 |
| No token call on the normal path | §4 token policy | Token, Latency L3 |

## 13. Pre-flight review scope (required before Astra)

- Every `Deadline` caller (§3, §4) and every use of `request_timeout_seconds` / `REQUEST_TIMEOUT_SECONDS` and
  `allow_budget_overrides` / `ALLOW_BUDGET_OVERRIDES` across code, tests, bench, compose, env examples, deploy and docs.
- The retry arithmetic in §6 (P, A, E, including the 0.05 s floor) for 3.0/1.0 against `ops_client.py:270–324` and
  `booking.py:219/298`, and the test design that pins it. Runtime evidence comes from the canary after
  implementation, not from pre-flight.
- The in-call token policy (§4): no `/auth/token` call on any successful path while an unexpired token exists;
  refresh only when absent or expired, or after a 401.
- Latency requirements L1–L7 (§5a): no added owner calls, sleeps, polling, sequential checks or success-path
  retries; reads unchanged; timing on the existing `tool_result` line only.
- Both intentional corrections in commit 1, and that nothing else changes behaviour there.
- Bench and external workflows without the bypass (§8).
- Schema byte stability and no ContextForge refresh.
- Deployment configuration (`rollout.env`, `deploy.sh` replace semantics) and the rollback paths in §11 step 7
  (recorded digest and environment; tag reuse ruled out).

## 14. Risks and non-goals

**Risks**
- A 3.0 s write means up to ~3 s of silence after "yes" if the owner is slow; the agent needs a short filler line
  (voice team) and LiveKit must allow it (D5).
- Retries are now more likely to happen; they stay safe (same key, frozen body; Manoj replays the stored `201`),
  and a refused retry stays `UNCERTAIN`.
- The schedule re-check inside a write may wait up to the write cap before refusing.
- A stale local `.env` that still sets a removed variable is ignored (`extra="ignore"`); Azure is safe because
  `deploy.sh` replaces all variables. Covered by docs and the grep check; no runtime shim.

**Non-goals:** changing tool outputs, outcomes, retry constants, Manoj's API, ContextForge or LiveKit settings;
slower reads; queues or background writes.
