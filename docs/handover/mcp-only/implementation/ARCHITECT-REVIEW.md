# Architect review — 1 October 2026

**Verdict: changes requested. Do not merge or deploy the current implementation.**

Reviewed source commit `e9c6bc5`, reports commit `9f3912d`, PR #11. This is an independent source,
test and Azure inspection, not acceptance of the developer's completion percentages. The separation
into MCP and external services is sound; several functional, deployment and verification defects
remain. Partner access and the real voice path are separate release gates.

## What was independently verified

- `services/api` has no tracked files. The active MCP code, dependency file, scripts and deployment
  paths do not import the old database/backend implementation. Four tools are implemented.
- Pooled HTTP clients, separate operational/knowledge boundaries, conversation/lifecycle authorization,
  and uncertain-write handling are substantial useful work. Development stubs remain outside the
  production implementation.
- `cd services/mcp && uv run --frozen pytest tests -q -p no:cacheprovider -m 'not external'`:
  **271 passed, 4 deselected**, approximately 12 seconds. These are local tests, not production proof.
- PR CI run `36827604781` succeeded. No active build/test command was observed; the terminal was at a
  shell prompt. An existing Claude process does not establish that useful work is still running.
- Git records roughly 90 minutes from the first migration implementation commit to the report, with
  a substantial final review/fix interval. This duration is plausible for the scope. Elapsed time is
  not the problem; declaring all repository work complete is.

## Required correction pass

P1 means fix before approval; P2 means a required correctness/evidence correction for this handoff.
All line references below refer to the reviewed commit.

### AR-01 · P1 · Never silently truncate the trusted routing input

`services/mcp/src/frontdesk_mcp/context.py:86` truncates the utterance to 1,000 characters. This can
remove the symptom that determines the owner's routing decision. A controlled fixture returned
`EMERGENCY_TRANSFER` for a complete 1,177-character utterance; after header parsing forwarded only
1,000 characters, CREATE returned `NOTED` and sent one synthetic appointment write.

Preserve the original input within an agreed size limit, or reject an oversized/incomplete context
and prevent routine booking. Do not truncate and then treat the remaining text as safety clearance.
Add a regression proving the decisive tail is preserved or the write is refused. The reproduction
uses an exact-match owner fixture; it makes no claim about a real clinical classifier.

### AR-02 · P1 · Make symptom routing available through search_knowledge

`services/mcp/src/frontdesk_mcp/knowledge.py:32` calls only the answer API. Its provisional answer
contract cannot represent emergency or department routing. In a fixture where the trusted caller
utterance requires emergency routing, a general hospital question returns `NO_ANSWER` /
`SAY_NO_ANSWER_AND_OFFER_DESK`, with zero routing calls. Forwarding the text to an answer endpoint
alone does not establish support for the required routing outcomes.

Agree and implement an owner-provided routing/answer boundary for this tool, preserving the trusted
utterance and appropriate emergency/department outcomes. This can be a combined owner response or
the existing routing operation followed by answering when cleared. Keep four tools and keep clinical
reasoning in Shobhit's service. Test emergency, department, clarification, FAQ and unavailable cases.

### AR-03 · P1 · Session filtering must preserve UNKNOWN

`services/mcp/src/frontdesk_mcp/availability.py:323` drops board entries without a matching session.
A department search for Morning with a sessionless UNKNOWN row returns `NOT_FOUND` /
`TRANSFER_DESK` / `NO_SESSION`. The user explicitly requires UNKNOWN to collect name/number,
offer a callback, and save a call summary only; no transfer or booking.

Keep unscopable UNKNOWN distinct from evidence that a doctor has no requested session. Return the
callback outcome for unknown availability and test missing/stale/sessionless board rows in both
doctor and department flows. Do not manufacture availability from regular working hours.

### AR-04 · P2 · Use consistent requested-session scope for booking

`services/mcp/src/frontdesk_mcp/booking.py:247` checks UNKNOWN across the doctor's whole day, whereas
availability can scope to a selected session. With Morning IN and Afternoon UNKNOWN, morning
availability offers an appointment request, but CREATE at 09:30 returns `CALLBACK_REQUIRED`.

Carry or resolve the requested session consistently with the owner contract. Clarify when scope
cannot be established; do not invent a slot engine. Add a journey test from the availability result
to the corresponding create request, including an UNKNOWN in an unrelated session.

### AR-05 · P1 · Fix deployment to an existing Container App

`deploy/azure/deploy.sh:155` updates the existing app's environment with new `secretref:` names but
does not attach those named secrets to the app. Only the create branch supplies `--secrets`.
Live read-only inspection of `mcp-demo-hospital` found only `agent-token` and `mcp-token` configured.
The new lifecycle, operational-client and knowledge secret references therefore do not exist there.

Configure the app's Key Vault references and required identity/registry access before switching its
revision environment. Preserve unrelated shared settings. Test upgrading an app that starts with
the legacy two-secret configuration; a clean-create test alone is insufficient. Do not deploy until
the remaining release gates are satisfied.

### AR-06 · P1 · Enforce the actual voice latency budget

`services/mcp/src/frontdesk_mcp/config.py:58` defaults to 1.2-second reads and 2.5-second writes,
before adding gateway, model and speech time. These limits do not enforce the one-second customer
response objective. The settings test named as fitting a one-second turn budget actually permits
these values. Fast local fixtures do not validate the slow/degraded path or the full voice path.

Derive a bounded tool deadline from the agreed voice budget, reserving time for the other stages;
account for all sequential calls, auth, pool waits and retries. Treat the approximately 250 ms tool
budget as a design allocation to validate, not a measured guarantee. Keep diagnostic/test overrides
explicit. Test slow multi-stage responses and uncertain writes. Report successful-response p95 and
failure rates together; fast failures are not evidence that the success latency target is met.

### AR-07 · P2 · Benchmark actual successful owner calls

`services/mcp/dev/bench.py:58` omits caller verification. Its booking LIST scenario is denied locally
as `IDENTITY_UNAVAILABLE`, but the failure counter at line 67 does not count that outcome. Independent
reproduction: zero owner appointment calls and a result counted as a successful timing sample.

Provide the correct synthetic trusted context, assert the expected successful outcome per scenario,
and prove the intended downstream operation occurred. Report rejected/refused cases separately.
Rerun affected benchmarks. The valid availability samples need not be discarded, but aggregate
"zero failures" and booking timings cannot currently support the claimed integration performance.

### AR-08 · P2 · Make external verification an actual acceptance gate

`services/mcp/tests/test_external.py:68` ends an assertion with `or True`. The write journey can accept
`CALLBACK_REQUIRED` without creating/cancelling an appointment, omits its advertised reschedule step,
and can skip writes despite the module's "never skips" statement. Direct service calls also do not
exercise the live MCP/gateway authorization and lifecycle transport.

Remove the vacuous assertion. Separate deterministic positive create/list/reschedule/cancel/summary
journeys from negative UNKNOWN cases. Require an explicitly designated synthetic tenant for writes.
Label a missing-input run BLOCKED, not verified. Add a separate transport/voice release gate and
report exactly which layer was tested. Do not solve missing access by weakening assertions.

## Reproductions from additional review probes

All five probes ran against in-memory development fixtures; no real appointments were created.

| Probe | Observed result |
|---|---|
| 1,177-character trusted utterance with decisive tail | 1,000 forwarded; full fixture routes emergency; actual CREATE returns NOTED, one write |
| Morning IN / Afternoon UNKNOWN, request Morning then create at 09:30 | Availability offers request; CREATE returns CALLBACK_REQUIRED |
| Department Morning query, sessionless UNKNOWN board row | NOT_FOUND / TRANSFER_DESK / NO_SESSION |
| search_knowledge with emergency routing fixture for original utterance | NO_ANSWER / SAY_NO_ANSWER_AND_OFFER_DESK; zero routing calls |
| Benchmark LIST context without caller verification | IDENTITY_UNAVAILABLE counted non-failure; zero owner appointment calls |

The exploratory script and raw results are in `.context/architect-review/` in this shared workspace.
Turn these cases into maintained regression tests rather than committing the scratch harness as
production code. The cases and expected corrections above are durable review evidence.

## External blockers: newly checked, not assumed

- `GET https://healthcare-api.icytree-6543aaa9.centralindia.azurecontainerapps.io/api/v1/departments`
  without a bearer returned **401 / Missing bearer token**.
- `POST /api/v1/auth/token` with `grant_type=client_credentials` and no credentials returned
  **401 / Invalid client credentials**. This API requires a registered machine client, not an
  interactive username/password. Guessing credentials is not a verification strategy.
- Shared-vault secret names were inspected: `ops-client-id` and `ops-client-secret` are absent.
  Reading even secret metadata from `kv-healthcare-ops-dev` returns **ForbiddenByRbac** for the
  current identity. No access control was changed or bypassed.
- Live OpenAPI now hashes to `6f827be1b62e22f4f4f0c54174d22a1b40bd02ab130ec74ce5f83b8b9aa80391`.
  The pinned file hashes to `b8f282718c2c45410dd0dd403369223b9cbe8dea045ee044207aa1e52ec2de78`.
  The inspected diff only replaces the placeholder Azure server with the real URL and description;
  paths/schemas are unchanged. The prior byte-identical statement is now stale, not evidence of a
  functional schema mismatch.
- No knowledge-service or ContextForge Container App appears in the current `healthcare-rg`
  inventory. This does not establish that Shobhit has no service elsewhere; obtain its actual
  contract/host rather than treating the provisional stub as the delivered service.

## Instructions for Fable's next pass

1. Fix AR-01 through AR-08 with meaningful regression tests. Keep source changes confined to the MCP
   adapter, its tooling and tests. Preserve other workspace work and `temp/`.
2. Update the reports and test descriptions to match actual evidence; avoid percentage claims that
   imply runtime acceptance. Reconcile the live contract server metadata without weakening pinning.
3. Run the hermetic/process suites and CI. Return a finding-to-commit-to-test table and measured
   benchmark outcomes. Do not claim the external or voice gates passed from stub results.
4. Once the registered client is securely supplied, verify reads first, then the designated synthetic
   write journey. Integrate Shobhit's published contract when supplied. No local replacement backend,
   database, clinical rules engine or invented owner contract is authorized as a shortcut.
5. Verify the voice/gateway transport, trust headers and lifecycle summary with their actual runtime.
   Run successful-request latency measurements from the MCP region with declared load.
6. Complete Azure retirement after proving consumers have moved. The user's latest instruction
   authorizes unwanted-resource cleanup; another generic request for authorization is unnecessary.
   Resource ownership, dependencies and data disposition still determine what is actually unwanted.

Return the corrected PR for architect re-review before merge/cutover. Completion means passing the
specified behavioral and deployment checks, not just having a green existing test suite.
