# Master execution prompt for Fable 5.1

This is the implementation assignment. Read it in full, then execute it when the user gives you this prompt. Its creation is not evidence that implementation, deployment or cleanup has already happened. Return your work for architectural review using the report requirements below.

## Your role and outcome

Act as the lead implementation engineer for an MCP-only healthcare integration, with responsibility for correctness, maintainability, security, conversational usability, latency and retirement of the previous implementation. Work through implementation, testing, integration, scoped cleanup and self-review. Deliver reviewable code and verifiable evidence, not just a proposal or a collection of mocked demonstrations.

The user will have another agent review your work. You must make it possible for that reviewer to reproduce checks from a clean checkout and distinguish what is implemented, what was actually exercised and what remains blocked. Do not certify your own work as independently approved.

Work in this existing workspace:

```text
/Users/garima/conductor/workspaces/healthcare-tools/des-moines
```

Repository: `Garry2012/healthcare-tools`. PR base: `main` / `origin/main`.

At the time this prompt was prepared, the workspace branch was `Garry2012/mcp-external-api`, and user-owned `temp/` was untracked. Recheck actual state; do not assume it is unchanged. Preserve existing edits and untracked files. Do not rename the branch, force-push, reset the workspace, run blanket cleanup or stage unrelated files. Coordinate access if another agent is active; concurrent writers must own separate files. Use focused commits. `.context/` is suitable for scratch work, but it must not contain the only copy of deliverables or review evidence.

## Read first and establish authority

Read these repository files, then verify the relevant executable source yourself:

1. `docs/handover/mcp-only/README.md`
2. `docs/handover/mcp-only/TARGET-STATE.md`
3. `docs/handover/mcp-only/PLAN.md`
4. `docs/handover/mcp-only/CURRENT-STATE.md`
5. `docs/handover/mcp-only/AZURE-RETIREMENT.md`
6. `docs/handover/mcp-only/contracts/README.md` and its pinned Manoj specification
7. `docs/handover/mcp-only/OPUS-REVIEW.md`
8. Applicable workspace/repository instructions, current MCP source/tests, gateway registration, CI, Docker/Compose, Azure scripts and agent startup hooks.

The user's confirmed decisions and the current target/plan take precedence over conflicting legacy architecture instructions. The original Opus review is historical: its recommendations were incorporated with qualifications, especially the user's UNKNOWN policy. Do not reopen settled questions or implement superseded review alternatives.

Inspect git status, current HEAD, remote main, relevant running processes and available tools before changing anything. Record a baseline and actionable work checklist. The legacy full CI already has an availability-completeness failure; confirm current results rather than assuming everything passed. Do not weaken or delete meaningful coverage just to obtain a green run. Translate its intent into the new contract where old slot semantics are retired.

Use the MCP and LiveKit official documentation linked in TARGET-STATE.md and the deployed SDK/gateway versions when implementing integration details. Verify actual capabilities rather than copying a current-doc example into an incompatible version. You may delegate independent implementation/review tasks if supported, with explicit ownership and a warning not to overwrite others' work; you remain accountable for integration.

## Non-negotiable architecture

```text
Caller ↔ LiveKit voice agent (STT, LLM, TTS)
                     ↕ MCP client
              IBM ContextForge gateway
                     ↕
              OUR MCP SERVER
                 /       \
       HTTPS /             \ HTTPS
   Manoj's operational API  Shobhit's knowledge API
   His code/image/storage   His code/image/storage
```

This repository owns only the MCP server/tool implementations, external client adapters, public contract snapshots/types, consumer fixtures/tests, MCP build/deployment, gateway integration and relevant documentation/observability. The voice platform and gateway may have their own infrastructure; do not rebuild them here.

Manoj owns operational REST behavior, scheduling/appointment rules and persistence in his own codebase/image/resources. Shobhit owns hospital knowledge, symptom routing, red-flag decisions, retrieval and storage in his own codebase/image/resources. Their published versioned Swagger/OpenAPI interfaces are the integration authority. Their source, server images, private modules, databases, migrations, embeddings and backend engines must not become dependencies of our build or runtime.

No additional LLM, agent loop, interpretation engine, clinical classifier, vector database, SQL persistence, Redis service or local fallback backend belongs inside MCP. Keep necessary validation, authentication, trusted identity, status mapping, retry discipline and small request orchestration. Reusing an HTTP library is appropriate; rebuilding another team's application is not.

Keep synthetic development stubs separate from production. They simulate contract responses and specific failure/replay scenarios; they must not grow into operational or knowledge engines. Production configuration must reject known stub/example endpoints and require explicitly configured owner services. Do not fetch Swagger or generate clients on the voice request path.

## Implement exactly these four MCP tools

### 1. get_doctor_availability

Replace legacy `find_availability`; do not retain `get_doctor_working_hours` as an additional tool.

Compose the necessary Manoj calls inside one model-facing invocation:

- `GET /departments`: resolve returned department names to IDs.
- `GET /doctors?query=...` and/or department filter: use the free-text search contract; clarify multiple matches.
- `GET /doctors/{doctorId}`: obtain usual working-hour windows and profile facts.
- `GET /availability?doctorId=...&date=...` or department equivalent: overlay date/session-specific board information. Pass exactly one supported target filter.

Profile and board reads can run concurrently once doctor/date are known. Use a department-wide board request when appropriate instead of unbounded per-doctor fan-out. Cache permitted stable directory/profile data with a bounded policy; do not cache live-board truth across turns. Preserve all relevant sessions/windows and explicit incompleteness/pagination.

There is no slot API yet. Do not invent slots, slot IDs, token numbers, capacity, guaranteed appointment times or patient arrival calculations. Do not use patientsPerHour to allocate anything. A patient's preferred time is a request.

Use facility timezone and a controllable clock. Distinguish the requested date and session; apply board timing without double-counting delays or guessing missing times. Preserve IN, LATE, CANCELLED, NOT_CONFIRMED and UNKNOWN semantics, on-call behavior and unconfirmed profile data. Standard hours alone cannot prove current attendance. A failed/malformed board request is an unavailable service result, not UNKNOWN or “no availability.”

**UNKNOWN policy is fixed:** for today or future dates, including stale/missing entries that the owner returns as UNKNOWN, stop this appointment journey. Ask the caller's name and callback number, say someone from the hospital will call back, and save only a call summary with CALLBACK_NOTED. No appointment, transfer, alternate booking, notification or separate callback task. Do not invent a callback deadline. Preserve this policy in schemas, prompts and tests.

### 2. manage_booking

Adapt create/list/cancel/reschedule to Manoj's actual appointment contract:

- `POST /appointments`
- `GET /appointments?mobile=...`
- `POST /appointments/{appointmentId}/cancel`
- `POST /appointments/{appointmentId}/reschedule`

Use contract-supported patient/doctor-or-department/date/preferred-time fields, with the action-specific requirements validated. Remove slotId/newSlotId assumptions. Do not invent doctor changes on a reschedule endpoint that does not support them. Obtain caller confirmation before writes.

A successful create returns NOTED: tell the caller their request was recorded, without promising a reserved time. Preserve other actual owner lifecycle statuses honestly. Distinguish validated success, definite rejection/conflict and uncertain completion. A timeout after possible submission must not become definite failure or success.

Department IDs and ISO dates are normal interface formats. Use returned directory choices and explicit confirmed dates. Advanced multilingual date/name/synonym interpretation is deferred; do not require a new interpretation endpoint or move the legacy resolver into MCP.

### 3. search_knowledge

Consume Shobhit's agreed interface for approved hospital answers, symptom routing, red flags, clarification and no-answer outcomes. Obtain and pin the actual contract when available. Do not invent a published URL/schema, scrape his backend or substitute a local knowledge engine.

For availability and appointment creation, trusted original turn context must reach Shobhit internally even if the LLM did not choose `search_knowledge`. Independent safe reads may overlap this check; routine scheduling results and a create must wait for a valid current routing clearance. New caller information requires a current decision. Missing context, a failed service or an unknown response shape cannot become clearance. Consume his decisions; do not detect symptoms locally.

If the contract remains unavailable, implement the clean integration boundary and explicitly provisional fixtures, finish independent work and record the exact missing agreement. Do not call a fixture-backed path production-integrated or delete required existing production resources to simulate completion.

### 4. record_call_summary

Use Manoj's `POST /call-summaries`. Implement this as an MCP tool invoked programmatically by the authenticated call-end lifecycle, outside ordinary conversational tool selection and the speech response budget.

Required owner fields are callId, startedAt, intent and outcome; validate all optional fields against the pinned contract. Inject authoritative call identity/timing from trusted platform context. The callback number is caller-provided contact data; do not populate it automatically from caller ID where the contract says otherwise.

For UNKNOWN callback: outcome CALLBACK_NOTED, caller-provided number in callerMobile, name and essential request/UNKNOWN context in summaryText, no appointmentId or transferredTo. Respect the 500-character limit without losing essential callback information.

The first accepted callId fixes the saved summary; a later replay returns the original unchanged. Finalize once, freeze the payload, and reuse it for retries. Never submit a provisional summary expecting later updates. Preserve completed actions after an abrupt disconnect; do not label every hang-up ABANDONED. Do not report a failed summary write as a saved callback request.

The voice platform owns durable finalization and eventual retries, including after disconnect; MCP stays stateless. Verify both conversational tool filtering and server-side authenticated lifecycle access. Client-side hiding alone is not a security boundary. If the platform code lives outside this workspace, deliver the exact integration contract and executable consumer/harness tests here, and report the owner change needed; do not silently recreate the platform in this repository.

## Cross-cutting implementation requirements

- Configure independent operational/knowledge base URLs, HTTP pools, auth, limits and deadlines. Respect full base paths: Manoj's documented backend uses /api/v1; the public mock does not. Obtain machine credentials through /auth/token as documented; staff login is not the MCP machine flow. Use registration-granted scopes, warm token caching and bounded single-flight refresh. Never log secrets or fetch them into committed files.
- Keep patient/callback contact separate from authority to list/change appointments. Derive trusted identity from authenticated, tenant-bound platform context, never a model-supplied phone/header/tenant field. No arbitrary last-ten-digit normalization. Enforce the agreed number/verification rules and initial family-access restrictions. Prevent cross-call/tenant leakage.
- For confirmed writes, use a trusted stable logical operation ID, opaque bounded idempotency key and frozen outgoing payload. Retrying after a lost response must not mint another intent/key because wording changed. Keep durable operation context in the platform. Do not assume a list-by-mobile uniquely reconciles a lost write.
- Validate requests and upstream responses. Return concise typed outcomes and useful next steps; do not expose raw upstream error text or unnecessary patient information. Preserve uncertainty, choices and completeness.
- Apply one total deadline over pool wait, auth, all calls and any retry. Remove legacy unconditional long write retries. Retry only within the remaining budget and verified owner semantics. Do not multiply retries at gateway, MCP and platform layers. Local cancellation is not proof a remote mutation was undone.
- Keep local /health and /ready distinct from dependency status; do not require an undocumented upstream /ready or fresh OAuth on every probe. External-read release checks still have to prove working dependencies.
- Use a small, clear model-facing schema with action enums/constraints and descriptions that distinguish the tools. Return compact structured data, without silently truncating choices/windows. Annotate behavior truthfully; manage_booking is not universally read-only. Pin schema/prompt versions and refresh actual ContextForge/LiveKit tool discovery.
- Do not equate tool-list discovery, an HTTP 200, or a mock response with semantic correctness. Verify authorization, context forwarding, errors, lifecycle access and results through the real MCP transport.

## Execute in phases with explicit gates

### A. Establish contracts and work plan

Inspect the current source dependencies rather than relying solely on reports. Map each required outcome to implementation files and a verification method. Maintain a small task checklist, decisions and dependency register. Ask necessary questions one at a time; use settled decisions and reasonable implementation judgment without repeatedly requesting permission.

Check the pinned Manoj snapshot/hash and any newer owner revision. Do not silently replace it. The pinned snapshot has five description-quoting defects affecting four schemas: preserve it; prefer a corrected owner contract, or use a labelled, hashed test-only quoting overlay. Do not add guessed semantics. Treat Shobhit's absent contract, real hosts/access and caller-verification/replay agreements as explicit dependencies, not reasons to invent a backend.

### B. Build independent tests and integration foundations

Create operational and knowledge contract fixtures/stubs with controllable clocks, auth/error cases and commit-then-drop-response behavior. Keep assumptions visible. Add a backend-free test command and CI path before retiring old fixtures. Mandatory consumer coverage must fail if required schemas/fixtures disappear; it must not silently skip because API source or a database is absent.

Implement client/config/auth/result/context/deadline foundations with focused tests. Keep changes cohesive and reviewable. Do not add abstractions or new services without a concrete need.

### C. Implement tools and platform/gateway boundary

Implement all four tools, routing orchestration, identity/operation context, summary lifecycle boundary and prompts. Update MCP registration, expected tool counts/names, input/output schemas and read-only smoke checks. Exercise MCP over HTTP with trusted headers, including concurrent calls.

Validate against the actual ContextForge and LiveKit versions. Verify forwarded identity/original turn metadata and finalization access rather than assuming the gateway transports every header. Document necessary changes in externally owned platform code and verify them when access is available. A test harness can establish our boundary, but cannot prove that an unmodified external deployment is integrated.

### D. Build, verify and measure early

Run clean-checkout install, lint/type checks appropriate to the project, mandatory tests and the production MCP image build. Exercise owner-designated test services with synthetic data when available. Do not write appointments/summaries to real production tenants as smoke tests. Keep API/database absence checks meaningful.

Start real-service latency measurement early, not after building everything. Target around 250 ms for the tool round trip including gateway and downstreams, preserving the provisional 70 ms gateway/MCP/transport plus 180 ms downstream budget. A sub-500 ms tool result alone does not prove an under-one-second voice response.

Measure end-of-caller-speech to first useful audible result at the caller. Use the planned proposed p95 ≤1,000 ms under declared load unless the user agrees another acceptance target. Report p50/p95/p99, sample count, concurrency, regions, versions, cold/warm conditions, failures/timeouts and measurement boundaries. Do not add stage percentiles as proof, exclude slow failures silently, or count filler as a useful answer. STT, endpointing, both LLM stages, TTS and media delivery all matter.

Use async pooled clients, warm auth, bounded permitted caches, parallel independent reads and compact payloads. Do not add another LLM inside MCP. If owner-service latency prevents the target, quantify the critical path and record the owner action needed; do not bypass routing or move their engine here. Call summaries run after the call.

### E. Retire source and cut over safely

Use PLAN.md's full retirement inventory. Remove all legacy services/api source, tests and service-only dependencies, migrations/seed/rollout loaders, API image builds, PostgreSQL startup/provisioning, DB configuration, API-dependent fixtures, benchmark/setup scripts, obsolete active docs and agent hooks. Keep only dependencies actually required by the new MCP implementation and its consumer tests. Preserve useful requirements/fixtures in their new contract form and history in Git; do not leave an executable fallback backend in an archive folder.

Coordinate changes to Makefile, CI, Compose, Azure deployment, gateway registration, demo scripts, packs, root instructions and handover docs. Default setup must not build/start/install any legacy backend or database. Production images must exclude fixtures/stubs, dev credentials and unnecessary runtime packages.

Complete source removal in the implementation branch once replacement build/test coverage is ready. Live cutover and cloud deletion additionally require the real-service, identity, routing, lifecycle and data-handoff gates. Missing external access must not force a fake production claim or prevent independently finishing reviewable code.

Use one appointment authority; never dual-write. Have a compatible rollback procedure against the same external ledger, with safe write disablement if rollback cannot preserve correctness. Do not casually reactivate the old database after external appointments have been created. Deploy/cut over only within the environment and authorization supplied for this assignment, after preparing the exact configuration and rollback evidence.

### F. Perform scoped Azure retirement

Cloud cleanup is part of completion, not an optional future note. Refresh the live inventory; the saved snapshot is not an automatic deletion allowlist. Prepare exact resource IDs, owners/consumers, data disposition, dependency order, proposed actions and recovery/retention requirements before destructive execution.

Known hazards from the earlier read-only inspection:

- healthcare-rg includes the old backend, MCP, voice-platform workloads and contract documentation/mock services.
- pg-fd-demo-hospital-0574c1 contains frontdesk AND other databases, including voice_agent, voice_cis, operations and medplum.
- The Container Apps environment, registry and other supporting resources are shared.

Retire the old API app/revisions, migration/apply/seed jobs, backend-only images, the old database assets and obsolete credentials/access only after cutover, consumer checks and required owner-led data handoff/retention. Do not delete a whole group, server, vault, registry, environment or identity while unrelated required consumers remain. Retain shared resources with explicit ownership/purpose or arrange their relocation first. Do not infer ownership from a resource name.

Within the user's authorized scope, execute verified legacy-only retirement once these gates are satisfied. If ownership, data disposition or authorization for an exact destructive action remains unresolved, finish the non-destructive work and present that concrete action/question to the user; do not ask for blanket permission to “clean Azure,” and do not destroy resources merely to complete the checklist. No messages to service owners without authorization.

After cleanup, verify absence of retired resources/references/jobs/grants, functioning MCP/voice paths, remaining shared-resource ownership, retained-data expiry where applicable, and residual cost. Report what was deleted versus preserved versus blocked. Do not state that all cleanup is complete while unexplained old resources remain.

### G. Review, fix and deliver

Review the complete diff against the target requirements, not just the files most recently changed. Use an independent reviewer agent if available; otherwise label your review as self-review. Review architecture separation, tool usability, schemas, identity, routing, replay/uncertain writes, timezones, lifecycle summaries, error handling, latency, deployment and cleanup evidence.

Fix actionable defects and rerun the affected checks. Do not waive blocking defects or manufacture an external approval. Review the final commit after fixes. Commit only intentional changes and sanitized evidence; push the implementation branch and open/update a PR against main when GitHub access is available. Leave the implementation PR for the requested architect review; do not merge or describe it as approved by that reviewer yourself.

If real contracts, credentials, platform access or owner decisions block part of the objective, complete all independent work and report exact unmet gates and who/what is needed. Distinguish code-ready, test-fixture-verified, real-service-verified, production-cut-over and cloud-retired states. Never turn “not tested” into “passed.”

## Minimum acceptance coverage

| Area | Required evidence |
|---|---|
| Surface | Exactly four intended MCP tools; three conversational tools and controlled call-end summary; gateway/agent schemas match the deployed server. |
| Availability | Complete multiple windows/sessions; profile+board overlay; late/cancelled/unconfirmed/UNKNOWN/on-call cases; date/timezone/expiry; pagination and explicit incompleteness; no synthetic slots. |
| UNKNOWN | Today/future/stale/missing-as-UNKNOWN: collect name/number, callback wording, exactly the summary business write; no booking/transfer/alternate/task/notification. A board failure follows the service-error path. |
| Lookup | Department IDs, free-text matches and clarification, explicit ISO dates, unsupported/ambiguous input; no copied interpretation engine. |
| Identity | Model phone/header override attempts, missing verification, supported/unsupported number formats, family restrictions and concurrent tenant/caller isolation. |
| Routing | Named doctor plus symptoms reaches Shobhit internally; required routing blocks writes until cleared; changed context, missing/slow/malformed response and outage cannot become clearance. |
| Mutations | Success, validation/conflict, same-intent replay, changed payload, uncertain commit, dropped response, duplicate/concurrent request, malformed success, auth rejection and total deadline. |
| Summaries | Actual call-end invocation/access, metadata after disconnect, frozen replay body, 200/201 semantics, 500-character preservation, language handling, completed outcome after hang-up and failed persistence. |
| Transport | Independent pools/auth, token expiry/single-flight, correct mock/backend base paths, bounded retries, cancellation uncertainty, local readiness and separate dependency status. |
| Separation | Fresh checkout installs/builds/runs mandatory CI without services/api, its venv, PostgreSQL or private workspace artifacts. No production fixtures or hidden engines. |
| Voice | Chosen model calls the right tools with valid arguments and concise honest speech; interruptions/retries do not duplicate writes. Gateway-to-tool and caller-audio timings measured separately. |
| Operations | Tested rollback, one appointment authority, scoped Azure before/after inventory, shared-resource preservation, no obsolete active references and appropriate cost/retention evidence. |

## Required handback for the architect

Save durable, sanitized results under `docs/handover/mcp-only/implementation/` and include them in the implementation branch. Create concise substantive reports, not empty templates or raw log dumps:

1. `REVIEW-REPORT.md`: completion status, final code commit, branch/PR, target-vs-built diagram, requirement-to-code/test/evidence mapping, architecture/self-review findings, fixes and remaining risks. Specify exact reproducible commands, pass/fail/skip counts and which checks used fixtures versus real services. Record the code SHA tested/reviewed; a later report-only commit may reference it explicitly.
2. `LATENCY-RESULTS.md`: benchmark method and commands, boundaries, tested hosts/regions/versions without secrets, sample size/load/cold-warm conditions, p50/p95/p99, failures, comparison to targets and bottlenecks. State clearly if real caller audio or owner APIs were unavailable; stub timings are not production timings.
3. `AZURE-RETIREMENT-RESULTS.md`: refreshed scoped inventory, changes executed, preserved resources and reasons/owners, data/retention disposition, validation and remaining costs or unverified items. Clearly say “not executed” for blocked actions.
4. `OPEN-DEPENDENCIES.md`: only actionable unresolved items, impact, owner, exact missing input/action, work already completed, and how the reviewer can verify closure. State “none” only if all required external evidence exists.

Keep raw large logs, private resource identifiers, transcripts and screenshots with sensitive data in an appropriately private evidence location; reference them safely. Commit no secrets, real caller data, virtualenvs, caches or unrelated workspace files. Any essential reproducible non-sensitive fixture, configuration template, test or build instruction must be tracked rather than existing only in .context.

Finish with a short message addressed to the architect containing: status, branch/PR and tested commit, links to the four reports, what was implemented/removed/deployed, key test and latency results, exact Azure actions, remaining blocked gates and the specific review requested. Do not just say “done.” The reviewer must be able to assess readiness without relying on your chat history.
