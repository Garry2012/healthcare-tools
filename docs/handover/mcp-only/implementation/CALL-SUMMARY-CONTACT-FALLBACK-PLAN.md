# Call-summary contact fallback implementation plan

**Status:** **Approved by Garima, 10 October 2026 (revision 2).** Approval authorises implementation only, not merge, deployment or live writes. Build brief: `.context/astra-build-contact-fallback.md`.

**Revision 2 (10 October 2026, Opus).** Applies Opus's review and Sol 5.6's two findings:
- Garima chose option A for base and sequencing (see "Base and release sequencing");
- two commits, each at most 10 files;
- the caller-ID source becomes a release condition;
- the evidence status of the live summary is stated;
- the exact schema statement is given;
- `PLAN.md`'s summary contract is added, with two new release gates;
- the external test checks storage as well as sending.

**Goal:** Preserve an explicit summary contact number; otherwise derive it from the caller header, without changing appointment authorization.

**Architecture:** Resolve contact information once inside `SummaryService` before its existing validation and body construction. Reuse `identity.contract_mobile`; keep transport, credentials, appointment authority and call-ID deduplication unchanged.

**Tech stack:** Python, Pydantic, FastMCP, httpx, pytest; no new dependency.

**Spec:** Garima's requirement in this conversation: explicit `callerMobile` wins; otherwise convert `X-Caller-Number` to Manoj's format; an ordinary summary may lack a usable number, whereas `CALLBACK_NOTED` may not; the number supplies contact information only. This document records that requirement and the proposed edge-case interpretation for approval.

## Current flow and root cause

`voice platform → ContextForge → authenticated MCP request → context.from_headers → tools.record_call_summary → SummaryService.record → POST /call-summaries → response validation → SummaryResult`

- `context.py` already captures `X-Caller-Number` as `CallContext.caller_number`. ContextForge registration already includes it in the passthrough list.
- `tools.py` constructs `SummaryRequest` from tool arguments. Its optional `callerMobile` defaults to `None`.
- `summary.py` validates and builds the body from that request; only call ID and start time come from context. It never derives a mobile from the caller header.
- `test_summary.py::test_caller_mobile_is_never_copied_from_caller_id` deliberately pins that behaviour. This is an old policy being changed, not a missing HTTP header or failed persistence operation.
- The live journey omitted `callerMobile` and asserted only `SAVED`/`ALREADY_SAVED`. It did not assert the submitted contact number. The created summary consequently lacked a mobile even though the appointment had one.
  - **Evidence status:** this comes from the authorised live summary run on the `jayashree` synthetic tenant, as reported to Opus by Garima.
  - **No captured artifact** (log, response body or call ID) is stored in this repository.
  - The implementation hand-back attaches redacted evidence if any exists. Otherwise it repeats this statement.

## Proposed behaviour and assumptions for approval

| Explicit callerMobile | Caller header | Ordinary summary | CALLBACK_NOTED |
|---|---|---|---|
| Valid 10-digit string | Any value or absent | Explicit value | Explicit value |
| Omitted or null | Valid `+<configured country code><10 digits>` | Converted national number | Converted national number |
| Omitted or null | Missing, empty, malformed or unsupported country | Omit callerMobile; allow if other inputs are valid | INVALID_REQUEST, fields includes callerMobile; no POST |
| Present but invalid, including empty/blank string or E.164 argument | Any value | Existing validation error; no POST | Existing validation error; no POST |

The last row is an explicit interpretation: fallback applies to absence (`None`), not to invalid supplied input. Do not silently replace an invalid explicit number with another person's contact number. Wrong-type arguments retain the existing private protocol-error behaviour. If Garima intends invalid explicit values to be discarded instead, amend this plan before implementation.

Reuse the existing strict conversion rule: no trimming, arbitrary prefix removal, guessing, or taking the last ten digits. A national-format number in the header is unsupported by that utility; the tool's explicit contact field already accepts that national format.

Summary contact fallback does **not** require `X-Caller-Verification`. That field continues to control appointment authority through `identity.authorised_mobile`; contact capture is separate. No mutation of `CallContext`, no identity state stored between calls, and no new tool arguments for trusted headers.

## Base and release sequencing (Garima, option A, 10 October 2026)

- **Branch:** `Garry2012/slots-phase-1a-1b`, on top of `980da73` (or the branch head at implementation time, if Garima has approved later commits). The hand-back records the actual base.
- **Release:** this change ships in the **same unreleased release** as the slots series, so there is one gateway/ContextForge and voice refresh, not two.
- **Schema version:** `prompt.SCHEMA_VERSION` goes from `2026-10-08.1` to **`2026-10-10.1`**. No other version is used.
- **The slots series' frozen `2026-10-08.1` is superseded for this combined release.** Commit B updates every current reference:
  - `docs/handover/mcp-only/PLAN.md`: gate 5 ("ContextForge schema refresh to `2026-10-08.1`") and the prompt-and-gateway paragraph ("refresh gateway/voice schemas to `2026-10-08.1`");
  - `docs/DECISIONS.md`: a dated supplement line under SL1, saying that `2026-10-10.1` replaces `2026-10-08.1` for the release because of this description change. SL1's existing D-1 text stays historical.
- **The slots and phase 5 review reports stay historical,** and are not edited.

## Existing decisions and owner conflict

1. Replace the explicit no-copy regression test and update the callback-with-null test: its current default fixture has a valid caller header, so it should now succeed. Retain rejection coverage using an absent/unusable header.
2. Update the healthcare pack's statement that callerMobile is necessarily caller-supplied, and VOICE-TEAM's summary header row, parameter description and missing-number example. Clarify that a usable *resolved* contact is required for CALLBACK_NOTED. Add a dated decision supplement to S1 and update CLAUDE's current summary rule. Preserve historical reports as historical evidence.
3. **Owner contract conflict:** the pinned Manoj OpenAPI describes callerMobile as “Only when the caller gave it during the call.” The requested fallback changes that provenance, although the wire format remains the same. Ask Manoj to confirm that platform-supplied caller ID is acceptable as summary contact and update his contract wording. Do not silently alter the pinned contract, hash or overlay. This is an integration agreement to resolve before releasing the fallback; it does not prevent approved local implementation and fixture verification.
4. First accepted summary remains final. This change cannot repair the already saved numberless summary by replaying its call ID. A later live check needs a fresh synthetic call ID.

## File and subsystem impact

| Files/subsystem | Planned change or verified boundary |
|---|---|
| `services/mcp/src/frontdesk_mcp/summary.py` | Derive the effective contact once for omitted/null input, using the existing converter and an immutable request copy. Feed that resolved request into the existing validator and body builder. Keep validation centralized; do not add fallback logic to both methods. Update the module description. |
| `services/mcp/src/frontdesk_mcp/identity.py`, `context.py`, `tools.py` | Reuse existing functions/context and the existing tool entry point; no production changes expected. Do not call the authorization helper for summary contact. |
| `services/mcp/src/frontdesk_mcp/packs/healthcare.json` | Update summary tool and callerMobile descriptions as facts: explicit precedence, absence fallback, effective callback requirement and no authorization effect. |
| `services/mcp/src/frontdesk_mcp/prompt.py` | `SCHEMA_VERSION` changes from `2026-10-08.1` to `2026-10-10.1` (commit B). This publishes changed descriptions, not new fields. |
| `services/mcp/tests/contracts/mcp-tools.snapshot.json` | Regenerate from the actual server (commit B). Only the `record_call_summary` description text (the tool and `callerMobile`) and the version metadata change. Field names, types, limits, defaults, required lists, annotations, output shapes and every other tool stay identical. |
| `services/mcp/tests/test_summary.py` | Replace obsolete no-copy expectations after replacement coverage exists; add the contact matrix, precedence, retry/deduplication and privacy assertions. |
| `services/mcp/tests/test_server.py` | Prove real MCP HTTP headers reach summary contact, context remains isolated across concurrent requests, explicit contact overrides fallback, and unverified header contact does not authorize appointment operations. Retain schema, documentation and private validation-error checks. |
| `services/mcp/tests/test_e2e_processes.py` | Assert the saved summary's callerMobile in the existing process journey, rather than only its outcome/count. |
| `services/mcp/tests/test_external.py` | **Sending:** assert that the actual summary POST body includes the expected converted contact when the argument is omitted.<br>**Storing:** Manoj's `CallSummary` response is `allOf` `CallSummaryCreate` (`manoj-openapi-20261007.yaml:2333–2339`), so it may echo `callerMobile`. Our parsed `contract.CallSummary` (`contract.py:194–200`) drops that field. So capture the **raw** create response at the HTTP boundary, with a test-scoped httpx hook or transport wrapper around the real client. For a new call ID (201), assert that `callerMobile` equals the expected number when it is present. When it is absent, record that, and the hand-back states: "storage of `callerMobile` not independently verified (response omits it; no `calls.read`)".<br>**Unchanged:** no production model change, extra owner call or `calls.read` requirement. Do not replace the live response with a fixture. Keep the response and replay assertions. |
| `docs/handover/VOICE-TEAM.md` | Update header meaning/matrix, summary prose and examples; regenerate affected tool-description/input rows from the snapshot and update current schema-version references. Clarify the national tool-argument format versus E.164 header format. Leave historically labelled release notes intact, with the new current behaviour clearly documented. |
| `docs/DECISIONS.md`, `CLAUDE.md` | Record the new current rule, the strict interpretation of explicit input, the separation of contact from authority, and the dependency on Manoj's contract wording. `DECISIONS.md` also gets the dated SL1 supplement line about `2026-10-10.1` (see "Base and release sequencing").<br>The S1 supplement **states the storage change explicitly**: "From this release, a summary stores the calling number as `callerMobile` when no number is given and the header converts; Garima approved this on 10 October 2026. It is contact data only." |
| `docs/handover/mcp-only/PLAN.md` | **Summary contract** ("Call-summary tool contract (approved 4 October 2026)"): describe the **resolved callback contact**:<br>• the explicit `callerMobile` if supplied;<br>• otherwise the caller-header number converted to the contract format;<br>• CALLBACK_NOTED requires a usable resolved contact;<br>• contact never grants booking authority.<br>**Version references:** gate 5 and the prompt-and-gateway paragraph change from `2026-10-08.1` to `2026-10-10.1`.<br>**Two new pre-deployment gates, both pending** (so the release conditions don't live only in this plan):<br>8. Manoj confirms that a converted caller-ID number is acceptable as `callerMobile` and updates the contract wording "Only when the caller gave it during the call";<br>9. the voice platform and ContextForge owners confirm that `X-Caller-Number` is always the end caller's own number, never a trunk number or a placeholder for a withheld ID. |
| `docs/handover/mcp-only/implementation/` | Preserve this plan and add a hand-back with actual red/green output, affected files, schema comparison and remaining release dependencies. No docs/superpowers folder. |
| `booking.py`, `ops_client.py`, `contract.py`, outcomes, dev stubs/demo | No production changes expected. Existing formats, scopes, retry handling and JSON body transport already support the resolved number; appointment identity and clinical/availability policies stay unchanged. Run their regression coverage. |
| Configuration, env files, rollout files, Docker/CI, Azure, Key Vault, ContextForge registration | No new setting, secret, scope, header, deployment asset or infrastructure change. Existing gateway header forwarding must be verified at eventual rollout; refresh discovery for revised descriptions. Preserve the unrelated pending cleanup edits. |
| Historical pinned OpenAPI/overlays, historical reports/reviews, user-owned temp/ | Preserve. No fabricated owner-contract amendment or rewriting old evidence. |

## Commits (each at most 10 files)

**Commit A, behaviour and tests (5 files):**
- `src/frontdesk_mcp/summary.py`;
- `tests/test_summary.py`, `tests/test_server.py`, `tests/test_e2e_processes.py`, `tests/test_external.py`.

No description changes in this commit, so `make schema` stays byte-identical to the `2026-10-08.1` snapshot. `make test-fast` passes.

**Commit B, publishing (8 files):**
- `src/frontdesk_mcp/packs/healthcare.json`;
- `src/frontdesk_mcp/prompt.py`;
- `tests/contracts/mcp-tools.snapshot.json`;
- `docs/handover/VOICE-TEAM.md`, `docs/DECISIONS.md`, `CLAUDE.md`, `docs/handover/mcp-only/PLAN.md`;
- the implementation hand-back.

After commit B, the structural schema comparison (descriptions removed, version normalised) shows only description text and version metadata changed.

## Test-first implementation sequence, after approval

- [ ] **Red service tests:** Before changing production code, show that omitted and explicit-null callerMobile produce the converted header number for both ordinary and CALLBACK_NOTED summaries. Existing code must fail because the body lacks the number or the callback is rejected. Paste actual failure output.
- [ ] **Matrix and retained boundaries:** Assert valid explicit contact wins over a different/invalid header; invalid explicit values remain rejected; absent/unusable header permits ordinary summaries but rejects callbacks; E.164 conversion uses the configured country code. Cover unverified contact fallback without appointment access. Test malformed, foreign-prefix, national-only, too-short/long and whitespace header inputs. Announce each test invocation before running it; fixture tests use synthetic contacts and need no real doctor/department.
- [ ] **Small coherent implementation:** In SummaryService.record, resolve only a missing contact into a request copy before the current validation/body-building path. Keep one validator and one body builder; preserve their existing unrelated checks. Reuse identity.contract_mobile unchanged. Remove the contradictory old no-copy expectation only once replacement tests exist.
- [ ] **HTTP/process proof:** Add assertions at the stored-body boundary; vary header numbers across concurrent calls and ensure no cross-call mixing. Prove an explicit alternate summary contact cannot affect LIST/CANCEL/RESCHEDULE, and a valid unverified header still gets IDENTITY_UNAVAILABLE for appointment access. Assert header-derived numbers are absent from tool output, logs and protocol errors.
- [ ] **Replay proof:** A repeated call ID retains the original stored contact even if subsequent contact/header differs. Transport retries reuse the already resolved identical body; no new lookup, read-back, retry engine or Idempotency-Key.
- [ ] **External-test correction:** Assert the actual posted contact in the existing real-service journey. Also assert the stored contact from the raw create response when Manoj echoes `callerMobile`; otherwise record "storage not independently verified". Do not introduce `calls.read` as a production requirement. Do not rerun that journey or create records during planning. For eventual live acceptance, announce the exact test, tenant, synthetic number, doctor/department (or none for a summary-only check), dates and writes before execution. `jayashree` is already approved for synthetic records; this approval is not permission to deploy.
- [ ] **Publication (commit B):** Update the pack and current documentation, including `PLAN.md`'s summary contract and its two version references. Add the S1 and SL1 supplements. Bump the schema version to `2026-10-10.1` and regenerate the snapshot. Compare old/new schemas after removing descriptions and normalizing the version metadata; prove that structural schemas and all other tools are unchanged. Update documentation from that same snapshot, not independently invented wording.
- [ ] **Verification:** Run focused tests, then the full required suite and review the final diff for stale current rules and unrelated edits. Retain actual command output, not just a pass claim. Stop for review; do not merge or deploy.

## Verification commands and acceptance evidence

Run from the repository root unless shown otherwise:

```bash
cd services/mcp
uv run pytest tests/test_summary.py -q
uv run pytest tests/test_server.py tests/test_booking.py tests/test_context.py tests/test_ops_client.py -q -m 'not external and not e2e'
uv run pytest tests/test_e2e_processes.py -q -m e2e
```

Then `make schema` to a temporary comparison file and compare with the regenerated snapshot; run the interface-table assertions in test_server.py. Run `./scripts/test.sh` without loading a live profile: frozen install, lint, hermetic tests, process smoke/journeys, package, production image and stub image. Ensure Docker builds actually run; report unavailable Docker as unverified rather than complete. No standalone static type checker is configured; do not add one merely for this change.

Use `git diff --check`, inspect the complete diff and repeat repository searches for callerMobile/no-copy/caller-header rules. No full-suite or live test is run during this planning step.

## Risks, integrations and release conditions

- **Where the caller-ID number comes from (release condition):**
  - `contract.MOBILE_PATTERN` is `^[0-9]{10}$` (`contract.py:17`), and the fallback does not require `X-Caller-Verification`.
  - So any `+<configured country code><10 digits>` header is stored as `callerMobile`. That includes a landline, a hospital trunk or PBX number, or a spoofed caller ID, and a callback could go to a number that is not the caller's.
  - **Before release,** the voice platform and ContextForge owners confirm that `X-Caller-Number` always carries the end caller's own number, never a trunk number or a placeholder for a withheld ID.
  - No new verification requirement is added; Garima's requirement stands.
- **Voice agent:** Can omit contact when the platform forwards a usable caller header; an explicitly supplied alternate contact still wins. If callbacks should go somewhere other than the calling number, that explicit contact remains necessary. No summary text composition is added.
- **ContextForge:** Existing trusted header forwarding is sufficient. The authenticated integration must control the header; the model must not supply it as an argument. Refresh cached descriptions after an separately approved release.
- **Manoj:** Same endpoint, scopes and 10-digit wire format. Confirm caller-ID provenance semantics above. Our current machine credential has calls.write but summary GET returned 403 for missing read access; staff/admin verification can establish number-searchability without expanding production MCP privileges.
- **Knowledge:** No Shobhit/other KB dependency or call is added.
- **Security/privacy:** More summaries contain a phone number; document that intentional storage change. No raw header logging. Conversion establishes formatting, not ownership, consent or appointment authority. The already documented FastMCP logging issue LOG-1 remains a separate release concern and must not be claimed fixed by this change.
- **Clinical safety:** No symptom interpretation, availability/UNKNOWN policy, booking decision or callback-task creation changes.
- **Latency/retries:** Local string validation/conversion only; no additional service round trip. Retain the existing separate summary deadline, same-body retry and 401-only refresh. No claim of sub-second summary latency follows from this change.
- **Compatibility:** Same tool arguments/results; omitted-contact submissions now store a number when available. Existing saved summaries remain unchanged. No compatibility shim or data migration.
- **Release:** Approval of this plan authorizes implementation, not merge/deployment. The latest slots code is still local and the Azure canary runs an earlier image; do not attribute a local test to deployed/ContextForge/voice verification. **Before calling the new behaviour release-verified:**
- resolve Manoj's wording agreement;
- get the caller-ID confirmation above;
- perform the separately announced live acceptance.

The combined slots and contact release still needs every pre-deployment gate in `PLAN.md`: gates 1 to 7 (with gate 5 at `2026-10-10.1`), plus the new gates 8 and 9 that commit B adds for Manoj's wording and the caller-ID confirmation.

## Hand-back requirements

List actual changed files, the removed old rule, exact failing/passing commands and outputs, schema-version bump/structural comparison, Docker result, any untested live/voice/gateway path, owner questions and readiness for review versus merge/deployment. Preserve every unrelated workspace change.
