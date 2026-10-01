# What the source code actually contains

Audit date: 1 October 2026. Runtime source baseline: `7e20b4459d0a58422bf3b5ba40a670be94b758f5`. Findings below come from reading executable source, dependency declarations, tests and deployment scripts, not from accepting the older architecture documents. Publishing this handover changes documentation only.

**The entire old backend is still present.** This is our previous backend implementation, covering responsibilities now assigned to Manoj and Shobhit; it is not a copy of Manoj's new implementation. None of the planned external integrations or backend removal has been implemented. There is no meaningful partial-removal percentage to report: the old application is still wired end to end.

```text
CURRENT CODE

MCP server: 3 tools
  find_availability / manage_booking / search_knowledge
                     |
                     | HTTP requests to our /api/v1/agent/... routes
                     v
Our REST backend (services/api)
  Doctors, departments, schedules and live board
  Name/date matching, booking rules and storage
  Knowledge search, red flags, call-summary storage, staff operations
                     |
                     v
Our PostgreSQL database: 15 tables

Local startup, integration tests and Azure deployment include this whole stack.
Manoj's API and Shobhit's service are not wired into these tools.
```

## The three current tools all depend on our API

The adapter has no direct database connection or backend-module import. It has an HTTP dependency on the backend, which in turn uses the database. The MCP package can therefore install/build by itself, but cannot deliver these operations without a compatible backend.

| Current tool | Actual downstream request(s) | Source |
|---|---|---|
| `find_availability` | `POST /agent/availability-search` | [tools.py](../../../services/mcp/src/frontdesk_mcp/tools.py#L210) |
| `manage_booking` | `GET /agent/bookings`, `POST /agent/bookings`, `POST /agent/bookings/{bookingId}/cancel`, `POST /agent/bookings/{bookingId}/reschedule` | [tools.py](../../../services/mcp/src/frontdesk_mcp/tools.py#L240) |
| `search_knowledge` | `POST /agent/knowledge-search` | [tools.py](../../../services/mcp/src/frontdesk_mcp/tools.py#L309) |

[config.py](../../../services/mcp/src/frontdesk_mcp/config.py) configures one API URL (default `http://127.0.0.1:8000/api/v1`) and a static bearer token, with read/write timeouts of 2/5 seconds. [server.py](../../../services/mcp/src/frontdesk_mcp/server.py) creates that client and calls the old API's `/ready` for readiness. These settings and checks are not the planned independent Manoj/Shobhit clients or one-second end-to-end deadline.

The actual registration and smoke lists in [register.py](../../../deploy/contextforge/register.py) and [smoke.py](../../../deploy/azure/smoke.py) still contain exactly three old tool names. `get_doctor_availability` and `record_call_summary` have not been registered or implemented. The presence of a call-summary route in the old backend does not provide the required MCP tool.

## What remains in the backend

[app.py](../../../services/api/src/frontdesk_api/app.py) constructs a SQLAlchemy engine and session factory, checks migration state, initializes directory/knowledge caches, and registers the operational, agent, knowledge, call, notification and health routers. [db/session.py](../../../services/api/src/frontdesk_api/db/session.py) creates the database engine; [pyproject.toml](../../../services/api/pyproject.toml) retains FastAPI, SQLAlchemy, asyncpg, Alembic and interpretation dependencies.

| Responsibility still implemented here | Direct source evidence |
|---|---|
| Scheduling and availability calculation | [domain/availability.py](../../../services/api/src/frontdesk_api/domain/availability.py), [services/search.py](../../../services/api/src/frontdesk_api/services/search.py) |
| Doctor/department resolution, synonyms and red-flag matching | [domain/resolver.py](../../../services/api/src/frontdesk_api/domain/resolver.py) |
| Spoken-date parsing and language data | [domain/dates.py](../../../services/api/src/frontdesk_api/domain/dates.py), [locales/](../../../services/api/src/frontdesk_api/locales/) |
| Booking creation, access checks and changes | [routers/agent.py](../../../services/api/src/frontdesk_api/routers/agent.py), [services/bookings.py](../../../services/api/src/frontdesk_api/services/bookings.py) |
| Local knowledge engine and database-backed approved answers | [services/knowledge.py](../../../services/api/src/frontdesk_api/services/knowledge.py), [domain/knowledge.py](../../../services/api/src/frontdesk_api/domain/knowledge.py) |
| Calls and notifications | [routers/calls.py](../../../services/api/src/frontdesk_api/routers/calls.py), [routers/notifications.py](../../../services/api/src/frontdesk_api/routers/notifications.py) |
| Database models, migrations and demo/rollout loading | [db/tables.py](../../../services/api/src/frontdesk_api/db/tables.py), [alembic/versions/](../../../services/api/alembic/versions/), [cli.py](../../../services/api/src/frontdesk_api/cli.py) |

The 15 declared tables are `categories`, `resources`, `resource_categories`, `lexicon_entries`, `schedule_templates`, `template_sessions`, `schedule_exceptions`, `board_entries`, `bookings`, `booking_history`, `notifications`, `idempotency_keys`, `call_summaries`, `knowledge_entries`, and `cache_versions`. Four Alembic revisions remain. This is source/schema evidence; no live database contents or deployed cloud resources were inspected or modified for this audit.

The legacy repository does contain interpretation code. That fact does not change the agreed new-service plan: advanced multilingual date/name/synonym behavior is deferred and must not be copied into MCP as a hidden replacement backend.

## Build, tests and deployment still depend on it

| Surface inspected | Dependency and consequence of immediate removal |
|---|---|
| [MCP pyproject](../../../services/mcp/pyproject.toml), [lockfile](../../../services/mcp/uv.lock), [Dockerfile](../../../services/mcp/Dockerfile) | Standalone package/image, without SQL libraries or an API build context. This part can build independently; a build alone does not prove tool functionality. |
| [Compose](../../../deploy/docker-compose.yml) | Starts PostgreSQL, migration job, API and MCP. MCP points at `http://api:8000/api/v1` and waits for API health. Removing the API breaks default startup. |
| [Makefile](../../../Makefile) | Default startup/build/logs include the API; migration, rollout-apply and seed targets invoke its CLI. `test-fast` also installs/checks API code. |
| [scripts/test.sh](../../../scripts/test.sh), [CI workflow](../../../.github/workflows/ci.yml) | CI runs the full old stack: test PostgreSQL, migration, API tests, rollout validation, seeded API, MCP end-to-end tests and API contract tests. Removing the backend breaks CI. |
| [MCP unit tests](../../../services/mcp/tests/test_tools_unit.py), [e2e tests](../../../services/mcp/tests/test_e2e.py) | Unit tests mock old `/agent` operations; tool discovery compares against the legacy spec. The spec test skips if that file is absent, so simply deleting it could hide lost coverage. E2E expects a running old API. |
| [Independent integration review tests](../../../services/mcp/tests/review/test_mcp_rest_integration.py) | Depend on the API virtualenv, test database, seeded state and spawned API process. Old slot/BOOKED behavior is not Manoj's NOTED journey. |
| [Azure deployment](../../../deploy/azure/deploy.sh) | Builds both images; provisions PostgreSQL and roles; runs migration/apply/seed jobs; deploys API and points MCP at it. Also uses the API environment for deployment preparation. Cannot become MCP-only by changing a single URL. |
| [demo.sh](../../../scripts/demo.sh), [review-suite.sh](../../../scripts/review-suite.sh), [local-pg.sh](../../../scripts/local-pg.sh) | Old API requests, slot extraction, seeding and database startup remain in active scripts. |
| [Agent session hook](../../../.claude/hooks/session-start.sh) | Remote-session setup installs API dependencies and starts/migrates local PostgreSQL. Future agent setup must stop recreating the retired backend. |

The full suite already fails on the current `main` baseline: [run 36571571806](https://github.com/Garry2012/healthcare-tools/actions/runs/36571571806) reports `test_mcp_offers_every_bookable_position_of_a_session` failing because four of seven positions were omitted. This is a pre-existing functional defect, not evidence that the handover changed runtime behavior. No tests were weakened or skipped to conceal it.

## What the planned result looks like

```text
TARGET AFTER IMPLEMENTATION

Our MCP server: 4 tools
       |                      |
       v                      v
Manoj's REST service     Shobhit's knowledge service
Doctors, live board,     Hospital answers, symptom routing,
appointments, summaries red-flag decisions
       |                      |
Their storage           Their storage

No operational REST backend or application database owned by this repository.
```

The next implementer must replace the HTTP contract, test fixtures, configuration, prompts, gateway registration, build/deployment and automation dependencies before retiring all of `services/api` and PostgreSQL setup. The [plan](PLAN.md) lists the full removal inventory and acceptance gates. Source removal is separate from deleting live infrastructure or data; neither has been authorized as part of publishing this handover.
