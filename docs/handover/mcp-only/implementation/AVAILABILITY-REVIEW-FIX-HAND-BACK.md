# Availability review fix hand-back — 6 October 2026

Status: implemented and locally verified; ready for Opus re-review. No push, merge, deployment,
Azure change or live write. Base: `228f0a0`. Branch: `Garry2012/garry2012/mcp-target-required`.
User request: availability-review fix prompt dated 6 October; original findings in
[OPUS-AVAILABILITY-POLICY-REVIEW.md](OPUS-AVAILABILITY-POLICY-REVIEW.md).

## Findings, root causes and rule ownership

| Item | Root cause and coherent fix | Proof |
|---|---|---|
| I-1 | `_future` applied the failed selection to every usual session; it now classifies sessions by weekday, preserves same-day alternatives, and keeps the doctor-level refusal. `decide_booking` respects that refusal; `_single` matches only sessions applicable to the date. | 01 red, 02 green; existing booking SESSION_NOT_USUAL test retained. |
| M-1 / 6 October owner rule | Hours-only presentation overrode callback outcomes, reused booking counts and lost on-call facts in ranking. `working_hours` uses the shared on-call policy; `_single` maps callback consistently; `aggregate` owns candidate selection and public counts; `rank` only orders/caps. | 07 red, 08 green; name/id, empty profile, regular hours, mixed department. |
| I-2 | The time model has no cross-midnight interpretation. Added the explicit unsupported limitation to DECISIONS, VOICE-TEAM and current handover; time logic unchanged. | AST audit 23; documentation-only, no invented red test. |
| M-2 | The known-on-call shortcut was after the today read branch. Moved the existing shortcut before date selection in `ScheduleReader.doctor`. | 12 red, 13 green; name query returns callback despite scripted board failure, zero board requests. |
| M-3 | `_schedule_gate` caught upstream read failures but omitted invalid owner identifiers. Added the existing `InvalidIdentifier` exception to that boundary. | 15 red, 16 green; malformed owner doctorId refuses reschedule with COULD_NOT_RECORD, without a write or identifier echo. |
| M-4 | Four test names described superseded behavior. Renamed them to describe profile failure, on-call callback, unmatched-today callback and capped name counts. | 20 fast green; test bodies unchanged by these renames. |
| M-5 | VOICE-TEAM lacked a consolidated consumer migration note. Added the 2026-10-05.1 breaking changes and the 2026-10-06.1 correction note. | Schema comparison 23; documentation-only. |
| M-6 | The hours smoke probe omitted an honest incomplete-search outcome. Added HANDOFF_REQUIRED to that probe's accepted outcomes. | 18 red, 19 green; actual MCP transport exercised against a boundary fixture. |

Availability remains read-only. The separate booking tool shares policy and retrieval, so its refusal
mapping and malformed upstream ID handling are covered too. Neither change creates appointments from
an availability request.

## Cleanup and design

- Renamed internal `SearchState.bookable_found` to `matches_found`: a working-hours search match is not
  evidence of a bookable appointment. Existing bounded search behavior remains intact.
- Moved candidate filtering out of `rank` into `aggregate`, so one policy selects the result and ranking
  cannot silently drop on-call facts from department working-hours results. Removed duplicate service
  filtering. No flag parameter, second reader or compatibility path.
- Removed unused `NO_REGULAR_HOURS` and an unused test import. Callback metadata now consistently uses
  `ON_CALL_DOCTOR` or `NO_USUAL_SCHEDULE` and `summaryOutcome=CALLBACK_NOTED`.
- Corrected a text guard's substring false positive: `ask ` matched inside `task is created`. It now
  checks whole words. The prohibition on spoken instructions is retained. Its observed failure is in 10.
- Old tests expecting WORKING_HOURS/NO_REGULAR_HOURS for an on-call individual were replaced because
  Garima's explicit 6 October rule supersedes that expectation. No skipped or xfailed regression tests.

Runtime diff: **52 insertions, 47 deletions; net +5 lines** across seven files. The policy's net +6
provides one typed candidate/count result, the search-field explanation and doctor-level refusal;
outcomes' net +1 documents hours counts. Availability's net -2 removes duplicated result filtering.
Other runtime files have zero net growth. No new runtime file or configuration setting.

## Red → green evidence (actual terminal summaries)

All files below are in [availability-review-fix-evidence/](availability-review-fix-evidence/).
Raw output is preserved, including pytest's failure formatting and whitespace.

```text
I-1:    01-I1-red.txt:           3 failed, 97 deselected in 0.28s
        02-I1-green.txt:         180 passed, 2 warnings in 3.09s
Rename: 04-search-count-red.txt: 7 failed, 41 passed in 0.40s
        05-search-count-green.txt: 48 passed in 0.38s
M-1:    07-M1-red.txt:           9 failed, 2 passed, 92 deselected in 0.37s
        08-M1-green.txt:         198 passed, 2 warnings in 3.39s
M-2:    12-M2-red.txt:           1 failed, 70 deselected in 0.24s
        13-M2-green.txt:         86 passed, 2 warnings in 2.14s
M-3:    15-M3-red.txt:           2 failed, 80 deselected in 0.32s
        16-M3-green.txt:         82 passed, 2 warnings in 2.16s
M-6:    18-M6-red.txt:           1 failed, 1 passed, 38 deselected, 2 warnings in 0.99s
        19-M6-green.txt:         40 passed, 2 warnings in 7.99s
```

The rename red output proves the internal field contract changed; it is not presented as a new
business behavior failure. Behavior regressions assert results and owner HTTP requests. I-2, M-4,
M-5 and documentation have no fabricated red runs. Intermediate lint/text-guard failures are retained
in 09 and 10; final lint is green.

## Consumer contract

One schema bump in this fix pass: **2026-10-05.1 → 2026-10-06.1**, because the output schema adds
`PRESENT_WORKING_HOURS` and removes unused `NO_REGULAR_HOURS`. Tool descriptions were updated and the
schema snapshot and VOICE-TEAM generated reference regenerated. All four input schemas are unchanged;
`search_knowledge` and `record_call_summary` full tool definitions are unchanged.

The preceding 2026-10-05.1 migration remains documented: `journey` → `decision`; CALLBACK_ONLY/DESK,
`expired`, `unknownSessions`, callback spoken fields removed; optional date plus purpose; booking
`departmentId` removed. This pass does not claim those earlier changes were deployed.

After separately approved deployment, refresh ContextForge discovery and compare **outputSchema**
through the voice-facing virtual MCP server. The input-only drift checker can report no change from
5.1 while output definitions remain stale. Refresh voice caches too. Credentials, headers, owner
contract, client retries, write idempotency and deadlines are unchanged. No secret migration required.

## Verification

```text
make test-fast
547 passed, 11 deselected, 2 warnings

env -u OPS_E2E_BASE_URL ./scripts/test.sh
== lint
All checks passed!
== hermetic suites
547 passed, 11 deselected, 2 warnings in 29.73s
== process e2e (stubs + adapter over TCP)
2 passed, 556 deselected, 2 warnings in 2.67s
== package build
Successfully built /tmp/frontdesk-mcp-build/frontdesk_mcp-0.1.0.tar.gz
Successfully built /tmp/frontdesk-mcp-build/frontdesk_mcp-0.1.0-py3-none-any.whl
== production image build (no stubs, no fixtures, no dev dependencies)
== development stubs image build (compose profile stubs)
== external gates not run: no profile loaded (scripts/run-profile.sh mock|live -- ./scripts/test.sh)
== all suites passed

make schema > .context/availability-review-schema.json
cmp .context/availability-review-schema.json services/mcp/tests/contracts/mcp-tools.snapshot.json
exit 0, identical

uvx vulture services/mcp/src --min-confidence 80
exit 0, no findings
```

Full output: 21 (documentation fast check), 22 (full build), 23 (schema/AST/source audit), 24 (knowledge
independence regression), 25 (final fast check: 547 passed, 11 deselected, 2 warnings in 30.13s). The two warnings are existing Authlib deprecations. No standalone static type
checker was run; repository lint and runtime schema/type validation are included in the tests.

The audit proves `_combine`, `_window`, `resolve_date` and `_today` unchanged, plus unchanged owner
contracts, authentication/context, configuration, operational client, deployment and registration
scripts. Smoke acceptance is the only deployment-code change. Runtime removed-symbol searches are
pasted in 23: obsolete routing inputs remain absent; ROUTING_REQUIRED remains intentionally in the
separate knowledge tool and its smoke acceptance. Historical documentation/evidence retains old names;
this is not a claim of zero textual hits throughout history. No reviewer-agent files changed.

Independent safety review: no concrete regression, 241 focused tests passed. Independent latency
review: no concrete regression, 119 focused tests passed; known-on-call lookup removes an owner read.
A final documentation safety review also found no concrete inconsistencies. Neither review established live latency. Pooling, cache, deadline and refresh rules are unchanged.

## Changed files and verification map

| Files | Change / check |
|---|---|
| `availability_policy.py` | Weekday facts, refusal preservation, hours callback and aggregation; policy tests. |
| `availability.py` | Date-aware matching, full callbacks, hours next step/count, selected candidates; availability tests. |
| `schedule_reader.py` | Reused early known-on-call shortcut; owner-request tests. |
| `booking.py` | InvalidIdentifier mapped at read boundary; booking tests. |
| `outcomes.py`, `prompt.py`, `packs/healthcare.json` | Output enum/docs/version; schema equality and server tests. |
| `tests/contracts/mcp-tools.snapshot.json` | Generated contract; `make schema` comparison. |
| `test_availability.py`, `test_availability_policy.py`, `test_schedule_reader.py`, `test_booking.py` | Behavioral regression cases and internal field rename. |
| `test_server.py` | Whole-word text guard retaining spoken-instruction prohibition. |
| `deploy/azure/smoke.py`, `test_deploy.py` | Accept honest incomplete hours result; local MCP transport test. |
| `VOICE-TEAM.md`, `CONTEXTFORGE.md` | Generated reference, schema migration and output refresh acceptance. |
| `CLAUDE.md`, `DECISIONS.md`, `TESTING.md`, MCP-only `PLAN.md`, `README.md`, `TARGET-STATE.md` | Current rules, limitations, evidence links. |
| This hand-back and evidence directory | Reproducible review proof. |
| Original Opus review | Preserved unchanged and tracked for review context. |

## Commit sequence

Every commit has at most ten files and a green `make test-fast` checkpoint; no commit was squashed.

| Commit | Files | Purpose | Fast proof |
|---|---:|---|---|
| 76661b5 | 7 | Future alternatives/date-specific matching | 03: 540 passed |
| 53f03d2 | 7 | Search-match naming | 06: 540 passed |
| b874f24 | 10 | Hours policy, outputs, schema, voice reference | 11: 543 passed |
| 0d89e1f | 10 | Known-on-call shortcut and preceding proof files | 14: 544 passed |
| 5601879 | 5 | Malformed upstream identifier | 17: 546 passed |
| b7c5a30 | 6 | Smoke/rename corrections | 20: 547 passed |
| ee73b37 | 9 | Current docs and unchanged Opus report | 21: 547 passed |

The final hand-back/evidence commit contains five files, with checkpoint 25 green; their hashes/file counts are available from
`git log --oneline 228f0a0..HEAD` and `git diff-tree --no-commit-id --name-only -r <sha>`.

## Not done / release boundaries

- **G-1 unchanged**: mixed ended/cancelled/offerable sessions can still require a choice, pending Garima.
- **M-7 not implemented**: optional additional today-board facts need approval.
- **Overnight sessions unsupported**: documented only; no hidden time behavior change.
- No live owner writes, live smoke, Azure deployment, ContextForge refresh or voice/audio validation.
  Real service data and post-deploy acceptance are still required; passing fixtures is not production proof.
- No new benchmark or claim of sub-300 ms caller response. In-region, gateway and end-to-end audio
  latency remain external acceptance tasks.
- User `temp/` preserved. Reviewer prompts untouched. No backend or database implementation added.

Ready for code review; merge/deployment still require explicit approval and coordinated schema refresh.

## Addendum checklist with proof

- [x] Availability remains independent of knowledge, configured or unconfigured:
  `services/mcp/.venv/bin/pytest -q services/mcp/tests/test_availability.py -k independent_of_knowledge_and_transcript`
  → **18 passed, 53 deselected, 2 warnings in 0.64s** (24).
- [x] Removed runtime symbols searched; exact commands/results in 23. Knowledge-only ROUTING_REQUIRED
  is intentional; historical references are retained. Vulture produced no findings.
- [x] Runtime line growth justified above; no parallel implementation or new settings.
- [x] Behavior regressions seen red before green; pasted summaries above, full proof 01–20.
- [x] Full test/build suite green, schema identical to snapshot, schema version bumped once this pass.
- [x] CLAUDE, PLAN, TARGET-STATE, DECISIONS and current voice handover updated together.
- [x] Existing voice-side guardrail/integration instructions retained; this task changes no LiveKit API.
- [x] Safety and latency reviews completed with no concrete findings; review-agent files untouched.
- [x] Per-file map, deferred decisions, external acceptance and release boundary listed above.
