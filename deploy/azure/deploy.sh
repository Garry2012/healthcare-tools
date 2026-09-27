#!/usr/bin/env bash
# Deploy one rollout to Azure Container Apps: docs/handover/AZURE.md as one re-runnable command.
#
#   deploy/azure/deploy.sh <rollout directory> [--seed-demo] [--dry-run]
#
# The rollout directory is the only input (rollouts/<id>/ here, or a private repository's copy):
# rollout.env becomes the containers' settings, data.yaml is baked into a per-rollout API image
# and written by a `rollout apply` job, and an optional azure.env overrides the Azure names and
# sizes below. Nothing in the platform changes per rollout.
#
# Re-running is safe: resources that exist are kept, secrets are generated once and then read
# from Key Vault, containers get the new image and exactly the rollout's current settings.
#   --dry-run    print every az/psql call instead of running it (no Azure login needed)
#   --seed-demo  demo rollouts only (demo-*): also load the demo scenario, with ENV=staging
set -euo pipefail

usage() { sed -n '2,15p' "$0" >&2; exit 2; }
[[ $# -ge 1 && -d "$1" ]] || usage
ROLLOUT="$(cd "$1" && pwd)"; shift
DRY="" SEED_DEMO=""
for arg in "$@"; do
  case "$arg" in --dry-run) DRY=1 ;; --seed-demo) SEED_DEMO=1 ;; *) usage ;; esac
done
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

# --- run, capture, or (in a dry run) print ---------------------------------------------------
show() { printf '+ %s\n' "$*" | sed -E 's/(--value |PGPASSWORD=|--admin-password )[^ ]*/\1***/g' >&2; }
run() { if [[ -n "$DRY" ]]; then show "$@"; else "$@"; fi; }
out() { if [[ -n "$DRY" ]]; then show "$@"; echo "<$2-$3>"; else "$@"; fi; }
exists() { [[ -z "$DRY" ]] && "$@" >/dev/null 2>&1; }  # a dry run shows a first deployment
step() { printf '\n== %s\n' "$*" >&2; }

# --- 1. the rollout must pass its own checks before anything is created ------------------------
step "validate $ROLLOUT (settings, data, dialogues)"
(cd "$ROOT/services/api" && uv run -q frontdesk-api rollout validate "$ROLLOUT" >/dev/null) || {
  (cd "$ROOT/services/api" && uv run -q frontdesk-api rollout validate "$ROLLOUT") >&2; exit 1; }

read_env() {  # KEY=value lines, never `source` (JSON quotes, `$` in patterns)
  grep -Ev '^[[:space:]]*(#|$)' "$1" || true
}
mapfile -t ROLLOUT_ENV < <(read_env "$ROLLOUT/rollout.env")
P="$(printf '%s\n' "${ROLLOUT_ENV[@]}" | sed -n 's/^PROVIDER_ID=//p')"
if [[ -f "$ROLLOUT/azure.env" ]]; then
  while IFS= read -r line; do export "${line?}"; done < <(read_env "$ROLLOUT/azure.env")
fi
if [[ -n "$SEED_DEMO" && "$P" != demo-* ]]; then
  echo "--seed-demo is for demo rollouts only; $P is loaded with its own data" >&2; exit 2
fi

# --- names: deterministic per subscription and rollout, so a re-run finds the same resources ---
SUB="$(out az account show --query id -o tsv)"
hash6() { printf '%s' "$1" | sha1sum | cut -c1-6; }
LOC="${AZ_LOCATION:-centralindia}"
RG="${AZ_RESOURCE_GROUP:-rg-frontdesk-$P}"
ENV_NAME="${AZ_CONTAINERAPPS_ENV:-cae-frontdesk-$P}" LAW="${AZ_LOG_WORKSPACE:-law-frontdesk-$P}"
ACR="${AZ_ACR:-acrfd$(hash6 "$SUB")}"                     # one registry per subscription
KV="${AZ_KEYVAULT:-kv-fd-${P:0:10}-$(hash6 "$SUB$P")}"     # max 24 characters, globally unique
PG="${AZ_POSTGRES:-pg-fd-$P-$(hash6 "$SUB$P")}" DB=frontdesk
PG_SKU="${AZ_POSTGRES_SKU:-Standard_B1ms}" PG_TIER="${AZ_POSTGRES_TIER:-Burstable}"
TAG="${TAG:-$(git -C "$ROOT" rev-parse --short HEAD)}"
ID_NAME="id-frontdesk-$P"

# --- 2. resource group, logs, Container Apps environment, registry, images ---------------------
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
DOMAIN="$(out az containerapp env show -g "$RG" -n "$ENV_NAME" --query properties.defaultDomain -o tsv)"
exists az acr show -n "$ACR" || run az acr create -g "$RG" -n "$ACR" --sku Basic -o none

step "images $TAG: platform images, then this rollout's data on top of the API image"
run az acr build -r "$ACR" -t "frontdesk-api:$TAG" "$ROOT/services/api" -o none
run az acr build -r "$ACR" -t "frontdesk-mcp:$TAG" "$ROOT/services/mcp" -o none
CONTEXT="$(mktemp -d)"; trap 'rm -rf "$CONTEXT"' EXIT
cp "$ROLLOUT/rollout.env" "$ROLLOUT/data.yaml" "$CONTEXT/"
[[ -f "$ROLLOUT/dialogues.yaml" ]] && cp "$ROLLOUT/dialogues.yaml" "$CONTEXT/"
printf 'FROM %s.azurecr.io/frontdesk-api:%s\nCOPY . /app/rollout\n' "$ACR" "$TAG" > "$CONTEXT/Dockerfile"
run az acr build -r "$ACR" -t "frontdesk-api-$P:$TAG" "$CONTEXT" -o none
API_IMAGE="$ACR.azurecr.io/frontdesk-api-$P:$TAG" MCP_IMAGE="$ACR.azurecr.io/frontdesk-mcp:$TAG"

# --- 3. Key Vault and the identity that reads it -----------------------------------------------
step "secrets: $KV (generated once, then kept)"
exists az keyvault show -n "$KV" ||
  run az keyvault create -g "$RG" -n "$KV" -l "$LOC" --enable-rbac-authorization true -o none
KV_ID="$(out az keyvault show -n "$KV" --query id -o tsv)"
ME="$(out az ad signed-in-user show --query id -o tsv)"
run az role assignment create --assignee "$ME" --role "Key Vault Secrets Officer" --scope "$KV_ID" -o none
secret() {  # secret NAME GENERATOR...: the stored value, or a new one stored now
  local value
  if exists az keyvault secret show --vault-name "$KV" -n "$1"; then
    value="$(az keyvault secret show --vault-name "$KV" -n "$1" --query value -o tsv)"
  else
    value="$("${@:2}")"
    run az keyvault secret set --vault-name "$KV" -n "$1" --value "$value" -o none
  fi
  printf '%s' "$value"
}
token() { openssl rand -hex 24; }
password() { openssl rand -base64 24 | tr -d '/+='; }
OWNER_PW="$(secret db-owner-password password)" APP_PW="$(secret db-app-password password)"
AGENT_TOKEN="$(secret agent-token token)" STAFF_TOKEN="$(secret staff-token token)"
MCP_TOKEN="$(secret mcp-token token)"

exists az identity show -g "$RG" -n "$ID_NAME" || run az identity create -g "$RG" -n "$ID_NAME" -o none
ID="$(out az identity show -g "$RG" -n "$ID_NAME" --query id -o tsv)"
PRINCIPAL="$(out az identity show -g "$RG" -n "$ID_NAME" --query principalId -o tsv)"
run az role assignment create --assignee-object-id "$PRINCIPAL" --assignee-principal-type ServicePrincipal \
  --role "Key Vault Secrets User" --scope "$KV_ID" -o none
run az role assignment create --assignee-object-id "$PRINCIPAL" --assignee-principal-type ServicePrincipal \
  --role AcrPull --scope "$(out az acr show -n "$ACR" --query id -o tsv)" -o none
kv() { echo "$1=keyvaultref:https://$KV.vault.azure.net/secrets/$1,identityref:$ID"; }

# --- 4. PostgreSQL: the owner runs migrations, the API role is DML-only ------------------------
step "database: $PG"
HOST="$PG.postgres.database.azure.com"
if ! exists az postgres flexible-server show -g "$RG" -n "$PG"; then
  run az postgres flexible-server create -g "$RG" -n "$PG" -l "$LOC" --version 16 --tier "$PG_TIER" \
    --sku-name "$PG_SKU" --storage-size 32 --admin-user frontdesk_owner --admin-password "$OWNER_PW" \
    --public-access 0.0.0.0 -o none
  run az postgres flexible-server db create -g "$RG" -s "$PG" -d "$DB" -o none
  MY_IP="$(out curl -s https://ifconfig.me)"
  run az postgres flexible-server firewall-rule create -g "$RG" -n "$PG" --rule-name setup \
    --start-ip-address "$MY_IP" --end-ip-address "$MY_IP" -o none
  ROLES="CREATE ROLE frontdesk_app LOGIN PASSWORD '$APP_PW';
GRANT CONNECT ON DATABASE $DB TO frontdesk_app;
GRANT USAGE ON SCHEMA public TO frontdesk_app;
ALTER DEFAULT PRIVILEGES FOR ROLE frontdesk_owner IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO frontdesk_app;
ALTER DEFAULT PRIVILEGES FOR ROLE frontdesk_owner IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO frontdesk_app;"
  # SQL on stdin and the password in the environment: neither shows in the process list.
  run env PGPASSWORD="$OWNER_PW" psql "host=$HOST port=5432 dbname=$DB user=frontdesk_owner sslmode=require" \
    -v ON_ERROR_STOP=1 <<<"$ROLES"
  run az postgres flexible-server firewall-rule delete -g "$RG" -n "$PG" --rule-name setup --yes -o none
fi
secret db-owner-url echo "postgresql://frontdesk_owner:$OWNER_PW@$HOST:5432/$DB?sslmode=require" >/dev/null
secret db-app-url echo "postgresql://frontdesk_app:$APP_PW@$HOST:5432/$DB?sslmode=require" >/dev/null
STAFF_SCOPES='"bookings.staff","schedule.write","board.write","directory.write","knowledge.write","calls.write","calls.read"'
secret auth-tokens echo "{\"$AGENT_TOKEN\":[\"agent\"],\"$STAFF_TOKEN\":[$STAFF_SCOPES]}" >/dev/null

# --- 5. jobs: migrate, then write the rollout (and, for a demo, its scenario) ------------------
job() {  # job NAME ENV SECRET ARGS...: (re)create a manual job with the current image, run it, wait
  local name="job-$1-$P" env="$2" db_secret="$3"; shift 3
  exists az containerapp job show -g "$RG" -n "$name" && run az containerapp job delete -g "$RG" -n "$name" --yes -o none
  run az containerapp job create -g "$RG" -n "$name" --environment "$ENV_NAME" --trigger-type Manual \
    --replica-timeout 600 --replica-retry-limit 0 --image "$API_IMAGE" --registry-server "$ACR.azurecr.io" \
    --registry-identity "$ID" --mi-user-assigned "$ID" --secrets "$(kv "$db_secret")" \
    --env-vars ENV="$env" DATABASE_URL="secretref:$db_secret" ROLLOUT_DIR=/app/rollout "${ROLLOUT_ENV[@]}" \
    --command frontdesk-api --args "$@" -o none
  local execution
  execution="$(out az containerapp job start -g "$RG" -n "$name" --query name -o tsv)"
  [[ -n "$DRY" ]] && return 0
  for _ in $(seq 1 120); do
    case "$(az containerapp job execution show -g "$RG" -n "$name" --job-execution-name "$execution" \
              --query properties.status -o tsv)" in
      Succeeded) return 0 ;;
      Failed|Stopped) echo "job $name failed: az containerapp job logs show -g $RG -n $name" >&2; exit 1 ;;
    esac
    sleep 5
  done
  echo "job $name did not finish in 10 minutes" >&2; exit 1
}
step "migrate (owner role), then apply the rollout (domain baseline + its data)"
job migrate production db-owner-url migrate
job apply production db-app-url rollout apply
[[ -n "$SEED_DEMO" ]] && { step "demo scenario (ENV=staging)"; job seed staging db-app-url seed; }

# --- 6. the API (internal only) and the MCP adapter (reached by the gateway) --------------------
app() {  # app NAME IMAGE PORT INGRESS SIZE SECRETS ENV...: create, or update to this image and env
  local name="$1" image="$2" port="$3" ingress="$4" cpu="$5" memory="$6" secrets="$7"; shift 7
  if exists az containerapp show -g "$RG" -n "$name"; then
    run az containerapp update -g "$RG" -n "$name" --image "$image" --replace-env-vars "$@" -o none
  else
    # shellcheck disable=SC2086  # the secrets list is space-separated on purpose
    run az containerapp create -g "$RG" -n "$name" --environment "$ENV_NAME" --image "$image" \
      --registry-server "$ACR.azurecr.io" --registry-identity "$ID" --user-assigned "$ID" \
      --ingress "$ingress" --target-port "$port" --min-replicas 1 --max-replicas 3 --cpu "$cpu" --memory "$memory" \
      --secrets $secrets --env-vars "$@" -o none
  fi
  # Container Apps ignores the Dockerfile HEALTHCHECK: readiness on /ready, liveness on /health.
  local spec; spec="$(mktemp)"
  run az containerapp show -g "$RG" -n "$name" -o yaml > "$spec"
  if [[ -z "$DRY" ]]; then
    (cd "$ROOT/services/api" && uv run -q python - "$spec" "$port" <<'PY'
import sys, yaml
path, port = sys.argv[1], int(sys.argv[2])
spec = yaml.safe_load(open(path))
spec["properties"]["template"]["containers"][0]["probes"] = [
    {"type": "Readiness", "httpGet": {"path": "/ready", "port": port}, "periodSeconds": 5},
    {"type": "Liveness", "httpGet": {"path": "/health", "port": port}, "periodSeconds": 10},
]
yaml.safe_dump(spec, open(path, "w"))
PY
    )
  fi
  run az containerapp update -g "$RG" -n "$name" --yaml "$spec" -o none
  rm -f "$spec"
}
step "containers: api-$P (internal), mcp-$P (external)"
app "api-$P" "$API_IMAGE" 8000 internal 0.5 1Gi "$(kv db-app-url) $(kv auth-tokens)" \
  ENV=production HOST=0.0.0.0 PORT=8000 ROLLOUT_DIR=/app/rollout DATABASE_URL=secretref:db-app-url \
  AUTH_TOKENS_JSON=secretref:auth-tokens "${ROLLOUT_ENV[@]}"
app "mcp-$P" "$MCP_IMAGE" 8100 external 0.25 0.5Gi "$(kv agent-token) $(kv mcp-token)" \
  ENV=production HOST=0.0.0.0 PORT=8100 "API_BASE_URL=https://api-$P.internal.$DOMAIN/api/v1" \
  API_BEARER_TOKEN=secretref:agent-token MCP_BEARER_TOKEN=secretref:mcp-token "${ROLLOUT_ENV[@]}"

step "done: $P"
cat >&2 <<EOF
MCP adapter:   https://mcp-$P.$DOMAIN/mcp/   (bearer: Key Vault $KV secret mcp-token)
Next:          register it with ContextForge (AZURE.md §7), then test (AZURE.md §8).
EOF
