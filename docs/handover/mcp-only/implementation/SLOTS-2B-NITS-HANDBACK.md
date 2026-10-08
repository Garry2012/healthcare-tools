# Slots phase 2b: Opus review cleanups

Review: `OPUS-SLOTS-2B-REVIEW.md`, approved head `8779ac4`.
Opus found no blockers and approved proceeding to phase 3a-1. Both optional nits
are addressed here; no later-phase work is included.

## Design and changes

- **N-1:** the successful on-call test had lost its callback reason assertion.
  `tests/test_availability.py` now compares the complete callback with the literal
  `{reason: ON_CALL_DOCTOR, summaryOutcome: CALLBACK_NOTED}` for today and future.
  Existing outcome and request-path assertions remain intact. No production
  callback code needed changing.
- **N-2:** AUTH is an error reason, not a read stage. `BookingService._schedule_gate`
  now chooses AUTH directly before using `read_failure_detail` for other failures.
  The helper in `schedule_reader.py` now maps only board, profile and slots.
  Its other caller, `AvailabilityService._service_error`, stays unchanged.
  Existing fallback, retry-after, refusal outcomes and no-write behaviour remain.

No signature, policy, schema/version, deployment, secret, prompt or API changes.
No new helper or test fixture. Removed the pseudo-stage entry and intermediate
stage variable. The two existing helper callers were checked by repository search.

## Honest failure and passing evidence

These are test coverage and behaviour-preserving refactoring cleanups, not fixes
for broken baseline runtime behaviour. The failures below were deliberately
induced to verify regression protection; they are **not baseline failures**.

### N-1: restored assertion

Command, from `services/mcp`:

```sh
uv run pytest tests/test_availability.py -q -k on_call_by_name_still
```

With the restored assertion and original production code:

```text
2 passed, 102 deselected in 0.23s
```

Then temporarily changed the single-doctor response mapper's callback reason to
NO_USUAL_SCHEDULE. The full assertion caught this for both dates:

```text
{'reason': <Reason.NO_USUAL_SCHEDULE: 'NO_USUAL_SCHEDULE'>} != {'reason': 'ON_CALL_DOCTOR'}
2 failed, 102 deselected in 0.17s
```

The temporary production mutation was restored in a `finally` block. It is not
part of the final diff.

### N-2: existing AUTH regression tests

First removed the pseudo-stage AUTH entry from the helper, before relocating
booking's AUTH handling. Ran:

```sh
uv run pytest tests/test_booking.py -q -k 'slot_failures_prevent_booking_writes and (401 or 403)'
```

Existing tests caught the incomplete refactor for CREATE and RESCHEDULE:

```text
At index 2 diff: 'PROFILE_UNAVAILABLE' != 'AUTH'
4 failed, 149 deselected in 0.25s
```

Then moved the AUTH decision into booking, as Opus requested. No new test of
private implementation structure was added.

### Both cleanups, final focused result

```sh
uv run pytest tests/test_availability.py tests/test_booking.py -q \
  -k 'on_call_by_name_still or slot_failures_prevent_booking_writes or legacy_availability'
```

```text
23 passed, 234 deselected in 0.29s
```

## Scope and remaining work

The on-call latency exception is the brief's wording conflict, as Opus confirmed;
no code correction is required. Measure that path in phase 4b. Slot policy
activation remains phase 3a-2. Phase 3a-1 may begin, but this intermediate phase
is not production deployment approval.

No live owner API calls, Azure changes, push, merge or deployment. Existing
`temp/` is preserved. The supplied Opus report is preserved byte-for-byte.

## Final verification

`make test-fast` (exit 0):

```text
All checks passed!
794 passed, 11 deselected, 2 warnings in 38.02s
```

`env -u OPS_E2E_BASE_URL ./scripts/test.sh` (exit 0):

```text
All checks passed!
794 passed, 11 deselected, 2 warnings in 38.24s
2 passed, 803 deselected, 2 warnings in 2.91s
Successfully built /tmp/frontdesk-mcp-build/frontdesk_mcp-0.1.0.tar.gz
Successfully built /tmp/frontdesk-mcp-build/frontdesk_mcp-0.1.0-py3-none-any.whl
== production image build (no stubs, no fixtures, no dev dependencies)
== development stubs image build (compose profile stubs)
== external gates not run: no profile loaded (scripts/run-profile.sh mock|live -- ./scripts/test.sh)
== all suites passed
```

Both warnings are existing Authlib deprecations.

`make schema > .context/slots-2b-nits-schema.json` and `cmp` against
`services/mcp/tests/contracts/mcp-tools.snapshot.json`: exit 0, byte-identical.
SHA-256: `1442e16900d49064d54d7d7e655b467211ba3c16ffdc3a6b897872a3d567a206`.
No schema-version bump.

`uvx vulture --min-confidence 100` over the three touched Python files: no output,
exit 0. `git diff --check`: exit 0. No separate type checker is configured.
No live service or latency verification was performed.

Self-review: four inserted and four removed Python lines in three files. The
restored assertion protects an actual response field. The AUTH relocation keeps
one booking-specific priority rule and one shared stage mapping, with no changed
signature or extra branch elsewhere. No temporary mutations remain. Review and
evidence are included with the cleanup commit, named `Address phase 2b review nits`.
