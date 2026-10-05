# Availability policy revision 6 — implementation hand-back

Source baseline: `892e537`. Branch: `Garry2012/garry2012/mcp-target-required`.
Approved policy: [AVAILABILITY-POLICY-PLAN.md](AVAILABILITY-POLICY-PLAN.md), revision 6.
Local source implementation and fixture verification complete. No push, merge, deploy, Azure change
or live appointment/summary write was performed. Existing user `temp/` files were not touched.
This is ready for code review; deployment still needs separate approval and the acceptance below.

## Pre-flight and behavior

Initial pre-flight exposed four ambiguities. The revision 6 attachment resolved all four; rechecking
the revised sections against the pinned contract and implementation leaves no conflict:

1. Owner board `status` remains IN/LATE/CANCELLED/NOT_CONFIRMED/UNKNOWN, byte-identical schema.
   MCP's `decision`/`reason` are separate at session and doctor level; old journey is removed.
2. Different decisions with a bookable session need selection; equal decisions permit a day-level
   request. No owner session field is invented.
3. Departments list only bookable doctors when any exist, name ordered/capped; otherwise callback
   and unavailable facts. Handoff lists none. Directory total, bookable count and completeness differ.
4. ContextForge registration checks names/input schemas only. No register.py change; output schemas
   need manual acceptance through the voice virtual server after separately approved deployment.

Today uses the live board only. Future dates and WORKING_HOURS use usual schedules and never call
`GET /availability`. ON_CALL always requires callback. Availability without a date returns DATE_REQUIRED;
WORKING_HOURS permits no date. CREATE requires doctorId; RESCHEDULE derives it from the verified
caller's appointment. Both successful writes report NOTED, retaining the nested owner status.
An explicit time with no supplied end time in a bookable session yields handoff, without a write.
Callback metadata is reason + CALLBACK_NOTED; no speech scripts, task or transfer is executed.

One pure availability_policy.py replaces board_scope.py and duplicated decision/date logic.
One schedule_reader.py owns cached retrieval and sorted deadline-bound batches. No knowledge calls
are added to scheduling. Four tools, the five trusted headers, all credentials, LIST/CANCEL authority,
confirmation, frozen operation keys, 401-only refresh and uncertainty remain unchanged.

## Test-first evidence

Full outputs are linked below; pasted summaries are the actual command results. New policy/reader
modules initially fail because they are absent; subsequent service/interface tests fail on the old
behavior. Existing unaffected regression cases in those groups also pass in the red runs; they are
not presented as newly failing tests. Tests that formerly asserted retired behavior were replaced.
Final order/cache tests use isolated mutations (remove local sort and disable profile caching),
then pass on unchanged production code. Those mutants never entered the main workspace source.
A lint-only failure on test line length/non-cryptographic seeded shuffle is retained in evidence38;
wrapping the line and a test-only S311 explanation resolves it. No test was skipped or xfailed.

### Pure policy: statuses, dates, hours, on-call, aggregation

[01-policy-red](availability-policy-evidence/01-policy-red.txt) → [02-policy-green](availability-policy-evidence/02-policy-green.txt)

```text
RED: 29 failed in 0.20s
GREEN: 29 passed in 0.05s
```

### Reader bounds, cache, deadline and cancellation

[04-reader-red](availability-policy-evidence/04-reader-red.txt) → [05-reader-green](availability-policy-evidence/05-reader-green.txt)

```text
RED: 12 failed, 1 passed in 0.18s
GREEN: 13 passed in 0.21s
```

### Availability orchestration and result mapping

[07-availability-red](availability-policy-evidence/07-availability-red.txt) → [08-availability-green](availability-policy-evidence/08-availability-green.txt)

```text
RED: 29 failed, 35 passed, 2 warnings in 2.21s
GREEN: 64 passed, 2 warnings in 1.84s
```

### Purpose/optional date and schema

[10-interface-red](availability-policy-evidence/10-interface-red.txt) → [11-interface-green](availability-policy-evidence/11-interface-green.txt)

```text
RED: 2 failed, 37 deselected, 2 warnings in 1.25s
GREEN: 2 passed, 37 deselected, 2 warnings in 0.98s
```

### Policy refuses unresolved/failed write facts

[13-booking-policy-red](availability-policy-evidence/13-booking-policy-red.txt) → [14-booking-policy-green](availability-policy-evidence/14-booking-policy-green.txt)

```text
RED: 2 failed, 29 deselected in 0.08s
GREEN: 31 passed in 0.05s
```

### Doctor-only booking and shared date/session policy

[16-booking-red](availability-policy-evidence/16-booking-red.txt) → [17-booking-green](availability-policy-evidence/17-booking-green.txt)

```text
RED: 19 failed, 55 passed, 2 warnings in 2.42s
GREEN: 105 passed, 2 warnings in 2.08s
```

### Booking schema removed department target

[18-booking-interface-red](availability-policy-evidence/18-booking-interface-red.txt) → [19-booking-fast](availability-policy-evidence/19-booking-fast.txt)

```text
RED: 1 failed, 39 deselected, 2 warnings in 1.17s
GREEN: 525 passed, 11 deselected, 2 warnings in 29.16s
```

### Safety review: unlabelled scope, end seconds, alternatives, hours

[20-review-red](availability-policy-evidence/20-review-red.txt) → [21-review-green](availability-policy-evidence/21-review-green.txt)

```text
RED: 5 failed, 2 passed, 169 deselected in 0.41s
GREEN: 7 passed, 169 deselected in 0.19s
```

### Multi-batch fixture with request history/delays

[23-fixture-red](availability-policy-evidence/23-fixture-red.txt) → [24-fixture-green](availability-policy-evidence/24-fixture-green.txt)

```text
RED: 1 failed, 15 deselected in 0.26s
GREEN: 16 passed in 0.33s
```

### Read-only hours smoke and verified cold/warm bench

[26-tooling-red](availability-policy-evidence/26-tooling-red.txt) → [27-tooling-green](availability-policy-evidence/27-tooling-green.txt)

```text
RED: 3 failed, 42 deselected, 2 warnings in 3.88s
GREEN: 45 passed, 2 warnings in 10.77s
```

### Time between known windows

[29-time-gap-red](availability-policy-evidence/29-time-gap-red.txt) → [30-time-gap-green](availability-policy-evidence/30-time-gap-green.txt)

```text
RED: 1 failed, 79 deselected in 0.24s
GREEN: 1 passed, 79 deselected in 0.14s
```

### 20 owner permutations and warm partial-cache progress

[36-reader-mutation-red](availability-policy-evidence/36-reader-mutation-red.txt) → [37-reader-green](availability-policy-evidence/37-reader-green.txt)

```text
RED: 2 failed, 13 deselected in 0.39s
GREEN: 15 passed in 0.34s
```

The existing idempotency target-change test keeps its conflict/key assertions; its second doctor
fixture changes to one whose supplied window includes the existing requested time. This avoids the
new correct time refusal masking the replay assertion. LIST/CANCEL/verification/uncertainty semantics
were not relaxed. E2E now tests future CREATE/reschedule without any future board setup and asserts
zero GET /availability during that future segment.

## Verification

```text
./scripts/test.sh (OPS_E2E_BASE_URL unset: no external gates or live writes)
All checks passed!
537 hermetic tests passed
2 process e2e tests passed
source distribution and wheel built
production image built; no stubs or pytest in it
development stubs image built
== all suites passed

make schema compared with pinned snapshot: identical
BoardSessionOut.status unchanged from baseline: PASS
record_call_summary schema unchanged except approved description prose: PASS
uvx vulture services/mcp/src --min-confidence 80: exit 0, no findings
make demo: exit 0
make test-fast: 537 passed, 11 deselected (2 e2e + 9 external), 2 dependency warnings
```

Logs: [full runner](availability-policy-evidence/40-full-verification.txt),
[schema comparison](availability-policy-evidence/42-schema-proof.txt),
[vulture](availability-policy-evidence/35-vulture.txt), [demo](availability-policy-evidence/41-demo.txt).
The repository has no separate configured mypy/pyright gate; no claim of static type-check success.
The two warnings are existing Authlib deprecations. External tests were deliberately not selected;
they remain explicit failing gates when required inputs are absent, rather than silent skips.

One schema bump: `2026-10-04.2` → `2026-10-05.1`. Earlier call-summary bumps are historical;
this availability change makes only one new bump. Snapshot and VOICE-TEAM match.

## Latency

[Actual benchmark output](availability-policy-evidence/32-benchmark.txt). 50 calls/scenario,
concurrency 1, warm token. Boundary: local TCP MCP tool call plus in-process ASGI fixture owner,
after session initialization. These are adapter fixture timings, not production or caller-audio evidence.

| Scenario | p50 ms | p95 ms | Intended outcome verified | Failures |
|---|---:|---:|---:|---:|
| availability_known_doctor | 27.9 | 31.7 | 50/50 | 0 |
| availability_department | 30.2 | 37.4 | 50/50 | 0 |
| availability_department_future_cold | 31.4 | 41.2 | 50/50 | 0 |
| availability_department_future_warm | 28.4 | 31.8 | 50/50 | 0 |

All four have zero samples over 300 ms. Future cold mode cleared profile/directory cache each call:
450 profile reads across 50 samples (9 per call). Warm mode had zero profile reads after priming.
Both still perform directory search and require its observed owner request; future board requests
are rejected by the benchmark. The fixture has early/late matches, empty schedules, visiting and
on-call doctors across multiple batches. Controlled delay tests exercise timeouts and partial progress.
Defaults retained: DOCTOR_CHOICE_LIMIT=3, PROFILE_BATCH_SIZE=3, MIN_BATCH_HEADROOM_SECONDS=0.05,
read/write share=0.30 s, existing profile cache=300 s; no tuning was justified by the local measurements.

## Independent review

Safety reviewer found and closed: unlabelled/whitespace UNKNOWN rows lost during time selection;
minute-only expiry missing seconds; useful alternatives dropped; working-hours on-call callback nextStep;
time between known windows incorrectly returning callback. Fixes have red/green evidence20/21 and29/30.
It also corrected the E2E audit from POST to actual GET board reads. Final code review: no remaining
concrete safety/privacy finding; 141 focused tests passed. Final documentation review found three old
statements (callback reasons, department CREATE, call-end summary access), corrected in current docs and explicitly confirmed closed by the reviewer.
Latency reviewer: no concrete final finding, 90 focused tests passed. It reviewed the measured report,
not an independent repeat of the 50-sample bench. No live-path latency conclusion is claimed.
Reviewer prompts are unchanged. voice-safety-reviewer.md point4 still has the obsolete future UNKNOWN
rule; point6 also assumes old summary/reason behavior. Reviewers used the approved current policy.

## Removal and size

[Repository removal audit](availability-policy-evidence/43-removal-audit.txt) records every hit and
scoped zero-hit checks. board_scope.py, duplicate caches/date parser, old overlay/finish/expiry,
board gate, department writes, old output fields and spoken callback scripts are gone from runtime.
Old names remain in historical review/evidence files, this removal report and the approved plan;
the mandated unchanged reviewer prompt also retains its obsolete wording. They are not live paths.
Owner DESK/source values, knowledge DESK_TRANSFER and Deadline.expired are unrelated valid uses.
Availability departmentId remains a directory input; booking tests mention it only to verify rejection.

Source diff: 694 added, 480 removed; net **+214 lines**.
[Full pre-hand-back diff stat](availability-policy-evidence/45-diff-stat.txt).
The increase is justified by the approved new purposes, explicit typed policy results and bounded
multi-batch retrieval: new pure policy327 + reader137 lines, while availability shrinks143, booking56,
and obsolete board_scope83 lines. Other net additions are schema fields20, config8, tool wiring2,
and prompt2. This replaces orchestration rules rather than retaining a second path.

## Affected files/subsystems

| Files | Change / verification |
|---|---|
| src/frontdesk_mcp/availability_policy.py (new), board_scope.py (deleted) | One pure date/status/session/ranking/write policy; test_availability_policy + booking tests. |
| src/frontdesk_mcp/schedule_reader.py (new), config.py | Shared bounded caches/profile batches, headroom and cancellation; reader tests plus settings validation. Retired unused directory_page_size. |
| src/frontdesk_mcp/availability.py, booking.py | Thin policy orchestration, future profile-only reads, doctor-only writes, alternatives and truthful failures; HTTP boundary suites. |
| src/frontdesk_mcp/outcomes.py, tools.py, prompt.py, packs/healthcare.json | Separate status/decision, purpose/date, fields/counts/callback metadata, facts-only text, shared reader, version. |
| tests/contracts/mcp-tools.snapshot.json; docs/handover/VOICE-TEAM.md | Generated tool shapes plus field/code meanings; snapshot and interface checks. |
| dev/frontdesk_stubs/ops.py, dev/frontdesk_stubs/data/demo_hospital.json | Synthetic request recording/delay controls and multi-batch schedules; test_stubs. Never production image contents. |
| dev/demo.py, dev/bench.py, deploy/azure/smoke.py | Future/hours demonstration, cold/warm truthful benchmark and extra read-only hours probe; test_bench/test_deploy. |
| tests/test_availability_policy.py, test_schedule_reader.py (new), test_availability.py, test_booking.py | New policy/reader cases and replacement of obsolete rules, red/green logs. |
| tests/test_server.py, test_e2e_processes.py, test_external.py, test_stubs.py, test_bench.py, test_deploy.py | Schema/privacy/transport, future no-board journey, owner gates, fixtures/tooling checks. |
| .env.example, CLAUDE.md, README.md, services/mcp/README.md | Defaults, ownership/current rules and build instructions. |
| docs/DECISIONS.md, docs/architecture/TARGET.md, docs/handover/mcp-only/PLAN.md, TARGET-STATE.md, README.md | Approved policy, tradeoffs, counts, no owner-engine dependency and rollout constraints. |
| docs/handover/CONTEXTFORGE.md, TESTING.md, OWNER-INTEGRATION-MESSAGES.md; implementation/OPEN-DEPENDENCIES.md | Manual output-schema acceptance, future usual-day owner tests, current summary/access rules and external needs. |
| implementation/AVAILABILITY-POLICY-PLAN.md, this hand-back, availability-policy-evidence/* | Approved source of truth, raw red/green/build/bench evidence and review results. |

Paths beginning src/, tests/ or dev/ above are under services/mcp/. No deploy.sh, register.py, secret,
owner contract, authentication client, knowledge implementation, summary service or reviewer-agent change.

## Commits (no squash; maximum 10 files)

Groups were split into smaller independently green commits to respect the ten-file cap including
proof files; the original logical order is preserved. Fast-run logs03,06,09,12,15,19,22,25,28,31,33,34,39
record each implementation commit. Evidence22 was run on an isolated exact staged safety change,
because concurrently prepared fixture tests were not part of that commit.

| Commit | Files | Purpose |
|---|---:|---|
| `55b9347` | 5 | Define date-aware availability decisions from owner facts |
| `0bd4549` | 6 | Bound schedule reads by batch, cache and invocation deadline |
| `33e731e` | 10 | Apply today and future policy to availability responses |
| `a3d26c7` | 10 | Expose working-hours purpose and precise availability counts |
| `ed82228` | 5 | Keep unresolved and failed facts outside booking writes |
| `29c1024` | 10 | Apply shared schedule decisions before doctor appointment writes |
| `6906af7` | 9 | Close unsafe session edges and remove obsolete board scoping |
| `b89757f` | 9 | Exercise future schedules with synthetic batches and owner gates |
| `943ca2d` | 7 | Probe working hours and measure cold and warm future lookups |
| `fc0c779` | 6 | Reject times between known session windows before callback aggregation |
| `c55f60d` | 9 | Document date-aware policy and retire unused directory page setting |
| `011fc25` | 8 | Align owner and gateway acceptance with revision six availability |
| `fde0d55` | 8 | Prove deterministic profile order and warm search progress |
| `ead9bc1` | 9 | Close documentation review gaps and preserve booking evidence |

Final documentation/evidence commits follow this table without altering runtime behavior; their
fast-suite logs and file counts are included in [the final commit audit](availability-policy-evidence/47-commit-audit.txt). No existing commit was rewritten.

## Not verified / release dependencies

- No real owner reads/writes or Azure operations in this task. Before release, verify a live doctor's
  usualSchedule is populated. Empty schedules intentionally produce callback; do not infer hours.
- Manoj: confirm synthetic tenant, provide a REGULAR/VISITING doctor and two future usual working dates;
  designate today's UNKNOWN/NOT_CONFIRMED negative case; grant calls.write if still missing. Existing
  vault credentials suffice once the owner grants scopes. No new secret is needed here.
- Manoj: document today-only consumer board use and ON_CALL callback policy, distinct from his broader
  dated endpoint contract; owner write validation remains authoritative.
- Knowledge provider: authoritative API/host/auth and real outcome verification remain external;
  scheduling does not depend on that service.
- Gateway/voice: after an approved deployment, rerun registration, manually compare every outputSchema
  through the virtual server with make schema, refresh voice cache, check trusted-header isolation and
  run General Medicine/Gynaecology today/future plus Dr. Shreyas WORKING_HOURS probes.
- Real in-region tool latency and end-to-end first useful audio are unmeasured by this change.
  Callback-summary detail quality is not enforced locally; the voice team must test that behavior.
- Rollback must coordinate MCP image and gateway/voice schema. Do not mix the two breaking schemas.
  Azure cleanup remains a separately authorized, ownership-verified retirement task.

Ready for review/merge decision after review; not authorized to merge or deploy. No statement here
claims external service, live gateway or voice production acceptance.
