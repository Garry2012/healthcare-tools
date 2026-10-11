# Target ownership, cleanup and voice performance

Updated 11 October 2026 for the three-tool ownership decision K3. This document defines the [implementation plan](PLAN.md)'s target boundaries, not evidence of deployment or cloud cleanup.

## Architecture and ownership

The source migration removed the repository-owned REST API and database implementation. The contract-only ownership boundary is:

```mermaid
flowchart TB
  P[Caller] <--> V[LiveKit voice agent: speech recognition, LLM, speech synthesis]
  V <-->|MCP tool calls and results| G[IBM ContextForge gateway]
  G <--> M[Our MCP server: three tools, thin integration code]
  M <-->|HTTPS: published operational contract| O[Manoj service: his code, Docker image and Azure resources]
  G <--> K[Stratum: separate registration owned by the voice team]
  O <--> OD[Manoj-owned storage]
  K <--> KD[Stratum-owned storage]
```

The LLM chooses a tool and arguments; the LiveKit runtime/MCP client executes the request through the gateway. Results return along that path for the voice agent to speak. The LLM can select `record_call_summary` through the same authenticated gateway as the other tools. Our three tools are `get_doctor_availability`, `manage_booking` and `record_call_summary`. A combined gateway view may also contain Stratum's tools, managed separately by its owners.

**External service dependencies remain; external implementation dependencies must not.** Calling Manoj's API requires an available service, configured URL and credentials. Stratum integrates with the voice platform through its own registration, not through this adapter. It must never require their source checkout, database access, migrations, server image, internal Python packages or implementation SDKs. Each owner supplies a versioned Swagger/OpenAPI interface as the integration authority. Required behavior, errors, auth/scopes and replay semantics must be documented there or in explicitly referenced contract documentation; an endpoint list alone does not establish those guarantees.

| Belongs here | Stays outside this repository |
|---|---|
| Our MCP tool definitions, descriptions, input/output validation and small HTTP adapters | Manoj's REST route handlers, booking/scheduling/name/date engines and database models |
| Pinned owner contracts, client-side request/response types, consumer tests and synthetic fixtures | Stratum's retrieval pipeline, embeddings, vector store, documents, classifiers and clinical rules |
| Authentication, trusted call-context forwarding, deadlines, safe replay handling and honest error mapping | Either team's source repository, Docker image build, deployment or database administration |
| Bounded in-memory caches of allowed directory/profile data and tokens | Operational data persistence, database/Redis requirements, a local booking ledger or knowledge fallback |
| MCP Dockerfile, CI, deployment, gateway registration and relevant observability | Provisioning either owner's cloud resources or retaining a hidden old backend for production fallback |

Generated client types are acceptable if they represent the public interface only. Do not generate server scaffolding. Development stubs are contract fixtures excluded from production, not an alternative scheduling or knowledge implementation. A developer can install, build and run mandatory MCP tests without either owner's source or database. Live integration needs their designated test service or labelled fixture servers.

MCP remains model-independent: there is no second LLM, agent loop, embedding call, database query or local interpretation/retrieval engine inside it. Its small orchestration layer combines the contracted facts needed for one caller request. All three front-desk tools call only Manoj. Knowledge, symptom and emergency journeys belong to the voice platform through Stratum. Voice-agent behaviour, prompts, guardrails and SDK wiring are owned by the voice team.

## Cleanup is part of completion

Code removal alone does not finish this migration. Follow the [Azure inventory and retirement requirements](AZURE-RETIREMENT.md) as well as the plan's source retirement inventory.

Completion requires:

1. External integrations pass consumer and real-service checks; exactly three front-desk tools are registered with gateway authentication. A combined voice view may additionally include Stratum's separately owned tools.
2. The old backend source, dependency declarations, database/migration/seed tooling, active legacy setup instructions and automation are removed or explicitly historical as appropriate. No active fallback or import can reach them.
3. A clean checkout builds and runs mandatory tests/CI without the old API, database or private workspace files. Required suites must not silently skip. Current legacy defects must have relevant consumer coverage after the old slot semantics are retired.
4. Obsolete Azure API apps/revisions, backend jobs, images, database assets, credentials and access grants are retired after cutover and any required data handoff. Shared resources retain a named owner and purpose, or are separated before removal. Delete an obsolete resource group only after every contained resource is retired or relocated.
5. The final resource inventory identifies what was deleted, what remains and why. Verify the MCP/voice path after cleanup, absence of obsolete references/jobs, applicable retained-data expiry and residual billing. A retention obligation has an owner and expiry; it must not become an undocumented permanent legacy service.
6. Voice performance and failure behavior pass the measured gates below. A successful Docker build alone is insufficient.

The user's requirement includes future cloud cleanup. This source change performs no Azure inspection, deletion or database modification. Before destructive execution, resolve ownership/data retention and prepare the exact scoped retirement list; never infer safe deletion from a resource name.

## Tool contract boundary

[VOICE-TEAM.md](../VOICE-TEAM.md) is the consumer interface: three tools, purpose and applicability,
parameter formats and conditional requirements, output fields, outcome/nextStep meanings, transport,
authentication and trusted headers. Its field tables are tested against the pinned MCP schema.

The adapter retains input validation, confirmed-write requirements, trusted identity and gateway authorization,
compact structured results, idempotency and error semantics. Descriptions and server metadata contain
facts only. Prompt design, spoken wording, guardrails, tool-selection strategy and LiveKit integration
are outside this repository. MCP carries no model-specific client or application implementation.

## Two different latency measurements

| Measurement | Boundary | Planning target |
|---|---|---|
| Tool round trip | Agent dispatches tool → gateway → MCP → owner service(s) → result back to agent | Aim around 250 ms: the existing plan allocates 70 ms to gateway/MCP/transport and 180 ms to downstream critical path. Sub-500 ms alone does not prove the caller target. |
| Customer response | Caller finishes speaking → first useful answer is audible to that caller | Proposed p95 ≤1,000 ms under agreed load; a useful sub-500 ms response is desirable but not currently demonstrated. Includes speech endpointing, model/tool selection, tool round trip, response generation, TTS and media delivery. |

These are engineering targets, not measured guarantees or MCP protocol requirements. Use the remaining turn budget to set a single deadline across auth, pool wait, downstream calls and any retry. Do not give each REST call a separate 500 ms allowance. Count timeout/failure rates separately so fast failure is not presented as successful low-latency service. Filler such as “Let me check” is not the useful-answer measurement.

To keep the adapter thin and fast:

- Reuse async HTTP connections and warm tokens; bound request/response sizes and fan-out. Cache only permitted stable directory/profile data, never current board or slot facts.
- Overlap independent Manoj reads. Once the doctor is resolved, profile and board can run together. An appointment write requires caller confirmation and the shared schedule decision: fresh board for today, usual profile schedule for a future date. Search-dependent reads cannot all be called parallel by assumption.
- Keep the gateway, MCP and owner services close enough in network terms to meet the measured budget. Bound cold-start delays with the chosen hosting setup; include cold starts in reporting.
- Summaries have a separate default 8-second deadline and may be selected by the LLM; their timing is the voice application's responsibility. Durable retries belong to platform infrastructure; no database/queue backend belongs in MCP. Cancelling a local request does not prove a remote appointment was undone.
- Measure the gateway separately and trace the entire LiveKit path. Owner API latency counts against the same response budget. If the owner service is too slow, negotiate placement/contract performance with its owner; do not copy its implementation into MCP or invent local interpretation.

Real-host MCP measurements still require declared concurrency, cold/warm token state and useful
outcomes/failure rates. End-to-end audio measurement belongs to the voice platform. Publishing a tool
contract or passing fixture tests does not establish application safety or the caller-response target.

## Current availability policy and release ordering

SL1 in [DECISIONS.md](../../DECISIONS.md) governs scheduling. Selected-doctor AVAILABILITY reads
slots alongside the applicable profile and today-only live board; owner `enabled` selects slot policy.
Department availability uses cached capabilities without per-doctor slots fan-out. WORKING_HOURS
reads no board or slots. Ordinary UNKNOWN in scope gives callback metadata; on-call uses confirmed
usable evidence or handoff. Failed reads are failures, never unavailable facts. No capacity is computed.

The three-tool source schema is `2026-10-11.2`. Gate 8 (Rajeev's team validating Stratum
symptom/emergency journeys and transfers before deployment) was approved by Garima on 11 October 2026. Gate 9 prohibits live voice traffic
until the adapter, our front-desk gateway entries and LiveKit cached tool view are refreshed and
voice-client discovery proves exactly three front-desk tools. Combined views may also include Stratum.
Our source change does not modify or verify Stratum's registration. Review, merge, deployment,
gateway refresh and leftover cloud-setting/secret cleanup require separate approval.
