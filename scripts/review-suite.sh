#!/usr/bin/env bash
# Independent review suite (docs/review/TEST-RESULTS.md), next to the existing suites.
# Starts its own throwaway PostgreSQL 16 container (tmpfs, unique name and port), so it never
# touches dev data or another workspace's test database, runs:
#   1. API: existing unit + contract + integration, then tests/review (unit, db, rest, e2e)
#   2. MCP: existing unit tests, existing e2e against a real API process, then tests/review
# and removes the container. Exit status is non-zero when any suite fails; every suite still runs.
#   scripts/review-suite.sh              # everything
#   scripts/review-suite.sh review       # only the review suites
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ONLY="${1:-all}"
NAME="frontdesk-review-pg-$$"
PORT="${REVIEW_PG_PORT:-55499}"
API_PORT="${REVIEW_API_PORT:-18099}"
AGENT_TOKEN="review-agent-$(openssl rand -hex 8)"
ALL_TOKEN="review-all-$(openssl rand -hex 8)"
FAILED=()
API_PID=""

cleanup() {
  [[ -n "$API_PID" ]] && kill "$API_PID" 2>/dev/null
  docker rm -f "$NAME" >/dev/null 2>&1
}
trap cleanup EXIT

if (exec 3<>"/dev/tcp/127.0.0.1/${PORT}") 2>/dev/null; then echo "port $PORT in use; set REVIEW_PG_PORT" >&2; exit 2; fi
docker run -d --name "$NAME" --tmpfs /var/lib/postgresql/data \
  -e POSTGRES_USER=review_owner -e POSTGRES_PASSWORD=review-owner-pw -e POSTGRES_DB=frontdesk \
  -e APP_DB_USER=review_app -e APP_DB_PASSWORD=review-app-pw \
  -v "$ROOT/deploy/postgres/init:/docker-entrypoint-initdb.d:ro" -p "127.0.0.1:${PORT}:5432" postgres:16-alpine >/dev/null
for _ in $(seq 1 60); do
  docker exec "$NAME" psql -U review_owner -d frontdesk -tAc "SELECT 1 FROM pg_roles WHERE rolname='review_app'" \
    2>/dev/null | grep -q 1 && break
  sleep 1
done
export TEST_DATABASE_URL="postgresql://review_app:review-app-pw@127.0.0.1:${PORT}/frontdesk"
export TEST_DATABASE_OWNER_URL="postgresql://review_owner:review-owner-pw@127.0.0.1:${PORT}/frontdesk"

run() {  # run LABEL DIR ARGS...
  local label="$1" dir="$2"; shift 2
  echo "== $label"
  (cd "$ROOT/$dir" && "$@") || FAILED+=("$label")
}

(cd "$ROOT/services/api" && uv sync --frozen -q && DATABASE_URL="$TEST_DATABASE_OWNER_URL" uv run frontdesk-api migrate)
(cd "$ROOT/services/mcp" && uv sync --frozen -q)

if [[ "$ONLY" == all ]]; then
  run "api: existing unit + contract + integration" services/api \
    uv run pytest tests/unit tests/contract/test_openapi_matches_spec.py tests/integration -q -p no:cacheprovider
fi
run "api: review (unit, db, rest, e2e)" services/api uv run pytest tests/review -q -p no:cacheprovider -rfEx

if [[ "$ONLY" == all ]]; then
  run "mcp: existing unit" services/mcp uv run pytest tests -q -p no:cacheprovider -m "not e2e" --ignore=tests/review
  eval "$("$ROOT/scripts/rollout-env.sh" "$ROOT/rollouts/demo-hospital")"
  (cd "$ROOT/services/api" && DATABASE_URL="$TEST_DATABASE_URL" LOG_LEVEL=WARNING uv run frontdesk-api seed --reset >/dev/null)
  (cd "$ROOT/services/api" && exec env ENV=test DATABASE_URL="$TEST_DATABASE_URL" PORT="$API_PORT" LOG_LEVEL=WARNING \
    AUTH_TOKENS_JSON="{\"${AGENT_TOKEN}\":[\"agent\"],\"${ALL_TOKEN}\":[\"agent\",\"bookings.staff\"]}" \
    uv run frontdesk-api serve) >/dev/null 2>&1 &
  API_PID=$!
  for _ in $(seq 1 50); do curl -sf "http://127.0.0.1:${API_PORT}/ready" >/dev/null && break; sleep 0.2; done
  run "mcp: existing e2e (real API process)" services/mcp env MCP_E2E_API_URL="http://127.0.0.1:${API_PORT}/api/v1" \
    MCP_E2E_API_TOKEN="$AGENT_TOKEN" uv run pytest tests/test_e2e.py -q -p no:cacheprovider
  kill "$API_PID" 2>/dev/null; API_PID=""
fi
run "mcp: review (MCP -> REST -> PostgreSQL)" services/mcp uv run pytest tests/review -q -p no:cacheprovider -rfEx

if ((${#FAILED[@]})); then
  printf '== failed: %s\n' "${FAILED[@]}"
  exit 1
fi
echo "== all suites passed"
