# Deploy and test on Azure

One stack per provider (hospital or hotel), as everywhere else (TARGET.md A1):

```
                       Azure Container Apps environment  (region: Central India or South India)
 LiveKit agent ──▶ ContextForge ──▶ frontdesk-mcp-<p> ──https (internal)──▶ frontdesk-api-<p> ──TLS──▶ Azure Database for PostgreSQL
                   (gateway)         (external ingress,     (internal ingress only)                   (Flexible Server 16)
                                      bearer auth)
 Images: Azure Container Registry   Secrets: Key Vault (read by a managed identity)   Logs: Log Analytics
 Migrations: a Container Apps job (manual trigger), run with the owner role before each rollout
```

> These steps use the documented `az` CLI (Azure CLI 2.60+ with the `containerapp` extension).
> They haven't been run against a subscription from this repository. Run them in a test
> subscription first, and read each step's check.

## 0. Variables

```bash
az login && az extension add -n containerapp --upgrade
export P=demo-hospital            # provider id: deploy/providers/$P.env
export RG=rg-frontdesk-$P LOC=centralindia
export ACR=acrfrontdesk$RANDOM KV=kv-frontdesk-$P ENV_NAME=cae-frontdesk LAW=law-frontdesk
export PG=pg-frontdesk-$P DB=frontdesk TAG=$(git rev-parse --short HEAD)
export OWNER_PW=$(openssl rand -base64 24 | tr -d '/+=') APP_PW=$(openssl rand -base64 24 | tr -d '/+=')
export AGENT_TOKEN=$(openssl rand -hex 24) STAFF_TOKEN=$(openssl rand -hex 24) MCP_TOKEN=$(openssl rand -hex 24)
```

Keep these values out of shell history in production (read them from Key Vault instead).

## 1. Resource group, logs, Container Apps environment, registry

```bash
az group create -n $RG -l $LOC
az monitor log-analytics workspace create -g $RG -n $LAW -l $LOC
LAW_ID=$(az monitor log-analytics workspace show -g $RG -n $LAW --query customerId -o tsv)
LAW_KEY=$(az monitor log-analytics workspace get-shared-keys -g $RG -n $LAW --query primarySharedKey -o tsv)
az containerapp env create -g $RG -n $ENV_NAME -l $LOC --logs-workspace-id $LAW_ID --logs-workspace-key $LAW_KEY
DOMAIN=$(az containerapp env show -g $RG -n $ENV_NAME --query properties.defaultDomain -o tsv)

az acr create -g $RG -n $ACR --sku Basic
az acr build -r $ACR -t frontdesk-api:$TAG services/api
az acr build -r $ACR -t frontdesk-mcp:$TAG services/mcp
```

**Check:** `az acr repository show-tags -n $ACR --repository frontdesk-api` lists `$TAG`.

## 2. PostgreSQL (one server or database per provider)

```bash
az postgres flexible-server create -g $RG -n $PG -l $LOC --version 16 \
  --tier Burstable --sku-name Standard_B1ms --storage-size 32 \
  --admin-user frontdesk_owner --admin-password "$OWNER_PW" --public-access 0.0.0.0
az postgres flexible-server db create -g $RG -s $PG -d $DB
```

`--public-access 0.0.0.0` lets Azure services reach the server. For production, use VNet
integration (`--vnet`/`--subnet`) and put the Container Apps environment on the same VNet.

Create the DML-only runtime role once, as the owner. The API never runs DDL:

```bash
psql "host=$PG.postgres.database.azure.com port=5432 dbname=$DB user=frontdesk_owner password=$OWNER_PW sslmode=require" <<SQL
CREATE ROLE frontdesk_app LOGIN PASSWORD '$APP_PW';
GRANT CONNECT ON DATABASE $DB TO frontdesk_app;
GRANT USAGE ON SCHEMA public TO frontdesk_app;
ALTER DEFAULT PRIVILEGES FOR ROLE frontdesk_owner IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO frontdesk_app;
ALTER DEFAULT PRIVILEGES FOR ROLE frontdesk_owner IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO frontdesk_app;
SQL
```

The connection strings keep Azure's `sslmode=require`. The service translates it for asyncpg
(`config.py`, `tests/unit/test_config.py`).

## 3. Secrets in Key Vault, read by one managed identity

```bash
az keyvault create -g $RG -n $KV -l $LOC --enable-rbac-authorization true
KV_ID=$(az keyvault show -n $KV --query id -o tsv)
az role assignment create --assignee "$(az ad signed-in-user show --query id -o tsv)" \
  --role "Key Vault Secrets Officer" --scope $KV_ID
HOST=$PG.postgres.database.azure.com
az keyvault secret set --vault-name $KV -n db-owner-url --value "postgresql://frontdesk_owner:$OWNER_PW@$HOST:5432/$DB?sslmode=require"
az keyvault secret set --vault-name $KV -n db-app-url   --value "postgresql://frontdesk_app:$APP_PW@$HOST:5432/$DB?sslmode=require"
az keyvault secret set --vault-name $KV -n auth-tokens  --value "{\"$AGENT_TOKEN\":[\"agent\"],\"$STAFF_TOKEN\":[\"bookings.staff\",\"schedule.write\",\"board.write\",\"directory.write\",\"knowledge.write\",\"calls.write\",\"calls.read\"]}"
az keyvault secret set --vault-name $KV -n agent-token  --value "$AGENT_TOKEN"
az keyvault secret set --vault-name $KV -n mcp-token    --value "$MCP_TOKEN"

az identity create -g $RG -n id-frontdesk-$P
ID=$(az identity show -g $RG -n id-frontdesk-$P --query id -o tsv)
PRINCIPAL=$(az identity show -g $RG -n id-frontdesk-$P --query principalId -o tsv)
az role assignment create --assignee-object-id $PRINCIPAL --assignee-principal-type ServicePrincipal \
  --role "Key Vault Secrets User" --scope $KV_ID
az role assignment create --assignee-object-id $PRINCIPAL --assignee-principal-type ServicePrincipal \
  --role AcrPull --scope "$(az acr show -n $ACR --query id -o tsv)"
kv() { echo "$1=keyvaultref:https://$KV.vault.azure.net/secrets/$2,identityref:$ID"; }
```

## 4. Provider settings

Container Apps takes the same non-secret file the compose stack uses. Read it line by
line; never `source` it, because that strips the JSON quotes:

```bash
mapfile -t PROVIDER_ENV < <(grep -Ev '^[[:space:]]*(#|$)' deploy/providers/$P.env)
```

## 5. Migrate (a job, run before every rollout)

```bash
az containerapp job create -g $RG -n job-migrate-$P --environment $ENV_NAME \
  --trigger-type Manual --replica-timeout 600 --replica-retry-limit 0 \
  --image $ACR.azurecr.io/frontdesk-api:$TAG --registry-server $ACR.azurecr.io --registry-identity $ID \
  --mi-user-assigned $ID --secrets "$(kv db-owner-url db-owner-url)" \
  --env-vars ENV=production DATABASE_URL=secretref:db-owner-url "${PROVIDER_ENV[@]}" \
  --command frontdesk-api --args migrate
az containerapp job start -g $RG -n job-migrate-$P
az containerapp job execution list -g $RG -n job-migrate-$P -o table     # wait for Succeeded
```

## 6. API (internal only) and MCP adapter (reachable by the gateway)

```bash
az containerapp create -g $RG -n api-$P --environment $ENV_NAME \
  --image $ACR.azurecr.io/frontdesk-api:$TAG --registry-server $ACR.azurecr.io --registry-identity $ID \
  --user-assigned $ID --ingress internal --target-port 8000 --min-replicas 1 --max-replicas 3 --cpu 0.5 --memory 1Gi \
  --secrets "$(kv db-app-url db-app-url)" "$(kv auth-tokens auth-tokens)" \
  --env-vars ENV=production HOST=0.0.0.0 PORT=8000 DATABASE_URL=secretref:db-app-url \
             AUTH_TOKENS_JSON=secretref:auth-tokens "${PROVIDER_ENV[@]}"

az containerapp create -g $RG -n mcp-$P --environment $ENV_NAME \
  --image $ACR.azurecr.io/frontdesk-mcp:$TAG --registry-server $ACR.azurecr.io --registry-identity $ID \
  --user-assigned $ID --ingress external --target-port 8100 --min-replicas 1 --max-replicas 3 --cpu 0.25 --memory 0.5Gi \
  --secrets "$(kv agent-token agent-token)" "$(kv mcp-token mcp-token)" \
  --env-vars ENV=production HOST=0.0.0.0 PORT=8100 \
             API_BASE_URL=https://api-$P.internal.$DOMAIN/api/v1 \
             API_BEARER_TOKEN=secretref:agent-token MCP_BEARER_TOKEN=secretref:mcp-token "${PROVIDER_ENV[@]}"
```

- `--min-replicas 1` keeps a warm instance, so a caller never waits for a cold start.
- The MCP adapter refuses to start in production unless `API_BASE_URL` is `https://`. The
  environment's internal FQDN serves TLS.
- If ContextForge runs in the same environment, make the adapter `--ingress internal` too.

**Health probes.** Container Apps doesn't use the Dockerfile `HEALTHCHECK`. Set HTTP probes
so traffic only reaches an API whose schema matches (`/ready`), and a stuck process is
restarted (`/health`). Export the app with `az containerapp show -g $RG -n api-$P -o yaml > api.yaml`,
add the following under `properties.template.containers[0]`, and apply with
`az containerapp update -g $RG -n api-$P --yaml api.yaml`. Do the same for `mcp-$P` on port 8100:

```yaml
probes:
  - type: Readiness
    httpGet: {path: /ready, port: 8000}
    periodSeconds: 5
  - type: Liveness
    httpGet: {path: /health, port: 8000}
    periodSeconds: 10
```

## 7. Gateway and voice agent

ContextForge is infrastructure (`CONTEXTFORGE.md`). Run it as another Container App from its
official image, following ContextForge's own deployment guide, with
`ENABLE_HEADER_PASSTHROUGH=true`. Then register this provider's adapter:

```bash
export CONTEXTFORGE_URL=https://<gateway-host> MCP_PUBLIC_URL=https://mcp-$P.$DOMAIN/mcp/ MCP_BEARER_TOKEN=$MCP_TOKEN
export PROVIDER_ID=$P DOMAIN_PACK=$(grep '^DOMAIN_PACK=' deploy/providers/$P.env | cut -d= -f2)
(cd services/mcp && uv run python ../../deploy/contextforge/register.py --dry-run && uv run python ../../deploy/contextforge/register.py)
```

Point the LiveKit agent at ContextForge and set the call headers (`LIVEKIT.md`).

## 8. Test in Azure

**Test environment only:** load the synthetic hospital. For a real provider, follow
`ONBOARDING.md` step 4 instead and never seed.

```bash
az containerapp job create -g $RG -n job-seed-$P --environment $ENV_NAME --trigger-type Manual \
  --replica-timeout 600 --replica-retry-limit 0 \
  --image $ACR.azurecr.io/frontdesk-api:$TAG --registry-server $ACR.azurecr.io --registry-identity $ID \
  --mi-user-assigned $ID --secrets "$(kv db-app-url db-app-url)" \
  --env-vars ENV=staging DATABASE_URL=secretref:db-app-url "${PROVIDER_ENV[@]}" \
  --command frontdesk-api --args seed
az containerapp job start -g $RG -n job-seed-$P
```

**The API, end to end.** Open the internal API to your own IP for the duration of the test,
then close it again:

```bash
az containerapp ingress update -g $RG -n api-$P --type external
az containerapp ingress access-restriction set -g $RG -n api-$P --rule-name tester \
  --ip-address "$(curl -s https://ifconfig.me)/32" --action Allow
API_HOST=$(az containerapp show -g $RG -n api-$P --query properties.configuration.ingress.fqdn -o tsv)
curl -s https://$API_HOST/ready                    # {"status":"ready","schema":"0003"}
API_URL=https://$API_HOST/api/v1 AGENT_TOKEN=$AGENT_TOKEN ./scripts/demo.sh   # book → list → reschedule → cancel
az containerapp ingress update -g $RG -n api-$P --type internal
```

Also run the scenarios in `TESTING.md` "Try these by hand" against `API_URL`.

**The MCP adapter, as the voice agent sees it:**

```bash
cd services/mcp && MCP_URL=https://mcp-$P.$DOMAIN/mcp/ MCP_TOKEN=$MCP_TOKEN uv run python - <<'PY'
import asyncio, os
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
async def main():
    t = StreamableHttpTransport(os.environ["MCP_URL"], headers={
        "Authorization": f"Bearer {os.environ['MCP_TOKEN']}", "X-Call-Id": "azure-smoke-1",
        "X-Caller-Number": "+919000000777"})
    async with Client(t) as c:
        print([tool.name for tool in await c.list_tools()])
        r = await c.call_tool("search_knowledge", {"question": "ಪಾರ್ಕಿಂಗ್ ಇದೆಯಾ", "language": "kn"})
        print(r.structured_content["outcome"], r.structured_content["answer"]["text"])
asyncio.run(main())
PY
```

Expected output: the three tools, then `ANSWERED` and the Kannada parking answer.

**Logs.** Every line is JSON with `provider` and `callId`:

```bash
az containerapp logs show -g $RG -n api-$P --follow
```

In Log Analytics:

```kusto
ContainerAppConsoleLogs_CL
| where ContainerAppName_s == "api-demo-hospital"
| extend j = parse_json(Log_s) | where tostring(j.callId) == "azure-smoke-1"
```

## 9. Upgrades

1. `az acr build` the new tag.
2. Update the migrate job's image and start it. Wait for `Succeeded`.
3. `az containerapp update --image …:<tag>` for `api-$P`, then `mcp-$P`.

`/ready` is strict, so an old API goes unready as soon as the schema moves on: roll out right
after the migration. Revision `0002` renames tables and needs a maintenance window
(`DEPLOY.md`).

## Production checklist

- Private networking: VNet-integrated environment, Postgres with no public access, and the API
  on internal ingress only.
- Data residency: Central India or South India region, for the DPDP Act.
- Secrets only in Key Vault. Rotate `AUTH_TOKENS_JSON` and `MCP_BEARER_TOKEN` by adding the
  new token, rolling out, then removing the old one.
- Backups: the Flexible Server's automated backups (7–35 days) and a tested point-in-time
  restore.
- Alerts in Log Analytics on 5xx rate, `COULD_NOT_CHECK` outcomes, and `db_ms` in
  `Server-Timing` above budget.
