# Owner integration messages — 2 October 2026

Copyable messages for the user to send. These have not been sent to any team. Credentials already
work; no new client ID or secret is requested. Never share secret values in chat.

## Manoj — call summaries

> The existing MCP client authenticates successfully, but its token has only `appointments.write`.
> Please grant that registered client `calls.write` as well, so a fresh `/api/v1/auth/token` token
> authorizes `POST /api/v1/call-summaries`; that route currently returns 403. Keep the existing
> client ID/secret in `kv-fd-demo-hospi-0574c1` unchanged unless rotation is necessary.

This is a backend client/scope permission change, not creating another vault secret. We can read
credentials and rerun verification ourselves after the grant; we cannot grant an owner-service
permission using this runtime client's existing scope. Confirm summary replay/idempotency semantics
in the contract when enabling the route.

## Manoj — synthetic booking test data

> `/availability` currently returns UNKNOWN for the doctor/date combinations we inspected, so there
> is no usable known availability for a positive booking test. Please confirm `jayashree` is safe for
> synthetic writes (or provide a dedicated synthetic tenant/client), and prepare fresh IN boards for
> Dr. V Shreyas Kumar (`30b5941b-1e7a-43cb-b994-eb8b47729736`) on two consecutive future dates,
> with a session covering 10:00, plus a separate UNKNOWN date; send the dates and session windows.

The journey creates on the first date, reschedules to the next day, cancels, and stores/replays its
summary. This is not a request for slot inventory. Boards must satisfy the contract's freshness and
end-time rules at test time. The MCP client lacks staff `availability.write`; the owner/staff service
should prepare these rows. We will not modify Manoj's database or guess that a tenant is synthetic.

## Shobhit — knowledge and routing

> Please share readiness, versioned OpenAPI, HTTPS test URL and secure auth reference for a single knowledge request returning an answer, no answer, clarification, department, desk or emergency decision. Our question/language consumer proposal is in knowledge_contract.py; please confirm it or supply your own contract, EN/KN/HI fixtures and latency evidence.

The provisional `/v1/answer` is a consumer proposal, not an imposed API. The voice platform separately needs an every-turn emergency classifier contract, covering conversation context, stale results, outages and transfer destinations. Scheduling tools do not call knowledge. Set the agreed provider URL once in `deploy/environments/live.env`; keep its bearer in Key Vault. The 300 ms tool allocation and one-second voice target still require real-path measurements.

## Rajiv — voice integration

> Connect the voice backend to the healthcare virtual-server MCP URL issued by the existing IBM
> ContextForge gateway, using a scoped voice-client token. Forward trusted per-call/per-operation headers
> (`X-Call-Id`, caller number + verification, stable operation ID); the platform
> must set them, not the LLM. At call end, invoke `record_call_summary` directly on the MCP canary with
> the separate `mcp-lifecycle-token`, timing headers and a durable retry queue. UNKNOWN availability
> means collect name/number and save a callback summary only. Follow the linked integration contracts
> and validate a full call before removing the voice services' old REST binding.

- [MCP interface and trusted headers](VOICE-TEAM.md)
- [Gateway URLs, setup and credential separation](CONTEXTFORGE.md)
- Conversation tools: `get_doctor_availability`, `manage_booking`, `search_knowledge`.
- Call-end URL: `https://mcp-demo-hospital-canary.icytree-6543aaa9.centralindia.azurecontainerapps.io/mcp/`.
- The platform handles confirmations, immutable retry payloads and stable IDs. A lost write response
  is UNCERTAIN, not a confirmed failure; do not issue a fresh booking with a new operation ID.
- Test simultaneous calls and per-write operation headers through the local booking wrapper. Pass EN/KN/HI
  caller words in the explicit knowledge question body, never a transcript header; never truncate them.

## Rajiv — expose Stratum without moving its implementation here

> Stratum can remain on its VM. Please expose a versioned HTTPS JSON API reachable from our MCP
> environment, with Swagger/OpenAPI, an agreed machine-auth method and a vault credential reference.
> Accept a question, language and agreed tenant/domain context; return approved answer text with
> source/document version and explicit no-answer/clarification outcomes. Publish a health endpoint,
> example responses, timeouts and latency measurements. We consume that interface only; we do not
> need Stratum's code, database, SSH access or a Docker conversion.

Read-only inventory found `ds-staging-stratum` in `DS-STAGING-RG`, East US 2; MCP and the gateway are
in Central India. Measure this cross-region hop against the 300 ms total tool budget. Agree regional
serving or owner-managed caching if needed; do not add unmeasured sequential calls to the voice path.

**Provider relationship to agree:** today MCP has one knowledge-service base URL, not two independently
wired knowledge providers. Recommended first integration: Stratum supplies retrieval behind Shobhit's
knowledge API, which continues to own clinical routing and red flags. If Stratum instead needs direct
MCP access as a second provider, define selection and response contracts first, then implement and test
that explicit adapter change. Merely adding a second URL does not implement provider selection.

## Gateway/platform operator — registration instructions

> Use the existing ContextForge 1.0.11 instance in `healthcare-rg`; do not create another gateway.
> Register the canary MCP URL over Streamable HTTP with vault `mcp-token`, enable the listed trusted
> headers, and create a team-scoped virtual server exposing only the three conversational tools.
> Give Rajiv its `/servers/<server-id>/mcp` URL and a secure reference to a scoped voice-client token.
> Keep the lifecycle token out of that registration. Follow the exact commands, REST payload and
> acceptance checks in [CONTEXTFORGE.md](CONTEXTFORGE.md).

We already have access to inspect the gateway and can perform its configuration/registration when
that deployment task is assigned. The platform owner supplies the intended team/access scope. No
new external service or backend credential is needed to start discovery; full voice acceptance still
requires the owner services and the voice integration. This pass prepared code/instructions only:
no registration, deployment, Azure deletion or live appointment/summary write was performed.
