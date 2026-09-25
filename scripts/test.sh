#!/usr/bin/env bash
# Runs every suite. Integration, contract and MCP end-to-end tests use the compose `test`
# profile's throwaway PostgreSQL (tmpfs) and a locally started API; nothing touches dev data.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
set -a; . ./.env; set +a
COMPOSE=(docker compose -f deploy/docker-compose.yml --env-file .env)
API_PORT="${TEST_API_PORT:-18000}"
AGENT_TOKEN="test-agent-$(openssl rand -hex 12)"
ALL_TOKEN="test-all-$(openssl rand -hex 12)"
TEST_DB="127.0.0.1:${TEST_POSTGRES_HOST_PORT}/${POSTGRES_DB}"
export TEST_DATABASE_URL="postgresql://${APP_DB_USER}:${APP_DB_PASSWORD}@${TEST_DB}"
export TEST_DATABASE_OWNER_URL="postgresql://${POSTGRES_OWNER_USER}:${POSTGRES_OWNER_PASSWORD}@${TEST_DB}"
API_PID=""

cleanup() {
  [[ -n "$API_PID" ]] && kill "$API_PID" 2>/dev/null || true
  "${COMPOSE[@]}" --profile test rm -sf postgres-test >/dev/null 2>&1 || true
}
trap cleanup EXIT

if lsof -i ":${API_PORT}" >/dev/null 2>&1; then echo "port ${API_PORT} is in use; set TEST_API_PORT" >&2; exit 1; fi
"${COMPOSE[@]}" --profile test up -d --wait postgres-test

echo "== api: lint, unit, contract (hermetic), integration (postgres)"
(cd services/api && uv sync --frozen -q && uv run ruff check src tests \
  && uv run pytest tests/unit tests/contract/test_openapi_matches_spec.py tests/integration -q -p no:cacheprovider)

echo "== starting api on :${API_PORT} with a freshly seeded database"
(cd services/api && DATABASE_URL="$TEST_DATABASE_URL" LOG_LEVEL=WARNING uv run healthcare-api seed --reset >/dev/null)
(cd services/api && exec env ENV=test DATABASE_URL="$TEST_DATABASE_URL" PORT="$API_PORT" LOG_LEVEL=WARNING \
  AUTH_TOKENS_JSON="{\"${AGENT_TOKEN}\":[\"agent\"],\"${ALL_TOKEN}\":[\"agent\",\"appointments.staff\",\"schedule.write\",\"board.write\",\"directory.write\",\"calls.write\",\"calls.read\"]}" \
  uv run healthcare-api serve) > /tmp/healthcare-api-test.log 2>&1 &
API_PID=$!
for _ in $(seq 1 50); do curl -sf "http://127.0.0.1:${API_PORT}/ready" >/dev/null && break; sleep 0.2; done
curl -sf "http://127.0.0.1:${API_PORT}/ready" >/dev/null || { cat /tmp/healthcare-api-test.log; exit 1; }

echo "== mcp: lint, unit, end-to-end through the adapter"
(cd services/mcp && uv sync --frozen -q && uv run ruff check src tests \
  && MCP_E2E_API_URL="http://127.0.0.1:${API_PORT}/api/v1" MCP_E2E_API_TOKEN="$AGENT_TOKEN" \
     uv run pytest tests -q -p no:cacheprovider)

echo "== contract: schemathesis against the running api"
(cd services/api && CONTRACT_API_URL="http://127.0.0.1:${API_PORT}/api/v1" CONTRACT_API_TOKEN="$ALL_TOKEN" \
  uv run pytest tests/contract/test_schemathesis.py -q -p no:cacheprovider)

echo "== all suites passed"
