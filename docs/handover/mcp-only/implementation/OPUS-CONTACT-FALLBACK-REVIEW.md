# Opus review: call-summary contact fallback (partial commit A) and the `make test-fast` blocker

- **Scope:**
  - uncommitted changes on `Garry2012/slots-phase-1a-1b`, base `980da73`;
  - 5 files: `summary.py`, `test_summary.py`, `test_server.py`, `test_e2e_processes.py`, `test_external.py`;
  - the hand-back and `.context/contact-fallback/`.
- **Spec:** `CALL-SUMMARY-CONTACT-FALLBACK-PLAN.md`, revision 2 (approved) and the build brief.
- **Commit B:** not started, as expected. The descriptions, version and documents still describe the old rule **on purpose**; that is not a defect here.
- **Review only:** no fixes, commits or owner calls.

## 1. Verdict

| Item | Verdict |
|---|---|
| **The commit A draft** (code and tests) | **Correct and ready to commit once its gate passes.** No defect found. Two optional observations (§2) |
| **The `make test-fast` blocker** | **Almost certainly the known sse-starlette process-wide flag (T-4), occurring naturally, not a regression from this change.** That is an inference with strong evidence; it is not proven (§3) |
| **Stopping** | **Justified.** The repair is in `conftest.py`, outside the brief's allowed files |
| **Next step** | A separate, small test-setup repair needs **Garima's approval** (§4). Then rerun the gate once, then commit A |

## 2. Implementation review

### 2.1 Code (`summary.py:103–105`)

```python
if request.callerMobile is None and ctx.caller_number:
    mobile = identity.contract_mobile(ctx.caller_number, self.settings.tenant_country_calling_code)
    request = request.model_copy(update={"callerMobile": mobile})
```

**This matches the plan exactly:**
- it runs once, before the single `_validate` and `build_body`;
- only `None` is resolved, so an invalid explicit value still reaches `_validate` and is rejected;
- it reuses the strict converter;
- it is an immutable copy, with no change to `CallContext`;
- it doesn't call `authorised_mobile`, so booking authority is untouched;
- an unconvertible header leaves `None`, so CALLBACK_NOTED still fails at `_validate:59–61`, and an ordinary summary omits the field (`build_body` skips falsy values);
- retries reuse one `body`, so it stays identical;
- the docstring is updated.

It is cohesive and minimal; nothing to change.

### 2.2 Tests

| Requirement | Evidence | Status |
|---|---|---|
| An explicit valid number wins | `test_explicit_contact_wins_over_header`: header `None`, invalid or valid, for both outcomes | Proven |
| Only an omitted or null number falls back | `test_missing_contact_uses_header_without_verification`: omitted and null, both outcomes, no verification; also asserts the request object is unchanged | Proven |
| An invalid explicit value stays invalid | `test_invalid_explicit_contact_is_not_replaced_by_header`: `""`, `" "`, E.164, short, long, both outcomes; no POST | Proven |
| No usable contact: an ordinary summary saves; CALLBACK_NOTED fails | `test_unusable_header_does_not_invent_contact`: 10 header variants (absent, empty, foreign prefix, national, short, long, whitespace both sides, garbage) | Proven |
| Configured country code | `test_contact_conversion_uses_configured_country` (`44`) | Proven |
| Replay and lost-write retry | `test_replay_keeps_original_header_contact` (the original stored contact survives a different header or explicit value); the lost-write test asserts header contact and identical bodies on retry | Proven |
| Real HTTP header to stored body; concurrency | `test_concurrent_summaries_keep_their_own_call_and_start_time` now uses a different header number per call | Proven |
| Privacy and unchanged booking authority | `test_summary_http_contact_is_private_and_never_grants_authority`: with no verification header, LIST, CANCEL and RESCHEDULE give `IDENTITY_UNAVAILABLE`; no `/appointments` request; neither number appears in results, protocol errors, logs (via `JsonFormatter`) or stdout/stderr | Proven |
| Process journey | `test_e2e_processes.py:113`: the stored `callerMobile == "9000000101"` | Proven |

**External hooks (`test_external.py:199–224`):**
- The request hook asserts the actual POSTed `callerMobile`.
- The response hook reads the **raw** 201 body:
  - when `callerMobile` is echoed, it asserts it;
  - otherwise it records "not independently verified (response omits it; no calls.read)", and `record_property` publishes that.
- A replay answered with 200 is excluded, and there must be exactly one captured 201.
- An assertion inside a hook propagates rather than being swallowed: `OpsClient._write` catches only specific transport exceptions (`ops_client.py:286–303`).

The hooks are honest. They have not run locally, because of the HTTPS gate, which is correctly stated.

**Removed and replaced tests are justified:**
- `test_caller_mobile_is_never_copied_from_caller_id` pinned the superseded rule. It was removed only after its replacement tests had failed first.
- The `({"callerMobile": None}, "callerMobile")` case of the callback-constraints table is removed because the default fixture now has a valid header, so that request legitimately saves. The rejection side survives in `test_unusable_header_does_not_invent_contact` for CALLBACK_NOTED.

**Optional observations (not blockers):**

**O-1. The lost-write test switched from `GENERAL`**, which carries an explicit `callerMobile`, to a request with no number. The identical-body-on-retry property now covers the header-derived path, which is the new risk. Explicit-contact retry is unchanged and identical by construction. No change is needed.

**O-2. The test-authoring mistakes are disclosed and do not count as red evidence:** the CANCEL operation id, and the process-state list index. The valid reds are 8 service failures, 2 HTTP failures and 1 process failure, all `KeyError: 'callerMobile'` or the expected outcome mismatches.

**My verification:** I announced and ran the three focused test sets, each with a hard timeout:

| Run | Result |
|---|---|
| `test_summary.py` | 107 passed |
| the two new HTTP tests | 3 passed |
| the process journey | 1 passed |

All three exit 0 (`.context/opus-cf-*.txt`). Astra's records show the schema byte-identical, Ruff clean and Vulture identical. **I did not rerun `make test-fast`**, since that would be retrying the failed gate.

## 3. The blocker

### Proven, from `09-A-fast.txt`, `collection.txt` and `status.json`

1. **Where it starts:** the run was healthy for 961 tests. The failures start at collection index 962 (`test_the_model_cannot_supply_booking_identity_fields`), immediately after `test_the_whole_journey_over_http` (961) passed. **Neither test was changed by this work.**
2. **The pattern** from 962 onward is `FFFF.F....F.F....`:
   - **Every failure** is a test that runs an MCP session over HTTP.
   - **Every pass in that stretch is a test with no MCP session:** `test_dependency_status_is_separate_from_local_readiness` (a plain JSON route), the pack and description tests, the CLI test and the interface-table tests.
   - **Two of those passing tests start a real server** through the `served` fixture: `test_dependency_status_is_separate_from_local_readiness` (966) and `test_dependency_refresh_is_single_flight_and_throttled` (971). They call only `/dependencies`, a plain JSON route, and both passed.

     **So server start-up and shutdown were working; only event-stream (MCP) responses failed.** That is the signature of sse-starlette's flag.
   - The same shape as T-2 run 8 (`FFFF.F....F.F....F`).
3. **The only changed test that failed is 964** (`concurrent_summaries`), and it failed **inside** the cascade, not at its start. The new privacy/authority test is at the end of the file and **was never reached**.
4. **Astra sent SIGINT during test 979.** The only captured diagnostic is from that test:
   - an incomplete `POST /mcp/` with `sse_should_exit: true`;
   - then `KeyboardInterrupt`.

### Inferred, with high confidence; not proven

**The cascade is the T-4 mechanism occurring naturally.** During test 961's teardown, the sse-starlette watcher saw that server's `should_exit` and set the process-wide `AppStatus.should_exit`. It stays set, so every later event-stream response in the process is cut off. The supporting facts:
- MCP over HTTP fails while plain routes pass;
- the cascade starts abruptly at an unchanged test;
- it is identical in shape to the T-2 cascade;
- T-4 reproduced the mechanism 20 of 20 times;
- the code change is a three-line local transformation in `SummaryService` that cannot touch server lifecycle, sse-starlette or uvicorn.

**What is not proven:**
- **The 7 tracebacks were never captured** (`-q`, then the interrupt), so the failure reason of tests 962 to 974 is unobserved.
- **The single captured diagnostic is contaminated by the interrupt.** sse-starlette patches `uvicorn.Server.handle_exit` so that a SIGINT sets `AppStatus.should_exit = True` (`sse_starlette/sse.py:211–224`), and uvicorn re-raises the captured signal after shutdown (`uvicorn/server.py:349`). That is exactly the "incomplete response, `sse_should_exit=true`, then `KeyboardInterrupt`" sequence. **That diagnostic therefore cannot, on its own, prove the flag was set before the interrupt.** The earlier cascade pattern is the real evidence.

### Was stopping justified?

**Yes.**
- **The rules required it.** The brief says "if anything else must change, stop and report" and "never hide a failure". The plausible repair is in `conftest.py`, outside the five allowed files. Astra didn't retry, skip, raise a timeout or reset the flag.
- **The interrupt was reasonable.** Each failing test waits for its 20 s watchdog.
- **What would have helped:** bounding the run externally (`timeout -k`) and keeping full tracebacks (`--tb=short`, without `-q`) would have preserved the first failure's own evidence, without a SIGINT polluting the last diagnostic. That applies next time; no fault to assign.

## 4. Recommendation

### Scope extension (needs Garima's approval)

A separate, small, test-only repair before commit A.

**Earlier decisions:** Garima said in T-4 that any test-setup remedy is a separate small brief and does not block 4b. It now blocks a required gate. This is a **fix of a confirmed mechanism, not a new investigation**, so it does not conflict with "no T-5 investigation".

**The repair (T-5 fix):**
- **Files:** `services/mcp/tests/conftest.py` and `services/mcp/tests/test_server.py` only. One commit, before commit A.
- **Change:** at the **start** of every `serving()`, set sse-starlette's process-wide `AppStatus.should_exit` back to `False`.
- **Why that is justified:**
  - T-4 confirmed that the flag outlives the server that set it;
  - production runs one server per process, so a fresh process starts with `False`;
  - the reset restores the same per-server semantics for each test server;
  - it is test-only.
- **How:** reach it through `sys.modules.get("sse_starlette.sse")`, as the recorder already does, so no new import of a transitive dependency is added. When the module is not loaded, there is nothing to reset.
- **Unchanged:** production code, `pyproject.toml`, uvicorn and sse-starlette themselves, and the recorder's strictness (it still fails any incomplete response).

**The regression test, red first, in a subprocess so it stays out of the main process:**
- reproduce T-4's deterministic sequence: server A, an MCP session, A's shutdown, a 0.6 s hold, then server B and a session;
- **without the fix:** B's session fails with the recorder's confirmed incomplete-response incident;
- **with the fix:** it completes;
- use fixed data, no wall clock, and a hard subprocess timeout.

**Documents:** this brief does not touch `CLAUDE.md`. The gotcha "never run two `serving()` blocks sequentially" is still prudent, and `CLAUDE.md` is updated in contact-fallback commit B. I will propose the exact wording then.

**Gate rerun, once:**
1. bounded with `timeout -k 10 900 make test-fast`;
2. full tracebacks (`--tb=short` through `PYTEST_ADDOPTS` if needed);
3. no interrupt; preserve the output.

If it fails, report it, with no retry.

### Then

1. Commit the contact-fallback commit A, with the five files exactly as they are now, once `make test-fast` passes.
2. Continue with commit B as the brief describes.

### If Garima does not approve the repair

The only honest alternative is to leave commit A **uncommitted and blocked**. A clean rerun would not be evidence: the mechanism is intermittent, and a pass would be luck. **Do not rerun until green.**

## 5. Plain-English summary for Garima

**Astra's code is right:**
- an explicit number wins;
- otherwise the calling number is converted and used;
- invalid numbers are still rejected;
- callbacks without a usable number still fail;
- booking access is unchanged;
- nothing leaks into results or logs.

The tests prove all of this, and I reran them green.

**The test-suite failure is almost certainly the old flag problem we found in T-4.** One test server's shutdown left a shared library flag switched on, which then broke the replies of every later test server in the same run. The failure pattern matches it exactly, and it started at a test Astra didn't touch. It is not caused by this change.

**Astra was right to stop.** Fixing it means editing the shared test setup, which her brief didn't allow.

**I recommend you approve one small test-only fix:** reset that shared flag whenever a test server starts, with a test proving it. Then rerun the suite once, and Astra can commit her work.
