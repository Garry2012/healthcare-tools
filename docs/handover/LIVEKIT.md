# Connecting the LiveKit voice agent

```
caller ──SIP──▶ LiveKit ──▶ voice agent ──MCP (streamable HTTP)──▶ ContextForge ──▶ frontdesk-mcp ──▶ owner services
                                  │ headers on every MCP request (set in agent code, never by the model):
                                  │   Authorization: Bearer <gateway token>
                                  │   X-Call-Id: <stable call id, ≤64 chars [A-Za-z0-9._:-]>
                                  │   X-Caller-Number: <verified caller number, E.164, e.g. +919845012345>
                                  │   X-Caller-Verification: SIP_CALLER_ID | OTP | ...   (what the platform asserts)
                                  │   X-Turn-Context: base64url(JSON {"utterance": <caller's words this turn>, "language": "kn", "turnId": "..."})
                                  └─  X-Operation-Id: <stable id per confirmed write intent>
```

The agent gets three tools through the gateway bearer: `get_doctor_availability`, `manage_booking`,
`search_knowledge`. Their descriptions and the server instructions come from
`services/mcp/src/frontdesk_mcp/packs/healthcare.json` and `prompt.py`; the pinned surface is
`services/mcp/tests/contracts/mcp-tools.snapshot.json` (`frontdesk-mcp schema`).

## What the platform must supply (integration contract)

| Header | When | Why |
|---|---|---|
| `X-Call-Id` | every request | Correlation, call-bound write keys, summary identity |
| `X-Caller-Number`, `X-Caller-Verification` | every request when known | Authority to list/change appointments. The platform must state what it verified (`SIP_CALLER_ID`, `OTP`, …): a number without a verification header is unverified and gets IDENTITY_UNAVAILABLE |
| `X-Turn-Context` | every request | The caller's original words of the current turn, which the adapter forwards to the knowledge service for the required routing decision. Without it availability and CREATE return ROUTING_UNAVAILABLE |
| `X-Operation-Id` | every CREATE/CANCEL/RESCHEDULE | A stable logical id per confirmed intent. Retrying the same intent reuses it (replay); any changed payload under the same id, including a changed doctor or appointment, is refused as a conflict; a new intent gets a new id. Keep the mapping in the platform's call state |
| `X-Call-Started-At`, `X-Call-Duration-Seconds` | the call-end summary | Authoritative timing; never from the model |

Tool filtering in the LiveKit SDK (`MCPServerHTTP(..., allowed_tools=[...])`) is convenience; the
server enforces the split by bearer.

## Call-end lifecycle

When the call ends (including abrupt disconnect), the platform invokes `record_call_summary`
**once**, with the **lifecycle** bearer (`MCP_LIFECYCLE_BEARER_TOKEN`), `X-Call-Id`,
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
