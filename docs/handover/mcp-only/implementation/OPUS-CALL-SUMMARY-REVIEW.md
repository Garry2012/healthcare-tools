# Opus review: call-summary change (8c2b60a..7a64f9b), 4 October 2026

Scope: the actual code diff from `8c2b60a` to `7a64f9b` (12 commits; 47 non-evidence files, +815/−901), checked against `.context/astra-prompt-call-summary.md`, `.context/astra-brief-addendum-code-quality.md`, `CALL-SUMMARY-HAND-BACK.md`, and Garima's later decisions:
- one gateway bearer for all four tools;
- an outer summary cap of 2,000, a service limit of 500 returning an in-band INVALID_REQUEST, and an advertised maxLength of 500;
- the unchanged 401-only token refresh;
- a definite 403 is NOT_SAVED unless an earlier send remains uncertain;
- private input is suppressed in summary protocol errors, with no custom argument validation.

This is a review only. No code, reviewer agents, Azure, merge or push were touched.

## Verdict

**Ready to merge, after one doc-label nit at most. No code changes are required.** There are no High or Medium code defects. One Medium item is an external verification risk in the ContextForge drift check, not a defect in the code as written. The remaining findings are Low.

## What I ran

| Check | Result |
|---|---|
| `./scripts/test.sh` at 7a64f9b | **Exit 0.** Ruff clean; hermetic 462 passed, 11 deselected; process e2e 2 passed; wheel and sdist built; production and stub images built; external gates not run (no profile loaded) |
| `make schema` vs `tests/contracts/mcp-tools.snapshot.json` | **Byte-identical** (`cmp`). Schema `2026-10-04.2`; no tool carries `lifecycle`; summary `summaryText.maxLength` = 500; output schema `{outcome (5 values) required, fields optional}` |
| Files per commit | 8, 10, 10, 10, 10, 7, 9, 5, 8, 10, 10, 9: **all ≤10** |
| Fast suite at each code commit (temporary detached worktree, removed afterwards) | See the per-commit table at the end |
| Obsolete-reference search (current files, excluding historical reports, the pinned contract and the archive) | Clean. The only hits are legitimate: booking's own `COULD_NOT_RECORD`/`SAY_COULD_NOT_RECORD`; negative tests that assert absence (`test_context.py:110`, `test_server.py:27,94,152`, `test_deploy.py:177`); `AZURE.md:97`, which names `mcp-lifecycle-token` as unused; `DECISIONS.md:82`; "appointment lifecycle" wording; and `.claude/agents/voice-safety-reviewer.md:3,12,21` (not to be edited; see L5) |
| Recorded red evidence | Read the hand-back table and the `call-summary-evidence/` links. The privacy red (7 failed, then 15 passed), status mapping, token 403, duration, access, schema drift and the HTTP mutation runs are consistent with the tests now in the tree |

## Requirement-by-requirement inspection (code, not report)

| Area | Evidence in code | Status |
|---|---|---|
| Authentication | `server.py` `BearerAuth`: one `hmac.compare_digest` against the gateway bearer. Development with no token is open, as before. `access.py`, `principal_var` and `MCP_LIFECYCLE_BEARER_TOKEN` are deleted. Production still refuses a missing gateway token (`config.py`) | ✓ |
| Trusted headers | `context.py` `PASSTHROUGH_HEADERS` = 5 (duration removed), and `register.py` `PASSTHROUGH` matches (asserted in `test_deploy.py`). Call id and start time come only from headers; `record()` returns NOT_SAVED when either is missing | ✓ |
| Exact text | `build_body` puts `request.summaryText` in unchanged; `compose_text` is gone. `_validate` refuses blank text or `len > 500`. The HTTP test `multilingual-exact` asserts the posted body equals the input, including leading and trailing whitespace and newlines | ✓ |
| Caps | The tool argument and `SummaryRequest` keep `max_length=2000` (framework). The advertised `maxLength` is set to 500 after registration (`tools.py:196`). 501 and 2000 give an in-band `{"outcome":"INVALID_REQUEST","fields":["summaryText"]}`; 2001 is a framework error (`test_server.py:429-492`) | ✓ |
| Five outcomes | `outcomes.SummaryResult`: `outcome` plus `fields`, with a `model_serializer` that drops `fields` unless INVALID_REQUEST. `nextStep`, `summaryId`, `detail` and `retryAfterSeconds` are removed from the wire | ✓ |
| Status mapping | `summary.record`: 201 → SAVED; 200 → ALREADY_SAVED; 400 → INVALID_REQUEST with owner field names intersected with known fields; other Rejected 4xx and unexpected 2xx → NOT_CONFIRMED; `Unavailable("AUTH")` (401 after one refresh, 403) → NOT_SAVED; other Unavailable, UncertainWrite and Malformed → NOT_CONFIRMED. The parameterised test covers 200, 201, 202, 400, 401, 403, 404, 409, 429, 500, 502, 503 and 504 | ✓ |
| Call-id deduplication | `create_call_summary` passes `key=None`, so `_write` sends no `Idempotency-Key`. Bookings still pass their keys (asserted). `stored.callId != ctx.call_id` → NOT_CONFIRMED and `summary_call_id_mismatch`, checked for both 200 and 201. There is no body comparison | ✓ |
| Retry uncertainty | `_write` is unchanged apart from the optional header: `sent` precedence is intact, and a later 400/401/403/429/503 after an unanswered send raises UncertainWrite → NOT_CONFIRMED (`test_summary.py:183`). Commit, then a lost response, then a 200 gives ALREADY_SAVED with one stored record and identical request bodies (`test_summary.py:192`) | ✓ |
| 401/403 policy | The refresh still happens only on API 401 (`ops_client.py:281`). A 403 → `_body` → AUTH → NOT_SAVED with no refresh. The token endpoint now treats 403 as AUTH as well (`ops_client.py:173`); see L3 | ✓ |
| Privacy | `_failure` logs only callId, outcome, reason and retryAfterSeconds. SAVED logs `summaryId` only when it matches `_LOG_ID`. `SummaryErrorRedaction` turns a framework `ValidationError` for this tool only into a fixed `ToolError … from None`. HTTP tests cover object, list and number text, the outer cap, a bad enum, a wrong-type contact and a private unexpected key. They assert no marker appears in the full protocol result, caplog or captured stdout/stderr, and that zero POSTs are made | ✓ |
| Latency | One POST and the same pooled client; no new round trip or preflight. The summary keeps its own 8 s invocation and per-exchange cap (`Deadline(summary, cap=summary)`); the 0.30 s share for other tools is unchanged. A slow-but-healthy owner (0.4 s) still gives SAVED | ✓ |
| Booking and date rule | No diff in `availability.py`, `booking.py` or `board_scope.py`. The `prompt.py` date sentence is unchanged. All booking, availability and knowledge suites are green | ✓ |
| Deployment assets | `deploy.sh` stops creating, reading or referencing `mcp-lifecycle-token`. Upgrade uses `--replace-env-vars`, so the old `MCP_LIFECYCLE_BEARER_TOKEN` variable is dropped from the new revision, while the secret stays attached (intended, for rollback). `smoke.py` expects four tools and never calls the summary tool. `docker-compose.yml` and `.env.example` are cleaned | ✓ |
| Docs | `CLAUDE.md` rules, `VOICE-TEAM.md` (eight arguments, five outcomes, the 8 s limit stated at line 262, headers), `CONTEXTFORGE.md` (five headers, four tools), `AZURE.md`, `TESTING.md`, `DECISIONS.md` and `OWNER-INTEGRATION-MESSAGES.md` (the `calls.write` request) are consistent with the code | ✓ |

## Findings

### Medium

**M1. The ContextForge drift check now requires byte-equal input schemas, and that is unverified against a real gateway.** External verification risk, not a code defect.
- **Where:** `deploy/contextforge/register.py:100`. It changed from comparing property-name sets to `schema != tool["inputSchema"]`.
- **Risk:** if ContextForge stores or returns `input_schema` with any normalisation, `verify()` reports drift on every run, triggers a refresh, then exits with "persistent drift". That blocks registration even though the schemas are equivalent. Normalisation could mean added `title`, `$schema` or `additionalProperties`, reordered `anyOf`, or dropped `default: null`.
- **Test coverage:** `test_deploy.py:112` uses fabricated gateway rows that echo the schema exactly, so it cannot show this. No evidence file shows a real `/v1/tools` response.
- **Reproduce:** register against the real ContextForge instance and compare `GET /v1/tools?include_inactive=true` `input_schema` with `make schema` output for the same tool.
- **Fix:** before relying on the script for release, capture one real `/v1/tools` row. If ContextForge normalises, compare a normalised projection (property names, `required`, and per-property `type`, `enum` and `maxLength`). That still catches the stale 500/2000 and required-field drift the change intended to catch.

### Low

**L1. `register.py:184` still prints "conversational tools:" for all four tools.** A cosmetic leftover from the split. Fix: print "tools:".

**L2. NOT_CONFIRMED for an unexpected status logs no status code.**
- **Where:** `summary.py:111,120`. The reason is `UNEXPECTED_STATUS`, and `ops_client._rejection` does not log, so an operator can't tell a 404 from a 409 or a 202.
- **Reproduce:** the `test_owner_statuses_are_mapped_without_returning_diagnostics[404]` case; the log has `reason=UNEXPECTED_STATUS` and no status.
- **Fix:** add the integer status to the `_failure` log fields. It is safe: no caller data.

**L3. Token-endpoint 403 is now AUTH for every operation (`ops_client.py:173`), not just summaries.**
- Bookings and reads get reason AUTH instead of UPSTREAM with retry-after. The hand-back says outcomes and nextStep are unchanged, and the booking suite is green.
- This is a deliberate, narrow shared change and reasonable (a refused credential is not transient). Listed for awareness; no change needed.

**L4. `_LOG_ID` (`summary.py:25`) encodes an assumed owner id shape (`cs_…` or a UUID).**
- Diagnostic only: SAVED is unaffected, and an unexpected format is just not logged. Manoj's contract only gives the example `cs_0107`.
- Fine as is. If his live ids differ, SAVED logs will lack the id. Confirm on the first live write.

**L5. `.claude/agents/voice-safety-reviewer.md:3,12,21` still describes the lifecycle principal and "lifecycle timing".**
- Correctly left unedited per instructions. It must be updated (with Garima's approval) before that reviewer is next used, or it will flag the new single-token design as a defect.

**L6. Two stale test names, no behavioural impact.**
- `test_ops_client.py:282` `test_call_summary_distinguishes_stored_from_replayed`: "replayed" is no longer a summary outcome.
- `test_stubs.py:125` is booking and fine.
- Rename when next touched.

### Not defects (checked)

- **Stub `create_summary` returns 200 for an existing callId before validating the new body.** The contract is silent on order; this matches "replaces nothing, returns the stored summary". OK as a fixture.
- **Over-2000 text is a protocol error, not INVALID_REQUEST.** This is the approved outer-cap design; its message is generic and redacted.
- **INVALID_REQUEST from an owner 400 with no recognised field names returns `fields: []`.** Documented in the plan; safe.
- **`idempotentHint=True` remains accurate:** repeating the call cannot change stored state.

## External dependencies (not code defects)

1. **Manoj: grant `calls.write` to `mcp-gateway`.** His Teams reply offered it; it is not yet confirmed. Until then every live summary is NOT_SAVED (403 or 401).
2. **Manoj: confirm `jayashree`, or another tenant, as the synthetic tenant** before any live summary write.
3. **Manoj: questions raised in conversation and not yet in `OWNER-INTEGRATION-MESSAGES.md`:**
   - which status a token without the scope gets (403 or 401);
   - whether the `voice-platform` client is still needed, and why it has `calls.read`;
   - which `outcome` a call with several results should use;
   - rotating the secrets shared in Teams;
   - whether call-id deduplication is atomic under concurrent posts.
4. **ContextForge:**
   - verify M1 against the real gateway;
   - rediscover the schema;
   - add the fourth tool to the voice virtual server and client permissions;
   - update the passthrough list to five headers.
5. **Voice team:**
   - breaking change: eight arguments and five outcomes;
   - must send `X-Call-Id` (characters `[A-Za-z0-9._:-]`, ≤64) and a timezone-aware `X-Call-Started-At`;
   - one summary per call, and the first is final;
   - handling of ALREADY_SAVED;
   - the 8 s summary limit.
6. **Live latency** of `POST /call-summaries` in region, to settle the 8 s default.
7. **Unused secret `mcp-lifecycle-token`.** It stays in Key Vault and on the existing app for rollback; deleting it needs separate approval.

## Per-commit fast suite

Hermetic suite (`pytest -m "not e2e and not external"`) at each commit with code changes, in a detached temporary worktree (removed afterwards). Docs and evidence-only commits 39f395c and a0a2aee were not run separately; their parent and child commits are green.

| Commit | Result |
|---|---|
| 768890e natural-key transport | 413 passed |
| 263c802 summary contract | 450 passed |
| bd3be3a duration removal | 451 passed |
| 68ecbf0 single gateway access | 448 passed |
| 62e750b credential/principal removal | 446 passed |
| 9450930 deploy/registration | 449 passed |
| 0e37c8f architecture docs | 449 passed |
| 4a9f132 integration docs | 449 passed |
| f1ea88e token refusal, HTTP boundaries | 456 passed |
| 7a64f9b privacy redaction | 462 passed |

Every code commit is green on its own, so the process breach of the earlier change (8575979) did not recur.

## Remaining deployment prerequisites (summary)

`calls.write` on `mcp-gateway`, plus a confirmed synthetic tenant. A real ContextForge registration and schema check (M1). Voice-team cutover to the new schema. Reviewer agent update (L5). An explicit go-ahead for the canary redeploy.
