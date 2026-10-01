# Azure inventory and mandatory retirement work

Read-only inspection: 1 October 2026, the currently selected Azure subscription. These findings come from Azure Resource Manager and deployed app configuration, not just repository documentation. They do not establish who originally created every resource or prove ownership of all data. No secrets, database rows or live call content were read; no deployment, database modification or deletion was performed.

The user requires removal of obsolete resources from the former full-backend approach as part of the future MCP-only migration. **Cloud cleanup is a completion gate**, with an exact scoped execution list prepared after ownership, data handoff and cutover checks. It is not satisfied by deleting source files.

## Observed deployment

- `healthcare-rg` contains the legacy app `api-demo-hospital`, MCP app `mcp-demo-hospital`, database server and backend jobs, along with voice-platform and contract services.
- Deployed MCP configuration still has `API_BASE_URL` pointing to the internal `api-demo-hospital` `/api/v1` endpoint. This confirms the old runtime dependency, not just a default in source.
- All ten listed Container Apps use `cae-frontdesk-demo-hospital` and images from `acrfd399536`. Thus the Container Apps environment and registry are shared.
- PostgreSQL server `pg-fd-demo-hospital-0574c1` lists `frontdesk`, `voice_agent`, `voice_cis`, `operations`, `medplum`, plus `postgres`, `azure_sys` and `azure_maintenance`. Database names establish coexistence, not individual ownership or usage. The repository deployment script explicitly selects `frontdesk` for the old API.

```text
healthcare-rg — shared today
├─ Old implementation: API + migration/apply/seed jobs + frontdesk database
├─ Our MCP app
├─ Voice platform apps and jobs
├─ Contract documentation and mock apps
└─ Shared environment, registry and PostgreSQL server
```

Deleting the group, shared environment, registry or entire PostgreSQL server would also remove resources outside the retiring backend. Separate or retain those dependencies before deleting a parent resource. Manoj/Shobhit's intended separately owned deployments do not mean today's shared resources have already been separated.

## Resource disposition to confirm before execution

| Observed resource(s) | Required future disposition |
|---|---|
| `api-demo-hospital` and its legacy revisions | Retire after external-service cutover and any accepted data handoff. Verify no gateway, app, job or client still points to it. |
| `job-migrate-demo-hospital`, `job-apply-demo-hospital`, `job-seed-demo-hospital` | Remove old backend jobs and deployment paths after the new runtime no longer needs them. |
| `frontdesk` on `pg-fd-demo-hospital-0574c1` | Inventory accepted data and retention requirements; export/hand over only as agreed; retire the old database and database-specific grants/credentials when no consumers remain. Do not infer that the whole server is disposable. |
| Old `frontdesk-api` / `frontdesk-api-demo-hospital` image repositories, tags and associated credentials | Inventory current/old revisions and jobs first; remove obsolete backend images and access after agreed rollback/retention needs end. Preserve images still needed by supported services. This audit saw the deployed rollout API image, not a complete registry-tag inventory. |
| `mcp-demo-hospital` | Adapt/redeploy as the standalone MCP service or replace it with an explicitly owned MCP deployment. Preserve service continuity and gateway registration during cutover. |
| `cae-frontdesk-demo-hospital`, `acrfd399536`, `law-frontdesk-demo-hospital` | Shared platform infrastructure: assign a continuing owner/purpose or relocate remaining consumers before deletion. A legacy name is not evidence of exclusive legacy use. Log retention and diagnostic dependencies need inspection. |
| `kv-fd-demo-hospi-0574c1`, `id-frontdesk-demo-hospital` | Inventory consumers and access grants without dumping secrets. Remove backend-only secrets/grants; preserve or replace MCP/voice dependencies before considering whole-resource deletion. |
| `voice-api`, `voice-worker`, `voice-agent`, `voice-web`, `voice-widget`, `voice-cis` | Other voice-platform workloads. Preserve unless their owners explicitly include them in a coordinated relocation/retirement. They are not the repository's old `api-demo-hospital`. |
| `voice-restcheck`, `voice-migrate-hva`, `voice-migrate-cis`, `voice-seed`, `voice-cis-retention`; `id-voice-agent`, `id-voice-migrate`, `id-voice-cis` | Other platform jobs/identities. Confirm references to shared storage/registry; do not remove through a name-based bulk cleanup. |
| `healthcare-contract-docs`, `healthcare-contract-mock`, `kv-healthcare-ops-dev` | Preserve published interface/development services and confirm their owner's target resource placement. They are not proof of a production operational backend, nor obsolete simply because our backend is being retired. |
| `voice_agent`, `voice_cis`, `operations`, `medplum` databases | Confirm owners and consumers; preserve or arrange owner-managed relocation. Do not delete them with the old `frontdesk` database or treat them as owned by this repository. |
| `healthcare-rg` itself | Retain while it hosts needed services, or remove only after all needed resources have been relocated and remaining contents are explicitly obsolete. Any exclusively legacy group found during the final inventory should be retired once empty/unneeded. |

## Execution and completion evidence

1. Refresh the live inventory across the agreed subscriptions/resource groups at cutover. For each candidate capture resource ID, owner, consumers, data/retention disposition, dependency order and proposed action. This snapshot is not a universal deletion allowlist.
2. Identify actual database consumers, vault/identity permissions, old images/revisions, DNS/endpoint references, jobs, monitoring and shared networking. Current read-only inspection did not audit database rows, permissions, all historical revisions, all registry tags, actual billing or other subscriptions.
3. Prove the new MCP service uses only the two owner interfaces; preserve one appointment authority. Verify voice/gateway/call-end summary operation before retiring the old API.
4. Execute the reviewed scoped retirement after data handoff/retention conditions are met. Remove consumers/jobs before their unshared storage, secrets or images. No bulk resource-group/server deletion while unrelated consumers remain.
5. Verify absence of retired resources and active references, successful MCP/voice smoke checks, removed obsolete access and reviewed residual cost. Record intentionally retained shared resources and owner-approved retained data with purpose/expiry. Do not report cleanup complete with unexplained legacy services left running.

This is future work in phase 6 of [PLAN.md](PLAN.md). Preparing this inventory does not authorize immediate destruction during the present planning check.

## Read-only evidence sources

The inspection used `az group list`, a filtered `az resource list`, `az containerapp list -g healthcare-rg`, `az containerapp show` projected to the MCP API URL, and `az postgres flexible-server db list` projected to database names. It used control-plane reads, without database connections or secret-value retrieval. The [deployment script](../../../deploy/azure/deploy.sh) corroborates the legacy resource names, database choice and creation/deployment flow.
