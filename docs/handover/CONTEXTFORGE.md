# IBM ContextForge integration

## Verified state — 2 October 2026

An existing **ContextForge 1.0.11** instance is running in `healthcare-rg`. Authenticated inspection
found no registered backends or virtual servers. This review read its version and OpenAPI; it did
not register anything or change Azure settings. Do not provision a second gateway.

| Setting | Value |
|---|---|
| Gateway base | `https://mcp-gateway.icytree-6543aaa9.centralindia.azurecontainerapps.io` |
| Upstream MCP URL | `https://mcp-demo-hospital-canary.icytree-6543aaa9.centralindia.azurecontainerapps.io/mcp/` |
| Transport | `STREAMABLEHTTP` |
| Backend registration name | `frontdesk-demo-hospital` |
| Upstream bearer | Current `mcp-token` in `kv-fd-demo-hospi-0574c1` |
| Separate call-end bearer | `mcp-lifecycle-token` in that vault; never attach it to the conversational registration |
| Existing admin access | Email from gateway `PLATFORM_ADMIN_EMAIL`; password reference `mcpgw-platform-admin-password` in that vault |

The canary currently has no working knowledge host. Discovery can be verified now; successful
availability/CREATE/knowledge journeys require Shobhit's contract and service. The gateway's actual
voice-facing URL is created in step 3 below, not the gateway base URL alone.

```text
Voice backend -- scoped gateway token + trusted headers --> ContextForge virtual server
             -- stored mcp-token + forwarded headers --> MCP canary --> Manoj / knowledge API
Call-end worker -- separate mcp-lifecycle-token --------> MCP canary --> Manoj call summaries
```

## 1. Platform owner: configure the existing instance

Enable `ENABLE_HEADER_PASSTHROUGH=true` and keep `ENABLE_OVERWRITE_BASE_HEADERS=false`. Neither flag
was explicitly present in the inspected Container App environment; verify effective configuration
after changing it. Allow only the headers below on this registered backend. Do not pass through the
incoming `Authorization` header: ContextForge must use its stored MCP credential upstream.

```text
X-Call-Id
X-Caller-Number
X-Caller-Verification
X-Turn-Context
X-Operation-Id
X-Call-Started-At
X-Call-Duration-Seconds
```

Allow network access to the upstream MCP URL. Restrict the virtual server and its client credential
to the trusted voice backend/team; these caller assertions must not be writable by an untrusted
browser or model. Platform-owned values override any model-generated values before transmission.

## 2. MCP/platform operator: register and verify the backend

Supply `CONTEXTFORGE_URL`, `MCP_PUBLIC_URL` from the table, `MCP_BEARER_TOKEN` from `mcp-token`, and
either a temporary admin JWT (`CONTEXTFORGE_TOKEN`) or the admin email/password above. Read secrets
into process memory through approved vault access; do not paste them into commands, Git or chat.
For shared team access also supply the existing `CONTEXTFORGE_TEAM_ID`.

```bash
eval "$(scripts/rollout-env.sh rollouts/demo-hospital)"
uv run --project services/mcp python deploy/contextforge/register.py --visibility team --dry-run
uv run --project services/mcp python deploy/contextforge/register.py --visibility team
```

The script POSTs `/v1/gateways` with the live schema's `authType`, `authToken`, `passthroughHeaders`
and `teamId` fields. It registers/updates the backend and compares discovered conversational tool
names and input-property names with the adapter. On drift it POSTs
`/v1/gateways/{id}/tools/refresh`, with a deactivate/activate fallback. It does **not** create a
virtual server or issue a voice-client token. Rerun after MCP schema changes; refresh the voice
agent's tool cache as well. Review full discovered schemas during acceptance, not just property names.

## 3. Platform owner: create the voice-facing virtual server

From `GET /v1/tools`, select the three tool IDs belonging to this registration:
`get_doctor_availability`, `manage_booking`, `search_knowledge`. Names may carry the registration
prefix. Verify their gateway association; do not select similarly named tools from another service.
Use the admin UI or this **1.0.11** REST request shape:

```http
POST /v1/servers
Authorization: Bearer <temporary-admin-JWT>
Content-Type: application/json

{
  "server": {
    "name": "healthcare-voice",
    "associated_tools": ["<availability-tool-id>", "<booking-tool-id>", "<knowledge-tool-id>"]
  },
  "team_id": "<existing-team-id>",
  "visibility": "team"
}
```

Save the returned server ID and issue a scoped, non-admin token authorized to use that team's
server. Give Rajiv the secure token reference and the resulting URL:

```text
https://mcp-gateway.icytree-6543aaa9.centralindia.azurecontainerapps.io/servers/<server-id>/mcp
```

That is the URL the voice agent registers as its MCP server. Confirm the deployed route using an
MCP initialize + tools/list request with the voice-client token. The platform supplies the existing
team choice, creates the virtual server and scopes its token; this repo supplies the upstream URL,
tool schemas, registration helper and header contract. No backend/database access is needed by the
gateway. Do not put `record_call_summary` in this conversational virtual server.

## 4. Joint acceptance before voice cutover

- Discover exactly the three tools through the scoped voice-client token; confirm another team or
  an unauthorized token cannot invoke them. Inspect complete input schemas and tool descriptions.
- Prove headers reach the adapter and stay isolated between simultaneous calls. Missing identity
  must be refused; the valid-identity LIST must actually reach Manoj, not merely avoid refusal.
- Test EN/KN/HI original turn text end to end. ContextForge documents a **4 KB header-value limit**;
  JSON + UTF-8 + base64 expansion can exceed it before our 4,000-character utterance limit. Test
  encoded byte sizes and explicit failure handling; never silently truncate the caller's words.
- Through the virtual server, complete routed availability, confirmed booking and knowledge
  journeys once owner inputs exist. Invoke call-end summary separately with its lifecycle bearer;
  verify retries/replay and UNKNOWN -> callback summary only.
- Measure gateway overhead and successful full voice responses from the deployed region under
  concurrency. The MCP in-call allocation is 0.30 s; the target is under one second to first caller
  audio. A timeout/refusal is not a successful response for latency acceptance.
- Keep legacy consumers and their resources until replacement calls pass. No cleanup of shared
  resources is part of registration.

References: [IBM header passthrough](https://ibm.github.io/mcp-context-forge/1.0.0-RC3/overview/passthrough/),
[IBM API usage](https://ibm.github.io/mcp-context-forge/manage/api-usage/),
[IBM MCP client URL examples](https://github.com/IBM/mcp-context-forge).
The request fields and version above were checked against this deployed instance's authenticated
OpenAPI, not inferred from a different release's examples.
