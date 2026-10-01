# Opus review of the MCP integration plan

Historical review, followed by its disposition. The original review below predates the revisions in [PLAN.md](PLAN.md); its input line references and old local filenames identify the reviewed revision, not files required by this handover. Opus has not re-reviewed the revised plan.

Review completed through the local Claude CLI using `--model opus`. CLI-reported model: `claude-opus-5-5`. Result: successful, one review turn, tools disabled. Recorded at 2026-09-30T12:23:49.877613+00:00. This is one independent reviewer, not a multi-reviewer consensus.

Current revised plan: [PLAN.md](PLAN.md). The reviewer received the earlier plan, the published contract snapshot, selected MCP/gateway/deployment source and the historical retirement inventory. The review used the GSD cross-AI review workflow with an explicit Opus selection and disabled tools. All 12 input files matched their pre-review hashes at review completion. The original review text is preserved below; local CLI transcripts, prompt bundles and run logs are intentionally excluded. They are not needed to implement the revised plan. No service-owner agreement or production validation is implied by the review.

**Verdict and findings**

Opus says **READY WITH CHANGES for implementation task planning; NOT READY for production**. It raised 11 findings: 3 HIGH, 5 MEDIUM and 3 LOW. The core architecture and four-tool mapping are supported; the review does not require a slot endpoint or advanced language interpretation before starting.

The main proposed amendments are: define future/unknown board behavior; make trusted caller authorization explicit; specify how original utterances reach Shobhit without relying on the model to choose a safety tool; define mutation identity/deadlines/uncertain outcomes; finalize call summaries through a reliable call-end mechanism; and make the current plan self-contained for retirement, rollback and acceptance checks.

**Our assessment of the recommendations**

These notes distinguish actionable findings from reviewer assumptions. At the user's subsequent request, the actionable recommendations were incorporated into the current plan with these qualifications and the callback-only UNKNOWN decision. The plan's “Opus recommendation disposition” table maps all 11 findings to the revisions. This is not a second Opus review; the original response below remains unchanged.

| Finding | Assessment and adjustment |
|---|---|
| OPUS-01: future and unknown boards | Valid policy gap. The claim that almost all future boards will be UNKNOWN is an inference, not measured behavior. The draft explicitly calls for handoff on UNKNOWN, so allowing requests in that state needs a deliberate product/contract decision. Do not adopt “board state never blocks create” as an established rule. Cancellation and on-call handling require their own accurate wording. |
| OPUS-02: caller identity | Valid. Separate patient contact from authorization for list/cancel/reschedule, reject model-supplied identity overrides, validate number normalization and define family handling. A trusted caller-number header is channel metadata, not universally proof of possession; the platform's accepted verification level and Manoj's consumer trust boundary still need agreement. |
| OPUS-03: safety enforcement | Valid design gap. Specify a deterministic orchestration gate using Shobhit decisions and trusted original utterance context. Read-only directory/board calls can overlap a knowledge check where appropriate; an appointment mutation must wait for the applicable safety decision and caller confirmation. Do not parallelize creation with the safety check or copy detection logic into MCP. |
| OPUS-04: mutation identity and uncertainty | Valid, but a hash of each new body alone is insufficient: rephrasing after a lost successful response can produce a new key and duplicate request. Use a stable logical operation identity and frozen payload for retries; define deliberate correction/replacement separately. A list lookup does not always uniquely reconcile a lost write response. Preserve deadline-aware retries, schema validation and explicit uncertain results. |
| OPUS-05: call summaries | Valid. Keep four MCP tools but distinguish the call-end tool's lifecycle access from ordinary conversational tool selection. Verify actual gateway/platform filtering capabilities. Freeze the final payload for retry. Do not label every abrupt disconnect ABANDONED if a completed appointment/action already determines the outcome. No new persistence engine belongs in MCP. |
| OPUS-06: latency and tool shape | Useful clarification: directory search and profile/board composition belong inside one get_doctor_availability invocation; a genuine caller clarification is a separate turn. The plan already specifies four tools, not separate model-facing search/profile tools. Carry the prior budget into the current plan; the suggested 300 ms MCP budget is a proposal, not measured evidence. |
| OPUS-07: OAuth, readiness and URL paths | Valid. Refresh tokens with bounded single-flight handling and remaining-deadline checks; distinguish local readiness from independent downstream status. Do not require external token acquisition for every readiness probe or unintentionally couple knowledge and operations availability. Test mock and backend base paths. |
| OPUS-08: clock and data approval | Valid. Configure facility timezone and deterministic test clock; qualify unconfirmed profile data and prevent false session-expiry claims. Handle date as well as local time, and do not treat a past-date entry as current. |
| OPUS-09: prompt and gateway migration | Valid. Explicitly refresh schemas/instructions and remove slot wording. CONFIRMED_BY_DESK means the desk acted; it still does not establish a guaranteed appointment time under this contract. Production smoke remains read-only. |
| OPUS-10: contract fixes and stubs | Valid. Prefer an owner-published corrected contract; if a temporary local quoting-only overlay is used for tests, keep the downloaded source untouched, label/hash the overlay and separate behavioral assumptions. A stub's passing tests are not evidence that the real service matches those assumptions. |
| OPUS-11: plan completeness | Valid. Bring the applicable retirement inventory, rollback and acceptance checks into the current plan, removing superseded interpretation and knowledge-outage assumptions. Coordinate tests/CI changes with the integration migration so “MCP-only” is actually demonstrated. |

**Incorporation status**

Completed in the current plan: consumer-side authorization boundaries, mandatory internal routing orchestration, mutation replay/uncertainty, total deadlines and latency budget, call-summary finalization, timezone, gateway refresh, inline removal inventory, rollback and acceptance checks. The user's four-tool scope and UNKNOWN callback-only rule are preserved. External service agreements remain explicitly separate from adapter implementation decisions and labelled development fixtures. No production code was implemented.

**Subsequent user decision — UNKNOWN policy resolved:** ask the caller's name and number, tell them someone will call back, and save only a call summary with CALLBACK_NOTED. No appointment, transfer or other action. The current integration plan now records this policy for today and future dates. This supersedes the first business question and the alternative UNKNOWN policies proposed in the original review below; the original Opus response is preserved unchanged for provenance.

**Unmodified Opus review follows**

# Independent review: MCP-only integration plan (`.context/MCP-INTEGRATION-PLAN-CURRENT.md`)

**Basis.** This review covers only the supplied plan, the published contract snapshot, the listed source files and the historical inventory. I inspected, ran and contacted nothing else. Items labelled *Proposal* or *Assumption* are mine, not facts from the evidence.

---

## 1. Summary and verdict

**Verdict: READY WITH CHANGES** to break into implementation tasks. **NOT READY** for production.

The plan follows the user's decisions closely:
- MCP-only ownership.
- Four tools.
- A profile plus board overlay.
- No slots or synthetic capacity.
- NOTED wording.
- No interpretation endpoint as a prerequisite.
- Call summaries through MCP outside the response path.

It also correctly avoids treating the Prism mock as proof of a backend.

Four gaps would cause implementers to build the wrong thing, or to build a safety or privacy hole:

1. **Future dates.** Under the contract's staleness rule, future-date boards will almost always read `UNKNOWN`. The plan's `UNKNOWN` → desk-handoff rule would then send most booking journeys to the desk.
2. **Identity.** The new contract's `mobile`/`callerMobile` is whatever MCP sends. Unless MCP binds it to trusted caller ID, list, cancel and reschedule become disclosure and mutation paths.
3. **Safety routing.** The plan says an LLM-chosen tool is not a sufficient safety gate. Its own sequence diagram still makes the knowledge check optional and agent-initiated.
4. **Write semantics.** The current idempotency key, retry and failure envelope don't match the new contract or the "uncertain" wording, and they break the one-second budget.

Production additionally depends on external gates:
- Shobhit's contract.
- A real Manoj host (currently a placeholder).
- Fixes to the schema defects.
- Measured end-to-end latency.

---

## 2. Strengths

- **Precise board semantics.** Board status overrides routine hours (plan L49, L55). Sessions stay distinct and cancelled or unknown rows stay visible. `delayMinutes` is not double-applied and end times are not inferred. This matches contract L262–268 and L1053–1059.
- **Honest write outcomes.** NOTED means "recorded, not reserved", and a timeout is reported as uncertain (L22, L51). This matches contract L9–10 and L381.
- **Call-summary first-write-wins is recognised.** The plan concludes "don't post a provisional summary" (L130), which follows from contract L609–611.
- **Correct token model.** Registration-granted scopes, `scope` ignored, token cached on `expires_in`, and staff auth kept away from tools (L42).
- **Base-path difference called out.** The plan names the `/api/v1` vs no-prefix difference between mock and backend (L33–39, L107).
- **Explicit dependency chain in the latency plan.** Search → parallel profile and board reads (L167), not a single-hop assumption.
- **Scope discipline.** The plan explicitly refuses to rebuild scheduling rules, interpretation or a knowledge engine (L53, L157).

---

## 3. Findings

### HIGH

#### OPUS-01 — Future-date boards will be `UNKNOWN`, and the plan routes `UNKNOWN` to the desk

- **Evidence.**
  - Contract L258–260: a stale or missing entry returns `UNKNOWN` and "the consumer's behaviour is to hand the caller to a person".
  - Contract L1069–1070: staleness means `lastUpdatedAt` is older than the tenant threshold (default 4 h).
  - Contract L264–268: pre-filled entries stay `NOT_CONFIRMED`.
  - Plan L49: "NOT_CONFIRMED/UNKNOWN must remain unconfirmed/unknown … with the uncertainty and desk handoff."
- **Failure scenario.** A caller asks for Dr X next Tuesday. Nobody has touched that board entry within the last 4 hours, or no entry exists yet. `getAvailability` returns `UNKNOWN`. Applying the plan literally, the agent hands off to the desk. That defeats the user's core journey: working hours → preferred time → NOTED request. It would happen for nearly every non-today request, including the "physician tomorrow" case at L92.
  - Missing-entry shape is also unspecified. The example at contract L328–335 has no `session`, so a multi-session doctor may get one sessionless `UNKNOWN` row that cannot be joined to usual sessions.
- **Minimal correction.** Add an explicit policy to the plan.
  - *Proposal (default):*
    - **Board state never blocks creating a NOTED request.** `createAppointment` has no such precondition, and adding one would be MCP-side business logic.
    - **Today:** `UNKNOWN`/stale → no attendance claim; offer desk handoff *or* noting a request.
    - **Future date:** state the usual hours *as usual hours* for that weekday; state that the day isn't confirmed yet; offer to note the request.
    - **`CANCELLED` for the requested session:** say so; offer another date or the desk.
    - **ON_CALL with no confirmed entry:** desk, per contract L943–946.
  - Ask Manoj to confirm the shape of missing entries: whether it is one synthesised `UNKNOWN` row per usual session or per doctor, and whether staleness applies to future dates at all.
- **Owner.** Us (policy); Manoj (semantics confirmation).
- **Timing.** Required **before implementation** of the `get_doctor_availability` output schema and prompt.

#### OPUS-02 — Trusted identity for list, cancel and reschedule must be decided now, not "tracked collectively"

- **Evidence.**
  - Contract L405–407: `findAppointments` returns requests for "the number it presents".
  - Contract L447, L464: cancel succeeds when `callerMobile` matches.
  - The contract has no name check and no binding between the value and the call.
  - Current MCP: trusted `X-Caller-Number` comes from headers (`tools.py:97-101`), but LIST also accepts a model-supplied `phone` (`tools.py:75-78`, `260-263`). The legacy API added a `customerName` check (`tools.py:289-297`); the new contract has none.
  - `Mobile` is exactly 10 digits (contract L910–914). Current `Customer.phone` allows 6–15 digits (`tools.py:53`).
  - Plan L117 says "authorized number" and L155 files trusted caller authorization and family access as a gap "tracked collectively".
- **Failure scenario.** A caller dictates someone else's number. MCP forwards it as `mobile` or `callerMobile`. Manoj returns and cancels that person's appointments, because the backend cannot tell a dictated number from a verified one.
  - Separately, `+91…` caller ID fails the 10-digit pattern, so list, cancel and reschedule fail for every caller, or someone "fixes" it ad hoc.
- **Minimal correction.** Add to the plan:
  - **Create:** `mobile` is the dictated patient contact, read back. This matches the existing "Never the caller ID" rule.
  - **List, cancel, reschedule:** `mobile`/`callerMobile` come **only** from trusted `X-Caller-Number`, normalised to 10 digits using a configured tenant country prefix. They are never a model argument.
  - **Absent or non-normalisable caller ID, or an appointment registered under another number (family case):** neutral response and desk handoff in the first release.
  - Remove the `phone` LIST argument.
  - Add tests for forged model fields and international numbers.
  - Ask Manoj to confirm that the agent credential is trusted to assert `callerMobile`, which is the implicit model.
- **Owner.** Us; Manoj (confirmation).
- **Timing.** **Before implementation** of `manage_booking`.

#### OPUS-03 — The safety pre-check mechanism contradicts the plan's own diagram

- **Evidence.**
  - Plan L46: "A tool name chosen by the LLM is not a sufficient safety gate: integration must provide a way for relevant original utterances to reach Shobhit even if a doctor is also named."
  - The sequence diagram at L63 makes the knowledge step `opt Symptoms or red flags need assessment`, initiated by the voice agent. That is exactly the LLM-chosen gate.
  - Plan L140 says unrelated operational reads can continue during a knowledge outage "under an agreed routing policy". But MCP cannot know what is "unrelated" without detection logic, which the user assigned to Shobhit.
- **Failure scenario.** "I want Dr Ravi today, I have chest pain since morning." The LLM calls `get_doctor_availability` only. Nothing reaches Shobhit, and a routine request is noted for a red-flag caller.
- **Minimal correction.** We can decide this now, independently of Shobhit's payload.
  - *Proposal:*
    - `get_doctor_availability` and `manage_booking` (create) take a required `utterance` (verbatim) and `language`.
    - MCP sends the utterance to Shobhit's routing endpoint **in parallel** with the Manoj reads, not before them, to protect latency.
    - MCP gates the result mechanically:
      - emergency or desk outcome → return that routing instead of scheduling facts, and refuse the create;
      - clarification → return the clarification;
      - "no routing concern" → proceed.
    - This consumes Shobhit's decision; it does not detect anything in MCP.
    - Until Shobhit's contract exists, keep this as an interface with a stub. **Cutover is gated on it.**
  - Fix the diagram so the check isn't optional.
  - Leave the outage policy as an explicit question (Q2).
- **Owner.** Us (mechanism); Shobhit and clinical owner (outcomes and failure policy).
- **Timing.** Mechanism **before implementation**; failure policy **before cutover**.

### MEDIUM

#### OPUS-04 — Write idempotency, retry and uncertainty don't fit the new contract

- **Evidence.**
  - `tools.py:109-112`: the key is `callId|action|casefolded name|target`, with the target built from slot IDs.
  - Contract L862–864: the same key with a different body returns `409 IDEMPOTENCY_CONFLICT`.
  - `tools.py:322-325`: with no call ID, no key is sent, because "the API then refuses (400)". But the new `Idempotency-Key` is optional (contract L860), so the write goes through unprotected.
  - `tools.py:159-175`: a same-key retry on timeout plus a 504 retry. The 504 path is legacy-API semantics absent from the new contract.
  - `config.py:40`: 5 s write timeout, so up to about 10 s per write.
  - `tools.py:118-119`: on failure, only `COULD_NOT_RECORD` exists.
  - Plan L51 wants "uncertain" wording.
  - `tools.py:184`: raw 2xx/4xx bodies go to the model unvalidated.
- **Failure scenarios.**
  1. The caller corrects "ravi" to "Ravi", or corrects the reason. The key is unchanged but the body differs → 409 → the agent says it could not record.
  2. The call ID is missing, the gateway retries, and duplicate NOTED requests result.
  3. A commit succeeds, the response is lost, and the agent says "could not record". The caller asks again, creating a duplicate or confusion.
  4. A 10 s blocking write violates the one-second target.
- **Minimal correction.**
  - Derive the key as `sha256(callId | operation | path id | canonical JSON of the exact outgoing body)`.
  - **Refuse writes** in MCP when the trusted call ID is missing or longer than 64 characters.
  - Add distinct outcomes: `RECORDED`, `UNCERTAIN` (timeout or transport error after send), `NOT_RECORDED` (definite 4xx), `IDEMPOTENCY_CONFLICT` and state `CONFLICT` (e.g. already cancelled). Don't lump them together.
  - Drop the legacy 504 rule.
  - Within the customer turn, allow at most one retry, and only if it fits a per-turn deadline.
  - After `UNCERTAIN`, the agent may offer LIST verification, which works only via the trusted number (OPUS-02).
  - Validate every 2xx body against the pinned schema; malformed → `COULD_NOT_CHECK` / `UNCERTAIN`.
  - Map Manoj errors into MCP-owned envelopes rather than passing raw messages to the model.
- **Owner.** Us; Manoj for replay retention and TTL (already listed at L155).
- **Timing.** **Before implementation.**

#### OPUS-05 — The call-summary tool must not be callable by the in-call LLM, and retries must be byte-stable

- **Evidence.**
  - Plan L101: "Expose to the authenticated agent lifecycle."
  - Plan L128: "model/lifecycle inputs include final intent/outcome."
  - Contract L609–611, L629: first write wins; the same `callId` returns the original unchanged.
  - The endpoint *also* takes `Idempotency-Key` (L616), where the same key with a different body returns 409.
  - `register.py:28` publishes every tool to the gateway.
- **Failure scenarios.**
  1. The LLM sees `record_call_summary` in its tool list and calls it mid-call. The provisional summary becomes permanent.
  2. A platform retry recomputes `durationSeconds` → a different body with the same key → 409 instead of the 200 replay.
  3. After an abrupt hang-up there is no LLM turn left to produce `intent`/`outcome`.
- **Minimal correction.**
  - Hide the tool from the conversational tool set. *Assumption:* this can be done via ContextForge tool visibility or a separate virtual server, and LiveKit tool filtering; to be verified.
  - Invoke it programmatically from the platform's call-end hook.
  - The platform builds the full payload once, stores it, and retries the identical body.
  - MCP sends no separate `Idempotency-Key`, or one derived solely from `callId` over that fixed body.
  - Define a deterministic fallback for abrupt hang-up: `outcome=ABANDONED`, `intent` from the last tool used or `OTHER`.
  - Map STT language to `EN/KN/HI`; omit `language` otherwise, since `ta`/`te` are not representable (contract L1198).
  - Truncate `summaryText` to 500 characters.
  - Add trusted `startedAt` and duration headers to `PASSTHROUGH` (`register.py:30`).
- **Owner.** Us and the voice-platform team.
- **Timing.** **Before implementation** of the tool; lifecycle hook **before cutover**.

#### OPUS-06 — The one-second target needs a per-turn budget and a single-call tool shape, not just measurement

- **Evidence.**
  - Plan L167 lists dependent hops but no allocation.
  - The diagram at L69–84 shows separate agent→MCP exchanges for name, clarification and date.
  - Each tool call costs an extra LLM round trip before audible speech.
  - `config.py:39` sets a 2 s read timeout. The Manoj production host is a placeholder (contract L21–26), so real round-trip time is unknown.
- **Failure scenario.** The LLM emits `searchDoctors` as one tool call, then profile and board as another, then speaks. That is two LLM inferences plus two serial Manoj round trips plus gateway hops, which already exceeds 1 s before TTS.
- **Minimal correction.**
  - One `get_doctor_availability` invocation takes `doctorName | departmentId`, `date` and `utterance`. It resolves internally: search → (profile ‖ board ‖ Shobhit). It returns either choices or the combined result.
  - Profiles get a short TTL cache; the board is never cached.
  - Set explicit budgets, e.g. MCP tool wall time p95 ≤ ~300 ms, as a *proposal* to be tuned.
  - Set per-hop timeouts derived from that budget.
  - Keep the token pre-warmed and refreshed with skew and single-flight.
  - Add an early phase-2 spike measuring real Manoj round-trip time from the MCP region as soon as a host exists. If that spike already exceeds the budget, escalate early for owner-side aggregation rather than discovering it at phase 4.
- **Owner.** Us; Manoj (host, round-trip time).
- **Timing.** Tool shape **before implementation**; spike **as soon as the host exists**; gate **before cutover**.

#### OPUS-07 — Transport, readiness and base-path code still assume the legacy API

- **Evidence.**
  - `tools.py:136-139` and `config.py:33`, `66-67`: a static bearer token.
  - `config.py:70-73`: `api_root` strips `/api/v1`.
  - `server.py:96-104`: `/ready` probes `{api_root}/ready`, which the new contract doesn't define.
  - `smoke.py:22-26`: the release fails unless `ready`.
  - `tools.py:176-180`: 401 is treated as a permanent operator error.
- **Failure scenarios.**
  1. `/ready` always returns 503 against Manoj or the mock, so smoke and deployment fail.
  2. A token expiring mid-call yields 401 → `COULD_NOT_CHECK` for the rest of the token lifetime.
  3. Prefix stripping mis-builds URLs against the no-prefix mock.
- **Minimal correction.**
  - Configure the full base URL verbatim per service; no stripping.
  - Use a client-credentials token provider: cache, refresh at `expires_in` minus skew, single-flight.
  - On 401, invalidate and retry once. Writes that were rejected by 401 were not processed, so retrying them is safe.
  - Base readiness on local config and token acquisition, with any upstream probe optional and non-fatal until Manoj defines health.
  - Test both prefix and no-prefix bases.
- **Owner.** Us.
- **Timing.** **Before implementation.**

#### OPUS-08 — The overlay needs a facility clock and should respect `dataConfirmed`

- **Evidence.**
  - Plan L49 and L55: "Apply expectedEndTime expiry" and weekday matching of `usualSchedule.daysOfWeek`.
  - Contract L272: `today` is resolved in the facility timezone.
  - Contract L1024–1026: `dataConfirmed=false` marks seed data.
  - Contract L1019–1023: `patientsPerHour` exists.
- **Failure scenario.**
  - MCP runs in UTC. At 00:30 IST it picks the wrong weekday's usual hours, or expires a session incorrectly.
  - Unconfirmed seed hours are spoken as the doctor's usual hours.
- **Minimal correction.**
  - Add a tenant timezone setting to MCP config.
  - Compute weekday and "now" in that zone.
  - Apply expiry only when the date is today.
  - Qualify or suppress usual hours when `dataConfirmed=false`.
  - State explicitly that `patientsPerHour` is not used for capacity claims.
- **Owner.** Us.
- **Timing.** **Before implementation.**

### LOW

#### OPUS-09 — Prompt and gateway migration is under-specified

- **Evidence.**
  - `prompt.py:14-23` and `26-29` still say: book with a slot ID; "timingCertainty"; "NO_SERVICE"; and "never as a calendar date you worked out".
  - `healthcare.json` promises "bookable slots".
  - `register.py:99` only re-registers on visibility or passthrough changes, and its tool-collision check (L107–112) runs only on first registration.
  - `smoke.py:18`, `37-42` hard-code the old tools and outcomes.
  - Plan L103 mentions these only generically.
- **Risk.**
  - A re-run of `register.py` reports "already registered" while ContextForge may keep the old tool schemas. *Assumption:* depends on ContextForge refresh behaviour.
  - Stale slot wording survives into the new prompt.
- **Correction.**
  - Rewrite the core rules around NOTED and the board-status vocabulary.
  - Keep "never say confirmed" (now: unless the status is `CONFIRMED_BY_DESK`).
  - Force a tool refresh on registration, or on tool-set hash change.
  - Smoke tests exercise only reads, never `record_call_summary`.
  - *Optional proposal, not a prerequisite:* expose the facility's current date so that "tomorrow" can be read back as an explicit date for confirmation.
- **Timing.** Before cutover.

#### OPUS-10 — Stubs can silently become a shadow backend; the pinned spec is not loadable as-is

- **Evidence.**
  - Plan L162: a custom stateful operational stub.
  - Plan L146–153: four invalid schemas in the pinned snapshot.
- **Risk.**
  - Our stub encodes our guesses (e.g. OPUS-01's missing-entry shape) and tests pass against assumptions.
  - Schema validators reject the invalid snapshot.
- **Correction.**
  - Keep a local overlay containing only quoting fixes, hash-recorded, and deleted when Manoj republishes.
  - Validate every stub response against it.
  - Tag behaviour tests that rest on unconfirmed semantics as `assumed`, and re-run them against Manoj's test tenant before cutover.
- **Timing.** Phase 2.

#### OPUS-11 — The current plan points at a historical inventory whose superseded rows conflict with it

- **Evidence.**
  - Plan L165 defers to "the earlier report's inventory".
  - The historical acceptance table says "Operations still work when knowledge fails", which conflicts with plan L140.
  - Its interpretation row treats advanced interpretation as acceptance scope, and it assigns date/safety pieces to an unassigned owner.
  - The rollback rules exist only in the historical text.
- **Risk.** Implementers follow superseded rows.
- **Correction.**
  - Copy the inventory, rollback rules and acceptance table into the current plan, with those rows corrected.
  - Mark advanced interpretation cases as deferred.
  - Sequence CI changes (`scripts/test.sh`, `ci.yml`, compose) in the same change set that repoints MCP. Otherwise the 16 e2e tests and the API/Postgres CI path break mid-migration.
- **Timing.** Before task breakdown.

---

## 4. Checklist coverage

| Area | Status |
|---|---|
| Complete backend removal | Adequate intent (L5, L164–165); fix via OPUS-11 (ordering, inline inventory). |
| Tools → REST mapping | Correct against the contract (L109–120). Department create is supported. Reschedule has no doctor change (correctly noted). Pagination is noted at L92. |
| Board overlays and optional fields | Good for today. The future-date gap is OPUS-01; timezone and `dataConfirmed` are OPUS-08. |
| Identity and family journeys | Gap: OPUS-02. |
| Idempotency and uncertain writes | Gap: OPUS-04. |
| OAuth and base path | Plan text correct; code gap: OPUS-07. |
| Knowledge safety without cloning logic | Gap: OPUS-03. Hospital-answer requirements (L142) are good. |
| Call-summary lifecycle | Mostly right; exposure and retry-body gaps: OPUS-05. |
| Prompt and gateway migration | OPUS-09. |
| Test and stub realism | OPUS-10. |
| Latency feasibility | Unproven; OPUS-06. |
| Rollback and data ownership | Only in historical text; OPUS-11 and Q3. |

## 5. Scope creep and unnecessary complexity

The plan is lean. Minor watch items:
- **Do not build a finalization queue in MCP.** The plan already says so at L130; keep it that way.
- **"Separate tool credential for `calls.write` if desired"** (L42): defer; one Manoj machine credential is sufficient initially.
- **"Owner-provided aggregation if needed"** (L167): correct as a contingency only. Don't pre-request it before the OPUS-06 spike.
- **Health, error and rate-limit contract asks** (L155): keep them as tracked asks, not gates. OPUS-07 removes our dependency on a health endpoint.
- Nothing reintroduces slots or an interpretation endpoint. The OPUS-09 date read-back is optional.

## 6. Ordered minimal amendments and acceptance checks

1. **Board-status policy (OPUS-01).**
   - *Check:* stub fixtures for a future date with a stale entry, a future date with no entry, and a `CANCELLED` session. The tool returns usual hours labelled as usual, makes no attendance claim, and create is still permitted. ON_CALL with no confirmed entry → desk.
2. **Identity rules (OPUS-02).**
   - *Check:* the LIST/CANCEL schema has no mobile argument. `+91XXXXXXXXXX` is normalised. A model-supplied number is ignored or rejected. Missing caller ID → neutral desk outcome. Concurrent calls never cross numbers.
3. **Safety pre-check mechanism (OPUS-03).**
   - *Check:* "Dr Ravi today + chest pain" through the knowledge stub's emergency fixture → emergency routing returned, and create refused. Knowledge timeout → the agreed failure outcome. Neither case depends on the LLM choosing `search_knowledge`.
4. **Write semantics (OPUS-04).**
   - *Check:* name correction → new key, no 409. Missing call ID → write refused. Commit then dropped response → `UNCERTAIN`. Replay → original returned. `IDEMPOTENCY_CONFLICT` and state `CONFLICT` are distinguished. Malformed 2xx → not success.
5. **Call-summary exposure and body stability (OPUS-05).**
   - *Check:* the in-call tool list excludes the tool. A retried identical body → 200 treated as "already stored". Abrupt hang-up → `ABANDONED` summary. `ta` language → field omitted.
6. **Single-call tool shape, budget and spike (OPUS-06).**
   - *Check:* the named-doctor case completes in one MCP call. Tool p95 is within the agreed budget against the stub with injected latency, then against the real host.
7. **Transport, readiness, timezone (OPUS-07, OPUS-08).**
   - *Check:* token expiry mid-call recovers transparently. `/ready` is green against the mock. Prefix and no-prefix bases both pass. Weekday is correct at 00:30 facility time.
8. **Prompt and gateway refresh, stub overlay, inline inventory (OPUS-09 to OPUS-11).**
   - *Check:* registration refreshes tool schemas. Smoke tests are reads only. A repository scan finds no `slotId` or `timingCertainty`. CI runs without `services/api` or Postgres.

## 7. Essential questions (ask one at a time)

1. **To the user:** do you accept OPUS-01's default? That is: for a future date, or when the board is `UNKNOWN`, the agent states usual hours as usual hours and may still note a request, rather than transferring every such caller to the desk.
2. **To Shobhit and the clinical owner, via the user:** if the knowledge service is slow or down, should availability and booking tools refuse to continue (desk transfer), or continue with a "safety check unavailable" flag? MCP cannot tell symptom utterances apart without detection logic.
3. **To the user:** does the legacy deployment hold real patient appointments? If yes, cutover needs the controlled migration or read-only desk path from the historical inventory. If no, retirement is a straightforward code removal.

The first-release family/delegated default (desk handoff) and Manoj's missing-entry semantics can go into the tracked contract asks rather than being separate user questions.

## 8. Overall risk and limitations

- **Overall risk: medium for implementation, high for production readiness.**
  - The main risks are patient safety (OPUS-03), privacy (OPUS-02) and product viability (OPUS-01).
  - Each needs only a plan paragraph plus tests, not new infrastructure.
- **External gates:**
  - Shobhit's endpoint, schema and auth.
  - The real Manoj host, idempotency retention and missing-entry semantics.
  - The republished, valid spec.
  - Measured latency.
- **Limitations of this review:**
  - Based only on supplied text. I did not verify ContextForge or LiveKit tool-visibility and refresh behaviour (OPUS-05, OPUS-09 are assumptions).
  - Backend and mock behaviour are unobserved.
  - Latency figures in OPUS-06 are proposals, not measurements.
  - Nothing was run, edited or contacted.
