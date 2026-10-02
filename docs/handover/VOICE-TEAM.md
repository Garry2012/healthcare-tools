# Voice AI team — integration handover

Updated 1 October 2026 for the MCP-only adapter. Environment: **synthetic healthcare demo** in
`healthcare-rg` (Central India). Shared-resource boundaries below are unchanged.

## Shared resources: reuse with these boundaries

| Resource | Existing name / address | Allowed use |
| --- | --- | --- |
| Container Apps environment | `cae-frontdesk-demo-hospital` | Deploy your own apps here. Do not recreate it or change shared networking. |
| Container Registry | `acrfd399536.azurecr.io` | Push your images to your own repositories. |
| Key Vault | `kv-fd-demo-hospi-0574c1` | Add secrets prefixed `voice-`, `livekit-`, `twilio-`, `whatsapp-`, `contextforge-`. Read `mcp-token` (gateway bearer) and, for the call-end finalizer only, `mcp-lifecycle-token`. |
| PostgreSQL 16 | `pg-fd-demo-hospital-0574c1` | Your own databases (`voice_agent`, `voice_cis`) with their own logins. The `frontdesk` database belongs to the retired backend and is scheduled for retirement; do not add consumers. |
| Log Analytics | `law-frontdesk-demo-hospital` | Reuse for logs. |

## MCP connection contract

```text
Channel integrations → Voice AI Agent → [ContextForge] → frontdesk-mcp → Manoj's API / Shobhit's service

Transport: Streamable HTTP
URL: https://mcp-<provider>.<environment domain>/mcp/
Authorization: Bearer <Key Vault: mcp-token>            (three in-call tools)
Authorization: Bearer <Key Vault: mcp-lifecycle-token>  (record_call_summary at call end only)
Headers: X-Call-Id, X-Caller-Number, X-Caller-Verification, X-Operation-Id,
         X-Call-Started-At, X-Call-Duration-Seconds   (LIVEKIT.md)
```

- Supply headers in agent/channel code, never from LLM tool arguments. Keep them isolated per call.
- Tools: `get_doctor_availability`, `manage_booking`, `search_knowledge`; `record_call_summary` from
  the call-end lifecycle only.
- **Required change on your side:** `HEALTHCARE_TOOLS_BINDINGS_JSON` on `voice-api`/`voice-worker`
  currently binds directly to the legacy `api-demo-hospital` REST API with agent/staff tokens. That
  API is being retired; appointments and summaries must go through MCP (one appointment authority:
  Manoj's service). Remove the direct REST binding and forward the headers above.
- Prior Manoj/canary evidence is historical; this routing-removal revision is not deployed or voice-path verified. Test the complete path with designated synthetic data before rollout.
- Implement the every-turn emergency guardrail and explicit agent instructions in [LIVEKIT.md](LIVEKIT.md). Scheduling no longer contacts knowledge.

Further integration details: [LIVEKIT.md](LIVEKIT.md), [CONTEXTFORGE.md](CONTEXTFORGE.md).
