# Opus review: phase 5 (rules and documents)

- **Commit reviewed:** `0282655` ("Document slot-aware rules and pending release gates"), base `9a1bea6`.
- **HEAD:** `0282655`.
- **Brief:** `.context/astra-build-slots-5.md`, identical to the attached copy, including Garima's five revisions.
- **Inputs read:**
  - the hand-back (`.context/slots-5-handback.md`), its fact table (`slots-5-facts.json`, 47 entries), and its static and check evidence;
  - SLOTS-PLAN;
  - my T-4, 4b and 4b-M1 reviews.
- **Code read:** the full diff of all three files, checked against `availability_policy.py` (`session_decision`, `working_hours`, `aggregate`), `outcomes.py`, `smoke.py`, `test_contract.py` and the pinned contract.

## 1. Verdict: APPROVED

- There are no blocking findings.
- Two Low observations are optional (§3).
- The documents describe the implementation correctly. They keep every approved decision and its limits, and they separate documentation from deployment readiness.
- **Phase 5 is complete.** That does not make the release ready for deployment: all seven gates are still pending.

## 2. Requirements

| # | Check | Status | Evidence |
|---|---|---|---|
| 1 | Exactly three files; `CLAUDE.md` under 80 lines | **Met** | `git show --stat` lists `CLAUDE.md`, `docs/DECISIONS.md` and `docs/handover/mcp-only/PLAN.md`. `git diff --quiet 9a1bea6 0282655 -- services deploy scripts Makefile VOICE-TEAM.md implementation/` shows no change. `wc -l CLAUDE.md` gives **47** |
| 2a | Slot reads | **Met** | `CLAUDE.md:24`, SL1 D-5 and `PLAN.md` item 3 match the reader: a selected doctor reads `/slots` for AVAILABILITY in both modes, today with profile and board, future with profile; only today reads the board; WORKING_HOURS reads neither. That matches the 4b pre-check and the bench's observed paths |
| 2b | Department capability checks | **Met** | Cached `/capabilities`, no fan-out to `/slots`, and `DOCTORS_MATCHED` with `bookableFound=0` until a doctor is selected (`aggregate`, `availability_policy.py:510–511`). An ended supplied session is not a match (`session_decision`, `SlotsNotRead` branch, `:250–252`) |
| 2c | UNKNOWN takes precedence | **Met** | `session_decision` checks UNKNOWN before CANCELLED (`:240–243`). `CLAUDE.md:27` and SL1 D-6/D-7 say ordinary UNKNOWN in the selected scope means callback, and that the label is evidence |
| 2d | Session matching | **Met** | An optional, non-blank `session` must match the normalised label of the session that contains the time; an unlabelled session can't satisfy a name; `session` is never forwarded (`CLAUDE.md:28`, SL1 K-6/D-2) |
| 2e | Booking time required | **Met** | With slots enabled, a missing time gives `INVALID_REQUEST`/`ASK_WHICH_TIME` with no write (`decide_booking` returns `TimeRequired` only when there is a `SlotPlan` and no time; `booking.py` maps that) |
| 2f | `slotTime` and `slotMoved` | **Met, exact** | `CLAUDE.md:29` and SL1 K-7/D-3: every appointment object has a nullable `slotTime` and a boolean `slotMoved` (false by default, false for LIST and CANCEL); a successful slot-aware write returns the block start; "moved" is judged against the chosen block's start, not the caller's minute. This matches `outcomes.py:185–191` |
| 2g | "Without slots, a supplied passed end is unavailable" (`CLAUDE.md:27`) | **Accurate** | With no slot evidence, `_ended_today` gives `SESSION_ENDED` (`:247–248`). With slot evidence, the owner's blocks decide (`:254–262`). With `SlotsNotRead`, the same guard applies (`:250–252`, P-1) |
| 3 | Two on-call rules, explicit and correct | **Met** | `CLAUDE.md:25` and SL1 D-8 (AVAILABILITY): confirmed IN or LATE **plus** a usable window or an open bookable block follows the ordinary policy; CANCELLED is unavailable; otherwise `HANDOFF_REQUIRED`/`TRANSFER_DESK`/`ON_CALL_DOCTOR`, never a callback. `CLAUDE.md:26` and SL1 D-8 (WORKING_HOURS): always handoff, because no confirmation data is read. This matches `working_hours` (`:406–408`) |
| 4 | SL1 supersedes the old on-call rule without editing A12 or A13 | **Met** | `DECISIONS.md:196` states the supersession. The diff appends only; 0 lines are removed, and A12 (`:118`) and A13 (`:147`) are byte-unchanged |
| 5 | Smoke exception, fixed-date policy and T-4 findings, with their limits | **Met** | Smoke: `DECISIONS.md:202` requires ON_CALL_DOCTOR, `complete` exactly true and TRANSFER_DESK; everything else fails, including SEARCH_INCOMPLETE (see O-2 on wording). Fixed dates: hermetic tests only; read-only smoke may use today; the live external journey uses dates the owner designates (`CLAUDE.md:47`, SL1). T-4: 20 of 20 confirmed, 20 of 20 clean comparison; "no single-server production risk **for this mechanism and execution model only**"; the freeze's cause is unproven; recorder strictness is open; the setup remedy is optional |
| 6 | Documentation versus deployment; gates pending; optional items stay optional | **Met** | `PLAN.md:33–51`: "Nothing in the slots series has been merged or deployed. Documentation completion is not deployment readiness." All seven gates are pending, and **LOG-1 is an open gate, undecided, with no resolution proposed**. The four non-gates (G-13 to G-15, recorder strictness, the T-4 remedy, O-1) are listed as "not deployment gates unless Garima says so". SL1 repeats this, and `CLAUDE.md:37` points to it |
| 7 | No stale or contradictory instructions, invented guarantees, reopened decisions or new requirements | **Met** | A sweep of the three files for "always callback", "ON_CALL always", "slot endpoint", "pending slot", "not yet supported" and "NOT_CONFIRMED require" finds only the historical A12/A13 text, which SL1 supersedes explicitly. `PLAN.md:59` ("No slot endpoint was added") sits under the 30 September heading, which `:55` marks as historical with the current 0.4.0 pin stated. SL1's K-5 is not invented: it comes from `OPUS-OPS-API-040-IMPACT.md:108`, resolved by G-9 |
| 8 | Fact references, links and schema | **Met** | I spot-checked 8 of the 47 fact references (`smoke.py:81`, `outcomes.py:185`, `availability_policy.py:406–408` and `:493`, `booking.py:62`, `live.env:5`, M1 review `:65` and `:139`). All point at the cited content. Every relative link and anchor in the three files resolves, by my own check. The SL1 contract hash `d3e93f45…6c80` equals `shasum` of `manoj-openapi-20261007.yaml` and `test_contract.py:19`; the version is `0.4.0-draft`. The schema is byte-identical (§4) |

## 3. Observations (optional, not blockers)

### O-1 (Low): a temporary status line in the permanent rules file

**Where:** `CLAUDE.md:37` ("Phase 5 documents … Schema stays `2026-10-08.1`; merge, live checks and deployment require separate approval").

**Why it matters:** this is release status, not a lasting rule. It will go out of date at release, or at the next schema bump. "Schema stays `2026-10-08.1`" could also be read as conflicting with the Commands rule to bump `SCHEMA_VERSION` when the surface changes.

**Fix:** either begin the line with "Until the slots release is approved:", or remove it at release. No change is needed now.

### O-2 (Low): the smoke exception's scope is worded loosely

**Where:** `DECISIONS.md:202`. It says the smoke accepts the handoff "only for a valid **availability** response".

**What the code does:** the code (`smoke.py:81`) applies the exception to **both** department probes of `get_doctor_availability`, the AVAILABILITY one and the WORKING_HOURS one. That is the approved behaviour, and the 4b-M1 tests cover it.

**Risk:** a reader could take "availability" to mean only the AVAILABILITY-purpose probe.

**Fix:** "for either department probe of `get_doctor_availability` (AVAILABILITY or WORKING_HOURS)". No change is needed now.

## 4. Verification

**Commands I ran:**

| Command | Result |
|---|---|
| `timeout -k 10 600 make test-fast` | **1,165 passed**, 14 deselected, 2 Authlib warnings, in 54.93 s, exit 0 (`.context/opus-5-fast.txt`) |
| `make schema` to a file, then `stat`, `shasum -a 256` and `cmp` | 64,111 bytes, `3ef91e78…6c62`, **byte-identical**; version `2026-10-08.1` present |
| `git diff --check 9a1bea6 0282655` | clean |
| `git diff --quiet 9a1bea6 0282655 --` over code, deploy, scripts, VOICE-TEAM and the implementation reports | no change |
| A link and anchor resolver over the three files | every relative link resolves |
| `wc -l CLAUDE.md` | 47 |
| `shasum -a 256` of the pinned contract | matches SL1 and `test_contract.py:19` |
| Reading `availability_policy.py`, `outcomes.py` and `smoke.py` | §2 rows 2–5 |

**Astra's evidence that I inspected but did not rerun:**
- `./scripts/test.sh`: 1,165 hermetic and 5 e2e tests, all suites passed;
- the scope and static JSON;
- the full 47-entry fact table (I spot-checked 8).

**Untested:** none of this changes behaviour, and nothing live was run, which is correct for a documentation phase.

## 5. Readiness

- **Phase 5:** **approved; the slots series documentation is complete.** O-1 and O-2 may be folded into any later documentation touch.
- **Deployment readiness:** **no.** These are the seven pending gates in `PLAN.md:33–51`:
  1. Garima's merge and deploy approval;
  2. the authorised live run on Manoj's HTTPS synthetic tenant;
  3. the authorised live bench against 0.30 s;
  4. knowledge host and deployed-adapter credentials, then the canary smoke;
  5. the ContextForge refresh to `2026-10-08.1`;
  6. voice-team readiness;
  7. LOG-1 (open; Garima decides).
- **No merge, push, deployment or live call** has been made by this review or by the commit.

## 6. Plain-English summary for Garima

**What's sound:**
- The three documents now describe exactly what was built: when slots are read, when a booking time is required, how `slotTime` and `slotMoved` work, and the two separate on-call rules. I checked each against the code.
- Your decisions are recorded with their limits: the narrow on-call smoke rule, the fixed daytime test dates, and the T-4 findings, including "not proven to be the cause of the old freeze".
- The old "on-call always means callback" rule is clearly superseded, without rewriting history.
- The plan says plainly that nothing has been merged or deployed, and lists all seven release gates as pending, including LOG-1 as your open decision.

**Needs fixing:** nothing.

**Two optional wording tweaks** for later:
- one line in `CLAUDE.md` is a temporary status note;
- one sentence could say more clearly that the smoke exception covers both department checks.

**Your decisions still open:**
- LOG-1;
- whether the strict test recorder stays;
- authorising the release gates when you're ready.

## 7. Follow-up commit `980da73`: O-1 and O-2 applied

**Diff:** exactly one line was removed and one added in each of `CLAUDE.md` (line 37) and `docs/DECISIONS.md` (line 202), confirmed with `git show --numstat`.

**Text:** both lines match the follow-up brief (`.context/astra-fix-slots-5-wording.md`) byte for byte, confirmed with `cmp`.

| Line | Before | After |
|---|---|---|
| `CLAUDE.md:37` | a temporary release-status line | a permanent rule: approval is not deployment readiness, and a schema change needs a reviewed `SCHEMA_VERSION` bump plus a gateway/ContextForge and voice refresh |
| `DECISIONS.md:202` | "only for a valid availability response" | names both department probes (AVAILABILITY and WORKING_HOURS) |

**Checks:**
- `CLAUDE.md` is still 47 lines;
- `git diff --check 0282655 980da73` is clean;
- no other file changed.

**Phase 5 remains APPROVED.**
