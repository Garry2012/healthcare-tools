# Ordinary call-summary tool implementation plan

> Execution: after Garima approves this plan, implement natively in this workspace using test-driven development, followed by the mandated safety and latency reviewers. No implementation is authorized by this document alone.

**Goal:** Expose `record_call_summary` through the same gateway bearer as the other three tools, storing the LLM's whole-call summary unchanged under Manoj's natural call-ID deduplication contract.

**Architecture:** Keep the stateless MCP adapter and existing pooled operational client. Summary validation, result mapping and diagnostics remain local to the summary boundary; bookings retain their existing authentication, identity checks, idempotency keys, outcomes and deadlines. No new backend, persistence, queue, clinical routing or second summary implementation.

**Tech stack:** Python 3.13, FastMCP 2.14.7, MCP SDK 1.30.0, Pydantic 2.13.5, httpx, Starlette, pytest, Azure Container Apps and ContextForge registration tooling.

**Spec:** `.context/astra-prompt-call-summary.md`, plus the user's whole-repository impact/TDD instructions and `.context/astra-brief-addendum-code-quality.md`. This plan repeats the implementation decisions so the ignored brief is not the sole handover artifact. Owner contract: `docs/handover/mcp-only/contracts/manoj-openapi-20260930.yaml`.

**Investigated baseline:** `8c2b60a`, branch `Garry2012/garry2012/explain-tool-requests-responses`. This is newer than the preceding hand-back: PR #12 is now merged in this checkout. Existing untracked `temp/` is preserved. No live service, Azure, secret value or database was accessed during this investigation.

## Global constraints

- Plan approval before code. No push, merge, deployment, Azure resource/secret deletion or history rewrite.
- Every commit: at most 10 files and inspected green `make test-fast` before committing. Evidence files count toward the limit.
- Tests first; capture important failures against old behaviour, then passing results. Mock HTTP/clock boundaries, not our own service functions.
- Keep availability/booking date rules, booking and knowledge outcomes, callback `ask`/`say` defaults, caller verification and tenant boundaries unchanged.
- Caller hang-up recovery is out of scope. No durable finalizer or queue is added here.
- Voice-team handover remains a tool contract; no voice prompts, scripts or LiveKit implementation instructions.
- Do not edit `.claude/agents/*`. Their old lifecycle-only and summary-after-call assumptions are superseded for this task and must be reported explicitly to reviewers.

## 1. Current behaviour, intended behaviour and root cause

| Concern | Current executable behaviour | Intended behaviour |
|---|---|---|
| Discovery/access | BearerAuth chooses conversation/lifecycle; LifecycleGate lists 3 tools or 1 and blocks calls across the split | One gateway bearer lists/calls all 4; unauthenticated/wrong bearer still gets HTTP 401 |
| Arguments | 10 arguments including callerName/requestedDate; summaryText allows 2,000 input characters | 8 arguments: intent, outcome, summaryText, callerMobile, language, doctorId, appointmentId, transferredTo |
| Text | compose_text adds a protected name/callback/date/doctor prefix, normalizes whitespace and truncates to 500 | Required, nonblank, at most 500 characters; accepted string is forwarded exactly, including whitespace/newlines; nothing synthesized or trimmed |
| Call context | Header call ID/start time and optional duration; caller data/context fields shared with bookings | Summary needs only X-Call-Id and timezone-aware X-Call-Started-At; other booking headers remain supported globally; duration removed |
| Deduplication | Generated summary_key sent as Idempotency-Key, plus owner callId deduplication; 200 compared with current intent/outcome/mobile | No summary Idempotency-Key; first accepted callId is final; valid 200 with matching callId is ALREADY_SAVED irrespective of other payload differences |
| Result | 8 outcomes plus nextStep, summaryId, fields, detail, retryAfterSeconds | 5 outcomes; only outcome, with fields present only for INVALID_REQUEST |
| Diagnostics | Many failure details returned to caller; dropped/rewritten summary text not visible | Safe reason/retry delay/created summary ID in correlated logs; never summaryText, callerMobile, names or raw owner error prose |
| Timing | Separate 8-second summary invocation/exchange cap described as after-call work | Same configurable summary limit, now available to an LLM; not a 300 ms tool guarantee |

**Root cause:** the earlier architecture deliberately made summaries a privileged call-end operation and implemented an adapter-authored callback summary. That assumption is encoded in middleware, Settings, tool tags, exported schema, secrets, discovery checks, fixtures, result models and documentation. Changing only the tool description or bearer check would leave contradictory authorization, stale gateway discovery, unsafe validation/error output and old retry semantics.

**Additional findings from source:**

- FastMCP `FunctionTool.run` validates function arguments before invoking the function. Simply changing its Field(max_length=2000) to 500 would produce a validation/protocol error rather than the required in-band INVALID_REQUEST. Missing/wrong-type arguments also need privacy coverage because validation errors can include input values.
- `OpsClient._write` is shared by CREATE/CANCEL/RESCHEDULE and summaries. It already distinguishes unsent failures from possibly committed writes and freezes retries. Its auth retry currently refreshes on 401, not 403.
- The stub routes summaries through the generic idempotency-key cache, even though it gives an existing callId precedence. Both mechanisms must not remain active for summaries.
- The current summary 200 path does not check returned callId. A shape-valid success is not sufficient evidence that it belongs to this call.
- `tools.observed` currently dumps default fields. Removing result fields from documentation alone would still emit them. The interface completeness test assumes every tool has nextStep and must change legitimately for the new summary model.
- `smoke.py` currently attempts a summary expecting authorization refusal. That check must disappear before release: a discovery smoke test must not become an actual write after access changes.

## 2. End-to-end trace

```text
LLM arguments: whole-call text + one intent/outcome + optional contact/IDs
  -> voice runtime attaches trusted call ID and start time
  -> ContextForge virtual MCP server (voice-client access token)
  -> registered adapter connection (MCP_BEARER_TOKEN; all 4 tools)
  -> summary input validation and trusted-context checks
  -> existing pooled OpsClient + OAuth machine credential/token
  -> POST OPS_BASE_URL/call-summaries, with calls.write
       no durationSeconds; no Idempotency-Key; unchanged accepted text
  -> parse owner CallSummary and check returned callId
  -> {outcome}, or {outcome: INVALID_REQUEST, fields: [...]}
```

One MCP bearer does **not** mean sharing it with Manoj or replacing ContextForge's own client/admin tokens. Operational OAuth `ops-client-id`/`ops-client-secret`, knowledge bearer, and gateway access controls remain separate boundaries.

| Result | Condition |
|---|---|
| SAVED | Verified, parseable 201 response for the call |
| ALREADY_SAVED | Verified, parseable 200 with our callId; existing body may differ; no update was made |
| INVALID_REQUEST | Local validation failure, or definite owner 400; sanitized field names from error.details, never message/issue/input values |
| NOT_CONFIRMED | Unanswered/possibly committed write, malformed/untrustworthy success, temporary transport/deadline/429/5xx failure |
| NOT_SAVED | Missing/malformed trusted call ID/start, or definite credential refusal with no earlier uncertain send |

An earlier possibly committed attempt takes precedence over a later 400/401/403: NOT_CONFIRMED, never a definite failure. The honesty rule means **an unverified possibly committed write** is not claimed saved or not saved; a later verified 200/201 can resolve that uncertainty.

## 3. What gets deleted

- `services/mcp/src/frontdesk_mcp/access.py`: entire lifecycle authorization middleware/tag; no replacement authorization split.
- Lifecycle principal/type/context variable once the single-bearer check no longer uses it; lifecycle branch and configuration parameter in BearerAuth.
- `MCP_LIFECYCLE_BEARER_TOKEN`, equality guards, setup fixtures and separate gateway/lifecycle tool collections; export `lifecycle` key and tool tag.
- `callerName` and summary `requestedDate`, their validations, prefix/truncation logic, `compose_text`, `summary_key`, and unused imports. Availability's requestedDate remains.
- Duration context field/parser/header forwarding and supported harness argument; no summary body duration field.
- Old summary result fields/outcome literals and the 200 payload-comparison/CALL_ID_ALREADY_USED branch. Booking equivalents remain.
- Summary participation in the stub's Idempotency-Key cache; retain appointment caching.
- Lifecycle secret creation/read/reference/env wiring and smoke/registration/client instructions; obsolete split-only tests replaced with the new access/identity tests.
- Current documentation statements claiming three gateway tools, separate finalizer credentials, automatic text rewriting or old result semantics. Historical reports, contract pins/overlay/hash and reviewer files remain unchanged.

**Unused secret:** Key Vault `mcp-lifecycle-token` (profile currently names `kv-fd-demo-hospi-0574c1`), plus any existing Container App reference of that name. This task will stop creating/referencing it in new revisions but will not delete it, including during the future upgrade path. Retention supports coordinated rollback; retirement needs separate approval.

## 4. What gets changed: complete impact inventory

Paths under `services/mcp/` below are relative to that directory.

| Files/subsystem | Change or explicit preservation |
|---|---|
| `src/frontdesk_mcp/summary.py` | New 8-field request, exact text, existing contact/ID/transfer validation, callId checks, five-result mapping and safe diagnostics |
| `src/frontdesk_mcp/outcomes.py` | SummaryOutcome/SummaryResult only; outcome always present, fields only for invalid request; other tools untouched |
| `src/frontdesk_mcp/tools.py` | Ordinary summary tool, summary-specific input validation boundary and conditional result serialization; preserve one tool_result event per invocation |
| `src/frontdesk_mcp/server.py`, `context.py`, deleted `access.py` | Single bearer, no principal split, trusted headers and call-ID logging preserved, duration removed |
| `src/frontdesk_mcp/config.py` | Remove second credential/guards; retain gateway requirement, production HTTPS/mock refusal, owner scopes/credentials and summary deadline |
| `src/frontdesk_mcp/ops_client.py` | Per-call optional idempotency header using existing _write; summary auth-refresh policy below; no duplicate retry implementation; strict summary success status handling |
| `src/frontdesk_mcp/cli.py`, `prompt.py`, `packs/healthcare.json` | Remove exported lifecycle metadata; factual descriptions and exact supplied whole-call text description; schema version increments for each surface-changing commit |
| `src/frontdesk_mcp/clock.py` | Clarify comment that summary cap is separate, not guaranteed after hang-up; deadline algorithm unchanged |
| `src/frontdesk_mcp/contract.py` | Reuse existing CallIntent, CallOutcome, CallSummary and safe error parsing; no enum invention. Review parser coverage, no pinned-owner-contract rewrite |
| `dev/frontdesk_stubs/ops.py`, `tests/test_stubs.py` | New callId 201 / duplicate 200 unchanged; no summary key handling, including accidental supplied keys; retain fixture auth/error/commit-then-fail controls |
| `tests/test_summary.py`, `test_ops_client.py` | Replace legacy summary expectations; wire, status, retry, privacy, text limits, auth and booking-key regression coverage |
| `tests/test_server.py` | Real HTTP discovery/calls/auth, in-band validation and log capture, exact summary result keys, schema and interface checks; no mandatory nextStep for summary |
| `tests/conftest.py`, `harness.py`, `test_context.py`, `test_settings.py` | Remove credential/duration fixtures, retain trusted identity isolation and fail-closed production configuration |
| `tests/test_deploy.py`, `test_e2e_processes.py`, `test_external.py`, `test_external_transport.py` | Four-tool smoke/discovery, single-token process journey, new summary assertions, remove MCP_E2E_LIFECYCLE_BEARER; preserve explicit synthetic-write gates |
| `dev/demo.py`, `dev/bench.py` | Single-token setup, whole-call example without separate arguments; benchmark setup no obsolete credential. Do not label summary latency as in-call performance |
| `tests/test_booking.py`, `test_availability.py`, `test_knowledge.py`, `test_bench.py`, `test_profiles.py`, `test_gate_assertions.py`, `test_contract.py` | Regression suites; change only assertions genuinely affected. Appointment lifecycle wording and availability requestedDate are unrelated and retained |
| `tests/contracts/mcp-tools.snapshot.json` | Regenerate from CLI; new required/optional input/output schema, five outcomes, no lifecycle metadata; other three tool schemas structurally unchanged |
| `deploy/azure/deploy.sh`, `deploy/azure/smoke.py` | Four-tool read-only smoke; single secret/env configuration, create/upgrade dry-run assertions, no new writes or secret deletions |
| `deploy/contextforge/register.py` | All four tools expected/verified; five supported passthrough headers, changed discovery/update tests; preserve team/private access and secret redaction |
| `deploy/docker-compose.yml`, `.env.example` | Remove second MCP bearer, describe separate summary budget; keep owner credential settings unchanged |
| `docs/handover/VOICE-TEAM.md` | Update existing interface in place: one MCP auth scope, exact eight arguments, five outputs, conditional fields, headers, first-write-final rule, configurable 8 s summary deadline |
| `CLAUDE.md`, `README.md`, `services/mcp/README.md` | Correct rules, tool/auth tables, write-honesty distinction and log policy |
| `docs/DECISIONS.md`, `docs/architecture/TARGET.md` | New decision with rationale/risks, and narrow generic keyed-write wording to bookings |
| `docs/handover/{CONTEXTFORGE,AZURE,TESTING,ONBOARDING,OWNER-INTEGRATION-MESSAGES}.md` | Update access, virtual-server membership, setup, read-only smoke and owner request text; no messages sent |
| `docs/handover/mcp-only/{PLAN,TARGET-STATE,README}.md`, `implementation/OPEN-DEPENDENCIES.md` | Replace old current rules; remove summary key-precedence dependency, keep owner scope/live testing and booking replay questions; label earlier live observations as historical |
| `deploy/environments/{live,mock}.env`, `deploy/environments/README.md`, `scripts/{env,run-profile,rollout-env}.sh`, rollout settings | Audited: endpoint/scoped owner secrets stay in their existing single location. No endpoint, tenant, resource group or credential changes needed |
| `Makefile`, `scripts/test.sh`, `.github/workflows/ci.yml`, Dockerfiles, lockfile/pyproject | Existing gates/builds reused; no new production dependency. No type checker is configured today; do not report Ruff as a type checker |

## 5. Implementation choices requiring approval with this plan

1. **Approved in-band validation:** retain the outer 2,000-character argument cap, enforce 500 in SummaryService, and advertise maxLength 500 once after registration like _apply_pack_text. No custom validation boundary. Additional wrong-type privacy handling is allowed only if a red test proves input values reach logs. Test real MCP calls, not just SummaryService. Inputs above the outer cap retain framework validation.
2. **Error-field privacy:** project owner validation fields onto known summary request/context field names. Unknown/raw field strings are omitted, not echoed; INVALID_REQUEST may have an empty fields list if the owner gave no safe names. Preserve original text only in the HTTPS write body.
3. **Response trust:** require callId equality for 201 as well as 200. Unexpected success status or undocumented 4xx (e.g. 404/409) becomes NOT_CONFIRMED with a safe contract-anomaly log, not an invented sixth result or a claim of non-persistence. Owner clarification remains an integration question.
4. **Approved auth policy:** retain existing 401-only refresh for all writes. A definite 403 is NOT_SAVED; after an earlier uncertain send it remains NOT_CONFIRMED. No scope/client substitution.
5. **Removal proof:** no obsolete positive implementation/config/doc references. The required negative regression for an ignored duration header necessarily names that old header. Explicitly list that test-only exception rather than hiding it through string concatenation. Likewise list intentional historical/pinned-contract/reviewer references and unrelated appointment lifecycle/availability requestedDate occurrences.

## 6. Commit groups (10 files maximum each)

These are incremental review commits in one implementation change, not separately deployable releases. Repeated schema/interface files keep each surface change pinned. Update process/external consumers at the indicated integration steps; full end-to-end acceptance is required at the end. No transitional dual-token mode or compatibility adapter is introduced. Actual file counts are checked before every commit; evidence is committed in separate batches when a code batch already has 10 files.

| Commit | Files (exact, paths abbreviated as above) | Test-first deliverable |
|---|---|---|
| 1. Natural-key transport | ops_client.py, summary.py, test_ops_client.py, test_summary.py, dev/frontdesk_stubs/ops.py, test_stubs.py (6) | No summary Idempotency-Key, same-body retry, changed-body duplicate returns stored record; booking key retained. Remove summary_key here |
| 2. New summary contract | summary.py, outcomes.py, tools.py, cli.py, packs/healthcare.json, prompt.py, snapshot, VOICE-TEAM.md, test_summary.py, test_server.py (10) | Eight inputs, exact ≤500 text, five results, safe input/result/log behaviour, 200 identity semantics; remove CLI lifecycle export now (runtime access migration follows) |
| 3. Remove duration and update journeys | context.py, harness.py, test_context.py, test_summary.py, test_server.py, test_e2e_processes.py, test_external.py, dev/demo.py, register.py, test_deploy.py (10) | Ignored obsolete header, no duration body; update positive wire journeys and matching header lists. No summary text synthesis |
| 4. Single gateway access | delete access.py; server.py, tools.py, prompt.py, snapshot, VOICE-TEAM.md, test_summary.py, test_server.py, smoke.py, test_deploy.py (10) | Gateway lists/calls all four; missing/wrong token denied; safe smoke never calls writes. Remove lifecycle tag/collections and gate-only tests after HTTP replacements |
| 5. Remove dead credential/principal setup | config.py, context.py, conftest.py, test_settings.py, test_server.py, dev/bench.py, dev/demo.py, test_external.py, deploy/docker-compose.yml, .env.example (10) | No second token or principal state required; production single-token guards and caller isolation remain |
| 6. Deployment/consumer alignment | deploy.sh, register.py, test_deploy.py, test_e2e_processes.py, test_external_transport.py, clock.py, test_settings.py (7) | Four-tool registration/update drift tests, no lifecycle secret provisioning, no secret deletion, process smoke/journey and correct summary budget |
| 7. Rules and architecture | CLAUDE.md, README.md, services/mcp/README.md, docs/DECISIONS.md, docs/architecture/TARGET.md, PLAN.md, TARGET-STATE.md, mcp-only/README.md, OPEN-DEPENDENCIES.md (9) | Current rule audit and explicit owner/deployment separation; no stale split or summary-key claims |
| 8. Operator/owner handover | CONTEXTFORGE.md, AZURE.md, TESTING.md, ONBOARDING.md, OWNER-INTEGRATION-MESSAGES.md, VOICE-TEAM.md if factual review requires corrections (≤6) | Current instructions match real tool/auth/result/deadline behaviour, no agent behaviour scripts |
| 9+. Review receipts | New dated hand-back and red/green/audit logs under implementation/, ≤10 files per evidence commit | Required proof, final diff/file counts, review findings and untested gates |

For every behavioural group: write/update focused tests → run and inspect the expected red → implement minimal change → run focused green → `make test-fast` → inspect output → commit. No skipped/xfail substitutes. Existing obsolete tests are replaced, not silently weakened. The planning document is a separate planning artifact; do not add it to a full 10-file implementation batch.

## 7. Review focus and proof matrix

| Failure/input class | Required assertions before implementation and after |
|---|---|
| Access/identity | Gateway tools/list returns exactly four; summary POST actually reaches fixture under gateway bearer; missing/wrong/previous separate bearer denied. Forged argument callId/start/tenant cannot override headers; simultaneous calls remain isolated |
| Text boundaries/validation | Missing, null, wrong-type, empty/whitespace, 500, 501, >2,000 and multilingual text. Invalid text returns in-band INVALID_REQUEST without owner POST; schema maxLength is 500; valid text byte-for-byte unchanged after JSON decoding |
| Callback and structured data | Required ten-digit dictated mobile for CALLBACK_NOTED; no caller-ID copying; no appointmentId/transferredTo for callback; destination only on transfer outcomes; IDs retain format checks; EN/KN/HI primary mapping and unsupported-language omission |
| Stored/repeated/mismatched responses | Exact SAVED on 201; exact ALREADY_SAVED on same/different existing body with same callId; original stored body unchanged; mismatched callId, unreadable JSON, missing required CallSummary fields and unexpected success statuses are NOT_CONFIRMED |
| Failure precedence | 400 safe fields, missing/malformed trusted context, auth token/API 401/403, 429 Retry-After, pre-send connection failure, post-send timeout, 5xx, exhausted budget. Uncertain first send followed by 400/403 remains NOT_CONFIRMED |
| Retry and key isolation | Commit-then-disconnect then 200 returns ALREADY_SAVED with one stored record; at most one same-request transport retry and bounded auth refresh; exact same JSON/context across attempts; no summary key; all three booking mutations still carry stable keys and retain UNCERTAIN behaviour |
| Sensitive data | Unique synthetic name, phone and symptom/text markers absent from structured result, MCP text content, error text and captured formatted logs on success and each failure class. Malicious owner error.field/message/issue cannot reflect them. Safe callId, reason, retry delay and saved ID remain observable |
| Timing/independence | Slow-but-healthy summary above 300 ms can succeed within its own budget; dribbling/never-answering owner bounded; no Retry-After sleep. Knowledge transport raises if touched by summary. Availability/booking independence and clinical UNKNOWN policy stay green |
| Removal/configuration | Single-token production startup; header allowlists match; no old exported metadata; no old input/output keys; exact result key sets; no lifespan/fixture env dependency. Deploy create/upgrade dry-run emits no old secret creation/reference/deletion |
| Gateway/process | Wrong/missing fourth tool or stale input schema fails registration verification; payload remains private/team scoped and secrets redacted. Process e2e calls all four over HTTP. Read-only smoke lists summary but never invokes it |
| Generated documentation | Snapshot equals generated schema; input/output tables and all five outcome meanings agree; other three tool schemas structurally unchanged; outcome completeness test handles summary without nextStep |

The current `test_deploy.py` has mocks of our own helper functions; newly changed coverage will use HTTP boundaries or the assembled server and subprocess/dry-run outputs, not add more such mocks.

## 8. Verification commands after approval

- Focused: `uv run --directory services/mcp pytest tests/test_summary.py tests/test_ops_client.py tests/test_stubs.py tests/test_server.py tests/test_context.py tests/test_settings.py tests/test_deploy.py -q` (narrow further per red step).
- Every commit: `make test-fast`; record real red/green counts, not planned counts.
- Schema: `make schema > /tmp/call-summary-schema.json` then `cmp /tmp/call-summary-schema.json services/mcp/tests/contracts/mcp-tools.snapshot.json`.
- Full gate: `./scripts/test.sh` (frozen install, Ruff, hermetic tests, process e2e, wheel, production/stub Docker builds and image-exclusion checks). If Docker is unavailable, report builds unverified rather than rely on the script's skip message.
- Syntax/static: `bash -n deploy/azure/deploy.sh scripts/*.sh`; `uvx vulture services/mcp/src --min-confidence 80`; `git diff --check`; `docker compose --env-file .env.example -f deploy/docker-compose.yml --profile stubs config --quiet`.
- No standalone type-checker is configured. Report that fact; do not add an unconfigured dependency merely to claim type checking. Pydantic schema/validation tests are not described as static typing.
- Relevant smoke: process e2e against local fixtures; deployment create and existing-app upgrade dry-runs. No real deploy or summary writes to an unconfirmed tenant.
- Search all tracked source/config/tests/current docs for removed symbols, old summary outcome/field names, credentials/header/env references and blanket write rules. Categorize historical and negative-test exceptions explicitly; preserve unrelated booking/availability names.
- Run `.claude/agents/voice-safety-reviewer.md` and `latency-reviewer.md` on the complete diff with the approved new policy supplied, without editing those files. Resolve findings with red/green proof.

## 9. Integration effects, risk and owner questions

**Voice team:** schema/input/output breaking change, all four tools available through its ContextForge virtual server. Summary needs call ID/start time headers but no operation ID, verified caller ID or duration. First accepted text is final; an early or incomplete LLM summary cannot be replaced. It is not guaranteed to run after abrupt disconnect; that remains explicitly out of scope. The voice team owns agent behaviour and must validate whole-call coverage and handling of ALREADY_SAVED without claiming the later proposed text was stored.

**ContextForge owner:** rediscover the changed tool schemas, include the fourth tool in the intended private/team virtual server and scoped client permissions, update the passthrough header list, keep trusted headers under platform control. Admin/discovery success alone does not prove virtual-server client authorization. Confirm deployed gateway version/configuration, virtual-server ID and consuming-client access at rollout; no new gateway API is invented by this plan.

**Manoj:** existing POST /call-summaries and machine client retained. He must grant `calls.write` to the existing `mcp-gateway` client and confirm a synthetic tenant for live tests; neither changing our bearer nor writing arbitrary Key Vault values grants that scope. Confirm live natural-key deduplication is tenant-scoped and atomic under concurrent posts, and which noncontract status codes may occur. We can implement/test against the pinned contract now; we cannot infer these live guarantees or self-grant owner authorization.

**Shobhit:** no new service/API/config dependency and no summary call to knowledge. Symptoms are stored as provided in the summary, not interpreted or independently validated as clinical facts. Availability, UNKNOWN booking protection and explicit search_knowledge behaviour remain unchanged. Missing knowledge integration does not block this summary change.

**Security/privacy:** gateway authority intentionally expands to summary creation. Tenant remains fixed by deployment/owner credentials; trusted call IDs cannot come from model arguments. A compromised trusted gateway can choose call IDs, as before; this task adds no caller identity proof to summaries. Caller-provided mobile is contact data only. Summary text now intentionally contains sensitive health/contact details sent to the operational service, never result/logs. Provider retention/access policies remain Manoj's responsibility.

**Clinical/operational safety:** CALLBACK_NOTED still creates no appointment, transfer or callback task. Free text may be incomplete or inaccurate because the LLM composes it; no local medical interpretation or hidden knowledge gate is introduced. Removing the structured name/prefix means name inclusion is a described input expectation, not something MCP can independently verify.

**Latency:** one operational POST on a warm success path, shared pooled client, no extra reads/preflight service call. Separate default 8 s summary limit remains (`SUMMARY_DEADLINE_SECONDS`, current allowed range >0 through 60 s), including auth/retries. If awaited in the conversational path it can exceed the one-second caller-response target; this is an explicit retained exception, not a promised fast voice response. No live latency claim from fixture tests.

**Rollout/backward compatibility:** no shim. Old direct finalizers, two-token clients, old input/result consumers and cached gateway schemas will break. Future deployment needs coordinated image + gateway rediscovery/virtual-server membership + voice-client update; avoid mixed old/new revisions serving the same registration. Retain the old image/secret until rollback is no longer needed. A rollback cannot undo summaries already stored under callId. This task will prepare assets/instructions only; separate explicit approval is required for merge and deployment.

**Unresolved owner facts are not code blockers:** scope grant, designated live test tenant, real service deduplication evidence and actual gateway/voice-path validation remain deployment acceptance gates. No endpoint/key changes are presumed necessary, and no new credentials are requested from Shobhit for this feature.

## 10. Hand-back and readiness

Provide deletion proof with explicit exceptions, red/green output per behaviour, all commands and actual results, diff stat/net production-source lines, per-file changes, reviewer findings, tests not run and external dependencies. List `mcp-lifecycle-token` as unused but not deleted. Distinguish ready for code review/merge from ready to deploy: local completion can support merge review, while live writes and the consumer cutover remain unverified until owner inputs and explicit deployment approval exist.

**Approved 4 October 2026 with the corrections below; implementation in progress.**

Approval corrections also require the mismatch event `summary_call_id_mismatch`, no committed docs/superpowers folder, evidence in this implementation directory, and both schema-version bumps identified in the hand-back. These corrections supersede any broader phrasing above.
