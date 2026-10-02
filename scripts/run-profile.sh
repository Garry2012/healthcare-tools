#!/usr/bin/env bash
# Run a command with one selected profile and its credentials. Never print secret values or export commands.
#   scripts/run-profile.sh live -- ./scripts/test.sh
#   scripts/run-profile.sh mock -- uv run --project services/mcp python services/mcp/dev/bench.py
set +x
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROFILE="${1:?usage: run-profile.sh <live|mock> -- command [args...]}"; shift
[[ "${1:-}" == -- ]] && shift
[[ $# -gt 0 ]] || { echo "a command is required" >&2; exit 2; }
PROFILE_EXPORTS="$("$ROOT/scripts/env.sh" "$PROFILE")" || exit 2
eval "$PROFILE_EXPORTS"

read_secret() {
  local value
  # Capture output; Azure errors are suppressed here so a failed command cannot echo credential material.
  value="$(az keyvault secret show --subscription "${AZ_SUBSCRIPTION_ID:?}" \
    --vault-name "${AZ_KEYVAULT:?}" --name "$1" --query value -o tsv 2>/dev/null)" || {
    echo "cannot read required Key Vault secret: $1" >&2; return 1;
  }
  [[ -n "$value" ]] || { echo "required Key Vault secret is empty: $1" >&2; return 1; }
  printf '%s' "$value"
}

case "${OPS_E2E_MODE:-}" in
  live)
    OPS_CLIENT_ID="$(read_secret "${OPS_CLIENT_ID_SECRET_NAME:-ops-client-id}")"
    OPS_CLIENT_SECRET="$(read_secret "${OPS_CLIENT_SECRET_SECRET_NAME:-ops-client-secret}")" ;;
  mock)
    # The public Prism server accepts example credentials. Never send the real client secret to it.
    OPS_CLIENT_ID=contract-example
    OPS_CLIENT_SECRET=contract-example ;;
  *) echo "profile must specify OPS_E2E_MODE=live or mock" >&2; exit 2 ;;
esac
export OPS_CLIENT_ID OPS_CLIENT_SECRET
export OPS_E2E_CLIENT_ID="$OPS_CLIENT_ID" BENCH_OPS_CLIENT_ID="$OPS_CLIENT_ID"
export OPS_E2E_CLIENT_SECRET="$OPS_CLIENT_SECRET" BENCH_OPS_CLIENT_SECRET="$OPS_CLIENT_SECRET"
if [[ -n "${KNOWLEDGE_BASE_URL:-}" ]]; then
  KNOWLEDGE_BEARER_TOKEN="$(read_secret "${KNOWLEDGE_BEARER_TOKEN_SECRET_NAME:-knowledge-token}")"
  export KNOWLEDGE_BEARER_TOKEN
  export KNOWLEDGE_E2E_BEARER_TOKEN="$KNOWLEDGE_BEARER_TOKEN" BENCH_KNOWLEDGE_BEARER_TOKEN="$KNOWLEDGE_BEARER_TOKEN"
else
  unset KNOWLEDGE_BEARER_TOKEN KNOWLEDGE_E2E_BEARER_TOKEN BENCH_KNOWLEDGE_BEARER_TOKEN
fi
exec "$@"
