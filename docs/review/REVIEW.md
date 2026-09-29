# Independent review: front-desk API and MCP adapter

Reviewer: independent architect / QA (not the implementing agent). Date: 2026-09-28.
Companion files: `TEST-AUDIT.md` (existing tests), `ASTRA-FIX-INSTRUCTIONS.md` (remediation),
`TEST-RESULTS.md` (commands, environment, results).

## 0. Scope, baseline and method

- **Code reviewed:** the working tree of `/Users/garima/conductor/workspaces/healthcare-tools/des-moines`
  at `32ef56b` **plus 16 uncommitted modifications and 5 untracked files** that were already present
  (`git status`), including in-progress production changes to `domain/availability.py` (the
  sequence-window formula), `schemas.py` (a one-minute precision rule), `config.py`, `openapi.yaml`
  and `IMPLEMENTATION.md`. Findings apply to that state. No production file was changed by this review.
- **Authoritative references:** `docs/frontdesk-api/openapi.yaml` (normative) and
  `docs/frontdesk-api/IMPLEMENTATION.md` (design rationale, §2.2 algorithm), both read in full, plus
  `docs/architecture/TARGET.md` and `docs/handover/OPEN-QUESTIONS.md` (the implementer's recorded
  decisions, used only to tell a deliberate choice from an accident).
- **References not trusted:** the ContextForge gateway (`mcp-gateway/paramaribo`) and the earlier
  utility MCP (`utility-tools-v1/phoenix`) were read only to check integration assumptions.
- **Method:** traced every principal flow through router → service → engine → database; wrote an
  independent oracle of the contract formulas (`services/api/tests/review/oracle.py`, no production
  imports); drove the real service through its public boundaries (REST, MCP over streamable HTTP,
  PostgreSQL 16) and compared the results with the oracle and with the stored rows.
- **Result in one line:** the write path (slot uniqueness, idempotency, atomic reschedule, neutral
  not-found, notifications) is sound and survived adversarial tests; the **read path the caller hears
  is lossy**: the agent-facing availability projection silently drops bookable slots and doctors, and
  several session-level facts disagree with the slots they summarise.

Classification used below: **Confirmed defect** (reproduced by a failing test, contradicts the
contract or the implementer's own recorded rule), **Architectural risk** (no rule is broken today,
but the design allows a harmful outcome), **Specification ambiguity** (the contract is silent or
self-contradictory; a decision is needed), **Missing test**, **Test-infrastructure limitation**.

## 1. Architecture assessment

| Area | Assessment |
|---|---|
| Layering | Good. Business rules live in `services/api`; `services/mcp/src/frontdesk_mcp/tools.py` maps three tools onto Agent operations, injects headers, derives keys and wraps failures, with no domain rules. `import-linter` contracts enforce router → service → db and a pure `domain/`. |
| Availability engine | `domain/availability.py::compute_sessions` is a pure function of template ⊕ exceptions ⊕ board ⊕ held slots, as the spec requires. The formulas for totals, reserve and sequence windows match the contract exactly (300 property examples, 9 REST shapes). The defects are in *which slots exist* (TIMED) and in *session-level facts computed before slot reachability* (same day). |
| Agent projection | `services/search.py::agent_search` + `services/views.py::session_instance` turn complete engine output into the caller-facing answer with **unannounced caps** (3 slots per session, 3 resources, first-N selection that ignores the requested day part). This is the main design fault (D-01). |
| Booking / concurrency | Strong. Uniqueness is a partial unique index (`uq_bookings_live_slot`), booking is `INSERT … ON CONFLICT DO NOTHING`, reschedule is an UPDATE in a savepoint, and resource advisory locks order schedule changes against bookings. Verified with separate connections and a forced interleaving. |
| Idempotency | Key row inserted first in the same transaction; concurrent retries serialise on the primary key; replays are checked against the booking's current state. Verified, including six concurrent retries and a 60-step randomised ledger. |
| Identity / disclosure | Identity only from headers at the API; the MCP tool schemas expose no identity field and FastMCP rejects unknown arguments. Neutral 404 body is identical across four causes. Two leaks remain (D-06, D-08) and the headers themselves are unauthenticated end to end (R-01). |
| Failure handling | Search and knowledge return `COULD_NOT_CHECK` on database failure; the adapter maps transport errors, 5xx and 429 to `COULD_NOT_CHECK`/`COULD_NOT_RECORD`, retries a write once with the same key. Verified against a closed port, a hanging peer and 5xx/429 peers. |
| Deployment isolation | One deployment per hospital (TARGET.md A1). Nothing binds a database to its provider at run time (R-03). |

## 2. Confirmed defects (severity-ranked)

### D-01 — HIGH — The agent never hears most bookable slots or doctors; nothing says they were left out

*Root cause (one abstraction, several symptoms):* the caller-facing projection applies silent,
position-blind caps to complete engine output.

- `services/views.py:44` `chosen = chosen[:max_slots]` keeps the **first N available slots of a session**.
- `services/search.py:293` passes `max_slots=body.max_slots_per_session` (default 3, `schemas.py:422`,
  contract `openapi.yaml:1993`); `search.py:320` and `:329` cut results and alternatives to
  `maxResources` (default 3).
- `services/search.py:278` filters sessions by day part (`_overlaps`), but slots inside a kept session
  are never filtered or chosen by the requested time.
- `services/mcp/src/frontdesk_mcp/tools.py:214-221`: `find_availability` does not expose
  `maxSlotsPerSession`/`maxResources`, so through MCP the caps are always 3.
- The response carries no omission signal: `capacity.remaining` is a count, but the agent may only
  book slot ids it was given (`prompt.py` CORE_RULES: "Never invent ids … times"), so it cannot offer
  what it was not shown.

*Reproduction (REST, fixed clock Wed 2026-09-23 10:00 IST):* a doctor with one session 15:00–17:00,
4 per hour, 25 % walk-in reserve. Contract: total 8, reserve 2, **6 phone positions**, windows
15:00–15:15 … 16:15–16:30. `GET /availability` returns all 6. `POST /agent/availability-search` for
that doctor and date returns positions 1–3 only (last window 15:30–15:45) with `remaining: 6`.

| Shape (from `test_agent_search_returns_every_bookable_position`) | Bookable | Returned | Last returned window vs session end |
|---|---|---|---|
| 15:00–17:00, 4/h, 25 % (calibration) | 6 | 3 | 15:30–15:45 vs 17:00 |
| 10:00–13:00, 6/h, 20 % | 14 | 3 | 10:20–10:30 vs 13:00 |
| 08:00–12:00, 8/h, 10 % | 28 | 3 | 08:15–08:22 vs 12:00 |
| 16:00–19:00, 12/h | 36 | 3 | 16:10–16:15 vs 19:00 |
| 14:00–16:30, FIXED 10, 20 % | 8 | 3 | 14:30–14:45 vs 16:30 |
| 09:00–11:00, FIXED 16 (7.5 min) | 16 | 3 | 09:15–09:22 vs 11:00 |
| 14:00–17:00, DEFAULT (12) | 12 | 3 | 14:30–14:45 vs 17:00 |
| 09:00–10:00, 2/h; 18:00–19:30 FIXED 3, 50 % (controls) | 2 | 2 | pass |

Further symptoms of the same cause (all failing tests):
- *Day part:* "evening" for a 15:00–19:00 session returns 15:00–15:45 (all outside EVENING 16:00–23:00)
  and none of the 12 evening positions (`test_day_part_offers_slots_inside_the_part_asked_for`).
- *Existing bookings:* with positions 1–2 booked, 4 remain; 3 are returned (`test_booked_early_positions_do_not_hide_later_ones`).
- *Same day:* at 15:40 (6/h, 15:00–17:00) the 8 reachable positions shrink to 3 (`test_same_day_offers_every_reachable_position`).
- *Doctors:* "any skin doctor tomorrow" with 5 bookable dermatologists returns 3; two are silently
  dropped (`test_category_search_represents_every_bookable_doctor_of_the_category`).
- *MCP end to end:* Dr Garima's Monday morning has 9 phone positions; the model receives 3
  (`services/mcp/tests/review/test_mcp_rest_integration.py::test_mcp_offers_every_bookable_position_of_a_session`).

*Impact:* "Can I come at 4:30?" / "Is she there in the evening?" is answered from 15:00–15:45 only.
The agent either says no, or offers an earlier time the caller did not ask for. This is the
"availability ends early" failure the brief describes, and it violates the product rule that a
caller is never told there is nothing when there is.

*Why the existing tests missed it:* `tests/integration/test_sequence_windows.py:54` asserts the
search returns exactly positions `[1, 2, 4]`, i.e. it *pins* the truncation; no test compares the
agent view with the staff view; no test passes `maxSlotsPerSession`/`maxResources`; MCP unit tests
use `httpx.MockTransport`; the MCP e2e takes the first/last slot of whatever it gets.

*Also a specification defect:* the contract itself defines the caps (A-01) without a selection rule
or any omission/continuation field. Fix the contract first (spec-first rule in CLAUDE.md).

### D-02 — HIGH — TIMED sessions whose capacity is below the time grid offer only the first N times

`domain/availability.py:391` generates `for i in range(offered)` start times from the session
start, so capacity decides **which times exist**, not how many may be booked. IMPLEMENTATION.md §2.2:
"slots = … start..end step slotMinutes [TIMED]".

*Reproduction:* TIMED 10:00–13:00, 15-minute slots, FIXED 6 → only 10:00…11:15 exist; 11:30…12:45
never exist. 2/hour on 10:00–12:00 → 10:00…10:45 only. FIXED 4 on 14:00–18:00 in 30-minute slots →
14:00…15:30 only (`test_timed_session_offers_times_across_the_whole_session`, 3 cases; engine property
`test_timed_slots_cover_the_session_grid`, minimal example 07:00–07:20, 10-minute slots, FIXED 1).
*Same-day consequence:* at 11:30 with **nothing booked**, the clinic reports `NONE_AVAILABLE` with
reason `FULL` (`test_timed_clinic_with_spare_capacity_is_bookable_later_in_the_day`).

*Why missed:* the only TIMED engine test uses DEFAULT capacity where capacity equals the grid
(`tests/unit/test_availability_engine.py:285-300`); `tests/integration/test_templates.py:95-104`
creates exactly this shape (FIXED 12 on an 18-slot grid) but asserts only a notification.
Which times a capacity-limited clinic should offer is under-specified (A-02); that ambiguity does
not make the current behaviour correct, because the stated algorithm lists the whole grid.

### D-03 — MEDIUM — Same-day session facts disagree with the slots; an empty session is reported FULL

`compute_sessions` decides `reason`/`bookable` (`availability.py:365-382`) from
`remaining = offered − booked`, then builds slots and withholds those the caller can no longer
reach (S8, `:386`, `:398`, `:412`), then recomputes only `remaining` (`:419-420`). Result: `bookable: true,
remaining: 0`, no available slot. `search.py:301` then reports `reason or "FULL"`, so the caller is
told the doctor is full when nobody has booked.

*Reproduction:* session 15:00–17:00, 4/h, 25 % reserve, today at 16:35 (arrive-by 16:45), zero
bookings → staff view `bookable=true remaining=0 slots available=0`; agent search
`unavailable[].reason = FULL` (`test_same_day_session_level_facts_agree_with_its_slots`,
`test_same_day_search_never_reports_full_for_an_empty_session`; engine property
`test_same_day_bookable_remaining_and_slots_agree`, minimal example at 06:15).
Contract: "bookable=false when … remaining == 0"; FULL means the desk marked it full or the
bookings used the capacity. What the caller should hear instead is A-04.

### D-04 — HIGH (in the uncommitted change) — Raising capacity cancels every booking in the session

The in-progress one-minute precision rule is enforced for templates only (`schemas.py:273-279`,
used by `setScheduleTemplate` and `rollout validate`). Exception inputs are not checked
(`services/schedule_exceptions.py:74-96`). The engine then marks an unrepresentable session
`NOT_OFFERED` and generates no slots (`availability.py:333`, `:371`, `:403`), and
`services/impact.py:103` treats "slot not in the offered set" as gone.

*Reproduction:* 15:00–17:00 FIXED 12, two bookings; `CAPACITY_CHANGE newCapacity=150` → `201`,
both bookings `NEEDS_RESCHEDULE`, notifications queued, session `NOT_OFFERED`
(`test_raising_capacity_never_cancels_existing_bookings`). `EXTRA_SESSION 18:00–18:20 newCapacity=30`
→ `201`, session never offered, 0 slots (`test_explicit_extra_session_capacity_is_either_refused_or_offered`).
Contract: only an exception that "removes or shortens a session" moves bookings to NEEDS_RESCHEDULE;
IMPLEMENTATION.md §2.2 (edited in this working tree) says explicit capacities that need sub-minute
intervals are rejected. The reason code `NOT_OFFERED` is also the resource-policy code ("never
offer"), so the agent hears a policy that does not exist.

### D-05 — MEDIUM — Search offers slots that booking refuses; reschedule ignores the booking horizon

The horizon rule lives only in `services/bookings.py:120` (`book`). The engine, search and
`reschedule` (`bookings.py:336`) do not apply it.
*Reproduction:* search with explicit dates 200 days ahead → `FOUND` with available slots; booking one
→ `400 Bookings open 180 days ahead.` Rescheduling an existing booking to the same slot → `200
RESCHEDULED` (`test_search_never_offers_a_slot_that_booking_refuses`,
`test_reschedule_applies_the_same_horizon_as_booking`). The agent promises, then fails; and the same
slot is refused for BOOK but accepted for RESCHEDULE.

### D-06 — MEDIUM (privacy) — A stranger can learn that a named patient has a booking with a doctor

`services/bookings.py:136-145`: when a booking with the same normalised name and phone exists in the
session and the request comes from another number, the API answers `409 CONFLICT "This customer
already has a booking in this session."`; otherwise the same request books (`201`).
*Reproduction:* patient "Meena Iyer / 9812300042" booked in the morning session; a caller from
+919800000777 tries to book "Meena Iyer / 9812300042" in the morning and in the afternoon session →
`409 "already has a booking"` vs `201` (`test_a_stranger_cannot_learn_that_a_named_person_has_a_booking`).
OPEN-QUESTIONS S9 states the 409 is neutral "so a stranger cannot learn of someone else's booking";
it is not. In healthcare, "X sees Dr Y (department) on date Z" is sensitive.
*Why missed:* `tests/integration/test_identity_and_scopes.py:183-197` is named
"reveals nothing to another caller" but asserts only that the id and code are absent from a 409 that
is itself the disclosure. Product decision needed (A-07).

### D-07 — MEDIUM — A desk confirmation on an unsigned resource reaches the agent as CONFIRMED

`services/booking_views.py:67-68` returns `CONFIRMED` whenever `row.timing_confirmed`, without the
cap that the session view applies (`availability.py:336-340`). Contract: "dataConfirmed=false on the
resource caps timingCertainty at EXPECTED" (`openapi.yaml:1104`, `:1663`; IMPLEMENTATION.md §2.2).
*Reproduction:* resource `dataConfirmed=false`; session certainty is correctly `EXPECTED`; desk
`POST /bookings/{id}/confirm`; agent `LIST` → `timingCertainty: CONFIRMED`
(`test_unsigned_resource_data_caps_every_certainty_at_expected`). The only word the agent may speak
as "confirmed" is thus produced from data the hospital has not signed. The contract also says the
desk confirmation is "the only state the agent may voice as confirmed" (`openapi.yaml:1231`); the two
rules need one precedence statement (A-05). Until then the stricter (cap) rule should win.

### D-08 — LOW (privacy) — The neutral 404 is distinguishable through a response header

Every response carries `Server-Timing: db;…;desc="N queries"` (`app.py:104-105`). Rescheduling
another patient's booking costs one more query than a non-existent booking (the second resource lock,
`bookings.py:345-346`): `5 queries` vs `6 queries` with identical bodies
(`test_neutral_not_found_does_not_leak_through_response_headers`). The MCP adapter drops headers, so
the model never sees it; any holder of the agent token calling the API directly does.

### Observation (not filed as a defect)
- Database connection refused on a write or lookup surfaces as `500 INTERNAL` (asyncpg raises a bare
  `OSError`, not an SQLAlchemy `OperationalError`, and `app.py:69-72` maps only the latter to
  `503 SERVICE_UNAVAILABLE` + `Retry-After`). Search and knowledge do catch `OSError`. The adapter maps
  both to a failure envelope, so no caller is misinformed; the status and missing `Retry-After` are
  inconsistent with the spec's 503 semantics.

## 3. What was verified correct (adversarially)

Each item is a passing test in `tests/review/**` or `services/mcp/tests/review/**`:
contract formulas for totals, reserve and windows (9 REST shapes + 300 property examples); windows
adjacent and inside the session; held slots unavailable and counted; unbookable states (cancelled,
left, ended, full, NOT_OFFERED, DESK_ONLY) expose no slot and `409` with empty `currentSlots`;
exceptions applied in creation order (TIME_CHANGE → TIMING_PENDING → TIMING_CONFIRMED → UNAVAILABLE →
EXTRA_SESSION); late board shifts windows from the expected start; board is today-only and expires;
arrive-by = min(offset, desk last arrival); 10 concurrent bookings of one slot → exactly one `201`;
a second transaction blocks on the first's uncommitted insert and then loses; the live-slot index
refuses a duplicate without the application; 6 concurrent retries with one key → one row; same key
with another body → `IDEMPOTENCY_CONFLICT`, nothing written; failed reschedule leaves both bookings
and history unchanged; successful reschedule releases the old slot; cancel/reschedule identity
failures return byte-identical bodies; contact phone or booked-from number may cancel; two patients on
one number → `NAME_REQUIRED` with no names; spoken number without name discloses nothing; identity in
the body is ignored; a stranger's LIST finds nothing; unconfirmed fees never reach the agent;
TIMING_PENDING and `DESK_WILL_CONFIRM_TIMING`; one notification per impacted booking, no duplicate
from an overlapping second exception or an identical TIME_CHANGE; withdrawal restores bookings and
deletes untold notices; a shorter queue moves people forward earliest-first before bumping; template
change impacts only bookings from its effective date; NOT_OFFERED switch impacts future bookings;
reason category and note never reach the agent; red flags win over every other field in every
language and return nothing else; namesakes are clarified with distinguishable details; knowledge
answers are the approved text verbatim (33 entry × language cases); drafts are never spoken and an
approval reaches a second application instance on its next question; scopes (agent vs staff);
database down → `COULD_NOT_CHECK`; facility-day resolution just after IST midnight; migrations
upgrade → downgrade → upgrade on an empty database; a clean database is not ready until migrated;
the published availability equals the booking ledger after every step of a seeded 60-step day;
MCP: no identity parameter in any tool schema, unknown arguments refused, find_availability body
identical to REST, every action reaches its operation with header identity, a write without a call
id is never recorded, a hanging API times out and a write is retried exactly once with the same key,
5xx/429 become failure envelopes carrying `Retry-After`.

## 4. Architectural risks

| # | Risk | Evidence | Recommendation |
|---|---|---|---|
| R-01 | **Caller identity is unauthenticated end to end.** With `ENABLE_HEADER_PASSTHROUGH` on, ContextForge copies `X-Caller-Number` from whoever calls it; the adapter and API trust it. Anyone with a gateway token can act as any caller number (list, cancel, reschedule with a known name). | gateway `mcpgateway/utils/passthrough_headers.py:440-470` (value copied after sanitising only), `config.py:3886` (passthrough off by default); adapter `tools.py:89-101`; TARGET.md "Next 1. Signed call context". | Treat as a production blocker for lookup/cancel/reschedule: signed call context verified by the API (not the adapter). |
| R-02 | **Stale identity across calls through the gateway.** ContextForge pools upstream MCP sessions per downstream session and fixes headers when the upstream session is created; if the voice agent reuses one MCP session across phone calls, later calls could carry the first call's `X-Call-Id`/`X-Caller-Number`. | `services/upstream_session_registry.py:925-942`, `services/tool_service.py:6748-6771` (from reading; not reproduced against a live gateway). | Voice agent must open one MCP session per phone call; verify on a live gateway (CONTEXTFORGE.md integration check). |
| R-03 | **No run-time binding between a deployment and its database.** A hotel deployment pointed at the hospital's database reports ready and serves it. | `routers/health.py:23-37` checks only the schema head; `test_a_deployment_refuses_another_providers_database` (xfail, strict). | Store the provider id in the database at `rollout apply`; refuse readiness on mismatch. |
| R-04 | **Unsafe defaults if ENV is unset.** Both services default to `ENV=development` (`api/config.py:50`, MCP `config.py`), which permits an empty MCP bearer token and a dev caller-number fallback; compose defaults to development (`deploy/docker-compose.yml:20`). Azure sets `ENV=production` (`deploy/azure/deploy.sh:279-283`). | as cited | Default to production, or refuse to start without an explicit ENV. |
| R-05 | **Capacity changes move booked customers' expected windows.** The window formula depends on total capacity; a CAPACITY_CHANGE from 12 to 24 moves position 6 from 15:50–16:00 to 15:25–15:30 with no notification. | `test_capacity_increase_does_not_silently_move_a_booked_window_earlier` (xfail, strict) | Decide (A-03). |
| R-06 | **Working tree is mid-change.** D-04 is introduced by the uncommitted precision rule; the spec example windows were edited in the same change. | `git diff` of `availability.py`, `schemas.py`, `openapi.yaml` | Land the change with D-04 fixed and its tests, as one reviewed commit. |

## 5. Specification ambiguities (decisions needed; spec first)

| # | Ambiguity | Where | Suggested decision |
|---|---|---|---|
| A-01 | `maxSlotsPerSession`/`maxResources` cap the answer with no selection rule and no omission/continuation field. | `openapi.yaml:1992-1993` | Either return every bookable slot (sessions are small: ≤ 36 positions in all realistic shapes), or define (a) selection relative to the requested time/day part and (b) an explicit omission count or continuation the agent can act on. Never a silent first-N. |
| A-02 | TIMED capacity below the grid: which times are offered. S12 covers only the reserve. | `IMPLEMENTATION.md §2.2`, OPEN-QUESTIONS S12 | Offer the whole grid; capacity limits bookings (session unbookable when booked = capacity − reserve). |
| A-03 | Does a capacity change that moves a booked window need a notification? | `createScheduleException` description | Either keep booked windows fixed, or notify with SESSION_TIME_CHANGED when a booked window moves earlier. |
| A-04 | Same day, an empty queue whose remaining positions' windows have all closed: what is it (FULL? ARRIVE_BY? walk in)? | S8, §2.2 `bookable` rule | A distinct reason (or `ARRIVE_BY_PASSED`-like) that the agent can phrase truthfully; never FULL without bookings. |
| A-05 | Precedence between "dataConfirmed=false caps certainty" and "desk confirmation is the only CONFIRMED". | `openapi.yaml:1104`, `:1231`, `:1663` | Cap wins; desk confirmation of an unsigned resource stays EXPECTED to the agent. |
| A-06 | Booking horizon scope: create only, or every slot the agent is offered or moved to. | `openapi.yaml:264` | Every agent-facing slot (search, book, reschedule). |
| A-07 | Duplicate-booking detection vs privacy (S9). Any different answer to a stranger discloses. | S9, `openapi.yaml:2169` | Product/privacy decision: allow the duplicate and let the desk merge, or answer the stranger exactly as a successful booking would be refused for another reason. |
| A-08 | Nullable fields are omitted (`exclude_none`) while the examples show explicit `null`. | `routers/deps.py:40`, `openapi.yaml:221,239,244` | State in the contract that absent means null (clients and the LLM prompt must not treat absence as unknown-error). |
| A-09 | "Book one patient per call" (pack instructions, tool text) can be read as one patient per *phone* call; the contract means one per *tool* call. | `services/mcp/src/frontdesk_mcp/packs/healthcare.json`, `openapi.yaml:268-269` | Reword: "one patient per manage_booking call; book each family member separately". |

## 6. Test-infrastructure limitations (what this review could not prove)

No live ContextForge, LiveKit agent or Supabase pooler; R-01/R-02 rest on code reading. Latency
budgets were not measured. The in-process REST tests share one event loop (requests overlap on
separate pooled connections; the forced-interleaving DB test covers the constraint itself). The MCP
integration tests run the API on the real clock with the demo seed relative to today. Timezone tests
use Asia/Kolkata only (no DST). Property tests are derandomized (reproducible, not exhaustive).
