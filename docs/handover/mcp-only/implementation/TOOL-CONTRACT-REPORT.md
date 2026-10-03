# Tool-contract-only hand-back — 3 October 2026

Implemented against baseline `231f10a`; implementation and current-document head `54720ba`.
Local commits only. No push, merge, deployment, Azure mutation, or history rewrite.

The repository now publishes the four MCP tools and their calling contract. Voice-agent prompts,
behaviour, guardrails and LiveKit implementation belong to the voice team (DECISIONS K2).
The interface is [VOICE-TEAM.md](../../VOICE-TEAM.md), rewritten in place and checked against the
pinned schema. New files in this change are review evidence and this report, not a second interface.

## Deletions and preserved boundaries

Deleted `docs/handover/LIVEKIT.md`, `docs/handover/mcp-only/AGENT-INSTRUCTIONS.txt`, the
`agent-instructions` CLI command, its Makefile target, export tests and the `CORE_RULES` block.
CLI coverage now verifies the remaining `serve` and `schema` commands. No alternate guidance exporter remains.

Existing callback result fields/defaults (`ask`, `say`) remain as explicitly approved; their
schema descriptions are factual. No tool names, inputs, outputs, constraints, enums, required sets,
defaults, annotations or scopes changed. Date validation is unchanged. Version is `2026-10-03.3`.
The three requested review corrections are explicit smoke configuration, original profile-exception
propagation, and field-name-only diagnostics. Malformed non-transfer knowledge coverage was added.

Historical reports/evidence and reviewer-agent prompts were preserved. The pre-existing untracked
Opus report and `temp/` were not added or altered by this task.

## Mandatory checklist

- [x] Availability remains independent of knowledge. Full suite includes all 18 parameterized
  `test_availability_is_independent_of_knowledge_and_transcript` cases (nine paths, configured and
  unconfigured). Boundary transport raises if touched and asserts zero requests, including doctor ID,
  name, ambiguous name, department ID/name, UNKNOWN, missing target, absent doctor and invalid date.
- [x] Booking reason present/absent journeys remain covered by three
  `test_booking_journey_forwards_reason_without_knowledge_or_transcript` cases.
- [x] Deleted guidance symbols have zero references in active tracked files. Grep proof below;
  historical implementation reports/evidence excluded, current OPEN-DEPENDENCIES included.
- [x] Vulture: exit 0, no findings, no added dependency.
- [x] Production source net **−36 lines** (`+65/−101`) against this task's baseline; **−230** against
  the original routing-removal baseline `73a0832`. New source lines are the explicit two-line
  exception guard and factual descriptions; no new abstraction or network stage.
- [x] Changed tests have observed red evidence against old code or deliberate mutations below.
  Temporary mutations were restored. Documentation audits are labelled static checks, not runtime tests.
- [x] Full `./scripts/test.sh`: 411 hermetic tests, 2 process e2e tests, wheel and both images passed.
  `make schema` is byte-identical to the snapshot. Two existing Authlib deprecation warnings remain.
- [x] CLAUDE, PLAN, TARGET-STATE and DECISIONS updated. Current guidance references removed.
- [x] Voice handover is the tool interface only. The older addendum's LiveKit guardrail/code handover
  requirement is superseded by the user's approved contract-only instruction.
- [x] Safety and latency reviewer findings closed. Safety independently ran 182 tests; latency ran 147.
  Review found no added service calls, serial stages, retries, client creation or deadline changes.
- [x] Every implementation commit had an inspected green `make test-fast` before committing;
  maximum 10 files. The final evidence-only commit also has its own fast-suite receipt.

## Red → green evidence

Full logs retain commands, failures, later passing output and intermediate corrections. They are
under [tool-contract-evidence](tool-contract-evidence/). Shell-like log command lines join argv for
readability: quote multiword pytest `-k` expressions when replaying.

| Item | Observed red | Observed green / receipt |
|---|---|---|
| Smoke env isolation | 1 failed, 6 passed with inherited `absent` | 403 passed with inherited `absent`; 01-smoke.txt |
| Missing smoke env | 1 failed after removing required-env validation | restored implementation passes full fast suite; 01-missing-env.txt |
| Profile env export | 1 failed, 1 passed after suppressing required export | restored export passes fast suite; 01-profile-env.txt |
| Dropped-field log privacy/name | 8 failed, 6 passed before log metadata fix | 409 passed; 02-knowledge.txt |
| Invalid ROUTE_DEPARTMENT / CLARIFY fields | widened transfer exemption: 5 failed, 1 passed; invalid-answer normalization: 2 failed | all six cases pass with mutations restored; 02-widen-transfer.txt, 02-invalid-answer.txt, 02-knowledge.txt |
| Profile exception guard | 1 failed: AttributeError concealed original RuntimeError | 410 passed; 03-profile.txt |
| Deleted CLI | 1 failed: old extra command visible | 410 passed; 04-delete.txt |
| Factual descriptions/instructions | 2 failed against old text | targeted 2 passed, suite 409 passed; 05-text.txt |
| Interface field/enum completeness | 2 failed against old document, still 2 failed with only version added | targeted 2 passed, suite 411 passed; 06-interface.txt |
| Interface field drift | 1 failed with changed maxLength | restored document passes 411; 06-field-drift.txt |
| Missing outcome meaning | 1 failed with outcome row removed | restored document passes 411; 06-outcome-drift.txt |
| Interface semantic review | static audit failed six meanings, then callback exclusions | all seven static checks pass; 06-meanings.txt |
| Current references | static audit failed eight files | eight pass, suite 411; 07-current-docs.txt |
| Ownership wording | static audit failed five files | five pass, suite 411; 08-ownership.txt |

Mutation patches are preserved alongside their receipts as evidence of the exact mutation used in
the then-current working tree; they are not production changes. `*.patch` is excluded only from
whitespace checking because unified-diff context lines carry their required leading space.

### Pasted run excerpts

[01-smoke.txt](tool-contract-evidence/01-smoke.txt)

```text
1 failed, 6 passed, 29 deselected, 2 warnings in 1.05s
EXIT: 1
EXIT: 2
403 passed, 11 deselected, 2 warnings in 25.49s
EXIT: 0
```

[01-missing-env.txt](tool-contract-evidence/01-missing-env.txt)

```text
1 failed, 35 deselected, 2 warnings in 0.91s
EXIT: 1
```

[01-profile-env.txt](tool-contract-evidence/01-profile-env.txt)

```text
1 failed, 1 passed, 34 deselected, 2 warnings in 0.68s
EXIT: 1
```

[02-knowledge.txt](tool-contract-evidence/02-knowledge.txt)

```text
8 failed, 6 passed, 35 deselected, 2 warnings in 1.04s
EXIT: 1
EXIT: 2
409 passed, 11 deselected, 2 warnings in 22.99s
EXIT: 0
```

[02-widen-transfer.txt](tool-contract-evidence/02-widen-transfer.txt)

```text
5 failed, 1 passed, 43 deselected, 2 warnings in 0.90s
EXIT: 1
```

[02-invalid-answer.txt](tool-contract-evidence/02-invalid-answer.txt)

```text
2 failed, 47 deselected, 2 warnings in 0.86s
EXIT: 1
```

[03-profile.txt](tool-contract-evidence/03-profile.txt)

```text
1 failed, 61 deselected, 2 warnings in 1.00s
EXIT: 1
410 passed, 11 deselected, 2 warnings in 22.98s
EXIT: 0
```

[04-delete.txt](tool-contract-evidence/04-delete.txt)

```text
1 failed, 20 deselected, 2 warnings in 1.79s
EXIT: 1
410 passed, 11 deselected, 2 warnings in 23.10s
EXIT: 0
```

[05-text.txt](tool-contract-evidence/05-text.txt)

```text
2 failed, 18 deselected, 2 warnings in 1.03s
EXIT: 1
1 failed, 1 passed, 18 deselected, 2 warnings in 0.96s
EXIT: 1
2 passed, 18 deselected, 2 warnings in 0.89s
EXIT: 0
409 passed, 11 deselected, 2 warnings in 23.61s
EXIT: 0
```

[06-interface.txt](tool-contract-evidence/06-interface.txt)

```text
2 failed, 20 deselected, 2 warnings in 0.92s
EXIT: 1
2 failed, 20 deselected, 2 warnings in 0.83s
EXIT: 1
2 passed, 20 deselected, 2 warnings in 0.84s
EXIT: 0
411 passed, 11 deselected, 2 warnings in 23.76s
EXIT: 0
411 passed, 11 deselected, 2 warnings in 23.38s
EXIT: 0
411 passed, 11 deselected, 2 warnings in 24.51s
EXIT: 0
411 passed, 11 deselected, 2 warnings in 24.47s
EXIT: 0
```

[06-field-drift.txt](tool-contract-evidence/06-field-drift.txt)

```text
1 failed, 21 deselected, 2 warnings in 0.93s
EXIT: 1
```

[06-outcome-drift.txt](tool-contract-evidence/06-outcome-drift.txt)

```text
1 failed, 21 deselected, 2 warnings in 0.83s
EXIT: 1
```

[06-meanings.txt](tool-contract-evidence/06-meanings.txt)

```text
FAIL: availability ambiguity is directory-only
FAIL: knowledge clarification is owner text
FAIL: availability not-found is directory-only
FAIL: booking not-found is verified caller scope
FAIL: staleness is owner supplied
FAIL: expiry is today-only with status exclusions
EXIT: 1
PASS: availability ambiguity is directory-only
PASS: knowledge clarification is owner text
PASS: availability not-found is directory-only
PASS: booking not-found is verified caller scope
PASS: staleness is owner supplied
PASS: expiry is today-only with status exclusions
EXIT: 0
FAIL: callback summary exclusions
PASS: availability ambiguity is directory-only
PASS: knowledge clarification is owner text
PASS: availability not-found is directory-only
PASS: booking not-found is verified caller scope
PASS: staleness is owner supplied
PASS: expiry is today-only with status exclusions
EXIT: 1
PASS: callback summary exclusions
PASS: availability ambiguity is directory-only
PASS: knowledge clarification is owner text
PASS: availability not-found is directory-only
PASS: booking not-found is verified caller scope
PASS: staleness is owner supplied
PASS: expiry is today-only with status exclusions
EXIT: 0
```

[07-current-docs.txt](tool-contract-evidence/07-current-docs.txt)

```text
FAIL: CLAUDE.md: LIVEKIT.md
FAIL: README.md: LIVEKIT.md, agent-instructions
FAIL: services/mcp/README.md: agent-instructions
FAIL: docs/handover/AZURE.md: LIVEKIT.md
FAIL: docs/handover/TESTING.md: LIVEKIT.md
FAIL: docs/handover/ONBOARDING.md: LIVEKIT.md
FAIL: docs/handover/OWNER-INTEGRATION-MESSAGES.md: LIVEKIT.md
FAIL: docs/handover/CONTEXTFORGE.md: agent-instructions
EXIT: 1
PASS: CLAUDE.md
PASS: README.md
PASS: services/mcp/README.md
PASS: docs/handover/AZURE.md
PASS: docs/handover/TESTING.md
PASS: docs/handover/ONBOARDING.md
PASS: docs/handover/OWNER-INTEGRATION-MESSAGES.md
PASS: docs/handover/CONTEXTFORGE.md
EXIT: 0
411 passed, 11 deselected, 2 warnings in 23.81s
EXIT: 0
```

[08-ownership.txt](tool-contract-evidence/08-ownership.txt)

```text
FAIL: docs/DECISIONS.md
FAIL: docs/handover/mcp-only/PLAN.md
FAIL: docs/handover/mcp-only/TARGET-STATE.md
FAIL: docs/handover/mcp-only/README.md
FAIL: docs/handover/mcp-only/implementation/OPEN-DEPENDENCIES.md
EXIT: 1
PASS: docs/DECISIONS.md
PASS: docs/handover/mcp-only/PLAN.md
PASS: docs/handover/mcp-only/TARGET-STATE.md
PASS: docs/handover/mcp-only/README.md
PASS: docs/handover/mcp-only/implementation/OPEN-DEPENDENCIES.md
EXIT: 0
411 passed, 11 deselected, 2 warnings in 23.77s
EXIT: 0
```

## Final verification and deletion proof

[Full build/test output](tool-contract-evidence/09-full-suite.txt):

```text
== install (frozen)
== lint
== hermetic suites
=============================== warnings summary ===============================
411 passed, 11 deselected, 2 warnings in 22.73s
== process e2e (stubs + adapter over TCP)
=============================== warnings summary ===============================
2 passed, 420 deselected, 2 warnings in 2.27s
== package build
Successfully built /tmp/frontdesk-mcp-build/frontdesk_mcp-0.1.0.tar.gz
Successfully built /tmp/frontdesk-mcp-build/frontdesk_mcp-0.1.0-py3-none-any.whl
== production image build (no stubs, no fixtures, no dev dependencies)
== development stubs image build (compose profile stubs)
== external gates not run: no profile loaded (scripts/run-profile.sh mock|live -- ./scripts/test.sh)
== all suites passed
EXIT: 0
```

[Final source/schema audit](tool-contract-evidence/10-final-audit.txt), with [audit source](tool-contract-evidence/10-final-audit.py):

```text
$ python3 /tmp/contract_final_audit.py
$ grep -rnHF LIVEKIT.md <102 active tracked files>
(no output)
EXIT: 1
$ grep -rnHF AGENT-INSTRUCTIONS.txt <102 active tracked files>
(no output)
EXIT: 1
$ grep -rnHF agent-instructions <102 active tracked files>
(no output)
EXIT: 1
$ grep -rnHF CORE_RULES <102 active tracked files>
(no output)
EXIT: 1
PASS zero references in active tracked files; dated reports/evidence excluded, user temp/ untouched.
PASS deleted: docs/handover/LIVEKIT.md
PASS deleted: docs/handover/mcp-only/AGENT-INSTRUCTIONS.txt
$ git diff --exit-code 231f10a -- .claude/agents
(no output)
EXIT: 0
$ git diff --exit-code 231f10a -- services/mcp/src/frontdesk_mcp/availability.py services/mcp/src/frontdesk_mcp/tools.py services/mcp/src/frontdesk_mcp/context.py services/mcp/src/frontdesk_mcp/identity.py services/mcp/src/frontdesk_mcp/summary.py services/mcp/src/frontdesk_mcp/ops_client.py services/mcp/src/frontdesk_mcp/config.py services/mcp/src/frontdesk_mcp/server.py
/Users/garima/conductor/workspaces/healthcare-tools/des-moines/services/mcp/.venv/lib/python3.13/site-packages/fastmcp/server/auth/providers/jwt.py:10: AuthlibDeprecationWarning: authlib.jose module is deprecated, please use joserfc instead.
It will be compatible before version 2.0.0.
  from authlib.jose import JsonWebKey, JsonWebToken
/Users/garima/conductor/workspaces/healthcare-tools/des-moines/services/mcp/.venv/lib/python3.13/site-packages/authlib/integrations/httpx_client/assertion_client.py:5: AuthlibDeprecationWarning: The httpx module is deprecated; please use httpx2 instead.
  from ._compat import httpx2
(no output)
EXIT: 0
PASS date validation, dispatch, identity/lifecycle, summary and operational client source unchanged.
PASS all tool names/scopes/annotations/constraints/enums/required fields/defaults identical to baseline.
PASS make schema byte-identical; version 2026-10-03.3
Server instructions characters: 2683 -> 634
$ git diff 231f10a --numstat -- services/mcp/src
2	0	services/mcp/src/frontdesk_mcp/booking.py
2	5	services/mcp/src/frontdesk_mcp/cli.py
1	1	services/mcp/src/frontdesk_mcp/knowledge_contract.py
4	4	services/mcp/src/frontdesk_mcp/outcomes.py
5	7	services/mcp/src/frontdesk_mcp/packs.py
41	38	services/mcp/src/frontdesk_mcp/packs/healthcare.json
10	46	services/mcp/src/frontdesk_mcp/prompt.py
EXIT: 0
SOURCE NET 231f10a -36
$ git diff 73a0832 --numstat -- services/mcp/src
31	110	services/mcp/src/frontdesk_mcp/availability.py
13	48	services/mcp/src/frontdesk_mcp/booking.py
12	2	services/mcp/src/frontdesk_mcp/config.py
1	46	services/mcp/src/frontdesk_mcp/context.py
18	53	services/mcp/src/frontdesk_mcp/knowledge.py
5	21	services/mcp/src/frontdesk_mcp/knowledge_client.py
58	55	services/mcp/src/frontdesk_mcp/knowledge_contract.py
10	12	services/mcp/src/frontdesk_mcp/outcomes.py
5	7	services/mcp/src/frontdesk_mcp/packs.py
41	38	services/mcp/src/frontdesk_mcp/packs/healthcare.json
10	42	services/mcp/src/frontdesk_mcp/prompt.py
3	3	services/mcp/src/frontdesk_mcp/tools.py
EXIT: 0
SOURCE NET 73a0832 -230
PASS commit file limit: bcaf57f 10
PASS commit file limit: 546264c 7
PASS commit file limit: 99c8c47 3
PASS commit file limit: f3350bb 6
PASS commit file limit: 243a995 7
PASS commit file limit: b217700 9
PASS commit file limit: 20f5983 10
PASS commit file limit: 54720ba 7
$ git diff --check 231f10a -- . :(exclude)**/*.patch
(no output)
EXIT: 0
$ uvx vulture services/mcp/src --min-confidence 80
(no output)
EXIT: 0
EXIT: 0
```

## Per-file changes and verification

| File | Change and verification |
|---|---|
| `CLAUDE.md` | Contract-only ownership and interface link; current-doc audit. |
| `Makefile` | Remove guidance export target; CLI regression/fast suite. |
| `README.md` | Remove export instructions and replace handover link; current-doc audit. |
| `deploy/azure/smoke.py` | Read expectation once in main, pass required argument; deploy tests. |
| `docs/DECISIONS.md` | Record K2 ownership and update active K1 handover wording; ownership audit. |
| `docs/handover/AZURE.md` | Replace retired handover link; current-doc audit. |
| `docs/handover/CONTEXTFORGE.md` | Remove guidance export, update schema version; current-doc audit. |
| `docs/handover/LIVEKIT.md` | Delete voice implementation guidance; deletion grep. |
| `docs/handover/ONBOARDING.md` | Replace retired handover link; current-doc audit. |
| `docs/handover/OWNER-INTEGRATION-MESSAGES.md` | Replace retired handover link; current-doc audit. |
| `docs/handover/TESTING.md` | Replace retired handover link; current-doc audit. |
| `docs/handover/VOICE-TEAM.md` | One complete interface with auth, headers, four tool schemas and meanings; schema/enum drift tests and semantic audit. |
| `docs/handover/mcp-only/AGENT-INSTRUCTIONS.txt` | Delete generated voice guidance; deletion grep. |
| `docs/handover/mcp-only/PLAN.md` | Remove voice instructions and pseudocode, state interface scope; ownership audit. |
| `docs/handover/mcp-only/README.md` | Remove duplicate voice assignment; ownership audit. |
| `docs/handover/mcp-only/TARGET-STATE.md` | Current MCP-only ownership and tool-contract boundary; ownership audit. |
| `docs/handover/mcp-only/implementation/OPEN-DEPENDENCIES.md` | Describe integration dependencies without prescribing voice implementation; ownership audit. |
| `services/mcp/README.md` | Remove old exporter reference; current-doc audit. |
| `services/mcp/src/frontdesk_mcp/booking.py` | Restore two-line original profile exception guard; boundary regression. |
| `services/mcp/src/frontdesk_mcp/cli.py` | Remove exporter and unused import; CLI regression. |
| `services/mcp/src/frontdesk_mcp/knowledge_contract.py` | Add dropped field name to structured log, no value; privacy assertions. |
| `services/mcp/src/frontdesk_mcp/outcomes.py` | Factual schema descriptions only; structural snapshot comparison. |
| `services/mcp/src/frontdesk_mcp/packs.py` | Neutral description/ownership wording; full suite. |
| `services/mcp/src/frontdesk_mcp/packs/healthcare.json` | Factual tool/parameter text including LIST filters; snapshot and forbidden-phrase tests. |
| `services/mcp/src/frontdesk_mcp/prompt.py` | Replace long rules with 634-character neutral instructions; bump version; snapshot tests. |
| `services/mcp/tests/contracts/mcp-tools.snapshot.json` | Regenerated text/version, structural contract preserved; make schema comparison. |
| `services/mcp/tests/test_booking.py` | Unexpected profile exception regression; red/green receipt. |
| `services/mcp/tests/test_deploy.py` | Explicit expectation, missing-env and export coverage; old-code/mutation receipts. |
| `services/mcp/tests/test_e2e_processes.py` | Pass explicit smoke expectation; process e2e. |
| `services/mcp/tests/test_external_transport.py` | Pass explicit smoke expectation; no external run claimed. |
| `services/mcp/tests/test_knowledge.py` | Six malformed non-transfer cases and field-only log assertions; mutation/privacy receipts. |
| `services/mcp/tests/test_server.py` | Replace guidance tests, add factual contract and interface drift checks; red/green receipts. |

Evidence files are individually linked in the red/green table or final checks. The `.patch` files record temporary mutations; the three static doc-audit scripts record wording checks. `10-final-audit.py` makes the final audit reproducible. `11-handback-fast.txt` records the evidence-only commit gate; `12-diff-stat.txt` records the complete staged stat/file inventory, excluding only itself. This report is the acceptance index.

## Commits and remaining work

```text
bcaf57f fix(smoke): isolate explicit deployment expectation
546264c fix(knowledge): identify dropped fields without values
99c8c47 fix(booking): preserve unexpected profile exceptions
f3350bb refactor(contract): remove voice guidance export
243a995 refactor(contract): publish facts instead of scripts
b217700 docs(contract): pin complete tool interface to schema
20f5983 docs(contract): remove retired guidance references
54720ba docs(ownership): keep voice implementation external
```

No requested implementation item remains. This hand-back is ready for Opus review. Real-service, deployed transport and voice-path latency were not exercised in this task; the full runner explicitly reports external gates not run without a profile. No claim of live readiness or production latency is made.

[Diff stat and full file inventory](tool-contract-evidence/12-diff-stat.txt) include documentation and required evidence; their line growth is separate from the 36-line production-source reduction.
