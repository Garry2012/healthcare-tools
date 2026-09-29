# Test results — independent review, 2026-09-28

## 1. Environment

| Item | Value |
|---|---|
| Machine | macOS 26.6 (Darwin 25.6, arm64), Docker available |
| Code under test | `32ef56b` + the working tree's 16 uncommitted modifications and 5 untracked files (present before the review; see `REVIEW.md` §0) |
| Python / uv | 3.13.13 / uv 0.11.21 |
| Key libraries | FastAPI 0.141.1, SQLAlchemy 2.0.54, asyncpg 0.31.0, fastmcp 2.14.7, hypothesis 6.168.1 (pinned as an API dev dependency by this review) |
| Database | PostgreSQL 16.15 (`postgres:16-alpine`), throwaway container on tmpfs, `127.0.0.1:55499`, owner role (migrations) + DML-only runtime role created by `deploy/postgres/init/01-roles.sh`. Never a Supabase or dev database; the review fixtures refuse any non-localhost URL. |
| Clock | API REST/unit review tests: facility time fixed at Wed 2026-09-23 10:00 Asia/Kolkata, moved per test through the `schedule.now_in` boundary. MCP review tests: real clock (the API runs as a separate process). |
| Rollout | `rollouts/demo-hospital` (domain `healthcare`, languages en,kn,hi) |

## 2. Commands executed

```bash
# Full run on a fresh container (creates, migrates, runs, removes): executed twice (runs 2 and 3)
scripts/review-suite.sh all

# Which runs, in order (see the script):
cd services/api && uv run pytest tests/unit tests/contract/test_openapi_matches_spec.py tests/integration -q -p no:cacheprovider
cd services/api && uv run pytest tests/review -q -p no:cacheprovider -rfEx
cd services/mcp && uv run pytest tests -q -p no:cacheprovider -m "not e2e" --ignore=tests/review
cd services/mcp && MCP_E2E_API_URL=http://127.0.0.1:18099/api/v1 MCP_E2E_API_TOKEN=… uv run pytest tests/test_e2e.py -q
cd services/mcp && uv run pytest tests/review -q -p no:cacheprovider -rfEx
```

Logs of the recorded runs are in the workspace's `.context/review/review-suite-run{2,3}.log` (not
committed). Runs 2 and 3 produced identical pass/fail/xfail sets.

## 3. Results

| Suite | Passed | Failed | xfailed | Skipped |
|---|---|---|---|---|
| API existing: unit + contract + integration | 558 | 0 | 0 | 0 |
| API review: `tests/review` (unit, db, rest, e2e) | 122 | **26** | 2 | 0 |
| MCP existing: unit (`-m "not e2e"`) | 35 | 0 | 0 | 5 deselected (e2e) |
| MCP existing: e2e against a real API process | 5 | 0 | 0 | 0 |
| MCP review: `tests/review` (MCP → REST → PostgreSQL) | 10 | **1** | 0 | 0 |

`scripts/review-suite.sh` exit status: **1** (review suites fail, as expected while the defects exist).

Other entry points, checked after adding the review suite:
- `make test-fast`: unchanged and green (API 413 passed; MCP 35 passed, 16 deselected = 5 existing
  e2e + 11 review, all marked `e2e`). Ruff and `lint-imports` (9 contracts kept) pass.
- Without `TEST_DATABASE_URL`: `tests/review` gives 5 passed, 2 failed (engine properties), 143
  skipped at fixture time; the MCP review module skips (11).
- `scripts/test.sh` (CI) was **not run** by the reviewer (it uses the shared compose test database).
  From reading it: its API step lists `tests/unit tests/contract/… tests/integration` explicitly, so
  the API review tests do not run in CI; its MCP step runs `pytest tests` with the database exported,
  so the MCP review module **will run in CI and fail on D-01** until Task 2 is done. Wiring
  `tests/review` into the API step is a CI-policy decision left to the owner.

## 4. Failing tests, by defect (all reproducible with the commands above)

| Defect | Failing tests | Evidence (assertion output, run 2) |
|---|---|---|
| D-01 silent truncation | `rest/test_availability_completeness.py::test_agent_search_returns_every_bookable_position` [7 of 9 shapes; the 2 shapes with ≤ 3 positions pass], `::test_booked_early_positions_do_not_hide_later_ones`, `::test_day_part_offers_slots_inside_the_part_asked_for`, `::test_same_day_offers_every_reachable_position`, `::test_category_search_represents_every_bookable_doctor_of_the_category`; `mcp/tests/review/test_mcp_rest_integration.py::test_mcp_offers_every_bookable_position_of_a_session` | "3 of 6 bookable positions silently omitted from the agent response (remaining=6); last offered window ('15:30', '15:45') vs session end 17:00"; "33 of 36 … ('16:10', '16:15') vs session end 19:00"; "asked for EVENING (16:00-23:00); offered windows outside it: [('15:00','15:15'), ('15:15','15:30'), ('15:30','15:45')]"; "2 of 5 bookable dermatologists silently left out"; MCP: "ses_res_garima_2026-10-05_1: 6 of 9 bookable positions never reach the model" |
| D-02 TIMED grid | `rest/test_capacity_and_slots.py::test_timed_session_offers_times_across_the_whole_session` [3], `::test_timed_clinic_with_spare_capacity_is_bookable_later_in_the_day`; `unit/test_engine_properties.py::test_timed_slots_cover_the_session_grid` | "offered ('10:00','10:15')..('11:15','11:30'), session runs 10:00-13:00"; "('NONE_AVAILABLE', ['FULL'])" with nothing booked; Hypothesis minimal example 07:00–07:20, 10-min slots, FIXED 1: "total=1 grid=2" |
| D-03 same-day facts | `rest/test_capacity_and_slots.py::test_same_day_session_level_facts_agree_with_its_slots`, `::test_same_day_search_never_reports_full_for_an_empty_session`; `unit/test_engine_properties.py::test_same_day_bookable_remaining_and_slots_agree` | "bookable=True remaining=0 available slots=0"; "nobody is booked, yet the agent is told ['FULL']"; Hypothesis: "at 06:15: bookable=True reason=None remaining=0 available=0" |
| D-04 capacity precision | `rest/test_capacity_and_slots.py::test_raising_capacity_never_cancels_existing_bookings`, `::test_explicit_extra_session_capacity_is_either_refused_or_offered` | "capacity 12 -> 150 (HTTP 201) changed bookings: BOOKED -> NEEDS_RESCHEDULE"; "201 Created, yet the extra session is notBookableReason=NOT_OFFERED with 0 slots" |
| D-05 horizon | `rest/test_capacity_and_slots.py::test_search_never_offers_a_slot_that_booking_refuses`, `::test_reschedule_applies_the_same_horizon_as_booking` | "search offered slot_…_2027-04-11_1_01 as available (outcome FOUND); booking it -> 400 Bookings open 180 days ahead."; "BOOK of that slot is 400, RESCHEDULE to it is 200" |
| D-06 duplicate disclosure | `rest/test_booking_lifecycle.py::test_a_stranger_cannot_learn_that_a_named_person_has_a_booking` | "{'has booking': (409, 'This customer already has a booking in this session.'), 'no booking': (201, None)}" |
| D-07 certainty cap | `rest/test_booking_lifecycle.py::test_unsigned_resource_data_caps_every_certainty_at_expected` | "desk confirmation of a booking on an unsigned resource reaches the agent as CONFIRMED" |
| D-08 header side channel | `rest/test_booking_lifecycle.py::test_neutral_not_found_does_not_leak_through_response_headers` | identical 404 bodies; `Server-Timing` "5 queries" vs "6 queries" |

Expected failures (`xfail(strict=True)`: they fail today by design and turn red if the behaviour
changes without the decision being recorded):
- `db/test_transactions.py::test_a_deployment_refuses_another_providers_database` — R-03.
- `rest/test_schedule_changes.py::test_capacity_increase_does_not_silently_move_a_booked_window_earlier` — A-03.

## 5. What passed and is therefore evidence of correct behaviour

See `REVIEW.md` §3 for the list. Notable: 10-way concurrent booking of one slot (one winner, DB row
count 1); a second transaction provably blocked on the first's uncommitted insert; 6 concurrent
retries with one key → one row; byte-identical neutral 404 bodies across four causes; exact
notification counts under overlapping exceptions; a seeded 60-step randomised day in which
published availability equalled the booking ledger after every step (≥ 3 successful books, cancels,
moves and replays); migrations upgrade/downgrade/upgrade on an empty database; MCP write retried
exactly once with the same Idempotency-Key against a hanging upstream.

## 6. Test-environment limitations

- No live IBM ContextForge, LiveKit agent or Supabase pooler: gateway header behaviour (R-01, R-02)
  is from code reading of `mcp-gateway/paramaribo`, not from a running gateway.
- REST tests use `httpx.ASGITransport` in one event loop; concurrency is real at the database
  (separate pooled connections) but not across processes or replicas (one test uses two app
  instances on one database for cache freshness).
- MCP review tests use the real clock and the demo seed dated from the run day; they avoid "today".
- Only Asia/Kolkata (no DST) is exercised; latency budgets were not measured.
- Property tests are derandomized for reproducibility (300 examples per property), not exhaustive.
- Fake upstreams are used only for the adapter's transport-failure tests (closed port, a peer that
  never answers, a peer that answers 500/503/429); every other MCP test reaches the real API and DB.

## 7. Files added or changed by the review (no production code)

| File | Purpose |
|---|---|
| `services/api/tests/review/{__init__,conftest,oracle}.py` | fixtures (throwaway DB, clock boundary, staff builders), contract oracle |
| `services/api/tests/review/unit/test_engine_properties.py` | property-based engine invariants |
| `services/api/tests/review/db/test_transactions.py` | forced-interleaving race, index without the app, migrations, clean start, provider binding (xfail) |
| `services/api/tests/review/rest/test_availability_completeness.py` | D-01 and the contract formulas |
| `services/api/tests/review/rest/test_capacity_and_slots.py` | D-02…D-05, arrive-by |
| `services/api/tests/review/rest/test_booking_lifecycle.py` | idempotency, races, reschedule, identity, disclosure, certainty, fees |
| `services/api/tests/review/rest/test_schedule_changes.py` | precedence, unbookable states, board, notifications |
| `services/api/tests/review/rest/test_resolution_isolation_failure.py` | red flags, multilingual, knowledge, scopes, DB failure, timezone |
| `services/api/tests/review/rest/test_contract_rules.py` | shallowly tested RULEs from TEST-AUDIT §C |
| `services/api/tests/review/e2e/test_ledger_consistency.py` | seeded randomised ledger |
| `services/mcp/tests/review/{__init__,test_mcp_rest_integration}.py` | MCP → REST → PostgreSQL |
| `scripts/review-suite.sh` | reproducible runner on its own container |
| `services/api/pyproject.toml`, `services/api/uv.lock` | `hypothesis==6.168.1` in the dev group (already present transitively via schemathesis) |
| `docs/review/*.md` | these reports |
