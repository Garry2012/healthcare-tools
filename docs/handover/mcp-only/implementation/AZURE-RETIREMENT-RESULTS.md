# Azure retirement results (1 October 2026)

> **Reconciliation (architect's actions, same day):** after this report was written the architect, at the user's
> request, deleted the three legacy jobs (`job-migrate-demo-hospital`, `job-apply-demo-hospital`,
> `job-seed-demo-hospital`) and created two generated test secrets (`ops-client-id`, `ops-client-secret`) in
> `kv-fd-demo-hospi-0574c1`, which the live backend rejected (401). Details and evidence paths:
> [ARCHITECT-AZURE-CLEANUP.md](ARCHITECT-AZURE-CLEANUP.md). The correction pass performed **no** further Azure
> change. Rows below are updated to the current state.

**Status: partially executed (by the architect, jobs only); the correction pass executed nothing.** The cutover gates in PLAN.md phase 5/6 are not met
(no credentials to Manoj's real service, Shobhit's service absent, the voice platform still bound to
the legacy REST API, no voice-path verification), so retiring the legacy API, jobs, images, database
or credentials now would break the running demo and remove the only appointment authority the voice
platform currently uses. This report records the refreshed read-only inventory, exact resource IDs,
dependency facts discovered, the scoped action list prepared for execution, and what remains blocked.

Subscription `Rajeev Subscription` (`4e1c081a-9a6a-4e16-9da2-90217c22378b`), resource group
`healthcare-rg`, Central India. Inspection via `az resource list`, `az containerapp show/revision list`,
`az containerapp job execution list`, `az role assignment list`, `az postgres flexible-server show/db list`,
`az acr repository/manifest list`, `az keyvault secret list` (names only), `az monitor log-analytics query`
(log line counts). No database connection, secret value read, deployment, deletion or configuration change.

## Refreshed inventory (31 resources) and disposition

Resource IDs share the prefix `/subscriptions/4e1c081a-9a6a-4e16-9da2-90217c22378b/resourceGroups/healthcare-rg/providers/`.

| Resource | Type | Owner / consumers (observed) | Disposition | Executed |
|---|---|---|---|---|
| `api-demo-hospital` (revision `--0000002`, image `frontdesk-api-demo-hospital:expected-windows-20260928051702`) | Microsoft.App/containerApps | This repo's retired backend. **Consumers:** `mcp-demo-hospital` (`API_BASE_URL`), and `voice-api`/`voice-worker` via `HEALTHCARE_TOOLS_BINDINGS_JSON.demo_hospital.base_url` with `VOICE_FRONTDESK_AGENT_TOKEN`/`VOICE_FRONTDESK_STAFF_TOKEN` | Retire after cutover gates | **Not executed** (active consumers) |
| `job-migrate-demo-hospital`, `job-apply-demo-hospital`, `job-seed-demo-hospital` | Microsoft.App/jobs | Retired backend's one-shot jobs | Delete | **Deleted by the architect** (ARCHITECT-AZURE-CLEANUP.md); absent from `az containerapp job list` on re-check |
| `frontdesk` database on `pg-fd-demo-hospital-0574c1` (Standard_B1ms, 32 GiB, PG16) | database | Retired backend only (roles `frontdesk_owner`, `frontdesk_app`). Rows not read (no TTY for `az containerapp exec`; API internal-only). Log Analytics (30 days): `booking_booked` ×5, `booking_rescheduled` ×1, `booking_cancelled` ×1, `bookings_listed` ×8, `availability_search` ×73, `knowledge_search` ×30, all between 27 Sep 13:33 and 28 Sep 05:56 UTC, i.e. the deployment's own demo/e2e runs on synthetic data; no activity since | Owner confirms the synthetic bookings need no handoff, then `DROP DATABASE frontdesk` and role removal. **The server stays**: `voice_agent`, `voice_cis`, `operations`, `medplum` belong to the voice platform and Manoj | **Not executed** |
| `frontdesk-api`, `frontdesk-api-demo-hospital` repositories (3 manifests each, ~74 MB, 27–28 Sep) | ACR repositories in `acrfd399536` | Retired backend images | Delete repositories after the API app is gone (keeps a rollback image until then) | **Not executed** |
| `frontdesk-mcp` repository (tags `32ef56b-…`, `-r2`) | ACR repository | Current MCP app (old revision); new adapter images will be pushed here | Keep; prune pre-migration tags after cutover | — |
| `mcp-demo-hospital` (revision `--0000001`, env `API_BASE_URL` → legacy API) | Microsoft.App/containerApps | This repo. Consumers: `voice-api`/`voice-worker` (`mcp.url`), gateway (none deployed) | Redeploy with the MCP-only image and owner URLs via `deploy/azure/deploy.sh` once credentials exist | **Not executed** (needs Manoj/Shobhit credentials; production config refuses stubs) |
| Key Vault `kv-fd-demo-hospi-0574c1` secrets `agent-token`, `auth-tokens`, `staff-token`, `db-owner-password`, `db-owner-url`, `db-app-password`, `db-app-url` | secrets | Retired backend credentials; `voice-frontdesk-agent-token`/`voice-frontdesk-staff-token` duplicate them for the voice platform | Delete after API/database retirement; rotate nothing else. Vault stays (voice/livekit/mcp secrets) | **Not executed** |
| Key Vault secrets `ops-client-id`, `ops-client-secret` (generated test values, tagged `validation=not-accepted-by-live-api`) | secrets | Created by the architect for the MCP adapter; not registered with Manoj's backend | Keep as the slots `deploy.sh` reads once Manoj registers the pair, or replace their values with registered ones | **Exists; not valid for the live API** |
| Key Vault grants: `Garima.Tyagi@intimetec.com` Secrets Officer; principal `39cb86ed-…` (id-frontdesk-demo-hospital) Secrets User | role assignments | Deployer and the shared identity | Keep (MCP redeploy uses the same identity) | — |
| `id-frontdesk-demo-hospital` | managed identity | API, jobs **and** MCP app (AcrPull, KV Secrets User) | Keep for MCP | — |
| `cae-frontdesk-demo-hospital`, `acrfd399536`, `law-frontdesk-demo-hospital` | shared environment, registry, logs | All 13 container apps and 8 jobs | Keep; owner: platform (this repo's deployer created them; voice team and Manoj consume them) | — |
| `pg-fd-demo-hospital-0574c1` server | PostgreSQL flexible server | Databases of three teams | Keep | — |
| `healthcare-api` (created 2026-10-01 06:07 UTC by manoj.mewara, image `healthcare-backend-api:0.3.0-draft-35dcb94-wip202610010815`, external, `/api/v1`), `healthcare-medplum` (internal), `kv-healthcare-ops-dev`, `healthcare-contract-docs`, `healthcare-contract-mock` | Manoj's services and vault | Manoj | Keep; this is the new appointment authority. Its served `/api/v1/openapi.yaml` was compared with the pinned snapshot (see REVIEW-REPORT) | — |
| `voice-api`, `voice-worker`, `voice-agent`, `voice-web`, `voice-widget`, `voice-cis`, jobs `voice-*`, identities `id-voice-*` | voice platform | Voice team | Keep; **owner action**: remove the direct `api-demo-hospital` REST binding and tokens, forward trusted MCP headers | — |

## Dependencies discovered that gate retirement

1. **The voice platform calls the legacy REST API directly** (`HEALTHCARE_TOOLS_BINDINGS_JSON` on
   `voice-api` and `voice-worker`, with agent and staff tokens). Retiring `api-demo-hospital` before the
   voice team repoints breaks their appointment flows. This was not visible in the earlier inventory.
2. **No ContextForge in `healthcare-rg`.** The `mcp-gateway` app in `vcare-rc-rg` belongs to another
   project. The voice platform binds to `mcp-demo-hospital` directly.
3. **Manoj's backend is deployed but closed to us.** `healthcare-api` returns 401 to unregistered
   clients; `kv-healthcare-ops-dev` is forbidden to this identity. Credentials must come from Manoj.
4. **Legacy data: synthetic demo only, by log evidence.** Rows were not read, but the API's own
   structured logs over 30 days show seven booking mutations on 27–28 Sep 2026 (the deployment's demo
   and e2e runs), none since; summaries endpoint never called. A row count by the owner remains the
   formal confirmation before `DROP DATABASE`.

## Scoped execution list (prepared, not run)

In this order, once gates 1–4 above are met and the owner confirms the `frontdesk` data disposition:

```bash
RG=healthcare-rg
# 0. prove the replacement: deploy/azure/deploy.sh rollouts/demo-hospital (MCP-only), smoke green, voice path verified
# 1. consumers first
az containerapp update -g $RG -n voice-api    --set-env-vars 'HEALTHCARE_TOOLS_BINDINGS_JSON=<without base_url/agent_key_ref/staff_key_ref>'   # voice team
az containerapp update -g $RG -n voice-worker --set-env-vars 'HEALTHCARE_TOOLS_BINDINGS_JSON=<same>'                                            # voice team
# 2. the retired backend
az containerapp delete -g $RG -n api-demo-hospital --yes
# (the three legacy jobs were already deleted by the architect on 1 Oct 2026)
# 3. its data (after owner-led export/handoff or explicit "delete")
#    psql as frontdesk_owner: DROP DATABASE frontdesk; DROP ROLE frontdesk_app;   (server stays: voice_agent, voice_cis, operations, medplum)
# 4. its credentials
for s in agent-token auth-tokens staff-token db-owner-password db-owner-url db-app-password db-app-url; do az keyvault secret delete --vault-name kv-fd-demo-hospi-0574c1 -n $s; done
az keyvault secret delete --vault-name kv-fd-demo-hospi-0574c1 -n voice-frontdesk-agent-token   # voice team confirms
az keyvault secret delete --vault-name kv-fd-demo-hospi-0574c1 -n voice-frontdesk-staff-token   # voice team confirms
# 5. its images
az acr repository delete -n acrfd399536 --repository frontdesk-api --yes
az acr repository delete -n acrfd399536 --repository frontdesk-api-demo-hospital --yes
# 6. verify absence and the live path
az resource list -g $RG --query "[?contains(name,'api-demo-hospital') || contains(name,'job-')]"   # expect only voice jobs
MCP_URL=https://mcp-demo-hospital.<domain>/mcp/ … deploy/azure/smoke.py
```

Rollback during the window: steps 1–2 are reversible only while the API image and database exist;
hence data (3) and images (5) are last. Nothing is deleted while it has a consumer.

## Residual cost and retention

Not measured (no Cost Management query was run). Three idle jobs already removed. Expected savings from the
remaining list: one Container App (0.5 vCPU/1 GiB, min 1 replica), ~450 MB of registry storage and one
database on a shared Burstable server (server cost unchanged). Retained-data expiry: to be set by the owner when
the `frontdesk` disposition is decided; no retention obligation is known for synthetic demo data.

## Verification evidence

- `az resource list -g healthcare-rg` on 1 Oct 2026 (31 resources; two new Manoj apps since the
  morning inventory in AZURE-RETIREMENT.md).
- `az containerapp show -g healthcare-rg -n voice-api --query "properties.template.containers[0].env[?name=='HEALTHCARE_TOOLS_BINDINGS_JSON']"`
  shows the direct legacy binding.
- Log Analytics (`law-frontdesk-demo-hospital`, workspace `77f660bb-5060-4394-8774-55a3bc40c687`, 30 days):
  `ContainerAppConsoleLogs_CL | where ContainerAppName_s == 'api-demo-hospital' | extend j=parse_json(Log_s) | summarize count() by tostring(j.msg)`
  → request 160,262 (probes), availability_search 73, knowledge_search 30, bookings_listed 8,
  booking_booked 5, booking_rescheduled 1, booking_cancelled 1 (27 Sep 13:33 – 28 Sep 05:56 UTC);
  `mcp-demo-hospital` 171,776 lines (mostly probes).
- `curl https://healthcare-api.icytree-6543aaa9.centralindia.azurecontainerapps.io/api/v1/openapi.yaml | shasum -a 256`
  → `b8f282718c2c45410dd0dd403369223b9cbe8dea045ee044207aa1e52ec2de78`, identical to the pinned snapshot.
