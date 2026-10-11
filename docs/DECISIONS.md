# Decisions

Architecture decisions for the adapter are the A-series in `docs/architecture/TARGET.md`; the
migration decisions are in `docs/handover/mcp-only/PLAN.md`. This file records library choices.
The D-series of the retired backend (FastAPI/SQLAlchemy/Alembic, resolver, slot uniqueness) is in Git
history before the MCP-only migration (October 2026) and no longer applies.

## Libraries

| Library (pinned) | Used for | Why this one | Fallback |
|---|---|---|---|
| fastmcp 2.14.7, mcp 1.30.0 | MCP server: tools and streamable HTTP | Matches the adapter stack; ASGI bearer authentication covers all tools | The `mcp` SDK's FastMCP directly |
| starlette 1.7.0, uvicorn 0.53.0 | ASGI assembly (/health, /ready, /dependencies, bearer middleware) | FastMCP's own base | — |
| httpx 0.28.1 | Pooled async clients to both owner services; MockTransport/ASGITransport at the boundary in tests | Explicit timeouts, per-request deadline caps, transport injection | aiohttp |
| pydantic 2.13.5, pydantic-settings 2.15.0 | Contract types, result envelopes, settings with production guards | Shared with FastMCP; output schemas come from the models | — |
| pytest 9.1.1, pytest-asyncio 1.4.0, pyyaml 6.0.3, jsonschema 4.26.0, ruff 0.16.9 (dev) | Tests (contract overlay parsing, stub responses validated against the OpenAPI schemas), lint | Standard | — |

Not adopted: an OpenAPI client generator (the public interface is small and the types double as
validation), a database or queue in the adapter (the platform owns durable finalization), any
NLP/interpretation library (deferred; owners decide meaning).

## K1 — Explicit knowledge tool; scheduling depends only on Manoj (2 October 2026)

Context: a routine availability call could fail before reading usable operational data because a
transcript header or the separate knowledge provider was missing. MCP sees tool calls, not every
conversation turn, so that gate did not provide conversation-wide emergency protection.

Decision: the user approved removal of all knowledge gates from availability and booking, including
optional checks on booking reasons. The LLM chooses search_knowledge for hospital questions and
symptom-to-department queries. That tool makes one owner request with verbatim question and language.
reasonVerbatim remains an optional operational payload field; it is not interpreted here. Scheduling
works with knowledge unconfigured. No local knowledge fallback or classifier is added.

Rejected alternatives: keep the mandatory gate (coupled outages and incomplete turn coverage), move
transcripts through headers (wrong layer and mutable-client/concurrency risk), or hide the gate behind
a feature flag/optional reason check (two paths and the same service coupling).

Consequences: remove obsolete context/client/fixture paths together; version tool descriptions and
schemas. Trusted identity, confirmation, live-board UNKNOWN handling, idempotency and uncertain-write
reporting remain adapter invariants. The knowledge contract remains provisional until owner acceptance.
MCP does not observe every conversation turn; voice behaviour and application acceptance are external
responsibilities, now explicitly separated by K2 below.

### K1 correction review — 3 October 2026

The single-request knowledge boundary now validates the decision before optional metadata. A valid
emergency/desk transfer survives malformed optional fields; those fields are dropped with a
field-name-only event. Other malformed responses fail explicitly. Require JSON and bounded owner strings.
Routing speech appears only in routing.speak, while answers and clarification use answer.text; the
tool contract describes the result codes. Schema at that review was 2026-10-03.3; date validation is unchanged.

Scheduling-only configuration means both knowledge URL and bearer are empty; partial production
configuration is rejected. Deployment supplies its expected knowledge state to smoke and removes an
obsolete app secret reference only after removing the environment reference. These paths have offline
tests; no cloud change was performed in the correction pass.

## K2 — MCP publishes only the tool contract (3 October 2026)

Decision: MCP publishes only the tool contract: endpoint/transport, authentication scopes, trusted
headers, parameters, output fields and outcome/nextStep meanings. The single interface document is
[VOICE-TEAM.md](handover/VOICE-TEAM.md), checked against the pinned schema. The server retains short,
neutral contract metadata, not conversational rules.

Voice-agent behaviour, prompts, guardrails and LiveKit wiring belong to the voice team. The separate
voice-design document and instruction-export command are retired. This supersedes K1's earlier
voice-guidance deliverable; it does not reintroduce knowledge checks inside scheduling.

Tool implementations, field names, validation, status mappings and response defaults stay compatible,
including existing callback text fields. Date accepts today or YYYY-MM-DD; other relative dates remain
unsupported. This text change does not decide future date interpretation. Clinical/application design,
voice implementation and their acceptance remain outside this repository; no owner consent or deployed
behaviour is asserted by publishing this contract.

## S1 — One LLM-called summary of the whole call (4 October 2026)

Context: the previous summary interface required a separate call-end credential and composed callback
fields into text. The approved interface now makes all four tools available to the model through one
gateway bearer; the separate summary principal, gate and token configuration are removed.

Decision: summaryText is required, nonblank and at most 500 characters, sent exactly as written.
It holds the whole conversation, including relevant names, callback details, symptoms, doctor,
department and requested date/time. No separate callerName or requestedDate summary arguments remain.
The other seven arguments mirror Manoj's fields; language maps en/kn/hi to EN/KN/HI. Trusted call ID and
start time come only from headers. No duration is sent. CALLBACK_NOTED requires a valid callback
mobile and excludes appointment/transfer fields; it creates no appointment or callback task.

The result contains only outcome, plus fields for INVALID_REQUEST: SAVED (verified 201), ALREADY_SAVED
(verified 200 for our call ID), INVALID_REQUEST, NOT_CONFIRMED, or NOT_SAVED. Both success responses
must parse as CallSummary and belong to our call. An existing summary is final even when a repeat
request differs. There is no Idempotency-Key on summaries; Manoj's call-ID deduplication is authoritative.
Booking key semantics remain unchanged. One same-body retry after an unanswered send remains bounded
by the summary deadline. All writes retain 401-only token refresh; definite 403 is not retried.

The advertised maxLength is 500, set once after tool registration. The existing outer argument cap
remains 2000 so 501–2000 characters reach service validation and return in-band INVALID_REQUEST.
There is no custom validation boundary. After explicit user approval, summary framework validation
errors receive a fixed, input-free protocol message. This is error presentation only: the framework
still validates the same arguments with the same limits. No error values, locations (which may be
untrusted argument names), context or raw exception are copied or logged. Other tools are unchanged.
HTTP tests cover wrong types, oversize text, enums and unexpected argument names; no upstream write
occurs for these invalid requests. The schema stays 2026-10-04.2 because inputs/outputs are unchanged.

Rejected: a second bearer/access path, server text composition or trimming, a parallel retry engine,
and 403-triggered token refresh. Summary work retains its own default 8-second deadline; its availability
to the LLM does not make it a 300 ms operation. Voice timing/tool selection and a final whole-call
payload belong to the consuming application. No database, queue or provider fallback is added.

Consequences: breaking tool schema and access change, requiring coordinated MCP/gateway/voice refresh.
Schema bumps: 2026-10-03.3 → 2026-10-04.1 for summary request/result, then → 2026-10-04.2 for gateway
access metadata. Live verification still requires calls.write and an owner-designated synthetic tenant.
The old deployment secret remains untouched until separately authorized retirement.

## A12 — Date-aware schedule facts and bounded profile reads (5 October 2026)

Context: applying an UNKNOWN future board blocked requests even when a doctor had a usual schedule.
Approved revision 6 separates today, future dates and WORKING_HOURS in one pure policy and one reader.
Today uses only live-board status/times; future and hours queries never fetch the board. ON_CALL is
always callback. No capacity, slot allocation, end time or confirmed attendance is inferred.
Owner `status` is preserved; our `decision` and `reason` explain the result. Same-decision sessions
permit a day-level request; differing decisions need selection. CREATE requires a doctor; RESCHEDULE
uses the verified caller's appointment doctor. A bookable session with unknown end time and a specific
requested time requires handoff, not a write. Callback stores only a call summary.

Future department profiles are read in sorted sequential batches, concurrent only within each batch,
under one deadline. Defaults: limit 3, batch 3, minimum headroom 0.05 s, existing cache 300 s. Results
separate directory total, bookable found and completeness; incomplete absence is never unavailability.
Rejected: future board gating, inferring missing sessions from profiles today, department writes,
unbounded profile fan-out, parallel policy paths and conversational scripts in responses.

Consequences: breaking schema 2026-10-05.1 needs gateway/voice refresh; unchanged owner API and scopes.
Owner usual schedules must be populated. ON_CALL and today-only board use are explicit consumer policy
choices, not revisions to Manoj's published contract. The owner still validates writes. LIST/CANCEL,
trusted identity, operation keys, uncertainty, 401-only refresh and summary behavior are unchanged.
Summary text can contain callback name/date/session/reason, but these details are not enforced;
summary quality needs acceptance when the voice agent is integrated. Live latency and output-schema
propagation are separate post-deploy acceptance, not established by local fixtures.

## A13 — Availability review corrections (6 October 2026)

Future sessions are classified by their own weekdays, independently of a failed requested-session
selection. The doctor-level refusal stays SESSION_NOT_USUAL; same-day sessions remain offerable
alternatives, other-day sessions are NOT_USUAL_DAY. Booking preserves that doctor-level refusal.
Session matching for future dates considers the requested weekday, not merely a matching label.

When the doctor is unavailable for the whole requested scope, booking reports the doctor's own reason (CANCELLED, SESSION_ENDED, NOT_USUAL_DAY or SESSION_NOT_USUAL), even when a preferred time was given; TIME_OUTSIDE_SESSION applies only when the doctor has bookable sessions and the chosen time falls outside them.

Garima reconfirmed that ON_CALL always means callback, including single-doctor WORKING_HOURS.
Single-doctor empty schedules also use the full callback result. Normal hours return a neutral
PRESENT_WORKING_HOURS next step; all WORKING_HOURS results have bookableFound=0. Internal search matches
still stop bounded schedule batches. Department hours keep on-call doctors as facts within the cap.
The policy selects eligible result candidates; ranking only orders/caps them. No second policy or
lookup path is introduced. An already identified on-call doctor's name query needs no board read.

Schema 2026-10-06.1 adds PRESENT_WORKING_HOURS and replaces NO_REGULAR_HOURS (emitted in schema
2026-10-05.1 for on-call working hours) with ON_CALL_DOCTOR. Inputs and credentials are unchanged.
A gateway already on 2026-10-05.1 therefore
needs explicit discovery refresh and a manual output-schema comparison; input drift cannot prove it.

Known limitation, confirmed by Garima: **sessions crossing midnight are unsupported**. This pass
adds no overnight interpretation or defensive time rule. G-1 (whether cancelled/ended sessions
should force a choice) remains pending; the approved mixed-decision rule is unchanged. Optional M-7
(showing other board facts when a named today session is absent) is not implemented without approval.

## A14 — Booking window and actionable rejection fields (6 October 2026)

Today's booking window starts at the later of the session start and facility now (strict, minute precision); future usual schedules and unknown-boundary handoffs are unchanged.

Booking rejection fields are tool argument names only: owner names are translated using the originating action's owner-field mapping (also used for write bodies), and names without a tool argument for that action are dropped.

## SL1 — Slot-aware availability and booking (9 October 2026)

Context: Manoj's 0.4.0-draft contract supplies per-doctor/date slot blocks and capacity facts.
The [pinned contract](handover/mcp-only/contracts/manoj-openapi-20261007.yaml) has SHA-256
`d3e93f45498fb86feeb5bb93c0adaba7cff47b48daa21ac810790b5483e96c80` (K-4).
The adapter consumes those facts; it does not implement the owner's scheduling engine.
The [slots plan](handover/mcp-only/implementation/SLOTS-PLAN.md) records the approved rules and reviews.

Decision:

- **K-1:** consume owner capacity, never compute it. NOT_CONFIRMED can permit a request with an open bookable block; future AVAILABILITY also reads slots.
- **K-2:** today's block is bookable only until its end; a block that has started but not ended can remain open.
- **K-3:** slot-enabled department searches report matching doctors (`DOCTORS_MATCHED`, `bookableFound=0`), not verified slot availability. Slots are checked after a doctor is selected.
- **K-4:** pin the served contract by hash, with the separately hashed quoting-only overlay; a version label alone is insufficient.
- **K-5:** owner blocks already reflect TIME_WINDOW (G-9); do not intersect them with a locally reconstructed board window.
- **K-6 / D-2:** slot-enabled CREATE/RESCHEDULE require `preferredTime`/`newPreferredTime`; absence gives `INVALID_REQUEST/ASK_WHICH_TIME`, no write. Optional nonblank `session` must match the containing session's normalized label; an unlabelled session cannot satisfy a name. Never forward `session` to Manoj.
- **K-7 / D-3:** accept the owner's returned block start in `slotTime`. `slotMoved` is true only when that returned time differs from the start of the block containing the chosen time. Choosing 10:45 and receiving 10:30 is not a move. Every appointment object exposes nullable `slotTime` and `slotMoved=false` by default; LIST/CANCEL keep false.
- **K-8:** unreadable slots/capabilities refuse booking and mean `COULD_NOT_CHECK`/`COULD_NOT_RECORD`, never unavailability. Existing authentication failure precedence remains.
- **D-1:** publish the complete schema once (3a-1); freeze `2026-10-08.1` for the rest of the series. Completing the series does not authorise deployment.
- **D-4:** a slot-only session can be offered when it has an open bookable block; future usual-session output marks it `oneDay`, not regular hours (today uses live-board facts). Keep refusal facts even when it cannot be offered.
- **D-5:** selected-doctor AVAILABILITY always reads slots alongside existing reads; `SlotPlan.enabled` decides applicability. Only department AVAILABILITY uses cached capabilities, with no slots fan-out or capability startup/background process. WORKING_HOURS reads neither board nor slots.
- **D-6:** ordinary UNKNOWN in a session that could be the caller's target always means callback, even against CANCELLED. Passed or out-of-hours times remain refused; callback cannot make them bookable.
- **D-7:** a session's label is evidence. Time-matched sessions and unlabelled unresolved rows remain in scope; if none matches, unknown-hour rows remain as the existing fallback. A labelled UNKNOWN for a different selected session does not block it.
- **D-8, on-call AVAILABILITY:** confirmed IN/LATE plus either a usable window (both bounds, not ended) or an open bookable block follows ordinary policy. CANCELLED is unavailable; otherwise `HANDOFF_REQUIRED/TRANSFER_DESK`, reason `ON_CALL_DOCTOR`, never callback. Usual schedules cannot establish an on-call doctor's availability.
- **D-8, single-doctor on-call WORKING_HOURS:** always `HANDOFF_REQUIRED/TRANSFER_DESK`, reason `ON_CALL_DOCTOR`, because no confirmation data is read. Empty regular schedules retain callback; normal hours use `PRESENT_WORKING_HOURS` and hours-only queries have `bookableFound=0`.

This entry supersedes A12's and A13's 'ON_CALL is always callback', including single-doctor WORKING_HOURS (D-8).
Garima accepted the latency consequence on 8 October: an on-call doctor resolved by name needs one
extra read group for AVAILABILITY (today board ∥ slots; future profile ∥ slots).

Garima's 9 October decisions:

- Release smoke accepts `HANDOFF_REQUIRED` from either department probe of `get_doctor_availability` (AVAILABILITY and WORKING_HOURS) only for a valid response with `detail=ON_CALL_DOCTOR`, `complete` exactly true and `nextStep=TRANSFER_DESK`. Other handoffs, including `SEARCH_INCOMPLETE`, and unexpected failures fail; the other approved smoke outcomes remain unchanged.
- Hermetic process and journey tests (in-process/local stubs) use fixed future dates and normal daytime slots, never wall-clock, overnight or all-day windows. Overnight appointments remain unsupported (A13). Read-only smoke may query today; authorised live external journeys use owner-designated dates.

Test infrastructure: T-1 to T-4 isolated sse-starlette's process-wide shutdown flag: a first test
server can leave it set and cut off the second server's event-stream replies. The mechanism was
confirmed in 20/20 runs, with a clean comparison in 20/20. Use one `serving()` server per process
or separate processes. Source analysis found no single-server production risk **for this mechanism
and execution model only**; the cause of the old intermittent freeze remains unproven.
The recorder fails incomplete HTTP responses; whether this strictness stays permanently is open
for Garima. An optional test-setup remedy remains separate.

Rejected: startup/background capabilities and flag parameters (unnecessary lifecycle or duplicate
facts); a separate booking matrix (duplicates policy and loses scope protections); department slot
fan-out (voice latency); relying only on owner write rejection (no offerable facts or local guards);
board-window/block intersection (G-9); CANCELLED over UNKNOWN or dropping one-day refusal rows
(loses refusal evidence); callbacks for every out-of-hours time or every other labelled stale session
(ignores the selected scope, D-6/D-7); policy-level malformed-data failures (reader responsibility);
a new blank-session module (existing shared module suffices); multiple schema publications and
forwarding `session` (D-1/D-2).

Consequences: the voice team must handle `DOCTORS_MATCHED`, `ASK_WHICH_TIME`, `openSlots`, `oneDay`,
`slotTime`, `slotMoved` and `HANDOFF_REQUIRED/ON_CALL_DOCTOR`, and use the returned appointment time.
The gateway/ContextForge and voice consumer need schema refresh. Owner write APIs and their scopes
are unchanged; new reads consume the pinned contract rather than revising the owner's API.
Phases 1a–4b are built and reviewed. Phase 5 completes the documentation only once approved;
**nothing in the slots series has been merged or deployed**. Deployment readiness is separate:
all [pre-deployment gates](handover/mcp-only/PLAN.md#slots-series-status-and-pre-deployment-gates-9-october-2026)
remain pending, including LOG-1 (fastmcp's own console handler bypasses JSON logging/privacy;
Garima's handling decision is open).

Open with Manoj, already designed around:

- **G-13:** a time exactly at session end belongs to no block and is refused.
- **G-14:** overlapping blocks across sessions or duplicate normalized session labels are malformed data: could not check/record.
- **G-15:** mixed labelled/unlabelled rows retain unlabelled refusals in booking scope under D-7; revisit only if owner clarification requires it.

Optional, not a blocker: 4b-M1 review O-1 notes that the process test does not assert a distinct
RESCHEDULE operation ID; its stub does not record idempotency keys. No change is required here.
Owner questions, recorder permanence, the optional T-4 setup remedy and O-1 are not deployment
gates unless Garima decides otherwise.

**SL1 supplement — 10 October 2026 (T-5).** The test-setup remedy for the T-4 mechanism is implemented
(`151ea61`): `serving()` resets sse-starlette's process-wide drain flag at the start of every test server,
proven by a subprocess regression test. It is no longer an open item. The SL1 lines above that call it
optional or separate are historical. Recorder strictness permanence remains open for Garima.

## L1 — 10 October 2026: one logging boundary for private data (LOG-1)

Garima approved LOG-1 revision 4 and retained `callId` and `summaryId` for correlation.
The local probe demonstrated two leaks: malformed MCP JSON-RPC validation echoed fake input into
root JSON logs, and an unexpected tool exception exposed fake private values through FastMCP's
independent Rich traceback on stderr. Unexpected exception messages also reached tool results.
Raising levels would not fix either log leak because both occur at WARNING or ERROR.

Implemented: `configure_logging` removes FastMCP's own handlers and propagates through the single
root JSON handler. `JsonFormatter` never interpolates arguments. Libraries/root keep only exact
approved unfilled templates, otherwise `library_message_omitted`; their extra fields are ignored.
Adapter fields use one 19-name table, with exact internal code/class sets built once from their
producers, primitive bounds and existing ID syntax checks. Unknown names or rejected values are
omitted, with names only in `omittedFields`. Dynamic owner path IDs become route templates; unknown
or query-bearing paths are omitted. Error records with `exc_info` keep only exception type and up to
10 file/line/function frames, never messages, locals, arguments or source lines. `mask_error_details=True`
hides unexpected tool-error text; deliberate ToolError and summary-validation responses are preserved.
Provider remains configuration data; syntax-checked `callId`/`summaryId` remain visible by design.

Rejected: a field-name denylist (new fields would escape); regex redaction of free text (unreliable);
higher logger levels (the demonstrated leaks survive); environment-only FastMCP suppression (leaves
root validation leakage); per-logger filters (scattered coverage); patching libraries (not this adapter's
boundary). No new calls, waits, locks, background work or success-path log events were introduced.

Evidence: 1,297 hermetic tests and five process e2e tests passed; wheel/source distribution and both
Docker images built. The original probe now contains zero fake private values on stdout and stderr.
LOG-1 does not change the published schema. WARNING and INFO fixture benchmarks
ran once before and once after, 50 samples per scenario, concurrency 1, both slot modes: 750/750
verified outcomes in each run, no material p50 regression (>10% and >1 ms). WARNING p50 deltas were
−0.1 to −1.2 ms; INFO −0.5 to −1.3 ms. Different host load means these small improvements are not
attributed to the change. INFO produced 752 `tool_result` entries before and after; `summary_saved`
was zero in both (not in that workload). Lifecycle strings now retain placeholders, with identical
event counts. These are local fixture timings, not real-service or voice latency evidence.

Remaining risks: lost library prose; template changes on dependency upgrades; future fields/codes/routes
requiring source-set updates; retained correlation IDs can carry syntax-valid sensitive content;
trusted adapter event names/logger names/provider remain code or configuration responsibility.
FastMCP's import-time handlers exist until application logging is configured, before serving requests.
Production container logs, live services, ContextForge and end-to-end voice latency remain unverified.

This entry supersedes the historical SL1 statement that LOG-1 handling is undecided. Gate 7 is
**implemented (LOG-1); awaiting review and Garima's closure**, not closed. Nothing is pushed, merged
or deployed by this work. Full commands, failures, test-scaffolding correction, benchmark tables and
protected-file hashes: [LOG-1 hand-back](handover/mcp-only/implementation/LOG-1-HAND-BACK.md).

## K3 — Three-tool front-desk adapter (11 October 2026)

Garima approved removal of Shobhit's `search_knowledge` from our front-desk adapter. K3 supersedes
K1's knowledge-tool decision. The tools are `get_doctor_availability`, `manage_booking` and
`record_call_summary`, all using the existing gateway bearer and Manoj's operational API.
Knowledge, symptom routing and emergency decisions belong to the LiveKit voice team through
Stratum's separate ContextForge registration; this repository neither modifies nor verifies it.

The three-tool rule applies to our adapter, registration `frontdesk-healthcare-canary` and virtual
server `frontdesk-healthcare`. A combined voice view may also contain Stratum's tools.
Rajeev's team must validate symptom/emergency journeys and transfers before deployment (gate 8).
No live voice traffic until the adapter, our gateway entries and LiveKit cache are refreshed and
voice-client discovery proves the intended front-desk surface (gate 9).

LOG-1 revision 6 removes only the deleted tool's permitted values: L1 now has 18 field names and
11 operational route templates. Existing privacy/masking and M-1 rules remain; gate 7 awaits
review and Garima's closure. Summary values including EMERGENCY, SYMPTOM_ROUTING and
EMERGENCY_TRANSFERRED remain unchanged. Scheduling, authorization and write semantics are unchanged.

Source schema is `2026-10-11.1`. Fixture checks do not prove deployment or voice safety.
Merge, deployment, our ContextForge refresh, voice acceptance and later removal of leftover cloud
settings/secrets require separate approval. Governing detail: [removal plan](handover/mcp-only/implementation/KNOWLEDGE-REMOVAL-PLAN.md)
and [LOG-1 revision 6](handover/mcp-only/implementation/LOG-1-PLAN.md).
