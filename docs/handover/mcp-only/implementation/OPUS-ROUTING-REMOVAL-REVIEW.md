# Independent review: removal of hidden knowledge checks (Opus)

> **Historical (3 October 2026).** This review of `aa11591` is kept as dated evidence. Its findings were
> fixed in `231f10a`. Section C and the LIVEKIT.md items are superseded by the contract-only decision
> (DECISIONS K2): `LIVEKIT.md` and `AGENT-INSTRUCTIONS.txt` were removed in `2a6b147`. The current
> interface is [VOICE-TEAM.md](../../VOICE-TEAM.md). Final verdict on `2a6b147`: approved; follow-ups
> are the hand-typed schema version at `CONTEXTFORGE.md:129` and the wall-clock assertion at
> `test_knowledge.py:98`.

Date: 2 October 2026. Reviewer: Claude Opus 5.5, independent of the implementer.
Branch `Garry2012/mcp-external-api-v2`, baseline `73a0832`, reviewed head `aa11591` (verified; working tree
equal to HEAD apart from user-owned untracked `temp/`). Scope: `git diff 73a0832..HEAD`, 81 files, all 11
commits. Read-only review: no implementation code changed, nothing deployed, merged or pushed, no secret
read, no owner API written.

Inputs read: both Astra briefs (`.context/`), `CLAUDE.md`, `ROUTING-REMOVAL-REVIEW.md` (Astra's report,
treated as claims), both reviewer-agent prompts. Skills used: `livekit:reading-livekit-docs` and
`building-livekit-agents` (LiveKit claims checked against current docs and `livekit/agents` source), plus
the addendum's verification and code-review discipline.

## How this review was done

| Area | Method |
|---|---|
| Whole suite | `./scripts/test.sh` on the clean head: lint clean, **358 passed**, 2 process e2e passed, wheel/sdist, production and stub images built, exit 0. External gates not run (no profile). |
| Safety invariants | `voice-safety-reviewer` agent against the committed diff, plus throwaway probes |
| Latency, concurrency | `latency-reviewer` agent; `dev/bench.py` rerun (50 samples per scenario, in-process stubs) |
| search_knowledge | Dedicated reviewer: 30+ probe payloads, status codes, timeout, cancellation, one in-place mutation (restored) |
| Deploy, config, smoke | Dedicated reviewer: dry runs, validator probes, smoke error envelopes |
| Docs, prompts, LiveKit | Dedicated reviewer: `make schema` and `make agent-instructions` regenerated and compared with `cmp` (both byte-identical, 43,330 and 2,699 bytes); every LiveKit API in `LIVEKIT.md` checked in docs and source |
| Tests, checklist | Dedicated auditor: red logs read, every commit extracted with `git archive` and tested, 9 mutation probes on runtime code (each restored; final tree verified equal to HEAD) |

I re-verified the material findings myself in the code before including them (quoted lines below).

## Verdict in one paragraph

The core change is correct and clean. Availability and every booking action can no longer reach the
knowledge service on any path; identity, confirmation, operation ids, replay keys, UNCERTAIN handling, board
scope, lifecycle authorisation and privacy are byte-for-byte or behaviourally unchanged; source shrank by 231
lines with no new module or dependency. The defects are at the edges: one emergency-signal downgrade in the
provisional knowledge contract, stale model instructions, a duplicated-speech result shape, a weakened
cancellation test, and documentation that still presents the old gate as current. The voice handover names
the right requirements but leaves three of them without an implementable LiveKit mechanism.

---

## A. Code defects Astra can fix here

### A1. Medium — an owner EMERGENCY_TRANSFER is lost when an optional field is malformed
- **Where:** `services/mcp/src/frontdesk_mcp/knowledge_contract.py:22-56` (whole-model validation), consumed at `knowledge_client.py:78-80`.
- **Trigger:** knowledge returns `{"outcome":"EMERGENCY_TRANSFER", ...}` with any optional field failing validation: blank `answer.language`, `answer.text` over 1,000 characters, blank `department.name`, non-string `sourceId`.
- **Incorrect behaviour:** the whole response is rejected as MALFORMED, so `search_knowledge` returns `COULD_NOT_CHECK / SAY_COULD_NOT_CHECK`. The agent says it could not check and offers the desk instead of transferring to emergency.
- **Why it matters:** this is the only emergency signal MCP relays, and the voice guardrail does not exist yet. The new `min_length=1`/non-blank validators make this stricter than the baseline.
- **Fix:** validate `outcome` first. For EMERGENCY_TRANSFER and DESK_TRANSFER, keep the decision and drop an invalid optional field (with a field-free log event). Only a missing or invalid `outcome` is MALFORMED. Add the four payloads above as tests.
- **Evidence:** probe output `EMERGENCY_TRANSFER -> COULD_NOT_CHECK SAY_COULD_NOT_CHECK MALFORMED` for all four payloads. In the code, `Speech.text: Field(min_length=1, max_length=1000)` and the `nonblank` validators raise inside `AnswerResponse`.

### A2. Medium — the model instructions still describe the removed routing-clarification path
- **Where:** `services/mcp/src/frontdesk_mcp/prompt.py:33-34` and `:37`, copied into `AGENT-INSTRUCTIONS.txt` and the snapshot.
- **Trigger:** knowledge returns CLARIFY or ROUTE_DEPARTMENT.
- **Incorrect behaviour:**
  - Line 33 says "ROUTING_REQUIRED: follow nextStep (TRANSFER_EMERGENCY at once, TRANSFER_DESK, **or ask routing.speak**)". `ASK_ROUTING_CLARIFICATION` no longer exists: ROUTING_REQUIRED now pairs only with TRANSFER_EMERGENCY, TRANSFER_DESK or CHECK_AVAILABILITY (`knowledge.py:42-47`).
  - CLARIFY now arrives as `CLARIFICATION_NEEDED` with the question in `answer.text`. But line 37 says "offer the returned choices (complete=false…)", which describes availability, and knowledge returns no choices.
  - "with the returned department" does not name the field. It should say `routing.department` → `departmentName`.
- **Why it matters:** LiveKit forwards these instructions only if the voice team pastes them in. When they do, the model gets a rule for an outcome that cannot happen and no rule for one that can. It may stall or invent a question instead of speaking the owner's text.
- **Fix:**
  - Rewrite the ROUTING_REQUIRED rule around its three real next steps.
  - Add "for search_knowledge, CLARIFICATION_NEEDED: ask answer.text verbatim".
  - Remove `CLARIFY` from `RoutingDecision` (`knowledge_contract.py:13`), because the `routing` object never carries it.
  - Bump `SCHEMA_VERSION`, then regenerate the snapshot and instructions.
- **Evidence:** the quoted lines above, read against `knowledge.py:40-47`.

### A3. Medium — owner speech is duplicated into two fields, and the description says to speak both
- **Where:** `knowledge.py:34-36,45-47` (`common` puts `answer` in every result, and `routing.speak` reuses the same `speech`); the description in `packs/healthcare.json:36`.
- **Trigger:** EMERGENCY_TRANSFER, DESK_TRANSFER or ROUTE_DEPARTMENT arrives with `answer`.
- **Incorrect behaviour:** the same text appears in `answer.text` and `routing.speak.text`. The description says "Speak approved answer.text and routing.speak.text exactly as returned", so the caller can hear an emergency instruction twice. The stub fixtures `routing-3`/`routing-4` contain "Fixture response", so in the demo a department route makes the agent say "Fixture response".
- **Why it matters:** this is a voice UX defect at the most time-critical moment, and the demo shows stub wording.
- **Fix:** routing outcomes carry speech only in `routing.speak` and leave `answer` empty. Update the description, the stub and the fixtures.
- **Evidence:** probe result `'answer': {'text': 'Fixture response'}, 'routing': {'decision': 'ROUTE_DEPARTMENT', 'speak': {'text': 'Fixture response'}, ...}`.

### A4. Medium — the CREATE cancellation test cannot detect lost parallelism
- **Where:** `services/mcp/tests/test_booking.py:551-585` (`test_cancelled_create_cancels_both_owner_reads_without_writing`).
- **Trigger:** a mutation that makes CREATE's profile and board reads sequential (`profile = await …; board = await board_read`).
- **Incorrect behaviour:** all 358 tests still pass. The hung profile read ends by its per-request timeout, `_profile` swallows that and returns None, and the board read then starts inside the test's 1 s window, so both "started" events still fire. `test_create_owner_calls_fit_the_diagnostic_budget` sends no `session`, so it never exercises the profile read.
- **Why it matters:** "profile and board overlap once the doctor is known" is a stated latency rule, and on session CREATEs no test guards it.
- **Fix:** give the fake a hang longer than the wait, or assert both requests are in flight at the same moment before cancelling.
- **Evidence:** auditor probe k, "358 passed" with the reads made sequential (source restored afterwards).

### A5. Low — knowledge client accepts any content type; two owner strings are unbounded
- **Where:** `knowledge_client.py:63-66`; `knowledge_contract.py:48-49`.
- **Trigger 1:** a 200 response with `text/html` and the body `{"outcome":"NO_ANSWER"}` becomes NO_ANSWER. A proxy page could produce a false "we have no answer".
- **Trigger 2:** a 5,000-character `destination` is passed through to the LLM. `sourceId` is likewise unbounded.
- **Fix:** require `application/json`, otherwise return MALFORMED. Add `max_length` (for example 64) to `destination` and `sourceId`.

### A6. Low — tests that guard the new boundary are missing or weakened
- **No external-cancellation test for knowledge.** Adding `asyncio.CancelledError` to the `except` tuple at `knowledge_client.py:54` turns a cancelled call into COULD_NOT_CHECK, and all tests still pass. The current code is correct (a probe showed CancelledError propagates), but nothing protects it. **Fix:** cancel while the transport hangs and assert CancelledError.
- **`test_server.py:25` dropped `turncontext`/`x-turn-context` from the FORBIDDEN tool-argument names.** Keeping them costs nothing and guards against the transcript coming back through a tool argument (addendum §A).
- **Privacy assertion only on success paths.** `question not in caplog.text` (`test_knowledge.py:54`) is checked only where nothing logs. Add it to the failure tests at lines 59-97, which is where `_post` logs.
- **Weak matrix rows.** `test_availability.py` (~420-432) asserts `result.doctors and result.doctors[0].board`. The department, NOT_FOUND and CLARIFICATION rows don't check ids or choices.
- **No drift test for the instructions file.** The committed `AGENT-INSTRUCTIONS.txt` is never byte-compared by a test; only the snapshot is.

### A7. Low — leftover structure and dead code introduced by the removal
- `availability.py:174`: `_compose` is still `async def` but awaits nothing (it awaited only the removed routed-department fetch), and it is called with `return await` at line 91. The `_prefetch` → `{"kind": …}` dict → `_compose` split existed so reads could run while routing did. **Fix:** make `_compose` synchronous; optionally fold the split back together (KISS).
- `booking.py:226-227`: `if isinstance(profile, BaseException): raise profile` is close to unreachable, because `_profile` swallows owner errors.
- `dev/frontdesk_stubs/knowledge.py:38,40,53-60`: the per-path failure injection (`fail_next_for`, `malformed_next_for`) has no users now that there is one path.

### A8. Low — deploy and config edges
- **Stale secret reference** (`deploy/azure/deploy.sh:178-198`): redeploying an existing app with an empty knowledge URL clears `KNOWLEDGE_BEARER_TOKEN`, but the `knowledge-token` Key Vault reference stays in the app's secret list. Container Apps resolves every referenced secret when it starts a revision, so deleting that vault secret later would block scheduling-only releases. **Fix:** `az containerapp secret remove … --secret-names knowledge-token` when there is no knowledge URL and the app exists; tolerate not-found; add a dry-run assertion.
- **Smoke trusts the app's own report** (`deploy/azure/smoke.py:43,57-62`): if the profile names a knowledge host but the running app reports `not_configured`, smoke passes as "scheduling only". **Fix:** `deploy.sh` passes `SMOKE_EXPECT_KNOWLEDGE=required|absent`, and smoke fails on a mismatch. A configured-but-down host already fails correctly.
- **Unexpected body escapes the exception list** (`smoke.py:38,43`): a `/dependencies` body that is a list or a string raises `AttributeError` with a traceback. It still exits 1, so this is not a false pass. **Fix:** check `isinstance(…, dict)` and raise `RuntimeError`.
- **Half-configured knowledge accepted in production** (`config.py:184-192`): a URL without a bearer, a bearer without a URL, and `"/"` (stripped to empty) are all accepted. **Fix:** outside development, require the URL and bearer both set or both empty, after stripping whitespace.

### A9. Medium (documentation) — current documents still describe the old gate
- `docs/handover/TESTING.md:37-40`: "routing decisions from the trusted turn … routing gate over the trusted turn plus `reasonVerbatim` before a create".
- `docs/handover/mcp-only/README.md:43`: "Preserve the plan's trusted caller identity, routing gate, …".
- `docs/handover/OWNER-INTEGRATION-MESSAGES.md:41`: the message to Rajiv still asks for "original turn context" headers.
- `docs/handover/CONTEXTFORGE.md:19-20,110-113`: still says availability and CREATE need Shobhit's service, and asks for 4 KB header and base64 tests for the removed transcript header.
- `deploy/environments/README.md:14-15` has a broken sentence. `docs/architecture/TARGET.md:24` (A7) puts `target` in the idempotency key, contradicting `booking.py:66` and CLAUDE.md (this predates the diff).
- None of these carries the "historical" banner the superseded reports received. **Fix:** update or banner each one.

### A10. Medium (model-facing text) — developer wording and a self-contradicting date rule
- **Developer text in the prompt.** `packs/healthcare.json:3` sends "The voice platform owns the every-turn emergency guardrail; MCP scheduling tools do not classify symptoms" to the model. DECISIONS K1 says the model's own judgement is the only emergency protection until the guardrail exists, and this sentence invites the model to leave emergencies to someone else. **Fix:** keep only "If the caller describes a medical emergency, transfer immediately…".
- **The date rule contradicts itself.** `prompt.py:18-19` says "Never work out a relative date yourself: ask for the day" next to "facilityToday … to help you confirm". The model has no `facilityToday` until it has called a tool, so "tomorrow" always costs an extra question. The LiveKit `building-livekit-agents` skill says the model should interpret "next Tuesday" and code should validate structure. This was flagged as optional in the main brief §7 and needs Garima's decision. **Recommended:** the platform injects the facility date and weekday per call; the model resolves the date and reads back "Saturday 3 October?"; `ASK_EXPLICIT_DATE` stays as the code check.

---

## B. Mandatory requirements not demonstrated

These come from the addendum, sections C and E. I am stating them explicitly rather than waiving them.

| # | Requirement | Status | Evidence |
|---|---|---|---|
| B1 | "Every new or changed test must fail against the old code or with the line under test removed" | **Not met for the key assertion.** All 16 + 3 + 21 red failures in `01-`, `02-`, `03-*-red.txt` have one cause: the tests pass no transcript header, so the old code returned `ROUTING_UNAVAILABLE` before any knowledge request. The core assertion, "knowledge transport recorded zero requests", was never seen red, and the 03 mapping assertions were never run against old behaviour. The failures are behavioural, not import or fixture errors, but they are for a different reason. | Auditor's reading of the red logs. **Mitigation:** the auditor's probe (re-add a knowledge call to availability) failed 8 of 8 configured cases, so the assertion does work. Astra should commit that probe and its red output. |
| B2 | Red proof for changed tests | **Partially met, disclosed.** About 20 existing test bodies and about 100 constructor or harness call sites were changed with no individual red run. The six mutations in `13-review-mutations-red.txt` are labels only; the diffs are not recorded, so nobody can replay them. | Astra's report says so in "Process accounting". **Fix:** record the mutation diffs (patch files) in the evidence. |
| B3 | "One logical change per commit" | **Not met.** Intermediate commits do not pass the fast suite: 36ee9ca (8 failed), 26c6e12 (snapshot), 283dae9 (4 failed, including a TypeError from the removed `turn=` argument), b9ade8d (5 failed). Green from 711ca6d onward. All commits are within 10 files and their messages explain why. | `git archive` per commit plus the fast suite. Astra's report admits the commits are "not … independently build[ing]". **Fix if history matters:** squash or reorder before merge. |
| B4 | Every removed symbol has zero references | **Met for active code, tests, deploy and current rules. Not met repo-wide**, as disclosed: historical reports with banners, plus the A9 documents above, which have no banner. | `git grep -w` scan. |
| B5 | Reviewer-agent findings fixed or answered | **Met, with a process caveat.** In d086d66 Astra rewrote the criteria of the two reviewer agents she then used to approve her own work. The changes are justified: the old invariant #3 required the gate, the 300 ms budget matches CLAUDE.md, and "approved knowledge speech" in results was always the design. But the person being reviewed should not edit the reviewer's criteria in the same change without separate approval. | `git diff 73a0832..HEAD -- .claude/agents`. **Action:** Garima approves these two edits explicitly. |
| B6 | Net source lines down; vulture explained; snapshot, instructions, version; docs and DECISIONS updated; voice handover; file-by-file hand-back | **Met.** −231 net source lines; vulture at 80 is clean; both artifacts regenerate byte-identical; `SCHEMA_VERSION` is `2026-10-02.1`; DECISIONS K1 records alternatives, residual risk and pending sign-offs (except the documents in A9). | Reproduced. |

---

## C. External integration work and owner decisions

These items are not defects in this repository, but each blocks production. LIVEKIT.md is honest that the
snippet "does not implement" them. It should still name a feasible mechanism, since I verified that LiveKit
offers no built-in one.

1. **High — voice team: per-write `X-Operation-Id` cannot be sent through `MCPToolset`.**
   - The problem: `MCPServerHTTP` holds one header dict on one shared httpx client, and its setter swaps the headers. `_tool_called` calls `client.call_tool(name, args)` with no per-request hook, and tools run as concurrent tasks. Every write without the header returns `OPERATION_CONTEXT_MISSING` (`booking.py:143`), so booking cannot work through the documented wiring.
   - Feasible mechanism: leave `manage_booking` out of `allowed_tools` and expose it as a local `@function_tool(raw_schema=<discovered schema>)` wrapper. The wrapper mints or reuses the operation id per confirmed intent from `RunContext.userdata` and sends its own request with explicit headers.
   - Still to check: whether ContextForge forwards per-request headers and is stateless.
   - Recommend that LIVEKIT.md §50-54 state this mechanism.
2. **High — voice team: the write barrier needs a concrete place to live.**
   - Tools run only after the reply's speech is authorised, which happens after `on_user_turn_completed` returns. So awaiting the classifier in the hook blocks that turn's writes. With preemptive generation on, the added delay is roughly the slower of the classifier and the LLM, not their sum, unless the hook edits `turn_ctx`, which discards the preemptive reply.
   - A background classifier, which LIVEKIT.md suggests, cannot hold back an MCP write.
   - The barrier should sit inside the same local `manage_booking` wrapper: before sending, it awaits the pending safety decision for the current conversation version.
3. **High — voice team: no route for CALLBACK_NOTED details.**
   - Nothing captures the caller's name, dictated number and `requestedDate` for the end-of-call summary, and the summary tool is deliberately hidden from the LLM.
   - Mechanism: a local `note_callback(...)` tool writes `session.userdata`; `ctx.add_shutdown_callback` builds the summary payload once. Both APIs exist in current source.
   - This also belongs in LIVEKIT.md §75-79 (raised with Garima earlier and parked).
4. **Medium — voice team: other handover gaps.**
   - "Transfer" appears in the instructions (desk, emergency, UNCERTAIN), but there is no transfer tool. The handover must name a local transfer tool that also sets escalation state.
   - `session.interrupt()` raises `RuntimeError` when the current speech disallows interruptions, so the emergency path needs `force=True`.
   - Add `MCPToolOptions(on_duplicate="reject")` for `manage_booking`; the default is `allow`.
   - A toolset that fails to connect does not stop the agent from starting. Require a startup check that routes callers to the desk.
5. **Shobhit:** agree the single-request knowledge contract (the current module is a provisional proposal), plus a separate every-turn classifier contract with an outage policy. Raise department naming: only the name crosses the boundary, so "Pediatrics" vs "Paediatrics" falls to availability's clarification.
6. **Sign-off:** DECISIONS K1 records that Shobhit, the voice team and the clinical owner have not accepted the interim gap. Until the guardrail is live, availability and booking have no emergency check beyond the model's judgement. Garima approved the direction, but the other owners' acceptance is still missing.
7. **Manoj and release:** the earlier scope, board-data and synthetic-tenant dependencies were not re-probed. Live journeys, the gateway schema refresh and instruction injection still need verifying after release authorisation.

## D. Optional improvements

- **Benchmark honesty.** `dev/bench.py:130` labels every accepted sample "ok", including weaker accepted outcomes (CALLBACK_REQUIRED, NO_ANSWER, NOT_FOUND). `booking_list` always measures an **empty** lookup: the rerun shows NOT_FOUND on 50 of 50 samples, so the report's "Booking LIST 15.3/23.7 ms" is an empty-list timing. The session CREATE profile-and-board path is never benchmarked, and the department scenario does not require `GET /doctors`. **Fix:** record the actual outcome, seed one appointment, add a `session` CREATE scenario, and require `GET /doctors`. These scenarios predate this diff.
- **Sequential reschedule reads.** The reschedule gate runs `find_appointments → board → profile` in sequence (this predates the diff). Once the doctor is known, the board and profile reads can overlap.
- **Code smells that predate the baseline** (from eb2529b, 1 October): `del today` (`booking.py:186`), the `step` parameter of `_written` that is overwritten (`:367-370`), and duplicated except blocks in `_reschedule_gate` (`:339-359`). Astra was right to leave them out of scope; they would make a small follow-up.
- **Instructions are rollout-specific.** `AGENT-INSTRUCTIONS.txt` contains "(en, kn, hi)" and was generated for `PROVIDER_ID=demo-hospital`, but `LIVEKIT.md:20-23` does not say so. Document `PROVIDER_ID=<id> make agent-instructions`. Also say whether the English callback lines should be translated for kn/hi callers.
- **What LiveKit forwards.** The MCP adapter builds tools from name, description and input schema only. Output-schema field descriptions and annotations never reach the model, so any rule that matters must live in descriptions or instructions.
- **Placeholder fallback.** `test_external.py:56` still falls back to `https://knowledge.pending.invalid`; an empty URL is now valid.

## Benchmark rerun (fixture only)

The latency reviewer reran `uv run python dev/bench.py` with in-process stubs, 50 samples per scenario, concurrency 1 and diagnostic deadlines (2 s read, 4 s write). It returned 350 of 350 ok, none over 300 ms:

| Scenario | p50 ms | p95 ms | Outcome actually returned |
|---|---:|---:|---|
| Availability, known doctor | 24.8 | 37.1 | AVAILABILITY |
| Availability, name search | 25.6 | 29.2 | AVAILABILITY |
| Availability, ambiguous | 24.7 | 29.0 | CLARIFICATION_NEEDED |
| Availability, department | 26.2 | 31.4 | AVAILABILITY |
| search_knowledge | 14.2 | 17.4 | ANSWERED |
| Booking LIST | 16.7 | 23.2 | **NOT_FOUND (empty)** |
| Booking CREATE | 16.6 | 19.9 | NOTED, with POST observed |

These are fixture timings with deadlines raised. They say nothing about the 0.30 s production cap, real owner latency, ContextForge, STT, LLM or TTS. The earlier live bench (LATENCY-RESULTS §E, from a laptop) already had owner stages at about 330 ms per round trip. In-region production latency is still unmeasured.

---

## Summary for Garima

**What is correct.**
- "Is Dr. Sharma available today?" now goes only to Manoj: no knowledge call, no transcript header, no switch to turn the check back on.
- Booking keeps every protection it had: caller confirmation, verified caller number, operation id, replay protection, honest "uncertain" results, and callback-only on an UNKNOWN board.
- `search_knowledge` makes exactly one request with the caller's words unchanged, and it never reports a failure as "no answer".
- Scheduling deploys and smoke-tests without a knowledge host.
- The code got smaller (−231 lines), and the full test run, schema and instructions all check out.

**What must be fixed here before merge.**
1. A1: an emergency decision from Shobhit is lost if any side field is malformed.
2. A2: the model instructions still describe an outcome that no longer exists and omit the real one.
3. A3: emergency speech is duplicated, and the demo says "Fixture response".
4. A9 and A10: current docs still describe the old gate, and a developer note in the model prompt weakens the model's own emergency judgement.
5. A4 and B1: the test that should catch lost parallelism doesn't, and the key "zero knowledge calls" assertion was never seen failing (commit the probe that proves it).

Everything else in A is Low and can follow. B3 (commits that don't build one by one) only matters if you care about clean history; squash before merge if you do. B5 needs your one-line approval of the reviewer-prompt edits.

**What remains with other teams.**
- **Voice team** (most important): sending a fresh operation id on each booking, holding writes until the safety check finishes, passing callback details to the end-of-call summary, a real transfer tool, and the every-turn emergency check itself. As documented today, bookings would fail with `OPERATION_CONTEXT_MISSING` through standard LiveKit wiring.
- **Shobhit:** the knowledge contract and the classifier contract.
- **Clinical owner:** accept the interim gap.
- **Manoj:** the previously listed scope and data items.

**Ready to merge?** Not yet. Fix A1, A2, A3, A9, A10 and A4, and add the B1 proof. These are small (roughly a day), and the core design is sound. After that it is mergeable, subject to your B5 approval and a squash decision for B3.

**Ready to deploy?** No. Local tests prove the adapter, not production. Deploying to callers needs: the voice team's operation-id mechanism, write barrier and emergency guardrail; Shobhit's contract (or a deliberate scheduling-only release with knowledge reporting NOT_CONFIGURED); the clinical owner's sign-off on the interim gap; and a measured in-region voice-path latency run. A scheduling-only canary deploy for internal testing is reasonable after merge, once A8's stale-secret fix is in.
