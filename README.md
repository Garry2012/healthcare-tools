# Hospital front-desk scheduling — REST service, MCP adapter, PostgreSQL

```
ContextForge (external) ──MCP──▶ frontdesk-mcp (FastMCP, 2 tools) ──HTTPS──▶ frontdesk-api (FastAPI) ──▶ PostgreSQL 16
```

- **Spec (source of truth):** `docs/frontdesk-api/openapi.yaml` and `IMPLEMENTATION.md`.
- **Handover:** `docs/handover/`:
  - `README-API.md`, the API for the staff-portal team
  - `ER.md`, the data model
  - `SEED.md`, the demo data
  - `DEPLOY.md`, local Postgres or Supabase
  - `CONTEXTFORGE.md`, gateway registration
  - `OPEN-QUESTIONS.md`, spec defects and the policy questions still open
- All business logic lives in `services/api`. `services/mcp` only adds call-context headers,
  idempotency keys and failure envelopes.

## Five-minute start

Needs Docker, [uv](https://docs.astral.sh/uv/) 0.11+, `jq`.

```bash
cp .env.example .env             # then replace every change-me value
make up                          # postgres + migrate + api (:8000) + mcp (:8100), all on 127.0.0.1
make migrate && make seed        # idempotent; synthetic data dated from today
make demo                        # Kannada "Dr Garima tomorrow evening" → book → list → reschedule → cancel
make test                        # unit + integration + contract + MCP, on a throwaway postgres
```

Try the agent facade directly:

```bash
set -a; . ./.env; set +a
AGENT=$(jq -r 'to_entries[] | select(.value | index("agent")) | .key' <<<"$AUTH_TOKENS_JSON" | head -1)
curl -s -X POST localhost:8000/api/v1/agent/availability-search \
  -H "Authorization: Bearer $AGENT" -H 'X-Call-Id: try-1' -H 'X-Caller-Number: +919000000101' \
  -H 'Content-Type: application/json' \
  -d '{"utterance":"lady doctor for thyroid","language":"en","department":"thyroid doctor","preferences":{"gender":"FEMALE"}}' | jq .
```

Register the adapter in ContextForge:

```bash
cd services/mcp && uv run python ../../deploy/contextforge/register.py --dry-run   # then without --dry-run
```

| Make target | What it does |
|---|---|
| `up` / `down` | start / stop the dev profile (data volume kept) |
| `migrate` | Alembic upgrade as the owner role (the API never runs DDL) |
| `seed` / `seed-reset` | load synthetic data / **wipe and reload** it |
| `test` | every suite; see `scripts/test.sh` |
| `demo` | `scripts/demo.sh` against the dev stack |
| `lint`, `build`, `logs` | ruff, image builds, compose logs |

## Layout

```
services/api/   FastAPI service: domain/ (pure engine, resolver, dates, identity), services/, routers/,
                db/, alembic/, tests/{unit,integration,contract}
services/mcp/   FastMCP adapter: tools.py (2 tools), server.py, tests/
deploy/         docker-compose.yml (profiles dev, test), postgres/init, contextforge/register.py
docs/           frontdesk-api/ (spec), handover/, archive/ (research; git-ignored)
```
