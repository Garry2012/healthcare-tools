# Remediation instructions for Astra/Codex

From the independent review (`REVIEW.md`). You own the production fixes; the reviewer will rerun the
independent suite afterwards. Work in the order below: earlier tasks remove root causes that later
symptoms depend on.

## Ground rules (read first)

1. **Spec first.** Where a task says "decide", change `docs/frontdesk-api/openapi.yaml` (and
   IMPLEMENTATION.md / OPEN-QUESTIONS.md) first, then code. The contract test must stay green.
2. **Fix the authoritative code path, once.** Every business rule below has one home in
   `services/api` (named per task). Do not add a second implementation in the MCP adapter, the
   prompt, a router, or a "post-processing" step. The adapter stays a mapper (CLAUDE.md).
3. **No workaround patches.** Not acceptable: raising `maxSlotsPerSession`'s default or maximum as the
   fix for D-01; special-casing a doctor, a session shape or a date; catching a failing case and
   returning a hard-coded value; filtering in `services/mcp`; changing a review test's expectation.
4. **Do not weaken or delete the review tests** (`services/api/tests/review/**`,
   `services/mcp/tests/review/**`). If you believe one is wrong, say which spec sentence it
   contradicts and ask for a decision; do not edit it.
5. **Existing tests that encode a defect** must be corrected to the specified behaviour, not deleted:
   `tests/integration/test_sequence_windows.py:53-54` (pins D-01) and
   `tests/integration/test_identity_and_scopes.py:183-197` (named "reveals nothing" while the 409 is
   the disclosure; D-06). Say so in the commit message.
6. The working tree already holds uncommitted changes to `availability.py`, `schemas.py`,
   `config.py`, `openapi.yaml`, `IMPLEMENTATION.md`. Task 1 finishes that change; land it with its fix.

How to run (fresh throwaway PostgreSQL, existing + review suites):

```bash
scripts/review-suite.sh            # everything; non-zero exit while any defect remains
scripts/review-suite.sh review     # only the review suites
# one file, against a DB you already have (TEST_DATABASE_URL / TEST_DATABASE_OWNER_URL):
cd services/api && uv run pytest tests/review/rest/test_capacity_and_slots.py -q
```

---

## Task 1 — D-04: capacity precision is validated for every explicit capacity, and a capacity increase never impacts bookings

- **Authoritative paths:** `services/api/src/frontdesk_api/schemas.py::session_problems` (rule exists
  for templates, `:273-279`); `services/schedule_exceptions.py::_validate_exception` (`:74-96`, rule
  missing); `domain/availability.py::compute_sessions` (`precision_supported`, `:333`, `:371`, `:403`);
  `services/impact.py::apply` (`gone`, `:103`).
- **Required behaviour:**
  - One precision rule, defined once and used by templates, `CAPACITY_CHANGE.newCapacity`,
    `EXTRA_SESSION.newCapacity` and `rollout validate`: an explicit SEQUENCE capacity that needs an
    interval below one minute is `400 VALIDATION_FAILED` with the field (`newCapacity`).
  - A session that cannot be represented only because of inherited/default/legacy data is not
    offered, but that must not read as a resource policy (`NOT_OFFERED` means "never offer this
    resource") and must never move existing bookings: `impact.apply` moves bookings only when a
    session is removed, its hours shrink, or its capacity is *reduced* below a booked position.
- **Regression tests that must pass:**
  `tests/review/rest/test_capacity_and_slots.py::test_raising_capacity_never_cancels_existing_bookings`,
  `::test_explicit_extra_session_capacity_is_either_refused_or_offered`; plus the existing
  `tests/unit/test_sequence_capacity_validation.py` and `tests/integration/test_sequence_windows.py::test_staff_template_rejects_sub_minute_sequence_capacity`.
- **Verify:** `CAPACITY_CHANGE newCapacity=150` on a 2-hour session → 400 and no row changed;
  `newCapacity=24` on a FIXED 12 session with bookings → 201, bookings still `BOOKED`, no notification.

## Task 2 — D-01: the agent-facing answer never drops a bookable slot or resource silently

This is the calibration defect and the most important one. It is a **contract + projection** defect.

- **Decide first (A-01), in `openapi.yaml`:** what the agent receives when a session has more bookable
  slots, or a search more bookable resources, than a spoken answer needs. The contract must give
  (a) a **selection rule** tied to what the caller asked (dates, day part, and — if you add it —
  a preferred time), and (b) an **explicit, machine-readable statement of what was left out** (for
  example a count of further bookable slots per session and further resources, or the complete set),
  so that the agent can truthfully say "there are later places too" and can obtain them without
  guessing. Silent first-N is not an option. Keep `capacity.remaining` meaning what it means today.
- **Authoritative paths:** `services/api/src/frontdesk_api/services/views.py::session_instance`
  (`:39-45`, the `[:max_slots]` cut), `services/search.py::agent_search` (`:278` day-part filter at
  session level only, `:293` slot cap, `:320`/`:329` resource caps, `:356-357` "upcoming" cap),
  `schemas.py:421-422`; then `services/mcp/src/frontdesk_mcp/tools.py::find_availability` **only**
  to pass through whatever request fields the contract defines (no selection logic in the adapter),
  and `packs/*.json` / `prompt.py` wording if the agent must now act on the omission field.
- **Required behaviour (spec-independent invariants the tests check):**
  - With default request fields, every phone-bookable slot of a returned session is either returned
    or declared as omitted by the contract's field; the same for bookable resources of a category.
  - With a day part, returned slots lie inside that day part; the slots inside it are not displaced
    by earlier ones of the same session.
  - Booked or unreachable (same-day) positions never cause later bookable ones to be lost.
  - The MCP result equals the REST result (the adapter adds nothing and removes nothing).
- **Regression tests that must pass:**
  `tests/review/rest/test_availability_completeness.py` (all), `services/mcp/tests/review/test_mcp_rest_integration.py::test_mcp_offers_every_bookable_position_of_a_session`
  and `::test_find_availability_is_the_rest_answer_unchanged`.
  If the contract keeps a cap with an omission field, the reviewer will extend the completeness
  assertions to accept "returned ∪ declared-omitted = bookable"; tell the reviewer the field name.
- **Correct the pinned test:** `tests/integration/test_sequence_windows.py:53-54` must assert the
  specified set, not `[1, 2, 4]`.
- **Verify by hand:** demo rollout, Dr Garima next Monday afternoon (15:00–17:00, 4/h, 25 %): the
  agent must be able to offer 16:15–16:30; "evening" must yield positions from 16:00.

## Task 3 — D-02 and D-03: one slot model per session, and session facts derived from it

Both live in `domain/availability.py::compute_sessions` and share a cause: slot existence and
session-level facts are decided separately.

- **D-02 (TIMED):** the slot list is the time grid `start..end step slotMinutes` (IMPLEMENTATION §2.2).
  Capacity (FIXED / PER_HOUR / DEFAULT) limits how many may be held, not which times exist. Decide the
  walk-in reserve for TIMED (A-02; today S12 withholds the last `reserve` times) and write it in the
  spec. When `booked == total − reserve`, remaining grid times are unavailable (`FULL`).
  Path: `availability.py:388-400` (`for i in range(offered)`), `_capacity` (`:277-299`).
- **D-03 (same day):** compute slots (including the same-day reachability rule S8) first, then derive
  `remaining`, `bookable` and `notBookableReason` from those slots and the board. `bookable` is true
  only if at least one slot is available; `FULL` only when bookings (or the desk's FULL) used the
  capacity. Decide what an empty session whose remaining positions have all closed is called (A-04)
  and add that reason to the contract if new. Remove the `or "FULL"` fallback in
  `services/search.py:301`: search must report the engine's reason, never invent one.
- **Regression tests that must pass:** `tests/review/unit/test_engine_properties.py` (all 7),
  `tests/review/rest/test_capacity_and_slots.py::test_timed_session_offers_times_across_the_whole_session`,
  `::test_timed_clinic_with_spare_capacity_is_bookable_later_in_the_day`,
  `::test_same_day_session_level_facts_agree_with_its_slots`,
  `::test_same_day_search_never_reports_full_for_an_empty_session`; existing
  `tests/unit/test_availability_engine.py` (update only cases whose expectation contradicts §2.2, and
  name them in the commit).
- **Watch:** `services/impact.py::_free_position` and `booking_views.slot_in` rely on the slot list;
  keep TIMED slot ids (`slot_<session>_HHMM`) stable so existing bookings keep their slot.

## Task 4 — D-05: the booking horizon is a property of a slot, applied everywhere a slot is offered or taken

- **Path:** today only `services/bookings.py:120` (`book`). Put the rule where slot eligibility is
  decided for the agent channel (the engine inputs or `_check_slot`), so `agent_search`, `book`,
  `reschedule` and `deskCreateBooking` agree. Decide (A-06) whether search shows such sessions as
  unbookable with a reason, and document it.
- **Tests:** `tests/review/rest/test_capacity_and_slots.py::test_search_never_offers_a_slot_that_booking_refuses`,
  `::test_reschedule_applies_the_same_horizon_as_booking`, `tests/review/rest/test_contract_rules.py::test_booking_horizon_boundary`.

## Task 5 — D-07: one certainty function, with the dataConfirmed cap applied last

- **Path:** `services/booking_views.py::_certainty` (`:67-70`) bypasses the cap applied in
  `availability.py:336-340`. Define the certainty rule once (domain), used by session views and
  booking views, with the order: booking/desk confirmation → session certainty → cap by
  `dataConfirmed`. Record the precedence (A-05) in the contract.
- **Tests:** `tests/review/rest/test_booking_lifecycle.py::test_unsigned_resource_data_caps_every_certainty_at_expected`,
  `tests/review/unit/test_engine_properties.py::test_unsigned_data_never_reaches_confirmed`.

## Task 6 — D-06: duplicate detection must not disclose a patient's booking to a stranger

- **Decide (A-07) with the product/privacy owner**, then implement in `services/bookings.py::book`
  (`:136-145`). The observable answer to a caller who is not the booking's number must be the same
  whether or not the named patient already holds a booking in that session. Update OPEN-QUESTIONS S9
  and correct `tests/integration/test_identity_and_scopes.py:183-197`.
- **Test:** `tests/review/rest/test_booking_lifecycle.py::test_a_stranger_cannot_learn_that_a_named_person_has_a_booking`.

## Task 7 — D-08: identity failures are indistinguishable in headers too

- **Path:** `app.py:104-105` (`Server-Timing` with the query count on every response) and the
  reschedule lock order (`services/bookings.py:345-346`). Either do not expose database detail on
  `/agent/*` responses, or make the identity-failure paths uniform. Do not add artificial queries.
- **Test:** `tests/review/rest/test_booking_lifecycle.py::test_neutral_not_found_does_not_leak_through_response_headers`.

## Task 8 — risks to schedule (not blocking the defects above)

- **R-01 (production blocker for lookup/cancel/reschedule):** signed call context verified by the API
  (TARGET.md roadmap item 1). Until then, document that anyone with a gateway token can assert any
  caller number.
- **R-02:** require one MCP session per phone call in `docs/handover/LIVEKIT.md`/`CONTEXTFORGE.md` and
  verify against a live ContextForge.
- **R-03:** record the provider id in the database at `rollout apply` and refuse readiness on
  mismatch; then remove the `xfail` from `tests/review/db/test_transactions.py::test_a_deployment_refuses_another_providers_database`
  (the reviewer will do this on verification).
- **R-04:** make `ENV` default to production or required, in both services.
- **Observation:** map a refused database connection on writes/lookups to `503 SERVICE_UNAVAILABLE`
  with `Retry-After` in `app.py`, as search already treats `OSError`.

## Definition of done (what the reviewer will check)

1. `scripts/review-suite.sh` exits 0: existing suites green, every review test green, the two
   `xfail(strict=True)` tests still xfail unless their decision was taken (then they must pass and
   the marker is removed by the reviewer).
2. `openapi.yaml`, IMPLEMENTATION.md and OPEN-QUESTIONS.md record the decisions A-01…A-07 taken.
3. No new logic in `services/mcp` beyond passing through contract fields.
4. `git diff` shows no change under `services/*/tests/review/`.
