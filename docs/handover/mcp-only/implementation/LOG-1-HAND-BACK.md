# LOG-1 hand-back — 10 October 2026

Implemented the approved revision 4 plan, including both Low findings from Opus's commit-P review. Ready for review only; **not pushed, merged or deployed**. Release gate 7 is implemented but remains open until review and Garima's closure.

## Scope, commits and behavior

Base: `e53eee25bfbead0ba6e088012682518034ec74e3`. Branch: `Garry2012/slots-phase-1a-1b`.

| Stage | Commit | Files |
|---|---|---|
| P: controlled benchmark logging | `7bf7275ce469685271b26f3a893194d632f005a0` | `services/mcp/dev/bench.py`; `services/mcp/tests/test_bench.py` |
| A: logging privacy and tests | `b7feb3cc942318bb33fc7c700be51da98165735b` | `services/mcp/src/frontdesk_mcp/server.py`; `schedule_reader.py`; `availability.py`; `summary.py`; `services/mcp/tests/test_server.py` |
| B: documentation and evidence | The commit introducing this document; command below resolves its full hash | `CLAUDE.md`; `docs/DECISIONS.md`; `docs/handover/mcp-only/PLAN.md`; this file |

```sh
git log --diff-filter=A --format=%H -- docs/handover/mcp-only/implementation/LOG-1-HAND-BACK.md
```

The B hash is also supplied in the final hand-back message and `.context/log1/commit-B.txt`. A document cannot embed the hash of its own containing commit without changing that hash. There is no fourth bookkeeping commit or amend. The plan's A table says “6 files” but lists five; the brief explicitly permits those same five, and A changes exactly those five.

P retains the existing WARNING default and benchmark report shape, adds `--log-level` / `--log-file`, rejects DEBUG or INFO without a file before measurement, and checks there is exactly one root handler before redirecting it. The stream is restored before the file closes, including exceptional exit.

A removes two demonstrated leak paths: MCP protocol-validation prose in root JSON logs, and FastMCP's Rich exception traceback on stderr. The single JSON formatter now keeps unfilled approved library templates, exact permitted adapter facts and sanitized route templates. It never interpolates record arguments. FastMCP propagates to that formatter; unexpected tool-error text is masked in client results. Deliberate ToolError responses, including summary-validation redaction, remain unchanged.

The three supporting source edits only move existing read-failure values to a constant, name the existing directory failure value, and type the existing summary failure reasons. No scheduling, clinical, authentication, idempotency, retry, deadline, upstream request, tool-schema or normal-result behavior changes. No additional REST calls, locks, waits, background tasks or success logging.

## Red/green evidence

Raw outputs remain preserved under `.context/log1/`, as required by the brief; the actual commands, failure reasons and result excerpts are pasted here so the committed hand-back remains useful without that ignored directory. Commands for focused pytest runs are from `services/mcp`; make/script commands are from the repository root.

### P: benchmark options

```sh
uv run pytest tests/test_bench.py -q -k log_level --tb=short
```

Before implementation (`P-red.txt`):

```text
bench.py: error: unrecognized arguments: --log-file .../bench.log
E   assert 2 == 0
2 failed, 14 deselected, 2 warnings in 2.87s
```

After implementation (`P-green.txt`):

```text
2 passed, 14 deselected, 2 warnings in 4.72s
```

Both cases run the real CLI in child processes. They prove the unchanged 17-key report, default WARNING behavior, INFO logs in their own JSON-lines file, and stdout containing only the JSON report.

### P: first gate failure and explicitly authorized correction

```sh
PYTEST_ADDOPTS=--tb=short timeout -k 10 900 make test-fast
```

First gate (`P-fast.txt`, exit 2):

```text
E501 Line too long (121 > 120)  dev/bench.py:322:121
E501 Line too long (122 > 120)  dev/bench.py:346:121
E501 Line too long (123 > 120)  dev/bench.py:391:121
Found 3 errors.
make: *** [test-fast] Error 1
```

Pytest did not run. These were line-wrap mistakes introduced by the benchmark block's mechanical indentation. Formatting was corrected; `P-lint-corrected.txt` records `All checks passed!`. Work stopped for Opus's review. Garima then authorized both Low findings and exactly one fresh P gate, preserved separately below. The original failure is not overwritten or described as a passing run.

### P: Opus L-1 (require log file) and L-2 (single handler)

```sh
uv run pytest tests/test_bench.py -q -k 'requires_file or ambiguous_log_ownership' --tb=short
```

`P-review-red.txt`:

```text
FAILED ...test_benchmark_requires_file_before_verbose_measurement[DEBUG]
E   assert 0 == 2
FAILED ...test_benchmark_requires_file_before_verbose_measurement[INFO]
E   assert 0 == 2
ModuleNotFoundError: No module named 'frontdesk_stubs'
3 failed, 16 deselected, 2 warnings in 5.82s
```

The first two are genuine L-1 failures: verbose benchmarks ran instead of refusing invalid CLI combinations. The handler case is a **test-scaffolding mistake**, not evidence of L-2: its injected child import lacked `dev` in `sys.path`. The first attempted green run (`P-review-green.txt`) exposed the same mistake:

```text
ModuleNotFoundError: No module named 'frontdesk_stubs'
1 failed, 4 passed, 14 deselected, 2 warnings in 7.83s
```

After correcting only that child import path, the new handler guard was temporarily removed to demonstrate a genuine red, then restored:

```sh
uv run pytest tests/test_bench.py -q -k ambiguous_log_ownership --tb=short
```

`P-handler-red-corrected.txt`:

```text
    assert code != 0
E   assert 0 != 0
1 failed, 18 deselected, 2 warnings in 2.88s
```

With both guards installed:

```sh
uv run pytest tests/test_bench.py -q -k 'log_level or requires_file or ambiguous_log_ownership' --tb=short
uv run ruff check . ../../deploy
```

`P-review-green-corrected.txt`, followed by the separate Ruff check (also verified in `P-fast-2.txt`):

```text
5 passed, 14 deselected, 2 warnings in 7.35s
All checks passed!
```

The single authorized fresh P gate (`P-fast-2.txt`, same bounded make command, exit 0):

```text
All checks passed!
1214 passed, 14 deselected, 2 warnings in 91.90s (0:01:31)
```

P was committed only after this gate. Both before-benchmarks then ran before any A production implementation.

### A: privacy tests and regression coverage

```sh
uv run pytest tests/test_server.py -q -k log1 --tb=short
```

`A-red.txt`, before implementation:

```text
E   AssertionError: assert 'Zelda Fakena...ECRETTOKENXYZ' == 'library_message_omitted'
E   AssertionError: assert 'Started serv... [9876501234]' == 'Started server process [%d]'
E   AssertionError: assert ('reason' not in {'ts': ..., 'level': 'INFO', ...})
E   AssertionError: assert ('/doctors/doc...da_9876501234' == '/doctors/{id}'
    assert failed.content[0].text == "Error calling tool 'record_call_summary'"
E   AssertionError
82 failed, 1 passed, 84 deselected, 2 warnings in 5.83s
```

The one already-passing test was `test_log1_real_adapter_events_keep_every_permitted_value`: retaining legitimate existing diagnostics is intentional, not a new behavior expected to fail. The other 82 cases failed on missing privacy behavior. No A test-scaffolding failure was encountered.

| Requirement | Tests in `test_server.py` (prefix `test_log1_`) |
|---|---|
| Root/library filled messages, templates and args, FastMCP's real filled tool-error message | `never_interpolates_values`; `libraries_cannot_inject_adapter_fields` |
| Error type, last 10 frame locations, no exception text/source/locals | `only_bounded_error_frames_are_kept` |
| Safe facts and unknown fields | `adapter_fields_keep_safe_facts_and_drop_unknown_values` |
| All 12 secret-shaped values from revision 4 | `secret_shaped_values_are_not_safe_codes` |
| Dynamic route IDs discarded; unknown/query paths omitted | `owner_paths_discard_ids_and_refuse_unknown_routes` |
| All 19 fields reject containers and accept null; primitive ranges and bool rejection | `fields_reject_containers_and_allow_none`; `invalid_primitives_are_omitted` |
| Existing correlation syntax | `context_call_id_uses_the_existing_syntax_check` |
| Six logger owners, exactly once, real stdout/stderr capture | `all_six_logging_sources_have_one_json_owner` |
| Real HTTP: malformed JSON-RPC, unexpected tool exception, normal CREATE/LIST/summary, deliberate validation error unchanged | `private_data_stays_out_of_real_http_logs_and_unexpected_errors` |
| All four tools cover all 12 actual client routes | `all_observed_owner_routes_are_templated` |
| Nine actual adapter event sources retain their permitted values | `real_adapter_events_keep_every_permitted_value` |

Focused green plus recorder/T-5/summary-redaction/log-correlation regressions:

```sh
uv run pytest tests/test_server.py -q -k 'log1 or recorder or watchdog or serving or invalid_summary or log_lines' --tb=short
```

`A-green.txt`, exit 0:

```text
125 passed, 42 deselected, 2 warnings in 34.73s
```

A's one full fast gate:

```sh
PYTEST_ADDOPTS=--tb=short timeout -k 10 900 make test-fast
```

`A-fast.txt`, exit 0:

```text
All checks passed!
1297 passed, 14 deselected, 2 warnings in 93.12s (0:01:33)
```

A's initial focused Ruff pass reported one import-layout error and four long lines (`A-lint-first.txt`); these were corrected before the full gate. `A-lint.txt` records `All checks passed!`. No A full-gate retry occurred. Two Authlib import deprecations appear in passing pytest runs; they are pre-existing warnings.

Independent read-only review (`/root/log1_review`) found no actionable findings in the five-file A draft. It checked revision-4 field sources, route templating, handler ownership, error masking, required test coverage, installed library templates and success-path work. It ran no tests, benchmarks or external calls; runtime evidence above belongs to the primary agent.

## Built allowlists

19 field names; exact sets are constructed once at import, not per request.

| Field | Distinct accepted values | Source |
|---|---:|---|
| `tool` | 4 | `tools.TOOL_NAMES` |
| `outcome` | 28 | `get_args` of the four outcome Literals in `outcomes` |
| `nextStep` | 27 | `get_args` of `NextStep`, `BookingNextStep`, `KnowledgeNextStep` |
| `detail` | 5 | `READ_FAILURE_DETAILS.values()` plus `DIRECTORY_FAILURE_DETAIL` |
| `reason` | 11 | `SummaryFailureReason` and `UnavailableReason` Literals |
| `error` | 25 | `READ_ERRORS`, the imported `httpx.RequestError` class tree (including `SSEError`), and `TimeoutError` |
| `model` | 24 | Pydantic classes defined by `contract` (including its `_Model` base) |
| `field` | 5 | `knowledge_contract.AnswerResponse.model_fields` |
| `header` | 5 | `context.FIELD_OF_HEADER` keys |
| `env` | 4 | `Settings.env` Literal |
| `pack` | 1 | Shipped JSON file names in `frontdesk_mcp/packs/` |
| `schemaVersion` | 1 | `prompt.SCHEMA_VERSION` (`2026-10-10.1`) |
| `path` | 12 route templates | One compiled route table; dynamic IDs discarded |
| `callId` | Syntax-limited, not enumerable | Existing `context._ID` for both context and field |
| `summaryId` | Syntax-limited, not enumerable | Existing `summary._LOG_ID` |
| `status`, `httpStatus` | 500 each | Exact int 100–599; bool excluded |
| `attempt` | 10 | Exact int 1–10 |
| `retryAfterSeconds` | 86,401 | Exact int 0–86,400 |

Every permitted field also accepts null. Containers, unknown fields and failed values are omitted; only their field names appear in `omittedFields`. Provider remains a configuration value. Call and summary IDs remain deliberately visible for correlation; syntax checks are not proof that an identifier contains no sensitive information.

All 12 routes are covered by a recorded real MCP fixture journey:

```text
/auth/token
/departments
/doctors
/doctors/{id}
/availability
/availability/{id}/slots
/capabilities
/appointments
/appointments/{id}/cancel
/appointments/{id}/reschedule
/call-summaries
/v1/answer
```

12 allowed library messages were checked verbatim against installed `uvicorn/server.py`, `uvicorn/lifespan/on.py`, the HTTP protocol implementations and `mcp/server/streamable_http.py`. Uvicorn constructs its running-message string using the fixed `%s://%s:%d` address format; the final template is checked. FastMCP's `tool_manager.py:166` builds an already-filled f-string and is deliberately excluded. Other library messages become `library_message_omitted`.

```json
[
  "ASGI callable returned without completing response.",
  "Application shutdown complete.",
  "Application startup complete.",
  "Application startup failed. Exiting.",
  "Exception in ASGI application\n",
  "Finished server process [%d]",
  "No response message received before stream closed",
  "Shutting down",
  "Started server process [%d]",
  "Uvicorn running on %s://%s:%d (Press CTRL+C to quit)",
  "Waiting for application shutdown.",
  "Waiting for application startup."
]
```

## Original leak probe, before and after

```sh
cd services/mcp
PYTHONPATH=.:src:dev timeout -k 5 180 uv run python ../../.context/log1/probe.py \
  > ../../.context/log1/stdout-after.txt 2> ../../.context/log1/stderr-after.txt
```

Exit 0; all 11 probe steps completed and `=== PROBE DONE` was present. The probe's own “ok” labels mean the invocation completed, not that every request was a business success: deliberately invalid requests are included. The new HTTP regression test separately asserts successful CREATE/LIST/summary and the exact masked unexpected-error response.

Counts use literal substring matching; the local original baseline was retained, not regenerated:

| Fake value | stdout before | stderr before | stdout after | stderr after |
|---|---:|---:|---:|---:|
| `Zelda Fakename` | 0 | 1 | 0 | 0 |
| `9876501234` | 0 | 1 | 0 | 0 |
| `+919876501234` | 0 | 0 | 0 | 0 |
| `SECRETREASONPAIN` | 0 | 0 | 0 | 0 |
| `SECRETTOKENXYZ` | 12 | 1 | 0 | 0 |
| `BearerSecretAlphaToken` | 0 | 0 | 0 | 0 |

`BearerSecretAlphaToken` is exercised by the new tests, not the original probe; its zero probe count is not claimed as an additional demonstrated baseline leak. The old stdout contained 12 fake-secret occurrences; old stderr exposed the fake name, mobile and secret once each. Afterward both streams contain none of the listed fake values. Stderr contains only the two known Authlib import warnings and the probe's fixed step/result labels, not a FastMCP traceback.

## Latency and log-volume evidence

Same Apple M5 arm64 Mac, macOS 26.6.2. Load averages at the recorded before/after points were respectively `(4.054, 3.620, 3.823)` and `(3.048, 3.377, 3.526)`. No other test or benchmark was run concurrently by this agent. Host load was not controlled; the small improvements below are not attributed to the code change.

Same fixture boundary, 50 samples per scenario, concurrency 1, warmed token, new MCP client session per sample. Both slot modes were observed. No `BENCH_*` or `OPS_E2E_*` environment overrides were present for the measurements.

Commands, one invocation before and one after:

```sh
# Repository root, substitute before or after in the evidence filename:
timeout -k 10 900 make bench > .context/log1/bench-warning-<when>.json 2> .context/log1/bench-warning-<when>.stderr

# services/mcp:
timeout -k 10 900 uv run python dev/bench.py --samples 50 --concurrency 1 --log-level INFO \
  --log-file ../../.context/log1/bench-info-<when>.log \
  > ../../.context/log1/bench-info-<when>.json 2> ../../.context/log1/bench-info-<when>.stderr
```

The WARNING capture includes make's echoed command before the JSON. It is preserved unchanged; analysis parses from the first `{`. INFO stdout is a standalone JSON report. No scenario refusals were used as latency samples. The threshold is strictly more than 10% **and** more than 1 ms in p50. No scenario crosses it, so no regression-triggered profiling or rerun was required.

### WARNING benchmark

| Scenario | Slots | Before p50 / p95 ms | After p50 / p95 ms | p50 delta ms (%) | Material regression |
|---|---|---:|---:|---:|---|
| `availability_known_doctor` | disabled | 31.1 / 34.8 | 30.6 / 34.3 | -0.5 (-1.6%) | No |
| `availability_name_search` | disabled | 31.5 / 36.2 | 31.2 / 34.9 | -0.3 (-1.0%) | No |
| `availability_ambiguous` | disabled | 30.9 / 35.4 | 30.3 / 34.1 | -0.6 (-1.9%) | No |
| `availability_department` | disabled | 31.6 / 36.5 | 30.9 / 35.0 | -0.7 (-2.2%) | No |
| `knowledge_answer` | disabled | 14.6 / 18.5 | 14.5 / 17.5 | -0.1 (-0.7%) | No |
| `booking_list` | disabled | 25.6 / 30.0 | 25.2 / 29.6 | -0.4 (-1.6%) | No |
| `booking_create` | disabled | 27.4 / 40.2 | 26.2 / 34.9 | -1.2 (-4.4%) | No |
| `availability_department_future_cold` | disabled | 35.4 / 39.8 | 34.5 / 38.5 | -0.9 (-2.5%) | No |
| `availability_department_future_warm` | disabled | 32.6 / 39.8 | 31.8 / 35.5 | -0.8 (-2.5%) | No |
| `slots_availability_future` | enabled | 31.6 / 36.1 | 30.9 / 36.2 | -0.7 (-2.2%) | No |
| `slots_availability_today` | enabled | 32.1 / 35.2 | 31.0 / 33.8 | -1.1 (-3.4%) | No |
| `slots_availability_oncall` | enabled | 32.1 / 36.0 | 31.1 / 35.1 | -1.0 (-3.1%) | No |
| `slots_booking_create` | enabled | 26.9 / 30.9 | 26.3 / 30.3 | -0.6 (-2.2%) | No |
| `slots_department_cold` | enabled | 33.3 / 38.5 | 32.5 / 36.1 | -0.8 (-2.4%) | No |
| `slots_department_warm` | enabled | 32.5 / 37.1 | 31.8 / 35.1 | -0.7 (-2.2%) | No |

15 scenarios × 50 samples = **750 verified successes; 0 refused/failed**, both before and after.

### INFO benchmark

| Scenario | Slots | Before p50 / p95 ms | After p50 / p95 ms | p50 delta ms (%) | Material regression |
|---|---|---:|---:|---:|---|
| `availability_known_doctor` | disabled | 31.9 / 39.2 | 30.7 / 34.3 | -1.2 (-3.8%) | No |
| `availability_name_search` | disabled | 32.0 / 35.7 | 31.0 / 35.1 | -1.0 (-3.1%) | No |
| `availability_ambiguous` | disabled | 31.4 / 38.8 | 30.1 / 35.7 | -1.3 (-4.1%) | No |
| `availability_department` | disabled | 31.7 / 36.0 | 30.9 / 35.1 | -0.8 (-2.5%) | No |
| `knowledge_answer` | disabled | 14.9 / 18.9 | 14.3 / 17.9 | -0.6 (-4.0%) | No |
| `booking_list` | disabled | 26.0 / 30.2 | 25.4 / 29.8 | -0.6 (-2.3%) | No |
| `booking_create` | disabled | 27.1 / 31.2 | 26.2 / 30.5 | -0.9 (-3.3%) | No |
| `availability_department_future_cold` | disabled | 35.7 / 39.1 | 34.5 / 38.1 | -1.2 (-3.4%) | No |
| `availability_department_future_warm` | disabled | 32.6 / 37.4 | 31.7 / 35.5 | -0.9 (-2.8%) | No |
| `slots_availability_future` | enabled | 31.9 / 35.9 | 30.9 / 35.1 | -1.0 (-3.1%) | No |
| `slots_availability_today` | enabled | 32.0 / 35.8 | 30.9 / 35.3 | -1.1 (-3.4%) | No |
| `slots_availability_oncall` | enabled | 32.6 / 35.9 | 31.8 / 35.5 | -0.8 (-2.5%) | No |
| `slots_booking_create` | enabled | 26.9 / 35.9 | 26.4 / 30.2 | -0.5 (-1.9%) | No |
| `slots_department_cold` | enabled | 33.1 / 37.8 | 32.3 / 38.1 | -0.8 (-2.4%) | No |
| `slots_department_warm` | enabled | 32.5 / 36.7 | 31.6 / 36.8 | -0.9 (-2.8%) | No |

15 scenarios × 50 samples = **750 verified successes; 0 refused/failed**, both before and after.

### INFO log volume (raw message strings)

| msg | Before | After |
|---|---:|---:|
| `Application shutdown complete.` | 1 | 1 |
| `Application startup complete.` | 1 | 1 |
| `Finished server process [%d]` | 0 | 1 |
| `Finished server process [21936]` | 1 | 0 |
| `Shutting down` | 1 | 1 |
| `Started server process [%d]` | 0 | 1 |
| `Started server process [21936]` | 1 | 0 |
| `Uvicorn running on %s://%s:%d (Press CTRL+C to quit)` | 0 | 1 |
| `Uvicorn running on http://127.0.0.1:55275 (Press CTRL+C to quit)` | 1 | 0 |
| `Waiting for application shutdown.` | 1 | 1 |
| `Waiting for application startup.` | 1 | 1 |
| `service_started` | 1 | 1 |
| `tool_result` | 752 | 752 |
| `summary_saved` (not part of benchmark workload) | 0 | 0 |

Raw lifecycle message strings intentionally change: PID/host/port arguments are no longer interpolated. The approved unfilled templates therefore appear as new raw strings; they represent the same lifecycle events, not added log calls. The table above retains that difference.

After normalizing only these three lifecycle templates, **all event counts are identical**. There are **761 lines in each file: 752 `tool_result`, 1 `service_started`, and 8 lifecycle lines**. `summary_saved` is 0 in both because this benchmark has no summary scenario; its behavior is covered by the real HTTP privacy test and real-event test.

Actual before `tool_result` sample:

```json
{"ts": "2026-10-10T02:18:18.288233+00:00", "level": "INFO", "logger": "frontdesk_mcp.tools", "msg": "tool_result", "provider": "demo-hospital", "callId": "bench-prepare-disabled", "tool": "get_doctor_availability", "outcome": "AVAILABILITY", "nextStep": "ASK_WHICH_SESSION"}
```

Actual after `tool_result` sample:

```json
{"ts": "2026-10-10T02:27:08.823365+00:00", "level": "INFO", "logger": "frontdesk_mcp.tools", "msg": "tool_result", "provider": "demo-hospital", "callId": "bench-prepare-disabled", "tool": "get_doctor_availability", "outcome": "AVAILABILITY", "nextStep": "ASK_WHICH_SESSION"}
```

### Verdict

Material p50 regressions (>10% **and** >1 ms): **0**. Fixture measurements are not evidence of live owner, gateway, or caller-audio latency. Each benchmark ran once before and once after; none was retried.

## Verification commands and actual results

Schema (before the A commit):

```sh
make schema > .context/log1/schema-A.json 2> .context/log1/schema-A.stderr
cmp .context/log1/schema-A.json services/mcp/tests/contracts/mcp-tools.snapshot.json
```

Exit 0, byte-identical: **64,603 bytes**, SHA-256 **`d666020548a83315c47ac2529a1972efa89f5bbe722786d18de7316f55454fdf`**, schema version **`2026-10-10.1`**. No version bump and no generated schema or VOICE-TEAM change.

Lint:

```sh
cd services/mcp
uv run ruff check . ../../deploy
```

`All checks passed!`; also executed by both successful fast gates and the full script. No separate static type-check command is part of the repository's verification script; no extra type-check result is claimed.

Vulture, before and after A (same command, no new findings):

```sh
uvx --offline vulture services/mcp/src/frontdesk_mcp/server.py services/mcp/src/frontdesk_mcp/schedule_reader.py services/mcp/src/frontdesk_mcp/availability.py services/mcp/src/frontdesk_mcp/summary.py services/mcp/dev/bench.py services/mcp/tests/test_server.py services/mcp/tests/test_bench.py --min-confidence 80
```

Both exit 0 with empty output (`vulture-before.txt`, `vulture-after.txt`, byte-identical). `git diff --check` also exits 0. Final document checks confirm `docs/DECISIONS.md` is append-only and `CLAUDE.md` stays at 47 lines (under 80).

Full script, once after both after-benchmarks:

```sh
env -u OPS_E2E_BASE_URL timeout -k 10 900 ./scripts/test.sh > .context/log1/full.txt 2>&1
```

Actual result excerpts, exit 0:

```text
== install (frozen)
== lint
All checks passed!
== hermetic suites
=============================== warnings summary ===============================
1297 passed, 14 deselected, 2 warnings in 91.53s (0:01:31)
== process e2e (stubs + adapter over TCP)
=============================== warnings summary ===============================
5 passed, 1306 deselected, 2 warnings in 5.29s
== package build
Successfully built /tmp/frontdesk-mcp-build/frontdesk_mcp-0.1.0.tar.gz
Successfully built /tmp/frontdesk-mcp-build/frontdesk_mcp-0.1.0-py3-none-any.whl
== production image build (no stubs, no fixtures, no dev dependencies)
== development stubs image build (compose profile stubs)
== external gates not run: no profile loaded (scripts/run-profile.sh mock|live -- ./scripts/test.sh)
== all suites passed
```

Docker was available: both production and development-stub images built successfully. The script verified that the production image cannot import `frontdesk_stubs` or `pytest`. This is a local image build and packaging check, not deployment or validation of logs inside a running production container. The five process e2e tests include the repository's local smoke/journey coverage. External tests were deliberately not invoked.

## Protected workspace files

All **376** files in the initial protected-file manifest were rehashed after implementation and verification; zero changed. The later-arriving `OPUS-LOG1-P-REVIEW.md` was captured separately when inspected and also remains unchanged. This compares against the user's working copies, not against Git HEAD; their pre-existing modifications remain in place and are not in the commits.

The required protected working files and every file under `temp/` have these before/after SHA-256 hashes:

| File | Before SHA-256 | After SHA-256 |
|---|---|---|
| `deploy/azure/deploy.sh` | `fb05a1bb9f4358cf12392deccc38cd5ffbda2e07365f29ea940fa1de2db17352` | `fb05a1bb9f4358cf12392deccc38cd5ffbda2e07365f29ea940fa1de2db17352` |
| `deploy/environments/README.md` | `855a23ec88d34a6b17be1b88de0a6466fbba1bd21497b08723d79ad7230ff410` | `855a23ec88d34a6b17be1b88de0a6466fbba1bd21497b08723d79ad7230ff410` |
| `deploy/environments/live.env` | `8bd2d6bae32e8d6fd94c6edd3ded88c7048663c2d2a1312ef8acf882e49fcc94` | `8bd2d6bae32e8d6fd94c6edd3ded88c7048663c2d2a1312ef8acf882e49fcc94` |
| `docs/handover/mcp-only/AZURE-RETIREMENT.md` | `225798592f9f13be238c3cdebedc56a0ebee85dacc804c420eb2b0206df5e08d` | `225798592f9f13be238c3cdebedc56a0ebee85dacc804c420eb2b0206df5e08d` |
| `docs/handover/mcp-only/implementation/AZURE-RETIREMENT-RESULTS.md` | `1c0aad345908ec4b3b14500d68fcb6074d057ad652b4467373038e1079abf843` | `1c0aad345908ec4b3b14500d68fcb6074d057ad652b4467373038e1079abf843` |
| `docs/handover/mcp-only/implementation/AZURE-RETIREMENT-CHECK-20261009.md` | `539aca46d36ab8dd023c87f3c5b93a7e3fd98ae33c4512f246027a22b63b0715` | `539aca46d36ab8dd023c87f3c5b93a7e3fd98ae33c4512f246027a22b63b0715` |
| `docs/handover/mcp-only/implementation/LOG-1-PLAN.md` | `c85b5dbe7eb43b2bcce9a723c76afc793d668ed01ccece889fdc5242f6cfa6a6` | `c85b5dbe7eb43b2bcce9a723c76afc793d668ed01ccece889fdc5242f6cfa6a6` |
| `docs/handover/mcp-only/implementation/OPUS-L1-T5-DOCS-REVIEW.md` | `3fb9e3a155c58f643a173802e5a92ee07ad1d663d0ff51b30897988196513c42` | `3fb9e3a155c58f643a173802e5a92ee07ad1d663d0ff51b30897988196513c42` |
| `temp/API_ENDPOINTS.md` | `d0534fc7d039f7862d6599a856f11f2f12dfe13da033816b5ca47b83f9acc5b7` | `d0534fc7d039f7862d6599a856f11f2f12dfe13da033816b5ca47b83f9acc5b7` |
| `temp/Healthcare_Operations_API_openapi_v0.3.yaml` | `c1f130be8c9fd51f50424a1919fd1131331b30ade64e96ce79d2b14d99af070a` | `c1f130be8c9fd51f50424a1919fd1131331b30ade64e96ce79d2b14d99af070a` |
| `temp/MCP_INTEGRATION (1).md` | `43b21d6a6f2531e9df5af5fb4f7a34c322649473fcb6bc53ae85ee48da9e49bc` | `43b21d6a6f2531e9df5af5fb4f7a34c322649473fcb6bc53ae85ee48da9e49bc` |
| `temp/openapi-3.0.json` | `7dac2f7d0fcc6d9d1d47bd2dcfd9d39f596c64926e566175b0afe83704314d49` | `7dac2f7d0fcc6d9d1d47bd2dcfd9d39f596c64926e566175b0afe83704314d49` |
| `temp/permission.txt.rtf` | `cca58e25ad751dbbbeed2f3c77f894ad5a19a47f02ff062f8ed5677a57d54cf8` | `cca58e25ad751dbbbeed2f3c77f894ad5a19a47f02ff062f8ed5677a57d54cf8` |
| `docs/handover/mcp-only/implementation/OPUS-LOG1-P-REVIEW.md` (later arrival) | `209927afb7166d939827fc6840c243e8edbb37fcd41f080edcbfbb864cbddfbb` | `209927afb7166d939827fc6840c243e8edbb37fcd41f080edcbfbb864cbddfbb` |

## Self-review, residual risks and release status

- P changes exactly two permitted files, A five, and B four. The plan/reviewer files, unrelated deployment work and `temp/` are not staged. No backend implementation or dependency was added.
- No ContextForge, environment, Dockerfile, dependency, log-level setting, `QUIET_LOGGERS`, schema or adapter log call site changed. FastMCP's handler removal/propagation and NOTSET setting are the explicit approved ownership change.
- No added success-path events: 752 `tool_result` before and after. `summary_saved` is absent from the benchmark workload in both runs; the summary test and real-event capture cover it. The raw lifecycle strings change to the approved unfilled templates, as explicitly shown above.
- No benchmark reruns, gate retries or hidden failures. The sole extra gate was P's specifically authorized fresh run after formatting correction; focused TDD reruns and the corrected P test-scaffolding failure are all disclosed above. No test was weakened, skipped or given a raised timeout.
- Library text outside the exact template list is deliberately lost. Upgrades must recheck templates; unknown text fails closed. New fields/codes/routes need source-set updates. Exception type and up to 10 frame locations remain available without messages, arguments, locals or source lines.
- Adapter event names, logger names and provider configuration remain trusted code/configuration values. `callId` and `summaryId` remain visible by Garima's decision; syntax checks cannot prove content is non-sensitive. FastMCP's import-time handlers exist until application logging is configured, before request handling.
- Every recorded fake-value leak was eliminated locally. This is not a claim that every conceivable runtime path has been exercised.
- **Not verified:** production container logs after deployment; real Manoj or knowledge services; Azure; ContextForge; real voice response latency; closure of release gate 7. No changes or requests were made to those systems in this task.
- The local verification supports **ready for review**. Merge and deployment remain unauthorized for LOG-1, and the other release gates in PLAN.md still apply. Garima must explicitly close gate 7 after review.
