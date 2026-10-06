# Booking F-1: action-specific rejection fields

## Design note (written before code)

1. Root cause: `_failure` flattens every write action's field mapping, so LIST loses its date aliases and mislabels the trusted caller number.
2. `_failure` owns rejection translation; `_OWNER_FIELDS` remains the single owner-to-tool relationship.
3. Add LIST's `from`, `to`, and `status` entries to that existing mapping; exclude its trusted `mobile`.
4. Derive each action's translation once at module load, including identity aliases for its tool names.
5. Reuse the existing write mappings unchanged, so request bodies and valid canonical names stay unchanged.
6. Replace `_failure(exc, write)` with `_failure(exc, action)` and derive `write = action != "LIST"` internally.
7. Update all five callers: `_list`, `_create`, `_schedule_gate`, `_change`, and `_reschedule_gate`.
8. Pass the originating action into `_schedule_gate` from both `_create` and `_reschedule_gate`.
9. Remove the per-call flattened dictionary and global model-field intersection: the action mapping already limits outputs to valid tool names.
10. Prove lookup and schedule rejection behaviour at the HTTP boundary; retain existing M-1/error tests and the schema snapshot unchanged.



## Implementation and impact

The rule lives in `booking.py`'s existing `_OWNER_FIELDS`, now with LIST query aliases. `_REJECTION_FIELDS` is generated entirely from that mapping once at module load; it is not a second handwritten rule. Identity aliases preserve already-canonical names only for the applicable action. `_write_body` still uses the same unchanged write-action entries.

`_failure` now takes `action`, replacing its boolean parameter. All five former callers preserve the exact read/write equivalence. The schedule gate carries the originating CREATE or RESCHEDULE action from both callers. An internal RESCHEDULE lookup never adopts LIST's names just because it calls `GET /appointments`.

Removed: the per-call flattened mapping, the boolean parameter, and the global `BookingRequest.model_fields` intersection. The intersection is redundant because every permitted result is already a tool-name value in that action's mapping. Sorted, deduplicated fields and owner error codes are preserved; owner error prose remains excluded.

Affected files in the code commit:
- `services/mcp/src/frontdesk_mcp/booking.py`: translation and action propagation.
- `services/mcp/tests/test_booking.py`: nine HTTP-boundary regression cases appended; existing tests unchanged.
- `docs/DECISIONS.md`: replace the now-incomplete “write-body mapping” wording with the originating action's owner-field mapping (also used for write bodies).
- This hand-back: pre-code design and verification evidence.

`VOICE-TEAM.md` remains accurate and unchanged. No changes to tool definitions, schemas, schema version, request bodies, operation keys, transport, retries, deadlines, authentication, secrets, configuration or deployment. No additional I/O. B-1, B-3, M-2, G-1, and review nit F-2 remain untouched.

## Red then green

Run from `services/mcp` before changing production code, then run unchanged after the fix:

```sh
uv run pytest tests/test_booking.py -q -k 'appointment_lookup_rejection or schedule_rejection or owner_create_rejection or owner_change_rejection'
```

Before (exit 1; exact assertion differences and failure summary):

```text
E         At index 3 diff: ['patientMobile'] != []
E         At index 3 diff: [] != ['fromDate', 'toDate']
E         At index 3 diff: ['doctorId', 'patientMobile'] != []
E         At index 3 diff: ['patientMobile'] != []
E         At index 3 diff: ['patientMobile', 'status'] != []
E         At index 3 diff: ['doctorId', 'newPreferredTime'] != ['doctorId']
E         At index 3 diff: ['doctorId', 'newPreferredTime'] != ['newPreferredTime']
FAILED tests/test_booking.py::test_appointment_lookup_rejection_uses_the_requested_action[LIST-owner_fields0-tool_fields0]
FAILED tests/test_booking.py::test_appointment_lookup_rejection_uses_the_requested_action[LIST-owner_fields1-tool_fields1]
FAILED tests/test_booking.py::test_appointment_lookup_rejection_uses_the_requested_action[LIST-owner_fields3-tool_fields3]
FAILED tests/test_booking.py::test_appointment_lookup_rejection_uses_the_requested_action[RESCHEDULE-owner_fields4-tool_fields4]
FAILED tests/test_booking.py::test_appointment_lookup_rejection_uses_the_requested_action[RESCHEDULE-owner_fields5-tool_fields5]
FAILED tests/test_booking.py::test_schedule_rejection_uses_the_originating_action[CREATE-tool_fields0]
FAILED tests/test_booking.py::test_schedule_rejection_uses_the_originating_action[RESCHEDULE-tool_fields1]
7 failed, 12 passed, 88 deselected in 0.42s
```

The seven failing cases cover LIST mobile, LIST dates, LIST unrelated arguments, RESCHEDULE lookup mobile, RESCHEDULE lookup unrelated arguments, and CREATE/RESCHEDULE schedule-gate field isolation. The two new cases that already passed guard applicable canonical names and status. All ten existing M-1 cases passed before and after without edits.

Each new case drives the real service and OpsClient with an owner HTTP 400. Tests check `REJECTED`/`ASK_TO_CORRECT`, unchanged `VALIDATION_FAILED`, filtered fields, absence of owner prose and no appointment/reschedule POST. Lookup cases additionally check the actual outgoing query (trusted mobile and LIST date/status filters).

After (exit 0):

```text
...................                                                      [100%]
19 passed, 88 deselected in 0.21s
```

## All callers

```sh
rg -n 'self\._failure\(|self\._schedule_gate\(' services/mcp/src/frontdesk_mcp/booking.py
```

```text
189:            return self._failure(exc, request.action)
214:        if blocked := await self._schedule_gate(request.doctorId, requested, request.session, preferred, deadline, now,
224:            return self._failure(exc, request.action)
239:            return self._failure(exc, action)
298:            return self._failure(exc, request.action)
310:                return self._failure(exc, request.action)
320:        return await self._schedule_gate(current.doctorId, requested, request.session, new_time, deadline, now,
```

The five `_failure` sites belong to `_list`, `_create`, `_schedule_gate`, `_change`, `_reschedule_gate`, respectively. The two schedule call continuations both pass `request.action`.

## Fast suite, dead code and schema

`make test-fast` (exit 0):

```text
cd services/mcp && uv run ruff check . ../../deploy && uv run pytest tests -q -m "not e2e and not external"
All checks passed!
........................................................................ [ 12%]
........................................................................ [ 24%]
........................................................................ [ 36%]
........................................................................ [ 48%]
........................................................................ [ 60%]
........................................................................ [ 72%]
........................................................................ [ 84%]
........................................................................ [ 96%]
.......................                                                  [100%]
=============================== warnings summary ===============================
.venv/lib/python3.13/site-packages/fastmcp/server/auth/providers/jwt.py:10
  /Users/garima/conductor/workspaces/healthcare-tools/des-moines/services/mcp/.venv/lib/python3.13/site-packages/fastmcp/server/auth/providers/jwt.py:10: AuthlibDeprecationWarning: authlib.jose module is deprecated, please use joserfc instead.
  It will be compatible before version 2.0.0.
    from authlib.jose import JsonWebKey, JsonWebToken

.venv/lib/python3.13/site-packages/authlib/integrations/httpx_client/assertion_client.py:5
  /Users/garima/conductor/workspaces/healthcare-tools/des-moines/services/mcp/.venv/lib/python3.13/site-packages/authlib/integrations/httpx_client/assertion_client.py:5: AuthlibDeprecationWarning: The httpx module is deprecated; please use httpx2 instead.
    from ._compat import httpx2

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
599 passed, 11 deselected, 2 warnings in 30.64s
```

The same two upstream Authlib deprecation warnings were present in the baseline run (590 passed). No new warning was introduced.

```sh
uvx vulture services/mcp/src/frontdesk_mcp/booking.py --min-confidence 80
```

Exit 0; stdout/stderr empty, no dead-code findings.

```sh
make schema > .context/booking-f1-schema.json
cmp .context/booking-f1-schema.json services/mcp/tests/contracts/mcp-tools.snapshot.json
```

Both exit 0; `cmp` emits nothing: schema byte-identical, no `SCHEMA_VERSION` bump. Schema generation emits the same two dependency deprecation warnings above.

Additional verification: `git diff --check` exit 0. Comparing the prior test file from `git show b1ce587:services/mcp/tests/test_booking.py` to the current prefix proves that every existing test remains byte-for-byte unchanged; only nine new parameterized cases are appended.

## Self-review

- Why a derived dictionary? It avoids rebuilding names on every error and preserves accepted canonical tool names without any parallel handwritten list. Every action entry is used by rejection handling; write entries still drive request bodies too.
- Why pass action through the schedule gate? It cannot infer CREATE versus RESCHEDULE from a doctor-profile request. Using its caller's action prevents returning CREATE-only `doctorId` during RESCHEDULE.
- Why remove the model-wide filter? It permitted names belonging to other actions. The action-specific translation is a stricter allowlist and provides the complete output set itself.
- Why change one decisions sentence? LIST's query aliases are now part of the rule, so “write-body mapping” alone no longer describes it fully.
- Security and safety: trusted phone numbers stay outside actionable LIST/RESCHEDULE errors. Confirmations, identity gates, uncertainty handling and clinical/availability policies are unchanged. Boundary tests prove rejected reads do not proceed to writes.
- Compatibility and latency: the tool contract is unchanged; only incorrect rejection field suggestions change. No new REST calls or retries; translation is precomputed. Production latency was not measured for this local fix.

## Commits and handoff

- Starting code: `b1ce587`.
- Review-only docs commit: `49da15c` (`Publish Opus booking B2 and M1 review`), one file, original review unchanged.
- The following single code commit contains these four files; its hash is provided in the final handoff (a commit cannot contain its own hash).
- Local review handoff only. No push, merge, deployment, live API write or Azure change. User-owned `temp/` remains untouched.

## Complete verification

```sh
env -u OPS_E2E_BASE_URL ./scripts/test.sh
```

Exit 0. Exact stage markers and results:

```text
== install (frozen)
== lint
All checks passed!
== hermetic suites
599 passed, 11 deselected, 2 warnings in 30.31s
== process e2e (stubs + adapter over TCP)
2 passed, 608 deselected, 2 warnings in 2.67s
== package build
Successfully built /tmp/frontdesk-mcp-build/frontdesk_mcp-0.1.0.tar.gz
Successfully built /tmp/frontdesk-mcp-build/frontdesk_mcp-0.1.0-py3-none-any.whl
frontdesk_mcp-0.1.0-py3-none-any.whl
frontdesk_mcp-0.1.0.tar.gz
== production image build (no stubs, no fixtures, no dev dependencies)
== development stubs image build (compose profile stubs)
== external gates not run: no profile loaded (scripts/run-profile.sh mock|live -- ./scripts/test.sh)
== all suites passed
```

Both Docker images were built, and the production-image exclusion checks passed. The process tests exercise local stub and MCP server processes over TCP. No live-owner, deployed-gateway, or voice-agent tests were run; this task does not authorize deployment and changes no external contract. Ready for review/merge consideration; deploying the accumulated branch remains a separately approved action. No owner input is needed for this F-1 fix.
