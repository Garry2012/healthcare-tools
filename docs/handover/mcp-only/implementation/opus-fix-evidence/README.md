# Correction-pass evidence and mutation replay

Red/green logs are actual captured output, including unsuccessful intermediate attempts. A `.patch`
introduces a deliberate defect; it is **never** an implementation patch. All runtime mutations were
restored before passing tests and commits. Static A7/A9/C audits prove document/structure requirements,
not runtime behaviour. File names identify findings in OPUS-ROUTING-REMOVAL-REVIEW.md.

## Replay without changing the shared workspace

Create a disposable checkout from the base below. Apply the selected patch with `git apply`, run its
listed pytest selector **from services/mcp**, verify exit 1 and inspect the intended assertion, reverse
with `git apply -R`, then verify exit 0. Use `uv sync --frozen` first. Keep patches/logs outside that
checkout while replaying. Never replay on the shared developer tree with another agent running.
`patch-replay.txt` records an independent `git apply --check` in isolated copies of the base files for
all 16 patches; it is an applicability check, not a new execution of the old tests.

| Patch | Replay base | pytest selector (prefix `uv run pytest`, suffix `-q --tb=short`) |
|---|---|---|
| A4-sequential-reads | f3ad09e | tests/test_booking.py -k cancelled_create |
| A6-cancellation | **7494629** | tests/test_knowledge.py -k external_cancellation |
| A6-privacy | 7494629 | tests/test_knowledge.py -k owner_failure |
| A6-artifact | 7494629 | tests/test_server.py -k instructions |
| A6-transcript-argument | 7494629 | tests/test_server.py -k without_trusted_fields |
| A6-matrix-choices | 0c6179d | tests/test_availability.py -k independent_of_knowledge |
| A6-matrix-doctors | 0c6179d | tests/test_availability.py -k independent_of_knowledge |
| A8-expectation | 96aa23d | tests/test_deploy.py -k profile_dependency_mismatch |
| B1-availability-knowledge | 0c6179d | tests/test_availability.py -k independent_of_knowledge |
| prior-01-empty-input | aa11591 | tests/test_knowledge.py -k empty_input |
| prior-02-routing-speech | aa11591 | tests/test_knowledge.py -k one_exchange |
| prior-03-deadline | aa11591 | tests/test_knowledge.py -k owner_failure |
| prior-04-smoke-envelope | aa11591 | tests/test_deploy.py -k unconfigured_smoke |
| prior-05-bench-write | aa11591 | tests/test_bench.py -k real_create |
| prior-06-stub-path | aa11591 | tests/test_stubs.py -k 'knowledge or routing or answers' |
| prior-07-date-validation | aa11591 | tests/test_availability.py -k independent_of_knowledge |

Check exact selectors against each log below before replay. The A6 test was initially committed in
8575979 with invalid deadline settings; use its correction 7494629 for execution. The earlier commit
IDs recorded as BASE in some logs precede unstaged test additions, so they are provenance, not replay
instructions. The table above points to restored source **including** those tests.

The seven `prior-*` diffs were reconstructed from reviewed commit aa11591 and the earlier mutation
scripts. Their original red runs remain in `../routing-removal-evidence/13-review-mutations-red.txt`
and `19-date-boundary-mutation.txt`. They were not rerun against the historical checkout in this pass.
The original green evidence is in that same evidence directory. Reconstructing diffs does not repair
the earlier task's unproven individual test edits or commits that did not build independently.

## Outputs

- A1-A5-red/green: malformed transfer metadata, content types, length boundaries.
- A2-A10-red/green: accurate instructions, routing enum, developer wording removal.
- A3: single speech location and meaningful fixture language.
- A4-sequential-reads: overlap mutation fails, cancellation test passes after restoration.
- A6-*: cancellation, privacy, schema argument blacklist, instruction artifact drift and matrix IDs.
- A7-cleanup: structural audit red/green and fast suite.
- A8-settings/release/expectation: partial config, secret-reference lifecycle and explicit smoke expectation.
- A9-docs: stale-document audit red/green and fast suite.
- B1-availability-knowledge: reintroduced hidden call reaches the exploding boundary (8 failed); restored green.
- C-livekit: handover audit red/green, including both reviewers' booking-to-callback correction.

Two process errors are retained visibly: the initial A6 cancellation test had invalid settings and
was committed before the failed suite was inspected; 7494629 corrects it without rewriting history.
A subsequent full run had an existing 300 ms timing test exceed its cap on the host; focused/full reruns
passed without changing that cap. Logs contain both attempts. Final report gives the acceptance status.
