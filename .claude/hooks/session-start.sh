#!/bin/bash
# SessionStart (Claude Code on the web): dependencies for both services and a throwaway
# PostgreSQL, so lint, unit, integration and MCP tests run without a Docker daemon.
set -euo pipefail
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"

(cd "$ROOT/services/api" && uv sync --frozen -q)
(cd "$ROOT/services/mcp" && uv sync --frozen -q)

# Migrated, empty schema; tests seed what they need. Idempotent across resumes.
exports="$("$ROOT/scripts/local-pg.sh" start)"
eval "$exports"
(cd "$ROOT/services/api" && DATABASE_URL="$TEST_DATABASE_OWNER_URL" uv run -q frontdesk-api migrate)
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "$exports" >> "$CLAUDE_ENV_FILE"
fi
