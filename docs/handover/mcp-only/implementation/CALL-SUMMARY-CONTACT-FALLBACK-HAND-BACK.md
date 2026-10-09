# Call-summary contact fallback and T-5 — implementation hand-back

**10 October 2026. Implemented, locally verified and ready for review. Not approved for merge or deployment.**

The missing summary contact now falls back to the strictly converted caller header. Explicit valid
contact wins, invalid explicit input is rejected, and contact grants no appointment authority. T-5
repairs the confirmed test-process SSE flag before each test server starts; production is untouched
by that repair. No owner, Azure, knowledge-host or ContextForge call was made in this build task.

## Base, commits and scope

- Branch: `Garry2012/slots-phase-1a-1b`.
- Actual base: `980da737bd85e87cbe3c5248856cb2a2c18a9125`.
- T-5: `151ea618cf63a2aec3cf691e275f88e5e5df4a78` — Reset sse-starlette's process-wide drain flag per test server.
- Contact A: `3b8cf18a80aea837b75c414cfff6a0996a7ba061` — Use caller header as missing summary contact.
- Contact B: the commit containing this report — Publish summary contact fallback contract and evidence.
  Its hash can be obtained with `git log -1 --format=%H -- docs/handover/mcp-only/implementation/CALL-SUMMARY-CONTACT-FALLBACK-HAND-BACK.md`; the final hand-back message supplies it.

T-5 contains exactly two files:

1. `services/mcp/tests/conftest.py`
2. `services/mcp/tests/test_server.py`

Contact A contains exactly five files:

1. `services/mcp/src/frontdesk_mcp/summary.py`
2. `services/mcp/tests/test_summary.py`
3. `services/mcp/tests/test_server.py`
4. `services/mcp/tests/test_e2e_processes.py`
5. `services/mcp/tests/test_external.py`

Contact B contains exactly eight files:

1. `services/mcp/src/frontdesk_mcp/packs/healthcare.json`
2. `services/mcp/src/frontdesk_mcp/prompt.py`
3. `services/mcp/tests/contracts/mcp-tools.snapshot.json`
4. `docs/handover/VOICE-TEAM.md`
5. `docs/DECISIONS.md`
6. `CLAUDE.md`
7. `docs/handover/mcp-only/PLAN.md`
8. This hand-back.

Evidence is retained under `.context/contact-fallback/` and `.context/t5/`; essential outputs are
pasted below so review does not depend on ignored folders. The unrelated cleanup files, modified
SLOTS-PLAN, approved contact plan, Opus reviews and user-owned `temp/` remain untouched and uncommitted
by this task. No identity, context, tools, booking, ops-client, owner-contract/overlay, stub,
configuration, dependency or deployment changes.

## Design note and implemented behaviour

Root cause: SummaryService intentionally used only the explicit optional contact; the no-copy test pinned that old policy. Resolution belongs in `SummaryService.record`, once before the existing validator and body builder. The implementation reuses `identity.contract_mobile` and `SummaryRequest.model_copy`: only omitted/null input is resolved from a header, using the configured country code. Explicit invalid input still fails; explicit valid input wins. No shared state or CallContext mutation, no new helper or changed signature, no authorization-helper call. Retries retain the same resolved body.

The old `test_caller_mobile_is_never_copied_from_caller_id` was removed only after replacement tests existed and failed. The callback-with-null assertion was removed from the old invalid-contact parameter table: its default valid header now supplies contact. New omitted/null positive tests plus unusable-header callback rejection tests retain both sides of that boundary. Existing replay/lost-response assertions remain and now include header-derived contact.

HTTP tests cover contact/body propagation, differing concurrent header numbers, explicit precedence, unverified-header refusal for LIST/CANCEL/RESCHEDULE, and input/output/log privacy. Process e2e asserts the actual stored contact. External-test request and response hooks assert the sent body and raw 201 callerMobile echo when present, or record `not independently verified (response omits it; no calls.read)`. Those external hooks have NOT been executed locally: the external journey remains subject to the HTTPS gate and no bypass was added.

## Evidence: commands, failures and passes

Unless prefixed `make`, commands below ran in `services/mcp`. Each red output is preserved independently; no file was overwritten by green output.

### Service behaviour — red then green

Command, both runs:

```bash
uv run pytest tests/test_summary.py -q --tb=short
```

Red (`01-service-red.txt`), before implementation and before removing the two obsolete expectations:

```text
KeyError: 'callerMobile'
AssertionError: assert {'outcome': 'INVALID_REQUEST', 'fields': ['callerMobile']} == {'outcome': 'SAVED'}
FAILED test_missing_contact_uses_header_without_verification[RESOLVED_BY_AGENT-omitted]
FAILED test_missing_contact_uses_header_without_verification[RESOLVED_BY_AGENT-null]
FAILED test_missing_contact_uses_header_without_verification[CALLBACK_NOTED-omitted]
FAILED test_missing_contact_uses_header_without_verification[CALLBACK_NOTED-null]
FAILED test_contact_conversion_uses_configured_country
FAILED test_replay_keeps_original_header_contact[contact0]
FAILED test_replay_keeps_original_header_contact[contact1]
FAILED test_lost_write_response_then_verified_replay_is_already_saved
8 failed, 101 passed, 2 warnings in 1.91s
```

Green (`06-service-green.txt`):

```text
107 passed, 2 warnings in 1.55s
```

The already-supported precedence/invalid-input/unusable-header cases passed before implementation; they are retained boundary tests, not claimed as newly failing behaviour.

### HTTP propagation/isolation/authority — red then green

Command:

```bash
uv run pytest tests/test_server.py -q --tb=short -k 'summary_http_contact or concurrent_summaries'
```

Initial red (`02-http-red.txt`): `3 failed, 80 deselected, 2 warnings in 2.07s`. Two were genuine missing contact failures. The explicit-contact case also revealed a mistake in my new test: CANCEL/RESCHEDULE lacked an operation ID, returning OPERATION_CONTEXT_MISSING before identity validation. I supplied that required header; production was still unchanged.

Corrected red (`04-http-red-corrected.txt`):

```text
KeyError: 'callerMobile'
FAILED test_concurrent_summaries_keep_their_own_call_and_start_time
FAILED test_summary_http_contact_is_private_and_never_grants_authority[contact0-9000000101]
2 failed, 1 passed, 80 deselected, 2 warnings in 1.90s
```

Green (`07-http-green.txt`):

```text
3 passed, 80 deselected, 2 warnings in 1.76s
```

Read-only independent review found no critical/important issue and one minor coverage gap: caplog.text does not reliably include structured record.fields. I reused JsonFormatter in the assertion, then announced and ran:

```bash
uv run pytest tests/test_server.py -q --tb=short -k summary_http_contact
```

Result (`10-http-privacy-review.txt`):

```text
2 passed, 81 deselected, 2 warnings in 1.64s
```

### Existing process journey — red then green

Command:

```bash
uv run pytest tests/test_e2e_processes.py::test_journey_and_summary_through_real_transport -q --tb=short
```

Initial red (`03-process-red.txt`): `TypeError: list indices must be integers or slices, not str`; `1 failed, 2 warnings in 2.52s`. My first assertion treated the stub HTTP state's summaries list as a dictionary. I corrected the test to inspect its sole stored summary, retaining existing counts. Production was still unchanged.

Corrected red (`05-process-red-corrected.txt`):

```text
KeyError: 'callerMobile'
1 failed, 2 warnings in 2.29s
```

Green (`08-process-green.txt`):

```text
1 passed, 2 warnings in 2.18s
```

### Schema and static checks

```bash
make schema > .context/contact-fallback/schema-A.json
cmp .context/contact-fallback/schema-before.json .context/contact-fallback/schema-A.json
shasum -a 256 .context/contact-fallback/schema-A.json
cd services/mcp && uv run ruff check . ../../deploy
```

Actual results: cmp exit 0, 64,111 bytes; SHA-256 `3ef91e78ccfc8b730c540244f8e390bb1ca2bdc74576a8cc4207f93ecc7d6c62`; ruff `All checks passed!`. Commit A remains `2026-10-08.1`, byte-identical. Commit B publishes `2026-10-10.1`; its separate comparison appears below.

Before and after:

```bash
uvx --offline vulture services/mcp/src/frontdesk_mcp/summary.py services/mcp/src/frontdesk_mcp/prompt.py services/mcp/tests/test_summary.py services/mcp/tests/test_server.py services/mcp/tests/test_e2e_processes.py services/mcp/tests/test_external.py --min-confidence 80
```

Both exit 0 with empty output; baseline and after-output are identical. `git diff --check` exit 0. Protected-file digest check: `protectedChanged: []`.

## Preserved original blocked full-suite run — not hidden

Command: `make test-fast`. Full output: `.context/contact-fallback/09-A-fast.txt`.

Lint passed. The suite developed repeated HTTP failures, including pre-existing booking tests that never call SummaryService. I announced an interruption and sent SIGINT to this run's pytest child after seven failure markers to stop the cascade and obtain diagnostics. The run is **failed and incomplete**, not a passing gate. Its final output does not contain a normal completed pytest summary. A separate collect-only command mapped progress markers to test names; 971 pass markers and 7 failure markers were observed, NOT claimed as a completed-suite result.

Failure markers mapped by collection order:

- `tests/test_server.py::test_the_model_cannot_supply_booking_identity_fields`
- `tests/test_server.py::test_summary_arguments_cannot_override_trusted_headers`
- `tests/test_server.py::test_concurrent_summaries_keep_their_own_call_and_start_time`
- `tests/test_server.py::test_concurrent_calls_keep_their_own_identity`
- `tests/test_server.py::test_log_lines_carry_the_call_id_not_the_caller`
- `tests/test_server.py::test_results_carry_an_output_schema_and_structured_content_without_sdk_revalidation`
- `tests/test_server.py::test_smoke_distinguishes_unconfigured_knowledge_from_scheduling_failure`

The interrupted test was `test_summary_length_is_an_in_band_invalid_request`. Captured incident:

```text
AssertionError: Incomplete HTTP response: POST /mcp/ #1 confirmed=true
"confirmed": true,
"flags_disagree": false,
"sse_should_exit": true,
"status": 200,
"response_content_type": "text/event-stream",
"started": true,
"complete": false,
"returned": true,
"raised": null,
"duration": 0.00181,
"disconnected": false
KeyboardInterrupt
make: *** [test-fast] Error 130
```

**Qualification from Opus's review:** SIGINT itself sets the SSE flag. This captured incident is
therefore contaminated by the interruption and does not prove the cause of the preceding failures.
The earlier failure cascade is consistent with the T-4 mechanism, but is not proved by this trace.
The original run was stopped and reported, not retried. Garima then explicitly authorised T-5 as a
separate fix with new gates. Those new gates and the unpolluted deterministic red test follow.

## T-5: isolated SSE regression and repair

The draft was stashed with only its five paths. Recorded SHA:
`a98332015e96cf84d8b7b97fc66ea165e11e7237`, message `contact-fallback-A-draft-t5`.
After T-5 was committed, that exact SHA was applied without conflict. Four restored files matched
the saved SHA-256 values; test_server minus the committed T-5 regression was byte-identical to the
saved draft. The stash entry was identified by SHA/message before being dropped:

```text
Dropped stash@{0} (a98332015e96cf84d8b7b97fc66ea165e11e7237)
```

The only conftest change, at the start of serving before server creation:

```python
# sse-starlette keeps one process-wide drain flag; a previous test server's shutdown can
# leave it set and cut off later event streams (T-4). Production has one server per process,
# so each test server starts with that same fresh-process flag state.
module = sys.modules.get("sse_starlette.sse")
if module is not None:
    module.AppStatus.should_exit = False
```

The regression runs in an isolated subprocess with a hard timeout. It sets the loaded module's flag
True before starting one serving block, calls actual MCP availability on fixed harness data, and
checks the outcome, no recorder incident, and the flag False at server start. It reaches the module
only through sys.modules; there is no new import/dependency. Timeout cleanup is subprocess.run's
kill-and-reap handling. The existing recorder and its strict failure behavior are unchanged.

Command (services/mcp), red before conftest change then green after:

```bash
uv run pytest tests/test_server.py::test_serving_resets_previous_server_sse_drain_flag -q --tb=short
```

Actual red excerpt (`.context/t5/red.txt`), with no SIGINT:

```text
TimeoutError
Incomplete HTTP response: POST /mcp/ #1 confirmed=true
"sse_should_exit": true
1 failed, 2 warnings in 12.90s
```

Actual green (`.context/t5/green.txt`):

```text
1 passed, 2 warnings in 2.38s
```

Recorder/serving/watchdog gate:

```bash
uv run pytest tests/test_server.py -q -k 'recorder or watchdog or serving'
```

```text
34 passed, 48 deselected, 2 warnings in 30.95s
```

Each approved fast gate ran once without interruption:

```bash
PYTEST_ADDOPTS=--tb=short timeout -k 10 900 make test-fast
```

T-5 with contact draft set aside (`.context/t5/fast.txt`):

```text
All checks passed!
1166 passed, 14 deselected, 2 warnings in 84.99s (0:01:24)
```

Contact A after restoring the draft (`.context/t5/fast-with-contact-A.txt`):

```text
All checks passed!
1209 passed, 14 deselected, 2 warnings in 85.83s (0:01:25)
```

T-5 and restored A both regenerated `make schema`: cmp exit 0, 64,111 bytes,
`3ef91e78ccfc8b730c540244f8e390bb1ca2bdc74576a8cc4207f93ecc7d6c62`.
Ruff: `All checks passed!`; git diff --check: exit 0. T-5 Vulture on conftest/server and A Vulture on
the contact Python scope: confidence 80, empty output before/after, cmp exit 0.
No reset was added outside serving, no recorder logic changed, no retry/skip/timeout increase was
added. Seeding True in the isolated test is the deliberate regression precondition, not a reset.

## Publication and final checks

Publication changes only summary tool/callerMobile descriptions and version metadata. The actual
server regenerated the snapshot, affected VOICE-TEAM input schema/table row and description. S1 and
SL1 receive dated supplements; original SL1/D-1 and historical release notes stay unchanged. PLAN's
current references use the combined release version; gates 8 and 9 are explicitly pending.

Schema comparison (`python3 .context/contact-fallback/schema-publication.py`):

```text
Structural schemas identical after removing descriptions and normalizing version. Other three tools byte-equivalent as JSON objects.
Changed paths:
.instructions
.schemaVersion
.tools[3].description
.tools[3].inputSchema.properties.callerMobile.description
Snapshot and affected voice input schema, table row, and tool description regenerated from server output.
```

Commit B fast gate, one run (`.context/contact-fallback/B-fast.txt`):

```bash
PYTEST_ADDOPTS=--tb=short timeout -k 10 900 make test-fast
```

```text
All checks passed!
1209 passed, 14 deselected, 2 warnings in 84.82s (0:01:24)
```

Full build/check gate, one run (`.context/contact-fallback/B-full.txt`), exit 0:

```bash
env -u OPS_E2E_BASE_URL timeout -k 10 900 ./scripts/test.sh
```

Actual output excerpts:

```text
== install (frozen)
== lint
All checks passed!
1209 passed, 14 deselected, 2 warnings in 87.49s (0:01:27)
== process e2e (stubs + adapter over TCP)
5 passed, 1218 deselected, 2 warnings in 5.75s
== package build
Successfully built /tmp/frontdesk-mcp-build/frontdesk_mcp-0.1.0.tar.gz
Successfully built /tmp/frontdesk-mcp-build/frontdesk_mcp-0.1.0-py3-none-any.whl
== production image build (no stubs, no fixtures, no dev dependencies)
== development stubs image build (compose profile stubs)
== external gates not run: no profile loaded (scripts/run-profile.sh mock|live -- ./scripts/test.sh)
== all suites passed
```

Docker builds actually ran. The production image passed the script's checks excluding the stubs
and pytest. No standalone static type checker is configured; none was added or claimed.

Local external checks reused the 4b-M1 process helper with output paths changed, one run per slot
mode. The helper starts local stubs/adapter, strips owner/deployed environment values, seeds only
local synthetic data, and retains the HTTPS write gate. Synthetic Dr Garima/Urology; fixed future
journey dates 2099-01-05 and 2099-01-12. Its additional read-only General Medicine today smoke
returned DOCTORS_MATCHED, complete=true, ASK_WHICH_DOCTOR. No external owner was called.

```bash
# services/mcp
PYTHONPATH=src:dev:. uv run python ../../.context/contact-fallback/local-external.py
# Each mode invokes, without a retry:
timeout -k 5 90 uv run pytest tests/test_external.py tests/test_external_transport.py -m external -v --tb=short
```

Actual pytest summaries (each pytest exit 1; helper preserves these statuses):

```text
slots disabled: 6 failed, 3 passed, 2 warnings in 0.80s
slots enabled:  6 failed, 3 passed, 2 warnings in 0.73s
```

These are **not green external suites**. Both have the same six explicit BLOCKED failures:

```text
positive write journey: BLOCKED: write tests require an expected tenant and an HTTPS owner endpoint
negative UNKNOWN test:  BLOCKED: write tests require an expected tenant and an HTTPS owner endpoint
knowledge search:      BLOCKED: KNOWLEDGE_E2E_BASE_URL is not set
deployed smoke:        BLOCKED: SMOKE_EXPECT_KNOWLEDGE is not set
deployed headers:      BLOCKED: MCP_E2E_URL is not set
deployed lookup:       BLOCKED: MCP_E2E_URL is not set
```

The three passes in each mode cover token/reads, refusal without a bearer, and availability against
local stubs. The new summary POST/raw-storage hooks never execute through the HTTPS guard locally;
no storage claim follows from these runs. The separate process e2e does verify saved stub contact.
The disabled/enabled runs are distinct required configurations, not retries of a failed gate.

Published schema: `2026-10-10.1`, 64,603 bytes,
SHA-256 `d666020548a83315c47ac2529a1972efa89f5bbe722786d18de7316f55454fdf`.
Historical VOICE-TEAM release notes are byte-preserved; generated snapshot matches server output.
Protected SHA-256 check: 15 files unchanged, including every user-owned temp file.

Vulture: the same contact Python scope and `--min-confidence 80`, exit 0, empty output identical to
baseline. `CLAUDE.md` has 47 lines (limit: under 80). `git diff --check`: exit 0.

Whole-repository search:

```bash
rg -n 'never copied|caller gave|caller-supplied|Only when the caller gave it' --glob '!.context/**' --glob '!temp/**'
```

No stale current summary rule found. Remaining matches are unchanged pins/overlays, historical
contract/ContextForge evidence, the approved plan describing the rule being removed, the explicit
pending Manoj gate, or unrelated JWT caller-supplied-token text. No owner pin/overlay was rewritten.

Read-only independent reviews: no concrete T-5 findings; no critical/important contact-A findings
(the minor formatted-log assertion gap was addressed); no concrete publication-B findings.
The final hand-back also received read-only review with no concrete accuracy/scope findings.
Review is not a substitute for the tests or external release gates.

## Live-summary evidence and unverified work

Historical local artifacts exist from the separately authorised 9 October journey: `.context/live-write-journey-20261009.txt` and `.xml`, showing `1 passed, 1 warning in 7.96s` with slots enabled. They contain no captured raw summary response/body or call ID; **no captured artifact proving the stored contact number** is available. The missing contact conclusion came from the executed test and summary code. No live call was repeated in this build task.

Not verified:

- Live Manoj storage; the raw external response assertion cannot execute locally because the HTTPS
  gate remains intact. Storage of callerMobile is not independently verified by this build.
- ContextForge or the voice platform; real caller-ID provenance.
- Release gates 1–9. Gates 8–9 require Manoj's agreement to caller-ID contact semantics and the
  voice/gateway owners' assurance that the number belongs to the end caller, not a trunk/placeholder.
- Production latency, live deployments or cloud cleanup. No new gate closure is claimed from
  historical tests. LOG-1 is not fixed or claimed fixed.

## Self-review

One rule lives in SummaryService.record and reuses existing conversion; no new runtime abstraction,
custom validation boundary, parallel body builder, identity state or authorization path. The tests
assert owner-boundary behavior, privacy, replay and immutable requests. The external hook reads real
raw content without an extra owner request or fabricated response. All contacts are synthetic.

Only the authorised T-5/A/B files were changed by this task. Unrelated protected SHA-256 hashes remain
unchanged. No owner calls, secrets, push, merge or deployment. Original failures, test-authoring
mistakes and SIGINT contamination are retained above. The local implementation is ready for code review;
external gates remain open and it is not approved for merge or deployment.
