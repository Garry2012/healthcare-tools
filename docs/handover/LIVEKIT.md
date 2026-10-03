# LiveKit integration: explicit tools and voice-owned emergency protection

Updated for schema `2026-10-03.2`. This is a design handover, **not an implemented or tested voice
worker**. This repository owns the four MCP tools, not the LiveKit application. SDK names below
were verified against the official docs and source on 3 October 2026; the voice owner must pin and
test their installed SDK. No deployment or real transfer is claimed here.

```text
Caller → STT → voice LLM → ContextForge virtual MCP server → our MCP
                 │        availability / booking / summary → Manoj
                 │        search_knowledge → knowledge owner (one request)
                 ├ local booking wrapper → safety barrier + per-write operation ID
                 ├ local note_callback → per-call state → shutdown summary
                 └ every-turn classifier / local transfer → voice platform
```

The LLM selects tools. Scheduling makes no knowledge request and receives no transcript header.
Symptoms can cause the LLM to select search_knowledge first, then availability with
`routing.department` as `departmentName`. The separate every-turn safety check belongs to the voice
platform, never inside an MCP scheduling tool.

## Instructions, discovery and startup

Run `PROVIDER_ID=<id> make agent-instructions` at the repository root and capture stdout as the
versioned instruction artifact. The checked-in [instructions](mcp-only/AGENT-INSTRUCTIONS.txt) are
for **demo-hospital** (en/kn/hi). Inject the whole block into `Agent(instructions=...)`, alongside
platform rules. Refresh the gateway's cached schema and tool descriptions when the version changes.
Keep the current date rule unchanged. Translate conversational callback wording into the selected
call language using voice-owner-approved wording; approved knowledge speech remains verbatim.

The LiveKit adapter imports name, description and input schema; do not rely on output-schema
comments, annotations or server initialization instructions reaching the LLM. Important behaviour
belongs in tool descriptions or the explicitly injected instruction block.
[Inspected adapter source](https://github.com/livekit/agents/blob/e684c2379e1c385afe8edcd1f02ea422051b035f/livekit-agents/livekit/agents/llm/mcp.py).

Before admitting a call, use the conversational credential to discover the three remote tools from
the ContextForge virtual server. Resolve their actual names (which may have gateway prefixes), check
schemas against the approved version, require all three and require summary to be inaccessible.
Save the discovered booking description and inputSchema for the local wrapper. Separately verify
lifecycle access in deployment tests. Do not give the lifecycle credential to the model.

**Leave manage_booking out of allowed_tools** on the LiveKit MCPToolset. Only availability and
search_knowledge go through the automatic adapter. Each call gets independent trusted headers and
client state. The following is wiring, with discovered names/configuration supplied by the platform:

```python
from livekit.agents import Agent, AgentSession, RunContext, function_tool, mcp

read_tools = mcp.MCPToolset(
    id="frontdesk",
    mcp_server=mcp.MCPServerHTTP(
        contextforge_virtual_server_url,
        transport_type="streamable_http",
        headers=trusted_per_call_headers,
        allowed_tools=[availability_name, knowledge_name],
    ),
    tool_options={
        availability_name: mcp.MCPToolOptions(on_duplicate="reject"),
        knowledge_name: mcp.MCPToolOptions(on_duplicate="reject"),
    },
)
await read_tools.setup()
assert {tool.info.name for tool in read_tools.tools} == {availability_name, knowledge_name}
```

The real startup check must catch connection/auth/schema errors, close partially opened clients and
send the caller to the platform's desk fallback before the conversational agent starts. An assert
alone is not that fallback. LiveKit logs a toolset setup failure and can continue without its tools;
therefore simply starting an Agent is insufficient. Close the toolset with the call's managed
lifecycle. [MCP toolsets](https://docs.livekit.io/agents/logic/tools/mcp/),
[async toolset lifecycle](https://docs.livekit.io/agents/logic/tools/async/).

## Local booking wrapper: operation IDs and the write barrier

Standard `MCPServerHTTP` has client-level headers, not a per-tool-call header hook. Mutating one
shared header dictionary races concurrent calls. Use the discovered schema without manually copying
its fields into a second schema:

```python
booking_schema = {
    "name": booking_name,
    "description": discovered_booking.description,
    "parameters": discovered_booking.inputSchema,
}

@function_tool(raw_schema=booking_schema, on_duplicate="reject")
async def manage_booking(raw_arguments: dict[str, object], context: RunContext):
    return await context.userdata.booking_dispatch(raw_arguments, context)
```

`booking_dispatch` is a **platform function to implement**, not a LiveKit API. Keep it inside the
local manage_booking wrapper's dispatch path, with these responsibilities:

1. LIST uses trusted verified caller context; it needs no write operation ID or write safety barrier.
   CREATE/CANCEL/RESCHEDULE require the caller's confirmed intent. Obtain identity and confirmation
   state from per-call platform state, never from model-invented headers or IDs.
2. Under a per-call write lock, snapshot the current conversation version and confirmed intent; await
   the safety decision for that version **and pending earlier turns**. Recheck the version,
   confirmation and sticky escalation state after every await. A newer turn invalidates the old
   authorization; a safe result cannot overwrite an earlier emergency. Apply the agreed outage
   policy, never silently approve a write on classifier error/timeout.
3. Freeze the confirmed payload and mint one operation ID. Retain that ID and payload on retries;
   mint another only for a genuinely new confirmed intent. `on_duplicate="reject"` rejects
   concurrent duplicates by tool name; it does not deduplicate completed intents or retries.
4. Immediately before dispatch, recheck safety/version and mark the intent as dispatching without
   an intervening await. After transport dispatch begins, cancellation or connection loss may mean
   a committed write: keep the operation ID, record the uncertainty and reconcile/retry the same
   payload under the existing MCP rules. Interrupting speech cannot undo a dispatched write.

A concrete request mechanism is a **dedicated initialized MCP client per confirmed intent** using
FastMCP's `Client(StreamableHttpTransport(virtual_server_url, headers=...))`, with immutable trusted
call headers plus that intent's `X-Operation-Id`. Call the discovered booking tool name with the frozen
payload. Retain/close clients through the call's async lifecycle; retry the same intent with the same
headers. Do not send a bare REST POST that bypasses MCP initialization/session handling. This works
without assuming the gateway is stateless. Pre-initialize the intent channel during read-back if
possible; initialization sends no booking write. Bound retained clients, close finished ones, and
measure the added initialization cost in the voice path. Verify per-request header forwarding and
session isolation against the installed gateway before release. This repository already uses that
FastMCP client/transport in `deploy/azure/smoke.py`; the voice application must pin its own dependency.

Use `AgentSession(userdata=call_state)` and expose the local wrapper with the two read tools, not a
second remote booking tool. [Raw-schema functions and RunContext](https://docs.livekit.io/agents/logic/tools/definition/).

## Callback capture and call-end finalization

When availability returns CALLBACK_REQUIRED/UNKNOWN, retain its authoritative requestedDate and
chosen doctor identifier in per-call state before returning the tool result to the model. A
`MCPServerHTTP(tool_result_resolver=...)` can observe the successful MCP result; validate its structured
content and test that the gateway preserves it. Do not parse spoken text or accept a model-invented
replacement date/doctor. If several doctors remain unresolved, preserve that uncertainty.

The local booking_dispatch must also capture CALLBACK_REQUIRED before returning it to the LLM:
CREATE or RESCHEDULE can discover UNKNOWN on a fresh board check after availability was IN. These
results do not carry requestedDate/doctor fields. Use frozen confirmed visitDate for CREATE or
newVisitDate for RESCHEDULE; resolve doctor identity only from that confirmed selection or the prior
verified LIST result. Keep an unresolved doctor unspecified. Initialize the same callback state;
the read-tool result resolver does not see calls made through the local booking wrapper.

Expose a local tool whose only persistence is session.userdata:

```python
@function_tool
async def note_callback(name: str, number: str, context: RunContext):
    """Save the caller's stated name and dictated callback number after callback is required."""
    return context.userdata.capture_callback(name=name, number=number)
```

`capture_callback` is platform code: require an active UNKNOWN callback state, validate the supplied
name/number, attach the stored requestedDate/doctor, and store the record through `context.userdata`
(the session's userdata). Do not substitute caller ID for the dictated number. Say the hospital will
call back; perform no booking, transfer, alternative search or other action because of UNKNOWN.
`note_callback` is a voice-local tool, **not a fifth MCP tool**.

Register a call finalizer with the verified job lifecycle API:

```python
async def finalize_call():
    await call_state.finalize_to_outbox()

ctx.add_shutdown_callback(finalize_call)
```

`finalize_to_outbox` is platform code. Freeze the summary once (CALLBACK_NOTED with requestedDate
when callback details were captured), durably enqueue it in the platform's **durable outbox**, then
call record_call_summary using lifecycle-only access and authoritative timing headers. Handle
abrupt disconnects and repeated finalizer invocation without changing the payload. DONE stops;
RETRY_SAME_PAYLOAD retries the exact payload with backoff outside the turn; RECORD_FAILED alerts
operations; FIX_PLATFORM_INPUT requires correction. Job shutdown has a finite timeout and cannot
survive a worker crash: use the platform's persisted call lifecycle and retry worker as well. MCP
contains no database or retry queue. [Job shutdown callbacks](https://docs.livekit.io/agents/server/job/).

## Every-turn safety and local transfer

Use `Agent.on_user_turn_completed(self, turn_ctx, new_message)` to start and retain the per-turn
classifier task over the caller's original words (`new_message.text_content`) and agreed context.
Awaiting it in the hook blocks the reply. If it runs in the background, the barrier **inside the local
manage_booking wrapper** must await the relevant task before any write. A background task alone is
not a barrier. Supervise tasks, deadlines and failures; cancel/drain on close. Associate decisions
with conversation versions and keep escalation sticky. The provider's classifier schema, language
coverage and outage policy remain owner agreements, not an assumed use of the MCP answer endpoint.
[Turn-completion hook](https://docs.livekit.io/agents/logic/nodes/).

Expose a local transfer tool and use the same platform transfer path for classifier emergencies:

```python
@function_tool(on_duplicate="reject")
async def transfer(destination: str, context: RunContext):
    """Transfer to an allowed desk or emergency destination when instructed."""
    context.userdata.begin_escalation(destination)
    await context.session.interrupt(force=True)
    return await context.userdata.perform_transfer(destination)
```

`begin_escalation` and `perform_transfer` are platform functions. Validate against configured logical
destinations (never arbitrary model-provided telephone/SIP addresses); set escalation before any
await, block new writes, then execute the actual verified telephony handoff. If handoff fails, keep
escalation set and execute the agreed fallback. Only report successful transfer after the real effect.
`interrupt(force=True)` handles speech that disallows ordinary interruption; it does not transfer a
call or roll back a booking. Use it only while the session is running; startup failures use the
platform's pre-agent fallback. [AgentSession source](https://github.com/livekit/agents/blob/e684c2379e1c385afe8edcd1f02ea422051b035f/livekit-agents/livekit/agents/voice/agent_session.py).

Realtime models need agent-side turn detection for the hook. Test the actual audio path, overlapping
turns and preemptive generation; text-only testing is not proof of audio protection.
[Turn controls](https://docs.livekit.io/agents/logic/turns/).

## Trusted identity and gateway boundary

| Header | Source and use |
|---|---|
| Authorization | Scoped voice credential to ContextForge; gateway uses its distinct upstream MCP bearer. No admin token or incoming-bearer passthrough. |
| X-Call-Id | Platform call identity, at most 64 allowed identifier characters. |
| X-Caller-Number + X-Caller-Verification | Platform verification for LIST/CANCEL/RESCHEDULE; a bare number authorizes nothing. |
| X-Operation-Id | Wrapper-owned stable confirmed-write identity, never an LLM argument. |
| X-Call-Started-At + X-Call-Duration-Seconds | Platform lifecycle timing for summary, not model arguments. |

Gateway owner supplies the virtual MCP URL, scoped access and tested header allowlist. The previously
used direct canary URL was `https://mcp-demo-hospital-canary.icytree-6543aaa9.centralindia.azurecontainerapps.io/mcp/`;
its current deployment/schema has **not** been verified in this correction pass. The lifecycle path
uses separate access (`mcp-lifecycle-token`), outside the LLM-visible conversational tool list.

## Voice-repository acceptance tests and latency

Use the actual SDK session harness and boundary HTTP fixtures for wiring; use the selected real model
for tool choice and multilingual utterances. Assert wire effects and emitted speech, not only state:

- Startup auth/connection/schema failure routes to the desk; only two remote reads and one local
  booking wrapper are exposed; summary is hidden. Generated instructions are injected explicitly.
- Two calls and concurrent write attempts retain isolated caller headers and per-intent IDs;
  same-intent retries reuse the ID and body; a new confirmed intent gets a fresh ID.
- Routine doctor lookup needs no MCP knowledge call. Symptoms select knowledge then availability
  with departmentName. Clarification asks answer.text; routing speaks routing.speak once.
- Danger signs, including Kannada/Hindi/mixed speech, trigger forced interruption and a real transfer.
  Earlier unresolved danger followed by “yes”, a stale safe result, slow/failed classifier and turn
  changes while waiting cannot release a write. Once sent, uncertainty is preserved.
- Availability IN followed by CREATE/RESCHEDULE UNKNOWN still initializes callback state and records
  only the summary, with the confirmed requested date and no invented doctor.
- UNKNOWN captures dictated callback details into userdata and finalizes only a summary; missing
  details prompt collection. Abrupt disconnect and worker restart use the outbox; lifecycle credentials
  never enter tools or logs. NOTED never becomes “confirmed”.
- Transfer failure, duplicate tools, canceled tools and shutdown leave no orphan tasks or false success.

These are required voice-owner tests, **not tests run here**.
[Testing guidance](https://docs.livekit.io/testing/unit-tests/),
[tool design](https://docs.livekit.io/agents/logic/tools/design/).

The adapter default is 300 ms (1.0 s end-to-end minus 0.65 s other stages and 0.05 s gateway). Preserve
parallel profile/board reads and live-board rechecks; summaries occur after the call. Removing a
previously overlapping knowledge request removes coupling, not necessarily a whole latency stage.
Measure caller-audio p50/p95/p99, useful outcomes and failures through ContextForge with real providers,
including channel initialization and the safety barrier. Fixture timings do not prove this budget.

Until voice protection is implemented, scheduling relies on model judgement, injected instructions
and explicit knowledge calls for emergency handling. The user's architectural approval does not
claim Shobhit/voice-team agreement or clinical acceptance of that interim risk. Those agreements,
real voice tests and latency measurements remain release work.
