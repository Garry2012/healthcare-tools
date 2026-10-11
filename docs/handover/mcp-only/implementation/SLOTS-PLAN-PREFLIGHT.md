# Slots plan revision 3: independent pre-flight

**Verdict: needs plan revision — resolve B-1 through B-6 below before building.**

Reviewed 7–8 October 2026 against HEAD `1325a8b8dd358e7087149d35b8301c5337ce351b`. This is a review, not an implementation or a replacement plan. Only this report is changed/committed. No operational API, authentication endpoint, database, Azure, push, merge or deployment action was performed.

## Scope and evidence

The sole proposed design reviewed is `SLOTS-PLAN.md`, revision 3. The impact document's facts, decisions and owner answers are background; its superseded sections 4–6 are not implementation authority. Source paths below are relative to the repository; short Python filenames in prose mean `services/mcp/src/frontdesk_mcp/` unless prefixed `tests/`.

Inputs were untracked at review time and are left untouched:

| Input under `docs/handover/mcp-only/implementation/` | SHA-256 |
|---|---|
| `SLOTS-PLAN.md` | `0b677111766867368cc9bb49742c5b5067afa3f873a5675de54b59394ac2e7a8` |
| `OPUS-OPS-API-040-IMPACT.md` | `b27d6217be28167d89f8228a6ee5d05d9480fc166565e707bc4ee67aa19a6828` |
| `evidence/manoj-slots-live-20261007.txt` | `6be6de05a346adccdd23a3f00e4b8f72cff2b66219d785169e7ecc2ee12ab4bd` |

The only network download was the public [OpenAPI contract](https://healthcare-contract-docs.icytree-6543aaa9.centralindia.azurecontainerapps.io/openapi.yaml), saved outside the repository as `/tmp/astra-preflight-openapi-040.yaml`. SHA-256: `d3e93f45498fb86feeb5bb93c0adaba7cff47b48daa21ac810790b5483e96c80`. It still labels itself `0.4.0-draft` (line 7); the supplied owner decision says it is stable. “0.4.0 line” references below identify these exact downloaded bytes, not a mutable later version of the URL.

## Check 1 — concrete claims

| # | Claim | Assessment and code evidence |
|---|---|---|
| 1 | Policy line references | **Confirmed:** `availability_policy.py`: `DoctorFacts:70`, `TODAY_STATUS:168`, `_today:207`, `_future:235`, `decide_doctor:253`, `_contains_time:272`, `decide_booking:281`, `rank` order dictionary `:323`, `aggregate:328`. |
| 1 | Retrieval line references | **Confirmed:** `schedule_reader.py`: `doctor:71`, summary ON_CALL early return `:73`, summary board branch `:85`, `department:98`, hard-coded APPOINTMENT_REQUEST counts `:110` and `:131`. The ON_CALL shortcut requires a supplied summary; it is not a blanket shortcut for ID-only calls. |
| 1 | Services, startup, retry references | **Confirmed:** `availability.py:141` decision table; `booking.py:86` `_appointment_out`, `:147` `_failure`, `:227` `_schedule_gate`, `:304` `_reschedule_gate`; the `Write` check is `:242`, its `return None` is **`:243`**. `server.py:182` calls `services.ops.start()`. `ops_client.py:307` preserves uncertainty on a retry response of **any status >=400**, not just 4xx. |
| 2 | New Decision needs `_single` and `rank` entries | **Confirmed, but incomplete.** Both index dictionaries directly (`availability.py:147`, `availability_policy.py:325`). Executable probes with the proposed decision string raise `KeyError` in both. `_combine:189` is another affected consumer absent from the plan's change list; see B-3. |
| 3 | 21 exact request-path assertions would break | **Wrong.** There are **21 matching source lines, 22 `ops_paths()` calls, 18 assertions containing a direct call, and only 3 whole-list equality assertions**. Many only forbid `/availability`, count one particular path, or check a subset; an extra `/slots` path does not violate those assertions. Details below. Conditional slot reads remain reasonable for latency, but this numerical justification is false. |
| 4 | Startup warm/refresh is feasible and invisible to per-call logs | **Feasible pattern; logging claim wrong as written.** `ops_client.py:212`/`:221` provide bounded warm-up/background ownership, with shutdown at `:226`. But `tests/harness.py:77` records **every** request; `ops_paths:54` excludes only `/auth/token`. `tests/test_server.py:47` reuses that recording transport through startup without clearing it. Capability reads will be recorded. Direct service tests also do not run server startup. See B-1. |
| 5 | Six description defects; quoting-only overlay parses | **Confirmed**, for the downloaded hash above. Lines **2327, 2328, 2351, 2370, 2396, 2460** are the six named properties. Raw YAML parses but creates bogus schema keys; quoting only those six descriptions produces valid mappings and parses. This is not a claim that raw YAML cannot be loaded. Full evidence below. |
| 6 | ErrorCode cannot gain SLOT_FULL without re-pinning | **Confirmed.** `tests/test_contract.py:17` pins the files, `:19` hashes, `:40` permitted overlay changes, `:71` exact error-code equality. The new contract adds exactly UNSUPPORTED_CAPABILITY and SLOT_FULL to those codes (0.4.0:2349). Re-pinning also needs the moved board example and the second overlay consumer, not just hashes/enums; see S-1. |
| 7 | Constructors and decision callers | **Confirmed inventory below:** 9 DoctorFacts constructors, 2 SessionDecision constructors, 1 Write constructor, 5 decide_doctor calls and 14 decide_booking calls across production/tests. Definitions and `isinstance(..., Write)` checks are not counted as constructors. |
| 8 | Enum/output consumers | **Confirmed inventory below; the plan omits some.** `_combine`, output formatting with a clock, stub contract validation, external journeys and benchmarks need attention as well as the enumerated tables/snapshot. |
| 9 | Fixture-only capability/slot stubs are possible | **Confirmed as a feasible extension, not existing functionality.** `dev/frontdesk_stubs/ops.py:45` owns scripted state, `:69` sets boards, `:136` injects failures, `:281` handles writes/replay, `:453` loads HTTP scenarios, `:471` lists routes. Neither new GET route exists now. Script supplied JSON by doctor/date and supplied write responses; do not generate blocks or allocate seats. Extend reset/scenario support and preserve auth/replay ordering. |

### Claim 3: exact count and meaning

| File under `services/mcp/tests/` | Source lines with calls | AST call count | Direct-call assertion statements | Whole-list equality lines |
|---|---|---:|---:|---|
| `test_availability.py` | 97, 184, 209, 254, 260, 269, 277, 285, 481, 494, 503, 515, 523 | 14 | 11 | 260, 523 |
| `test_booking.py` | 119, 389, 398, 538, 542, 691, 730 | 7 | 6 | 691 |
| `test_server.py` | 86 | 1 | 1 | None |

Line 515 contains two calls. Lines 209/277 in availability and 538 in booking assign intermediate values rather than asserting. Additional assertions on those intermediates count selected paths, not equality of the entire request sequence. The three equality cases are missing date, ambiguous doctor name, and malformed doctor ID: they are not three ordinary successful single-doctor reads that necessarily gain slots. Empty-path truthiness checks at booking lines 119/398 also concern local validation. Preserve the intent of all these tests; do not claim 21 would necessarily fail.

### Claim 5: overlay proof

The raw descriptions contain commas and spurious `: null` fragments. In-memory double-quoting of the entire description value on each of these lines changes only quote characters; it does **not** silently repair wording or remove those fragments.

| 0.4.0 line | Property |
|---:|---|
| 2327 | `CallSummaryCreate.properties.doctorId` |
| 2328 | `CallSummaryCreate.properties.appointmentId` |
| 2351 | `Error.properties.error.properties.message` |
| 2370 | `ClientCredentialsGrant.properties.scope` |
| 2396 | `LoginResponse.properties.role` |
| 2460 | `AdminStaff.properties.role` |

Actual probe output:

```text
Raw YAML parses, but flow mappings contain bogus keys
Quoting-only changed lines: [2327, 2328, 2351, 2370, 2396, 2460]
Quotes-only: True
Overlay SHA256: 1217015de39f137ebef159915f4fa90dfcf2fa196277ee43b6e5ce192679ff2f
```

A recursive scan of the complete raw document found exactly six description mappings with spurious null-valued keys, at the six named properties. After quoting, each has only `type` and `description`. This verifies the proposed overlay's scope, not all semantic correctness of the upstream OpenAPI document. No overlay or new pin was written into the repository.

### Claim 7: complete call-site inventory

| Symbol | Production locations under `services/mcp/src/frontdesk_mcp/` | Test locations under `services/mcp/tests/` |
|---|---|---|
| `DoctorFacts(...)` | `schedule_reader.py:74,84,86,88,96,108,115` | `test_availability_policy.py:26,194` |
| `SessionDecision(...)` | `availability_policy.py:215,231` | None directly; policy helpers create them |
| `Write(...)` | `availability_policy.py:318` | None directly; tests check type |
| `decide_doctor(...)` | `availability.py:91`; `booking.py:240` | `test_availability_policy.py:31`; `test_schedule_reader.py:66,99` |
| `decide_booking(...)` | `booking.py:241` | `test_availability_policy.py:74,80,88,91,110,135,150,168,177,185,198,210,228` |

Defaulting added dataclass fields preserves the existing positional calls. There are two SessionDecision construction sites, but `_usual` feeds both `_future` and `working_hours` (`availability_policy.py:241,268`); it must not attach date-specific capacity to WORKING_HOURS. Dataclass `replace` calls in policy tests preserve new fields automatically; tests changing board facts still need suitable slot evidence when testing the new branch.

### Claim 8: consumers and propagation

| Contract element | Consumers that need an explicit decision/update |
|---|---|
| Decision | `availability_policy.py:168,189,203,207,229,235,253,261,281,321,328`; `schedule_reader.py:110,131`; `availability.py:39,141,156`; `outcomes.py:44,56,81`. `_combine`, selection of alternatives and `_future`'s early exits matter as much as rank. |
| Reason | Policy reason selection and BookingDecision unions; `booking.py:240` result mapping; `availability.py:135,154`; `outcomes.py:34,45,57,82`. Adding enum values changes **both tools'** schemas, including nested Callback definitions. |
| AvailabilityOutcome | `outcomes.py:98,111`; `availability.py:132,141`; `availability_policy.py:328`; direct outcome expectations in `tests/test_availability.py`, `tests/test_stubs.py:42`, `tests/test_external.py:119`, `dev/bench.py:54`. |
| BookingNextStep | `outcomes.py:154,165`; `booking.py:244`; `tests/test_server.py:442` requires the documented next-step row immediately. |
| New slot/appointment fields | `outcomes.py:38,48,60,137,163`; `availability.doctor_out:39`; `booking._appointment_out:86`, `_list:190`, `_change:300`, `_written:328`. LIST and CANCEL also use AppointmentOut; slotMoved is only computable when a comparison exists. |
| MCP publication | `tools.py:104,127` generate output schemas at registration; `cli.py:16` exports them; `prompt.py` supplies version metadata; `services/mcp/src/frontdesk_mcp/packs/healthcare.json` supplies descriptions; `tests/contracts/mcp-tools.snapshot.json`; `tests/test_server.py:134,409,442`; `docs/handover/VOICE-TEAM.md` contains exact input/output table rows, outcomes and descriptions. |
| Operational tests/docs | `tests/test_contract.py`; independent old overlay path in `tests/test_stubs.py:22`; `tests/test_external.py:114,145,151,158`; `dev/bench.py:46`; `tests/test_bench.py`; `README.md:22`; `CLAUDE.md:14,20,23,24`; `docs/DECISIONS.md:115,166`; `docs/handover/mcp-only/PLAN.md:35,67,89,126,133,204`. Prior hand-backs remain historical, not rewritten. |

No additional knowledge-service request, gateway bearer, trusted header, secret, backend implementation or database is required by the slot design. Existing `OPS_BASE_URL` and machine authentication serve the new GETs. ContextForge still registers the same four tools, but must refresh their schemas/descriptions after the separately approved deployment. Voice consumers need the updated outputs and time-selection flow. Shobhit's service is unaffected. These are interface consequences, not actions taken in this review.

## Check 2 — design findings

### Blocking B-1 — capability lifetime, startup and test isolation are not specified sufficiently

**Evidence:** `SLOTS-PLAN.md` B-1 promises no hot-path discovery and unchanged request logs. The recorder does not isolate startup; the direct service constructors create their own readers (`booking.py:117`, `availability.py:54`), while `Services.build` shares one reader but does not expose it as a Services field (`tools.py:54`). `Services.aclose:61` closes only HTTP clients. `ScheduleReader` has no start/close/background task today. `DirectoryCache.get:21` deletes expired entries and has no refresh/retained-stale semantics. A token refresh pattern is reusable, but its hot-path fallback at `ops_client.py:118` must not be copied for capabilities if the plan forbids that fallback.

Actual in-process probe (only local stub transport):

```text
Startup requests: [('POST', '/api/v1/auth/token')]
ops_paths after token warm: []
Current /capabilities fixture: Rejected 404
ops_paths after simulated capability warm: ['/capabilities']
```

**Required revision:** specify the one owner of the shared capability snapshot and refresh task, startup/refresh budgets, cadence, freshness/expiry policy, recovery after a failed startup, and cancellation before HTTP-client shutdown. Explicitly decide what happens after a cached `enabled=false` value ages while the owner enables slots; it must not silently authorize the legacy booking path forever. State how `SlotPlan.enabled=false` after cached enabled=true is handled. Specify which operations depend on this data: CREATE/RESCHEDULE and AVAILABILITY versus unrelated LIST/CANCEL/summary/knowledge and WORKING_HOURS.

Provide a startup fixture used by direct services as well as the server, with a genuine request-boundary marker for per-call assertions and separate startup assertions. Do not globally hide `/capabilities` from logs/tests, because that would hide accidental hot-path calls. Preserve `cli.schema_document` as an offline operation (`cli.py:19`). Direct external tests and low-level MockTransport tests must be covered, not just `server.py`.

**Tests to add:** enabled/disabled startup, failed startup then recovery, refresh failure/expiry, concurrent reads during refresh, disabled→enabled transition, teardown, zero capability GETs caused by a tool invocation, and unrelated tools remaining usable when capability discovery fails. Keep existing invocation request assertions meaningful.

### Blocking B-2 — C-1's ordering is sound, but its inputs and join rules leave holes

**Evidence:** C-1 gives `None` the legacy meaning and the matched SlotSession the new meaning. C-3 also requires “empty evidence” for a board row whose slot session is absent, without defining a distinct representation. Passing `None` there would restore legacy IN/LATE bookability. C-1's proposed `(status, evidence, now)` cannot distinguish BOARD_STALE from BOARD_UNKNOWN without the stale fact (`availability_policy.py:211`), and the future path must distinguish no clock check from today's check. C-3 reads board and slots concurrently; their statuses can disagree, but it does not specify which status is passed to C-1.

The plan's intended UNKNOWN-first branch **does** prevent UNKNOWN + session-bookable-false from becoming NO_OPEN_SLOT. That guarantee is incomplete if a board IN row is paired with a slot UNKNOWN row and only the board status is supplied, or if missing evidence is misrepresented. A generic “all blocks ended” check must not run before UNKNOWN/CANCELLED precedence.

**Required revision:** define the evidence variants for disabled, deliberately unread, read-but-unmatched/empty, and matched; define a single status reconciliation/precedence rule for conflicting board/slot facts and stale metadata. Keep that decision in one policy function. Specify duplicate/normalised session-label handling, including blank labels, without first-match guesses. Explicitly define the empty-block case (do not let vacuous `all([])` invent SESSION_ENDED). Future no-slot behaviour must remain usual-schedule behaviour, not today's NOT_CONFIRMED callback rule.

**Tests to add:** board IN + slot UNKNOWN, board UNKNOWN + slot IN, cancellation disagreement, stale UNKNOWN, missing/extra/duplicate/blank sessions, empty blocks, future versus today. Assert UNKNOWN callbacks are never converted into “not available” by capacity handling, and no open slots are offered from a session whose status/flag forbids booking.

### Blocking B-3 — department matching omits `_combine` and future selection

**Evidence:** `availability_policy._combine:193` recognises only APPOINTMENT_REQUEST as a positive mixed-session result. An executable probe on the existing function gives:

```text
Existing combine(SLOT_CHECK_REQUIRED, CANCELLED), no selected session:
(<Decision.NOT_AVAILABLE: 'NOT_AVAILABLE'>, <Reason.CANCELLED: 'CANCELLED'>, False)
```

Thus adding `is_match`, rank and aggregate alone can discard a valid department candidate with Morning “check slots” and Evening cancelled. Mixed “check slots”/callback also needs an explicit scoping rule. `_future:243` builds alternatives solely from APPOINTMENT_REQUEST and `:244` selects only those alternatives; simply changing the per-session decision to SLOT_CHECK_REQUIRED loses future department matches. `aggregate:336` likewise filters APPOINTMENT_REQUEST, while the two reader counts stop a search based on that same value.

**Required revision:** include `_combine`, alternatives, `_future` selection and missing/empty usual-schedule exits in C-6. Define mixed-session behaviour for named scope and unnamed scope once; use `is_match` consistently where the purpose is finding candidates, not where it means confirmed capacity. Keep `SearchState.matches_found` distinct from published `bookableFound`. `DOCTORS_MATCHED` with `bookableFound=0` is coherent; the current pack's “department AVAILABILITY lists only bookable doctors” needs the new outcome described separately. WORKING_HOURS still reports zero, with its current facts and ordering.

**Tests to add:** a department doctor with matched+cancelled, matched+UNKNOWN (including an unlabelled unresolved row), matched+callback, selected versus unselected session, future matched versus wrong weekday, partial searches with matches and without matches, ranking/capping, and WORKING_HOURS under enabled capabilities.

### Blocking B-4 — booking precedence and result types do not yet fit C-5

**Evidence:** `decide_booking:289` immediately returns a whole-doctor NOT_AVAILABLE result. C-1 maps a session whose blocks are all full to NO_OPEN_SLOT; C-5 says a selected FULL block produces SLOT_FULL. For a one-session all-full doctor, the existing early return prevents C-5 from identifying the selected block. Likewise C-5's “any slot evidence and no time → TimeRequired” cannot unconditionally precede UNKNOWN, CANCELLED, ON_CALL, ended-session and read-failure handling. Those refusals must not become a prompt to choose a time.

The existing `NotAvailable.alternatives` is `tuple[SessionDecision, ...]` (`availability_policy.py:118`) and `booking.py:255` passes each item to `outcomes.session_out`. C-5 calls alternatives “open blocks”; returning raw SlotBlock objects there is incompatible. `_contains_time` is currently a boolean used twice (`:294,316`), and `:298,314` treats missing board boundaries as unverifiable even when proposed block evidence could supply complete bounds.

**Required revision:** write an explicit precedence matrix for whole-scope refusal, session choice, missing time, then selected-block FULL/CLOSED/OPEN. Retain N-2's CANCELLED/SESSION_ENDED meaning while stating when slot-specific NO_OPEN_SLOT may be refined to SLOT_FULL. Keep session alternatives with open-slot data, or explicitly change the result type and every formatter; do not silently mix blocks and sessions.

`_contains_time` can remain one membership rule, dispatching on evidence rather than a boolean flag. Separate block **containment** from block **bookability**: FULL blocks must still be discoverable. Share one block lookup between membership and expected_slot selection rather than copying the interval comparison. Decide how verified block bounds replace legacy TIME_NOT_VERIFIABLE checks only for the slot branch.

**Tests to add:** all blocks full with/without a requested time, a selected full block beside an open block, session flag false with apparently open blocks, UNKNOWN/cancelled/ended with missing time, incomplete board time bounds but complete slot blocks, exact block boundary and session end, unknown-boundary legacy regression cases unchanged. Alternatives must serialize through the actual MCP output models.

### Blocking B-5 — slot formatting lacks the required time/source information

**Evidence:** C-2 requires `now` for open-block classification; C-3 deliberately retains unfiltered SlotSession blocks. `outcomes.session_out(s, requested)` (`outcomes.py:60`) has no `now`. It is called from `availability.doctor_out:41` and both booking alternatives paths (`booking.py:247,255`). Recomputing clock/filter rules in presentation would violate the single-policy rule. An owner block can remain `bookable=true` in a stale response while our end-time guard closes it.

C-4 includes future desk-added slot sessions, including doctors without a usual schedule. The current `_future:239` exits before considering them. `UsualSessionOut` requires non-null `start`/`end` and emits `onRequestedDate` from `s.days` (`outcomes.py:38,65`); SlotSession contains neither usual days nor session-level start/end. A desk-added empty/cancelled session cannot be truthfully converted by inventing hours or recurrence. `UsualSessionOut` also has no owner status, although C-4 depends on future NOT_CONFIRMED/CANCELLED facts.

**Required revision:** define how the captured invocation time reaches the one policy helper producing open slots (or retain a policy-derived projection alongside full evidence). Formatting must reuse it and respect session/status gates; it must not offer blocked sessions' blocks. Define the presentation and provenance of slot-only future sessions, including no usual schedule, same label on a non-usual weekday, empty block lists, and `onRequestedDate`. Do not label a one-date desk exception as recurring usual hours. Resolve the tension between “desk-added session is included” and “other weekdays stay NOT_USUAL_DAY.”

**Tests to add:** clock-consistent openSlots at end==now and minute boundaries, no offered slots after status/flag refusal, future desk-added session with and without usual hours, empty future cancelled session, and output-schema validation for all of these.

### Blocking B-6 — the proposed green-commit/schema phasing is contradictory

**Evidence:** plan lines 193–198 change schemas in 3a/3b/4 but defer snapshot/version/docs to 5, while requiring each commit to pass `make test-fast`. `tools.py:104,127` generates the schema immediately from current models; there is no delayed-publication layer. `tests/test_server.py:134` compares it exactly with the snapshot. `:409` compares snapshot fields against the VOICE-TEAM tables, and `:442` compares current outcome/next-step literals against those tables. Adding fields or enums fails these checks in the same commit, regardless of a promise to merge the series together.

Phase 2 also spans more than ten files once shared lifecycle, direct fixtures and tests are included. New Decision handling cannot be deferred to phase 4 if 3a already produces that decision. `Reason` additions alter both tool schemas, not just availability.

**Required revision:** adopt explicit bounded subcommits as outlined in Check 3. Update schema/snapshot/tables with each exposed change, with version bumps, **or explicitly approve moving the one complete final schema publication to 3a**, including final booking/department fields and tables, then keep that surface unchanged through the remaining unpublished implementation commits. The latter is staged publication, not permission to deploy incomplete behaviour. Hold capability activation as well as phases 3a–5 from partial deployment. Do not weaken schema or table tests to make the sequence green.

### Should change S-1 — complete the 0.4.0 migration and fixture provenance

`tests/test_stubs.py:22` independently loads the old overlay; changing only `test_contract.py` leaves stub conformance checks on 0.3.0. `README.md:22` also names the old pin as current. The board example moved from `schema.example` to `examples.facilityBoardMixedDay.value` (0.4.0:444); `tests/test_contract.py:84` would raise KeyError, and its date/count/time assertions refer to the old example. Update the fixture validation source and actual 0.4.0 example expectations, preserving the old pin as explicitly historical.

The supplied live evidence contains **two today slot payloads and their board/profile context**; it does not contain a raw capability response or raw future response. Use the public contract's named capability/future-compatible examples as labelled contract fixtures where needed; do not describe them as copied live captures. The live file's capture 1 has an unlabelled desk window and capture 2 has NOT_CONFIRMED morning closed/evening open; both should remain identifiable fixtures.

### Should change S-2 — complete failure and response-integrity rules

Adding stage strings alone is insufficient. `availability._service_error:76` converts Rejected to NOT_FOUND/INVALID_REQUEST before its COULD_NOT_CHECK return. `booking._schedule_gate:238` sends Rejected to general `_failure`, which yields REJECTED rather than K-8's COULD_NOT_RECORD. Define treatment of slot/capability 400/404, malformed 200, timeout, 401/403 and unsupported capability, distinguishing read failure from a definite appointment-write rejection. Booking's capability-stage detail is not specified in D-2 although CAPABILITIES_UNAVAILABLE is listed in E.

Validate a slot plan's doctor/date association before using it, and define handling of mismatched enabled flags, invalid block intervals, negative counts, duplicate/overlapping blocks and ambiguous labels. These are validation of facts being consumed, not permission to recompute seats. Do not invent extra contract requirements silently: document any consumer invariant and its failure outcome. Test that malformed or mismatched data never causes a write or becomes ordinary unavailability.

### Should change S-3 — carry write evidence through every response path; test replay after capacity changes

Returning `Write(expected_slot)` from `_schedule_gate` is the smallest appropriate transport of that policy result. Callers to change are `_create:214`, `_reschedule_gate:320`, and `_change:281` (through `_reschedule_gate`); its existing `None` on lookup miss (`:315`) is still needed for the explicitly accepted B-1 bypass. Successful Write objects are truthy, so the current `if blocked: return blocked` idiom must be replaced with explicit result handling. `_written:324` is also part of CREATE/CANCEL formatting, not just `_appointment_out` and `_change`.

The B-1 description is shorthand: current code bypasses whenever the appointment is **absent from the lookup**, not by explicitly checking its date. Past appointments are one cause (stub `ops.py:417`, owner default from-today). Preserve this accepted behaviour, and state that expected_slot is unknown on bypass.

Specify slotMoved when the optional owner slotTime and expectedTime are both absent, and on LIST/CANCEL where no comparison exists. Never present a missing time as a verified moved block. Test a non-boundary requested time (e.g. 10:45 maps to 10:30) separately from an actual owner move. Keep NOTED and owner status distinct.

The transport's same-key retry rule is correct and remains unchanged (`ops_client.py:307`). Add a scenario where a **later tool invocation** repeats the same operation after a possibly committed write and the last seat is now full: the service repeats its gate before POST (`booking.py:214`). Document the intended result and whether owner replay can still be reached. Do not add local persistence or invent an idempotency-lookup API to solve it during implementation.

### Should change S-4 — external gates, latency scenarios and rollout are missing from the file plan

`tests/test_external.py:151,158` intentionally submits CREATE/RESCHEDULE without times and expects NOTED; K-6 will reject these for an enabled facility. The department test's allowed outcomes at `:119` omit DOCTORS_MATCHED. These tests are excluded from `make test-fast`, so that command alone cannot expose the incompatibility. Update them with owner-designated synthetic slot data and startup handling; executing them requires a separate live-test authorization, not this review.

`dev/bench.py:46` expects old department outcomes and does not require a slot GET for known-doctor/booking success. Add enabled/disabled scenarios that verify useful outcomes and observed slot reads before timing them; retain the designated-tenant write gate. The hard-coded 10:45 booking choice is not a generally valid live open block. Name lookup is still a sequential directory stage followed by parallel reads; RESCHEDULE is still lookup → parallel schedule reads → write. The 0.30-second adapter budget (`config.py:59`) is not a measured guarantee just because the extra read is parallel. Test concurrency, connection-pool contention, cancellation and the unchanged wall-clock deadline.

No new secret or endpoint configuration is needed for these two REST paths. If capability freshness settings are added, document their deployment defaults deliberately; do not create a user-configured slots-enabled flag. Update ContextForge's cached schema after an approved release, and coordinate voice handling of DOCTORS_MATCHED, ASK_WHICH_TIME, openSlots and actual slotTime before cutover. No need to involve Shobhit for the operational change.

### Nits and simpler alternatives

- **N-1:** C-1's signature is a design sketch, not implementation-ready: stale metadata and today-versus-future clock context must be carried as data. Prefer a small existing-facts-based input over more behaviour-switch booleans.
- **N-2:** Do not add a scheduling/capacity engine to stubs. Extend supplied response scenarios; keep auth, same-key replay and “failed reschedule leaves original unchanged” discipline. A repeated allocation algorithm would only test our implementation against itself.
- **N-3:** D-1 leaves the single-doctor SlotsNotRead result as a choice between a misleading AVAILABILITY fallback and an assertion. Resolve it in the plan: a violated retrieval invariant should not claim checked availability. Prefer the existing explicit failure envelope if a runtime error response is needed; no new tool or compatibility layer is required.
- **N-4:** Warming facility capabilities is a defensible latency choice, but a dedicated second cache/task framework is not automatically necessary. Decide one shared lifetime first and reuse existing cancellation/deadline patterns. The rejected always-read-slots alternative does cost an extra request on disabled facilities; the 21-assertion argument is not evidence for rejecting it.

## Check 3 — files and green-commit feasibility

The following filenames are concrete, not directory placeholders. Abbreviations used only in these lists:

- `src/` = `services/mcp/src/frontdesk_mcp/`
- `tests/` = `services/mcp/tests/`
- `dev/` = `services/mcp/dev/`
- `contracts/` = `docs/handover/mcp-only/contracts/`
- `VOICE` = `docs/handover/VOICE-TEAM.md`
- `PLAN` = `docs/handover/mcp-only/PLAN.md`

New snapshot names below are **proposed filenames**, not files created by this review. Hashes can live in the contract README and tests as today; no extra hash-file artifact is needed.

### Original phases: concrete footprints and conflicts

| Phase | Concrete file footprint | Assessment |
|---|---|---|
| 1 | `contracts/manoj-openapi-20261007.yaml`; `contracts/manoj-openapi-20261007.test-overlay.yaml`; `contracts/README.md`; `tests/test_contract.py`; `src/contract.py`; `src/booking.py`; `dev/frontdesk_stubs/ops.py`; `tests/test_booking.py`; VOICE | 9 listed files, but add omitted `tests/test_stubs.py` and root `README.md` for a complete migration: **11**, split below. No schema change is necessary for a detail-string-only definite SLOT_FULL mapping. |
| 2 | `src/contract.py`; `src/ops_client.py`; `src/schedule_reader.py`; `src/availability_policy.py`; `src/server.py`; `src/tools.py`; `dev/frontdesk_stubs/ops.py`; `tests/test_contract.py`; `tests/test_ops_client.py`; `tests/test_schedule_reader.py`; `tests/test_server.py`; `tests/harness.py` | **At least 12**, before settings, direct-service fixtures and failure-mapping files. Cannot certify green as one commit. B-1's lifecycle choice must be fixed first. |
| 3a | `src/availability_policy.py`; `src/availability.py`; `src/outcomes.py`; `tests/test_availability_policy.py`; `tests/test_availability.py` | 5 core files. To be green add `src/prompt.py`, `tests/contracts/mcp-tools.snapshot.json`, VOICE and `src/packs/healthcare.json`: **9**. Must include all reachable Decision consumers, not defer `_combine`/aggregate until 4. |
| 3b | `src/availability_policy.py`; `src/booking.py`; `src/outcomes.py`; `tests/test_availability_policy.py`; `tests/test_booking.py`; `tests/test_server.py` | 6 core/integration files. With prompt, snapshot, pack and VOICE in the same commit: **10**. As written, deferring those artifacts to 5 is red. More service tests can live in existing test_booking/test_server rather than another test file. |
| 4 | `src/availability_policy.py`; `src/schedule_reader.py`; `src/outcomes.py`; `tests/test_availability_policy.py`; `tests/test_schedule_reader.py`; `tests/test_availability.py` | 6 core files; prompt, snapshot, pack and VOICE bring it to **10**, if repeated publication is approved. However C-6 must move earlier if 3a emits its Decision. Operational bench/external updates require their own bounded follow-up. |
| 5 | `src/prompt.py`; `tests/contracts/mcp-tools.snapshot.json`; `src/packs/healthcare.json`; VOICE; `CLAUDE.md`; `docs/DECISIONS.md`; PLAN | **7**, but it cannot repair previously green commits retroactively. Move publication artifacts to the commits that change them. |

### Proposed split for a revised plan

These are proposed commit boundaries, not approval to build a new plan. “Green” here is a dependency analysis; future code has not been written or executed. The plan owner must resolve B-1 through B-5 before certifying enabled-slot behaviour.

1. **1a — pin and contract validation (7):** the two new `contracts/manoj-openapi-20261007*.yaml` files, `contracts/README.md`, `src/contract.py`, `tests/test_contract.py`, `tests/test_stubs.py`, root `README.md`. Update ErrorCode and all fixture/example consumers together. Old snapshots remain historical. No MCP schema change. Can be green independently.
2. **1b — definite SLOT_FULL mapping (4):** `src/booking.py`, `dev/frontdesk_stubs/ops.py`, `tests/test_booking.py`, VOICE. Script and test definite rejection versus retry uncertainty. Can be green independently after 1a.
3. **2a — typed transport and scripted fixtures (6):** `src/contract.py`, `src/ops_client.py`, `dev/frontdesk_stubs/ops.py`, `tests/test_contract.py`, `tests/test_ops_client.py`, `tests/test_stubs.py`. Keep sample slot/capability JSON in the stub module for this count; a separate data file would make 7. No retrieval activation yet, so existing service behaviour remains testable.
4. **2b — shared capability lifecycle (8):** `src/schedule_reader.py`, `src/tools.py`, `src/server.py`, `src/config.py`, `tests/test_settings.py`, `tests/test_schedule_reader.py`, `tests/test_server.py`, `tests/harness.py`. This assumes the revised plan chooses a shared reader-owned snapshot/task and explicit lifecycle exposure in Services. Establish lifecycle tests and request-boundary observation before enforcing capability-dependent service paths. If existing settings suffice, omit config.py/test_settings.py rather than adding unused settings. Schema construction stays offline.
5. **2c — direct-service fixture/startup coverage (8):** `tests/harness.py`, `tests/test_availability.py`, `tests/test_booking.py`, `tests/test_gate_assertions.py`, `tests/test_schedule_reader.py`, `tests/test_stubs.py`, `tests/test_settings.py`, `tests/test_external.py`. Migrate setup/teardown and direct Services/reader instances; preserve existing business assertions. Cold-capability tests remain explicitly cold. This is not a global request-log filter or production fallback.
6. **2d — retrieval facts and stage handling (8):** `src/availability_policy.py`, `src/schedule_reader.py`, `src/availability.py`, `src/booking.py`, `tests/test_schedule_reader.py`, `tests/test_availability.py`, `tests/test_booking.py`, `tests/test_server.py`. Wire slots/SlotsNotRead, failure stages and the shared match predicate, initially preserving legacy policy results until 3a. Test retrieval boundaries. This commit is **not a deployable slot-aware implementation**; hold the whole activation series.
7. **3a — single-doctor policy plus enum closure/publication (9):** `src/availability_policy.py`, `src/availability.py`, `src/outcomes.py`, `tests/test_availability_policy.py`, `tests/test_availability.py`, `src/prompt.py`, `tests/contracts/mcp-tools.snapshot.json`, `src/packs/healthcare.json`, VOICE. Move C-6's pure combination/aggregation/ranking here so the new Decision is safe everywhere. If retaining one version bump, explicitly approve publishing the complete final optional slot/appointment fields and enum surface here, including TimeRequired's next step, and keep that surface identical afterwards. Otherwise use a version bump and synchronized artifacts for each later schema change. Both alternatives revise the original phase-5-only rule.
8. **3b — booking propagation (up to 10):** `src/availability_policy.py`, `src/booking.py`, `src/outcomes.py`, `tests/test_availability_policy.py`, `tests/test_booking.py`, `tests/test_server.py`, plus `src/prompt.py`, `tests/contracts/mcp-tools.snapshot.json`, `src/packs/healthcare.json`, VOICE **if** this commit changes the published surface. With an approved complete 3a surface, those last four files should not change. Cover `_written`, bypass handling and response time evidence as well as the gate.
9. **4a — department integration and bounds (4):** `src/schedule_reader.py`, `tests/test_schedule_reader.py`, `tests/test_availability.py`, `tests/test_stubs.py`. C-6's policy consumers and public output already land in 3a; finish/verify retrieval propagation and match-count bounds here. Avoid adding a second match rule. If fully implemented earlier, make this a targeted test/verification commit, not duplicate production code.
10. **4b — operational verification consumers (6):** `tests/test_external.py`, `tests/test_external_transport.py`, `dev/bench.py`, `tests/test_bench.py`, `dev/demo.py`, `tests/test_e2e_processes.py`. Update only consumers whose enabled-slot expectations/journeys need it; use selected fixture slots, no slot engine and no unapproved live execution. Retain the unchanged legacy demo path where applicable. This separate budget prevents phase 4 exceeding ten files.
11. **5 — final rules and release documentation (3):** `CLAUDE.md`, `docs/DECISIONS.md`, PLAN. Current schema, descriptions and VOICE tables must already agree. Add capability-settings deployment documentation in this commit if settings were actually introduced; choose exact files in the revised plan (still room within ten). Run full tests/builds and schema comparison on the integrated tree before separately seeking merge/deploy authorization.

The one-version option deliberately exposes the final schema before all runtime behaviour is implemented in the local series. If that temporary mismatch is unacceptable, prefer multiple honest schema-version bumps with artifacts updated in each commit. Do not claim the original sequence satisfies both requirements unchanged. No intermediate capability-enabled deployment is safe merely because the disabled-slot fixtures pass.

## Verification performed and limits

Read the listed production modules, stub routes/state, relevant tests, current interface docs/pack and supplied live captures. Used repository-wide searches plus Python AST enumeration for constructors/callers and request assertions. Executed only in-memory/local-fixture probes, including the missing capability route, new Decision dictionary lookup, mixed-session combination and public-contract parsing. No production file or test was patched to perform these probes.

Baseline command (from `services/mcp`):

```sh
uv run pytest tests/test_contract.py tests/test_availability_policy.py tests/test_schedule_reader.py tests/test_booking.py tests/test_server.py::test_tool_schemas_match_the_pinned_snapshot tests/test_server.py::test_interface_parameter_and_output_tables_match_pinned_schema tests/test_server.py::test_interface_describes_every_outcome_and_next_step -q -p no:cacheprovider
```

Actual result:

```text
........................................................................ [ 36%]
........................................................................ [ 73%]
.....................................................                    [100%]
197 passed, 2 warnings in 4.31s
```

Warnings are the existing Authlib deprecations. This establishes the current baseline, not the correctness of unimplemented slots. Full-suite/Docker/production latency/live-owner/ContextForge/voice tests were not run for this report-only review. G-11/G-12/G-13 remain the supplied open owner questions; no new owner response is assumed. Most required corrections are plan-owner decisions, not reasons to call Manoj's live API now.

**Hand-back:** return this report to the plan author. Resolve B-1 lifecycle, B-2 evidence/precedence, B-3 department combination, B-4 booking precedence/types, B-5 formatting/provenance and B-6 green phasing; incorporate the concrete omissions S-1–S-4. Preserve the agreed UNKNOWN callback, NOTED-only confirmation, accepted B-1 bypass and owner-computed capacity boundaries.
