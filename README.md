# Front-desk platform — voice-agent tools, REST service, PostgreSQL

Reusable front desk for voice agents: healthcare first (hospitals), hospitality next, with the
same code. One deployment per provider; domain words come from domain packs.

```
LiveKit agent ──MCP──▶ ContextForge ──▶ frontdesk-mcp (FastMCP, 3 tools) ──HTTPS──▶ frontdesk-api (FastAPI) ──▶ PostgreSQL 16
                                        find_availability · manage_booking · search_knowledge
```

- **Architecture and decisions:** `docs/architecture/TARGET.md` (tenancy, domain packs,
  knowledge base, latency budgets).
- **Spec (source of truth):** `docs/frontdesk-api/openapi.yaml`; the healthcare domain guide
  is `IMPLEMENTATION.md` (historical v1 rationale, with a name-mapping table at the top).
- **Handover:** `docs/handover/`:
  - `TESTING.md`, testing locally and what to expect
  - `AZURE.md`, deploying and testing on Azure
  - `LIVEKIT.md`, connecting a LiveKit agent (cascade or speech-to-speech), languages
  - `ONBOARDING.md`, adding a hospital or hotel (and a new language)
  - `README-API.md`, the API for the staff-portal team
  - `ER.md`, the data model
  - `SEED.md`, the demo data
  - `DEPLOY.md`, local Postgres or Supabase, database roles and upgrades
  - `CONTEXTFORGE.md`, gateway registration
  - `OPEN-QUESTIONS.md`, spec defects and the policy questions still open
- All business logic lives in `services/api`. `services/mcp` only adds call-context headers,
  idempotency keys and failure envelopes.

## Five-minute start

Needs Docker, [uv](https://docs.astral.sh/uv/) 0.11+, `jq`. With no Docker daemon, `./scripts/test.sh`
uses a local PostgreSQL 16 (`scripts/local-pg.sh`).

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
  -d '{"utterance":"lady doctor for thyroid","language":"en","category":"thyroid doctor","preferences":{"gender":"FEMALE"}}' | jq .
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

## Upgrading an existing checkout (v1 → v2 names)

The core now uses domain-neutral names (`docs/architecture/TARGET.md`). Migration `0002`
renames tables and data in place. Two local steps apply:

```bash
docker compose -p healthcare-frontdesk -f deploy/docker-compose.yml --env-file .env --profile dev down
# The stack is now frontdesk-$PROVIDER_ID with its own volume; to keep old dev data, migrate it
# before switching. Otherwise start fresh:
make up && make migrate && make seed-reset   # demo ids changed (doc_* → res_*); plain `seed` refuses to mix them
```
