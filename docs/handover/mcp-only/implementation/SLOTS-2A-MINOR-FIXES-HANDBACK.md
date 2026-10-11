# Slots phase 2a: Opus M-1 through M-4 follow-up

Date: 8 October 2026. Base: `d61867ec05e0f989c72f903a4a73791108ea366e`.
This report accompanies the separate `Fix phase 2a review notes` commit on
`Garry2012/slots-phase-1a-1b`. No push, merge, deploy, owner calls or Azure changes.

## Changes and design

Only the development stub, two test files and this hand-back changed. Production
transport, tool behavior, configuration, authentication, deadlines and schema are unchanged.

| Finding | Root cause and correction | Evidence |
|---|---|---|
| M-1 | An unscripted slot plan indexed optional `blockMinutes` directly. It now uses the existing `default_capabilities()` value when omitted. No second default or new state. | A contract-valid capabilities fixture without minutes now produces a complete disabled plan with 30-minute blocks. |
| M-2 | HTTP `writeOutcomes` accepted raw JSON without conversion or validation. One Pydantic `TypeAdapter` validates the existing two TypedDict shapes before any scenario state is changed. Numeric string statuses are normalised; malformed items return HTTP 400. | A string `"409"` yields an actual 409 write response, followed by a successful scripted write. Fifteen invalid cases return 400 without partially adding queue entries or `failNext`. |
| M-3 | The existing rule consumed one queue item before handler validation, but coverage did not pin that fact. A comment and stronger test now document/assert consumption and show that the following valid write has no leaked `slotTime`. | Existing behavior passes. A disposable in-memory mutation replacing `pop(0)` with indexing is caught by the test. No queue semantic change. |
| M-4 | The field-parity test omitted the inline session schema. The existing parameterised test now also reads `SlotPlan.properties.sessions.items` and compares required names with `SlotSession`. | Existing model passes. A disposable in-memory mutation removing `bookable` is caught. Required/null-label tolerance remains unchanged. |

M-2 reuses the installed Pydantic dependency, the existing `ErrorCode` literal,
the existing stub time pattern and the existing FIFO. Error items require an HTTP
error status (400–599) and a known code; success items require an HH:MM `slotTime`.
Extra or mixed-shape keys are rejected. In-process fixture assignment remains
unchanged, including intentional invalid fixtures used in conformance tests.
No new queue, alternate parser or compatibility path was introduced.

## Tests before implementation

From `services/mcp`:

```sh
uv run pytest tests/test_stubs.py tests/test_contract.py -q \
  -k 'omit_them or http_write_outcomes or success_fixture or slot_model_fields'
```

Actual output before the stub fixes:

```text
E   KeyError: 'blockMinutes'
E   TypeError: '<' not supported between instances of 'str' and 'int'
E   assert (200 == 400)
17 failed, 4 passed, 72 deselected in 1.32s
```

Breakdown: M-1 failed once; M-2 failed sixteen cases. M-3 and M-4 were
coverage additions for correct existing behavior, so they passed immediately
(alongside the existing SlotPlan/SlotBlock parity cases). They are not claimed
as previously failing product behavior.

After implementation, the same command:

```text
21 passed, 72 deselected in 0.79s
```

Additional sensitivity checks used altered source loaded only into disposable
Python processes. No source file was changed. M-3 mutation output:

```text
M3: in-memory mutation only; expected test failure
E   AssertionError: assert {'/appointments': [{'slotTime': '11:00'}]} == {'/appointments': []}
1 failed, 1 warning in 0.30s
```

M-4 mutation output:

```text
M4: in-memory mutation only; expected test failure
E     Extra items in the right set:
E     'bookable'
1 failed in 0.23s
```

The M-3 mutation runner emitted a pytest module-already-imported warning; it did
not affect the assertion. Normal runs did not use either mutation.

## Full verification

```text
make test-fast
All checks passed!
689 passed, 11 deselected, 2 warnings in 37.35s

env -u OPS_E2E_BASE_URL ./scripts/test.sh
All checks passed!
689 passed, 11 deselected, 2 warnings in 36.83s
2 passed, 698 deselected, 2 warnings in 2.65s
Successfully built /tmp/frontdesk-mcp-build/frontdesk_mcp-0.1.0.tar.gz
Successfully built /tmp/frontdesk-mcp-build/frontdesk_mcp-0.1.0-py3-none-any.whl
== production image build (no stubs, no fixtures, no dev dependencies)
== development stubs image build (compose profile stubs)
== external gates not run: no profile loaded (scripts/run-profile.sh mock|live -- ./scripts/test.sh)
== all suites passed
```

The full script exited 0, including both Docker builds and checks excluding
development stubs and pytest from the production image. The two normal-run
warnings are existing Authlib deprecations.

```sh
make schema > .context/slots-2a-minors-schema.json
cmp .context/slots-2a-minors-schema.json services/mcp/tests/contracts/mcp-tools.snapshot.json
```

`cmp` exited 0. SHA-256:
`1442e16900d49064d54d7d7e655b467211ba3c16ffdc3a6b897872a3d567a206`.
No schema-version bump.

From `services/mcp`:

```sh
uvx vulture dev/frontdesk_stubs/ops.py tests/test_contract.py tests/test_stubs.py --min-confidence 100
```

Exit 0, no output. `git diff --check` also passed. No separate type-check command
is configured in this repository.

Full local logs are `.context/slots-2a-minors-{red,green,fast,full,vulture}.txt`;
mutation evidence is `.context/slots-2a-minors-m{3,4}-mutation.txt`. Essential
results are pasted above so this tracked hand-back does not depend on those files.

## Scope and disposition

- M-1 through M-4 are addressed. The changes are ready for follow-up review.
- Phase 2b was not started. The separate pre-existing `reject_next_create`
  cleanup was not included.
- No real backend, voice-path or Azure validation was run; this is fixture/test
  maintenance and requires no new owner credentials or approvals.
- Existing untracked Opus reports and `temp/` were preserved, not staged.
- No production behavior changes or new production latency; no deployment is
  needed to use these test improvements. Merge/deploy were not performed.
