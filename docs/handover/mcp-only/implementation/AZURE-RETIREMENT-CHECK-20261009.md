# Azure legacy retirement completed — 9 October 2026

## Authority and scope

Garima requested cleanup, confirmed the voice team no longer uses the old apps, and then instructed: **“I don't want to keep anything related to old mcp and api.”** This authorised removing the exclusively legacy database, application role, images, credentials and local app-recovery configurations without retaining a manual backup. Garima separately chose **“Leave for Rajeev to remove”** for stale settings in his voice apps. Shared services remain protected.

## Removed

| Asset | Result |
|---|---|
| `api-demo-hospital` Container App | Deleted; absence verified |
| `mcp-demo-hospital` Container App | Deleted; absence verified |
| `frontdesk` PostgreSQL database, including its old booking/knowledge data | Dropped; no active connections at deletion; absence verified |
| `frontdesk_app` PostgreSQL login role | Dropped after its database dependencies disappeared; absence verified |
| ACR repositories `frontdesk-api` and `frontdesk-api-demo-hospital` | Deleted, including their image manifests/tags |
| `frontdesk-mcp:32ef56b-20260927130453` and `frontdesk-mcp:32ef56b-20260927130453-r2` | Legacy manifests deleted; remaining manifest list has only the four standalone-MCP versions |
| Key Vault secrets `agent-token`, `auth-tokens`, `staff-token`, `db-app-password`, `db-app-url`, `db-owner-url` | Deleted and permanently purged; absent from active and deleted-secret inventories |
| `.context/azure-retirement-recovery-20261009/` and its two old app configuration files | Removed; no manual app-recovery files retained |
| Three old migration/apply/seed jobs | Already absent before this execution |

The two old apps were deleted in dependency order (MCP, then API). The old database was dropped without forcing off active users: the active-connection count was zero. `frontdesk_app` was dropped only after a cross-database dependency check found no remaining dependencies. No database export was made. Secrets were purged only after scanning current app/job vault references. Two initial purge requests failed; their retries succeeded and final absence was checked.

## Verified retained resources

Subscription `4e1c081a-9a6a-4e16-9da2-90217c22378b`, resource group `healthcare-rg`.

At **2026-10-09 08:54:35 UTC**:

- 13 Container Apps remain, down from 15. Their image, latest revision and running status match the pre-deletion baseline.
- `mcp-demo-hospital-canary` remains on `frontdesk-mcp:36336aa`, revision `mcp-demo-hospital-canary--0000003`.
- Canary `/health` and `/ready` each return HTTP 200. This is not a voice/booking journey test, and the new slots series was not deployed.
- Other databases remain: `voice_agent`, `voice_cis`, `operations`, `medplum`, `mcpgateway`, `postgres` and Azure system databases.
- Remaining MCP image tags are `1d0ad08`, `73a0832`, `e96242f` and `36336aa`, used by the standalone canary's current/historical revisions. These are not the retired pre-migration MCP implementation.
- Shared resource group, Container Apps environment, ACR, Key Vault, managed identity, Log Analytics workspace and PostgreSQL server were not removed or reconfigured.
- **`frontdesk_owner` and `db-owner-password` remain because they are the shared PostgreSQL server administrator and its credential.** Despite the historical names, they are not exclusive old-backend assets. Removing them would impair administration of other teams' databases.

The image audit inspected 41 current subscription apps, 5 group jobs and 202 revisions in `healthcare-rg`. None referenced the deleted old API/MCP images. No unrelated image repository was changed. The unrelated already-soft-deleted `mcpgw-healthcare-client-token` was not purged.

## Remaining owner-managed references and platform retention

Per Garima's decision, no change was made to Rajeev's running apps or jobs:

- `voice-api` and `voice-worker`: remove the unused `HEALTHCARE_TOOLS_BINDINGS_JSON.demo_hospital` entry pointing to the deleted API/MCP.
- `voice-restcheck`: its `BACKEND_URL` still references the old API; Rajeev must update or retire that job as appropriate.
- Voice-owned copied credentials such as `voice-frontdesk-agent-token` and `voice-frontdesk-staff-token` remain under his ownership; they were not part of our secret deletion list.

Any attempt to reuse those obsolete endpoints now fails. We did not silently point old clients at incompatible new APIs/tools. No message was sent to Rajeev.

Azure-managed PostgreSQL backups follow the shared server's configured **seven-day** retention. Historical recovery points may still contain the deleted database until they expire; no shared backup policy was changed and no claim of immediate physical erasure is made. There is no retained manual database export or old-app recovery configuration. Git history, historical contract snapshots and sanitised audit evidence are retained as records, not running legacy implementations.

Shobhit's KB is no longer a planned dependency per Garima; removing the current `search_knowledge` tool remains separate work. Current MCP credentials and knowledge/Stratum resources were not deleted under this legacy cleanup.

## Evidence and verification

Local evidence in ignored `.context/` contains no secret values or patient rows:

- `retirement-final-verification.json`: final app/database/image/secret checks and canary HTTP results.
- `retirement-db-role-audit.json`: database ownership, role dependencies and active-connection counts before deletion.
- `retirement-db-deletion-result.json`: database and role absence, shared admin retained.
- `retirement-exclusive-assets-audit.json`: app/job/revision images and vault-reference inventory.
- `retirement-image-deletions.json`: all four image deletion commands returned exit 0.
- `retirement-secret-deletions.json`, `retirement-secret-purge-retry.json`: deletion/purge results, including retry evidence.
- Earlier `azure-retirement-*` and aggregate traffic files preserve the initial investigation; their pre-deletion state is historical.

Audit commands: Azure resource/app/job/revision lists, ACR repository/manifest lists, Key Vault active/deleted secret names, PostgreSQL metadata queries and explicitly scoped DROP commands. Secret values were handled only in process memory for authenticated database access, never printed or written into evidence. The original pre-deletion read-only inventory used estimated table counts, not patient rows.

No new deployment, shared-resource configuration change, change to Rajeev's apps, source-code behaviour change, Git push/merge or owner communication occurred. Repository updates record the completed retirement and remove stale comments describing the deleted deployment; no runtime configuration value changed. Existing untracked `OPUS-SLOTS-5-REVIEW.md` and `temp/` are preserved.
