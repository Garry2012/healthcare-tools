# Availability N-1 / N-2 hand-back

Base: `6733ffe`. Scope: two test files, two documentation files and this evidence file; one local commit.

- N-1: corrected DECISIONS and VOICE-TEAM: NO_REGULAR_HOURS was emitted for on-call working hours
  in schema 2026-10-05.1, so describing it as unused was inaccurate.
- N-2: documented and pinned the existing whole-scope refusal precedence. Ended/cancelled doctors
  retain SESSION_ENDED/CANCELLED even with a preferred time; a bookable doctor with an outside time
  still produces TIME_OUTSIDE_SESSION. Two real booking-service cases assert no POST /appointments.
- These tests **passed immediately**, as requested: existing behavior is being recorded, not changed.
  No artificial red run or production-code mutation was performed.

## New tests and first-run output

```sh
services/mcp/.venv/bin/pytest -v services/mcp/tests/test_availability_policy.py services/mcp/tests/test_booking.py -k 'preferred_time_preserves_whole_scope or preferred_time_keeps_whole_scope'
```

```text
============================= test session starts ==============================
platform darwin -- Python 3.13.13, pytest-9.1.1, pluggy-1.6.0 -- /Users/garima/conductor/workspaces/healthcare-tools/des-moines/services/mcp/.venv/bin/python
cachedir: .pytest_cache
rootdir: /Users/garima/conductor/workspaces/healthcare-tools/des-moines/services/mcp
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.15.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=function, asyncio_default_test_loop_scope=function
collecting ... collected 120 items / 115 deselected / 5 selected

services/mcp/tests/test_availability_policy.py::test_preferred_time_preserves_whole_scope_unavailability_reason[IN-20-NOT_AVAILABLE-SESSION_ENDED] PASSED [ 20%]
services/mcp/tests/test_availability_policy.py::test_preferred_time_preserves_whole_scope_unavailability_reason[CANCELLED-10-NOT_AVAILABLE-CANCELLED] PASSED [ 40%]
services/mcp/tests/test_availability_policy.py::test_preferred_time_preserves_whole_scope_unavailability_reason[IN-10-APPOINTMENT_REQUEST-TIME_OUTSIDE_SESSION] PASSED [ 60%]
services/mcp/tests/test_booking.py::test_create_preferred_time_keeps_whole_scope_reason_without_a_write[IN-SESSION_ENDED] PASSED [ 80%]
services/mcp/tests/test_booking.py::test_create_preferred_time_keeps_whole_scope_reason_without_a_write[CANCELLED-CANCELLED] PASSED [100%]

====================== 5 passed, 115 deselected in 0.28s =======================
```

## Full fast suite

```sh
make test-fast
```

```text
cd services/mcp && uv run ruff check . ../../deploy && uv run pytest tests -q -m "not e2e and not external"
All checks passed!
........................................................................ [ 13%]
........................................................................ [ 26%]
........................................................................ [ 39%]
........................................................................ [ 52%]
........................................................................ [ 65%]
........................................................................ [ 78%]
........................................................................ [ 91%]
................................................                         [100%]
=============================== warnings summary ===============================
.venv/lib/python3.13/site-packages/fastmcp/server/auth/providers/jwt.py:10
  /Users/garima/conductor/workspaces/healthcare-tools/des-moines/services/mcp/.venv/lib/python3.13/site-packages/fastmcp/server/auth/providers/jwt.py:10: AuthlibDeprecationWarning: authlib.jose module is deprecated, please use joserfc instead.
  It will be compatible before version 2.0.0.
    from authlib.jose import JsonWebKey, JsonWebToken

.venv/lib/python3.13/site-packages/authlib/integrations/httpx_client/assertion_client.py:5
  /Users/garima/conductor/workspaces/healthcare-tools/des-moines/services/mcp/.venv/lib/python3.13/site-packages/authlib/integrations/httpx_client/assertion_client.py:5: AuthlibDeprecationWarning: The httpx module is deprecated; please use httpx2 instead.
    from ._compat import httpx2

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
552 passed, 11 deselected, 2 warnings in 30.81s
```

## Contract and scope checks

```sh
make schema > .context/n1-n2-schema.json 2> .context/n1-n2-schema-stderr.txt
cmp .context/n1-n2-schema.json services/mcp/tests/contracts/mcp-tools.snapshot.json
# exit 0; identical, no output

git diff --exit-code 6733ffe -- services/mcp/src services/mcp/tests/contracts .claude/agents
# exit 0; no changes

git diff --check
# exit 0; no whitespace errors
```

No production or schema changes; SCHEMA_VERSION remains 2026-10-06.1. G-1 untouched.
Existing Authlib deprecation warnings remain. No full Docker/process suite or external tests rerun:
this pass changes tests/documentation only. No push, merge, deploy, Azure action or live write.
The untracked Opus review and user `temp/` are preserved unchanged.

Commit identity: `git log -1 --format=%h -- docs/handover/mcp-only/implementation/AVAILABILITY-NITS-HAND-BACK.md`.
The final response provides the resulting hash; it cannot be embedded in its own commit.
