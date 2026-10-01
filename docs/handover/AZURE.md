# Deploy and test on Azure

The adapter is one Container App per rollout. It needs the two owner services' base URLs and machine
credentials; it needs no database, migration job or backend image. `deploy/azure/deploy.sh` is the
whole procedure as one re-runnable command; this page explains what it does and how to test.

## One command

```bash
R=rollouts/demo-hospital
export OPS_BASE_URL=https://<manoj-host>/api/v1 KNOWLEDGE_BASE_URL=https://<shobhit-host>
export OPS_CLIENT_ID=... OPS_CLIENT_SECRET=... KNOWLEDGE_BEARER_TOKEN=...   # first run only: stored in Key Vault
deploy/azure/deploy.sh $R --dry-run     # prints every az call; no login needed
deploy/azure/deploy.sh $R               # creates/updates, waits for the revision, runs the smoke
```

Production configuration refuses `http://` and any stub/mock hostname (`healthcare-contract-mock`,
`localhost`, `stub`, `prism`, ...). The script validates the adapter configuration offline first
(`frontdesk-mcp schema` under `ENV=production`).

## What it creates or reuses

| Resource | Default name | Notes |
|---|---|---|
| Resource group, Log Analytics, Container Apps environment, registry | `rg-frontdesk-<p>`, `law-frontdesk-<p>`, `cae-frontdesk-<p>`, `acrfd<hash>` | Reused when present; override with `AZ_RESOURCE_GROUP`, `AZ_CONTAINERAPPS_ENV`, `AZ_LOG_WORKSPACE`, `AZ_ACR` in `azure.env` (the demo uses the shared `healthcare-rg` set) |
| Image | `frontdesk-mcp:<git sha>` | Built from `services/mcp` only: no stubs, no fixtures, no dev dependencies |
| Key Vault | `kv-fd-<p>-<hash>` | `mcp-token` and `mcp-lifecycle-token` generated once; `ops-client-id`, `ops-client-secret`, `knowledge-token` supplied by the owners on first run |
| Managed identity | `id-frontdesk-<p>` | Key Vault Secrets User + AcrPull |
| Container App | `mcp-<p>` | External ingress on 8100, 1–3 replicas, readiness `/ready` (local), liveness `/health` |

Settings come from `rollout.env` (tenant identity) plus the owner URLs; secrets are Key Vault
references. `--replace-env-vars` on update, so a removed setting falls back to its default.

## Gateway and voice agent

Run ContextForge from its official image with `ENABLE_HEADER_PASSTHROUGH=true` and register the
adapter (`CONTEXTFORGE.md`). Give the voice platform the gateway bearer for the three in-call tools
and the lifecycle bearer for `record_call_summary` only (`LIVEKIT.md`).

## Test in Azure

The deploy script already runs `deploy/azure/smoke.py`: readiness, dependency status, refused
unauthenticated request, exactly three conversational tools, the lifecycle boundary, and two
read-only calls (`get_doctor_availability` for a department today, `search_knowledge`). It never
creates an appointment or a summary. Run it again any time:

```bash
MCP_URL=https://mcp-$P.$DOMAIN/mcp/ MCP_BEARER_TOKEN=... MCP_LIFECYCLE_BEARER_TOKEN=... SMOKE_LANGUAGE=en \
  uv run --project services/mcp python deploy/azure/smoke.py
```

Synthetic write journeys (create → list → reschedule → cancel → summary) run only against the
owners' designated test tenant: `OPS_E2E_BASE_URL=… ./scripts/test.sh` (suites marked `external`).
Never against a hospital's production tenant.

**Dependency status** without a token: `curl https://mcp-$P.$DOMAIN/dependencies` reports the
operational service (an authenticated `listDepartments` with a 1 s deadline, cached 15 s) and whether
the knowledge service is configured. `/ready` stays local: it does not probe upstreams.

**Logs.** Every line is JSON with `provider`, `callId`, `tool`, `outcome`, `nextStep`; never caller
numbers, names or upstream prose.

```bash
az containerapp logs show -g $RG -n mcp-$P --follow
```

## Upgrades and rollback

Re-run `deploy/azure/deploy.sh <rollout>` for a new adapter version or a settings change. Pin
together: image tag, `prompt.SCHEMA_VERSION`, the gateway registration (re-run `register.py` so the
gateway rediscovers tools) and the owner contract revision. Rollback is
`az containerapp revision activate` of the previous revision (or `deploy.sh` with `TAG=<previous>`)
against the same owner services: there is one appointment authority, never two. If a compatible
previous adapter cannot operate, disable writes by rotating the gateway bearer and keep the desk
flow; do not reactivate the retired backend.

## Production checklist

- Owner URLs are the owners' production hosts; credentials registered by them with exactly
  `appointments.write` and `calls.write`; `ACCEPTED_CALLER_VERIFICATION` agreed with Manoj and the platform.
- Gateway and lifecycle bearers differ and are held by different components.
- ContextForge passthrough covers every trusted header; voice platform forwards them and invokes the
  summary at call end with the lifecycle bearer.
- Smoke passes; latency measured on the real path (`mcp-only/implementation/LATENCY-RESULTS.md`).
- The retired backend's app, jobs, images, database and credentials are gone
  (`mcp-only/AZURE-RETIREMENT.md`, `mcp-only/implementation/AZURE-RETIREMENT-RESULTS.md`).
