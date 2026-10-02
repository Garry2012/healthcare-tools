#!/usr/bin/env bash
# Print `export` lines for one environment profile (deploy/environments/<profile>.env), for `eval`:
#   eval "$(scripts/env.sh mock)"      # public contract mock: integration tests, benchmarks
#   eval "$(scripts/env.sh live)"      # Manoj's live API
# Adds the derived variables the external gates and the benchmark read, so the endpoint is written once.
# Never prints or reads secret values; scripts/run-profile.sh loads them from the selected Key Vault.
# DEPLOY_PROFILE_DIR overrides the profile directory (tests).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
profile="${1:?usage: env.sh <mock|live>}"
dir="${DEPLOY_PROFILE_DIR:-$ROOT/deploy/environments}"
file="$dir/$profile.env"
[[ -f "$file" ]] || { echo "unknown profile '$profile' ($dir)" >&2; exit 2; }
ops="" knowledge="" lines=()
while IFS= read -r line || [[ -n "$line" ]]; do
  [[ -z "${line// }" || "$line" == \#* ]] && continue
  key="${line%%=*}" value="${line#*=}"
  [[ "$key" == OPS_BASE_URL ]] && ops="$value"
  [[ "$key" == KNOWLEDGE_BASE_URL ]] && knowledge="$value"
  lines+=("$(printf 'export %s=%q' "$key" "$value")")
done < "$file"
if [[ -z "$ops" ]]; then
  echo "profile '$profile' has no OPS_BASE_URL yet: awaiting the owner's live base URL; nothing exported" >&2
  exit 3
fi
printf '%s\n' "${lines[@]}"
printf 'export OPS_E2E_BASE_URL=%q\n' "$ops"
printf 'export BENCH_OPS_BASE_URL=%q\n' "$ops"
# Clear all three knowledge URLs when the selected profile has no host. Never retain a previous profile's host.
printf 'export KNOWLEDGE_BASE_URL=%q\n' "$knowledge"
printf 'export KNOWLEDGE_E2E_BASE_URL=%q\n' "$knowledge"
printf 'export BENCH_KNOWLEDGE_BASE_URL=%q\n' "$knowledge"
printf 'export DEPLOY_PROFILE=%q\n' "$profile"
