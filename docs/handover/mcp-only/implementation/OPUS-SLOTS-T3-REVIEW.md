# Opus review: T-3 (incomplete-response recorder and reproduction modes)

- **Commit reviewed:** `b49850d` ("Record incomplete HTTP responses in test servers"), base `cd9a084`.
- **Files:** `services/mcp/tests/conftest.py`, `services/mcp/tests/test_server.py`. No other file changed.
- **Brief:** `.context/astra-build-slots-t3.md` (identical to the attached copy).
- **Inputs read:**
  - `OPUS-SLOTS-T2-REVIEW.md`, `.context/astra-prompt-booking-b2-m1.md`;
  - the hand-back, design note, results, checks and library-source note;
  - all three mode drivers, the Mode 1 run JSON and all 40 logs, the Mode 2 JSON, log and recorder export, and every Mode 3 JSON and process log;
  - the self-incident JSON.
- **Code read:**
  - all of `conftest.py` and the new tests in `test_server.py`;
  - every `serving()` caller;
  - `test_e2e_processes.py`;
  - `src/frontdesk_mcp/server.py` and `cli.py` (read only);
  - installed uvicorn 0.53.0 (`protocols/http/httptools_impl.py`, `server.py`), sse-starlette 3.4.11 (`sse.py`), mcp 1.30.0 (`server/streamable_http.py`) and fastmcp 2.14.7 (`utilities/logging.py`, `__init__.py`).
- **No new experiments were run.** Every behaviour claim below that was not executed is marked "by reading".

## 1. Verdicts

| Item | Verdict |
|---|---|
| **Recorder (commit `b49850d`)** | **CHANGES REQUIRED (small).** The main detection path works. It identifies the exact request, correlates uvicorn's confirmation, keeps private data out, and fails the owning test for both direct and fixture callers. Three Medium defects remain: incidents after the test body are silently dropped (F-1); the incident branches swallow interrupts and cancellations (F-2); and the wrapper-to-uvicorn correlation works in one direction only (F-3). All three are test-only and none touches production. |
| **Investigation (Part B)** | **ACCEPTED as "not reproduced".** All three modes ran as briefed, the counts match the logs, and the one disclosed deviation made no difference. None of the three objective questions is established. |
| **Root cause** | **Not established.** The sse-starlette lead is a hypothesis from reading source. I checked it independently: it fits both T-2 observations exactly, but no runtime value was ever collected. |
| **Phase 4b** | **Not cleared by T-3.** I recommend one more narrow, deterministic check (T-4, §6) that confirms or rules out the lead, with the recorder fixes in the same commit. |

## 2. Findings (most severe first)

### F-1 (Medium): incidents after the test body are recorded, then thrown away

`conftest.py:366–370` checks `recorder.incidents` only when the body ends (direct callers). `conftest.py:52` and `:58` check it only when the test call ends (fixture callers). Nothing checks the list again:
- after the shutdown wait (`:377–388`);
- during fixture teardown, where `owner is asyncio.current_task()` is false, so `:366` is skipped.

The outer `finally` (`:389–395`) then removes the recorder.

- **What gets lost:** any incomplete response recorded while the server shuts down, or while a fixture tears down. That includes stream closures that finish after the client has returned. Nothing fails and nothing is printed.
- **Why it matters:**
  - **It breaks the brief.** A-5 requires that "an incomplete-response incident always fails the owning test".
  - **It hides the window that now matters most.** The current lead (§5) depends on what happens when a server shuts down, and that is exactly when incidents are discarded.
- **Fix:** after the bounded shutdown completes, check again for incidents not yet reported and raise. In the fixture case that appears as `ERROR at teardown`, which is honest.
- **Test:** an app whose incomplete response happens only after `should_exit` is set must fail.

### F-2 (Medium): incident branches catch everything, cancel out a cancellation nobody asked them to, and hide the original error

**Where:**
- `conftest.py:51–55` (`tracked`);
- `conftest.py:358–361` (`serving`).

**What the code does:** both catch `BaseException`. Whenever an incident exists, they:
- call `uncancel()`;
- raise `AssertionError(...) from None`.

**Problem 1: it swallows interrupts and exits.** `KeyboardInterrupt` and `SystemExit` raised in a body that has a recorded incident become an `AssertionError`. pytest then carries on instead of stopping. (By reading.)

**Problem 2: it cancels out other code's cancellations.** `uncancel()` should only undo a cancellation that this code itself issued, which in T-2's design is the watchdog's. For an outer `asyncio.timeout`, a `TaskGroup` or a Ctrl-C delivered as cancellation, the call consumes a request belonging to some other part of the code.
- The common case still ends as an `AssertionError`, because `uncancel` never goes below zero.
- Nested scopes can lose their cancellation.

**Problem 3: it hides the original error.** `from None` suppresses the context. When a test's own assertion fails, or the client raises, the reader sees only the incident report. The original traceback is not displayed.

**The existing test misses it:** `test_serving_recorder_preserves_ordinary_cancellation` (`test_server.py:408`) runs with no incident, so it cannot catch this.

**Fix:**
- Give the incident precedence only over `Exception`, with `raise ... from exc`.
- Treat `CancelledError` as the watchdog's only when `failure` (or `state.failure`) is set, and call `uncancel()` only in that case.
- Let `KeyboardInterrupt` and `SystemExit` propagate.

**Test:** an incident plus an outer `asyncio.timeout` must not have its cancellation consumed, and the original exception must stay visible as the cause.

### F-3 (Medium): the wrapper and uvicorn are correlated in one direction only

**(a) Unconfirmed incidents are not labelled.**

The wrapper's view of the response is the app's view, not the connection's:
- its `disconnected` flag means the app received `http.disconnect` (`:202–206`);
- its `started` and `complete` flags are set after `send()` returns (`:208–215`).

uvicorn tracks the connection itself:
- it marks the request disconnected in `connection_lost` (`httptools_impl.py:122–123`), whether or not the app ever calls `receive()`;
- after a disconnect, `send()` silently drops messages (`httptools_impl.py:467–468`), yet the wrapper still marks them started or complete.

**Result:** a client that disconnects while the app returns without reading `receive()` produces a wrapper incident, but no uvicorn line. Under the strict policy this fails a test labelled "Incomplete HTTP response". The confirmations list exists, but `failure()` (`:275–280`) never says whether each incident was confirmed. This is exactly the misleading attribution the review request asked about. It is rare, but it is possible.

**(b) The unmatched path discards the request it already knows.**

- **What uvicorn does:** it logs "returned without completing" only after the app has returned (`httptools_impl.py:420–441`).
- **What the code does:** `emit` reads the exact sequence from the request task (`:249`). When no incident matches, it calls `capture(None)` (`:254`), which:
  - discards that sequence;
  - builds `candidates` from requests that have **not** returned (`:232–234`). That excludes, by construction, the one request uvicorn is complaining about.
- **Result:** the report says "not established", although the request was known.
- **Why the self-test misses it:** `test_server.py:417–428` logs from the test task, where the sequence is `None` and no requests exist, and asserts `candidates == []`. It cannot detect this.

**My share of the blame:** the brief said "all candidate requests **open** at that moment". That wording was mine, and it is wrong for a log that appears only after the app has returned.

**Fix:**
- Label each incident `confirmed=true/false` in the failure line.
- When `emit` has a sequence but no match, record that request (flagged as "wrapper flags disagree") instead of `None`.
- Report candidates only when no sequence is available.

Each of these needs a real test: a request whose wrapper flags disagree with uvicorn's, not a log emitted by hand.

### F-4 (Low): the investigation design limits what the clean runs can say

- **Mode 2 and Mode 3 cannot exercise the leading hypothesis.** Each runs **one** server for the whole mode, as my brief prescribed. The sse-starlette lead (§5) needs a server to shut down and a later server in the same process to serve. So 4,000 clean sessions say nothing for or against it. This design gap is in my brief, not in Astra's execution.
- **Mode 1's null result is weak.** At T-2's observed rate of 2 in 36 runs, 40 clean runs happen by chance about 10% of the time (0.944^40). Using 4 in 46 (T-1's "2 of 10" plus T-2's 2 of 36) gives about 3%. So the null result is somewhat surprising, but it cannot be attributed. Possible causes include:
  - the recorder's extra layer changing timing;
  - the 19 new tests changing the run order;
  - different machine load;
  - luck.
- **Mode 3's detector has no positive control.** I confirmed by reading that it would see the line:
  - production sends `uvicorn.error` through the root JSON handler to stdout (`server.py:68`, `cli.py:52–53` with `log_config=None`);
  - the driver scans both stdout and stderr.

  But nothing proved it end to end.
- **Driver details:**
  - Mode 3's `seconds` field is overwritten by the client's loop duration (disclosed).
  - Mode 1 used `timeout 300` with no kill-after (disclosed). No timeout fired, so it made no difference to the results. It is still weaker than the brief's "hard" timeout, and future drivers should use `timeout -k`, as Modes 2 and 3 did.

### F-5 (Low): small tidiness points

- **Unused fallback:** `_task_evidence(task, limit, chain_info=None)` (`:123–124`) is never called without `chain_info`. Make it required. (Astra noted this herself.)
- **Dead assertion:** in `test_server.py:474`, the inner `assert not second.incidents` would itself be turned into the expected incident failure (F-2), so it can never fail usefully. Delete it; `:476` is the real check.
- **A test that mirrors a constant:** `test_serving_recorder_preserves_safe_library_message_and_logger` (`:479`) logs the allowlisted constant from the test and checks that it survives. I confirmed the string is real: `mcp/server/streamable_http.py:632`. The test is acceptable, but it proves only the pass-through.
- **Incident plus watchdog:** in the T-2 freeze shape (an incident followed by a frozen client), the `AssertionError` carries the incident report. The watchdog's later task dump survives only in the printed stdout (`:349`). Both are kept, so no change is needed. Reviewers should know to look in "Captured stdout".

### F-6 (Low, observation outside T-3's scope)

`test_serving_recorder_library_log_privacy` emits `logging.getLogger("fastmcp").warning("payload %s", {...})`. The recorder correctly drops it. However, fastmcp's own Rich console handler prints it with the argument formatted: Mode 1 log line 1 shows `WARNING payload {'patient': 'PRIVATE-PATIENT'}`. The value is synthetic.

The wider point: fastmcp installs that handler on import (`fastmcp/__init__.py:9–10`, `utilities/logging.py:56`, `propagate` false) unless `FASTMCP_LOG_ENABLED` is false. The adapter does not set it. In production, fastmcp warnings therefore bypass the adapter's JSON and privacy logging.

This is not a T-3 defect. It deserves a separate check against the CLAUDE.md log-privacy rule.

## 3. Requirement status

| Requirement | Status |
|---|---|
| A-1 request record | **Met.** All fields are present. Lifespan and websocket scopes pass through. Method, path and content type use allowlists. Header presence is recorded as true/false only. |
| A-2 wrapper as primary detector, uvicorn as confirmation | **Met for the main path.** The exact request is marked, and the confirmation is matched through a context variable local to the request task. I confirmed by reading that it does not leak between keep-alive requests or concurrent servers, and the concurrent self-test passes. **Partial** for the unmatched path and the confirmation label (F-3). |
| A-3 dump priority and classification | **Met.** Tasks with server or client frames sort right after the body. Unclassified and `contextlib` frames no longer overwrite a classification. The 11,800-character budget plus the header holds. The task cap and the classification through `contextlib` are tested with a genuine synthetic library frame (`:430–458`). |
| A-4 library logs | **Met, using the allowlist option.** Every non-allowlisted message is omitted, and arguments are never formatted. Logger names use an allowlist. The privacy test uses an already-formatted secret. sse-starlette's logger is not captured, but it logs only at DEBUG, so nothing is lost. |
| A-5 reporting | **Partial.** Incidents during the body fail the owning test, and a normal run stays quiet (the capsys checks pass). Incidents after the body are dropped (F-1). The strictness is disclosed as investigation-time only. |
| A-6 self-tests | **Met as specified:** the incident probe; subprocess ownership proof for direct, fixture, direct-error and fixture-error callers; log privacy; raised versus returned; a normal round trip; ordinary cancellation. **Untested:** an incident combined with an outer cancellation or interrupt (F-2); a realistic unmatched or unconfirmed incident (F-3); an incident after the body (F-1). |
| A-7 verification | **Met.** Rerun independently (§4). |
| Mode 1 | **Met.** 40 runs, each 67 passed, exit 0, no `FAILED` or `ERROR` lines, 0 incidents or watchdog firings, 1,083 s in total, stopped at the 40-run cap. Deviation: TERM-only timeout, which made no difference (F-4). |
| Mode 2 | **Met.** One `serving()`, 2,000 sessions, all completed with outcome `AVAILABILITY`, longest session 0.107 s, 85 s in total. The recorder saw 8,000 requests (POSTs answered 200 event-stream or 202), with 0 incidents, confirmations or warnings. `timeout -k 5` outside, 10 s per session inside. |
| Mode 3 | **Met.** Processes and arguments match `test_e2e_processes.py`, with an unmodified adapter at `LOG_LEVEL=WARNING` and a separate client process. 2,000 of 2,000 sessions completed. The adapter's stderr contains only the two known Authlib deprecation warnings, and its stdout is empty: 0 incomplete-response lines, 0 ASGI exceptions. The client wait is bounded, with a kill on expiry. |
| Self-incident versus spontaneous incident | **Kept separate.** `slots-t3-self-incident.json` is the deliberate probe and is labelled as such. No spontaneous incident occurred in any mode. |
| Reporting rule and stop rule | **Met.** The hand-back says "not reproduced", makes no claim that production is safe, labels the sse-starlette lead a hypothesis, and proposes no fix. |

## 4. Verification I ran

| Command | Result |
|---|---|
| `timeout -k 10 300 uv run pytest tests/test_server.py -q -p no:cacheprovider -k "recorder or watchdog or serving"` | 19 passed, 48 deselected, in 15.07 s (`.context/opus-t3-focused.txt`) |
| `timeout -k 10 600 make test-fast` | 1,112 passed, 11 deselected, 2 Authlib warnings, in 56.44 s, exit 0 (`.context/opus-t3-fast.txt`) |
| `make schema` to a file, then `stat`, `shasum -a 256` and `cmp` against the snapshot | 64,111 bytes, SHA-256 `3ef91e78…6c62`, **byte-identical**, exit 0 |
| `git diff --check cd9a084 b49850d` | clean |
| `git diff --quiet cd9a084 b49850d -- services/mcp/src services/mcp/dev pyproject.toml uv.lock deploy docs` | no change |

**Not run:**
- `./scripts/test.sh` (Astra's run is recorded and passing; the verdict does not depend on the process tests or the image builds);
- the reproduction modes (no repeats, as instructed);
- any probe for F-1 to F-3 (all three are established by reading the code).

## 5. The investigation's evidence and limits

1. **Which request:** not established. No spontaneous incident occurred.
2. **Which component:** not established.
3. **Production-shaped setup:** not established. Modes 2 and 3 were clean, which means "not reproduced in 2,000 sessions" each, and their single-server design cannot test the leading hypothesis (F-4).

### The sse-starlette lead, checked against source (still a hypothesis)

I confirmed each step of the hand-back's note in the installed source:

1. **The flag is process-wide and never reset.** `AppStatus.should_exit` is a class attribute (`sse.py:184`). The package only ever sets it to True (`:134`, `:214`); nothing sets it back to False.
2. **The watcher remembers one particular server.** `_shutdown_watcher` finds the uvicorn server through the current SIGTERM handler (`:100`). uvicorn installs that handler from the main thread, which is where the tests run (`uvicorn/server.py:332–344`). The watcher then checks every 0.5 s, and copies that server's `should_exit` into the shared flag once it sees it (`:126–141`).
3. **Once the flag is set, every later stream is cut short.** `_listen_for_exit_signal` returns at once when the flag is True (`:407–408`). `cancel_on_finish` then cancels the response's task group (`:510`).
4. **That produces exactly the T-2 symptom.** `_stream_response` sends `http.response.start` first (`:361–367`) and the final `more_body: False` only at the end (`:385`). A cancellation in between leaves the app returning normally after starting, but not completing, its response. That is exactly F-1's signature in T-2: a normal return, a response started but never finished, very early in the new server's life.
5. **It also explains the T-2 run-8 cascade.** The flag stays set for every later server in the same pytest process. Whether each stream finishes before the immediate cancellation is a scheduling race, which fits the intermittent `FFFF.F....F.F....F` pattern.
6. **Why it would usually be invisible in production.** Production has one server per process, so the flag becomes True only at a real shutdown, which is the behaviour sse-starlette intends. The tests use MCP's event-stream responses: production mounts streamable HTTP (`server.py:164`), and mcp uses `EventSourceResponse` (`streamable_http.py:25, 668`).

**What is missing:**
- the runtime value of the flag at any incident;
- which server the watcher had captured;
- evidence that this branch actually ran.

So this remains the best-supported lead, not a cause. It is also cheap to settle deterministically.

## 6. Next step (T-4): narrow, test-only, no fix

**Objective:** establish whether sse-starlette's process-wide `AppStatus.should_exit`, once set during one test server's shutdown, makes a later server in the same process return incomplete event-stream responses.

**Acceptance criteria:**

1. **A deterministic probe.** It runs in one process and is driven exactly as the tests drive servers. It must:
   - serve one MCP request on server A, which starts the watcher;
   - set `should_exit` on A and keep the loop alive for at least 0.6 s, so the watcher can observe it;
   - start server B and run one MCP session against it.

   It records, for every step:
   - `AppStatus.should_exit` (true/false);
   - whether the watcher was running;
   - whether the watcher's captured server is A (compared by identity, never by repr);
   - the recorder's incidents and confirmations.

   It is repeated N times, with the counts reported.
2. **A control.** The same sequence with the flag back at its default before B, done inside the probe only, so that the comparison isolates the flag.
3. **Recorder additions, test-only and read-only:** each incident records `AppStatus.should_exit` and whether the watcher was running.
4. **The F-1, F-2 and F-3 fixes in the same commit,** each with the test named in §2.
5. **A report** marking the lead **established** or **refuted**.
   - If established: say whether the effect is confined to multiple servers per process. Any remedy goes in a **separate reviewed brief**. Nothing is reset, patched or proposed in production code.
   - If refuted: report it plainly, and say whether further investigation is warranted.
6. **The same hard limits as T-3:**
   - only the two test files are committed;
   - probes stay in `.context/` and use `timeout -k`;
   - every run is preserved.

**Phase 4b:** start it after T-4 reports. T-4 is a single short, deterministic step, not another campaign.

## 7. Plain-English summary for Garima

**The recorder works for the case that matters.** When a test server half-sends a reply, the recorder:
- names exactly which request it was;
- confirms it against the server's own error line;
- keeps private data out;
- fails the right test.

**Three small fixes are still needed in the test code:**
- it currently ignores problems that happen while a server is shutting down;
- it can swallow Ctrl-C or a timeout;
- when its own view and the server's view disagree, it doesn't say which request it was.

**The investigation was honest, but it did not catch the bug.** About 7,000 attempts were all clean. That means "not reproduced", nothing more.

**There is one strong suspect.** A library used for streaming replies keeps a "server is shutting down" flag shared by the whole test process. In the tests, once one server shuts down, that flag can stay switched on and cut off replies from the next server. That matches both earlier symptoms:
- the half-sent reply;
- the run of failures that followed it.

In production, each process runs only one server, so this would normally only matter at real shutdown. **It is still a suspect, not proven.**

**Recommendation:** one short, deterministic test (T-4) to confirm or rule it out, with the three fixes in the same commit. Then phase 4b. No production change.
