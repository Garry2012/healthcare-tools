# Canary --0000007 (image 42f9873) synthetic write check, 14 Oct 2026 09:53–09:55 UTC

Approved by Garima. Synthetic patient only; doctor a76ce94f…; no summaries created; all appointments cancelled.
Scripts: create_cancel_runs.py (4 runs), reschedule_run.py (1 journey). Client output: runs.txt.
Server tool_result durationMs (server-logs.tsv); no ops_* warnings in the window.

| Tool call | Outcome | durationMs (server) |
|---|---|---|
| availability (probe, 15 Oct) | AVAILABILITY | 199 |
| CREATE ×4 (15 Oct 14:00) | NOTED ×4 | 286, 240, 210, 246 |
| CANCEL ×4 | CANCELLED ×4 | 79, 62, 63, 65 |
| availability 15 Oct / 16 Oct (reschedule journey) | AVAILABILITY | 96, 118 |
| CREATE (15 Oct 14:00) | NOTED | 233 |
| RESCHEDULE → 16 Oct 14:00 | NOTED (status CHANGED) | 244 |
| CANCEL | CANCELLED | 73 |

Writes take 0.21–0.29 s server-side against a 3.0 s total: under the old 0.30 s budget they sat at the cliff edge,
which explains the intermittent UNCERTAIN results. No write warning, no retry.
