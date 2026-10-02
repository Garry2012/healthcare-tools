# Target ownership, cleanup and voice performance

Confirmed 1 October 2026. This document strengthens the [implementation plan](PLAN.md) following the user's handover review. It specifies the required future state; the migration and Azure cleanup have not been executed.

## Architecture and ownership

The current wiring is voice agent → ContextForge → our MCP server → our REST API → PostgreSQL. The API implementation and database setup are in this repository today. The target is:

```mermaid
flowchart TB
  P[Caller] <--> V[LiveKit voice agent: speech recognition, LLM, speech synthesis]
  V <-->|MCP tool calls and results| G[IBM ContextForge gateway]
  G <--> M[Our MCP server: four tools, thin integration code]
  M <-->|HTTPS: published operational contract| O[Manoj service: his code, Docker image and Azure resources]
  M <-->|HTTPS: published knowledge contract| K[Shobhit service: his code, Docker image and Azure resources]
  O <--> OD[Manoj-owned storage]
  K <--> KD[Shobhit-owned storage]
```

The LLM chooses a tool and arguments; the LiveKit runtime/MCP client executes the request through the gateway. Results return along that path for the voice agent to speak. The call-end lifecycle invokes `record_call_summary` separately from ordinary conversational model selection. The four tools remain `get_doctor_availability`, `manage_booking`, `search_knowledge`, and `record_call_summary`.

**External service dependencies remain; external implementation dependencies must not.** Calling their APIs requires available services, configured URLs and credentials. It must never require their source checkout, database access, migrations, server image, internal Python packages or implementation SDKs. Each owner supplies a versioned Swagger/OpenAPI interface as the integration authority. Required behavior, errors, auth/scopes and replay semantics must be documented there or in explicitly referenced contract documentation; an endpoint list alone does not establish those guarantees.

| Belongs here | Stays outside this repository |
|---|---|
| Our MCP tool definitions, descriptions, input/output validation and small HTTP adapters | Manoj's REST route handlers, booking/scheduling/name/date engines and database models |
| Pinned owner contracts, client-side request/response types, consumer tests and synthetic fixtures | Shobhit's retrieval pipeline, embeddings, vector store, documents, classifiers and clinical rules |
| Authentication, trusted call-context forwarding, deadlines, safe replay handling and honest error mapping | Either team's source repository, Docker image build, deployment or database administration |
| Bounded in-memory caches of allowed directory/profile data and tokens | Operational data persistence, database/Redis requirements, a local booking ledger or knowledge fallback |
| MCP Dockerfile, CI, deployment, gateway registration and relevant observability | Provisioning either owner's cloud resources or retaining a hidden old backend for production fallback |

Generated client types are acceptable if they represent the public interface only. Do not generate server scaffolding. Development stubs are contract fixtures excluded from production, not an alternative scheduling or knowledge implementation. A developer can install, build and run mandatory MCP tests without either owner's source or database. Live integration needs their designated test service or labelled fixture servers.

MCP remains model-independent: there is no second LLM, agent loop, embedding call, database query or local interpretation/retrieval engine inside it. Its small orchestration layer combines the contracted facts needed for one caller request. Only search_knowledge forwards its verbatim question to the knowledge owner. Availability and booking call only Manoj. The voice platform owns every-turn emergency detection, including safety state before dispatching a write.

## Cleanup is part of completion

Code removal alone does not finish this migration. Follow the [Azure inventory and retirement requirements](AZURE-RETIREMENT.md) as well as the plan's source retirement inventory.

Completion requires:

1. External integrations pass consumer and real-service checks; exactly four intended tools are registered with correct lifecycle access.
2. The old backend source, dependency declarations, database/migration/seed tooling, active legacy setup instructions and automation are removed or explicitly historical as appropriate. No active fallback or import can reach them.
3. A clean checkout builds and runs mandatory tests/CI without the old API, database or private workspace files. Required suites must not silently skip. Current legacy defects must have relevant consumer coverage after the old slot semantics are retired.
4. Obsolete Azure API apps/revisions, backend jobs, images, database assets, credentials and access grants are retired after cutover and any required data handoff. Shared resources retain a named owner and purpose, or are separated before removal. Delete an obsolete resource group only after every contained resource is retired or relocated.
5. The final resource inventory identifies what was deleted, what remains and why. Verify the MCP/voice path after cleanup, absence of obsolete references/jobs, applicable retained-data expiry and residual billing. A retention obligation has an owner and expiry; it must not become an undocumented permanent legacy service.
6. Voice performance and failure behavior pass the measured gates below. A successful Docker build alone is insufficient.

The user's requirement includes future cloud cleanup. This documentation update performs only read-only Azure inspection, not deletion or database modification. Before destructive execution, resolve ownership/data retention and prepare the exact scoped retirement list; never infer safe deletion from a resource name.

## Tools designed for conversational models

The [MCP tools specification](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) describes model-controlled tools with names, descriptions, input schemas and optional output schemas. Apply that interface to caller tasks:

- Keep the four task-level tools instead of exposing every REST operation as a separate model decision. Compose directory/profile/board reads inside one availability invocation. Genuine ambiguity still requires caller clarification.
- Give each tool a concise, distinct purpose and explicit prerequisites. Use precise fields/enums, validated action-dependent booking inputs and structured, compact results. Preserve important status, ambiguity, completeness and available next steps; do not dump raw API responses or silently truncate results.
- Keep trusted identity, credentials and operation IDs out of model-writable arguments. Write actions require confirmed caller intent. Correctly describe read/write behavior; a mixed-action `manage_booking` tool cannot be marked universally read-only. Metadata hints do not replace authorization or backend replay guarantees.
- Keep conversational access to the three in-call tools; invoke the fourth from authenticated call finalization. LiveKit documents tool filtering, but the deployed SDK/gateway version and server-side lifecycle access must both be verified. Client-side hiding alone is not authorization.
- Initialize connections/tool discovery before conversation where possible. Refresh schemas when the tool version changes, not on every turn. Do not download Swagger or generate clients during a tool call.
- Test model selection, arguments, concise responses, failure/ambiguity handling and caller interruptions with the chosen model. The protocol is portable; equal tool-use quality across models is not assumed.

LiveKit's [MCP integration documentation](https://docs.livekit.io/agents/logic/tools/mcp/) covers tool exposure/filtering and execution. Pin and test the actual SDK version; examples from current docs are not evidence that the existing deployment already supports them.

## Two different latency measurements

| Measurement | Boundary | Planning target |
|---|---|---|
| Tool round trip | Agent dispatches tool → gateway → MCP → owner service(s) → result back to agent | Aim around 250 ms: the existing plan allocates 70 ms to gateway/MCP/transport and 180 ms to downstream critical path. Sub-500 ms alone does not prove the caller target. |
| Customer response | Caller finishes speaking → first useful answer is audible to that caller | Proposed p95 ≤1,000 ms under agreed load; a useful sub-500 ms response is desirable but not currently demonstrated. Includes speech endpointing, model/tool selection, tool round trip, response generation, TTS and media delivery. |

These are engineering targets, not measured guarantees or MCP protocol requirements. Use the remaining turn budget to set a single deadline across auth, pool wait, downstream calls and any retry. Do not give each REST call a separate 500 ms allowance. Count timeout/failure rates separately so fast failure is not presented as successful low-latency service. Filler such as “Let me check” is not the useful-answer measurement.

To keep the adapter thin and fast:

- Reuse async HTTP connections and warm tokens; bound request/response sizes and fan-out. Cache only permitted stable directory/profile data, not current board truth or stale knowledge answers.
- Overlap independent Manoj reads. Once the doctor is resolved, profile and board can run together. An appointment write requires caller confirmation and a current board check. Search-dependent reads cannot all be called parallel by assumption.
- Keep the gateway, MCP and owner services close enough in network terms to meet the measured budget. Bound cold-start delays with the chosen hosting setup; include cold starts in reporting.
- Keep summaries and durable retry work after the call in platform infrastructure. Do not add a database/queue backend to MCP or retry long writes during speech turns. Cancelling a local request does not prove a remote appointment was undone.
- Measure the gateway separately and trace the entire LiveKit path. Owner API latency and any knowledge-service LLM work count against the same response budget. If either service is too slow, negotiate placement/contract performance with its owner; do not copy its implementation into MCP or invent local interpretation.

Run an early real-host latency experiment before completing the migration. Report p50/p95/p99 and failure rates under declared concurrency, cold/warm tokens and English/Kannada/Hindi scenarios. Include at least known-doctor hours+board, name search, ambiguity, appointment write, knowledge routing, outage and lost-write-response cases. The [LiveKit observability guidance](https://docs.livekit.io/testing/observability/data/) provides turn/component timings; [audio simulations](https://docs.livekit.io/testing/simulations/) distinguish generated-audio timing from what the caller actually hears. Verify actual useful audio at the caller, including tool follow-up turns, rather than relying on an incomplete sum of component timings.

The 2 October routing-removal decision is in DECISIONS.md. Until the voice guardrail is implemented, model judgement and explicit instructions are the scheduling emergency protection. Owner agreement and residual-risk acceptance remain release requirements.
