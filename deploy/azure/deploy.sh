#!/usr/bin/env bash
# Deploy the MCP adapter for one rollout to Azure Container Apps, as one re-runnable command.
#
#   deploy/azure/deploy.sh <rollout directory> --profile <live|mock> [--dry-run]
#
# The rollout directory supplies rollout.env (tenant settings, non-secret). The profile
# (deploy/environments/<profile>.env, loaded through scripts/env.sh) supplies the owner-service base URL,
# the Key Vault secret names and the exact Azure target: subscription and resource group. The script refuses
# to run without a profile, when the signed-in subscription differs from the profile's, or when the profile
# names no resource group: it never invents one. The owner services are external and MUST be their real hosts
# over https; production configuration refuses stubs and mocks (so `--profile mock` can only dry-run). Nothing here provisions a
# database, runs migrations or builds any backend image: Manoj and Shobhit deploy their own services.
#
# Re-running is safe: resources that exist are kept, generated secrets are created once and then read
# from Key Vault, the container gets the new image and exactly the rollout's current settings.
#   --dry-run    print every az call instead of running it (no Azure login needed)
#
# Secrets in Key Vault (names): mcp-token (gateway bearer),
# ops-client-id / ops-client-secret (Manoj machine client, supplied by the owner: set OPS_CLIENT_ID /
# OPS_CLIENT_SECRET in the environment on first run), knowledge-token (Shobhit, same).
set -euo pipefail

usage() { sed -n '2,22p' "$0" >&2; exit 2; }
[[ $# -ge 1 && -d "$1" ]] || usage
ROLLOUT="$(cd "$1" && pwd)"; shift
DRY="" PROFILE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY=1; shift ;;
    --profile) [[ $# -ge 2 ]] || { echo "--profile needs a value: live or mock" >&2; exit 2; }; PROFILE="$2"; shift 2 ;;
    *) usage ;;
  esac
done
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
[[ -n "$PROFILE" ]] || { echo "--profile <live|mock> is required (deploy/environments/)" >&2; exit 2; }
# The profile is the only source of the target: forget anything inherited from the shell first, and stop if the
# profile cannot be loaded (eval alone would ignore env.sh's exit code and carry on with stale exports).
unset OPS_BASE_URL OPS_E2E_MODE AZ_SUBSCRIPTION_ID AZ_RESOURCE_GROUP AZ_CONTAINERAPPS_ENV AZ_LOG_WORKSPACE AZ_ACR \
  AZ_KEYVAULT AZ_IDENTITY AZ_MCP_APP
PROFILE_EXPORTS="$("$ROOT/scripts/env.sh" "$PROFILE")" || { echo "profile $PROFILE not usable; stopping" >&2; exit 2; }
eval "$PROFILE_EXPORTS"

show() { printf '+ %s\n' "$*" | sed -E 's/(--admin-password |--value )[^ ]*/\1***/g' >&2; }
run() { if [[ -n "$DRY" ]]; then show "$@"; else "$@"; fi; }
out() { if [[ -n "$DRY" ]]; then show "$@"; echo "<$2-$3>"; else "$@"; fi; }
# A dry run shows a first deployment, or an upgrade of an existing app with DEPLOY_ASSUME_EXISTING=1 (only the
# container-app existence check honours the flag; vault/identity lookups still show a first deployment).
exists() {
  if [[ -n "$DRY" ]]; then
    [[ -n "${DEPLOY_ASSUME_EXISTING:-}" && "$*" == *"containerapp show"* ]]
    return
  fi
  "$@" >/dev/null 2>&1
}
step() { printf '\n== %s\n' "$*" >&2; }

required="uv git openssl"
[[ -n "$DRY" ]] || required="$required az"
for command in $required; do
  command -v "$command" >/dev/null 2>&1 || { echo "missing prerequisite: $command" >&2; exit 1; }
done

# --- 1. rollout settings and the owner service endpoints -----------------------------------------
read_env() { grep -Ev '^[[:space:]]*(#|$)' "$1" || true; }
ROLLOUT_ENV=()
while IFS= read -r line || [[ -n "$line" ]]; do ROLLOUT_ENV+=("$line"); done < <(read_env "$ROLLOUT/rollout.env")
P="$(printf '%s\n' "${ROLLOUT_ENV[@]}" | sed -n 's/^PROVIDER_ID=//p')"
[[ -n "$P" ]] || { echo "rollout.env must set PROVIDER_ID" >&2; exit 2; }
: "${OPS_BASE_URL:?the profile must set OPS_BASE_URL (the operational API base, https://host/api/v1)}"
KNOWLEDGE_BASE_URL="${KNOWLEDGE_BASE_URL:-}"
: "${AZ_SUBSCRIPTION_ID:?the profile must name the subscription}"
: "${AZ_RESOURCE_GROUP:?the profile must name the resource group; this script never defaults to rg-frontdesk-<provider>}"
for url in "$OPS_BASE_URL" "$KNOWLEDGE_BASE_URL"; do
  [[ -z "$url" ]] && continue
  [[ "$url" == https://* ]] || { echo "owner service URLs must be https: $url" >&2; exit 2; }
  case "$url" in *contract-mock*|*localhost*|*127.0.0.1*|*stub*|*prism*|*mock*)
    echo "refusing to deploy production against a stub/mock endpoint: $url" >&2; exit 2 ;;
  esac
done

step "validate the adapter configuration offline (settings, pack, tool schema)"
(cd "$ROOT/services/mcp" && env -i PATH="$PATH" HOME="$HOME" ENV=production "${ROLLOUT_ENV[@]}" \
  OPS_BASE_URL="$OPS_BASE_URL" OPS_CLIENT_ID=validate OPS_CLIENT_SECRET=validate \
  KNOWLEDGE_BASE_URL="$KNOWLEDGE_BASE_URL" KNOWLEDGE_BEARER_TOKEN="${KNOWLEDGE_BASE_URL:+validate}" \
  MCP_BEARER_TOKEN=validate-a \
  uv run -q frontdesk-mcp schema >/dev/null)

# --- the Azure target comes from the profile; the signed-in subscription must match -------------
SUB="$(out az account show --query id -o tsv)"
[[ -n "$DRY" && -n "${DEPLOY_DRY_SUBSCRIPTION:-}" ]] && SUB="$DEPLOY_DRY_SUBSCRIPTION"  # tests simulate the login
if [[ ( -z "$DRY" || -n "${DEPLOY_DRY_SUBSCRIPTION:-}" ) && "$SUB" != "$AZ_SUBSCRIPTION_ID" ]]; then
  echo "signed-in subscription $SUB is not the profile subscription $AZ_SUBSCRIPTION_ID; run az account set first" >&2
  exit 2
fi
LOC="${AZ_LOCATION:-centralindia}"
RG="$AZ_RESOURCE_GROUP"
ENV_NAME="${AZ_CONTAINERAPPS_ENV:?profile must name the Container Apps environment}"
LAW="${AZ_LOG_WORKSPACE:?profile must name the Log Analytics workspace}"
ACR="${AZ_ACR:?profile must name the registry}"
KV="${AZ_KEYVAULT:?profile must name the Key Vault}"
TAG="${TAG:-$(git -C "$ROOT" rev-parse --short HEAD)}"
ID_NAME="${AZ_IDENTITY:?profile must name the managed identity}"
APP="${AZ_MCP_APP:-mcp-$P}"

# --- 2. shared infrastructure (kept if present) and the image ------------------------------------
step "shared infrastructure named by the profile must already exist (this script creates none of it)"
require() {  # require DESCRIPTION az-show-command...: the shared resource must exist; dry runs only list the check
  local what="$1"; shift
  if [[ -n "$DRY" ]]; then show "$@"; return 0; fi
  "$@" >/dev/null 2>&1 || { echo "$what not found; shared infrastructure is not created by this script" >&2; exit 2; }
}
require "resource group $RG" az group show -n "$RG"
require "log workspace $LAW" az monitor log-analytics workspace show -g "$RG" -n "$LAW"
require "container apps environment $ENV_NAME" az containerapp env show -g "$RG" -n "$ENV_NAME"
require "registry $ACR" az acr show -n "$ACR"

step "image frontdesk-mcp:$TAG (services/mcp only: no stubs, no fixtures)"
run az acr build -r "$ACR" -t "frontdesk-mcp:$TAG" "$ROOT/services/mcp" -o none
MCP_IMAGE="$ACR.azurecr.io/frontdesk-mcp:$TAG"

# --- 3. Key Vault secrets and the identity that reads them ---------------------------------------
step "secrets: $KV (shared vault named by the profile)"
require "key vault $KV" az keyvault show -n "$KV"
KV_ID="$(out az keyvault show -n "$KV" --query id -o tsv)"
ME="$(out az ad signed-in-user show --query id -o tsv)"
run az role assignment create --assignee "$ME" --role "Key Vault Secrets Officer" --scope "$KV_ID" -o none
secret() {  # secret NAME GENERATOR...: the stored value, or a new one stored now; fails if it can't store
  local value
  if exists az keyvault secret show --vault-name "$KV" -n "$1"; then
    value="$(az keyvault secret show --vault-name "$KV" -n "$1" --query value -o tsv)" || return 1
  else
    value="$("${@:2}")" || return 1
    local file attempt stored=""
    file="$(umask 077 && mktemp)"
    printf '%s' "$value" > "$file"
    for attempt in 1 2 3 4 5 6; do
      if run az keyvault secret set --vault-name "$KV" -n "$1" --file "$file" --encoding utf-8 -o none; then
        stored=1; break
      fi
      sleep "${KV_RETRY_SECONDS:-20}"
    done
    rm -f "$file"
    [[ -n "$stored" ]] || { echo "could not store secret $1 in $KV; stopping" >&2; return 1; }
  fi
  printf '%s' "$value"
}
token() { openssl rand -hex 24; }
supplied() {  # supplied VAR: the owner-provided credential from the environment (first run only)
  if [[ -z "${!1:-}" ]]; then
    [[ -n "$DRY" ]] && { echo "(dry run: $1 would be required on the first real run)" >&2; printf '<%s>' "$1"; return 0; }
    echo "$1 is not in Key Vault yet; export it for this first run" >&2; return 1
  fi
  printf '%s' "${!1}"
}
MCP_TOKEN="$(secret mcp-token token)"
OPS_ID_SECRET="${OPS_CLIENT_ID_SECRET_NAME:-ops-client-id}"
OPS_PASSWORD_SECRET="${OPS_CLIENT_SECRET_SECRET_NAME:-ops-client-secret}"
KNOWLEDGE_SECRET="${KNOWLEDGE_BEARER_TOKEN_SECRET_NAME:-knowledge-token}"
secret "$OPS_ID_SECRET" supplied OPS_CLIENT_ID >/dev/null
secret "$OPS_PASSWORD_SECRET" supplied OPS_CLIENT_SECRET >/dev/null
if [[ -n "$KNOWLEDGE_BASE_URL" ]]; then
  secret "$KNOWLEDGE_SECRET" supplied KNOWLEDGE_BEARER_TOKEN >/dev/null
fi

require "managed identity $ID_NAME" az identity show -g "$RG" -n "$ID_NAME"
ID="$(out az identity show -g "$RG" -n "$ID_NAME" --query id -o tsv)"
PRINCIPAL="$(out az identity show -g "$RG" -n "$ID_NAME" --query principalId -o tsv)"
run az role assignment create --assignee-object-id "$PRINCIPAL" --assignee-principal-type ServicePrincipal \
  --role "Key Vault Secrets User" --scope "$KV_ID" -o none
run az role assignment create --assignee-object-id "$PRINCIPAL" --assignee-principal-type ServicePrincipal \
  --role AcrPull --scope "$(out az acr show -n "$ACR" --query id -o tsv)" -o none
kv() { echo "$1=keyvaultref:https://$KV.vault.azure.net/secrets/$1,identityref:$ID"; }

# --- 4. the adapter (reached by the gateway) --------------------------
step "container: $APP"
SECRETS="$(kv mcp-token) $(kv "$OPS_ID_SECRET") $(kv "$OPS_PASSWORD_SECRET")"
ENV_VARS=(ENV=production HOST=0.0.0.0 PORT=8100
  "OPS_BASE_URL=$OPS_BASE_URL" "OPS_CLIENT_ID=secretref:$OPS_ID_SECRET" "OPS_CLIENT_SECRET=secretref:$OPS_PASSWORD_SECRET"
  "KNOWLEDGE_BASE_URL=$KNOWLEDGE_BASE_URL"
  MCP_BEARER_TOKEN=secretref:mcp-token
  "${ROLLOUT_ENV[@]}")
if [[ -n "$KNOWLEDGE_BASE_URL" ]]; then
  SECRETS="$SECRETS $(kv "$KNOWLEDGE_SECRET")"
  ENV_VARS+=("KNOWLEDGE_BEARER_TOKEN=secretref:$KNOWLEDGE_SECRET")
else
  ENV_VARS+=("KNOWLEDGE_BEARER_TOKEN=")
fi
if exists az containerapp show -g "$RG" -n "$APP"; then
  # Upgrade path (AR-05): an app deployed by the legacy script carries only agent-token/mcp-token. Attach the
  # identity and registry access, then every Key Vault reference the new environment names, BEFORE switching the
  # revision's environment; otherwise the new revision cannot resolve its secretrefs and never becomes ready.
  run az containerapp identity assign -g "$RG" -n "$APP" --user-assigned "$ID" -o none
  run az containerapp registry set -g "$RG" -n "$APP" --server "$ACR.azurecr.io" --identity "$ID" -o none
  # shellcheck disable=SC2086  # the secrets list is space-separated on purpose
  run az containerapp secret set -g "$RG" -n "$APP" --secrets $SECRETS -o none
  run az containerapp update -g "$RG" -n "$APP" --image "$MCP_IMAGE" --replace-env-vars "${ENV_VARS[@]}" -o none
  if [[ -z "$KNOWLEDGE_BASE_URL" ]]; then
    # Inspect names only; an already-absent reference is a no-op. Query/remove failures still stop release.
    knowledge_ref="$(out az containerapp show -g "$RG" -n "$APP" \
      --query "properties.configuration.secrets[?name=='$KNOWLEDGE_SECRET'].name" -o tsv)"
    if [[ -n "$knowledge_ref" ]]; then
      run az containerapp secret remove -g "$RG" -n "$APP" --secret-names "$KNOWLEDGE_SECRET" -o none
    fi
  fi
  # Legacy secrets (agent-token for the retired API) stay attached until the retirement step removes them.
else
  # shellcheck disable=SC2086  # the secrets list is space-separated on purpose
  run az containerapp create -g "$RG" -n "$APP" --environment "$ENV_NAME" --image "$MCP_IMAGE" \
    --registry-server "$ACR.azurecr.io" --registry-identity "$ID" --user-assigned "$ID" \
    --ingress external --target-port 8100 --min-replicas 1 --max-replicas 3 --cpu 0.25 --memory 0.5Gi \
    --secrets $SECRETS --env-vars "${ENV_VARS[@]}" -o none
fi
# Container Apps ignores the Dockerfile HEALTHCHECK: readiness on /ready (local), liveness on /health.
SPEC="$(mktemp)"
run az containerapp show -g "$RG" -n "$APP" -o yaml > "$SPEC"
if [[ -z "$DRY" ]]; then
  (cd "$ROOT/services/mcp" && uv run -q --with pyyaml==6.0.3 python - "$SPEC" <<'PY'
import sys, yaml
path = sys.argv[1]
spec = yaml.safe_load(open(path))
spec["properties"]["template"]["containers"][0]["probes"] = [
    {"type": "Readiness", "httpGet": {"path": "/ready", "port": 8100}, "periodSeconds": 5},
    {"type": "Liveness", "httpGet": {"path": "/health", "port": 8100}, "periodSeconds": 10},
]
yaml.safe_dump(spec, open(path, "w"))
PY
  )
fi
run az containerapp update -g "$RG" -n "$APP" --yaml "$SPEC" -o none
rm -f "$SPEC"

wait_ready() {
  local revision health ready
  revision="$(out az containerapp show -g "$RG" -n "$APP" --query properties.latestRevisionName -o tsv)"
  for _ in $(seq 1 60); do
    health="$(out az containerapp revision show -g "$RG" -n "$APP" --revision "$revision" --query properties.healthState -o tsv)"
    ready="$(out az containerapp show -g "$RG" -n "$APP" --query properties.latestReadyRevisionName -o tsv)"
    [[ -n "$DRY" ]] && return 0
    [[ -n "$revision" && "$health" == Healthy && "$ready" == "$revision" ]] && return 0
    sleep "${READY_RETRY_SECONDS:-5}"
  done
  echo "$APP revision $revision did not become ready; inspect its Container Apps logs" >&2
  return 1
}
step "verify: latest revision ready, dependencies, authentication, four tools"
wait_ready
MCP_HOST="$(out az containerapp show -g "$RG" -n "$APP" --query properties.configuration.ingress.fqdn -o tsv)"
LANG1="$(printf '%s\n' "${ROLLOUT_ENV[@]}" | sed -n 's/^TENANT_SUPPORTED_LANGUAGES=//p' | cut -d, -f1)"
SMOKE_EXPECT_KNOWLEDGE=absent
[[ -z "$KNOWLEDGE_BASE_URL" ]] || SMOKE_EXPECT_KNOWLEDGE=required
if [[ -n "$DRY" ]]; then
  show env "SMOKE_EXPECT_KNOWLEDGE=$SMOKE_EXPECT_KNOWLEDGE" uv run --project "$ROOT/services/mcp" python "$ROOT/deploy/azure/smoke.py"
else
  MCP_URL="https://$MCP_HOST/mcp/" MCP_BEARER_TOKEN="$MCP_TOKEN" \
    SMOKE_LANGUAGE="$LANG1" SMOKE_EXPECT_KNOWLEDGE="$SMOKE_EXPECT_KNOWLEDGE" uv run --project "$ROOT/services/mcp" python "$ROOT/deploy/azure/smoke.py"
fi

step "done: $P"
cat >&2 <<EOF2
MCP adapter:      https://$APP.<environment domain>/mcp/
Gateway bearer:   Key Vault $KV secret mcp-token            (ContextForge / voice agent, four tools)
Next:             register with ContextForge (deploy/contextforge/register.py), then AZURE.md §tests.
EOF2
