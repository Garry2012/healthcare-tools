# Opus review: M-1 correction and L-1 note (booking write budget)

Review only, 14 October 2026. Not committed. Nothing fixed, committed, pushed, merged or deployed.

- **Reviewed:** `f8618825b369a9bc3f21e86763a24b8aefc38663..dff06f2313d5e4245999e9a1d54259fafc4accf2`
  ("Read local operation budgets from rollout.env only"), branch `Garry2012/booking-write-budget`.
- **State verified first:** HEAD `dff06f2`; no tracked changes; only untracked file is my earlier
  `OPUS-BOOKING-WRITE-BUDGET-REVIEW.md` (unmodified since I wrote it: still my text and verdict, file time 16:34,
  before the 19:47–19:50 correction run). Six commits since `e6b9193`. Plan SHA-256 unchanged
  (`fc036795…6575`, per `M1-plan-hash.txt`).

## Verdict: APPROVED FOR MERGE REVIEW

M-1 is resolved and L-1 is addressed. No new findings that need action. **Deployment readiness is not established**:
the O-1 benchmark decision, canary measurement, the voice team's LiveKit timeout confirmation (D5), rollback-target
recording, merge and deployment approvals all remain open.

## 1. M-1: resolved

| Requirement | Evidence | Result |
|---|---|---|
| Only four files changed | `git diff --name-only f861882 HEAD`: `.env.example`, `deploy/docker-compose.yml`, `rollouts/demo-hospital/rollout.env`, `services/mcp/README.md` (4 insertions, 16 deletions) | ✓ |
| Compose's six overriding entries removed | `docker-compose.yml` diff removes exactly the six `READ_/WRITE_/SUMMARY_…` lines from the `mcp` `environment:` block (were lines 33–38); the service still loads `rollouts/${PROVIDER_ID:-demo-hospital}/rollout.env` through `env_file` (`docker-compose.yml:12`, merged at `:17`) | ✓ |
| Voice-budget settings and all other compose lines unchanged | diff touches only those six lines; `VOICE_RESPONSE_BUDGET_SECONDS`, `RESERVED_STAGE_SECONDS`, `GATEWAY_OVERHEAD_SECONDS`, `ACCEPTED_CALLER_VERIFICATION` and the rest are untouched | ✓ |
| `.env.example` no longer duplicates the six | six assignments deleted; three explanatory comments replaced by one line pointing to `rollouts/<id>/rollout.env` and `config.py` defaults; the three voice-budget lines kept | ✓ |
| README names `rollout.env` as the local source | `services/mcp/README.md:64` "Local compose reads the six settings from rollout.env." | ✓ |
| Budget values unchanged | `rollout.env` values still 0.30/0.30/3.0/1.0/8.0/8.0; only a comment line added | ✓ |
| No source, test, schema, plan, DECISIONS or other doc change | diff scope above | ✓ |
| Prior evidence and my review preserved | only new `M1-*` files and an appended section in `HAND-BACK-FINAL.md` changed after the correction run | ✓ |

**Precedence independently proven (not inferred from matching defaults).** I rendered each revision's compose file
against a probe rollout identical to `demo-hospital` except `WRITE_DEADLINE_SECONDS=2.5`, with `.env.example`
placeholders, in a temporary directory outside the worktree (`.context/opus-m1-review/precedence-probe.txt`):

| Revision | Rollout says | Shell exports | Rendered |
|---|---|---|---|
| `f861882` (before) | 2.5 | — | **3.0** (compose default overrode the rollout) |
| `f861882` (before) | 2.5 | 9.9 | **9.9** (a stray shell variable leaked in) |
| `dff06f2` (after) | 2.5 | — | **2.5** (rollout is the source) |
| `dff06f2` (after) | 2.5 | 9.9 | **2.5** (shell no longer overrides) |

So the before-state really overrode `rollout.env`, and the correction makes `rollout.env` the single local source.

## 2. L-1: addressed

`rollout.env:14` and `services/mcp/README.md:52`: "A write total below 1.0 s also needs a matching
WRITE_EXCHANGE_TIMEOUT_SECONDS; each cap must not exceed its total." Matches the `_exchange_caps` rule; no value changed.

## 3. New findings

None requiring action. Two notes:
- **Note:** a developer's existing local `.env` copied from the older example may still contain the six lines; Compose no
  longer references them, so they are inert (no effect, no failure).
- **Nit:** the new `.env.example` comment line is long (~150 characters); `.env.example` is not linted.

## 4. Commands

**Mine** (outputs in `write-budget/.context/opus-m1-review/`):

| Command | Result |
|---|---|
| `git rev-parse HEAD`, `git status --porcelain`, `git log --oneline f861882..HEAD`, `git diff --stat/--name-only f861882 HEAD`, full diff | as expected (above) |
| Compose precedence probe, attempt 1 | **invalid, my own harness error**: zsh read `$rev:r…` as a history modifier, so the probe rollout copies were empty. No product failure. Preserved as `precedence-probe-attempt1-invalid.txt` |
| Compose precedence probe, attempt 2 (corrected quoting, run once) | exit 0; results in the table above (`precedence-probe.txt`) |

I did not rerun `make test-fast`; the change touches no Python, test or schema file.

**Inspected (Astra's evidence, not rerun):**
`M1-diff.txt` (four files); `M1-compose-config.txt` (placeholders only; budgets 0.30/0.30/3.0/1.0/8.0/8.0);
`M1-sources.txt` (six assignments only in `rollout.env`, plus the L-1 comment); `M1-test-fast.txt` (Ruff "All checks
passed!", 1295 passed, 13 deselected, exit 0); `M1-commits.txt` (six commits); `M1-status.txt` (only my review
untracked); `M1-plan-hash.txt` (unchanged); `HAND-BACK-FINAL.md` "M-1 correction" section.

## 5. Gates still open

- **O-1:** paired 200-sample stub bench, or Garima's explicit acceptance of the single-sample p99 interpretation.
- **D5:** voice team confirms LiveKit `timeout` and `client_session_timeout_seconds`.
- Before deployment: record the running revision's image digest and environment (rollback target).
- Canary measurement of write timing after deployment; merge and deployment approvals.

## Summary for Garima

Astra's fix is correct and contained: four files, no code, values unchanged. I proved it by trying both versions: before
the fix, the local Docker setup ignored a changed `rollout.env` (and even picked up stray shell values); after the fix,
`rollout.env` is the one place the six budgets come from. The extra note about write totals below one second is in
place. The branch is ready for your merge review. Still open before any deployment: your call on the benchmark tail
(accept or run one larger benchmark), the voice team's LiveKit timeout confirmation, and recording the rollback image.
