# Architecture

Current statement of the target: [docs/handover/mcp-only/TARGET-STATE.md](../handover/mcp-only/TARGET-STATE.md)
(ownership, boundaries, cleanup gates, latency measurements). This file records the adapter's own
design decisions (A-series); the owner services' designs are theirs.

## Shape

```
LiveKit voice agent ──MCP + trusted call headers──▶ ContextForge ──▶ frontdesk-mcp ──HTTPS──▶ Manoj's operational API
                                                 └──▶ Stratum (separate registration, voice-team owned)
```

## Decisions

| # | Decision | Why |
|---|---|---|
| A1 | One deployment per rollout; tenant identity (timezone, calling code, languages) has no default | A wrong default is a wrong hospital |
| A2 | Three task-level tools; directory, profile and board composed inside one availability call | Fewer model decisions, one round-trip budget |
| A3 | Trusted context in headers only; gateway authentication for all three tools | Model arguments are untrusted; client-side hiding is not authorization |
| A4 | Voice platform owns knowledge, symptom and emergency journeys through Stratum's separate registration; no knowledge client in this adapter | Gate 8 requires voice-team acceptance before deployment; gate 9 requires refreshed discovery before traffic |
| A5 | SL1 governs ordinary UNKNOWN callbacks, on-call confirmed evidence or handoff, and slot-aware requests; failed reads remain failures | User-fixed policy; failures are never "no availability" |
| A6 | NOTED, never confirmed; no slot, capacity or arrival computation | Slots and capacity come from the owner contract, never local allocation |
| A7 | Frozen booking body keyed by sha256(tenant\|call\|action\|operation); UNCERTAIN as a distinct outcome; one same-key retry within the deadline | Lost responses must not mint new intents |
| A8 | One deadline per invocation covering auth, every call and any retry; warm single-flight token cache; bounded directory cache; board never cached | Voice latency |
| A9 | Pinned owner contract (hash + quoting-only test overlay) and client-side types asserted by tests; development stubs outside the image; production refuses stub hosts | Contract drift and shadow backends fail loudly |
| A11 | LLM-called whole-call summary; exact text ≤500; first accepted call ID final; no header idempotency key | Owner contract deduplicates summaries by call ID; five honest outcomes; independent default 8 s deadline |
| A10 | Pinned tool schema snapshot and `SCHEMA_VERSION`; gateway names/input discovery verified automatically; output schemas checked manually after deployment | Gateway/voice caches are refreshed deliberately |

## Latency

Targets, boundaries and what was actually measured: [TARGET-STATE.md](../handover/mcp-only/TARGET-STATE.md)
and [implementation/LATENCY-RESULTS.md](../handover/mcp-only/implementation/LATENCY-RESULTS.md).

Schedule decisions live in `availability_policy.py` (pure). `schedule_reader.py` owns shared cached
profiles/departments and bounded batches. Services compose the reader, policy and response mapping.
Today never fills usual hours; future and WORKING_HOURS never read the live board. This is a mapping
of owner facts, not a slot allocator or a second scheduling backend.
