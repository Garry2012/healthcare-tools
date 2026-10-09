# Opus review: T-4 (recorder fixes and the sse-starlette flag probe)

- **Commit reviewed:** `6c8b90c` ("Preserve HTTP recorder incidents and cancellation"), base `b49850d`.
- **HEAD:** still `6c8b90c`, so there were no later commits to separate out.
- **Scope:** `services/mcp/tests/conftest.py` and `services/mcp/tests/test_server.py` only. I confirmed there is no change to `src/`, `dev/`, `pyproject.toml`, `uv.lock`, `Dockerfile`, `deploy/` or `docs/`.
- **Inputs read:**
  - the brief `.context/astra-build-slots-t4.md` (identical to the attached copy);
  - `OPUS-SLOTS-T3-REVIEW.md` and SLOTS-PLAN row T-4;
  - the hand-back and `astra-prompt-booking-b2-m1.md`;
  - the probe, its JSON, log, verdict script and verdict JSON, and the flag-writer search.
- **Code and source read:**
  - the full diff and the complete `serving`, recorder and boundary code;
  - every `serving()` caller;
  - installed sse-starlette 3.4.11 and uvicorn 0.53.0;
  - `cli.py`, `Dockerfile` and `deploy/azure/deploy.sh`.

## 1. Verdicts

| Item | Verdict |
|---|---|
| **Commit `6c8b90c` (recorder)** | **APPROVED.** All three T-3 findings are fixed and properly tested. Two Low findings remain (§2); neither needs to be fixed before 4b. |
| **Probe** | **Valid. CONFIRMED stands**, and I recounted it from the raw JSON (§4). |
| **Single-server conclusion** | **"No single-server risk found" is supported**, and correctly limited to this mechanism and this way of running the server (§5). |
| **Phase 4b stop condition** | **Not triggered.** The plan allows 4b now. The Low recorder findings are separate from that decision and do not gate it. |

## 2. Findings (most severe first)

### L-1 (Low): the late-incident check can attach a report to the wrong exception

**Where:** `conftest.py:411–416`.

**What it does:** after shutdown, the code chooses between "add a note" and "raise" using `sys.exception()`. But `sys.exception()` returns any exception currently being *handled* in the caller's frames, not only one propagating through `serving`.

**I checked it with a minimal standalone script.** `serving` exits normally inside the caller's `except` block, and the generator's `finally` sees the caller's `KeyError`.

**Impact:** if a test ever enters `serving` inside an `except` block, a late incident becomes a note on that unrelated, already-handled exception and is not raised. If the caller then swallows that exception, the incident is lost. No current caller does this: none of the 22 call sites sits inside an `except` block. So the risk is latent, not live.

**Smallest fix:** record the propagating exception explicitly, for example with `except BaseException as exc: propagating = exc; raise` around the inner body and shutdown, and use that instead of `sys.exception()`.

### L-2 (Low): a test helper finds its server through the process signal handler

**Where:** `test_server.py:476–495`.

`_ShutdownResponseApp`:
- finds the running server with `signal.getsignal(signal.SIGTERM).__self__`. That works only on the main thread, and only while a single server is running. Nested servers would find the most recent one.
- polls `server.should_exit` every 10 ms.

Both are bounded by the test's own timeout, and the tests pass. This is fragile coupling rather than a defect.

**Smallest fix:** give the app an event that `serving` sets (or that the test sets) when shutdown starts. Optional.

### Notes (no change needed)

- **Incident plus watchdog:** when both happen, the `AssertionError` carries the incident report, and the watchdog dump is in the printed stdout (`conftest.py:382`). This is unchanged from T-3 and both are kept.
- **Candidates overlap:** an unmatched uvicorn line with no sequence lists every request not marked complete, including requests that already have their own incident. That is a superset, which is harmless.
- **Untested exits:** `SystemExit` and `GeneratorExit` are not tested separately. By reading, they take the same path as `KeyboardInterrupt` (`conftest.py:77–81`: add a note, then `raise`), and `KeyboardInterrupt` is exercised in a subprocess.

## 3. What happened to the T-3 findings

### T-3 F-1 (incidents after the body dropped): FIXED

- **Reported once:** `failure()` reports only incidents not yet reported (`conftest.py:301–313`, using `_reported`), so each incident appears exactly once.
- **Checked after shutdown:** the final check runs after the bounded shutdown (`:409–416`). It raises when nothing else is propagating, and otherwise adds a note.
- **Cleanup always runs:** removing the handlers, closing the recorder, removing it from the body list and resetting the context variable sit in an inner `finally` (`:417–423`). They run even when reporting or shutdown fails.
- **Multiple recorders:** the `tracked` boundary joins every recorder's report (`:61–63`). Nested and concurrent recorders consume their own reports independently.
- **Tests:**
  - a late incident, direct case: `test_recorder_t4_reports_shutdown_incident_once[None]`;
  - a body failure plus a late note: `[body failure]`;
  - fixture teardown: `test_recorder_t4_exception_and_teardown_ownership[late-fixture]`, which shows `ERROR at teardown`;
  - a body incident and a shutdown incident reported separately, one each: `..._reports_body_and_shutdown_incidents_separately`;
  - the shutdown-limit error keeping its identity with a late note: `..._late_incident_does_not_replace_shutdown_limit`.

### T-3 F-2 (interrupts and cancellations swallowed, original error hidden): FIXED

- **One shared boundary.** `_http_failure_boundary` (`conftest.py:66–88`) replaces the two duplicated handlers.
- **Only the watchdog's cancellation becomes its failure.** A `CancelledError` becomes the watchdog `AssertionError`, and `uncancel()` runs, only when the watchdog has recorded a failure (`:74–76`). In `serving`, that failure is considered only in the owner's task (`:389`).
- **Ordinary exceptions stay visible.** An incident replaces only an `Exception`, and the original is kept as the cause (`:78–79`).
- **Everything else passes through.** Other `BaseException`s, including outer cancellations and interrupts, propagate unchanged, with the incident attached as a note (`:80–81`).
- **Tests, each in a subprocess for both direct and fixture callers:**
  - outer cancellation, reported as `CancelledError`;
  - the test's own failure, with `ORIGINAL_BODY_FAILURE` shown as the "direct cause";
  - `KeyboardInterrupt`: exit code 2, pytest stops, not reported as a failure.
- **Outer timeout:** `asyncio.timeout` still produces `TimeoutError`, with the incident attached as a note on its `CancelledError` cause (`test_recorder_t4_outer_timeout_keeps_cancellation`).
- **Watchdog tests:** the existing ones are unchanged and pass.

### T-3 F-3 (one-way correlation): FIXED

- **Labels:** every failure line carries `confirmed=true` or `confirmed=false` (`conftest.py:310`).
- **Known sequence, no wrapper incident:** that exact request is captured, with `flags_disagree=true` and `confirmed=true` (`:273–278`).
- **No sequence:** candidates are every request not marked complete, including requests that returned without finishing (`:253–255`).
- **Concurrency:** the confirmation finds its request through a context variable local to the request task. uvicorn logs right after the app returns, with no waiting in between (`httptools_impl.py:422–441`), so the confirmation cannot land on another request, and is set before anyone reads the report.
- **The real-uvicorn test genuinely exercises disagreement.** The app sends a header value containing a newline:
  - uvicorn sets `response_started`, then raises "Invalid HTTP header value." (`httptools_impl.py:475` onwards);
  - the wrapper never marks the response started, because `send` raised;
  - the app returns, and uvicorn logs the incomplete response.

  The test asserts one incident for sequence 1 `POST /mcp/`, with `flags_disagree=true` and `confirmed=true`.
- **Unconfirmed case:** tested at unit level, as the brief required, together with no-sequence candidates that include the returned-incomplete request.

### A-4 and A-5 (flag evidence and tidy-ups): MET

- **Read-only flag:** `sse_should_exit` is read only through `sys.modules.get("sse_starlette.sse")` and `getattr`. It is `None` when the module is absent (`conftest.py:248–250`). Committed code never imports or writes it; the only new import is the standard-library `sys`. The test covers absent, false and true.
- **Tidy-ups:** `_task_evidence`'s chain argument is now required (`:140`). The masked inner assertion is deleted, and the real one is kept (`test_server.py:461`).
- **Privacy:** unchanged from T-3.
- **Unused code:** Vulture found none.
- **Tests:** none weakened. The T-3 test of the unmatched case was replaced as the brief asked, and its no-sequence assertion now lives in the unit test.

## 4. Probe validity

**Driver (`.context/slots-t4-probe.py`):**
- one main-thread process;
- every phase in its own `asyncio.run` loop, so A and B have separate loops;
- the app built as in the tests, run through `conftest.serving`;
- each session limited to 10 s;
- run under `timeout -k 5 600`;
- 242 s in total.

**Observations:**
- **Server identity:** the probe wraps the uvicorn `Server` constructor only to keep a reference to the real instance. Behaviour is unchanged. It then compares that instance by identity with `signal.getsignal(SIGTERM).__self__` while A is still serving, after the session. That is equivalent to "at that moment" for a single server.
- **Watcher:** observed through sse-starlette's thread state, which a probe may read.
- **Hold:** 0.6 s after A's `serving` exits, in A's loop.
- **Resets:** at the start of every repetition, and between A and B in the comparison arm only.
- **Failures kept as data:** B's expected recorder `AssertionError` is caught and recorded as a measurement. A `serving` assertion with no recorder incident would have been recorded as a probe error; none was.

**My independent recount from `slots-t4-probe.json`:**

| | Treatment (20) | Comparison (20) |
|---|---|---|
| Arms alternate T, C, T, C… | yes | yes |
| Flag false at reset and at A's start | 20 | 20 |
| A session completed with `AVAILABILITY`, 0 incidents on A | 20 | 20 |
| SIGTERM handler is A | 20 | 20 |
| Flag true after A's hold | **20** | 20 |
| Flag true before B (and at B's start) | **20** | **0** |
| B has a confirmed incomplete `POST /mcp/`, with `sse_should_exit=true` | **20** (1 incident each, 0 `flags_disagree`) | **0** |
| B session | **20 hung** (10 s bound) | **20 completed** |
| Probe errors | 0 | 0 |

- **Timing:** B's incidents began 25–30 ms after B's server started. T-2 run 36 showed 28 ms.
- **The literal rule:** CONFIRMED requires at least 18 of 20 with the flag set, every one of those cut off, and a clean comparison. Every condition holds.
- **Retries:** none. The log has exactly 40 repetition lines and one final summary.

**What it does and does not show:**
- **It shows** that the mechanism exists and produces the T-2 signature on demand: a normal return, an event-stream response started but not finished, about 28 ms into the new server, followed by the client stuck in `Client._connect`.
- **It does not show** that this caused the T-2 run 36 freeze or the run 8 cascade. Those runs never captured the flag, and the 0.6 s hold makes the A→flag step certain where ordinary test timing would make it occasional.
- **The hand-back claims neither.** It says the same thing.

## 5. The single-server conclusion

I checked the cited sources:

- **What writes the flag:**
  - `AppStatus.should_exit` is set True only by the watcher (`sse.py:134`), when the server it captured has `should_exit`, and by the patched `Server.handle_exit` (`sse.py:211–224`), which is that server's own signal handler;
  - the class default is False (`:184`);
  - the flag-writer search found no other writes in the installed packages, and the repository's own code has none.
- **The uvicorn lifespan flags are a different thing.** `lifespan/on.py:60, 74` set `LifespanOn.should_exit`. A startup failure exits the process (`server.py:117`).
- **The production entry point runs one server:**
  - `cli.py:52` calls `uvicorn.run` once;
  - `uvicorn/main.py:622–632` creates one `Server`, and multiple workers would be separate processes;
  - the image `CMD` is `frontdesk-mcp serve` (`Dockerfile:20`);
  - `deploy.sh` sets the image with no other command, and its replicas are separate containers;
  - nothing in `src/` starts a second server.

So in this execution model, no path was found that sets the flag in a long-running server except that server's own shutdown.

**The stated limits are correct:**
- this is source reasoning, not a live Azure check;
- it is not a claim of general production safety;
- it is not protection against code that rewrites the flag at runtime.

**One related fact belongs on record, but it is not a stop condition.** At a real shutdown, for example Azure scaling in or replacing a revision, sse-starlette ends in-flight event streams at once, with no grace period. That is the library's intended drain behaviour, and Astra noted it ("no guarantee that in-flight streams complete during shutdown"). It does not affect a server that keeps running.

## 6. Verification

**Commands I ran:**

| Command | Result |
|---|---|
| `timeout -k 10 300 uv run pytest tests/test_server.py -q -p no:cacheprovider -k "recorder or watchdog or serving"` | 33 passed, 48 deselected, in 21.34 s (`.context/opus-t4-focused.txt`) |
| `timeout -k 10 600 make test-fast` | **1,126 passed**, 11 deselected, 2 Authlib warnings, in 50.54 s, exit 0 (`.context/opus-t4-fast.txt`) |
| `make schema` to a file, then `stat`, `shasum -a 256` and `cmp` against the snapshot | 64,111 bytes, `3ef91e78…6c62`, **byte-identical** |
| `uv run ruff check tests/conftest.py tests/test_server.py` | All checks passed |
| `uvx --offline vulture tests/conftest.py tests/test_server.py --min-confidence 80` | no findings, exit 0 |
| `git diff --check b49850d 6c8b90c` | clean |
| `git diff --quiet b49850d 6c8b90c -- src dev pyproject uv.lock Dockerfile deploy docs` | no change |
| a standalone Python check of `sys.exception()` inside an async context manager's `finally` | it confirms L-1 |

**Astra's recorded results that I did not rerun:**
- `./scripts/test.sh`: 1,126 hermetic tests, 2 process tests, the wheel and sdist, and both images (`.context/slots-t4-check-full.txt`, exit 0);
- the probe itself.

I didn't rerun the probe because the raw JSON covers every repetition and there is no evidence gap that would justify repeating it.

**The red runs I inspected are preserved:**
- the initial 12 failures and the corrected 13 failures;
- the two finalization regressions, made red against the `b49850d` recorder;
- one first green attempt that failed only on the order of pytest's summary counts. The new assertion checks the counts independently and rejects any `FAILED` line, so it is not weakened.

**Untested:**
- `SystemExit` and `GeneratorExit` (checked by reading);
- the historical cause of T-2;
- other library versions and HTTP backends;
- live shutdown and drain behaviour in Azure.

## 7. Phase 4b

The plan's T-4 row says: "After T-4 reports, 4b proceeds unless T-4 shows a genuine risk to a single long-running production server." T-4 found no such risk, so **the stop condition is not triggered, and 4b may start.**

**Kept separate from that decision:**
- L-1 and L-2 are optional test tidy-ups;
- a test-harness remedy for the confirmed mechanism (so that one test's server shutdown cannot cut off a later test's server) would be its own small brief, at Garima's discretion;
- LOG-1 (fastmcp's console logging) remains a separate item.

None of them blocks 4b.

## 8. Plain-English summary for Garima

**T-4 did its job.**

**The test recorder is fixed and approved.** It no longer:
- loses problems that happen while a server shuts down;
- swallows Ctrl-C or timeouts;
- forgets which request a problem belonged to.

**The suspect is confirmed.** When one test server shuts down, a library flag stays switched on, and the next test server in the same process then cuts off its replies. That happened in 20 of 20 runs. Switching the flag back off fixed it in 20 of 20.

**Production isn't affected by this mechanism.** Each container runs one server, so the flag only comes on when that server itself is shutting down.

**Still not proven:** that this flag caused the old intermittent freeze, although it produces exactly the same symptom.

Two tiny optional test tidy-ups remain. Nothing blocks phase 4b, and the plan's own rule says 4b can start now.
