# Test audit: the existing suites, and a requirements-to-tests matrix

Audited on disk on 2026-09-28 (working tree at `32ef56b` with uncommitted changes). Paths are
relative to `services/api/` unless they start with `services/mcp/`. Every claim cites file:line.
Existing suites all pass (558 API, 35 MCP unit, 5 MCP e2e; `TEST-RESULTS.md`), yet they did not detect
D-01…D-08 of `REVIEW.md`. This file explains why.

## 1. How the existing suites run

| Suite | Layer | Real DB | Runs in |
|---|---|---|---|
| `tests/unit/*` (408 collected cases) | domain + helpers | no | `make test-fast`, CI |
| `tests/contract/test_openapi_matches_spec.py` | generated OpenAPI vs spec | no | `make test-fast`, CI |
| `tests/integration/*` (145 collected cases) | REST in process (`httpx.ASGITransport`) over PostgreSQL 16 | yes | `scripts/test.sh`, CI; **skipped at import without DB env** (`tests/integration/conftest.py:28-29`) |
| `tests/contract/test_schemathesis.py` | schema fuzzing of a running API | yes | `scripts/test.sh`; `status_code_conformance`, `positive_data_acceptance`, `negative_data_rejection` switched off (`:5-9`) |
| `services/mcp/tests/test_tools_unit.py` (23) | adapter with `httpx.MockTransport` | no | `make test-fast` |
| `services/mcp/tests/test_e2e.py` (5) | adapter process → real API process → PostgreSQL | yes | only `scripts/test.sh` (marked `e2e`, deselected by `make test-fast`, `Makefile:33`) |

The integration conftest replaces `schedule.now_in` for every test (`tests/integration/conftest.py:64-71`),
a legitimate time boundary; it also means the production `now_in` (`services/schedule.py:196-197`) is
never executed by any API test.

## 2. Weaknesses, by the brief's categories

| Category | Evidence | What slips through |
|---|---|---|
| Requirement with no test | `maxSlotsPerSession`/`maxResources` have 0 hits in tests; `alternatives[]`, `resourceToday`, `requestTimingConfirmation`/`followUp` never asserted (see §4) | D-01; regressions in alternatives and same-day lookup |
| Test pins a defect | `tests/integration/test_sequence_windows.py:53-54`: search must return exactly positions `[1, 2, 4]` out of `rate*3 − 1` free positions | D-01 is locked in as expected behaviour |
| Only status codes | `test_schedule_concurrency.py:49` (`[201,409,409,409]`), `test_input_bounds.py:50,64,73,79,82,89,101,108`, `test_board.py:98,103`, `test_staff_robustness.py:31,45,55`, `test_knowledge.py:75` | wrong error code/body, rows written anyway |
| Only schemas | `contract/test_openapi_matches_spec.py:80-103` compares enums, `required` and property presence, spec → generated only; types, defaults, min/max and extra generated properties are not compared | a default changed from 3 to 5; a staff-only field added to an agent schema |
| Duplicates the implementation | `services/mcp/tests/test_tools_unit.py:186` computes the expected key with `tools.idempotency_key`; `:71` expected instructions with `prompt.instructions`; `tests/unit/test_availability_engine.py:357` asserts `remaining == len(available)` (self-consistency, not the formula) | a wrong key formula or prompt; wrong `remaining` that equals a wrong slot list |
| Mocks the code under test | `services/mcp/tests/test_tools_unit.py:303,328` monkeypatch `tools.get_http_headers` (the header-injection source); `tests/integration/test_hardening.py:32-33` replaces `search.agent_search` to test COULD_NOT_CHECK | header injection broken by a FastMCP change; a real DB failure path |
| Happy path only | `unit/test_config.py`, `unit/test_logging.py`, `integration/test_seed_guard.py`; every template test starts today (`test_templates.py:25-27,69,95`) | "bookings before effectiveFrom are untouched" |
| First item only | `unit/test_availability_engine.py:63,89`; `integration/test_exceptions.py:44-46` (facts on `pending[0]`), `:59`; `test_board.py:73,117`; `test_booking.py:228`; `test_identity_and_scopes.py:133,141`; `test_search_dead_ends.py:21,80`; `test_sequence_windows.py:53` (`sessions[0]`) | wrong facts on later notifications; a second session of the day dropped |
| Passes when data is silently omitted | `test_booking.py:32` (`currentSlots` truthy), `test_e2e.py:186-187`; `test_languages.py:21-22,35` (set of dates only); `unit/test_knowledge.py:41` (`>=`); `test_exceptions.py:304` (`in`, duplicates pass); `test_search_dead_ends.py:22` (`>` instead of the exact next date) | D-01; duplicate notifications; truncated conflict alternatives |
| Integration without a real DB | none among `tests/integration` (all use PostgreSQL); MCP unit tests never reach the REST service | — |
| MCP tests that never call REST | all of `services/mcp/tests/test_tools_unit.py` (MockTransport at `:41` and handlers `:126…:298`) except `test_api_down…` (closed port, `:110`); `test_deploy_smoke.py` (AsyncMock) | REST/MCP contract drift; truncation across MCP |
| Concurrency that is sequential in practice | `services/mcp/tests/test_e2e.py:182-183` "race" awaits the two bookings one after another. The API races (`test_booking.py:25`, `test_schedule_concurrency.py`) are genuinely concurrent (per-request sessions, pool 10+10) | — |
| Cannot fail meaningfully | `unit/test_identity.py:67-71` compares three calls of `not_found()` with no arguments; `test_schedule_concurrency.py:34-40` passes if every booking loses (`all()` over an empty set); `test_identity_and_scopes.py:210-216` passes on an empty result list; `test_hardening.py:16-18` checks a config flag, not a log line | leaks and races the tests claim to guard |
| Misleading / skipped | `test_identity_and_scopes.py:183` is named "a duplicate booking reveals nothing to another caller" but asserts a 409 that is itself the disclosure (D-06); `unit/test_logging.py:1` docstring "never carry the customer" without such an assertion; module-level skips (`integration/conftest.py:28-29`, `contract/test_schemathesis.py:28`, `test_e2e.py:24-27`) are legitimate environment skips but mean `make test-fast` exercises no database, no running API and no MCP↔REST path | D-06; everything in D-01…D-05 under `make test-fast` |

Two further gaps with direct defect consequences:
- **Neutral 404 compared on the body only, and only for CANCEL** (`test_identity_and_scopes.py:15-29`).
  Headers are never compared (D-08); reschedule mismatches have no REST test.
- **The TIMED shape that exposes D-02 exists but is not asserted:** `test_templates.py:95-104` sets
  TIMED FIXED 12 on an 18-slot grid and checks only a notification. The engine test
  (`unit/test_availability_engine.py:285-300`) uses DEFAULT capacity equal to the grid.

## 3. Missing test layers (now added under `tests/review/`)

| Layer | Existing | Added |
|---|---|---|
| Independent oracle of the contract formulas | none (tests restate outputs or self-consistency) | `tests/review/oracle.py` (no production imports) |
| Property-based engine tests | none | `tests/review/unit/test_engine_properties.py` (7 properties, 300 derandomized examples each) |
| DB-level transaction tests with a forced interleaving | none | `tests/review/db/test_transactions.py` (blocking second writer, index without the app, migrations up/down/up, clean start) |
| Agent view vs staff view completeness | none | `tests/review/rest/test_availability_completeness.py` |
| Stored-row verification after REST calls | rare | `tests/review/rest/test_booking_lifecycle.py`, `test_schedule_changes.py`, `test_capacity_and_slots.py` |
| Randomised ledger consistency | none | `tests/review/e2e/test_ledger_consistency.py` (seeded 60-step day) |
| MCP → REST → DB with DB-side verification | e2e checks response fields only | `services/mcp/tests/review/test_mcp_rest_integration.py` |
| Transport failure through a real adapter process | MockTransport only | same file: closed port, hanging peer, 5xx/429 peers |

## 4. Requirements-to-tests traceability matrix

Legend: **E** = existing test (strength: ✓ adequate, ~ shallow, ✗ none); **R** = review test
(`tests/review/…`, `mcp/…` = `services/mcp/tests/review/…`); result **P** pass, **F** fail (defect), **X** xfail (risk/ambiguity).

| # | Requirement (source) | E | Review test(s) | R |
|---|---|---|---|---|
| 1 | Availability completeness: every bookable slot reaches the caller (brief; §2.2 slots) | ✗ (pinned wrong, `test_sequence_windows.py:54`) | `rest/test_availability_completeness.py::test_agent_search_returns_every_bookable_position[9]`, `…booked_early…`, `…day_part…`, `…same_day…`, `…category_search…`; `mcp/…::test_mcp_offers_every_bookable_position_of_a_session` | F (D-01) |
| 2 | Sequence positions and windows = boundary(n) (`Slot.expectedWindow`, §2.2) | ~ (`test_sequence_windows.py`) | `rest/…::test_staff_view_matches_the_contract_formulas[9]`; `unit/…::test_future_queue_matches_the_contract_exactly`, `…windows_are_adjacent…` | P |
| 3 | Fixed / per-hour / default capacity (`CapacitySpec`) | ~ | same as 2 (FIXED, PER_HOUR, DEFAULT shapes) | P |
| 4 | Walk-in reserve = ceil(total × % / 100), never offered (§2.2) | ~ | same as 2; `rest/…completeness` (reserve positions never offered) | P |
| 5 | Template and exception precedence, creation order (§2.2) | ~ (≤ 1 exception per session in engine tests) | `rest/test_schedule_changes.py::test_exceptions_apply_in_creation_order_over_the_template`, `…does_not_touch_the_next` | P |
| 6 | Extra, changed, cancelled, pending sessions | ~ | same; `…unbookable_session_exposes_no_bookable_slot_anywhere[cancelled]`; `rest/test_booking_lifecycle.py::test_pending_timing…`; `rest/test_capacity_and_slots.py::test_explicit_extra_session_capacity…` | P / F (D-04) |
| 7 | Live board arrived / late / left / full (`setBoard`) | ~ | `rest/test_schedule_changes.py::…unbookable…[left,ended,full]`, `…late_board_shifts_windows…`, `…board_is_for_today…`, `…board_facts_of_yesterday_expire`; `rest/test_contract_rules.py::test_same_day_lookup_embeds_the_resource_state_today` | P |
| 8 | Same-day vs future behaviour; session facts agree with slots (§2.2 bookable rule) | ✗ | `rest/test_capacity_and_slots.py::test_same_day_session_level_facts_agree…`, `…never_reports_full…`; `unit/…::test_same_day_bookable_remaining_and_slots_agree` | F (D-03) |
| 9 | Facility timezone and date boundaries (`openapi.yaml:168-169`) | ~ (call summaries only) | `rest/test_resolution_isolation_failure.py::test_relative_days_are_facility_days[3]`, `…board_accepts_the_facility_date…`, `…ended_yesterday…` | P |
| 10 | Booking cutoffs and arrive-by (`arriveBy`, horizon) | ~ (far values only) | `rest/test_capacity_and_slots.py::test_arrive_by_is_the_earlier…`, `…search_never_offers_a_slot_that_booking_refuses`, `…reschedule_applies_the_same_horizon…`; `rest/test_contract_rules.py::test_booking_horizon_boundary[180,181]` | P / F (D-05) |
| 11 | Deterministic slot ids re-derived and validated at booking (§2.1) | ~ | `rest/…::test_every_returned_slot_belongs_to_its_session…`; `…unbookable…` (409 on a stale id) | P |
| 12 | Concurrent booking of one slot (§2.5) | ✓ (genuine gather) | `rest/test_booking_lifecycle.py::test_concurrent_bookings_of_one_slot…`; `db/test_transactions.py::test_second_writer_blocks…`, `…live_slot_index_refuses…` | P |
| 13 | Idempotent retries (§2.5) | ~ (BOOK only, no row count) | `rest/test_booking_lifecycle.py::test_retry_with_same_key…`, `…different_request…`, `…concurrent_retries…`; `e2e/test_ledger_consistency.py`; `mcp/…::test_every_action…` | P |
| 14 | Atomic rescheduling (`agentRescheduleBooking`) | ~ (2 columns) | `rest/test_booking_lifecycle.py::test_failed_reschedule_leaves_both…`, `…successful_reschedule_releases…` | P |
| 15 | Cancellation identity checks | ✓ (cancel) | `rest/test_booking_lifecycle.py::test_every_identity_failure…`, `…reschedule_identity_failures…`, `…contact_phone_or_booked_from…` | P |
| 16 | Multiple patients on one number (`NAME_REQUIRED`) | ✓ | `rest/test_booking_lifecycle.py::test_two_customers_on_one_number…` | P |
| 17 | Different-number and withheld-number callers | ✓ | `rest/test_booking_lifecycle.py::test_different_number_and_withheld…` | P |
| 18 | Neutral not-found privacy | ~ (body, cancel) | `rest/test_booking_lifecycle.py::test_every_identity_failure…` (body+type), `…does_not_leak_through_response_headers`, `…a_stranger_cannot_learn…` | P / F (D-06, D-08) |
| 19 | Confirmation and fee certainty (`Money.confirmed`, dataConfirmed cap) | ~ (search fee only) | `rest/test_booking_lifecycle.py::test_unconfirmed_fee…`, `…confirmed_fee…`, `…unsigned_resource_data_caps…`; `unit/…::test_unsigned_data_never_reaches_confirmed` | P / F (D-07) |
| 20 | Session cancellation and impacted-customer notifications | ~ | `rest/test_schedule_changes.py::test_cancelled_session_notifies_each…`, `…shorter_queue_moves_people_forward…`, `…withdrawn_cancellation…`, `…template_change_impacts_only…`; `rest/test_contract_rules.py::test_switching_a_resource_to_not_offered…`; `rest/test_capacity_and_slots.py::test_raising_capacity_never_cancels…` | P / F (D-04) |
| 21 | Notification de-duplication | ✗ | `rest/test_schedule_changes.py::test_cancelled_session_notifies_each_impacted_customer_exactly_once`, `…identical_time_change_twice…` | P |
| 22 | Red flag before all other resolution, "nothing else" (`openapi.yaml:163-164`) | ~ (action only) | `rest/test_resolution_isolation_failure.py::test_red_flag_wins…[5]`, `…knowledge_question_transfers…` | P |
| 23 | Multilingual and ambiguous-name clarification | ✓ | `rest/test_resolution_isolation_failure.py::test_two_doctors_with_one_surname…`, `…name_in_any_script…[4]`, `…knowledge_answers_are_the_approved_text_verbatim[33]`, `…draft_answer…`; `rest/test_contract_rules.py::test_an_approved_answer_reaches_every_replica…` | P |
| 24 | REST/OpenAPI conformance | ~ (presence only) | `mcp/…::test_find_availability_is_the_rest_answer_unchanged`; `rest/test_contract_rules.py::test_slot_conflict_carries_every_current_bookable_slot…`, `…search_range_is_capped_at_31_days…[2]`, `…named_doctor_on_leave_gets…alternatives` | P |
| 25 | MCP tool schemas and header injection | ~ (monkeypatched headers) | `mcp/…::test_no_tool_lets_the_model_supply_identity…`, `…model_arguments_cannot_override_the_caller`, `…every_action_reaches…`; `rest/test_booking_lifecycle.py::test_identity_in_the_body_never_overrides…` | P |
| 26 | MCP action → REST routing | ~ (MockTransport) | `mcp/…::test_every_action_reaches_its_operation_with_header_identity`, `…write_without_call_context…` | P |
| 27 | Transport failure and timeout mapping (§2.5) | ~ (MockTransport) | `mcp/…::test_unreachable_api…`, `…hanging_api_times_out_and_a_write_is_retried_once…`, `…server_errors_and_rate_limits…[3]`; `rest/test_resolution_isolation_failure.py::test_database_down…[2]` | P |
| 28 | Prevention of silent response truncation | ✗ | as #1 | F (D-01) |
| 29 | Tenant / facility isolation | ~ (rollout refusal only) | `rest/test_resolution_isolation_failure.py::test_the_agent_credential_cannot_reach_staff_operations[5]`, `…staff_credential…`, `…no_credential…`; `db/test_transactions.py::test_a_deployment_refuses_another_providers_database` | P / X (R-03) |
| 30 | Migration, configuration and clean start | ~ (`test_ready.py`) | `db/test_transactions.py::test_migrations_build_a_clean_database_downgrade_and_rebuild`, `…clean_start_is_not_ready_until_migrated` | P |
| — | TIMED slots = start..end step slotMinutes (§2.2) | ✗ (capacity = grid only) | `rest/test_capacity_and_slots.py::test_timed_session_offers_times…[3]`, `…timed_clinic_with_spare_capacity…`; `unit/…::test_timed_slots_cover_the_session_grid` | F (D-02) |
| — | Booking counts agree with records; no two live bookings hold one slot | ~ | `e2e/test_ledger_consistency.py`; `unit/…::test_held_positions_are_unavailable_and_counted` | P |
| — | Capacity change moves booked windows (A-03) | ✗ | `rest/test_schedule_changes.py::test_capacity_increase_does_not_silently_move…` | X |

## 5. Specification rules still without a review test

Not covered here, and worth adding when the related decisions land: 24-hour idempotency-key expiry
(`services/idempotency.py:25`); desk-booking replay and horizon (`deskCreateBooking`); "anyone
available right now" presence ordering (`search.py:21`); gender preference with unknown gender on a
non-empty result; request-size (64 KiB) and nesting (32) boundaries; latency budgets.
