# Deploy and test on Azure

The adapter is one Container App per rollout. It needs Manoj's operational base URL and machine
credentials; it needs no database, migration job or backend image. `deploy/azure/deploy.sh` is the
whole procedure as one re-runnable command; this page explains what it does and how to test.

## One command

```bash
R=rollouts/demo-hospital
# deploy/environments/live.env carries Manoj's base URL (…/api/v1) and targets the canary app; change endpoints there only
deploy/azure/deploy.sh $R --profile live --dry-run      # prints every az call; no login needed
deploy/azure/deploy.sh $R --profile live                # creates/updates mcp-demo-hospital-canary in healthcare-rg, runs the smoke
```

The profile (`deploy/environments/live.env`, non-secret, committed) names the subscription
`4e1c081a-9a6a-4e16-9da2-90217c22378b`, resource group `healthcare-rg`, environment, registry, vault and
identity; the script refuses to run without `--profile`, when the signed-in subscription differs, and it never
creates or defaults a resource group. Production configuration refuses `http://` and any stub/mock hostname,
so `--profile mock` can only dry-run. The script validates the adapter configuration offline first
(`frontdesk-mcp schema` under `ENV=production`).

**Ops credentials:** `ops-client-id`/`ops-client-secret` hold the registered pair Manoj stored on 2 October 2026 (accepted by `/auth/token`; token scope `appointments.write` only, so `record_call_summary` returns NOT_SAVED on a definite 403 until `calls.write` is granted). `deploy.sh` reads the current vault version and never overwrites an existing secret from the environment; rotate explicitly (`deploy/environments/README.md`). This is dated credential evidence, not a current permission check.

## What it creates or reuses

| Resource | Default name | Notes |
|---|---|---|
| Resource group, Log Analytics, Container Apps environment, registry | named by the profile: `healthcare-rg`, `law-frontdesk-demo-hospital`, `cae-frontdesk-demo-hospital`, `acrfd399536` | Shared; must exist; never created by this script |
| Image | `frontdesk-mcp:<git sha>` | Built from `services/mcp` only: no stubs, no fixtures, no dev dependencies |
| Key Vault | named by the profile (`kv-fd-demo-hospi-0574c1`) | `mcp-token` generated once; `ops-client-id`, `ops-client-secret` supplied by Manoj (replace explicitly; see above) |
| Managed identity | `id-frontdesk-<p>` | Key Vault Secrets User + AcrPull |
| Container App | named by the profile (`mcp-demo-hospital-canary` until the voice platform cuts over) | External ingress on 8100, 1–3 replicas, readiness `/ready` (local), liveness `/health` |

Settings come from `rollout.env` (tenant identity) plus the operational URL; secrets are Key Vault
references. `--replace-env-vars` on update, so a removed setting falls back to its default.

## Gateway and voice agent

Configure the existing ContextForge instance with `ENABLE_HEADER_PASSTHROUGH=true` and register the
adapter (`CONTEXTFORGE.md`). All three tools share the upstream gateway bearer. The voice platform
receives a scoped ContextForge client token and virtual-server URL (`VOICE-TEAM.md`).

## Test in Azure

The deploy script already runs `deploy/azure/smoke.py`: readiness, dependency status, refused
unauthenticated request, exactly three tools, and two
read-only availability calls (a department today and WORKING_HOURS for a doctor). It never
creates an appointment or a summary. Run it again any time:

```bash
MCP_URL=https://mcp-$P.$DOMAIN/mcp/ MCP_BEARER_TOKEN=... \
  uv run --project services/mcp python deploy/azure/smoke.py
```

Synthetic write journeys (create → list → reschedule → cancel → summary) run only against the
owners' designated test tenant: `OPS_E2E_BASE_URL=… ./scripts/test.sh` (suites marked `external`).
Never against a hospital's production tenant.

**Dependency status** without a token: `curl https://mcp-$P.$DOMAIN/dependencies` reports the
operational service only (an authenticated `listDepartments` with a 1 s deadline, cached 15 s). `/ready` stays local: it does not probe upstreams.

**Logs.** JSON tool-result events carry `provider`, `callId`, `tool`, `outcome` and nextStep where
applicable (null for summaries). Summary diagnostics record reason/retry delay under the call ID;
SAVED may log a bounded opaque summary ID. Summary text, caller numbers/names and upstream prose are excluded.

```bash
az containerapp logs show -g $RG -n mcp-$P --follow
```

## Upgrades and rollback

Re-run `deploy/azure/deploy.sh <rollout> --profile live` for a new adapter version or a settings change. Pin
together: image tag, `prompt.SCHEMA_VERSION`, the gateway registration (re-run `register.py` so the
gateway rediscovers tools) and the owner contract revision. Rollback is
`az containerapp revision activate` of the previous revision (or `deploy.sh` with `TAG=<previous>`)
against the same owner services: there is one appointment authority, never two. If a compatible
previous adapter cannot operate, disable writes by rotating the gateway bearer and keep the desk
flow; do not reactivate the retired backend.

## Production checklist

- The operational URL is Manoj's production host; credentials registered by them with exactly
  `appointments.write` and `calls.write`; `ACCEPTED_CALLER_VERIFICATION` agreed with Manoj and the platform.
- The voice client token is scoped to its ContextForge team/server; the upstream MCP bearer stays in gateway configuration.
- ContextForge passthrough covers every trusted header; voice platform forwards them and invokes the
  LLM-called summary through the same gateway authentication.
- Smoke passes; latency measured on the real path (`mcp-only/implementation/LATENCY-RESULTS.md`).
- The retired backend's app, jobs, images, database and credentials are gone
  (`mcp-only/AZURE-RETIREMENT.md`, `mcp-only/implementation/AZURE-RETIREMENT-RESULTS.md`).

## Removed summary credential

`mcp-lifecycle-token` becomes unused by the new revision. The script no longer creates, reads or
attaches it; `--replace-env-vars` removes its runtime setting. Existing Key Vault versions and app
secret references remain untouched by this task, for separately approved ownership/rollback review.
No Azure secret deletion is authorized by the source change. Coordinate image, gateway/voice schema
and auth configuration for rollback; an older image expects the removed second credential.

## Three-tool release and later cleanup

The source schema is `2026-10-11.1`; this document does not claim it deployed. Follow
[PLAN.md](mcp-only/PLAN.md): gate 8 requires Rajeev's symptom/emergency and transfer validation
through Stratum before deployment. After deployment refresh only our front-desk registration,
virtual server and LiveKit cache. Gate 9 requires voice-client discovery before live traffic.

The deployment script no longer reads, creates, attaches or deletes a knowledge credential.
Leftover app secret references and Key Vault `knowledge-token` require separately approved removal
after deployment. Legacy runtime settings are ignored by this adapter; a normal update replaces
runtime settings from the current configuration. No shared resource or Stratum cleanup is authorized.
