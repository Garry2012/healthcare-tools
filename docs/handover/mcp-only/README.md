# MCP-only implementation handover

Updated 11 October 2026: the source exposes three front-desk tools over Manoj's operational API.
It contains no operational backend, database or knowledge implementation. The voice team owns
knowledge, symptom routing and emergency decisions through Stratum's separate ContextForge registration.
The three-tool removal was approved in review on 11 October 2026; source completion is not deployment or live acceptance.

## Current integration contract

[VOICE-TEAM.md](../VOICE-TEAM.md) defines the three tools: `get_doctor_availability`,
`manage_booking` and `record_call_summary`. Source schema is `2026-10-11.1`.
Voice prompts, behaviour, guardrails and SDK wiring belong to the voice team.

Current availability and booking policy is DECISIONS.md SL1. Today uses the live board; selected-doctor
AVAILABILITY also consumes owner slots. Department matching uses cached capabilities without slot
fan-out. WORKING_HOURS reads no board or slots. Ordinary UNKNOWN in scope means callback-only metadata;
on-call follows SL1's confirmed usable evidence or handoff. A successful appointment request is NOTED.
Caller authorization, frozen booking intent, uncertainty and whole-call summary semantics are unchanged.
Summary values for symptoms and emergencies remain valid.

## Read in this order

1. [TARGET-STATE.md](TARGET-STATE.md): ownership and performance boundaries.
2. [PLAN.md](PLAN.md): current release gates, three-tool REST mapping and labelled migration history.
3. [Contract provenance](contracts/README.md) and [Manoj's pinned contract](contracts/manoj-openapi-20261007.yaml).
4. [VOICE-TEAM.md](../VOICE-TEAM.md), [CONTEXTFORGE.md](../CONTEXTFORGE.md),
   [AZURE.md](../AZURE.md) and [TESTING.md](../TESTING.md): current integration and operating instructions.

[CURRENT-STATE.md](CURRENT-STATE.md), [OPUS-REVIEW.md](OPUS-REVIEW.md), the original Fable assignment
and dated implementation reports preserve historical evidence; they are not current deployment inventories.
The committed removal plan and LOG-1 revision 6 specified this change; its implementation was approved in review on 11 October 2026.
Gate 8 requires Rajeev's Stratum symptom/emergency and transfer acceptance before deployment.
Gate 9 prevents voice traffic until our adapter and gateway/voice discovery are refreshed.
A combined voice view may include Stratum; its registration and tools are outside this repository's scope.

## Review and build on another laptop

Clone the repository and check out the agreed review commit. Use Python 3.13 and uv 0.11+.
Mandatory checks need no owner source or database:

```bash
./scripts/test.sh          # frozen install, lint, hermetic suites, process e2e, package + images
make demo                  # walk the three tools against the operational development stub
```

Read-only smoke and owner write journeys require separately approved environments and credentials.
Fixture timings do not prove the one-second useful-audio target; real voice measurements belong
to the platform team. Source review, merge, deployment, gateway refresh and cloud cleanup are
separate approvals, governed by [PLAN.md](PLAN.md).

## Handover validation on 1 October 2026

- A checkout made exclusively from staged Git files, with no private workspace artifacts, passed frozen MCP dependency installation, source/wheel package builds and all 35 database-free MCP tests (16 end-to-end tests deselected).
- `make test-fast` passed: lint, all nine architecture import contracts, 413 API unit/contract tests and 35 MCP tests.
- Handover links resolve to tracked files/directories. The public contract checksum matches, and the original Opus review body is preserved unchanged.
- These checks validate the existing package and portable handover. They do not exercise Manoj's real service, prove the latency target, or clear the legacy end-to-end failure below. No local database or deployment was started for this handover.

## Historical starting limitations — 1 October 2026

- **Existing main CI is failing.** At source baseline `7e20b4459d0a58422bf3b5ba40a670be94b758f5`, [CI run 36571571806](https://github.com/Garry2012/healthcare-tools/actions/runs/36571571806) failed `test_mcp_offers_every_bookable_position_of_a_session`: the old tool omitted 4 of 7 bookable positions. It reported 50 other MCP tests passing. This predates the handover and is not concealed by changing tests or CI. The migration must preserve complete results or explicitly report incompleteness, although old slot semantics will be retired.
- The pinned Manoj spec has known schema defects. Preserve the original; prefer an owner correction, or the plan's labelled quoting-only test overlay. No overlay or new stub implementation is supplied in this documentation change.
- Shobhit's endpoint/schema/auth contract has not been supplied. Proposed fixture behavior must remain labelled provisional.
- Real service hosts, machine credentials/scopes, caller-verification agreements, replay/board details, gateway access controls and actual latency measurements remain external dependencies. Credentials are obtained securely, never committed. The public mock does not prove a live working backend.
- No database migration, deployment, cloud cleanup or external service write is part of publishing this handover. Historical data handoff and resource retirement need owner coordination later.

This dated record describes the migration baseline, not current service readiness or release acceptance.
