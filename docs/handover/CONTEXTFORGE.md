# IBM ContextForge integration

## Verified deployment — 4 October 2026

The merged call-summary release is deployed to the existing canary. Registration
`frontdesk-healthcare-canary` and virtual server `frontdesk-healthcare` now expose all four tools,
including `record_call_summary`, under their existing team visibility. Five passthrough headers
are configured. Actual input/output schemas and descriptions match the adapter (schema `2026-10-04.2`).

Voice-facing URL:
`https://mcp-gateway.icytree-6543aaa9.centralindia.azurecontainerapps.io/servers/19d78ceb97994906b0c7f1990c7e3b58/mcp`

Admin-session discovery and a refused context-free summary call passed. Scoped voice-client
access and successful owner writes still require acceptance. Initial discovery omitted the new
summary output schema; an explicit gateway refresh populated it. Inspect output schemas too:
the registration helper's automatic comparison covers inputs only. See
[release evidence](mcp-only/implementation/CALL-SUMMARY-RELEASE.md).

## Historical inspection — 2 October 2026

An existing **ContextForge 1.0.11** instance is running in `healthcare-rg`. Authenticated inspection
found no registered backends or virtual servers. This review read its version and OpenAPI; it did
not register anything or change Azure settings. Do not provision a second gateway.

| Setting | Value |
|---|---|
| Gateway base | `https://mcp-gateway.icytree-6543aaa9.centralindia.azurecontainerapps.io` |
| Upstream MCP URL | `https://mcp-demo-hospital-canary.icytree-6543aaa9.centralindia.azurecontainerapps.io/mcp/` |
| Transport | `STREAMABLEHTTP` |
| Existing backend registration name (verified 4 October) | `frontdesk-healthcare-canary` |
| Upstream bearer | Current `mcp-token` in `kv-fd-demo-hospi-0574c1` |
| Existing admin access | Email from gateway `PLATFORM_ADMIN_EMAIL`; password reference `mcpgw-platform-admin-password` in that vault |

The 2 October inspection found no working knowledge host on the canary. In the revised adapter,
availability and booking depend on Manoj only; knowledge queries need the agreed knowledge host.
The revision in this branch is not claimed deployed. The gateway's actual
voice-facing URL is created in step 3 below, not the gateway base URL alone.

```text
Voice backend -- scoped gateway token + trusted headers --> ContextForge virtual server
             -- stored mcp-token + forwarded headers --> MCP canary --> Manoj / knowledge API
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
X-Operation-Id
X-Call-Started-At
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
uv run --project services/mcp python deploy/contextforge/register.py --name frontdesk-healthcare-canary --visibility team --dry-run
uv run --project services/mcp python deploy/contextforge/register.py --name frontdesk-healthcare-canary --visibility team
```

The script POSTs `/v1/gateways` with the live schema's `authType`, `authToken`, `passthroughHeaders`
and `teamId` fields. It registers/updates the backend and compares all four tool
names and complete input schemas with the adapter. On drift it POSTs
`/v1/gateways/{id}/tools/refresh`, with a deactivate/activate fallback. It does **not** create a
virtual server or issue a voice-client token. Rerun after MCP schema changes; refresh the voice
agent's tool cache as well. Review full discovered schemas during acceptance, not just property names.

## 3. Platform owner: create the voice-facing virtual server

From `GET /v1/tools`, select all four tool IDs belonging to this registration:
`get_doctor_availability`, `manage_booking`, `search_knowledge`, `record_call_summary`. Names may carry the registration
prefix. Verify their gateway association; do not select similarly named tools from another service.
Use the admin UI or this **1.0.11** REST request shape:

```http
POST /v1/servers
Authorization: Bearer <temporary-admin-JWT>
Content-Type: application/json

{
  "server": {
    "name": "healthcare-voice",
    "associated_tools": ["<availability-tool-id>", "<booking-tool-id>", "<knowledge-tool-id>", "<summary-tool-id>"]
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
gateway. The virtual server includes `record_call_summary` with the same upstream gateway bearer.

## 4. Joint acceptance before voice cutover

- Discover exactly four tools through the scoped voice-client token; confirm another team or
  an unauthorized token cannot invoke them. Inspect complete input schemas and tool descriptions.
- Prove headers reach the adapter and stay isolated between simultaneous calls. Missing identity
  must be refused; the valid-identity LIST must actually reach Manoj, not merely avoid refusal.
- Test EN/KN/HI question bodies end to end and fail explicitly on oversized questions; never truncate.
  Scheduling requires no transcript header. Verify operation IDs are request-scoped through the local
  booking wrapper and the gateway; no shared-header mutation between concurrent requests.
- Through the virtual server, complete direct availability, caller-confirmed booking requests and explicit knowledge
  journeys once owner inputs exist. Invoke the summary through the same virtual server;
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

After this change, refresh discovered descriptions/output schemas for schema `2026-10-04.2`.
The forwarding allowlist is exactly the five headers above; remove obsolete transcript and duration entries.
Refresh both input and output schemas and verify the voice client discovers the new summary result.
The published tool contract is [VOICE-TEAM.md](VOICE-TEAM.md); server metadata contains neutral tool facts. Voice prompts and behaviour belong to the consuming team.

Summary contract cutover: first accepted summary is final; changing it on a later call returns
ALREADY_SAVED without overwriting. The application supplies a complete whole-call text, not repeated
partial snapshots. The summary budget defaults to 8 seconds, separate from the scheduling allocation.
Rollback needs matching MCP image, gateway discovery and voice schema; the previous image expects
separate summary authentication. Do not reactivate it with only the new single-token configuration.
The 4 October deployment refreshed the existing registration; it did not rotate tokens or delete Key Vault secrets.

## Pending availability-policy release — 2026-10-05.1 (not deployed)

After separate deployment approval, rerun `register.py`. It checks exactly four names and complete
**input** schemas; the new purpose/date and doctor-only booking inputs trigger refresh. It does not
verify output schemas. No script, token, passthrough header or access-scope change is required.

Manual acceptance: run `make schema`, list tools via the voice-facing virtual-server URL, and compare
each tool's `outputSchema` (including nested definitions and required fields) to that generated JSON.
Confirm unchanged owner BoardSessionOut.status plus new decision/reason; removed journey/expired and
spoken callback fields; and booking sessions/outcomes. Record differences and refresh gateway discovery
until they match. Then refresh virtual-server/voice caches. An input-only script pass is insufficient.
Exercise General Medicine/Gynaecology today and future and Dr. Shreyas WORKING_HOURS; future queries
must use populated profiles without board reads. Measure actual voice-path latency separately.
Keep image, gateway discovery and voice schema aligned on rollback; 2026-10-04.2 and 2026-10-05.1
are not interchangeable consumer schemas. The verified deployment section above is historical evidence.
