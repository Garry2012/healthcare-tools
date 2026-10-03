# Decisions

Architecture decisions for the adapter are the A-series in `docs/architecture/TARGET.md`; the
migration decisions are in `docs/handover/mcp-only/PLAN.md`. This file records library choices.
The D-series of the retired backend (FastAPI/SQLAlchemy/Alembic, resolver, slot uniqueness) is in Git
history before the MCP-only migration (October 2026) and no longer applies.

## Libraries

| Library (pinned) | Used for | Why this one | Fallback |
|---|---|---|---|
| fastmcp 2.14.7, mcp 1.30.0 | MCP server: tools, middleware (lifecycle gate), streamable HTTP | Matches the deployed stack; tags + middleware give a server-side access boundary | The `mcp` SDK's FastMCP directly |
| starlette 1.7.0, uvicorn 0.53.0 | ASGI assembly (/health, /ready, /dependencies, bearer middleware) | FastMCP's own base | — |
| httpx 0.28.1 | Pooled async clients to both owner services; MockTransport/ASGITransport at the boundary in tests | Explicit timeouts, per-request deadline caps, transport injection | aiohttp |
| pydantic 2.13.5, pydantic-settings 2.15.0 | Contract types, result envelopes, settings with production guards | Shared with FastMCP; output schemas come from the models | — |
| pytest 9.1.1, pytest-asyncio 1.4.0, pyyaml 6.0.3, jsonschema 4.26.0, ruff 0.16.9 (dev) | Tests (contract overlay parsing, stub responses validated against the OpenAPI schemas), lint | Standard | — |

Not adopted: an OpenAPI client generator (the public interface is small and the types double as
validation), a database or queue in the adapter (the platform owns durable finalization), any
NLP/interpretation library (deferred; owners decide meaning).

## K1 — Explicit knowledge tool; scheduling depends only on Manoj (2 October 2026)

Context: a routine availability call could fail before reading usable operational data because a
transcript header or the separate knowledge provider was missing. MCP sees tool calls, not every
conversation turn, so that gate did not provide conversation-wide emergency protection.

Decision: the user approved removal of all knowledge gates from availability and booking, including
optional checks on booking reasons. The LLM chooses search_knowledge for hospital questions and
symptom-to-department queries. That tool makes one owner request with verbatim question and language.
reasonVerbatim remains an optional operational payload field; it is not interpreted here. Scheduling
works with knowledge unconfigured. No local knowledge fallback or classifier is added.

Rejected alternatives: keep the mandatory gate (coupled outages and incomplete turn coverage), move
transcripts through headers (wrong layer and mutable-client/concurrency risk), or hide the gate behind
a feature flag/optional reason check (two paths and the same service coupling).

Consequences: remove obsolete context/client/fixture paths together; version tool descriptions and
schemas. Trusted identity, confirmation, live-board UNKNOWN handling, idempotency and uncertain-write
reporting remain adapter invariants. The knowledge contract remains provisional until owner acceptance.
MCP does not observe every conversation turn; voice behaviour and application acceptance are external
responsibilities, now explicitly separated by K2 below.

### K1 correction review — 3 October 2026

The single-request knowledge boundary now validates the decision before optional metadata. A valid
emergency/desk transfer survives malformed optional fields; those fields are dropped with a
field-name-only event. Other malformed responses fail explicitly. Require JSON and bounded owner strings.
Routing speech appears only in routing.speak, while answers and clarification use answer.text; the
tool contract describes the result codes. Current schema is 2026-10-03.3; date validation is unchanged.

Scheduling-only configuration means both knowledge URL and bearer are empty; partial production
configuration is rejected. Deployment supplies its expected knowledge state to smoke and removes an
obsolete app secret reference only after removing the environment reference. These paths have offline
tests; no cloud change was performed in the correction pass.

## K2 — MCP publishes only the tool contract (3 October 2026)

Decision: MCP publishes only the tool contract: endpoint/transport, authentication scopes, trusted
headers, parameters, output fields and outcome/nextStep meanings. The single interface document is
[VOICE-TEAM.md](handover/VOICE-TEAM.md), checked against the pinned schema. The server retains short,
neutral contract metadata, not conversational rules.

Voice-agent behaviour, prompts, guardrails and LiveKit wiring belong to the voice team. The separate
voice-design document and instruction-export command are retired. This supersedes K1's earlier
voice-guidance deliverable; it does not reintroduce knowledge checks inside scheduling.

Tool implementations, field names, validation, status mappings and response defaults stay compatible,
including existing callback text fields. Date accepts today or YYYY-MM-DD; other relative dates remain
unsupported. This text change does not decide future date interpretation. Clinical/application design,
voice implementation and their acceptance remain outside this repository; no owner consent or deployed
behaviour is asserted by publishing this contract.
