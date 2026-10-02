# Opus correction implementation plan — 3 October 2026

Goal: fix A1–A10 (excluding the explicitly deferred date change), B1 replayable proof, and the concrete LiveKit mechanisms requested in the fix brief. Baseline aa11591. User authorized execution directly. Use existing modules and HTTP/clock test boundaries; no new production module or dependency.

Delete: stale routing-clarification vocabulary, duplicate routing speech, fixture placeholder text, async-only composition wrapper, unreachable profile raise, unused per-path stub injection, stale secret reference, old gate instructions and developer-only model wording.

Change, in independently green commits of at most ten files:

1. A1/A5: knowledge contract/client and boundary tests. Red for the four optional-field payloads on both transfers, media type and metadata length; preserve valid decision with field-free log. Fast suite before commit.
2. A2/A10: prompt, pack, RoutingDecision, server instruction assertions; regenerate versioned snapshot/text. Red assertions for real next steps, clarification wording, departmentName mapping and developer sentence removal; date rule unchanged.
3. A3: knowledge result, pack, fixtures and tests; speech only in routing.speak on routing decisions, meaningful demo text. Regenerate artifacts; fast suite.
4. A4/A6/B1: strengthen concurrency, cancellation, privacy, forbidden-argument, instructions-drift and availability-result tests. Record actual reversible mutation patches plus red/restored-green output. Delete A7 leftovers with behavior preserved and dedicated structure evidence. Split test and cleanup commits if needed.
5. A8: settings pair validation; deploy secret removal; independently configured smoke expectation, type and mismatch checks. HTTP boundary and shell dry-run tests first. Each coherent step passes fast suite.
6. A9: correct current operating docs and idempotency key description. Use executable stale-text checks before/after; no historical evidence rewriting.
7. LIVEKIT: check official docs/source and supply raw-schema local booking wrapper mechanism, per-intent operation IDs, current-turn safety barrier, callback state/shutdown and escalation tools; document startup/duplicate behavior. Handover is specification, not a claimed deployed voice implementation.
8. Fresh unchanged reviewer agents; full scripts/test.sh; snapshot/instructions comparison, source stat and file-by-file correction report with actual red/green excerpts and all remaining owner work.

New files are limited to this plan, the correction report and reproducible evidence/patches required by the user. Do not edit reviewer agents, rewrite old commits, change date interpretation, push, merge, deploy, access secrets or mutate owner services. Preserve temp/ and Opus's original report.
