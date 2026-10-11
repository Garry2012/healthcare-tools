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

The three-tool source revision is not claimed deployed. It calls only Manoj.
The existing front-desk voice-facing virtual server is listed in the dated record above.
Stratum is a separate registration managed by its owners; this source change neither modifies
nor verifies its tools.

```text
Voice backend -- scoped gateway token + trusted headers --> ContextForge virtual server
             -- stored mcp-token + forwarded headers --> MCP canary --> Manoj
Voice backend -- separately owned tool access --> Stratum registration via ContextForge
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
and `teamId` fields. It registers/updates the backend and compares all three front-desk tool
names and complete input schemas with the adapter. On drift it POSTs
`/v1/gateways/{id}/tools/refresh`, with a deactivate/activate fallback. It does **not** create a
virtual server or issue a voice-client token. Rerun after MCP schema changes; refresh the voice
agent's tool cache as well. Review full discovered schemas during acceptance, not just property names.

## 3. Platform owner: refresh our existing front-desk virtual server

From `GET /v1/tools`, select the three IDs belonging to registration `frontdesk-healthcare-canary`:
`get_doctor_availability`, `manage_booking` and `record_call_summary`. Names carry our registration
prefix. Update the existing virtual server `frontdesk-healthcare` using the supported admin UI/API;
do not create a replacement server merely to refresh its tool selection. Remove only our retired
front-desk `search_knowledge` entry. Never remove or modify Stratum's registration or tools,
even if one has a similar name.

The voice client uses the existing server URL from the verified record above, with a scoped,
non-admin token authorized for its team/server. Share only the secure token reference with Rajeev.
Keep the upstream MCP bearer stored in gateway configuration, separate from the voice client token.
All three front-desk tools share that upstream bearer, including `record_call_summary`.

A combined view may contain our three front-desk tools plus Stratum's separately configured tools.
Its owner manages that composition; the adapter registration helper ignores other registration
prefixes. Do not compare the combined tool count to three.

## 4. Joint acceptance before voice cutover

- Gate 8, before deployment: Rajeev's team confirms and tests Stratum symptom/emergency journeys
  and transfer behaviour. This repository's tests do not verify Stratum.
- Gate 9: no live voice traffic until the adapter, our front-desk entries and LiveKit cached tool
  view are refreshed. Through the scoped voice-client path, the front-desk view must discover
  exactly the three front-desk tools; a combined view may additionally show Stratum's tools.
  Neither view may retain our front-desk `search_knowledge`. Stratum remains untouched.
- Confirm another team or unauthorized token cannot invoke our tools. Inspect complete input/output
  schemas and tool descriptions against `make schema` for source schema `2026-10-11.2`.
- Prove headers reach the adapter and stay isolated between simultaneous calls. Missing identity
  must be refused; the valid-identity LIST must actually reach Manoj, not merely avoid refusal.
- Scheduling requires no transcript header. Verify operation IDs are request-scoped through the local
  booking wrapper and the gateway; no shared-header mutation between concurrent requests.
- Through the virtual server, complete direct availability and caller-confirmed booking requests
  once owner inputs exist. Invoke the summary through the same virtual server;
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

After approved deployment, refresh discovered descriptions/input/output schemas for source schema `2026-10-11.2`.
The forwarding allowlist is exactly the five headers above; remove obsolete transcript and duration entries.
Refresh both input and output schemas and verify the voice client discovers the new summary result.
The published tool contract is [VOICE-TEAM.md](VOICE-TEAM.md); server metadata contains neutral tool facts. Voice prompts and behaviour belong to the consuming team.

Summary contract cutover: first accepted summary is final; changing it on a later call returns
ALREADY_SAVED without overwriting. The application supplies a complete whole-call text, not repeated
partial snapshots. The summary budget defaults to 8 seconds, separate from the scheduling allocation.
Rollback needs matching MCP image, gateway discovery and voice schema; the previous image expects
separate summary authentication. Do not reactivate it with only the new single-token configuration.
The 4 October deployment refreshed the existing registration; it did not rotate tokens or delete Key Vault secrets.

## Release 2026-10-11.2

Schema `2026-10-11.1` was deployed to the canary on 11 October 2026 (revision `--0000004`, image `28f11a8`); Garima reported on 12 October 2026 that our front-desk entries were refreshed; the canary then served
`2026-10-11.1` (three tools, no front-desk `search_knowledge`). `2026-10-11.2` changes description text only;
refresh our entries again after `2026-10-11.2` is deployed.
`2026-10-11.2` was deployed to the canary on 12 October 2026 (revision `--0000005`, image `01b9dcc`); the second refresh of our entries is pending.

The helper checks our three names and complete input schemas only; manually compare every
`outputSchema`, nested definition and required field through the voice-facing virtual-server URL
with `make schema`. A successful helper run alone is insufficient. Refresh the gateway and
LiveKit caches and record discovery evidence under gate 9. The five-header allowlist and access
scopes are unchanged. Keep image, gateway discovery and voice schema aligned on rollback.
The verified deployment section at the top is historical evidence, not evidence of this release.
