# Booking B-2 / M-1 hand-back

## Step 0 — design note (written before code)

1. B-2: duplicated session membership comparisons omit facility now, admitting elapsed times in still-open sessions.
2. `availability_policy.decide_booking` owns the rule; one helper will replace both comparisons and use `time.fromisoformat`, as `_window` does.
3. For LIVE_BOARD only, the lower bound is max(start, now at minute precision); usual schedules stay unchanged.
4. Unknown start/end handling and whole-scope refusal precedence remain in their existing branches.
5. Reuse `_create`/`_change`'s captured `local_now`; remove `_schedule_gate`'s second clock read.
6. Signature callers: `_create` and `_reschedule_gate` call `_schedule_gate`; `_change` calls `_reschedule_gate`; `_schedule_gate` and policy tests call `decide_booking`.
7. M-1: `_failure` forwards owner field names without translating/filtering them to tool arguments.
8. One action-indexed owner-to-tool mapping will drive normalized write-body fields and rejection translation; replace the implicit body-name pairs rather than adding a parallel list.
9. Reuse `BookingRequest.model_fields` for allowed output names and summary's sorted set/filter principle; summary and OpsClient need no change. No existing body mapper or now-aware membership helper exists.
10. Retain trusted call/caller fields outside that mapping; update only the two prescribed doc bullets, test fixtures needed for the new rule, and evidence. No schema, owner contract, network, retries or authentication changes.

Initial docs commit: `84103b0` (two Opus files preserved unchanged); `make test-fast`: 552 passed, 11 deselected, 2 warnings in 32.62s.


## Result and rule ownership

**B-2:** `_contains_time` replaces both membership comparisons inside `decide_booking`. It parses
clock times exactly as `_window` already does, applies the LIVE_BOARD lower bound at minute precision,
and leaves usual schedules alone. CREATE captures facility time once; RESCHEDULE passes its existing
captured time through the appointment lookup and shared schedule gate. Removed the duplicate clock
read. Existing unknown-start/end branches still hand off, and whole-scope SESSION_ENDED/CANCELLED
precedence stays ahead of time matching. Availability policy functions, including their end-time
precision, are unchanged.

**M-1:** `_OWNER_FIELDS` is the sole owner/tool field relationship for CREATE, CANCEL and RESCHEDULE.
`_write_body` uses it to select normalized request values; `_failure` derives translation from the same
mapping, intersects with `BookingRequest.model_fields`, and sorts/de-duplicates the surviving names.
This reuses summary's filtering principle without changing summary or introducing a shared framework.
Trusted callerMobile/callId are added separately from trusted context and cannot be supplied by the
model. Removed the implicit body field-name pairs, duplicated callId assignment in the two change
branches, and raw rejection-field forwarding. Existing owner error detail is retained.

No existing helper expressed either required relationship. The new membership helper replaces two
comparisons; the small body helper makes the single field map usable in both directions. No flags,
new settings, reason codes, schema fields, REST calls, retries or transport changes were added.
Runtime delta: availability_policy +12/-3; booking +28/-24. The net increase is the shared rule and
explicit mapping, not a second path.

## Test-first proof

Before production edits, the new tests ran against the pre-fix implementation:

```sh
services/mcp/.venv/bin/pytest -q services/mcp/tests/test_availability_policy.py services/mcp/tests/test_booking.py -k 'booking_window or mcp_create_respects or mcp_reschedule_refuses or owner_create_rejection or owner_change_rejection'
```

B-2 red excerpts (the old code allowed the write):

```text
E            +  where False = isinstance(Write(), <class 'frontdesk_mcp.availability_policy.NotAvailable'>)
E       AssertionError: assert 'NOTED' == 'NOT_AVAILABLE'
E       AssertionError: assert ('NOTED', Non...EQUEST_NOTED') == ('NOT_AVAILAB...SION_OR_TIME')
```

M-1 red excerpts (the old code returned the owner field):

```text
E         At index 3 diff: ['mobile'] != ['patientMobile']
E         At index 3 diff: ['expectedTime'] != ['preferredTime']
```

Actual combined red summary and failing test names:

```text
FAILED services/mcp/tests/test_availability_policy.py::test_booking_window_uses_facility_minute_only_for_today[09:15-None-today]
FAILED services/mcp/tests/test_availability_policy.py::test_booking_window_uses_facility_minute_only_for_today[09:15-Morning-today]
FAILED services/mcp/tests/test_booking.py::test_mcp_create_respects_todays_current_minute[09:15-NOT_AVAILABLE]
FAILED services/mcp/tests/test_booking.py::test_mcp_reschedule_refuses_a_passed_time_today
FAILED services/mcp/tests/test_booking.py::test_owner_create_rejection_names_only_actionable_tool_arguments[owner_fields0-tool_fields0]
FAILED services/mcp/tests/test_booking.py::test_owner_create_rejection_names_only_actionable_tool_arguments[owner_fields1-tool_fields1]
FAILED services/mcp/tests/test_booking.py::test_owner_create_rejection_names_only_actionable_tool_arguments[owner_fields2-tool_fields2]
FAILED services/mcp/tests/test_booking.py::test_owner_create_rejection_names_only_actionable_tool_arguments[owner_fields3-tool_fields3]
FAILED services/mcp/tests/test_booking.py::test_owner_create_rejection_names_only_actionable_tool_arguments[owner_fields4-tool_fields4]
FAILED services/mcp/tests/test_booking.py::test_owner_create_rejection_names_only_actionable_tool_arguments[owner_fields5-tool_fields5]
FAILED services/mcp/tests/test_booking.py::test_owner_create_rejection_names_only_actionable_tool_arguments[owner_fields6-tool_fields6]
FAILED services/mcp/tests/test_booking.py::test_owner_change_rejection_names_the_tool_argument[RESCHEDULE-newExpectedTime-newPreferredTime]
FAILED services/mcp/tests/test_booking.py::test_owner_change_rejection_names_the_tool_argument[CANCEL-reason-reasonVerbatim]
13 failed, 25 passed, 120 deselected, 2 warnings in 2.28s
```

Four B-2 cases and nine M-1 cases failed. The 25 passing cases were preservation/boundary guards,
including future dates, current-minute acceptance, unknown boundaries and the unchanged newVisitDate
name. Those guards are not misrepresented as tests that failed before implementation.

After the implementation, the same combined command produced:

```text
38 passed, 120 deselected, 2 warnings in 2.12s
```

Per-item green commands (run from `services/mcp`):

```sh
uv run pytest tests/test_availability_policy.py tests/test_booking.py -q -k 'booking_window or mcp_create_respects or mcp_reschedule_refuses'
```

```text
28 passed, 130 deselected, 2 warnings in 2.08s
```

```sh
uv run pytest tests/test_booking.py -q -k 'owner_create_rejection or owner_change_rejection'
```

```text
10 passed, 88 deselected in 0.21s
```

The booking-service B-2 tests call the actual MCP tool over streamable HTTP, with trusted headers and
an in-process owner fixture. They assert no POST /appointments or /reschedule on refusal, preserve
open sessions as alternatives, and verify that 10:30 and 10:45 at 10:30:40 are recorded. M-1 CREATE
uses the existing reject_next_create stub hook; change rejections are injected only at the owner HTTP
boundary. Existing successful lifecycle tests still assert exact owner payloads and idempotency keys.

### Necessary fixture maintenance

The success fixture requested 09:30 with a fixed 10:00 clock. With B-2 fixed, 26 existing success-path
cases correctly stopped reaching their intended write. Moved that fixture to 10:45 in test_booking,
the HTTP journey, the gate-predicate fixture and benchmark; updated the corresponding expected wire
time and comment. Assertions, failure gates and intended scenarios remain intact. The past-time rule
now has its own explicit refusal tests. Existing N-2 assertions and inputs remain unchanged apart
from supplying the newly required `now` keyword in the policy test.

An intermediate direct pytest invocation from the repository root also produced two unrelated runner
failures: test_server subprocesses expected the service working directory and uv-provided CLI PATH.
The prescribed `make test-fast` runner supplied both and passed. No test or runtime change was made
for those invocation errors. Intermediate lint caught three overlong lines; they were wrapped before
the final passing run.

## Changed signatures: every caller

`decide_booking` requires `now`; `_schedule_gate` and `_reschedule_gate` receive the captured datetime.
The production flow is `_create` → `_schedule_gate` → `decide_doctor`/`decide_booking`, and `_change`
→ `_reschedule_gate` → `_schedule_gate` → the same policy. `_failure`'s signature is unchanged, so all
five existing rejection paths use the new field rule without additional call-site checks.

```sh
rg -n 'decide_booking\(|_schedule_gate\(|_reschedule_gate\(' services/mcp --glob '*.py'
```

```text
services/mcp/src/frontdesk_mcp/availability_policy.py:281:def decide_booking(decision: DoctorDecision, *, session: str | None,
services/mcp/src/frontdesk_mcp/booking.py:208:        if blocked := await self._schedule_gate(request.doctorId, requested, request.session, preferred, deadline, now):
services/mcp/src/frontdesk_mcp/booking.py:220:    async def _schedule_gate(self, doctor_id: str, requested: policy.RequestedDate, session: str | None,
services/mcp/src/frontdesk_mcp/booking.py:233:        booking = policy.decide_booking(decision, session=session, preferred_time=preferred, now=now)
services/mcp/src/frontdesk_mcp/booking.py:273:            if blocked := await self._reschedule_gate(mobile, request, requested, new_time, deadline, now):
services/mcp/src/frontdesk_mcp/booking.py:296:    async def _reschedule_gate(self, mobile: str, request: BookingRequest, requested: policy.RequestedDate,
services/mcp/src/frontdesk_mcp/booking.py:312:        return await self._schedule_gate(current.doctorId, requested, request.session, new_time, deadline, now)
services/mcp/tests/test_availability_policy.py:74:    result = p.decide_booking(decide(facts(end=None)), session="Morning", preferred_time=preferred, now=NOW)
services/mcp/tests/test_availability_policy.py:80:    assert isinstance(p.decide_booking(decide(facts(end=None)), session="Morning", preferred_time=None, now=NOW),
services/mcp/tests/test_availability_policy.py:88:    assert isinstance(p.decide_booking(mixed, session=None, preferred_time=None, now=NOW), p.SessionRequired)
services/mcp/tests/test_availability_policy.py:91:    assert isinstance(p.decide_booking(equal, session=None, preferred_time=None, now=NOW), p.Write)
services/mcp/tests/test_availability_policy.py:110:    assert isinstance(p.decide_booking(result, session=None, preferred_time=None, now=NOW), p.Callback)
services/mcp/tests/test_availability_policy.py:135:    result = p.decide_booking(decide(facts()), session="Morning", preferred_time="14:00", now=NOW)
services/mcp/tests/test_availability_policy.py:150:    result = p.decide_booking(doctor, session=None, preferred_time="21:00", now=NOW.replace(hour=hour))
services/mcp/tests/test_availability_policy.py:168:    result = p.decide_booking(decide(facts(statuses=("UNKNOWN",), end=None)),
services/mcp/tests/test_availability_policy.py:177:    result = p.decide_booking(decision, session=None, preferred_time=None, now=NOW)
services/mcp/tests/test_availability_policy.py:185:    assert isinstance(p.decide_booking(result, session="Morning", preferred_time=None, now=NOW.replace(second=30)),
services/mcp/tests/test_availability_policy.py:198:    booking = p.decide_booking(result, session="Evening", preferred_time=None, now=NOW)
services/mcp/tests/test_availability_policy.py:210:    result = p.decide_booking(doctor, session=session, preferred_time=preferred, now=now)
services/mcp/tests/test_availability_policy.py:228:    result = p.decide_booking(doctor, session=session, preferred_time=preferred, now=NOW.replace(minute=30))

```

The multiline call at test_availability_policy:168 supplies `now` on its next line. An AST check
independently verified the keyword on all 14 calls, including every multiline call.

## Verification

```sh
make test-fast
```

```text
cd services/mcp && uv run ruff check . ../../deploy && uv run pytest tests -q -m "not e2e and not external"
All checks passed!
........................................................................ [ 12%]
........................................................................ [ 24%]
........................................................................ [ 36%]
........................................................................ [ 48%]
........................................................................ [ 61%]
........................................................................ [ 73%]
........................................................................ [ 85%]
........................................................................ [ 97%]
..............                                                           [100%]
=============================== warnings summary ===============================
.venv/lib/python3.13/site-packages/fastmcp/server/auth/providers/jwt.py:10
  /Users/garima/conductor/workspaces/healthcare-tools/des-moines/services/mcp/.venv/lib/python3.13/site-packages/fastmcp/server/auth/providers/jwt.py:10: AuthlibDeprecationWarning: authlib.jose module is deprecated, please use joserfc instead.
  It will be compatible before version 2.0.0.
    from authlib.jose import JsonWebKey, JsonWebToken

.venv/lib/python3.13/site-packages/authlib/integrations/httpx_client/assertion_client.py:5
  /Users/garima/conductor/workspaces/healthcare-tools/des-moines/services/mcp/.venv/lib/python3.13/site-packages/authlib/integrations/httpx_client/assertion_client.py:5: AuthlibDeprecationWarning: The httpx module is deprecated; please use httpx2 instead.
    from ._compat import httpx2

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
590 passed, 11 deselected, 2 warnings in 34.74s

```

```sh
env -u OPS_E2E_BASE_URL ./scripts/test.sh
```

Actual full-run summary (routine progress dots and repeated warning prose omitted):

```text
== install (frozen)
== lint
All checks passed!
== hermetic suites
=============================== warnings summary ===============================
590 passed, 11 deselected, 2 warnings in 31.69s
== process e2e (stubs + adapter over TCP)
=============================== warnings summary ===============================
2 passed, 599 deselected, 2 warnings in 2.55s
== package build
Successfully built /tmp/frontdesk-mcp-build/frontdesk_mcp-0.1.0.tar.gz
Successfully built /tmp/frontdesk-mcp-build/frontdesk_mcp-0.1.0-py3-none-any.whl
== production image build (no stubs, no fixtures, no dev dependencies)
== development stubs image build (compose profile stubs)
== external gates not run: no profile loaded (scripts/run-profile.sh mock|live -- ./scripts/test.sh)
== all suites passed
```

```sh
make schema > .context/booking-b2-m1-schema.json
cmp .context/booking-b2-m1-schema.json services/mcp/tests/contracts/mcp-tools.snapshot.json
# exit 0; identical, no output

uvx vulture services/mcp/src/frontdesk_mcp/availability_policy.py services/mcp/src/frontdesk_mcp/booking.py --min-confidence 80
# exit 0; no findings, no dependency added

git diff --check
# exit 0
```

SCHEMA_VERSION remains 2026-10-06.1. No schema regeneration, pack-text change or consumer argument
change. Authlib deprecation warnings are pre-existing. No standalone type-checker run or live-service,
voice/audio or latency measurement was performed; no production performance claim is made.

Safety reviewer: no findings; independently ran policy/booking suites, **158 passed**. Latency reviewer:
no concrete issues, equivalent request bodies and operation keys, no added I/O, retries, deadline changes
or lost concurrency. Neither reviewer changed files.

## Self-review: lines I would question in someone else's diff

- `_contains_time` returns false for unknown bounds: correct because membership and unverifiable
  bounds are separate existing decisions; the unchanged later branches still produce handoff/callback,
  proven for missing start, missing end and both, named and unnamed sessions.
- The `max` uses minute-truncated now, while `_window` still checks session expiry at its existing
  precision: intentional. A still-open session accepts the current minute; whole-scope ended/cancelled
  precedence is unchanged. No overnight behavior is invented.
- `_write_body` obtains the request values then selects only the action's mapped fields: it does not
  forward all model arguments. Validated values override raw dates/name/time; empty optional fields
  remain omitted; trusted context remains separate. Exact-body tests guard against drift.
- `_failure` derives names from all write maps, then intersects with model fields: this follows the
  requested tool-argument vocabulary without creating a second allowlist or changing `_failure` callers.
- Fixture times change: necessary to keep success tests exercising writes under the newly strict rule;
  assertions were retained and separate negative tests prove the refusal.

## Files, commits and release boundary

Docs commit `84103b0`: the two supplied Opus files, unchanged; fast suite green before commit.
Code commit: ten files — availability_policy.py, booking.py, test_availability_policy.py, test_booking.py,
test_server.py, test_gate_assertions.py, dev/bench.py, DECISIONS.md, VOICE-TEAM.md and this hand-back.
The final response supplies its hash (a commit cannot contain its own hash).

B-1's past-appointment lookup behavior, B-3's session-only behavior, M-2's already-cancelled conflict,
G-1's mixed-session choice and overnight limitations remain unchanged by instruction. No deployment,
merge or push; no live writes, new credentials, databases or Azure resource changes. User temp/ is
preserved. Ready for Opus review; the deployed release remains 36336aa until a separately approved release.
