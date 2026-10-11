# Plan: a concise, complete voice-team handover

- **Status:** revision 5, 12 October 2026. **Approved by Garima:** the four-sentence tool description, the `doctorId`/`doctorName`/`date` parameter descriptions, the `choices`/`departmentChoices` output descriptions, and test change B **without a line limit**. Opus writes `VOICE-TEAM.md` (done, §9); Astra does only the published-text, schema and test changes; Opus then reviews both.
- **Base:** `main` `28f11a8`, deployed to the canary as revision `--0000004`, schema `2026-10-11.1`.
- **Audience:** Rajeev's team, building the LiveKit voice agent that calls our three tools through ContextForge.
- **Rule kept (contract only):** the handover states facts about the interface: what a tool accepts, returns and means. It does not prescribe agent behaviour, prompts or spoken words.

## 1. Problem

1. **Length and duplication.**
   - `docs/handover/VOICE-TEAM.md` is 1,596 lines, and the voice team found it too long.
   - About 440 lines are input-schema JSON copied from `tools/list`.
   - About 640 lines are full example payloads, mostly written before slots were enabled.
   - The 135 field rows repeat shared types (`BoardSessionOut`, `UsualSessionOut`, `SlotOut`, `Callback`, `Decision`, `Reason`) under two tools, and ten outcome codes are explained twice.
   - About 35 lines are obsolete version history.
2. **Stale or wrong content.** These are G-1 to G-6 in §7: the deployment status, the removed knowledge field `question`, the claim that `language` can't be null, the note that slots are "not yet deployed", and the missing change notes.
3. **A gap seen live.** In ContextForge chat today, a department search returned `DOCTORS_MATCHED`. The model then claimed slots needed a check "closer to the date", yet a request with the same date and that doctor's `doctorId` returned two open blocks at once (`.context/live-try/gm-20261012.txt`). Neither the published description nor the guide makes that step explicit.

## 2. What the voice team needs (my assessment)

I derived these needs from what an integrator has to decide at each step of a call. Each item has exactly one home.

| # | Need | Home |
|---|---|---|
| N1 | Connecting: the endpoint (ContextForge or direct), the bearer, and that `tools/list` is the authoritative schema | Part 1 §1 |
| N2 | Trusted request context: the five headers, their format, which action needs which, and what happens when they are missing | Part 1 §2 |
| N3 | Each tool's purpose, and **when it applies** (which caller need maps to which tool and action) | Part 1 §3 |
| N4 | Inputs: where each value comes from (caller speech, an earlier result, the platform), and when it's required | Part 1 §3 (per tool) and §4 |
| N5 | **How data moves between calls:** availability → booking → summary, and which fields carry forward | Part 1 §4 |
| N6 | Reading results: `outcome`, `nextStep`, `decision` versus owner `status`, `detail`/`reason`, and empty versus `null` | Part 1 §5; codes in Part 2 |
| N7 | **Truthfulness rules:** what a result does and doesn't establish (NOTED isn't a reservation, `DOCTORS_MATCHED` isn't availability, `COULD_NOT_CHECK` isn't "unavailable", `[]` versus `null`, `NOT_CONFIRMED`, `slotMoved`, `UNCERTAIN`) | Part 1 §6 |
| N8 | Failures, retries and uncertainty: rejected arguments versus refused requests, the idempotency key, same-operation retries, `UNCERTAIN`, `retryAfterSeconds`, the summary being final, latency budgets | Part 1 §7 |
| N9 | Worked flows that show the chain end to end | Part 1 §8 |
| N10 | Acceptance scenarios the voice team can test their agent against (gate 6) | Part 1 §9 |
| N11 | What changed since the schema they last integrated (`2026-10-06.1`) | Part 1 §10 |
| N12 | Every field with its type, whether it's required and its meaning; every reason, detail, decision and status code; the slots-disabled rules | Part 2 |

## 3. Decisions (Opus)

1. **One authoritative file, in two parts** (Garima's decision, revision 3). There is a single `VOICE-TEAM.md`, so nothing can be missed by reading only part of the handover.
   - **Part 1, "Using the tools":** everything needed to integrate with and safely use the tools.
   - **Part 2, "Reference":** the complete field and code tables, in the same file.
   - **Length:** no fixed limit (Garima, revision 5). Completeness and clarity come first, with no unnecessary duplication. Result: 652 lines (Part 1 about 345), down from 1,596.
   - **Placement rule:** a fact needed in order to *act* on a result goes in Part 1; a fact needed only to *look something up* goes in Part 2. No fact appears in both.
   - **Navigation:** Part 1 opens with a contents list covering both parts. Where Part 1 relies on a Part 2 table, it names that table.
2. **Removed material:**
   - the copied input-schema JSON, because `tools/list` is the source;
   - the full example payloads, replaced by trimmed flows and scenarios;
   - the change history for `2026-10-05.1` and `2026-10-06.1` (git keeps it);
   - the duplicated `$defs` and outcome rows.
3. **Kept: the slots-disabled rules.** Slots are enabled per doctor (`SlotPlan.enabled`), so a doctor without slots still follows those rules. They go in Part 2, with a single pointer in Part 1.
4. **Examples use fixture data** from the development stubs, with slots enabled. That keeps them stable, and no live doctor or patient data goes into a shared document. Payloads are trimmed to the decisive fields, marked "…".
5. **Shared codes are explained once.** `CALLBACK_REQUIRED`, `HANDOFF_REQUIRED`, `NOT_AVAILABLE`, `COULD_NOT_CHECK`, `INVALID_REQUEST`, `TRANSFER_DESK`, `ASK_CALLBACK_DETAILS`, `SAY_COULD_NOT_CHECK`, `OFFER_OTHER_SESSION_OR_DATE` and `ASK_WHICH_SESSION` each get one row, marked as applying to both tools. This needs the test change in §8 (B).
6. **Shared output types are described once** in Part 2 (`$defs.BoardSessionOut.*` and so on), not once per tool. This also needs §8 (B).
7. **The tool-to-summary table is a correspondence of facts.** It lists which summary `outcome` value matches which tool result, and is not an order. It closes the most likely source of misleading summaries.

## 4. Target structure: `VOICE-TEAM.md` Part 1, "Using the tools"

Line budgets are approximate. Each section lists what it **must** contain; the old line numbers show where the fact comes from today.

**§0 Status** (≈6 lines)
- Schema `2026-10-11.1` on the canary `mcp-demo-hospital-canary`, deployed 11 October 2026.
- Exactly three tools.
- `GET /ready` returns the served `schemaVersion`.
- Until ContextForge refreshes our entries, the gateway may still show the older schema.
- `tools/list` wins over any document.

**§1 Connect** (≈12 lines) (`:5–25`)
- The ContextForge virtual-server URL versus the direct `/mcp/` (streamable HTTP).
- `Authorization: Bearer`: the gateway credential for all three tools.
- Credentials, the caller's number and the call time are never tool arguments.

**§2 Request context** (≈18 lines) (`:26–37`, `:76–90`)
- One table: the five headers with their format, and which tool or action needs which. This merges today's two tables.
- What a missing header produces: `OPERATION_CONTEXT_MISSING`, `IDENTITY_UNAVAILABLE`, `NOT_SAVED`.
- Malformed headers are treated as absent.
- Caller authority needs both the number and an accepted verification label. A number on its own, or a dictated number, carries no authority.

**§3 The tools** (≈70 lines, ≈23 per tool). For each: purpose (2 lines), when it applies, actions, top-level arguments with their source and when they're required, and the order of checks.
- **`get_doctor_availability`:**
  - targets by `doctorId`, else `doctorName`, else department;
  - `purpose` AVAILABILITY (needs `date`: `today` or `YYYY-MM-DD`) or WORKING_HOURS (no date, no live check);
  - optional `session` and `gender`;
  - department results are capped (3) and name-ordered;
  - read-only and safe to repeat.
- **`manage_booking`:**
  - the CREATE/LIST/CANCEL/RESCHEDULE action table (kept from `:631–636`, tightened);
  - the order of checks (`:637–641`);
  - `callerConfirmed` means agreement to the exact details;
  - RESCHEDULE takes its doctor from the caller's appointment, and only appointments in the caller's own list (from today) are eligible (A15);
  - `patientMobile` is contact data only.
- **`record_call_summary`:**
  - one summary per call, and the first accepted summary is final;
  - field rules (`:1225–1232`);
  - `callerMobile` is required for `CALLBACK_NOTED`;
  - names, symptoms, dates and sessions go inside `summaryText` (500 characters at most, never shortened);
  - headers X-Call-Id and X-Call-Started-At.

**§4 Data flow between calls** (≈20 lines) (`:53–56`, `:110–111`, plus new)
- **Identifier origins:** `doctorId` from `doctors[]`/`choices[]`, `departmentId` from `department.id`/`departmentChoices[]`, `session` from `board[].session`/`usualSessions[].label`, `appointmentId` from `appointment`/`appointments[]`. Made-up identifiers match no record.
- **Chain 1, department to booking:**
  - `DOCTORS_MATCHED`/`CLARIFICATION_NEEDED` → the same `date` and `purpose` with the chosen `doctorId` → `openSlots` → CREATE with the same date, `preferredTime` inside an open block, and `session` optional (it must match that block's session if given);
  - `facilityToday` is the reference for "today";
  - **this is the step that failed live (G-5).**
- **Chain 2:** LIST → `appointmentId` → CANCEL or RESCHEDULE.
- **Chain 3, tool result → summary:** which `outcome`, plus `appointmentId`/`doctorId` when present.
- **Correspondence table:**

| Tool result | Summary outcome |
|---|---|
| CREATE `NOTED` | `APPOINTMENT_NOTED` |
| RESCHEDULE `NOTED` | `APPOINTMENT_RESCHEDULED` |
| CANCEL `CANCELLED` | `APPOINTMENT_CANCELLED` |
| `CALLBACK_REQUIRED` | `CALLBACK_NOTED`, with `callerMobile` and no `appointmentId` |
| Desk handoff, after the platform actually transferred the call | `TRANSFERRED`, with `transferredTo`. MCP never transfers calls, so this outcome reflects the platform's action, not the tool result |

**§5 Reading a result** (≈20 lines)
- `outcome` is the result and `nextStep` is the disposition code. Both are returned codes, not instructions.
- `decision` (MCP's) is separate from `status` (Manoj's IN/LATE/CANCELLED/NOT_CONFIRMED/UNKNOWN).
- `detail` and `reason` name the cause.
- **Empty versus null:** `openSlots: null` means not checked; `[]` means checked and nothing is offered. Absent optional fields mean not applicable. `slotTime: null` means no time was recorded.
- **Counts:** `bookableFound` versus `totalMatches`. `complete: false` means absence isn't established (`SEARCH_INCOMPLETE`).
- Then the **outcome and `nextStep` tables** for all three tools: 59 codes, with the shared ones explained once (Decision 5).

**§6 What results do and don't establish** (≈22 lines). Each item has its contract source.
- `NOTED` records a request, not a reservation or confirmation. After a `NOT_CONFIRMED` session, the desk confirms.
- `DOCTORS_MATCHED`/`SLOT_CHECK_REQUIRED` is not an availability claim (`bookableFound` 0). A request with that `doctorId` and date returns its `openSlots`, **including when only one doctor matches**.
- `WORKING_HOURS` is usual hours, never current attendance, and has no appointment offer.
- `COULD_NOT_CHECK`/`COULD_NOT_RECORD` is a failed read, never "unavailable" or "full".
- `CALLBACK_REQUIRED` means no appointment was written; the callback lives only in a `CALLBACK_NOTED` summary. MCP creates no callback task.
- `HANDOFF_REQUIRED`/`TRANSFER_DESK` means desk assistance. MCP doesn't transfer calls, and the result carries no callback metadata.
- `NOT_AVAILABLE` alternatives are only the `sessions`/`openSlots` in that result. An empty list says nothing about other times, and an owner `SLOT_FULL` rejection carries no alternatives.
- `slotTime` is the recorded block start. `slotMoved` is true only when the owner recorded a different block (choosing 10:45 and getting its 10:30 start isn't "moved").
- `NOT_FOUND` from booking is neutral: an unknown id, another caller's id and a past appointment look the same.
- Dates must be `today` or `YYYY-MM-DD`; relative words are refused (`ASK_EXPLICIT_DATE`). Times are `HH:MM`. Mobiles are exactly 10 digits.
- `patientName` appears only on the verified caller's own appointments, and the desk-authored board `note` (at most 200 characters) is written for callers. These are the only private or free-text values in results.

**§7 Failures, retries and uncertainty** (≈28 lines) (`:57–64`, `:86–96`, booking and summary notes)
- **Two kinds of failure:**
  - `isError: true` means the arguments were rejected before the tool ran. An identical retry fails the same way, and summary messages are generic.
  - A structured `INVALID_REQUEST` comes with `fields`/`detail`.
- **Writes:**
  - each confirmed write has its own `X-Operation-Id`;
  - the same id with identical arguments is a safe retry, but the schedule is re-checked, so the retry can be refused, and that refusal doesn't prove the earlier write failed;
  - the same id with different arguments gives `CONFLICT`;
  - a new id is a new write.
- **`UNCERTAIN`:** the write may have committed. The disposition is desk handoff, not a retry under a new id.
- **`retryAfterSeconds`:** present when the owner asked for a delay.
- **Summaries:** the first accepted one is final; a repeat gives `ALREADY_SAVED`, even with different text. `NOT_CONFIRMED` means persistence wasn't verified; `NOT_SAVED` means the headers were missing or invalid.
- **Latency:** scheduling and booking reads and writes have a 0.30-second budget. When the owner is slow, the tool returns `COULD_NOT_CHECK`/`COULD_NOT_RECORD`, not a guess (seen live on 11 October). Summaries have up to 8 seconds.
- **The tool-annotations table** (read-only, writes data, safe to retry), kept from `:88–92`.

**§8 Worked flows** (≈45 lines). Trimmed fixture payloads, arguments → decisive result fields.
1. Department → `DOCTORS_MATCHED` → doctor → `AVAILABILITY` with `openSlots` → CREATE with a time → `NOTED`, `slotTime`, `slotMoved: false`.
2. Ordinary doctor UNKNOWN today → `CALLBACK_REQUIRED` → summary `CALLBACK_NOTED` with `callerMobile` → `SAVED`.
3. LIST → RESCHEDULE with `newPreferredTime` → `NOTED`; then an uncertain write → `UNCERTAIN`/`SAY_UNCERTAIN_AND_TRANSFER`.

**§9 Acceptance scenarios** (≈35 lines). One table: the situation → the expected `outcome`/`nextStep` → the key fact. It covers:
1. a department match, then slots after the doctor-specific request;
2. a slot day with no time → `ASK_WHICH_TIME`, no write;
3. a full block → `NOT_AVAILABLE`/`SLOT_FULL`;
4. `NOT_CONFIRMED` with an open block → `NOTED` (the desk confirms);
5. ordinary UNKNOWN → `CALLBACK_REQUIRED`;
6. an on-call doctor not confirmed → `HANDOFF_REQUIRED`, no callback;
7. a cancelled session → `NOT_AVAILABLE`;
8. WORKING_HOURS → `PRESENT_WORKING_HOURS`, `bookableFound` 0;
9. an ambiguous name → `CLARIFICATION_NEEDED` with `choices`;
10. a relative date → `ASK_EXPLICIT_DATE`;
11. a write without `callerConfirmed` → `CONFIRMATION_REQUIRED`;
12. a write without an operation id → `OPERATION_CONTEXT_MISSING`;
13. LIST without verification → `IDENTITY_UNAVAILABLE`;
14. a dictated number is ignored for LIST;
15. RESCHEDULE of another caller's or a past appointment → `NOT_FOUND`, no write;
16. same id and same arguments → replay or a fresh refusal;
17. same id, different arguments → `CONFLICT`;
18. `UNCERTAIN` → desk handoff;
19. a slow owner → `COULD_NOT_CHECK`, not "unavailable";
20. `slotMoved: true` when the owner moves the block;
21. a second summary → `ALREADY_SAVED`;
22. a summary over 500 characters → `INVALID_REQUEST` naming `summaryText`;
23. `CALLBACK_NOTED` without `callerMobile` → `INVALID_REQUEST`;
24. an unknown argument → `isError`, no structured result.

Each row must match an existing hermetic test or current behaviour. The hand-back names the test for each.

**§10 Changes since schema `2026-10-06.1`** (≈10 lines)
- The slots release: `openSlots`, `oneDay`, `slotTime`/`slotMoved`, `DOCTORS_MATCHED`, `SLOT_CHECK_REQUIRED`, `ASK_WHICH_TIME`, `NO_OPEN_SLOT`, `SLOT_FULL`, `HANDOFF_REQUIRED` as a decision, and on-call handoff instead of callback (D-8).
- Our front-desk `search_knowledge` was removed, leaving three tools; knowledge now goes through Stratum.
- RESCHEDULE is limited to the caller's own list (A15).
- The owner's `expectedTime` is checked against `HH:MM`.

**Contents list** at the top of the file (≈8 lines, within the budget), covering Part 1 §0–§10 and the Part 2 tables.

## 5. Target structure: `VOICE-TEAM.md` Part 2, "Reference" (≈200–250 lines)

- **Field tables,** one row per field, test-checked:
  - each tool's top-level input and output fields, with input meanings equal to the schema descriptions, as now;
  - shared output types once (`$defs.<Type>.<field>`).
- **Code tables:** `Reason` (`:1504–1527`), `Decision` (`:1534–1541`), details (`:1550–1555`), and owner `status` values with their effect.
- **Rules by owner status and attendance type:**
  - slots enabled versus disabled;
  - ordinary versus on-call (D-6, D-7, D-8, K-1, K-2, K-8);
  - `oneDay` sessions, null hours, and sessions that cross midnight (unsupported).
- **Booking time rules:**
  - with slots disabled: today's window starts at the later of the session start and the current time;
  - session label matching;
  - unlabelled sessions;
  - field-name translation in rejections.
- **Summary details:** the `language` codes kept (`en`, `kn`, `hi`); `transferredTo` only with transfer outcomes; `appointmentId` refused with `CALLBACK_NOTED`.
- **Not in Part 2:** copied JSON and history.

## 6. Coverage guarantee (nothing operational lost)

- **Coverage map in the hand-back:** Astra delivers a table mapping every section and bullet of the old `VOICE-TEAM.md` (by line range) to its new home (file and section), or to "removed", with one of these reasons only:
  - copied from `tools/list`;
  - an obsolete version note;
  - a duplicate of another row (say which);
  - stale or incorrect (§7 below).
- **Tests stay as strict as now:** every schema field, outcome and `nextStep` must still be documented exactly once. Input meanings must equal the schema descriptions. The schema version line must match the snapshot.
- **Opus review:** I check the map line by line against the old file.

## 7. Stale or incorrect content (fix in the move)

| # | Old line | Fix |
|---|---|---|
| G-1 | `:11–14`, `:1583`, `:1588–1596` | Deployment status: canary `--0000004`, image `28f11a8`, schema `2026-10-11.1`, 11 October; ContextForge refresh pending |
| G-2 | `:49` | Remove `question` (a field of the removed tool). Remove `language` from the "doesn't accept null" list, because it does accept null (`:1364`) |
| G-3 | `:322` | `ASK_TO_REPHRASE`: "name or department". The meaning is hand-written in the document, not published (`outcomes.py:131` holds only the code), so this is a documentation fix |
| G-4 | `:329–333` | Replace the slots-disabled examples (§8 flows) |
| G-5 | `:308`, `:318`, `:1535` | State that the doctor-specific request returns `openSlots`, including with one match (§6) |
| G-6 | `:1588–1596` | Change notes for the removal and A15 (§10) |

## 8. Decisions that need Garima's approval

**(A) Published wording, with a schema version bump.** (Revision 4.)

**Status of each part:**
- the three parameter descriptions: **approved by Garima** (subject to schema-consistency checks);
- the shortened tool-description text and the two output descriptions: **proposed, awaiting approval**.

**Principle (Garima, revision 4):**
- The tool description carries only what a model needs to **choose and sequence** this tool, independent of conversation order.
- Target precedence, validation outcomes and edge cases live in the parameter and output descriptions they belong to, and in `VOICE-TEAM.md`.

**1. Tool description** (`packs/healthcare.json`, `tools.get_doctor_availability.description`).
- **Replace** the sentence "Department searches with slots enabled return DOCTORS_MATCHED and SLOT_CHECK_REQUIRED when doctors match: doctors match the request, not yet available; slot availability is known after a doctor-specific check, with bookableFound=0 for these matches." with this text (444 characters):

  > Each request is evaluated only on its own arguments; AVAILABILITY needs a target and a date in the same request. openSlots come only from a doctor-specific result for that doctor and date. A department result reads no slots: DOCTORS_MATCHED and SLOT_CHECK_REQUIRED establish no open time, and bookableFound is 0, also when one doctor is listed. In a doctor-specific result, a doctor without slots for that date follows the slots-disabled rules.

- **Remove** "Ambiguous names return choices." This now lives in `doctorName` and `choices`.
- **Size:** the description goes from 2,733 to 2,896 characters. The rest of the description is unchanged.

**2. Parameter descriptions** (`packs/healthcare.json`, `parameters`). **Approved.**

| Parameter | New description |
|---|---|
| `doctorId` | Directory identifier for a selected doctor, from doctors[] or choices[]; gives a doctor-specific result and takes precedence over doctorName and department fields; optional. |
| `doctorName` | Doctor name for directory search, in the caller's original wording; optional. Exactly one match gives a doctor-specific result; several matches return choices. |
| `date` | 'today' or YYYY-MM-DD; required in each AVAILABILITY request, optional for WORKING_HOURS. Other relative dates are not accepted. |

**3. Output descriptions** (`outcomes.py`, `AvailabilityResult`; both empty today). **Proposed.** Without them, removing "Ambiguous names return choices." would leave the choice lists unexplained in the published schema.

| Field | New description |
|---|---|
| `choices` | Doctors matching a doctorName with several directory matches, capped by the configured limit; a doctorId from here gives a doctor-specific result. |
| `departmentChoices` | Departments with consultants, returned when departmentName or departmentId matched none or several; a departmentId from here gives a department result. |

**Where the remaining detail lives** (not in the tool description):

| Detail | Home |
|---|---|
| Target precedence | `doctorId` description (approved) and `VOICE-TEAM.md` Part 1 §3 |
| One name match versus several versus none | `doctorName` and `choices` descriptions; Part 1 §3; Part 2 |
| Date required in every request; relative dates refused | `date` description (approved); Part 1 §3 and §6 |
| Validation codes: `ASK_EXPLICIT_DATE`, `TARGET_REQUIRED`, `DEPARTMENT_AMBIGUOUS`/`DEPARTMENT_UNMATCHED`, `NO_CONSULTANT`, `NO_DOCTORS`, `NOT_FOUND`/`ASK_TO_REPHRASE` | Part 1 §5 outcome table; Part 2 detail table |
| Edge cases: capped lists, incomplete searches, on-call by name, sessions crossing midnight | Existing description sentences (unchanged); Part 2 |

**Schema-consistency checks** (done by Opus against the code):
- "doctor-specific result" means the same in the tool description and in `doctorId`/`doctorName`;
- `doctors[]` and `choices[]` exist;
- "department fields" means `departmentId`/`departmentName`;
- `choices` is capped by `doctor_choice_limit` (`availability.py:104–108`);
- `departmentChoices` lists active departments with consultants when the department matched none or several (`:116–118`);
- `bookableFound` is 0 for `DOCTORS_MATCHED` (`availability_policy.py:508–511`);
- department requests read no slots (`schedule_reader.py:152`);
- doctor-specific requests read the doctor's slot plan, and a plan disabled for that date applies the slots-disabled rules.
- None of the phrases banned by `test_published_tool_text_contains_facts_not_behaviour_scripts` appear (checked).

**Astra repeats these checks:**
- the regenerated snapshot must contain each new text exactly once;
- the published-text tests must pass;
- the `VOICE-TEAM.md` input meanings must equal the new parameter descriptions (existing test).

**Consequences:**
1. `SCHEMA_VERSION` becomes `2026-10-11.2`, and the snapshot is regenerated.
2. One more pull request, merge and canary deployment.
3. Our ContextForge refresh (gate 5) happens once, after that deployment, to `.2`.

**Tests (Astra):** confirm, or add if missing, a hermetic test for each published fact:
- a missing date with a doctor name gives `ASK_EXPLICIT_DATE` and no directory read;
- `doctorId` takes precedence over `departmentName`;
- a single name match returns slots, and several return `choices`;
- an unmatched department returns `departmentChoices`;
- a department with slots enabled reads no slots;
- a slot-disabled doctor via `doctorId` gets slots-disabled decisions.

**(B) One authoritative `VOICE-TEAM.md`, guide first, reference later: confirmed by Garima.** This is the test change that the structure needs, in `services/mcp/tests/test_server.py`:
- **Change:**
  - the field test expects each shared output type once (`$defs.<Type>.<field>`), and asserts that its shape is identical in every tool that uses it;
  - the outcome test accepts one shared row for a code common to both tools;
- **Strictness:** every field, outcome and `nextStep` is still documented and checked exactly once. **Approved** (no line limit).

Nothing else needs a code or schema decision. The document content, structure, examples and line budget are Opus decisions within the contract-only rule.

## 9. Delivery (revision 5)

**Commit 1 (Opus, documentation):**
- the rewritten `docs/handover/VOICE-TEAM.md`, written for schema `2026-10-11.2`;
- this plan.

**Commit 1b (Opus, documentation):** the current documents that named `2026-10-11.1` as the release to publish (`AZURE.md`, `CONTEXTFORGE.md`, `PLAN.md`, `mcp-only/README.md`, `TARGET-STATE.md`) now name `2026-10-11.2` and record the 11 October merge and deployment; `docs/DECISIONS.md` A16.

**Commit 2 (Astra, code):**
- `packs/healthcare.json`: the tool description and the three parameters (§8 A);
- `outcomes.py`: the `choices` and `departmentChoices` descriptions;
- `prompt.SCHEMA_VERSION` set to `2026-10-11.2`, and the regenerated snapshot;
- `test_server.py`: the interface tests (§8 B), plus any missing published-fact tests (§8 A).

Astra **doesn't** edit `VOICE-TEAM.md`. If a test shows the document disagrees with the code or schema, Astra stops and reports it.

**Row formats the interface tests must accept** (exactly as written in commit 1):
- **Field rows,** four cells: `` | `<key>` | `<wire type JSON>` | required/optional | meaning | ``.
  - The key is `<tool>.input.<field>` or `<tool>.output.<field>` for top-level fields, and `$defs.<Type>.<field>` for every `$defs` type, once across all tools.
  - Each `$defs` type must be wire-identical in every tool that contains it.
  - Input meanings must equal the schema descriptions.
- **Code rows,** three cells: `` | `outcome.<CODE>` or `nextStep.<CODE>` | <tool>[, <tool>…] | meaning | ``.
  - Every (tool, field, code) from the `outcomes.py` models must be covered by exactly one row.
  - A row must not name a tool that lacks that code.
  - The same code may appear in several rows only for disjoint tool sets, when its meaning differs (for example `outcome.NOT_FOUND`).
- **Schema version line:** `` Schema version: `<SCHEMA_VERSION>` ``.
- **Pre-check:** Opus checked commit 1 against these rules with the current snapshot plus the approved parameter text (`.context/voice-team-doc/check_doc.py`): 110 field rows, 49 code rows, 0 errors.

**Checks (Astra), each once, stopping at the first failure:**
1. `make test-fast`;
2. `make schema` byte-compared with the regenerated snapshot (`2026-10-11.2`); only the approved texts and the version may differ from `.1`;
3. `make test-e2e`;
4. `./scripts/test.sh`;
5. the trace search.

**After Astra (Opus):**
- review the code;
- verify `VOICE-TEAM.md` against the final code and schema;
- check the coverage map of old to new content.

**Then (Garima, separately):** pull request, merge, canary redeployment, then the ContextForge refresh to `.2`.
