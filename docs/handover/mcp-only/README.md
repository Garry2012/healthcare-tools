# MCP-only implementation handover

Published 1 October 2026; implementation delivered the same day on branch `Garry2012/mcp-external-api`.

> **Implementation status:** the source migration is **implemented and fixture-verified**: four MCP
> tools, independent owner clients, stubs, retirement of `services/api`, PostgreSQL tooling and legacy
> docs. It is **not real-service-verified, not cut over and not cloud-retired**: Manoj's deployed backend
> needs machine credentials, Shobhit's contract is still provisional, the voice platform does not yet
> forward the trusted headers, and the legacy Azure resources remain running. Read
> [implementation/REVIEW-REPORT.md](implementation/REVIEW-REPORT.md) for the evidence and
> [implementation/OPEN-DEPENDENCIES.md](implementation/OPEN-DEPENDENCIES.md) for what is missing.
> The planning text below describes the state before implementation and is kept as the authority the
> implementation was built against.

The application before this work had three MCP tools, our REST backend and PostgreSQL. The target has four MCP tools consuming Manoj's operational API and Shobhit's knowledge service, with no application database or backend engine in this repository.

## Implementation assignment

[FABLE-MASTER-PROMPT.md](FABLE-MASTER-PROMPT.md) is the comprehensive execution prompt for the coding agent working in this workspace. It covers implementation, tests, voice/gateway integration, source and Azure retirement, self-review, and the evidence to return for architect review. Giving the prompt to an agent starts a separate implementation assignment; publishing it has not implemented or cleaned up the system.

## Implementation assignment

[FABLE-MASTER-PROMPT.md](FABLE-MASTER-PROMPT.md) is the comprehensive execution prompt for the coding agent working in this workspace. It covers implementation, tests, voice/gateway integration, source and Azure retirement, self-review, and the evidence to return for architect review. Giving the prompt to an agent starts a separate implementation assignment; publishing it has not implemented or cleaned up the system.

## Read in this order

Start with [TARGET-STATE.md](TARGET-STATE.md) for the ownership diagram, contract-only boundary, cleanup completion gates and voice-performance requirements. The [Azure inventory](AZURE-RETIREMENT.md) identifies actual legacy and shared resources that must be handled during retirement.

1. [CURRENT-STATE.md](CURRENT-STATE.md): direct source audit, current dependency diagram and what breaks if the backend is removed now.
2. [PLAN.md](PLAN.md): authoritative scope, four tools and REST mapping, contract mismatches, stubs, response budget, phases, removal inventory, rollback and acceptance criteria.
3. [OPUS-REVIEW.md](OPUS-REVIEW.md): original review plus disposition; recommendations are incorporated in the plan, subject to the user's decisions. This is not a second review of the revised plan.
4. [Contract provenance and defects](contracts/README.md) and [the exact Manoj snapshot](contracts/manoj-openapi-20260930.yaml).

Existing architecture, API specs and setup documents outside this directory describe the legacy implementation. Use them as source evidence, not as instructions to preserve backend ownership during migration. Source code and public contract examples remain in Git; local logs, CLI transcripts, virtual environments, attachments and credentials are excluded.

## Decisions to preserve

- Keep this repository; adapt MCP in place. Manoj owns operational rules and persistence. Shobhit owns knowledge retrieval, symptom routing and red-flag decisions.
- Four target tools: `get_doctor_availability`, `manage_booking`, `search_knowledge`, `record_call_summary`.
- Availability combines the doctor's usual hours with the date/session-specific live board. No invented slots or capacity. A successful appointment request is NOTED, not a reserved appointment time.
- UNKNOWN availability, today or future: collect caller name and callback number, say someone from the hospital will call back, and save only a call summary with CALLBACK_NOTED. No booking, transfer, alternative booking, notification or separate callback task. Failed reads are not valid UNKNOWN responses.
- Department IDs come from the department list; doctor search accepts free text; appointment dates use confirmed ISO dates. Advanced multilingual interpretation and synonym/fuzzy matching are deferred, not new endpoint prerequisites.
- Preserve the plan's trusted caller identity, routing gate, stable write identity, uncertain-write handling and call-end-only summary access. The platform owns durable finalization/retries; MCP remains stateless.
- Target one second from end of caller speech to first useful audible response. The budget is provisional until measured on the real voice path; call summaries are outside it.

## Review and build on another laptop

Clone this repository, check out the implementation branch, use Python 3.13 and uv 0.11.21. Everything a reviewer needs runs without a database or any owner source:

```bash
git clone git@github.com:Garry2012/healthcare-tools.git
cd healthcare-tools && git checkout Garry2012/mcp-external-api
./scripts/test.sh          # frozen install, lint, hermetic suites, process e2e, package + image build
make demo                  # walk the four tools against the development stubs
```

`implementation/REVIEW-REPORT.md` lists the exact commands, counts and which checks used fixtures versus real services.

## Handover validation on 1 October 2026

- A checkout made exclusively from staged Git files, with no private workspace artifacts, passed frozen MCP dependency installation, source/wheel package builds and all 35 database-free MCP tests (16 end-to-end tests deselected).
- `make test-fast` passed: lint, all nine architecture import contracts, 413 API unit/contract tests and 35 MCP tests.
- Handover links resolve to tracked files/directories. The public contract checksum matches, and the original Opus review body is preserved unchanged.
- These checks validate the existing package and portable handover. They do not exercise real Manoj/Shobhit services, prove the latency target, or clear the legacy end-to-end failure below. No local database or deployment was started for this handover.

## Known starting limitations

- **Existing main CI is failing.** At source baseline `7e20b4459d0a58422bf3b5ba40a670be94b758f5`, [CI run 36571571806](https://github.com/Garry2012/healthcare-tools/actions/runs/36571571806) failed `test_mcp_offers_every_bookable_position_of_a_session`: the old tool omitted 4 of 7 bookable positions. It reported 50 other MCP tests passing. This predates the handover and is not concealed by changing tests or CI. The migration must preserve complete results or explicitly report incompleteness, although old slot semantics will be retired.
- The pinned Manoj spec has known schema defects. Preserve the original; prefer an owner correction, or the plan's labelled quoting-only test overlay. No overlay or new stub implementation is supplied in this documentation change.
- Shobhit's endpoint/schema/auth contract has not been supplied. Proposed fixture behavior must remain labelled provisional.
- Real service hosts, machine credentials/scopes, caller-verification agreements, replay/board details, gateway lifecycle controls and actual latency measurements remain external dependencies. Credentials are obtained securely, never committed. The public mock does not prove a live working backend.
- No database migration, deployment, cloud cleanup or external service write is part of publishing this handover. Historical data handoff and resource retirement need owner coordination later.

Everything available and necessary for **reviewing and starting** the agreed implementation is tracked here. The missing owner contracts and production evidence cannot be supplied by copying workspace artifacts into Git.
