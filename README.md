# Front-desk MCP adapter — voice-agent tools for a hospital

Four MCP tools for a LiveKit voice agent, implemented as a thin adapter over two owner services.
This repository contains the adapter only; it owns no data and runs no backend.

```
Caller ⇄ LiveKit voice agent (STT, LLM, TTS)
             ⇅ MCP client (+ trusted call headers)
        IBM ContextForge gateway
             ⇅
        frontdesk-mcp (services/mcp): get_doctor_availability · manage_booking · search_knowledge
                                       record_call_summary (call-end lifecycle bearer only)
            /                       \
   HTTPS, machine OAuth              HTTPS, bearer
 Manoj's operational API           Shobhit's knowledge service
 (directory, live board,           (approved answers, symptom routing,
  appointments, summaries)          red flags) — contract pending
```

- **Plan, target and evidence:** `docs/handover/mcp-only/` (read its README first; implementation
  reports under `implementation/`).
- **Owner contract:** `docs/handover/mcp-only/contracts/manoj-openapi-20260930.yaml` (pinned, hashed).
- **Adapter:** `services/mcp/README.md`.
- **Integration:** `docs/handover/LIVEKIT.md` (headers and lifecycle the platform must send),
  `docs/handover/CONTEXTFORGE.md`, `docs/handover/AZURE.md`, `docs/handover/TESTING.md`.

## Five-minute start

Needs [uv](https://docs.astral.sh/uv/) 0.11+ and Python 3.13; Docker only for the compose stack and
the image build. No database.

```bash
uv sync --project services/mcp --frozen
./scripts/test.sh                 # lint, hermetic suites, process e2e, package/image build
make demo                         # walk the four tools against the development stubs
cp .env.example .env && make up   # adapter + stubs on 127.0.0.1:8100 / :8200 / :8300
```

Environments: `eval "$(scripts/env.sh mock)"` (public contract mock, integration tests) or `live` (Manoj's API,
blank until he supplies the base URL) — see `deploy/environments/README.md`. Deploy with
`deploy/azure/deploy.sh rollouts/demo-hospital --profile live --dry-run`. Register the adapter in ContextForge:
`cd services/mcp && uv run python ../../deploy/contextforge/register.py --dry-run`.

| Make target | What it does |
|---|---|
| `test`, `test-fast`, `test-e2e`, `lint` | see `scripts/test.sh` |
| `demo`, `bench`, `schema` | walk the tools, measure tool round trips, print the pinned tool surface |
| `up`, `up-mcp`, `down`, `logs`, `build` | compose stack (adapter + stubs / adapter only), production image |

## Layout

```
services/mcp/   src/frontdesk_mcp (adapter), dev/frontdesk_stubs (fixtures, never deployed), tests/
rollouts/       demo-hospital/rollout.env: tenant identity (timezone, calling code, languages)
deploy/         docker-compose.yml, environments/{mock,live}.env, azure/deploy.sh + smoke.py, contextforge/register.py
docs/           handover/mcp-only (plan, contracts, implementation evidence), handover/*.md, DECISIONS.md
```
