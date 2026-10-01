#!/usr/bin/env bash
# Deploy the MCP adapter for one rollout to Azure Container Apps, as one re-runnable command.
#
#   deploy/azure/deploy.sh <rollout directory> [--dry-run]
#
# The rollout directory supplies rollout.env (tenant settings, non-secret) and an optional azure.env
# that overrides the Azure names below. The two owner services are external: their base URLs come
# from azure.env or the environment (OPS_BASE_URL, KNOWLEDGE_BASE_URL) and MUST be the owners' real
# hosts over https; production configuration refuses stubs and mocks. Nothing here provisions a
# database, runs migrations or builds any backend image: Manoj and Shobhit deploy their own services.
#
# Re-running is safe: resources that exist are kept, generated secrets are created once and then read
# from Key Vault, the container gets the new image and exactly the rollout's current settings.
#   --dry-run    print every az call instead of running it (no Azure login needed)
#
# Secrets in Key Vault (names): mcp-token (gateway bearer), mcp-lifecycle-token (call-end bearer),
# ops-client-id / ops-client-secret (Manoj machine client, supplied by the owner: set OPS_CLIENT_ID /
# OPS_CLIENT_SECRET in the environment on first run), knowledge-token (Shobhit, same).
set -euo pipefail

usage() { sed -n '2,20p' "$0" >&2; exit 2; }
[[ $# -ge 1 && -d "$1" ]] || usage
ROLLOUT="$(cd "$1" && pwd)"; shift
DRY=""
for arg in "$@"; do
  case "$arg" in --dry-run) DRY=1 ;; *) usage ;; esac
done
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

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
if [[ -f "$ROLLOUT/azure.env" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do export "${line?}"; done < <(read_env "$ROLLOUT/azure.env")
fi
: "${OPS_BASE_URL:?set OPS_BASE_URL to Manoj's deployed API base (https://host/api/v1)}"
: "${KNOWLEDGE_BASE_URL:?set KNOWLEDGE_BASE_URL to Shobhit's deployed service base (https://host)}"
for url in "$OPS_BASE_URL" "$KNOWLEDGE_BASE_URL"; do
  [[ "$url" == https://* ]] || { echo "owner service URLs must be https: $url" >&2; exit 2; }
  case "$url" in *contract-mock*|*localhost*|*127.0.0.1*|*stub*|*prism*|*mock*)
    echo "refusing to deploy production against a stub/mock endpoint: $url" >&2; exit 2 ;;
  esac
done

step "validate the adapter configuration offline (settings, pack, tool schema)"
(cd "$ROOT/services/mcp" && env -i PATH="$PATH" HOME="$HOME" ENV=production "${ROLLOUT_ENV[@]}" \
  OPS_BASE_URL="$OPS_BASE_URL" OPS_CLIENT_ID=validate OPS_CLIENT_SECRET=validate \
  KNOWLEDGE_BASE_URL="$KNOWLEDGE_BASE_URL" KNOWLEDGE_BEARER_TOKEN=validate \
  MCP_BEARER_TOKEN=validate-a MCP_LIFECYCLE_BEARER_TOKEN=validate-b \
  uv run -q frontdesk-mcp schema >/dev/null)

# --- names: deterministic per subscription and rollout ------------------------------------------
SUB="$(out az account show --query id -o tsv)"
hash6() { printf '%s' "$1" | openssl dgst -sha1 | sed 's/^.*= //' | cut -c1-6; }
LOC="${AZ_LOCATION:-centralindia}"
RG="${AZ_RESOURCE_GROUP:-rg-frontdesk-$P}"
ENV_NAME="${AZ_CONTAINERAPPS_ENV:-cae-frontdesk-$P}" LAW="${AZ_LOG_WORKSPACE:-law-frontdesk-$P}"
ACR="${AZ_ACR:-acrfd$(hash6 "$SUB")}"
KV="${AZ_KEYVAULT:-kv-fd-${P:0:10}-$(hash6 "$SUB$P")}"
TAG="${TAG:-$(git -C "$ROOT" rev-parse --short HEAD)}"
ID_NAME="${AZ_IDENTITY:-id-frontdesk-$P}"
APP="${AZ_MCP_APP:-mcp-$P}"

# --- 2. shared infrastructure (kept if present) and the image ------------------------------------
step "infrastructure: $RG in $LOC"
run az group create -n "$RG" -l "$LOC" -o none
exists az monitor log-analytics workspace show -g "$RG" -n "$LAW" ||
  run az monitor log-analytics workspace create -g "$RG" -n "$LAW" -l "$LOC" -o none
if ! exists az containerapp env show -g "$RG" -n "$ENV_NAME"; then
  LAW_ID="$(out az monitor log-analytics workspace show -g "$RG" -n "$LAW" --query customerId -o tsv)"
  LAW_KEY="$(out az monitor log-analytics workspace get-shared-keys -g "$RG" -n "$LAW" --query primarySharedKey -o tsv)"
  run az containerapp env create -g "$RG" -n "$ENV_NAME" -l "$LOC" \
    --logs-workspace-id "$LAW_ID" --logs-workspace-key "$LAW_KEY" -o none
fi
exists az acr show -n "$ACR" || run az acr create -g "$RG" -n "$ACR" --sku Basic -o none

step "image frontdesk-mcp:$TAG (services/mcp only: no stubs, no fixtures)"
run az acr build -r "$ACR" -t "frontdesk-mcp:$TAG" "$ROOT/services/mcp" -o none
MCP_IMAGE="$ACR.azurecr.io/frontdesk-mcp:$TAG"

# --- 3. Key Vault secrets and the identity that reads them ---------------------------------------
step "secrets: $KV"
exists az keyvault show -n "$KV" ||
  run az keyvault create -g "$RG" -n "$KV" -l "$LOC" --enable-rbac-authorization true -o none
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
LIFECYCLE_TOKEN="$(secret mcp-lifecycle-token token)"
secret ops-client-id supplied OPS_CLIENT_ID >/dev/null
secret ops-client-secret supplied OPS_CLIENT_SECRET >/dev/null
secret knowledge-token supplied KNOWLEDGE_BEARER_TOKEN >/dev/null
[[ "$MCP_TOKEN" != "$LIFECYCLE_TOKEN" ]] || { echo "gateway and lifecycle bearers must differ" >&2; exit 1; }

exists az identity show -g "$RG" -n "$ID_NAME" || run az identity create -g "$RG" -n "$ID_NAME" -o none
ID="$(out az identity show -g "$RG" -n "$ID_NAME" --query id -o tsv)"
PRINCIPAL="$(out az identity show -g "$RG" -n "$ID_NAME" --query principalId -o tsv)"
run az role assignment create --assignee-object-id "$PRINCIPAL" --assignee-principal-type ServicePrincipal \
  --role "Key Vault Secrets User" --scope "$KV_ID" -o none
run az role assignment create --assignee-object-id "$PRINCIPAL" --assignee-principal-type ServicePrincipal \
  --role AcrPull --scope "$(out az acr show -n "$ACR" --query id -o tsv)" -o none
kv() { echo "$1=keyvaultref:https://$KV.vault.azure.net/secrets/$1,identityref:$ID"; }

# --- 4. the adapter (reached by the gateway and the call-end lifecycle) --------------------------
step "container: $APP"
SECRETS="$(kv mcp-token) $(kv mcp-lifecycle-token) $(kv ops-client-id) $(kv ops-client-secret) $(kv knowledge-token)"
ENV_VARS=(ENV=production HOST=0.0.0.0 PORT=8100
  "OPS_BASE_URL=$OPS_BASE_URL" OPS_CLIENT_ID=secretref:ops-client-id OPS_CLIENT_SECRET=secretref:ops-client-secret
  "KNOWLEDGE_BASE_URL=$KNOWLEDGE_BASE_URL" KNOWLEDGE_BEARER_TOKEN=secretref:knowledge-token
  MCP_BEARER_TOKEN=secretref:mcp-token MCP_LIFECYCLE_BEARER_TOKEN=secretref:mcp-lifecycle-token
  "${ROLLOUT_ENV[@]}")
if exists az containerapp show -g "$RG" -n "$APP"; then
  # Upgrade path (AR-05): an app deployed by the legacy script carries only agent-token/mcp-token. Attach the
  # identity and registry access, then every Key Vault reference the new environment names, BEFORE switching the
  # revision's environment; otherwise the new revision cannot resolve its secretrefs and never becomes ready.
  run az containerapp identity assign -g "$RG" -n "$APP" --user-assigned "$ID" -o none
  run az containerapp registry set -g "$RG" -n "$APP" --server "$ACR.azurecr.io" --identity "$ID" -o none
  # shellcheck disable=SC2086  # the secrets list is space-separated on purpose
  run az containerapp secret set -g "$RG" -n "$APP" --secrets $SECRETS -o none
  run az containerapp update -g "$RG" -n "$APP" --image "$MCP_IMAGE" --replace-env-vars "${ENV_VARS[@]}" -o none
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
step "verify: latest revision ready, dependencies, authentication, three conversational tools, lifecycle boundary"
wait_ready
MCP_HOST="$(out az containerapp show -g "$RG" -n "$APP" --query properties.configuration.ingress.fqdn -o tsv)"
LANG1="$(printf '%s\n' "${ROLLOUT_ENV[@]}" | sed -n 's/^TENANT_SUPPORTED_LANGUAGES=//p' | cut -d, -f1)"
if [[ -n "$DRY" ]]; then
  show uv run --project "$ROOT/services/mcp" python "$ROOT/deploy/azure/smoke.py"
else
  MCP_URL="https://$MCP_HOST/mcp/" MCP_BEARER_TOKEN="$MCP_TOKEN" MCP_LIFECYCLE_BEARER_TOKEN="$LIFECYCLE_TOKEN" \
    SMOKE_LANGUAGE="$LANG1" uv run --project "$ROOT/services/mcp" python "$ROOT/deploy/azure/smoke.py"
fi

step "done: $P"
cat >&2 <<EOF2
MCP adapter:      https://$APP.<environment domain>/mcp/
Gateway bearer:   Key Vault $KV secret mcp-token            (ContextForge / voice agent, three tools)
Lifecycle bearer: Key Vault $KV secret mcp-lifecycle-token  (call-end finalizer, record_call_summary)
Next:             register with ContextForge (deploy/contextforge/register.py), then AZURE.md §tests.
EOF2
