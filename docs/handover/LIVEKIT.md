# Connecting the LiveKit voice agent

```
caller ──SIP──▶ LiveKit ──▶ voice agent ──MCP (streamable HTTP)──▶ ContextForge ──▶ frontdesk-mcp ──▶ owner services
                                  │ headers on every MCP request (set in agent code, never by the model):
                                  │   Authorization: Bearer <scoped voice-client token issued by ContextForge>
                                  │   X-Call-Id: <stable call id, ≤64 chars [A-Za-z0-9._:-]>
                                  │   X-Caller-Number: <verified caller number, E.164, e.g. +919845012345>
                                  │   X-Caller-Verification: SIP_CALLER_ID | OTP | ...   (what the platform asserts)
                                  │   X-Turn-Context: base64url(JSON {"utterance": <caller's words this turn>, "language": "kn", "turnId": "..."})
                                  └─  X-Operation-Id: <stable id per confirmed write intent>
```

The agent gets three tools through its ContextForge virtual-server URL: `get_doctor_availability`, `manage_booking`,
`search_knowledge`. Their descriptions and the server instructions come from
`services/mcp/src/frontdesk_mcp/packs/healthcare.json` and `prompt.py`; the pinned surface is
`services/mcp/tests/contracts/mcp-tools.snapshot.json` (`frontdesk-mcp schema`).

ContextForge stores a different credential (`mcp-token`) for its upstream connection to our canary.
Never forward the voice-client Authorization header to MCP. See [ContextForge setup](CONTEXTFORGE.md)
for the actual hosts, registration, virtual-server creation and token separation. Use a scoped voice
credential, not an administrator token. The platform's trusted headers must be refreshed per call
and turn; avoid shared mutable client headers that can mix concurrent callers.

The adapter's 4,000-character turn limit does not guarantee transport acceptance: JSON, UTF-8 and
base64 increase the header size, while ContextForge documents a 4 KB header-value cap. Validate
encoded sizes and multilingual delivery through the real gateway; handle rejection explicitly and
never truncate or treat missing context as routing clearance.

## What the platform must supply (integration contract)

| Header | When | Why |
|---|---|---|
| `X-Call-Id` | every request | Correlation, call-bound write keys, summary identity |
| `X-Caller-Number`, `X-Caller-Verification` | every request when known | Authority to list/change appointments. The platform must state what it verified (`SIP_CALLER_ID`, `OTP`, …): a number without a verification header is unverified and gets IDENTITY_UNAVAILABLE |
| `X-Turn-Context` | every request | The caller's original words of the current turn (≤ 4,000 characters, never truncated by the adapter: an oversized or malformed value is refused with ROUTING_UNAVAILABLE), forwarded to the knowledge service for the required routing decision before any availability result, create or knowledge answer. Without it those tools return ROUTING_UNAVAILABLE |
| `X-Operation-Id` | every CREATE/CANCEL/RESCHEDULE | A stable logical id per confirmed intent. Retrying the same intent reuses it (replay); any changed payload under the same id, including a changed doctor or appointment, is refused as a conflict; a new intent gets a new id. Keep the mapping in the platform's call state |
| `X-Call-Started-At`, `X-Call-Duration-Seconds` | the call-end summary | Authoritative timing; never from the model |

Tool filtering in the LiveKit SDK (`MCPServerHTTP(..., allowed_tools=[...])`) is convenience; the
server enforces the split by bearer.

## Call-end lifecycle

When the call ends (including abrupt disconnect), the platform invokes `record_call_summary`
**once per logical call**, with retries of the identical payload when necessary. Connect directly to
`https://mcp-demo-hospital-canary.icytree-6543aaa9.centralindia.azurecontainerapps.io/mcp/`,
using the **lifecycle** bearer from Key Vault `mcp-lifecycle-token` (`MCP_LIFECYCLE_BEARER_TOKEN`), `X-Call-Id`,
`X-Call-Started-At` and `X-Call-Duration-Seconds`, and the summary fields it decided from the call
record: `intent`, `outcome`, `summaryText`, optional `callerName`, `callerMobile` (only when the
caller gave it), `language`, `doctorId`, `appointmentId`, `transferredTo`. For the UNKNOWN callback
flow: `outcome=CALLBACK_NOTED`, `callerName`, `callerMobile`, context in `summaryText`, no
`appointmentId`/`transferredTo`, plus `requestedDate` so the date survives the 500-character limit.
Build the payload once and resend it unchanged on retry. Act on `nextStep`: `DONE` (`STORED`/`REPLAYED`),
`RETRY_SAME_PAYLOAD` (`UNCERTAIN`, or `COULD_NOT_RECORD` for a transient owner failure, honouring
`retryAfterSeconds`), `RECORD_FAILED` (credential problem: alert operations, keep the payload),
`FIX_PLATFORM_INPUT` (`INVALID_REQUEST`/`REJECTED`/`CONFLICT`: the platform's inputs are wrong). The
platform owns the finalization queue and retries; the adapter is stateless. Call summaries are outside
the voice response budget.

## Sessions and the create

`get_doctor_availability` returns board sessions per doctor. When a doctor has several sessions that day,
pass the chosen one as `session` on `manage_booking` CREATE (or a `preferredTime` inside its window); the
adapter re-reads the live board for the visit date with the same scope rule as availability and refuses an
UNKNOWN (or missing) session with the callback-only outcome; a preferred time outside the chosen session's window
is rejected. The same check runs for a RESCHEDULE on the new date.

## Latency budget the adapter enforces

The adapter derives its read deadline from `VOICE_RESPONSE_BUDGET_SECONDS` (1.0) minus
`RESERVED_STAGE_SECONDS` (0.65 for endpointing/STT, model tool choice, model answer, TTS start and headroom) minus
`GATEWAY_OVERHEAD_SECONDS` (0.05): 0.30 s for every in-call tool, reads and confirmed writes alike. A tool
that cannot finish inside that returns COULD_NOT_CHECK / UNCERTAIN promptly rather than holding the turn. These are design
allocations to validate on the real path; diagnostic overrides (`READ_DEADLINE_SECONDS`, …) are explicit.

## Conversation rules the agent follows

The server instructions carry them (`prompt.CORE_RULES`): explicit dates only; board status over
usual hours; NOTED is not confirmed; CALLBACK_REQUIRED → ask name and callback number, say someone
will call back, nothing else; read back and confirm before any write; UNCERTAIN → say so and
transfer; IDENTITY_UNAVAILABLE → desk; ROUTING_REQUIRED → follow nextStep and speak routing.speak
verbatim; failures → "could not check right now", never "no one is available"; approved answers
spoken verbatim. Test tool selection and wording with the chosen model before cutover.

## Status

Not yet tested on a live call. Everything above is verified through the adapter's HTTP and MCP
interfaces against stubs and process-level e2e. The deployed voice platform (voice-api/voice-worker)
currently binds to the legacy REST API directly and does not yet forward `X-Turn-Context`,
`X-Caller-Verification`, `X-Operation-Id` or the lifecycle headers: see
`mcp-only/implementation/OPEN-DEPENDENCIES.md`.
