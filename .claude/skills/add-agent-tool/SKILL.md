---
name: add-agent-tool
description: Add or change a voice-agent tool end to end (spec, API Agent operation, MCP tool, every domain pack, registration, tests, latency budget). Use when a new capability must be exposed to the LiveKit voice agent.
---
# Add a voice-agent tool

Work in this order; each step has a check that must pass before the next.

1. **Spec** — add the `Agent`-tagged operation to `docs/frontdesk-api/openapi.yaml` with an
   `x-mcp` block, request/response schemas, RULE/WHY comments, and an entry in `x-mcp-tools`
   (`inputs_from_context: [X-Call-Id, X-Caller-Number]`). Update the "N tools / N operations"
   wording in `info` and the `Agent` tag.
2. **API** — schemas in `schemas.py` (class names = component names), a pure function in
   `domain/` if there is logic, the service in `services/`, the route in `routers/agent.py`.
   Failures return an outcome (`COULD_NOT_CHECK`), never an empty success. Run
   `tests/contract/test_openapi_matches_spec.py`.
3. **Latency** — reads on the voice path go through a `VersionedCache` where the data is
   read-mostly; writers call `cache.bump`. Add the call to `tests/integration/test_latency_budget.py`
   with a round-trip ceiling, and a scenario to `scripts/bench.py`.
4. **MCP** — the wrapper in `services/mcp/src/frontdesk_mcp/tools.py` (no domain rules; identity
   headers from `call_context`, never parameters; writes get `_keyed` idempotency). Add the
   tool's description and parameter wording to **every** `packs/*.json`, and add it to the
   required set in `register()`. A rule every agent follows whatever the domain goes in
   `prompt.CORE_RULES`, never into the packs (a test fails if a pack repeats a core rule).
5. **Gateway** — add the tool to `TOOLS` in `deploy/contextforge/register.py`.
6. **Tests** — unit (domain), integration (HTTP, scopes, red flags first if it reads caller
   words), MCP unit (tool listed, no header params leak), MCP e2e.
7. `./scripts/test.sh` must end with `== all suites passed`. Then update
   `services/mcp/README.md` and `docs/handover/README-API.md`.
