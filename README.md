# Front-desk MCP adapter — voice-agent tools for a hospital

Three MCP tools for calling applications, implemented as a thin adapter over Manoj's operational API.
This repository contains the adapter only; it owns no data and runs no backend.

```
Caller ⇄ LiveKit voice agent (STT, LLM, TTS)
             ⇅ MCP client (+ trusted call headers)
        IBM ContextForge gateway
             ⇅                                      ⇅ separate registration
        frontdesk-mcp (services/mcp)               Stratum (voice-team owned)
        get_doctor_availability · manage_booking
        record_call_summary (same gateway bearer)
             ⇅ HTTPS, machine OAuth
        Manoj's operational API
        (directory, live board, slots, appointments, summaries)
```

- **Plan, target and evidence:** `docs/handover/mcp-only/` (read its README first; implementation
  reports under `implementation/`).
- **Owner contract:** `docs/handover/mcp-only/contracts/manoj-openapi-20261007.yaml` (pinned, hashed).
- **Adapter:** `services/mcp/README.md`.
- **Integration:** `docs/handover/VOICE-TEAM.md` (tool interface, authentication and trusted headers),
  `docs/handover/CONTEXTFORGE.md`, `docs/handover/AZURE.md`, `docs/handover/TESTING.md`.

## Five-minute start

Needs [uv](https://docs.astral.sh/uv/) 0.11+ and Python 3.13; Docker only for the compose stack and
the image build. No database.

```bash
uv sync --project services/mcp --frozen
./scripts/test.sh                 # lint, hermetic suites, process e2e, package/image build
make demo                         # walk the three tools against the operational stub
cp .env.example .env && make up   # adapter + operational stub on 127.0.0.1:8100 / :8200
```

Environments: `eval "$(scripts/env.sh mock)"` (public contract mock, integration tests) or `live` (Manoj's API,
configured in the live profile) — see `deploy/environments/README.md`. Deploy with
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

All three front-desk tools call only Manoj. The voice agent uses Stratum through a separate ContextForge registration for knowledge, symptom and emergency journeys.
Voice behaviour and prompts belong to the voice team; the published interface is [VOICE-TEAM.md](docs/handover/VOICE-TEAM.md).

Availability policy: today uses Manoj's live board; future dates use usual working hours, with attendance
unconfirmed. `purpose=WORKING_HOURS` allows an omitted date; AVAILABILITY requires today or an explicit
future date and a doctor/department target. CREATE requires a doctor. The approved revision 6 plan and
implementation evidence are in `docs/handover/mcp-only/implementation/`.
