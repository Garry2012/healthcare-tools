# Voice AI team — Azure deployment handover

Verified 28 September 2026. Environment: **synthetic healthcare demo**.

**All new Azure resources must use `healthcare-rg` and Central India. Reuse the shared
resources below; deploy your components as separate applications.**

## Deployment target

| Setting | Value |
| --- | --- |
| Subscription | `Rajeev Subscription` |
| Subscription ID | `4e1c081a-9a6a-4e16-9da2-90217c22378b` |
| Tenant ID | `18323149-cc4d-4bff-809d-3eda6caec73a` |
| Resource group | `healthcare-rg` |
| Region | `centralindia` |

```bash
az account set --subscription 4e1c081a-9a6a-4e16-9da2-90217c22378b
export RG=healthcare-rg LOCATION=centralindia
```

## Shared resources: reuse with these boundaries

| Resource | Existing name / address | Allowed use |
| --- | --- | --- |
| Container Apps environment | `cae-frontdesk-demo-hospital` | Deploy your own apps here. Do not recreate it or change shared networking. |
| Container Registry | `acrfd399536.azurecr.io` | Push your images to new repositories such as `voice-agent`, `channel-gateway`, `contextforge`. Use unique release tags. |
| Key Vault | `kv-fd-demo-hospi-0574c1` | Add secrets prefixed `voice-`, `livekit-`, `twilio-`, `whatsapp-`, or `contextforge-`. Read the existing `mcp-token` for MCP access. |
| PostgreSQL 16 | `pg-fd-demo-hospital-0574c1.postgres.database.azure.com:5432` | Create a separate database, e.g. `voice_agent`, with its own restricted login. Use TLS. Platform owner handles initial DB/role provisioning; runtime gets only its own credentials. |
| Log Analytics | `law-frontdesk-demo-hospital` | Reuse for your applications' logs. Do not change workspace retention or remove existing logs. |

PostgreSQL currently uses **Standard_B1ms, 32 GiB**. Coordinate capacity changes before adding
significant load; the server is shared. No VM, AKS cluster, Redis, LiveKit media server or SIP
server is currently deployed in this resource group.

## Backend-owned: do not modify, delete, redeploy or run

| Protected item | Names |
| --- | --- |
| Running applications | `api-demo-hospital`, `mcp-demo-hospital` |
| Setup jobs | `job-migrate-demo-hospital`, `job-apply-demo-hospital`, `job-seed-demo-hospital` |
| Database and logins | Database `frontdesk`; roles `frontdesk_owner`, `frontdesk_app`; PostgreSQL system databases |
| Managed identity | `id-frontdesk-demo-hospital` — create your own identity instead |
| Registry repositories | `frontdesk-api`, `frontdesk-api-demo-hospital`, `frontdesk-mcp` |
| Existing secrets | `agent-token`, `auth-tokens`, `db-app-password`, `db-app-url`, `db-owner-password`, `db-owner-url`, `mcp-token`, `staff-token` |

`mcp-token` is **read-only for your integration**; do not rotate it. Do not use the backend's
DB-owner credentials. Do not change server-wide settings/firewalls, shared RBAC, or API ingress
without coordination. The API must stay internal. Do not run `deploy/azure/deploy.sh` to deploy
your agent: that script manages the backend.

These are ownership rules, not newly configured access restrictions. Scope deployment and
runtime RBAC accordingly; resource-group Contributor access would also permit backend changes.

## Deploy your Docker images

1. Push Linux `amd64` images to your own repositories in `acrfd399536`.
2. Create separate Container Apps, e.g. `voice-agent` and `channel-gateway`, in the existing
   environment. Choose CPU/memory for your agent's components and expected concurrency.
3. Create your own managed identity, e.g. `id-voice-agent`. Have the platform owner grant
   `AcrPull` and access to only your required Key Vault secrets, including `mcp-token`.
   Use [Key Vault secret references](https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets).
4. Keep the agent worker running with at least one replica. Public ingress is needed for your
   webhook/web services, not normally for the LiveKit worker. Test graceful call draining before
   enabling scale-down or rolling updates. [LiveKit deployment guidance](https://docs.livekit.io/deploy/custom/deployments/)
5. Configure your LiveKit connection, Twilio/WhatsApp credentials and model-provider keys in
   Key Vault. Own the channel webhooks, signature verification, web-user authentication and
   real call transfers.

If self-hosting LiveKit media/SIP, provision suitable networking/compute **in the same resource
group**; it needs media/SIP ports beyond an ordinary HTTP app.
[LiveKit port requirements](https://docs.livekit.io/transport/self-hosting/ports-firewall/)

## MCP connection contract

```text
Channel integrations → Voice AI Agent → [ContextForge, if used] → MCP → internal API

Transport: Streamable HTTP
URL: https://mcp-demo-hospital.icytree-6543aaa9.centralindia.azurecontainerapps.io/mcp/

Authorization: Bearer <Key Vault secret: mcp-token>
X-Call-Id: <unique stable conversation ID, maximum 64 characters>
X-Caller-Number: <verified caller number in E.164, e.g. +919000000777>
```

- Supply headers in agent/channel code, never from LLM tool arguments. Keep them isolated per
  conversation. For unverified web users, omit caller number; never invent one.
- Tools: `find_availability`, `manage_booking`, `search_knowledge`. Use these for booking logic.
- If using ContextForge, configure its own client authentication, the upstream MCP bearer,
  and passthrough of both call headers. ContextForge is **not deployed yet**.
- Live Azure tests passed for all three tools, multilingual answers and the full booking
  lifecycle. Your team must test the complete LiveKit/Twilio/WhatsApp/web path, including
  concurrent callers and actual transfers. Use synthetic data until a production rollout is agreed.

Further integration details: [LIVEKIT.md](LIVEKIT.md), [CONTEXTFORGE.md](CONTEXTFORGE.md).
