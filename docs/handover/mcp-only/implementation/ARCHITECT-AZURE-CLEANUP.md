# Architect Azure cleanup — 1 October 2026

Execution verified by 09:13 UTC. This supplements the earlier retirement report, whose statement
that nothing has been deleted is no longer current for the three jobs listed here.

The user explicitly requested Azure cleanup during the architect review. No new generic cleanup
approval is needed. Changes were restricted to confirmed obsolete resources from this repository.

Subscription: `4e1c081a-9a6a-4e16-9da2-90217c22378b` (Rajeev Subscription).
Resource group: `healthcare-rg`. No other resource group was changed.

## Executed and verified

| Resource | Evidence before deletion | Result |
|---|---|---|
| `job-migrate-demo-hospital` | Manual trigger, one successful execution on 27 September, no active execution | Deleted; absent from job list |
| `job-apply-demo-hospital` | Manual trigger, one successful execution on 27 September, no active execution | Deleted; absent from job list |
| `job-seed-demo-hospital` | Manual trigger, one successful execution on 27 September, no active execution | Deleted; absent from job list |

Each resource was a `Microsoft.App/jobs` resource under the subscription/group above. Commands:

```bash
az containerapp job delete --subscription 4e1c081a-9a6a-4e16-9da2-90217c22378b -g healthcare-rg -n job-migrate-demo-hospital --yes -o none
az containerapp job delete --subscription 4e1c081a-9a6a-4e16-9da2-90217c22378b -g healthcare-rg -n job-apply-demo-hospital --yes -o none
az containerapp job delete --subscription 4e1c081a-9a6a-4e16-9da2-90217c22378b -g healthcare-rg -n job-seed-demo-hospital --yes -o none
```

All three commands succeeded. The remaining job list contains only `voice-restcheck`,
`voice-migrate-hva`, `voice-migrate-cis`, `voice-seed` and `voice-cis-retention`; these belong to the
voice platform and were not changed. No job was started and no database mutation was performed.

Redacted resource metadata and execution summaries were saved before deletion in
`.context/architect-review/azure/`. These are diagnostic records, not complete restorable backups;
inline environment values are redacted. Legacy deployment definitions remain available in Git
history if a job must be reconstructed. API images and databases have not been removed.

## Retained because they are still required

- `api-demo-hospital`: both `voice-api` and `voice-worker` still contain its URL in
  `HEALTHCARE_TOOLS_BINDINGS_JSON`. The deployed MCP also remains on the old integration. Removing
  the API now would break existing callers before their replacement is verified.
- `pg-fd-demo-hospital-0574c1`: direct database inventory shows `frontdesk`, `voice_agent`, `voice_cis`,
  `operations`, and `medplum`, in addition to Azure/system databases. This is a shared server, not
  an obsolete backend-only server. Keep it. Retiring only `frontdesk` requires completed consumer
  cutover and a confirmed export/delete decision for its data; log activity alone does not prove
  every stored row is synthetic.
- Existing backend credentials/images: retained while the API is live and for rollback during
  cutover. Remove their exact scoped names after their last consumer is gone.
- Shared environment, registry, vault, logs and identity: consumed by retained MCP/voice/owner apps.
- Manoj's apps, vault and contract mock: owner resources, not this repository's obsolete backend.
  No knowledge-service or ContextForge app was found in this resource group's current app list.

After deletion Azure reports `Succeeded` / `Running` for `api-demo-hospital`, `mcp-demo-hospital`,
`voice-api`, `voice-worker`, and `healthcare-api`. This verifies management-plane state only; it does
not claim a real customer call was tested.

## Remaining ordered work

1. Resolve the code/test/deployment findings in `ARCHITECT-REVIEW.md`.
2. Obtain registered Manoj credentials and the synthetic tenant, plus Shobhit's actual contract/host.
   The current identity has no access to Manoj's vault; no permission was changed or bypassed.
3. Prove the replacement tools and voice/gateway/lifecycle integration, then switch consumers off
   the old REST binding. Validate the live path before retiring the API.
4. Retire the old API; export or remove only its `frontdesk` data as agreed; remove unused backend
   credentials and image repositories. Keep shared and other-team resources.
5. Refresh the inventory and verify both absence of retired resources and working retained flows.

Cleanup is therefore **partially executed**, not complete. No source implementation was changed,
PR was merged, application was deployed or database was modified during this architect review.
