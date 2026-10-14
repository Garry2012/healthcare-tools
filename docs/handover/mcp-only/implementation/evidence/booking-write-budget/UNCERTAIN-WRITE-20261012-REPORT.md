# Uncertain appointment write, call 9f201655 (12 Oct 2026, 22:13:54 UTC)

Investigation only. No code, Azure, appointment or live-write change. Evidence files in this folder:
`window-lines.txt` (22:10–22:20 UTC, redacted), `day-raw.json`, `booking-outcomes.tsv`.
Langfuse traces were not accessible from this workspace.

## Timeline (Azure Log Analytics, revision --0000005, image 01b9dcc)

| UTC | Event |
|---|---|
| 22:11:34.02 | `get_doctor_availability` → DOCTORS_MATCHED / ASK_WHICH_DOCTOR |
| 22:12:00.56 | `get_doctor_availability` → AVAILABILITY / OFFER_APPOINTMENT_REQUEST |
| 22:13:54.364245 | WARNING `ops_write_unanswered`, path `/appointments`, attempt 1 |
| 22:13:54.364528 | `manage_booking` → UNCERTAIN / SAY_UNCERTAIN_AND_TRANSFER (0.3 ms after the warning) |
| 22:14:32.27 | `record_call_summary` → SAVED (`cs_68d6474e`) |

No `ops_write_unanswered` attempt 2, no `ops_write_retry_inconclusive`, no `ops_write_server_error`.

## Code path (main = deployed; `git diff 01b9dcc origin/main -- services deploy rollouts` is empty)

- `booking.py:219` creates one `Deadline(write_deadline_seconds)` before the schedule gate; the gate's
  reads (`:220`) and the POST (`:229`) share it.
- Deployed config sets no deadline variables (env names: ENV, HOST, PORT, OPS_*, MCP_BEARER_TOKEN,
  PROVIDER_ID, DOMAIN_PACK, TENANT_*), so `config.py:140–155` derives write deadline = read deadline =
  request timeout = 1.0 − 0.65 − 0.05 = **0.30 s**.
- `ops_client.py:236–249`: each exchange is capped at `min(remaining, request timeout)`; hitting the cap is
  re-raised as `httpx.ReadTimeout`.
- `ops_client.py:299–304`: any `httpx.RequestError` after the request may have left sets `sent`, logs
  `ops_write_unanswered`, and retries only if `remaining ≥ max(0.05, 1.5 × elapsed)` (`:321–324`);
  otherwise `UncertainWrite`.
- `booking.py:167–169`: `UncertainWrite` → UNCERTAIN / SAY_UNCERTAIN_AND_TRANSFER / NO_VERIFIED_RESPONSE.

## What the evidence proves

- **Fact:** the POST was attempted once and ended in an `httpx.RequestError` raised after the request may
  have been sent (only that branch logs `ops_write_unanswered`).
- **Fact:** not a 502/504, a 5xx, a malformed body or an MCP parsing problem: those paths log differently or
  return a different detail (`MALFORMED_SUCCESS`).
- **Fact:** no retry was started; UNCERTAIN followed the warning within 0.3 ms.
- **Fact:** Manoj's UI shows the appointment NOTED, so the owner committed it.
- **Not proven:** which `RequestError` it was; the warning does not log the exception type or elapsed time.
- **Strong inference:** the 0.30 s budget ran out. The same budget first paid for the schedule gate's
  `/slots` read, leaving well under 0.30 s for the owner's create; a cap-induced `ReadTimeout` leaves
  ~0 s, which fails the retry rule. Langfuse span durations for trace `ba22403465d69daeace385d41e354090`
  (total close to 0.30 s) would confirm it.

## Recurrence

Since revision --0000005 (11 Oct 21:49 UTC): 8 CREATE/RESCHEDULE results, **2 NOTED (01:17, 01:55 UTC),
then 6 UNCERTAIN in a row (08:58–22:13 UTC)**, each with a single `ops_write_unanswered` attempt 1.
This is a design/configuration issue, not an isolated incident: a confirmed write (schedule re-check +
owner create) is held to the same 0.30 s voice-turn budget as a read.

## Safety

MCP behaved safely: it did not claim success or failure, wrote nothing twice and returned the desk
handoff disposition. Reconciliation was possible in principle: an identical retry with the same
`X-Operation-Id` uses the same Idempotency-Key and Manoj replays the original result, unless the schedule
re-check refuses it first; LIST shows the appointment only if `patientMobile` was the verified caller's
number.

## ABANDONED

Chosen by the voice agent: `record_call_summary` stores the `outcome` argument as given
(`summary.py` validates, never selects). It is consistent with A17 only if no transfer and no callback
happened, and it hides a booking that exists. `VOICE-TEAM.md` has no summary row for an UNCERTAIN booking.

## Smallest coherent next steps (each needs Garima's decision)

1. **Instrumentation:** add the exception type and elapsed/remaining milliseconds to `ops_write_unanswered`
   (reads already log the error type in `ops_unreachable`).
2. **Budget decision:** give confirmed writes their own budget (for example the POST gets its own deadline,
   separate from the schedule re-check, or a larger write deadline) — a change to the documented 0.30 s rule,
   so DECISIONS + code + tests.
3. **Doc:** a summary row for UNCERTAIN (desk handoff; mention the uncertain booking in `summaryText`).

## Evidence still needed

- Langfuse span timings for both traces.
- From Manoj, for the appointment carrying `callId` 9f201655-d483-4bb2-8567-11f464f2462d: request arrival
  time, Idempotency-Key, appointment id, commit time, HTTP status, response body and response time; the
  same for the five earlier UNCERTAIN calls (callIds starting 627c1594, 23ddc51a, b4da61e5, fca90519, 4f0d6b1a).

## Separate finding

10 `manage_booking` results since the deploy were IDENTITY_UNAVAILABLE (1 FOUND), including call 0de2e519
at 22:16:12 UTC. The verified caller number often does not reach MCP; this likely explains the
"agent didn't recognise my appointment" report.

## Budget experiment (13 Oct 2026, Garima-approved)

- Before: `before-state.txt` (revision --0000005, image 01b9dcc, no deadline variables). Applied 00:10:51 UTC
  (`apply.txt`): `WRITE_DEADLINE_SECONDS=3.0`, `REQUEST_TIMEOUT_SECONDS=3.0`, `ALLOW_BUDGET_OVERRIDES=true`.
  After: revision --0000006, same image, Healthy, 100% traffic, `/ready` 2026-10-11.2 with 3 tools (`after-state.txt`).
  Offline settings check: `experiment-config-check.txt`.
- Synthetic run (`experiment.py`, `experiment-run.txt`, `experiment-result.json`, `experiment-logs.txt`),
  call `budget-exp-fc5bf93830674b62a5f12c48fee0ffc2`, doctor a76ce94f…, 2026-10-14 14:00, synthetic patient:
  availability AVAILABILITY (4 open blocks) → CREATE **NOTED** (appointment 47e2b103-79f7-4517-af93-20a3174c0d81,
  slotTime 14:00, no `ops_write_unanswered`) → CANCEL **CANCELLED** → summary **SAVED** (`cs_4d02e965`).
- Client-observed call_tool times 2.7–3.4 s for every tool, including the availability read whose server work
  is capped at 0.30 s: ~2.9 s is this client path's transport overhead, so these numbers do not measure
  server time. Estimate for the CREATE's server work: ≈0.2–0.5 s (3.35 s − ~2.9 s), above the old 0.30 s.
- Summaries were not affected by `REQUEST_TIMEOUT_SECONDS`: `summary.py:109` gives them their own 8 s
  deadline and 8 s per-exchange cap.
- Timeouts beyond MCP: ContextForge `tool_timeout` default 60 s and `httpx_read_timeout` 120 s
  (local source v1.0.7+; deployed 1.0.11 sets no override among non-secret variables; `register.py` sets no
  per-tool `timeout_ms`). LiveKit `MCPServerHTTP` defaults `timeout=5` s and
  `client_session_timeout_seconds=5` s; the voice team's actual values are unknown and must be confirmed.

### Controlled repeat (13 Oct 2026, 00:20 UTC)

`experiment_runs.py`, `experiment-runs.txt`, `experiment-runs-result.json`, `experiment-runs-logs-final.tsv`.
Four runs, each with unique call and operation ids, same doctor, 2026-10-14 14:00, synthetic patient; no summaries.
All four CREATE → NOTED (appointments b04c35d5…, 8ebc1cf6…, 8adff87a…, a8a3d3ee…), each CANCEL → CANCELLED.
Server logs show one `tool_result` per step on revision --0000006 and no `ops_*` warning
(`ops_write_unanswered`, `ops_write_retry_inconclusive`, `ops_write_server_error`, `ops_timeout`).
Client-observed times 2.6–3.1 s per call (same client overhead as before; not server time).
Totals with 3 s budget: 5 of 5 CREATE NOTED. With 0.30 s since 11 Oct 21:49 UTC: 2 of 8.
Limits: one ~10-minute window (05:43–05:50 IST), one doctor and date, cached profile, MCP-direct client
(no ContextForge or LiveKit), no server-side timings.
