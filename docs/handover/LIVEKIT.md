# LiveKit integration: explicit tools and voice-owned emergency protection

Updated for schema `2026-10-02.1`. This is an integration handover, not an implemented voice agent.
This repository contains no LiveKit worker. The runtime changes here have not been deployed.

```text
Caller → STT → voice agent LLM → ContextForge virtual MCP server → our MCP
                   │                    availability/booking/summary → Manoj
                   │                    search_knowledge → knowledge owner (one request)
                   └ every-turn emergency classifier → knowledge owner
```

The LLM selects `get_doctor_availability`, `manage_booking` or `search_knowledge`. Scheduling makes
no knowledge request and receives no transcript header. When symptoms need a department, select
knowledge first, then availability with the returned department. An ordinary named-doctor MCP lookup
makes zero knowledge requests; the separate voice safety classifier still runs on every turn.

## Explicit instructions and MCP wiring

Run `make agent-instructions` at the repository root. The generated versioned artifact is
[mcp-only/AGENT-INSTRUCTIONS.txt](mcp-only/AGENT-INSTRUCTIONS.txt). Paste its entire content into the
voice agent's `instructions`, alongside the platform's own conversation rules. Regenerate whenever
the schema version changes, and refresh ContextForge's cached tools/descriptions/output schemas.

Current LiveKit source calls `await client.initialize()` without retaining its returned instructions:
[SDK source inspected 2 October](https://github.com/livekit/agents/blob/e684c2379e1c385afe8edcd1f02ea422051b035f/livekit-agents/livekit/agents/llm/mcp.py).
Do not rely on MCP server instructions automatically reaching the model. ContextForge forwarding of
those instructions is not verified; explicit Agent instructions work independently of that question.

Current documented Python wiring (verify against the voice team's installed SDK; this repo does not
install it):

```python
from livekit.agents import Agent, mcp

agent = Agent(
    instructions=versioned_frontdesk_instructions,
    tools=[mcp.MCPToolset(
        id="frontdesk",
        mcp_server=mcp.MCPServerHTTP(
            contextforge_virtual_server_url,
            transport_type="streamable_http",
            headers=trusted_per_call_headers,
            allowed_tools=registered_conversational_names,
        ),
    )],
)
```

Use the actual three tool names discovered from the virtual server (ContextForge may prefix them).
Keep `record_call_summary` out of that list. Each call owns its MCP client/header state; never mutate
a shared client dictionary to change caller identity or a write's operation ID. The platform must
supply the operation ID on the specific write request with a request-scoped transport mechanism,
verified against its SDK/gateway version; this snippet alone does not implement that mechanism.

[Current MCP docs](https://docs.livekit.io/agents/logic/tools/mcp/) describe `MCPToolset`, server-level
`allowed_tools`, and explicit streamable HTTP transport. The brief's wording was checked against these docs.

## Trusted context and lifecycle

| Header | Purpose |
|---|---|
| Authorization | Scoped voice credential to ContextForge; gateway uses its separate upstream MCP bearer. Never forward the incoming authorization as the upstream bearer. |
| X-Call-Id | Stable call identity, at most 64 allowed identifier characters. |
| X-Caller-Number + X-Caller-Verification | Verified caller authority for LIST/CANCEL/RESCHEDULE; a bare number authorizes nothing. |
| X-Operation-Id | Stable per confirmed write intent; retain on identical retry. Changed payload under the same ID conflicts. |
| X-Call-Started-At + X-Call-Duration-Seconds | Authoritative lifecycle timing, not model arguments. |

At call end, including abrupt disconnect, the platform durably finalizes the call using the lifecycle
bearer (`mcp-lifecycle-token` in Key Vault), separate from conversational access. The current canary
endpoint is `https://mcp-demo-hospital-canary.icytree-6543aaa9.centralindia.azurecontainerapps.io/mcp/`;
verify its deployed schema before cutover. The gateway's actual virtual server URL/token come from
its owner; do not substitute an admin token.

For UNKNOWN: collect caller name and dictated callback number, say the hospital will call back,
then finalize `CALLBACK_NOTED` with `requestedDate`; no appointment, transfer, alternative or task.
Freeze the summary payload once. `DONE` ends retries; `RETRY_SAME_PAYLOAD` reuses exactly that payload
with backoff outside the turn; `RECORD_FAILED` alerts operations; `FIX_PLATFORM_INPUT` requires correction.
Do not derive the dictated callback number from caller ID. MCP owns no durable retry queue.

## Every-turn guardrail: voice team's implementation contract

Use `Agent.on_user_turn_completed(self, turn_ctx, new_message)` to start the classifier alongside
ordinary reply generation. Pass original caller words (`new_message.text_content`) and whatever
conversation context the owner contract requires. The classifier's host/schema/outage policy are
still to be agreed with Shobhit or the selected provider; do not reuse the provisional MCP answer
endpoint as if it were an agreed classifier API.

[Hook documentation](https://docs.livekit.io/agents/logic/nodes/) confirms that it runs before the reply;
awaiting remote classification inside the hook delays the reply. Retain and supervise background tasks
in per-call state; give them deadlines, handle errors explicitly, and cancel/drain them on call close.
Associate each decision with the conversation version it examined. A stale safe result must not clear
a newer turn, and an emergency result must not be discarded merely because a later turn arrived.
Persist an escalation state until the platform resolves it.

On an emergency, stop routine speech with `session.interrupt()` and execute the platform's real,
verified transfer workflow. Interrupting speech neither rolls back an already dispatched write nor
proves a telephone transfer happened. Before dispatching CREATE/CANCEL/RESCHEDULE, the voice platform
must resolve all relevant pending safety decisions and check that escalation has not started. That
write barrier belongs in platform code, not in another MCP service call or an LLM-provided flag.
Its timeout/outage handling and transfer destination require the voice/clinical owner's agreement.
A write already sent follows MCP's UNCERTAIN/replay rules; do not cancel it and report definite failure.

For realtime models, the hook requires agent-side turn detection. Check actual audio and text input
paths; a text test alone does not prove the audio hook fires. Test preemptive generation and parallel
tool calls explicitly. [Turn controls](https://docs.livekit.io/agents/logic/turns/),
[tool design](https://docs.livekit.io/agents/logic/tools/design/).

## Acceptance tests in the voice repository

Use the real SDK session harness with a scripted provider for wiring, boundary HTTP fixtures for
owner responses, and ordinary-language tests with the chosen real model for tool selection. Assert
emitted tool calls/arguments, transfer effects and no further unintended actions; do not mock the
safety logic or pretend a private state update is a caller turn.

- Routine named-doctor question: availability only from the LLM, no MCP knowledge call; background classifier still runs.
- Named doctor plus danger sign, including Kannada/Hindi/mixed language: interrupt and actually transfer; no booking write.
- Symptoms without a department: knowledge first, then availability with the approved department; no invented department.
- Earlier dangerous symptoms followed by “yes”: prior unresolved/escalated safety state prevents writes.
- Slow, failed or malformed classifier; stale safe result; overlapping turns; call closes during classification:
  apply agreed failure policy, keep callers isolated and leave no orphan tasks.
- Guardrail/write race: no write before safety resolves; if already sent, preserve uncertain-write semantics.
- UNKNOWN: name/number and summary only. NOTED never spoken as confirmed/booked. UNCERTAIN never retried as a new intent.
- Gateway identity isolation, per-operation ID delivery, separate lifecycle access and durable summary retry.

These voice tests are required handover work, not tests claimed to run in this repository.
[LiveKit testing guidance](https://docs.livekit.io/testing/unit-tests/).

## Latency and release

The adapter's default in-call deadline is 300 ms: 1.0 s total budget − 0.65 s other stages − 0.05 s
gateway allowance. Summaries run after the call. Removing knowledge from scheduling removes a failure
dependency; the previous calls overlapped, so no whole-hop latency saving is promised. Preserve the
live-board recheck before CREATE/RESCHEDULE. Measure useful caller audio p50/p95/p99 and failures under
load through ContextForge; fixture timings and deadline enforcement are not production latency proof.

Before the voice guardrail is live, emergency handling relies on model judgement, explicit instructions
and whichever knowledge calls the model selects. The user approved the architectural separation;
Shobhit/voice-team agreement and user/clinical-owner acceptance of the interim risk remain outstanding
before merge/cutover. This handover does not claim their consent or implementation.
