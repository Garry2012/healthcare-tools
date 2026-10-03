# Opus correction hand-back — 3 October 2026

All requested repository corrections in A1–A10 (date change excluded by instruction), B1 and the
LiveKit handover are implemented. The final runtime is fixture-verified, not deployed. Both unchanged
reviewer agents have no remaining findings after the callback-handover correction.

Baseline: `aa11591`; implementation/evidence head before this report: `8e6b768`. Runtime last changed
in `96aa23d`; later commits strengthen tests, documentation and evidence. Schema: `2026-10-03.2`.
No push, merge, deployment, Azure/database mutation, secret retrieval or history rewrite occurred.
User-owned `temp/` and the supplied untracked Opus review remain untouched.

**Process exception:** commit `8575979` was incorrectly made before inspecting a failing fast run.
Its cancellation-test settings were invalid; its commit message incorrectly claimed a passing suite.
Commit `7494629` fixes that setup, demonstrates the intended cancellation failure and passes all 380
then-current tests. Both commits and all output are retained. This does **not** satisfy the user's
independently-green requirement for that one commit; it cannot be repaired without changing history,
which was explicitly prohibited. No claim of perfect process compliance is made.

## What changed

- Emergency/desk decisions survive bad optional metadata. Invalid optional fields are dropped without
  logging their values; normal malformed answers still fail explicitly. JSON and string limits apply.
- Knowledge routing speech has one location. Instructions now describe the real transfer,
  department-selection and clarification results. The date rule is byte-identical to baseline.
- Stronger boundary tests detect sequential booking reads, swallowed cancellation, private text in
  failure logs, schema/instruction drift, wrong doctor/choice IDs and any hidden availability KB call.
- Dead routing-era structure and fixture injection are removed. No parallel implementation exists.
- Deployment expects an explicitly configured or absent knowledge service, rejects partial production
  credentials, and removes an unused app secret reference after removing its environment reference.
- Current docs match the implementation. LiveKit handover specifies per-intent transport, a local
  write barrier, callback capture from both availability and booking, finalization and real transfer.
  Those voice functions are **instructions to the voice team**, not implemented SDK integrations here.

## Red and green output for each item

The following are excerpts from captured output, not estimates. Each link contains full commands,
tracebacks and exit codes. Red runs deliberately exercise old or mutated code; passing runs restore
correct runtime code. Full-suite green includes the failing selectors. Structural/document audits
are explicitly labelled and are not presented as behavioural tests.

| Item | Actual red output | Actual restored green output | Evidence |
|---|---|---|---|
| A1 + A5: transfer metadata, JSON and lengths | `13 failed, 26 passed` (8 transfer payloads, 3 media types, 2 length boundaries) | `373 passed, 11 deselected` | [red](opus-fix-evidence/A1-A5-red.txt), [green](opus-fix-evidence/A1-A5-green.txt) |
| A2 + A10: instructions, enum, developer wording | `3 failed, 18 deselected`; `DID NOT RAISE ValidationError` for old CLARIFY enum | `376 passed, 11 deselected` | [red](opus-fix-evidence/A2-A10-red.txt), [green](opus-fix-evidence/A2-A10-green.txt) |
| A3: one speech location and real fixture wording | `assert Speech(text='Owner wording', language='en') is None`; `5 failed, 51 passed` | `379 passed, 11 deselected` | [output](opus-fix-evidence/A3.txt) |
| A4: reads truly overlap | Sequential mutation: `1 failed, 60 deselected` (wait for both in-flight reads times out) | `379 passed, 11 deselected` | [output](opus-fix-evidence/A4-sequential-reads.txt), [patch](opus-fix-evidence/A4-sequential-reads.patch) |
| A6: external cancellation | Corrected mutation run: `Failed: DID NOT RAISE CancelledError`; `1 failed, 42 deselected` | `15 passed, 28 deselected` (cancellation + failure/privacy); then `380 passed` | [output](opus-fix-evidence/A6-cancellation.txt), [patch](opus-fix-evidence/A6-cancellation.patch) |
| A6: private question in failure log | `14 failed, 29 deselected`; assertion rejects `private caller question` in caplog | Same focused `15 passed`, then `380 passed` above | [red](opus-fix-evidence/A6-privacy.txt), [patch](opus-fix-evidence/A6-privacy.patch) |
| A6: forbidden transcript arguments | `get_doctor_availability exposes {'x-turn-context'}`; `1 failed, 20 deselected` | Corrected full run `380 passed` | [red](opus-fix-evidence/A6-transcript-argument.txt), [patch](opus-fix-evidence/A6-transcript-argument.patch) |
| A6: instructions artifact drift | `1 failed, 20 deselected` on byte comparison | Corrected full run `380 passed`; final independent comparison: `2684 bytes`, identical | [red](opus-fix-evidence/A6-artifact.txt), [patch](opus-fix-evidence/A6-artifact.patch), [comparison](opus-fix-evidence/final-audit.txt) |
| A6: exact doctors and choices | Empty choices: `2 failed, 16 passed`; wrong doctor IDs: `8 failed, 10 passed` | `400 passed, 11 deselected` after restoring both mutations | [choices](opus-fix-evidence/A6-matrix-choices.txt), [doctors](opus-fix-evidence/A6-matrix-doctors.txt), [green](opus-fix-evidence/B1-availability-knowledge.txt) |
| A7: leftover structure (static audit) | Three `FAIL` lines: synchronous composition, unreachable raise, unused injection | Three `PASS` lines; `380 passed` | [output](opus-fix-evidence/A7-cleanup.txt), [audit](opus-fix-evidence/A7-audit.py) |
| A8: partial settings | `10 failed, 1 passed, 21 deselected` | `391 passed, 11 deselected` | [output](opus-fix-evidence/A8-settings.txt) |
| A8: deploy/smoke | `11 failed, 22 passed`; missing expectation, mismatches, malformed bodies | `400 passed, 11 deselected` | [output](opus-fix-evidence/A8-release.txt) |
| A8: mismatch assertion mutation | `2 failed, 1 passed`; `DID NOT RAISE` when guard removed | Restored full run `400 passed` | [red](opus-fix-evidence/A8-expectation.txt), [patch](opus-fix-evidence/A8-expectation.patch), [green](opus-fix-evidence/A8-release.txt) |
| A9: six current documents (static audit) | Six `FAIL` lines | Six `PASS` lines; `400 passed` | [output](opus-fix-evidence/A9-docs.txt), [audit](opus-fix-evidence/A9-audit.py) |
| B1: actual hidden KB call | `AssertionError: availability must not contact knowledge`; `8 failed, 10 passed` | `400 passed, 11 deselected` after restoration | [output](opus-fix-evidence/B1-availability-knowledge.txt), [patch](opus-fix-evidence/B1-availability-knowledge.patch) |
| C1–C4: concrete voice handover (static audit) | Five initial `FAIL` lines; later `FAIL: callback transition on booking board recheck` | All six checks `PASS`; `400 passed` | [output](opus-fix-evidence/C-livekit.txt), [audit](opus-fix-evidence/C-livekit-audit.py) |

All **16** mutation diffs are committed with [replay bases and commands](opus-fix-evidence/README.md).
Seven reconstruct the earlier labelled probes from aa11591; their original red logs remain intact.
[Applicability output](opus-fix-evidence/patch-replay.txt) verifies every patch in isolated source copies;
this is not represented as re-executing historical tests. The date probe exists only as a patch file;
it was not applied in this correction pass.

## Final verification, pasted

Full [script output](opus-fix-evidence/final-suite.txt), run after all runtime/test/doc changes:

```text
$ ./scripts/test.sh
== lint
All checks passed!
== hermetic suites
400 passed, 11 deselected, 2 warnings in 23.82s
== process e2e (stubs + adapter over TCP)
2 passed, 409 deselected, 2 warnings in 2.36s
Successfully built /tmp/frontdesk-mcp-build/frontdesk_mcp-0.1.0.tar.gz
Successfully built /tmp/frontdesk-mcp-build/frontdesk_mcp-0.1.0-py3-none-any.whl
== production image build (no stubs, no fixtures, no dev dependencies)
== development stubs image build (compose profile stubs)
== external gates not run: no profile loaded
== all suites passed
EXIT: 0
```

The script also checked that the production image cannot import stubs or pytest. Warnings are the
existing Authlib deprecations. One earlier A6 full run exceeded an existing timing assertion on this
host; the focused and full reruns passed without loosening its deadline. Original output is preserved.

Additional [audit output](opus-fix-evidence/final-audit.txt):

```text
PASS make schema: byte-identical ... (43369 bytes)
PASS make agent-instructions: byte-identical ... (2684 bytes)
PASS date rule byte-identical to aa11591
$ git diff --exit-code aa11591 -- .claude/agents
(no output)
EXIT: 0
$ uvx vulture services/mcp/src --min-confidence 80
(no output)
EXIT: 0
```

The audit pastes `grep -rnIw` for every removed symbol across runtime, tests, stubs, deploy and
current docs: zero active matches. Scheduler outcome models have no routing field/vocabulary; neither
scheduler imports or holds knowledge. The lowercase forbidden-name blacklist is intentionally back.
**Not literally zero across the whole repository:** historical reports, reviewer evidence and mutation
patches preserve old names, and negative tests prohibit them. Deleting these would destroy requested
proof. No executable legacy path is retained. Patch-format context lines are excluded from the
whitespace check; all other changed tracked files pass it.

Source size, compared at 8e6b768:

```text
git diff aa11591 --numstat -- services/mcp/src
56 added, 19 deleted; net +37

git diff 73a0832 --numstat -- services/mcp/src
165 added, 359 deleted; net -194
```

The correction adds 25 net contract-validation/logging lines, 10 config-validation lines, 2 JSON
media-type lines, 1 result-construction line and 1 instruction line; deleting the unreachable raise
saves 2. Availability and pack edits have zero net change. No production module or dependency was
added. The complete removal-plus-correction still reduces production source by **194 lines**.
The full requested `git diff --stat` and per-file status are in [diff-stat.txt](opus-fix-evidence/diff-stat.txt).

## Reviewer findings and closure

The existing voice-safety and latency reviewer prompts were used unchanged. Safety's runtime checks
passed 191 focused tests; latency's passed 183. Both then reviewed the LiveKit handover against current
official docs/source and independently found the same callback gap: CREATE/RESCHEDULE can return
UNKNOWN after availability said IN, bypassing the read-tool result resolver.

Added the failing documentation audit before changing the handover. `booking_dispatch` now explicitly
initializes callback state from the frozen confirmed date and verified doctor information, and the
voice acceptance list covers that transition. Both reviewers re-read it and confirmed closure with no
remaining findings. These are repository/handover reviews, not validation of an implemented voice app.

## Mandatory checklist with its limits

- [x] Zero-knowledge availability assertion itself seen red (B1), restored and passing; unconfigured
  paths, exact doctor/choice IDs, empty/failure/date boundaries are in the 18-case matrix.
- [x] Requested new behavioural guards have old-code/mutation red output and restored green output.
  A7/A9/C are structural/doc audits. Historical harness-only edits were not retroactively proven one by
  one; preserved mutations improve reproducibility without rewriting that history.
- [x] No active removed symbols; vulture clean; retained historical/negative-test references disclosed.
- [x] Source-size accounting, version bump, byte-identical generated artifacts and full test script.
- [x] Current docs corrected. CLAUDE.md, PLAN.md and TARGET-STATE.md were already updated by the
  baseline task; this pass updates DECISIONS.md and the A9 docs rather than adding redundant churn.
- [x] Concrete voice handover; fresh reviewers' finding fixed and closure recorded.
- [x] Date rule, reviewer files, existing commits and user files preserved; nothing deployed.
- [x] Every new commit has at most ten files (audit output); report-only commits follow the same limit.
- [ ] Every new commit independently green: **8575979 fails**, corrected by 7494629 as described above.

## Remaining work and decisions (not claimed complete)

1. **Voice owner:** implement/test the local booking wrapper, safety checks, callback capture,
   outbox/finalizer and telephony transfer. ContextForge header delivery and scoped discovery need real
   gateway verification. There is no voice worker in this repository to implement or run these here.
2. **Knowledge owner / clinical owner:** accept the provisional answer contract and agree a separate
   every-turn classifier, outage policy and interim-risk acceptance. No service or consent was invented.
3. **Manoj / release owners:** prior credentials/scopes, usable board test data and synthetic-tenant
   confirmation were not re-probed. Real journeys and in-region caller-audio latency remain release
   checks. This pass uses local HTTP fixtures/processes only, as required by its no-deploy scope.
4. **Garima:** date interpretation stays unchanged pending your separate decision. Prior-task reviewer
   prompt changes (B5) still need your approval; none were edited here. Prior broken intermediate
   commits (B3) and the disclosed A6 correction remain, because rewriting/squashing is prohibited.
5. **Optional review D items:** benchmark expansion, pre-baseline reschedule parallelism/booking smells
   and external-test placeholder cleanup were not requested by the fix brief and remain follow-ups.
   The useful instructions/rollout and SDK-forwarding clarifications were included in LIVEKIT.md.

The next action is review of these local commits, not deployment or Azure cleanup.

## Per-file change list

Runtime/test/doc files are listed below; the finding table above identifies their verification.

| File | Change |
|---|---|
| `deploy/azure/deploy.sh` | A8: conditional validation bearer, explicit smoke expectation, ordered removal of stale app secret reference. |
| `deploy/azure/smoke.py` | A8: dictionary-shaped health/dependencies and explicit knowledge expectation/mismatch validation. |
| `deploy/environments/README.md` | A9/A8: fixed prose, dated historical endpoint claims, knowledge config/smoke lifecycle. |
| `docs/DECISIONS.md` | K1 correction semantics, configuration and voice handover mechanisms; risks retained. |
| `docs/architecture/TARGET.md` | A9: remove target from the documented operation-key input. |
| `docs/handover/CONTEXTFORGE.md` | A9: scheduling independence and updated trusted-header tests. |
| `docs/handover/LIVEKIT.md` | C1–C4: verified SDK wiring and specified platform-owned implementation/acceptance work. |
| `docs/handover/OWNER-INTEGRATION-MESSAGES.md` | A9: remove obsolete turn-header requests and knowledge-gated scheduling claims. |
| `docs/handover/TESTING.md` | A9: current owner-only scheduling and single-exchange knowledge test description. |
| `docs/handover/mcp-only/AGENT-INSTRUCTIONS.txt` | A2/A3/A10: regenerated exact model-facing instructions. |
| `docs/handover/mcp-only/README.md` | A9: remove obsolete instruction to preserve the routing gate. |
| `docs/handover/mcp-only/implementation/OPUS-FIX-PLAN.md` | Authorized delete/change/test sequence and explicit constraints. |
| `scripts/env.sh` | A8: derive and export expected knowledge mode from the loaded deployment profile. |
| `services/mcp/dev/frontdesk_stubs/data/demo_hospital.json` | A3: meaningful department speech replaces fixture placeholder. |
| `services/mcp/dev/frontdesk_stubs/knowledge.py` | A7: delete unused per-path failure injection and its path argument. |
| `services/mcp/src/frontdesk_mcp/availability.py` | A7: synchronous result composition; no second implementation. |
| `services/mcp/src/frontdesk_mcp/booking.py` | A7: delete unreachable profile exception branch only. |
| `services/mcp/src/frontdesk_mcp/config.py` | A8: whitespace normalization and paired knowledge URL/bearer validation. |
| `services/mcp/src/frontdesk_mcp/knowledge.py` | A3: speech only in the correct result field. |
| `services/mcp/src/frontdesk_mcp/knowledge_client.py` | A5: reject non-JSON media types before interpreting response. |
| `services/mcp/src/frontdesk_mcp/knowledge_contract.py` | A1/A2/A5: decision-first validation, preserve transfer signal, bounded fields, remove impossible routing enum. |
| `services/mcp/src/frontdesk_mcp/packs/healthcare.json` | A3/A10: one speech location and direct emergency instruction. |
| `services/mcp/src/frontdesk_mcp/prompt.py` | A2: real next steps and explicit departmentName mapping; schema bump; date unchanged. |
| `services/mcp/tests/contracts/mcp-tools.snapshot.json` | Regenerated public schema/description snapshot. |
| `services/mcp/tests/test_availability.py` | A6/B1: exact IDs/choices and empty results in the no-knowledge matrix. |
| `services/mcp/tests/test_booking.py` | A4: longer hang and concurrent in-flight assertions before cancellation. |
| `services/mcp/tests/test_deploy.py` | A8: dry-run upgrade/secret ordering, expectations and malformed response tests. |
| `services/mcp/tests/test_external_transport.py` | A8: external transport gate requires explicit knowledge expectation. |
| `services/mcp/tests/test_knowledge.py` | A1/A3/A5/A6: bad metadata, media type, lengths, speech, cancellation and private failure-log tests. |
| `services/mcp/tests/test_server.py` | A2/A6/A10: current instructions, forbidden argument names and byte comparison of artifact. |
| `services/mcp/tests/test_settings.py` | A8: malformed/partial production config and whitespace cases. |
| `services/mcp/tests/test_stubs.py` | A3: assert meaningful department-routing speech. |

Evidence files (every new path; logs contain commands and outcomes, patches reproduce defects):

- [A1-A5-green.txt](opus-fix-evidence/A1-A5-green.txt) — captured command output.
- [A1-A5-red.txt](opus-fix-evidence/A1-A5-red.txt) — captured command output.
- [A2-A10-green.txt](opus-fix-evidence/A2-A10-green.txt) — captured command output.
- [A2-A10-red.txt](opus-fix-evidence/A2-A10-red.txt) — captured command output.
- [A3.txt](opus-fix-evidence/A3.txt) — captured command output.
- [A4-sequential-reads.patch](opus-fix-evidence/A4-sequential-reads.patch) — replayable deliberate defect.
- [A4-sequential-reads.txt](opus-fix-evidence/A4-sequential-reads.txt) — captured command output.
- [A6-artifact.patch](opus-fix-evidence/A6-artifact.patch) — replayable deliberate defect.
- [A6-artifact.txt](opus-fix-evidence/A6-artifact.txt) — captured command output.
- [A6-cancellation.patch](opus-fix-evidence/A6-cancellation.patch) — replayable deliberate defect.
- [A6-cancellation.txt](opus-fix-evidence/A6-cancellation.txt) — captured command output.
- [A6-matrix-choices.patch](opus-fix-evidence/A6-matrix-choices.patch) — replayable deliberate defect.
- [A6-matrix-choices.txt](opus-fix-evidence/A6-matrix-choices.txt) — captured command output.
- [A6-matrix-doctors.patch](opus-fix-evidence/A6-matrix-doctors.patch) — replayable deliberate defect.
- [A6-matrix-doctors.txt](opus-fix-evidence/A6-matrix-doctors.txt) — captured command output.
- [A6-privacy.patch](opus-fix-evidence/A6-privacy.patch) — replayable deliberate defect.
- [A6-privacy.txt](opus-fix-evidence/A6-privacy.txt) — captured command output.
- [A6-transcript-argument.patch](opus-fix-evidence/A6-transcript-argument.patch) — replayable deliberate defect.
- [A6-transcript-argument.txt](opus-fix-evidence/A6-transcript-argument.txt) — captured command output.
- [A7-audit.py](opus-fix-evidence/A7-audit.py) — executable structural/document acceptance audit.
- [A7-cleanup.txt](opus-fix-evidence/A7-cleanup.txt) — captured command output.
- [A8-expectation.patch](opus-fix-evidence/A8-expectation.patch) — replayable deliberate defect.
- [A8-expectation.txt](opus-fix-evidence/A8-expectation.txt) — captured command output.
- [A8-release.txt](opus-fix-evidence/A8-release.txt) — captured command output.
- [A8-settings.txt](opus-fix-evidence/A8-settings.txt) — captured command output.
- [A9-audit.py](opus-fix-evidence/A9-audit.py) — executable structural/document acceptance audit.
- [A9-docs.txt](opus-fix-evidence/A9-docs.txt) — captured command output.
- [B1-availability-knowledge.patch](opus-fix-evidence/B1-availability-knowledge.patch) — replayable deliberate defect.
- [B1-availability-knowledge.txt](opus-fix-evidence/B1-availability-knowledge.txt) — captured command output.
- [C-livekit-audit.py](opus-fix-evidence/C-livekit-audit.py) — executable structural/document acceptance audit.
- [C-livekit.txt](opus-fix-evidence/C-livekit.txt) — captured command output.
- [README.md](opus-fix-evidence/README.md) — replay guide and process limitations.
- [patch-replay.txt](opus-fix-evidence/patch-replay.txt) — captured command output.
- [prior-01-empty-input.patch](opus-fix-evidence/prior-01-empty-input.patch) — replayable deliberate defect.
- [prior-02-routing-speech.patch](opus-fix-evidence/prior-02-routing-speech.patch) — replayable deliberate defect.
- [prior-03-deadline.patch](opus-fix-evidence/prior-03-deadline.patch) — replayable deliberate defect.
- [prior-04-smoke-envelope.patch](opus-fix-evidence/prior-04-smoke-envelope.patch) — replayable deliberate defect.
- [prior-05-bench-write.patch](opus-fix-evidence/prior-05-bench-write.patch) — replayable deliberate defect.
- [prior-06-stub-path.patch](opus-fix-evidence/prior-06-stub-path.patch) — replayable deliberate defect.
- [prior-07-date-validation.patch](opus-fix-evidence/prior-07-date-validation.patch) — replayable deliberate defect.
- [final-suite.txt](opus-fix-evidence/final-suite.txt) — complete final test/build output.
- [final-audit.txt](opus-fix-evidence/final-audit.txt) — symbol, date, reviewer, artifact, source-size and vulture checks.
- [diff-stat.txt](opus-fix-evidence/diff-stat.txt) — requested full Git diff stat and file status.
- [handback-fast.txt](opus-fix-evidence/handback-fast.txt) — final report/evidence commit fast-suite receipt.
- `OPUS-FIX-REPORT.md` — this acceptance report, excerpts, limitations and per-file index.
