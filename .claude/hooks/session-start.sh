#!/bin/bash
# SessionStart (Claude Code on the web): the adapter's dependencies, nothing else. No database, no backend.
set -euo pipefail
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
(cd "$ROOT/services/mcp" && uv sync --frozen -q)
