# Call-summary hand-back — 4 October 2026

Implementation baseline: `8c2b60a`. Reviewed implementation head: `f1ea88e`; later commits contain
only evidence and this report. No push, merge, deployment, live write or Azure secret deletion.
Existing untracked `temp/` remains untouched. No reviewer-agent files or date rules were changed.

## Result and readiness

The approved whole-call summary implementation is complete locally: all four tools share gateway
authentication; summaries forward exact nonblank text up to 500 characters, use Manoj's call-ID
deduplication, and return only five outcomes plus field names for INVALID_REQUEST. All old runtime
summary-access, composition, duration and idempotency-header paths are removed.

**Ready for code review; not approved for deployment.** The previously disclosed summary protocol-error
privacy issue is now fixed following explicit user approval. FastMCP/Pydantic still validates inputs;
a small error-presentation middleware replaces summary ValidationError text with a fixed, safe message.
It neither adds argument validation nor changes tool schemas, caps, auth, deadlines, retries or writes.
The original failing probe remains historical evidence; the new permanent HTTP regression suite is green.

### Approved privacy follow-up

Baseline for this follow-up: `a0a2aee`. Changes are limited to server error formatting, HTTP regression
tests, current privacy documentation and evidence. `SummaryErrorRedaction` catches only framework
ValidationError for record_call_summary and raises a fixed ToolError from None. It does not inspect or
copy the rejected values, error locations, messages or context. This matters because an unexpected
argument's *name* can itself contain patient information. No new dependency or configuration is needed.

[15-error-privacy.txt](call-summary-evidence/15-error-privacy.txt) contains the actual red and green runs:

```text
$ uv run --directory services/mcp pytest tests/test_server.py -q -k invalid_summary_does_not_echo
7 failed, 30 deselected, 2 warnings
EXIT: 1
$ uv run --directory services/mcp pytest tests/test_server.py -q -k 'invalid_summary_does_not_echo or summary_http_boundaries or summary_length'
15 passed, 22 deselected, 2 warnings
EXIT: 0
```

The seven cases are object/list/number summary values, >2000 text, an invalid intent, wrong-type contact,
and an unexpected argument name containing private text. Each asserts no echo in the full protocol
result or logs, explicit error status, and zero summary POSTs. Existing tests preserve valid exact text,
500 accepted, 501/2000 in-band INVALID_REQUEST, and >2000 framework rejection. No custom validation
boundary, monkeypatch, duplicate validator or service call was added. Schema remains 2026-10-04.2;
the two prior schema bumps below remain the complete schema history for this change.

Voice-safety review: 17 focused HTTP tests passed; latency review found no added I/O or deadline change.
Full verification for this follow-up is in [16-privacy-full.txt](call-summary-evidence/16-privacy-full.txt);
static/schema checks are in [17-privacy-static.txt](call-summary-evidence/17-privacy-static.txt).
No live service, Azure, gateway registration or voice deployment was exercised.

```text
$ ./scripts/test.sh
All checks passed!
462 passed, 11 deselected, 2 warnings in 27.47s
2 passed, 471 deselected, 2 warnings in 2.43s
== package build
Successfully built frontdesk_mcp-0.1.0.tar.gz and frontdesk_mcp-0.1.0-py3-none-any.whl
== production image build (no stubs, no fixtures, no dev dependencies)
== development stubs image build (compose profile stubs)
== external gates not run: no profile loaded
== all suites passed
EXIT: 0
```

The two existing Authlib deprecation warnings remain. `make test-fast` independently passed 462 tests.
`make schema` still matches the pinned snapshot and `uvx vulture` reported no findings. Runtime change
is 17 added lines; the complete summary migration is now 118 source lines smaller than 8c2b60a.

Root cause: FastMCP 2.14.7 ToolManager deliberately rethrows Pydantic ValidationError unchanged,
including when its general error-masking setting is enabled; MCP turns the exception into error text.
The fix uses FastMCP's middleware extension point solely for exception presentation in server.py.
No schema/TypeAdapter monkeypatch, framework upgrade, alternate parser or regular-expression scrubbing.

## Approved details and effects

- **One token:** gateway lists and invokes all four tools; missing/wrong/old second bearer receives 401.
  Trusted call ID/start are headers only, isolated across concurrent calls. Other identity, booking
  verification and operation-ID protections remain intact.
- **Eight arguments:** intent, outcome, summaryText, callerMobile, language, doctorId, appointmentId,
  transferredTo. Name, date/time, callback details and symptoms can occur in the whole-call text.
  No prefix, trimming or normalization. CALLBACK_NOTED requires valid mobile, rejects appointment
  and transfer fields, and creates no appointment or callback task.
- **Validation:** advertised maxLength 500 is set once after registration. Service checks nonblank/≤500;
  501–2000 returns in-band INVALID_REQUEST. Missing/wrong-type/>2000 remains framework validation.
- **Outcomes:** verified 201→SAVED; verified 200 for our call→ALREADY_SAVED even if submitted payload differs;
  local/owner 400→INVALID_REQUEST; uncertainty/transient/malformed/wrong-call→NOT_CONFIRMED;
  missing trusted context or definite credential refusal→NOT_SAVED. Both successes parse CallSummary.
  fields appears only for INVALID_REQUEST, with safe known field names; no stored body or ID in results.
- **Replay:** no Idempotency-Key on summary requests, including retries. Owner first accepted callId is
  final. A lost response followed by owner 200 is ALREADY_SAVED. Bookings keep their operation keys.
  A previous uncertain send takes precedence over a later refusal. Shared 401-only refresh unchanged;
  definite 403 does not trigger refresh. Token 403 is now AUTH, correcting summary NOT_CONFIRMED to NOT_SAVED.
  Narrow shared effect: booking diagnostic reason for token 403 becomes AUTH; outcome/nextStep unchanged.
- **Diagnostics:** mismatch event is exactly `summary_call_id_mismatch`. Reasons/retry delay are logged
  under callId. SAVED logs only an opaque-ID-shaped summaryId; unexpected owner-ID formats are omitted
  without changing SAVED. No text/mobile/name/raw upstream error is logged by these paths.
- **Latency:** same pooled clients, warm token cache and retry logic; no new upstream round trip.
  Summary default 8 s total/per-exchange budget is separate from scheduling/knowledge's 300 ms share.
  There is no sub-second summary or real-voice latency claim.
- **Gateway/release:** registration verifies four tools and full input schemas, catches stale 500/2000
  constraints and required fields, refreshes once then fails on persistent drift. Smoke remains read-only.
  The new deploy revision omits the second token setting and reference; it does not delete existing secrets.
- **Two version bumps:** `2026-10-03.3 → 2026-10-04.1` for summary arguments/results, then
  `2026-10-04.1 → 2026-10-04.2` for gateway-access metadata. Snapshot and VOICE-TEAM match the final version.

## Red → green evidence

Each link contains the actual command, pasted output and exit status, including intermediate mistakes
and their corrected reruns. There are no skipped/xfail tests added to get green. Existing log-privacy
characterization passed before changes; no false red is claimed for that already-working behavior.

| Item | Observed red / reason | Observed green / evidence |
|---|---|---|
| Natural-key summary writes and stub | 3 failed: header still sent, stub different-call same-header conflict | Fast 413 passed; [01-natural-key](call-summary-evidence/01-natural-key.txt) |
| Request/result contract | 61 failed, 18 passed, plus snapshot 2 failed; old required callback-name/text composition/outcomes | Focused 82 passed; fast444 then450passed after review; [02-contract](call-summary-evidence/02-contract.txt) |
| Owner status mapping without old callback-name gate masking it | 26 failed against restored old service with GENERAL_INFO fixture | Included in final 456 passed; [02-owner-mapping-red](call-summary-evidence/02-owner-mapping-red.txt) |
| Unsafe owner IDs in diagnostics | 2 failed, 2 passed: raw PII-like IDs in saved log | Fixed, final suite green; [02-log-privacy](call-summary-evidence/02-log-privacy.txt) |
| Token 400/401 refusal | 2 failed: old COULD_NOT_RECORD | Final token 400/401/403 cases pass; [02-token-refusal](call-summary-evidence/02-token-refusal.txt) |
| Duration removal | Corrected red 4 failed: parsed duration and forwarded header | Fast 451 passed; [03-duration](call-summary-evidence/03-duration.txt) |
| Single gateway access | HTTP 5 failed: summary hidden/refused, old bearer accepted; smoke 9 failed, 1 passed | Fast 448 passed after factual-prose correction; [04-access](call-summary-evidence/04-access.txt) |
| Production requires only gateway token | 2 failed: old second-token guard | Fast 446 passed; [05-settings](call-summary-evidence/05-settings.txt) |
| Deployment/registration | Secret removal red 1 failed; corrected registration2 failed against old three-tool check | Fast 447 passed and process2passed; [06-deployment](call-summary-evidence/06-deployment.txt), [06-process](call-summary-evidence/06-process.txt) |
| Full input-schema drift | 2 failed, 2 passed: stale maxLength/required accepted | Fast 449 passed; [06-schema-drift](call-summary-evidence/06-schema-drift.txt) |
| Token 403 refusal | 1 failed, 2 passed: NOT_CONFIRMED despite zero writes | Fast 456 passed; [10-review-fixes](call-summary-evidence/10-review-fixes.txt) |
| HTTP input boundaries and exact multilingual text | 6 failed after temporary removal/alteration of cap/required/nonblank/exact-text boundaries; original source restored | All 6 pass in final suite; [10-http-mutation](call-summary-evidence/10-http-mutation.txt) |

The HTTP mutation temporarily made text optional/any, converted null to empty, raised the request cap,
removed blank validation and prefixed/trimmed the outgoing body. Every corresponding test failed.
None of those mutations remains in source. Input/log fixtures contain synthetic names and numbers only.
The original protocol-privacy probe records the pre-fix behavior; the approved follow-up now has permanent passing regression tests.

## Original implementation verification (before privacy follow-up)

Original full-run output: [13-final-full.txt](call-summary-evidence/13-final-full.txt).

```text
$ ./scripts/test.sh
All checks passed!
456 passed, 11 deselected, 2 warnings
2 passed, 465 deselected, 2 warnings
Successfully built frontdesk_mcp-0.1.0.tar.gz and frontdesk_mcp-0.1.0-py3-none-any.whl
== production image build (no stubs, no fixtures, no dev dependencies)
== development stubs image build (compose profile stubs)
== external gates not run: no profile loaded
== all suites passed
EXIT: 0
```

Two existing Authlib deprecation warnings remain.11 deselected = 2 process tests plus 9 external tests;
process tests run in their own stage. External tests were not silently skipped or represented as passing.
No owner credentials or live services were used for this change.

[14-final-static.txt](call-summary-evidence/14-final-static.txt) records:

```text
uvx vulture services/mcp/src --min-confidence 80   EXIT: 0, no findings
make schema                                     MATCH pinned snapshot,2026-10-04.2
bash -n deploy/azure/deploy.sh                   EXIT: 0
docker compose ... --env-file .env.example --profile stubs config --quiet  EXIT: 0
git diff --check                                EXIT: 0
git diff 8c2b60a -- .claude/agents                empty
git ls-files docs/superpowers                    empty
```

Ruff runs over adapter, fixtures/tests and deployment code. The repository configures no separate
static type checker; none was invented or claimed. Package/wheel and both Docker builds succeeded.
Local process smoke passed; deployed/Azure/ContextForge/voice smoke was not run.

## Mandatory removal and quality checklist

- [x] Availability/booking remain independent of knowledge; existing zero-call and absent-provider tests
  are included in the final green suite. No routing gate or voice behavior code introduced.
- [x] Deleted access.py, principal context, second-bearer branch/config, tool tag/schema metadata,
  duration parser/header/context field, summary composition/name/date arguments, summary_key, old result
  diagnostics and payload-comparison branch, summary header-key handling. Replaced old access tests.
- [x] Search proof: [11-removal-audit.txt](call-summary-evidence/11-removal-audit.txt) shows zero matches in
  tracked runtime/dev/deploy/config for lifecycle/LIFECYCLE, X-Call-Duration-Seconds, durationSeconds,
  callerName, compose_text and summary_key; requestedDate is absent from the summary surface.
- [x] Remaining repository matches are intentional: negative removal/auth assertions in test_context,
  test_server and test_deploy; unrelated appointment lifecycle tests; PLAN's appointment lifecycle and
  platform operation-context wording; availability.requestedDate in code/schema/docs; ADR/report removal
  descriptions; pinned owner contracts/overlay; dated historical reports/evidence; unchanged reviewer prompts.
  This is zero obsolete active behavior, not a claim that historical text and proof assertions contain no names.
- [x] Production source including the privacy fix: +106/−224, **net −118 lines** against 8c2b60a. Diff statistics and per-file list below.
- [x] TDD behavior evidence pasted above and linked; final full run, schema check, lint/build checks green.
- [x] CLAUDE, PLAN, TARGET-STATE, DECISIONS and current operational docs updated. No docs/superpowers files.
- [x] VOICE-TEAM is the current contract. The old addendum's voice-code deliverable is superseded by
  the approved contract-only boundary; no LiveKit agent implementation or prompts belong in this repo.
- [x] Voice-safety and latency reviewers ran at each source/deploy stage and over the full final diff.
  Findings fixed: unsafe ID logs, missing token-refusal proof, gateway schema comparison, token 403 mapping,
  HTTP boundary proof and stale after-call prose. Final safety recheck 27 passed; final latency review no
  concrete regression. No measured benchmark claim. Reviewer files remain unchanged as explicitly required.
- [x] Summary framework error-response privacy and log privacy verified after explicit follow-up approval.

## External actions and rollout

1. Manoj: grant calls.write to the existing registered MCP client; authorize a synthetic tenant/boards
   for the external write journey. Existing machine credentials remain in Key Vault. Do not use another
   client to bypass the grant. Verify summary 201/200/403 against the designated service after approval.
2. Gateway/voice: coordinate the new image/config and schema 2026-10-04.2; include summary in the virtual
   server, forward five trusted headers, refresh cached schemas/descriptions and verify concurrent isolation.
   Tool timing, complete final summary text and real caller-audio acceptance belong to the voice team.
3. Knowledge owner: contract/host/auth still pending; it does not block summaries or scheduling.
4. Unused deployment secret: **mcp-lifecycle-token** in the existing vault/app. It was not deleted, read,
   rotated or recreated here. Review ownership/rollback and separately authorize retirement. No Azure
   resources were cleaned up in this task. Old image rollback requires its old credential/config/schema.

No live end-to-end, owner permissions, gateway version/API compatibility, cloud cutover, voice safety or
latency acceptance is claimed. Exact schema comparison intentionally fails on differences; validate
any gateway-side normalization against the actual instance, not by weakening the check speculatively.

## Per-file change inventory

Paths below are repository-relative. Verification references use the suites named above.

| File | Change / verification |
|---|---|
| `.env.example` | Remove second-token setting; compose/config checks. |
| `CLAUDE.md` | Current auth, trusted headers, summary honesty/deadline rules. |
| `README.md` | Single-token architecture and endpoint guidance. |
| `deploy/azure/deploy.sh` | Remove old credential wiring; retain cloud secrets; test_deploy dry runs. |
| `deploy/azure/smoke.py` | Four-tool discovery; read-only calls only; server/process smoke. |
| `deploy/contextforge/register.py` | Five forwarded headers, four tools, full input-schema drift; test_deploy. |
| `deploy/docker-compose.yml` | Remove second-token environment; compose validation. |
| `docs/DECISIONS.md` | Align current architecture/interface/operational guidance with the approved summary contract. |
| `docs/architecture/TARGET.md` | Align current architecture/interface/operational guidance with the approved summary contract. |
| `docs/handover/AZURE.md` | Align current architecture/interface/operational guidance with the approved summary contract. |
| `docs/handover/CONTEXTFORGE.md` | Align current architecture/interface/operational guidance with the approved summary contract. |
| `docs/handover/ONBOARDING.md` | Align current architecture/interface/operational guidance with the approved summary contract. |
| `docs/handover/OWNER-INTEGRATION-MESSAGES.md` | Align current architecture/interface/operational guidance with the approved summary contract. |
| `docs/handover/TESTING.md` | Align current architecture/interface/operational guidance with the approved summary contract. |
| `docs/handover/VOICE-TEAM.md` | Align current architecture/interface/operational guidance with the approved summary contract. |
| `docs/handover/mcp-only/PLAN.md` | Align current architecture/interface/operational guidance with the approved summary contract. |
| `docs/handover/mcp-only/README.md` | Align current architecture/interface/operational guidance with the approved summary contract. |
| `docs/handover/mcp-only/TARGET-STATE.md` | Align current architecture/interface/operational guidance with the approved summary contract. |
| `docs/handover/mcp-only/implementation/CALL-SUMMARY-PLAN.md` | Approved implementation plan and user corrections; tracked outside .context. |
| `docs/handover/mcp-only/implementation/OPEN-DEPENDENCIES.md` | Align current architecture/interface/operational guidance with the approved summary contract. |
| `services/mcp/README.md` | Align current architecture/interface/operational guidance with the approved summary contract. |
| `services/mcp/dev/bench.py` | Remove obsolete second-token constructor argument. |
| `services/mcp/dev/demo.py` | Single-token whole-call demo, no duration/name argument. |
| `services/mcp/dev/frontdesk_stubs/ops.py` | First callId final201/200, no summary key handling; test_stubs. |
| `services/mcp/src/frontdesk_mcp/access.py` | Deleted obsolete gate and tag; HTTP auth tests replace split tests. |
| `services/mcp/src/frontdesk_mcp/cli.py` | Remove access-split export metadata; snapshot. |
| `services/mcp/src/frontdesk_mcp/clock.py` | Correct summary budget comment; deadline logic unchanged. |
| `services/mcp/src/frontdesk_mcp/config.py` | Remove second-token field/guards; test_settings. |
| `services/mcp/src/frontdesk_mcp/context.py` | Remove principal and duration parsing; test_context/HTTP identity. |
| `services/mcp/src/frontdesk_mcp/ops_client.py` | Optional write key; no summary key; token 403 AUTH; client/summary/booking tests. |
| `services/mcp/src/frontdesk_mcp/outcomes.py` | Five compact summary outcomes; omit fields unless invalid; wire tests. |
| `services/mcp/src/frontdesk_mcp/packs/healthcare.json` | Whole-call factual descriptions and eight arguments; snapshot/interface tests. |
| `services/mcp/src/frontdesk_mcp/prompt.py` | Two version bumps and one gateway authentication fact. |
| `services/mcp/src/frontdesk_mcp/server.py` | One constant-time bearer check; no gate; summary-only validation error redaction; HTTP auth/isolation/privacy. |
| `services/mcp/src/frontdesk_mcp/summary.py` | Exact text, validation, safe diagnostics, owner mapping/deduplication; test_summary. |
| `services/mcp/src/frontdesk_mcp/tools.py` | Eight arguments, one-time advertised500 cap, no access tag; HTTP/schema tests. |
| `services/mcp/tests/conftest.py` | Single gateway credential fixture. |
| `services/mcp/tests/contracts/mcp-tools.snapshot.json` | Generated tool contract2026-10-04.2; make schema matches. |
| `services/mcp/tests/harness.py` | Remove duration-header fixture parameter. |
| `services/mcp/tests/test_context.py` | Updated behavioral and contract coverage; included in named local suite (external tests updated, not run). |
| `services/mcp/tests/test_deploy.py` | Updated behavioral and contract coverage; included in named local suite (external tests updated, not run). |
| `services/mcp/tests/test_e2e_processes.py` | Updated behavioral and contract coverage; included in named local suite (external tests updated, not run). |
| `services/mcp/tests/test_external.py` | Updated behavioral and contract coverage; included in named local suite (external tests updated, not run). |
| `services/mcp/tests/test_external_transport.py` | Updated behavioral and contract coverage; included in named local suite (external tests updated, not run). |
| `services/mcp/tests/test_ops_client.py` | Updated behavioral and contract coverage; included in named local suite (external tests updated, not run). |
| `services/mcp/tests/test_server.py` | Updated behavioral and contract coverage; included in named local suite (external tests updated, not run). |
| `services/mcp/tests/test_settings.py` | Updated behavioral and contract coverage; included in named local suite (external tests updated, not run). |
| `services/mcp/tests/test_stubs.py` | Updated behavioral and contract coverage; included in named local suite (external tests updated, not run). |
| `services/mcp/tests/test_summary.py` | Updated behavioral and contract coverage; included in named local suite (external tests updated, not run). |
| `docs/handover/mcp-only/implementation/call-summary-evidence/*.txt` | Actual red/green, mutation, build, schema and removal evidence. |

## Diff statistics (implementation plus recorded evidence at report generation)

```text
 .env.example                                       |   4 +-
 CLAUDE.md                                          |   8 +-
 README.md                                          |   4 +-
 deploy/azure/deploy.sh                             |  19 +-
 deploy/azure/smoke.py                              |  38 +-
 deploy/contextforge/register.py                    |  26 +-
 deploy/docker-compose.yml                          |   1 -
 docs/DECISIONS.md                                  |  39 +-
 docs/architecture/TARGET.md                        |   5 +-
 docs/handover/AZURE.md                             |  33 +-
 docs/handover/CONTEXTFORGE.md                      |  31 +-
 docs/handover/ONBOARDING.md                        |   4 +-
 docs/handover/OWNER-INTEGRATION-MESSAGES.md        |  25 +-
 docs/handover/TESTING.md                           |  23 +-
 docs/handover/VOICE-TEAM.md                        |  70 +-
 docs/handover/mcp-only/PLAN.md                     |  66 +-
 docs/handover/mcp-only/README.md                   |   5 +-
 docs/handover/mcp-only/TARGET-STATE.md             |   8 +-
 .../mcp-only/implementation/CALL-SUMMARY-PLAN.md   | 206 +++++
 .../mcp-only/implementation/OPEN-DEPENDENCIES.md   |  10 +-
 .../call-summary-evidence/01-natural-key.txt       | 133 +++
 .../call-summary-evidence/02-contract.txt          | 946 +++++++++++++++++++++
 .../call-summary-evidence/02-log-privacy.txt       |  35 +
 .../call-summary-evidence/02-owner-mapping-red.txt | 456 ++++++++++
 .../02-protocol-privacy-probe.txt                  |  42 +
 .../call-summary-evidence/02-token-refusal.txt     |  49 ++
 .../call-summary-evidence/03-duration.txt          | 152 ++++
 .../call-summary-evidence/04-access.txt            | 668 +++++++++++++++
 .../call-summary-evidence/05-settings.txt          | 268 ++++++
 .../call-summary-evidence/06-deployment.txt        | 328 +++++++
 .../call-summary-evidence/06-process.txt           |  16 +
 .../call-summary-evidence/10-http-mutation.txt     | 359 ++++++++
 .../call-summary-evidence/10-review-fixes.txt      |  63 ++
 .../call-summary-evidence/11-removal-audit.txt     | 155 ++++
 services/mcp/README.md                             |  15 +-
 services/mcp/dev/bench.py                          |   2 +-
 services/mcp/dev/demo.py                           |  13 +-
 services/mcp/dev/frontdesk_stubs/ops.py            |  15 +-
 services/mcp/src/frontdesk_mcp/access.py           |  42 -
 services/mcp/src/frontdesk_mcp/cli.py              |   2 -
 services/mcp/src/frontdesk_mcp/clock.py            |   2 +-
 services/mcp/src/frontdesk_mcp/config.py           |  20 +-
 services/mcp/src/frontdesk_mcp/context.py          |  20 +-
 services/mcp/src/frontdesk_mcp/ops_client.py       |  16 +-
 services/mcp/src/frontdesk_mcp/outcomes.py         |  18 +-
 .../mcp/src/frontdesk_mcp/packs/healthcare.json    |  10 +-
 services/mcp/src/frontdesk_mcp/prompt.py           |   4 +-
 services/mcp/src/frontdesk_mcp/server.py           |  31 +-
 services/mcp/src/frontdesk_mcp/summary.py          | 135 +--
 services/mcp/src/frontdesk_mcp/tools.py            |  15 +-
 services/mcp/tests/conftest.py                     |   2 +-
 .../mcp/tests/contracts/mcp-tools.snapshot.json    | 104 +--
 services/mcp/tests/harness.py                      |   4 +-
 services/mcp/tests/test_context.py                 |  18 +-
 services/mcp/tests/test_deploy.py                  | 120 +--
 services/mcp/tests/test_e2e_processes.py           |  22 +-
 services/mcp/tests/test_external.py                |  10 +-
 services/mcp/tests/test_external_transport.py      |  10 +-
 services/mcp/tests/test_ops_client.py              |  18 +-
 services/mcp/tests/test_server.py                  | 142 +++-
 services/mcp/tests/test_settings.py                |  16 +-
 services/mcp/tests/test_stubs.py                   |  16 +-
 services/mcp/tests/test_summary.py                 | 430 +++++-----
 63 files changed, 4660 insertions(+), 907 deletions(-)
```

The statistics above predate the approved privacy follow-up (+17 runtime lines); the current source reduction is 118 lines.
