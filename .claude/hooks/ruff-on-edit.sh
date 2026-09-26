#!/usr/bin/env bash
# PostToolUse hook: lint the Python file Claude just edited with the owning service's ruff.
# Exit 2 feeds ruff's findings back to Claude so it fixes them before moving on.
set -uo pipefail
file=$(jq -r '.tool_input.file_path // empty')
[[ "$file" == *.py ]] || exit 0
root="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
case "$file" in
  "$root"/services/api/*) svc="$root/services/api" ;;
  "$root"/services/mcp/*) svc="$root/services/mcp" ;;
  *) exit 0 ;;
esac
out=$(cd "$svc" && uv run --frozen -q ruff check --no-cache "$file" 2>&1) || { echo "$out" >&2; exit 2; }
exit 0
