#!/usr/bin/env bash
# Everything a reviewer runs on a clean checkout, with no database and no owner source:
#   1. frozen dependency install for services/mcp
#   2. ruff on the adapter, its dev stubs/tests and deploy scripts
#   3. hermetic suites (contract snapshot, settings, context, clients, stubs, tools, server over HTTP)
#   4. process-level e2e: `python -m frontdesk_stubs` + `frontdesk-mcp serve`, release smoke, full journey
#   5. source/wheel build; the production image when a Docker daemon is available
# Real owner services are exercised only when OPS_E2E_BASE_URL etc. are set (tests marked `external`).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/services/mcp"

echo "== install (frozen)"
uv sync --frozen -q

echo "== lint"
uv run ruff check . ../../deploy

echo "== hermetic suites"
uv run pytest tests -q -p no:cacheprovider -m "not e2e and not external"

echo "== process e2e (stubs + adapter over TCP)"
uv run pytest tests -q -p no:cacheprovider -m e2e

echo "== package build"
rm -rf /tmp/frontdesk-mcp-build && uv build --out-dir /tmp/frontdesk-mcp-build >/dev/null && ls /tmp/frontdesk-mcp-build

if docker info >/dev/null 2>&1; then
  echo "== production image build (no stubs, no fixtures, no dev dependencies)"
  docker build -q -t frontdesk-mcp:ci . >/dev/null
  if docker run --rm --entrypoint python frontdesk-mcp:ci -c "import frontdesk_stubs" >/dev/null 2>&1; then
    echo "production image contains the development stubs" >&2; exit 1
  fi
  if docker run --rm --entrypoint python frontdesk-mcp:ci -c "import pytest" >/dev/null 2>&1; then
    echo "production image contains development dependencies" >&2; exit 1
  fi
  echo "== development stubs image build (compose profile stubs)"
  docker build -q -f dev/Dockerfile -t frontdesk-stubs:ci . >/dev/null
else
  echo "== no docker daemon: image build skipped (CI runs it)"
fi

if [[ -n "${OPS_E2E_BASE_URL:-}" ]]; then
  echo "== external gates (${OPS_E2E_MODE:-?} profile: ${DEPLOY_PROFILE:-manual}): owner services / deployed adapter"
  uv run pytest tests -q -p no:cacheprovider -m external
else
  echo "== external gates not run: no profile loaded (scripts/run-profile.sh mock|live -- ./scripts/test.sh)"
fi

echo "== all suites passed"
