# Azure retirement results (1 October 2026)

> **Reconciliation (architect's actions, same day):** after this report was written the architect, at the user's
> request, deleted the three legacy jobs (`job-migrate-demo-hospital`, `job-apply-demo-hospital`,
> `job-seed-demo-hospital`) and created two generated test secrets (`ops-client-id`, `ops-client-secret`) in
> `kv-fd-demo-hospi-0574c1`, which the live backend rejected (401). Details and evidence paths:
> [ARCHITECT-AZURE-CLEANUP.md](ARCHITECT-AZURE-CLEANUP.md). The correction pass performed **no** further Azure
> change. Rows below are updated to the current state.

**Status: partially executed (by the architect, jobs only); neither correction pass executed anything. The inventory
below is the proposed plan with per-resource ownership evidence; shared resources are retained even where this
repository created them (environment, registry, vault, log workspace, PostgreSQL server, managed identity).** The cutover gates in PLAN.md phase 5/6 are not met
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

## Resource-ID inventory (read-only, 1 October 2026, after the architect's job deletions)

Note: the live-vs-pinned contract statement earlier in this report is superseded: the live `/api/v1/openapi.yaml` hash is `6f827be1…` (servers entry only differs).

Prefix for every ID: `/subscriptions/4e1c081a-9a6a-4e16-9da2-90217c22378b/resourceGroups/healthcare-rg/providers/`.
"Ours" = created by this repository's `deploy/azure/deploy.sh` (createdBy `Garima.Tyagi@intimetec.com`, 27 Sep 2026,
names matching the script's `<kind>-frontdesk-<provider>` / `<kind>-<provider>` pattern, no `product=` tag).
Voice-platform resources carry `product=healthcare-voice-ai` tags and were created by `Rajeev.Kumar@intimetec.com`;
Manoj's by `manoj.mewara@intimetec.com`. **Only resources that are ours AND have no remaining consumer are proposed
for retirement; shared resources are retained even though this repository created them.** Nothing below was executed
in this pass.

| Resource (ID suffix) | Ours? (evidence) | Current consumers | Shared? | Disposition | Must happen before retirement |
|---|---|---|---|---|---|
| `Microsoft.App/containerApps/api-demo-hospital` | Yes (deploy.sh `api-$P`, createdBy Garima 2026-09-27) | `mcp-demo-hospital` (`API_BASE_URL`), `voice-api` and `voice-worker` (`HEALTHCARE_TOOLS_BINDINGS_JSON.demo_hospital.base_url` + `VOICE_FRONTDESK_*_TOKEN`) | No (ours), but consumed by another team | **Retire** | Voice team removes the REST binding; new MCP image deployed and voice path verified; `frontdesk` data disposition decided |
| `Microsoft.App/containerApps/mcp-demo-hospital` | Yes (deploy.sh `mcp-$P`) | `voice-api`/`voice-worker` (`mcp.url`), future gateway | No | **Retain** as the legacy integration until the voice team moves to the canary; then retire or rename | Live URL + registered credentials + knowledge host (canary works); voice team cutover |
| `Microsoft.App/jobs/job-{migrate,apply,seed}-demo-hospital` | Yes | none | No | **Already deleted by the architect** | — |
| `Microsoft.DBforPostgreSQL/flexibleServers/pg-fd-demo-hospital-0574c1` (server) | Created by deploy.sh (createdAt 2026-09-27 13:12; admin `frontdesk_owner`) | databases `voice_agent`, `voice_cis` (voice team), `operations`, `medplum` (Manoj), `frontdesk` (ours) | **Yes** | **Retain** (shared server) | — |
| database `frontdesk` on that server | Yes (deploy.sh `DB=frontdesk`, roles `frontdesk_owner`/`frontdesk_app`) | `api-demo-hospital` only | No | **Retire after data disposition** | Owner-confirmed inventory of rows (appointments, summaries, knowledge entries): log activity shows demo-era writes only, which is **not** proof every row is disposable; decide export vs delete; then `DROP DATABASE frontdesk` and drop roles |
| `Microsoft.ContainerRegistry/registries/acrfd399536` | Created by deploy.sh (createdBy Garima) | all 13 container apps and 5 jobs (`voice-*`, `healthcare-*`, ours) | **Yes** | **Retain** | — |
| repositories `frontdesk-api`, `frontdesk-api-demo-hospital` (3 manifests each, Sep 27–28) | Yes | `api-demo-hospital` (running image `frontdesk-api-demo-hospital:expected-windows-20260928051702`) | No | **Retire after the API app** | API app deleted; rollback window closed |
| repository `frontdesk-mcp` | Yes | `mcp-demo-hospital` | No | **Retain**; prune pre-migration tags after cutover | — |
| `Microsoft.App/managedEnvironments/cae-frontdesk-demo-hospital` | Created by deploy.sh (createdBy Garima) | every container app and job in the group | **Yes** | **Retain** | — |
| `Microsoft.OperationalInsights/workspaces/law-frontdesk-demo-hospital` | Created by deploy.sh | the environment's logs (all apps) | **Yes** | **Retain** | — |
| `Microsoft.KeyVault/vaults/kv-fd-demo-hospi-0574c1` | Created by deploy.sh | ours (`mcp-token`, …), voice (`voice-*`, `livekit-*`), gateway (`mcpgw-healthcare-client-token`) | **Yes** | **Retain** | — |
| vault secrets `agent-token`, `auth-tokens`, `staff-token`, `db-owner-password`, `db-owner-url`, `db-app-password`, `db-app-url` | Yes (deploy.sh `secret` names) | `api-demo-hospital`, `mcp-demo-hospital` (`agent-token`) | No | **Retire after the API and `frontdesk` database** | API/database gone; MCP upgraded to the new secret set |
| vault secrets `voice-frontdesk-agent-token`, `voice-frontdesk-staff-token` | **No** (voice team's copies) | `voice-api`/`voice-worker` | voice team | **Not ours — removed from our list**; the voice team retires them when they drop the REST binding | — |
| vault secrets `mcp-token`, `mcp-lifecycle-token`*, `ops-client-id`, `ops-client-secret`, `knowledge-token`* (*created on first `deploy.sh` run) | Yes / architect | `mcp-demo-hospital` (future) | No | **Retain**; replace dummy ops values with registered ones (deploy/environments/README.md) | — |
| `Microsoft.ManagedIdentity/userAssignedIdentities/id-frontdesk-demo-hospital` (Key Vault Secrets User, AcrPull) | Created by deploy.sh | `api-demo-hospital`, `mcp-demo-hospital` **and Manoj's `healthcare-api`, `healthcare-medplum`, `healthcare-contract-docs`, `healthcare-contract-mock`** | **Yes** | **Retain** (a legacy-looking name is not exclusive legacy use) | — |
| `voice-*` apps/jobs, `id-voice-*` | No (voice team, tagged) | voice platform | other team | **Retain** | — |
| `healthcare-api`, `healthcare-medplum`, `healthcare-contract-docs`, `healthcare-contract-mock`, `kv-healthcare-ops-dev` | No (Manoj) | Manoj; the mock is our integration-test target | other team | **Retain** | — |
| databases `voice_agent`, `voice_cis`, `operations`, `medplum` | No | voice team / Manoj | other teams | **Retain** | — |
| `healthcare-rg` | Shared group | everyone | **Yes** | **Retain** | — |

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
# 0. prove the replacement: deploy/azure/deploy.sh rollouts/demo-hospital --profile live (canary app), smoke green, voice path verified
# 1. consumers first
az containerapp update -g $RG -n voice-api    --set-env-vars 'HEALTHCARE_TOOLS_BINDINGS_JSON=<without base_url/agent_key_ref/staff_key_ref>'   # voice team
az containerapp update -g $RG -n voice-worker --set-env-vars 'HEALTHCARE_TOOLS_BINDINGS_JSON=<same>'                                            # voice team
# 2. the retired backend
az containerapp delete -g $RG -n api-demo-hospital --yes
# (the three legacy jobs were already deleted by the architect on 1 Oct 2026)
# 3. its data: ONLY after an owner-confirmed row inventory and an explicit export-or-delete decision
#    (log activity showing demo-era writes is not proof that every row is disposable)
#    psql as frontdesk_owner: DROP DATABASE frontdesk; DROP ROLE frontdesk_app;   (server stays: voice_agent, voice_cis, operations, medplum)
# 4. its credentials
for s in agent-token auth-tokens staff-token db-owner-password db-owner-url db-app-password db-app-url; do az keyvault secret delete --vault-name kv-fd-demo-hospi-0574c1 -n $s; done
# voice-frontdesk-agent-token / voice-frontdesk-staff-token are the voice team's: not in our list
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
  → at that time `b8f28271…` (identical); later the same day `6f827be1…` (servers entry only; see note above).
