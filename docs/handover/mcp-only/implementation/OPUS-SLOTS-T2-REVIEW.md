# Opus review: T-2 (bounded shutdown clean-up, HTTP test watchdog, freeze capture)

- **Commits:**
  - A `dfae5caf3ea08ea64134099c4a3ec59d1816e228`: "Simplify and bound test server shutdown cleanup"
  - B `cd9a084c79669757ae9261788a151e180bf97030`: "Capture stalled HTTP test bodies with a watchdog"
- **Base:** `2912208`
- **Branch:** `Garry2012/slots-phase-1a-1b` (HEAD = B)
- **Inputs:**
  - brief `.context/attachments/RQLoOj/astra-build-slots-t2.md` (byte-identical to `.context/astra-build-slots-t2.md`)
  - `OPUS-SLOTS-T1-REVIEW.md`
  - `.context/astra-prompt-booking-b2-m1.md`
  - `.context/slots-t2-handback.md`
  - `.context/slots-t2-freeze-analysis.md`
  - the run files listed in §3
  - both diffs and the final `conftest.py`/`test_server.py`
  - every `serving()` caller
  - installed uvicorn 0.53.0 (`protocols/http/httptools_impl.py:420–446`)
  - fastmcp 2.14.7, mcp 1.30.0
- **Scope:** test infrastructure only. `git diff --quiet 2912208 cd9a084` over `src`, `dev`, `pyproject.toml`, `uv.lock`, `deploy`, `docs` shows no change.

## Verdicts

| Item | Verdict |
|---|---|
| **Commit A** (shutdown clean-up) | **APPROVED** |
| **Commit B** (watchdog) | **APPROVED as a diagnostic tool.** Low notes in §1; none blocking |
| **The investigation (Part C)** | **Did its job:** a freeze was captured and the stop rule was honoured. It establishes **a server-side protocol failure** in the frozen test, but **not its cause**, which request was affected, or whether production is affected |
| **Phase 4b** | **Not yet.** First do one narrow follow-up investigation, T-3 (§4). It is test-only, with a time limit, and changes no production code |

Verification is **not all green**. Two of the 36 investigation runs failed (8 and 36). Every other check I ran passed.

## 1. Findings

### F-1 (High, open; established by evidence, cause unknown): the server returned an incomplete HTTP response in the frozen test

- **What the evidence establishes (`.context/slots-t2-server-run-36.txt:72–76`):**
  - The test's own server started at `00:06:35.395636` on port 53693.
  - **28 ms later**, uvicorn logged `ASGI callable returned without completing response.` at `00:06:35.423446`.
  - The watchdog fired 20 s after that.
  - So the error **precedes** the watchdog's cancellation and was not caused by it.
- **What that log line means** (installed `uvicorn/protocols/http/httptools_impl.py:432–444`): the line is logged only in the `else` branch, which means **the ASGI app returned normally, without raising**, after it had **started** a response it never completed. The connection was not marked disconnected. Uvicorn then closes the transport.
  - An exception would have logged `Exception in ASGI application` instead.
  - So some request handler in the server stack returned early, after starting its response, without raising.
- **What is not known:**
  - which request it was (initialize POST, the GET event stream, or another);
  - which component returned early (the FastMCP or mcp streamable-HTTP session manager, Starlette routing, our app's auth or middleware, or something else);
  - why it returned early.
- **Impact:** this is the server code path that production uses. Whether it can happen with **one** server per process (the production shape), as opposed to many sequential servers in one test process, is unknown.
- **Next step:** the T-3 investigation (§4). No fix and no production change, as the stop rule requires.

### F-2 (Medium, open): once it happens, failures continue for the rest of the test process (run 8)

- **Evidence:** `.context/slots-t2-server-run-08.txt:1` shows `...............FFFF.F....F.F....F`: **eight failures in one process** after the first 15 passes. The duration (179 s) fits several 20-second watchdog firings. Each test creates a **fresh** server on a fresh port, so a one-off race in a single server would not explain a run of failures.
- **What this suggests (hypothesis only):** some process-wide state survives from one server instance to the next.
  - Every server's lifespan starts FastMCP's Docket worker, visible as `docket/worker.py` and `burner_redis/pubsub.py` tasks in the dump.
  - That worker uses an in-memory backend and a thread (`asyncio/threads.py to_thread`).
  - That is a candidate. It is **not** established.
- **Limits of the evidence:** run 8's failure details were lost in buffering, so its watchdog status is unknown, as Astra recorded. From run 16, `-x` stops at the first failure, which preserves that failure's details but hides any further failures in the same run.
- **Next step:** T-3 must run without `-x`, so a run of failures is visible, and must test the one-server-per-process shape.

### F-3 (Low): the watchdog wraps every async test by replacing the test function at runtime

- **Where:** `tests/conftest.py:33–61`. The `http_test_body` fixture is autouse and replaces `request.node.obj` with a wrapper for **every** coroutine test.
- **Why it works:** pytest-asyncio reads `item.obj` when the test is called, after fixture setup. The self-test `test_serving_watchdog_fails_the_fixture_backed_test_call` proves this in a separate pytest process, and the run-36 capture went through this path (`conftest.py:53`).
- **Why mention it:**
  - it is a global change to how every async test runs, for a diagnostic;
  - it relies on that plugin behaviour, which is not a documented promise.
- **Correction:** none now. When the freeze is resolved, decide whether to keep the watchdog or remove it, and record the decision.

### F-4 (Low): the dump's size limits hide detail when many tasks are pending

- **Where:** `conftest.py:122–129`.
- **The limit:** the body task gets 3,000 characters. With the cap of 40 tasks, each other task gets about 225 characters, so long server-side chains shrink to a header plus a truncated middle. In run 36 (19 tasks) the `LifespanOn.main` chain was already truncated.
- **The classifier:** it uses the innermost frame that is not an asyncio or anyio primitive. That can be `contextlib` (giving `class=other`), as for `Client._session_runner`. Astra classified that one correctly by hand.
- **Correction (T-3, test-only):** give priority to tasks whose chain includes a `server` or `client` frame, and classify by the innermost **classified** frame.

### F-5 (Low): no self-test for an ordinary cancellation

- **The behaviour:** an ordinary cancellation (not from the watchdog) is re-raised unchanged (`conftest.py:48–50` and `:192–194`, where `failure is None` leads to `raise`). Reading the code, this is correct.
- **The gap:** no test asserts it.
- **Correction:** add one test where an outer `asyncio.timeout` cancels a body under `serving` and expect `TimeoutError`, not the watchdog `AssertionError`.

## 2. Review areas

### Part A: shutdown clean-up (commit A)

| Check | Result | Evidence |
|---|---|---|
| T-1's uvicorn-internal code and the stray print removed | **Pass** | Searching for `lifespan_tasks`, `server_state`, `wait_closed`, `gather(*owned` and `print(message)` in both files finds nothing |
| Both waits bounded, including after cancellation | **Pass** | `conftest.py:207` waits `shutdown_limit`, then `:211–212` cancels and waits **0.5 s**. There is no unbounded `await` or `gather` |
| Ordinary server exceptions propagate | **Pass** | `:208–209` (`await task` when it finished) |
| A cancellation-resistant task is reported honestly | **Pass** | Message `stopped after cancellation=False`. `test_serving_reports_a_server_task_that_ignores_cancellation` turns my T-1 probe case into a test that finishes in under 2 s |
| Blocked resources released, unrelated task kept, exact-port reuse | **Pass** | The self-tests release the blocked children, assert `unrelated` is not done, and restart on the same port |
| Commit A on its own | **Pass** | In a temporary worktree at `dfae5ca`, `-k serving_` gives **4 passed** |

### Part B: watchdog (commit B)

| Check | Result | Evidence |
|---|---|---|
| Covers direct `serving()` bodies and async-fixture callers | **Pass** | Direct case: the `owner` task is cancelled, and `:192–196` turns that into an `AssertionError`. Fixture case: `owner` is done, so the tracked call task is cancelled and `tracked` raises the `AssertionError` (`:51–53`). Proven by `test_serving_watchdog_captures_body_without_private_values` and by a separate pytest process (`test_serving_watchdog_fails_the_fixture_backed_test_call`: `1 failed`, no `ERROR at setup`) |
| ContextVar and wrapper across pytest-asyncio's setup, call and teardown tasks | **Pass** (F-3) | The state is set by the sync autouse fixture and reset in `finally`, and `node.obj` is restored, so nothing leaks between tests |
| No wrong-task cancellation, swallowed exception or changed semantics | **Pass** (F-5) | Only the owner task or the recorded call task is cancelled. If the body swallows the cancellation, the `AssertionError` is still raised (`:51–53`, `:197–199`). Ordinary cancellation is re-raised |
| Evidence captured before cancellation | **Pass** | `:182` builds the dump, then `:186` cancels |
| Await-chain walk, relative paths, classification | **Pass** (F-4) | Follows `cr_await`/`gi_yieldfrom`/`ag_await` with a cycle guard (96 steps); paths relative to `site-packages`, the repository or the standard library |
| Task cap, field truncation, total limit; privacy | **Pass** | The cap of 40 is asserted (`len(...) == 41`); size ≤ 12,000; the secret-like name, argument and number are absent; non-`Task-<n>` names become `<custom>`; no locals or reprs. The run-36 dump contains no caller data |
| Normal tests: no leaks or delays | **Pass** | `test_serving_watchdog_normal_http_round_trip_is_quiet`: no output, no warnings, no leftover tasks. Fast-suite duration is unchanged (about 48 s) |

### Investigation run handling

- **The `-x --capture=tee-sys` switch from run 16:** documented (handback lines 195–197). No failure was hidden or replaced:
  - runs 16–35 each report all **55** passing;
  - run 15 finished unchanged under the paused runner;
  - run 8 is kept as a failure;
  - run 36 stopped the loop as specified.
- **Limits:** 36 runs in 15 min 8 s; no external timeout fired.
- **Cost of `-x`:** it limits what can be seen about failures that follow the first (F-2).

## 3. The captured freeze: what is established and what is not

**1. Where the client is waiting (established):**
- **The test body:** `test_server.py:409` → `fastmcp/client/client.py:496 Client.__aenter__` → `:536 Client._connect` → `Event.wait`. It is waiting for the session's ready signal, so session start-up has not completed, and the test has not yet sent its tool call.
- **The session runner:** `client.py:649 _session_runner` is still entering its session context. Per Astra's reading of the source, the ready signal is set only after that returns or the runner exits.
- **The POST writer** (`mcp/client/streamable_http.py:554`) is idle, waiting for the next outbound message. **A shared `BaseSession._receive_loop`** (`mcp/shared/session.py:357`) is idle, waiting for an inbound message. Its role (client or server instance) cannot be told from metadata alone.
- **Net:** the client is waiting for a session-start response that never arrives.

**2. Server-side protocol failure (established, F-1):** in the same test's server, 28 ms after start and before any cancellation, a request handler returned normally with a started but incomplete response, and uvicorn closed that connection.

**3. Not proven (open):**
- that the incomplete response is the reason the client never became ready. This is likely, given the timing, but not proven;
- which request it was and which component returned early;
- whether the client should have surfaced the closed connection as an error instead of waiting. That would be a separate client-side defect, test-only for us, since our production client is the voice platform's;
- why failures continue within a process (F-2);
- whether a production-shaped server (one per process) can show it;
- **any production-safety conclusion, either way.**

**Hypotheses for T-3 to test, not conclusions:**
- process-wide state shared by the FastMCP Docket in-memory worker across sequential servers in one process;
- a race in the streamable-HTTP session start (initialize POST and the event stream) when client and server share one event loop.

## 4. Proposed next investigation: T-3 (narrow; test-only; time-boxed)

- **Objective:** identify **which HTTP request** returned an incomplete response and **which component** ended it, and determine whether this can happen in a **production-shaped** setup (one server per process, many sessions) or only when many servers start one after another in one test process.
- **Allowed changes:** `tests/conftest.py`, `tests/test_server.py` and a test-only probe script under `services/mcp/dev/` or `.context/`. No production, dependency, configuration, schema or documentation change. **No fix.**
- **Acceptance criteria:**
  1. **A per-request record for every request.** A test-only ASGI wrapper inside `serving` records method, path (no query), status, response content type, whether the response body completed, duration, and whether the app raised. For `mcp-session-id`, it records **presence only**, never values.
  2. **A trigger on the uvicorn error.** When uvicorn logs `ASGI callable returned without completing response`, a test-only handler on the `uvicorn.error` logger immediately records the pending server-side tasks (the T-2 dump format, with server-classified tasks first, F-4) and the matching request record.
  3. **Mode 1, the current suite.** `tests/test_server.py` **without `-x`**, until one capture with both records, or 40 runs, or 60 minutes. The number of failures per process is reported, which addresses F-2.
  4. **Mode 2, production-shaped.** One process, **one** `create_app` server for its whole life. Repeated client sessions (initialize, one tool call, close) up to 2,000 sessions or 30 minutes. Report whether an incomplete response ever occurs.
  5. **A report** naming the request and component, backed by the records, plus whether Mode 2 reproduces it, and what that implies for production. A server-side cause is reported to Garima with **no fix**. Any client or harness cause is described, not fixed.
  6. **Verification:** `make test-fast`, the schema byte comparison and `test.sh` all pass after the test-only changes. Every failing run is kept.
- **Phase 4b:** wait for T-3. If Mode 2 shows the problem cannot happen with one server per process, 4b can proceed with the watchdog in place, and the test-only cause gets its own fix brief.

## 5. Commands run (independently)

| Command | Result |
|---|---|
| `git diff --stat` for A and B; `git diff 2912208 cd9a084 --check`; `git diff --quiet` over `src`, `dev`, `pyproject.toml`, `uv.lock`, `deploy`, `docs` | Two test files only; no whitespace errors; no production, configuration or docs change |
| `timeout 120 uv run pytest tests/test_server.py -k serving_` (at B) | **7 passed** |
| Commit A on its own: temporary worktree at `dfae5ca`, `-k serving_` | **4 passed** (worktree removed) |
| `timeout 300 make test-fast` | **1,100 passed**, 11 deselected, 2 Authlib deprecation warnings |
| `make schema > .context/opus-slots-t2-schema.json`; `/usr/bin/cmp` with the snapshot | 64,111 bytes; **cmp exit 0** |
| `timeout 900 env -u OPS_E2E_BASE_URL ./scripts/test.sh` | **Exit 0**: lint clean; hermetic 1,100 passed; process e2e **2 passed**; package built; both images built; external gates not run. Log: `.context/opus-slots-t2-testsh.log` |
| Run 36 timeline and the uvicorn source branch | As in F-1 |
| Run 8 output | `FFFF.F....F.F....F` after 15 passes (F-2) |

**Not tested by me:**
- I did not run my own capture loop (Astra's environment reproduces the freeze; mine has not in 20 `test_server.py` runs during the 3b and 4a reviews, plus several full-suite runs).
- No external gates, live owner APIs, ContextForge or voice path.
- No production-shaped load test (that is T-3 Mode 2).

## Summary for Garima

**The two commits:**
- **A (tidy-up):** approved. The server shutdown now always gives up after a set time, even if something refuses to stop, and the leftover T-1 code is gone.
- **B (watchdog):** approved. It does exactly what we wanted: a frozen test fails after 20 seconds with a record of what everything was waiting for, and no private data. Astra's investigation used it to catch the freeze on run 36.

**What the capture shows:**
- **Client side:** the test client was waiting for the server to confirm a new session, and never got the confirmation.
- **Server side (the important part):** 28 milliseconds after that test's server started, the server itself logged that it had **started a reply and then stopped without finishing it**. That is a genuine server-side fault, not something the test or the watchdog caused.
- **What we don't know yet:** which request it was, which part of the server stopped early, or why.
- **A worrying sign:** in one run, once it happened, eight more tests failed in the same run. Something seems to linger inside the test process.

**Is production affected?** We can't say yet, either way. Our tests start many servers one after another in one process; production runs one server. That difference may matter.

**Next step:** one more focused, test-only investigation (T-3). It records every request so we can see which one broke, and runs a production-like setup (one server, thousands of sessions) to see whether it happens there too. No fixes until we know. Phase 4b waits for that answer.
