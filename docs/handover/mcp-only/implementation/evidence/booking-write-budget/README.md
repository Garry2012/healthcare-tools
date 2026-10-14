# Booking write budget: evidence record

Reviews and reports for the independent booking write budget (plan:
`../../BOOKING-WRITE-BUDGET-PLAN.md`, revision 7; merged as PR #23, `42f9873`; deployed 14 October 2026 to canary
revision `--0000007`).

| File | What it is |
|---|---|
| `UNCERTAIN-WRITE-20261012-REPORT.md` | Investigation of the 12 October uncertain booking (call `9f201655…`) and the 13 October budget experiment |
| `OPUS-BOOKING-WRITE-BUDGET-PARTIAL-REVIEW.md` | Opus review of commits 1–2 and the draft commit-3 tests |
| `SOL-BOOKING-WRITE-BUDGET-REVIEW.md` | SOL independent review |
| `OPUS-BOOKING-WRITE-BUDGET-REVIEW.md` | Opus final review (finding M-1) |
| `OPUS-BOOKING-WRITE-BUDGET-M1-REVIEW.md` | Opus review of the M-1 correction |
| `CANARY-0000007-WRITE-CHECK.md` | Synthetic CREATE/RESCHEDULE/CANCEL check on the deployed canary |

**Raw evidence is not in the repository.** The files these documents cite by local path (log extracts, test and
benchmark outputs, scripts, hand-backs, `.context/…` paths in the reviews) were kept in the des-moines workspace:
`.context/uncertain-write-20261012/`, `.context/canary-42f9873/`, `.context/deploy/`, and, for the removed
`write-budget` worktree, `.context/archive/write-budget/context/`. They contain no patient data or secrets but are
local working files, not published records.
