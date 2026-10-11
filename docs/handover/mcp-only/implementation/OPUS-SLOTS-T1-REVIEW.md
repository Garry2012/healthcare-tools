# Opus review: T-1 (bounded HTTP test-server shutdown)

- **Commit:** `2912208aca125157f147fa08fd2034550643bbb8`, "Bound HTTP test server shutdown"
- **Base:** `5c139ea521d6109d7bfd01aa374c86193c22854c`
- **Branch:** `Garry2012/slots-phase-1a-1b` (HEAD = review commit)
- **Inputs:**
  - brief `.context/attachments/HpRyhx/astra-build-slots-t1.md`
  - `.context/astra-prompt-booking-b2-m1.md`
  - `.context/slots-t1-handback.md`
  - `.context/slots-t1-stall-analysis.md`
  - the full diff and both complete files
  - every `serving()` caller (`test_server.py:50, :371`, `test_booking.py:703–711`, `test_deploy.py:277–302`)
  - installed uvicorn 0.53.0 (`Server.serve`/`shutdown`, `LifespanOn`)
  - every preserved stall trace (3b, 4a ×2, T-1 runs 4 and 7)
- **Versions:** fastmcp 2.14.7, mcp 1.30.0, uvicorn 0.53.0, httpx 0.28.1, anyio 4.15.1, pytest-asyncio 1.4.0, Python 3.13.13.

## Verdicts

1. **T-1 implementation: CHANGES REQUIRED. It is not approved as is.**
   - It works for what it targets: a server whose shutdown is stuck but responds to cancellation.
   - One demonstrated defect: after cancellation the wait is unbounded (F-2).
   - More importantly, **the evidence shows that T-1 targets the wrong place** (F-1). That mistake is mine: my 3b and 4a reviews, and the T-1 brief, misread the traces.
   - The recommendation is to keep only a minimal shutdown bound (or none) and drop the uvicorn-internal diagnostic machinery.
2. **Phase 4b: hold it for a short, time-boxed investigation (T-2)** of the real stall, which happens while a test is running, not at shutdown (§3).
3. **Verification is not entirely green.**
   - 2 of Astra's 10 `test_server.py` repetitions stalled (runs 4 and 7, both counted as failures).
   - Every other required check passed in Astra's and my own runs.

## 1. Findings

### F-1 (High for the plan; mine): the stalls happen while the test runs, not at server shutdown; T-1 bounds a wait that has never been seen to hang

- **Evidence (verified independently).** In each preserved trace I located the faulthandler dump that came **before** the first `KeyboardInterrupt`. All five show the main thread in the **test-call phase**, with the event loop idle:

  | Trace | Lines before the interrupt | Main thread |
  |---|---|---|
  | `.context/slots-3b-interrupted-green.txt` | 8–61 | `selectors.select` ← `pytest_asyncio … Runner.run` ← `_pytest/python.py:167 pytest_pyfunc_call` ← `runner.py:184 pytest_runtest_call` |
  | `.context/slots-4a-testsh-interrupted.txt` | 17–70 | the same |
  | `.context/slots-4a-testsh-interrupted-2.txt` | 907–961 | the same (test `test_log_lines_carry_the_call_id_not_the_caller`) |
  | `.context/slots-t1-repeat-server-4.txt` | 1–54 | the same |
  | `.context/slots-t1-repeat-server-7.txt` | 1–54 | the same |

- **Where the earlier reading went wrong:** the `served` → `conftest.py serving: await task` → `uvicorn capture_signals` frames appear only **after** the manual SIGINT. When uvicorn exits, its `capture_signals` re-raises the captured SIGINT, and pytest then tears down the fixture. My 3b review (L-2) and 4a review (L-2) read those post-interrupt frames as the hang location. That was wrong, and it led directly to the T-1 brief. Astra's stall analysis reads the traces correctly.
- **Consequence:**
  - No shutdown stall has ever been observed.
  - The real stall is an idle-loop wait during an HTTP client test body. It hits different tests in different runs: the log-privacy test, and the model-supplied-identity test according to collection order. That stall is **unaddressed** by T-1, and T-1 could not have caught it (its bound applies only after the test body ends).
  - Astra rightly reported that no shutdown diagnostic fired in runs 4 and 7.
- **Impact:**
  - T-1 adds about 50 lines of uvicorn-internal machinery (frame inspection of `LifespanOn.main`, coroutine await-chain walking, owned-task cancellation, listener closing) for a hypothetical failure.
  - That conflicts with the proportionality requirement of the code-quality standard.
  - It is also tied to uvicorn's private structure: `conftest.py:59–64` relies on the coroutine name `main` and `self is server.lifespan`. It is scoped correctly to this server instance, but a uvicorn upgrade would silently empty the set.
- **Recommended correction:**
  - **Option A (recommended):** replace `conftest.py:68–114` with a minimal bound. Wait for the server task with a time limit; on expiry cancel it, wait a bounded time, and raise an `AssertionError` naming the limit. Drop the lifespan frame matching and the diagnostic walker. Keep the stuck-shutdown and normal-shutdown self-tests, simplified. Put the evidence capture where the stall actually is (T-2, §3).
  - **Option B:** revert T-1 entirely. The pre-T-1 `await task` has never been shown to hang.

  Either way, record in the plan that L-2's "shutdown" diagnosis was wrong.

### F-2 (Medium for T-1's own goal; demonstrated): the cleanup after cancellation is not bounded

- **Where:**
  - `tests/conftest.py:110`: `await asyncio.gather(*owned, return_exceptions=True)` after `cancel()`;
  - `:113`: `await listener.wait_closed()`.
- **Reproduction:** probe `.context/opus_t1_probe.py`, output in `.context/opus-t1-probe-output.txt`. It runs `serving(app, shutdown_limit=0.5)` inside an outer `asyncio.timeout(8)`:
  - lifespan shutdown stuck but responding to cancellation → `AssertionError: test server shutdown exceeded 0.5s` after **1.05 s**. Correct.
  - lifespan shutdown that **ignores cancellation** (it catches `CancelledError` and keeps waiting) → never returns. The outer 8 s `asyncio.timeout` cannot interrupt it, because `gather` waits for all its children. The process was killed by the external `timeout 45` (exit 124).
- **Impact:** the helper's guarantee to "fail fast instead of freezing" does not hold for a task that shields or absorbs cancellation. anyio-based code can do that during cleanup (shielded cancel scopes), so this is a realistic hazard. The real case is not proven here.
- **Hypothesis, not demonstrated:** on Python 3.12+, `Server.wait_closed()` also waits for active connections. A connection that outlives the forced exit could block `:113` in the same way.
- **Note:** my T-1 brief said "cancel it and await it". It should have said "await it with a time limit". This defect follows from the brief.
- **Correction (if any shutdown bound is kept):** replace both awaits with `asyncio.wait(..., timeout=<small>)`, list any survivors in the failure message, and raise regardless.

### F-3 (Low): stray `print` in the self-test

- **Where:** `tests/test_server.py:78`: `print(message)`.
- **Impact:** harmless (pytest captures it), but it is debug output in a committed test.
- **Correction:** remove it; the assertions already check the message.

### What T-1 does correctly (verified)

- **Normal path unchanged** (`conftest.py:68–70`): `asyncio.wait` returns as soon as the task finishes, then `await task` re-raises ordinary server exceptions. Timing and output are the same. `test_serving_normal_shutdown_stays_fast_and_quiet` asserts under 1 s, no output and no warnings. An exception from the test body is chained, not lost.
- **Diagnostic captured before force or cancel; bounded; no caller data:**
  - it holds counts, lifespan-shutdown flags, at most 8 tasks (owned first), qualnames and `basename:line` only;
  - custom task names are replaced by `<custom>`;
  - the self-test asserts that `PRIVATE42` is absent and the message is under 4,000 characters.
- **Scope of cancellation:** only this server's task, its lifespan task and its request tasks. The self-test proves an unrelated task survives.
- **Where the failure surfaces:** on the owning test. For `served` users it is a fixture-teardown error; for direct `async with serving(...)` users it is a test-call error.
- **Self-test strength:** it proves the bound and timing (0.5–2 s), that lifespan shutdown started but not finished (captured before cancellation), that every owned task is done, that no tasks leaked, exact-port reuse, and that a fresh server restarts on that port. The red run of the old helper was bounded by a test-level timeout (`.context/slots-t1-red-unbounded.txt`).
- **Nothing else touched:** no production, configuration, lockfile, schema or docs change (`git diff --quiet` over `src`, `dev`, `pyproject.toml`, `uv.lock`, `deploy`, `docs`). Every existing test is unchanged.

## 2. Commands run (independently, at `2912208`)

| Command | Result |
|---|---|
| `uv run pytest tests/test_server.py -k "serving_bounds or serving_normal"` | **2 passed** |
| `make test-fast` (via `rtk proxy`) | **1,095 passed**, 11 deselected, 2 Authlib deprecation warnings (pre-existing) |
| `make schema > .context/opus-slots-t1-schema.json`, then `/usr/bin/cmp` with the snapshot | 64,111 bytes; **cmp exit 0** |
| `git diff 5c139ea 2912208 --check` | Exit 0 |
| `git diff --quiet` over `src`, `dev`, `pyproject.toml`, `uv.lock`, `deploy`, `docs` | No change |
| Probe `.context/opus_t1_probe.py` (2 scenarios, unbuffered, external `timeout 45`) | Cooperative: bounded, 1.05 s. Cancellation-ignoring: **hung until killed (exit 124)**. See F-2 |
| Pre-interrupt phase of all five stall traces (`awk` between the faulthandler line and the first `KeyboardInterrupt`) | All five in `pytest_runtest_call` → `pytest_pyfunc_call` → `selectors.select`. See F-1 |

**Astra's runs, read and accepted as recorded** (`.context/slots-t1-repetition-results.json`; I did not rerun them):

| Run | Result |
|---|---|
| `make test-fast` × 5 | 1,095 passed each |
| `tests/test_server.py` × 10 | **8 passed (50 each); runs 4 and 7 stalled, then exit 130** |
| `test.sh` | Exit 0, including the 2 process tests, package and both images |

Across these runs no shutdown diagnostic fired. I did not run `test.sh` this time: the commit changes test code only, and I ran the fast suite and schema independently. Earlier in the series I ran `tests/test_server.py` 20 times without a stall (3b and 4a reviews). The stall reproduces in Astra's environment (2 of 10 here), not in mine so far.

## 3. What the stalls indicate

- **Not a T-1 regression.** The same idle-loop, test-call stall predates T-1: it appears in the 3b and 4a traces, before T-1 existed.
- **An unresolved, separate problem.** Some HTTP client test bodies sometimes wait forever on I/O that never arrives. The client and server run on one event loop. It has hit at least two different tests: the log-privacy test, and the model-supplied-identity test according to collection order.
- **Not enough evidence for a root cause.** The faulthandler dumps show threads, not asyncio task await chains, so it is unknown whether the wait is on the client side (the fastmcp `Client` and streamable-HTTP transport, test-only), the server side (the FastMCP or mcp streamable-HTTP session manager, **production code path**), or session start or exit.
- **Hypotheses only:**
  - a lost wakeup or race in the streamable-HTTP session lifecycle when client and server share one loop;
  - a race that shows up only under machine load (Astra's environment) and not in quieter runs.
- **Why this matters before deployment:** if the wait is on the server side, a real voice-agent tool call could hang until the gateway gives up. That is why I recommend investigating before 4b adds more HTTP-based runs (bench, end-to-end).

**Recommended T-2: investigation, time-boxed, test-only, no production change unless the evidence proves a cause:**
1. Add a watchdog to the HTTP client tests (the `served` fixture): if the test body exceeds a limit (for example 20 s), dump every pending asyncio task's await chain (`task.get_stack()`, plus the coroutine chain via `cr_await`), using the same privacy rules as T-1's diagnostic. Then fail the test.
2. Run `tests/test_server.py` repeatedly where it reproduces (Astra's environment, about 20%) until the watchdog fires at least once, or stop at a fixed run count. Preserve every failure.
3. Classify the chain as client, server, or session start/exit, and report. If it is server-side, bring it to Garima before any fix. If it is client-side, the fix is test-only.

This can **replace** most of T-1's machinery. T-1's diagnostic walker is the right idea but attached to the wrong phase.

## 4. Summary for Garima

**What I got wrong, and its effect:** in my 3b and 4a reviews I read the freeze traces wrongly. The "server shutdown" frames I pointed to were printed only after Astra pressed Ctrl-C. Before that, all five freezes were in the middle of a test, with the program waiting for a reply that never came. I sent Astra to fix server shutdown, which wasn't the problem. Astra spotted this and reported it honestly.

**T-1 itself:** well built, but aimed at the wrong place. It also has one gap: in a rare case its cleanup can still hang. I recommend reducing it to a simple time limit (or removing it), rather than keeping 50 lines of machinery for a problem we've never seen.

**The real freeze:** it is still there (2 of Astra's 10 runs). We don't yet know whether it is in the test client (only affects tests) or in the server (could affect real calls).

**Next step:** a short investigation (T-2) that records exactly what the program is waiting for when it freezes. Then we'll know whether it matters for real calls. I recommend that before 4b.
