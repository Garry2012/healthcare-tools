# Plan: remove `search_knowledge` from the front-desk MCP server (three-tool server)

- **Status:** **revision 3, approved by Garima on 11 October 2026** ("looks good"), including the wording of gate 8 and gate 9. P2–P4 are complete: LOG-1 revision 6 approved, the Azure-retirement work committed (`9964839`), and both plans committed (`4548ab1`).
- **Documentation correction, 11 October 2026 (Garima's request):** this plan and `LOG-1-PLAN.md` are **governing documents** (§6). They are excluded from the knowledge residual search, must stay byte-identical to the base, and stay inside the contact-rollback trace search. This doesn't change implementation scope.
- No code, configuration, cloud or ContextForge change has been made.
- **Author:** Opus.
- **Branch:** `Garry2012/slots-phase-1a-1b` at `42dae2c` (not pushed; nothing released since the canary).

## Changes since revision 2 (Garima's review, 11 October 2026)

| # | Garima's point | Where |
|---|---|---|
| 1 | Keep our front-desk MCP registration separate from Stratum. "Exactly three tools" applies only to our front-desk adapter and its virtual-server view. Stratum's registration and tools are never modified. A combined voice view may hold our three tools plus Stratum's. "Stop calling `search_knowledge`" means Shobhit's tool on **our** front-desk server only | §1 items 2 and 9, §3 release order, §5 C1 (registration code), §7 gates 5, 6 and 9, §8 item 4, §11 |
| 2 | Committing the approved plan and LOG-1 revision 6 is **mandatory before** recording Astra's base SHA. Astra implements from the committed plan only | §3 P4–P6 |
| 3 | Stronger checks for each commit, keeping every first-run failure without retries | §10 |

## 1. Decision being implemented (Garima, 10 October 2026)

1. **Remove Shobhit's `search_knowledge` from our front-desk MCP server.** The server keeps three tools: `get_doctor_availability`, `manage_booking`, `record_call_summary`.
2. **Who takes over:** knowledge, symptom routing and emergency decisions move to the **LiveKit voice agent, using Stratum through ContextForge**. Stratum is a **separate MCP registration with its own tools, owned outside this repository.** This plan never modifies, removes or verifies Stratum's registration or tools.
3. **Before deployment,** Rajeev's team confirms and tests symptom and emergency journeys, including transfer behaviour, through Stratum (gate 8).
4. **Keep Manoj's call-summary values** `EMERGENCY`, `SYMPTOM_ROUTING`, `EMERGENCY_TRANSFERRED` and the rest.
5. **Documents:** historical documents stay unchanged; only current documents are updated (§6).
6. **Repository scripts change, but nothing live runs.** Astra edits `deploy/azure/deploy.sh`, `deploy/azure/smoke.py`, `deploy/contextforge/register.py`, `scripts/env.sh` and `scripts/run-profile.sh`, and tests them only through the existing hermetic tests (fakes and dry runs inside pytest). **No live Azure or ContextForge action is authorised:**
   - no `az` command;
   - no Key Vault read: no `scripts/run-profile.sh live` and no `eval "$(scripts/env.sh live)"` followed by an owner call;
   - no manual run of `deploy.sh`, in any mode, including `--dry-run`;
   - no `register.py` run;
   - no ContextForge API call;
   - no live owner call.
7. **The Azure-retirement work is finished first** (§3).
8. **LOG-1 revision 6** for the three-tool server is written, approved and committed **before implementation** (§3, §4).
9. **What "three tools" means.** It applies to **our front-desk adapter** (its `/mcp/` tool list) and to **our front-desk view in ContextForge**:
   - our registration, verified on 4 October as `frontdesk-healthcare-canary`, whose tool names carry that prefix;
   - our virtual server `frontdesk-healthcare`.

   A combined ContextForge view used by the voice agent may list our three front-desk tools **plus Stratum's tools**. That is expected and not a failure. "Stop calling `search_knowledge`" means **Shobhit's tool served by our front-desk adapter** (under our registration prefix). It does not mean any Stratum tool, even one with a similar name.

## 2. Why removal is safe for scheduling (verified in code)

- **Nothing else depends on knowledge.** `availability.py`, `booking.py`, `summary.py`, `schedule_reader.py` and `availability_policy.py` contain no knowledge reference. Existing tests require availability and booking to make no knowledge request (`test_availability.py:432`, `test_booking.py:552`).
- **Knowledge is already optional in configuration.** An empty `KNOWLEDGE_BASE_URL` leaves scheduling working (`config.py:196–198`). The 10 October live journey on Manoj's API passed with no knowledge host.
- **Leftover variables can't stop startup.** `Settings` uses `extra="ignore"` and no env file (`config.py:21`), so `KNOWLEDGE_*` variables left on the canary are ignored. C2 adds a test for this.
- **Only knowledge uses these types:** `Speech` and `Routing` (`outcomes.py:27–34`) appear only in `KnowledgeResult` (`outcomes.py:228–235`).
- **What `/dependencies` reports today:** operational status plus a knowledge block (`server.py:271–273`). **`/health` (`server.py:289`) has no knowledge content and is not changed.**
- **The registration helper only looks at our own tools.** Its drift check skips any gateway tool outside our registration prefix (`register.py:91`), so Stratum's tools are never compared, flagged or changed.

## 3. Sequence (each step needs the previous one)

| Step | Who | What |
|---|---|---|
| **P1** | Garima | Approve this plan (revision 3) |
| **P2** | Opus, then Garima | Opus writes **LOG-1 revision 6** (§4) into `docs/handover/mcp-only/implementation/LOG-1-PLAN.md`; Garima approves it |
| **P3** | Garima | **Finish and commit the Azure-retirement work** on `Garry2012/slots-phase-1a-1b`: `deploy/azure/deploy.sh`, `deploy/environments/README.md`, `deploy/environments/live.env` and the Azure-retirement documents |
| **P4 (mandatory)** | Garima, or Opus only if she explicitly asks | **Commit the approved `KNOWLEDGE-REMOVAL-PLAN.md` (this revision) and the approved `LOG-1-PLAN.md` (revision 6)** on the same branch, after P3. Before committing, the contact-rollback trace search (the command in `.context/contact-rollback/OPUS-REVIEW.md`) must print nothing for both files |
| **P5** | Opus | Record the **exact base SHA**: the commit that contains P3 and P4. Then write the Astra prompt against it |
| **P6** | Astra | Create a **clean worktree** from that SHA on a new branch, for example `git worktree add -b Garry2012/remove-knowledge <path> <SHA>`. `git status --porcelain` must be empty before any edit. Astra checks that the plan and LOG-1 revision 6 in the worktree equal `git show <SHA>:<path>`. **Astra implements only from these committed files.** Uncommitted copies in the des-moines workspace, or anywhere else, are not specifications. **Nothing in the des-moines workspace is edited or run** |
| **B0** | Astra | Baseline benchmark at the base SHA, before C1 (§9) |
| **C1–C4** | Astra | The commits in §5, each with the checks in §10 |
| **R** | Opus | Review of C1–C4, including a LOG-1 re-review and the benchmark comparison |
| **M** | Garima | Decide how the reviewed branch joins `Garry2012/slots-phase-1a-1b` (a fast-forward if nothing else has been committed there; no history rewrite) |

**Release order (later, each step separately approved; not part of implementation):**
1. **Gate 8:** Rajeev's team passes the Stratum symptom and emergency tests, and the voice agent no longer calls **our front-desk** `search_knowledge` (the tool under our registration prefix). Stratum's tools stay as Rajeev's team configures them.
2. **Deploy** the three-tool adapter to the canary.
3. **Refresh our front-desk entries only** (gate 5): our registration `frontdesk-healthcare-canary` and our virtual server `frontdesk-healthcare`. Then refresh the LiveKit cached tool view. **Stratum's registration, virtual server and tools are not modified.**
4. **Gate 9, the release safeguard:** discovery through the voice client path shows:
   - **front-desk view:** **exactly** `get_doctor_availability`, `manage_booking` and `record_call_summary`;
   - **combined view (if the agent uses one):** those three front-desk tools plus Stratum's tools, and **no** front-desk `search_knowledge`.
5. **Only then** live voice traffic. **No live voice traffic** before steps 2–4 are all complete.

## 4. LOG-1 revision 6: what changes for the three-tool server

LOG-1 revision 4 (`b7feb3c`/`7c44955`) assumes four tools and uses knowledge modules, a route and model fields. Revision 6 changes **only** the following. Every other rule, test and the M-1 guard stay as they are.

**The authoritative detail is `LOG-1-PLAN.md`, revision 6, §R:** the exact test changes, the full lists of knowledge-only and shared values, and the containers-test update. Where this summary differs, the LOG-1 plan wins.

| Item (`server.py`) | Revision 4 | Revision 6 (lands in C1) |
|---|---|---|
| `tool` | `tools.TOOL_NAMES`, 4 names | Same source, **3 names** |
| `outcome` | includes `outcomes.KnowledgeOutcome` (`:90–92`) | removed |
| `nextStep` | includes `outcomes.KnowledgeNextStep` (`:93`) | removed |
| `field` | `knowledge_contract.AnswerResponse.model_fields` (`:100`). Its only emitter is `knowledge_optional_field_dropped` (`knowledge_contract.py:73`), reached only through the knowledge client | **Entry deleted.** The field table goes from **19 to 18 names**. `server.py` no longer imports `knowledge_contract` |
| `path` | 12 templates, including `knowledge_contract.ANSWER_PATH` (`:78`) | **11 templates**; `/v1/answer` is an unknown route and is omitted |
| Knowledge events | `knowledge_unreachable`, `knowledge_rejected_adapter_credentials`, `knowledge_error`, `knowledge_answer_malformed`, `knowledge_optional_field_dropped` | No longer emitted. The first four go with `knowledge_client.py` in C1. The last stays in `knowledge_contract.py` until C2, but nothing in the server calls it after C1 |
| `test_log1_all_observed_owner_routes_are_templated` (`test_server.py`, expected set `:1633`) | Four tools; expects `/v1/answer` | Three tools; no `/v1/answer` |
| `test_log1_real_adapter_events_keep_every_permitted_value` (`test_server.py:1637–1690`) | Triggers `knowledge_optional_field_dropped` through `knowledge_contract` (`:1662`) | Only that trigger and its event name are removed; every other assertion stays |
| HTTP privacy test, six-source ownership test, interpolation, frames, `mask_error_details`, M-1 | — | **Unchanged** |

**Rules:**
- **No weakening.** Each removed LOG-1 assertion must correspond to a deleted event, route, field or outcome, and the hand-back lists the correspondence.
- **New fail-closed tests:**
  - a record carrying `field` is omitted, with its name in `omittedFields`;
  - a `/v1/answer` path is omitted.
- **Gate 7** stays "implemented; awaiting review and Garima's closure". Opus re-reviews LOG-1 in R. Production-log verification still follows an approved deployment.

## 5. Commits (Astra; checks for each commit in §10)

**Import map for the modules being removed** (`git grep` at `42dae2c`):

| Module | Imported by | Removed in |
|---|---|---|
| `knowledge.py` (service) | `tools.py`, `test_knowledge.py`, `test_availability.py:795`, `test_booking.py:994`, `test_settings.py:170` | **C1** (all importers edited in C1) |
| `knowledge_client.py` | `tools.py`, `tests/harness.py:13`, `test_external.py:31` | **C1** |
| `knowledge_contract.py` | `knowledge.py`, `knowledge_client.py`, `outcomes.py:12`, `server.py:37`, `test_server.py:1637`, **`dev/frontdesk_stubs/knowledge.py:20`**, **`test_stubs.py:16`** | **C2**. After C1, only the stub and `test_stubs.py` import it |
| `dev/frontdesk_stubs/knowledge.py` | `__main__.py:17`, `harness.py:15`, `test_stubs.py:18`, `dev/bench.py:39`, `dev/demo.py:29` | **C2**. Harness, bench and demo stop using it in C1 |
| `Settings.knowledge_*` | `knowledge_client.py`, `server.py:271` (`/dependencies`), tests, `conftest.py:327` | **C2**. Unused by the server after C1 |

**One exception, approved with revision 2:** C1 is about 24 files. The tool, its service and client, the schema, the interface table and the tool-set checks in smoke and registration have to change together. Otherwise the pinned-interface test, `test_deploy.py:56–60`/`:158` and the importers fail. C2–C4 stay at 10 files or fewer.

### C1: remove the tool, its service and client (schema, interface, LOG-1 revision 6, `/dependencies`)

| Kind | Files |
|---|---|
| Delete | `src/frontdesk_mcp/knowledge.py`, `src/frontdesk_mcp/knowledge_client.py`, `tests/test_knowledge.py` |
| Source | `tools.py` (`TOOL_NAMES` `:31`, `Services` `:39–63`, tool `:160–172`, docstring `:1`); `server.py`: LOG-1 tables `:78/:91/:93/:100` and the `knowledge_contract` import `:37`; **`/dependencies`** drops the `knowledge` block, so the body is `{"operational": …}` (`:271–273`); `create_app` loses `knowledge_transport` (`:279–282`); docstrings `:1/:3/:247` say "the operational service" and "three tools". **`/health` and `/ready` unchanged.** `outcomes.py` (import `:12`, `Speech`/`Routing` `:27–34`, section `:219–235`); `prompt.py` (`:23` "all four tools"; `SCHEMA_VERSION` `:7`); `packs/healthcare.json` (instructions `:3`, `search_knowledge` `:38–42`) |
| Schema and interface | `tests/contracts/mcp-tools.snapshot.json` (regenerated); `docs/handover/VOICE-TEAM.md`: every `search_knowledge` row and section removed, the schema-version line updated, "All four tools" made three (`:22`). The interface tests compare it with the snapshot exactly |
| Tests | `test_server.py`: tool list `:30`; search calls `:908`/`:1614`; **`/dependencies` assertions `:995–996`** (operational only; the degraded and concurrency checks `:999`/`:1074` unchanged); smoke `:1107`; `Routing` test `:1130`; interface models `:1193`; LOG-1 per §4. `test_availability.py` (`:432–456` drop the forbidden-knowledge transport but **keep the transcript-independence assertions**; `:795` drop the `KnowledgeService` use, keep the summary and booking independence). `test_booking.py` (`:552–574` the same; `:709`, `:994–1003`). `test_summary.py:225` (keep "slow healthy owner", drop the knowledge failure). `test_settings.py:170` (the `KnowledgeRequest` use only; the settings tests wait for C2). `test_external.py` (knowledge test and `KnowledgeClient`). `test_e2e_processes.py:100` (tool set only; the stub flags wait for C2). `test_deploy.py`: smoke and registration tool sets `:56–180`; **fake `/dependencies` bodies** `:43–45`, `:410`, `:426`, `:520`; server `:309`; plus the **Stratum-separation test** in §8 item 4. `test_bench.py:37`. `tests/harness.py` (client and knowledge stub state) |
| Dev and deploy (Python) | `dev/bench.py` (`knowledge_answer` scenario, knowledge stub, `knowledge_transport`, the knowledge-host label); `dev/demo.py` (three tools, no knowledge stub); `deploy/azure/smoke.py` (talks to **our adapter directly**: exact three-tool set; `/dependencies` checked for `operational` only; no knowledge checks or `SMOKE_EXPECT_KNOWLEDGE`; docstring and messages `:4/:116`); `deploy/contextforge/register.py` (**our** registration only: three tools `:22/:37/:115`; the drift check stays limited to our prefix, `:91`). **These are code edits only; neither script is run** |

- **`SCHEMA_VERSION`:** the implementation date, `YYYY-MM-DD.1`, and that date **must be after 10 October 2026**. That rules out reusing the withdrawn version.
- **Checks after C1:** `git grep knowledge_contract -- services/mcp/src` matches only `knowledge_contract.py` itself. Outside `config.py`, nothing in `src` reads `settings.knowledge_*`. The e2e adapter process may still receive `KNOWLEDGE_*` values until C2; they are accepted by the unchanged settings and unused.

### C2: contract, stub, configuration and local stack (10 files)

| Files | Change |
|---|---|
| Delete `src/frontdesk_mcp/knowledge_contract.py` and `dev/frontdesk_stubs/knowledge.py` | Removed together, after their last importers |
| `dev/frontdesk_stubs/__main__.py`, `dev/frontdesk_stubs/__init__.py` | Ops stub only; no `--knowledge-port` or `--knowledge-bearer`; docstrings say "operational stub" (`__init__:1`, `__main__:1`) |
| `tests/test_stubs.py` | Remove the knowledge stub tests; docstring `:1` |
| `src/frontdesk_mcp/config.py` | Remove `knowledge_base_url`, `knowledge_bearer_token`, `knowledge_pool_max_connections`, their validators and production checks (`:2, :41–46, :62, :79, :111–121, :189–198`); "one owner service" and "three tools" |
| `tests/conftest.py`, `tests/test_settings.py` | Remove knowledge defaults (`conftest.py:327`) and tests. **Add:** leftover `KNOWLEDGE_BASE_URL` / `KNOWLEDGE_BEARER_TOKEN` in production settings are ignored |
| `tests/test_e2e_processes.py` | Start only the ops stub (`:52–62`); no `KNOWLEDGE_*` environment |
| `deploy/docker-compose.yml` | No knowledge-stub service, alias, port or `KNOWLEDGE_*` variables (`:5`, `:28–29`, `:51–56`) |

### C3: profiles and deployment script (10 files; the base already contains P3)

`scripts/env.sh`, `scripts/run-profile.sh`, `tests/test_profiles.py`, `tests/test_gate_assertions.py:127`, `tests/test_external_transport.py:36–40`, `deploy/environments/mock.env`, `deploy/environments/live.env`, `deploy/environments/README.md` (`:37–53`), `deploy/azure/deploy.sh` (`:70–203`, `:244`, `:249`, `:260`), `tests/test_deploy.py` (deploy-script part `:194–231`).

- **`deploy.sh` no longer handles knowledge.** The canary's leftover knowledge secret and variables, and Key Vault `knowledge-token`, are harmless and are removed only in a separately approved cloud step (§7).
- **Editing only:** these scripts are tested through the existing hermetic tests and never run against Azure (§1 item 6).

### C4: current documents (two commits, 10 files or fewer each)

- **C4a (10 files):**
  - `CLAUDE.md`: "Three MCP tools … consuming Manoj's operational service"; drop Shobhit's ownership line and the `search_knowledge` rule; three-tool bearer; stays under 80 lines;
  - `README.md` (`:3`, `:35`), `services/mcp/README.md` (`:3–6`, `:17`, `:26`, `:31`);
  - **`Makefile`:** `:8` "against the two local development stubs" becomes "against the local operational stub", and `:36` "four tools" becomes "three tools";
  - `services/mcp/pyproject.toml` (description), `.env.example` (`:18–23`, `:42–43`);
  - `docs/handover/mcp-only/PLAN.md` (§6, §7);
  - `docs/DECISIONS.md`: append entry **K3**. It records this decision, the front-desk/Stratum separation (§1 item 9), supersedes K1's knowledge tool, and gives L1's new counts (18 fields, 11 routes). Earlier entries stay unchanged;
  - `.claude/agents/voice-safety-reviewer.md`, `.claude/agents/latency-reviewer.md`.
- **C4b (7 files):** `docs/handover/mcp-only/README.md`, `docs/handover/mcp-only/TARGET-STATE.md`, `docs/architecture/TARGET.md`, `docs/handover/TESTING.md`, `docs/handover/AZURE.md` (including "two owner services" `:3` and the smoke description `:43–49`), `docs/handover/CONTEXTFORGE.md`, `docs/handover/ONBOARDING.md`.
  - **In `CONTEXTFORGE.md`:** select **our** three front-desk tool IDs for **our** virtual server; Stratum is a separate registration, managed by its owners, and a combined view may contain both. Gate 9's discovery check goes here too.
  - Update current instructions only; dated "verified deployment" records stay as written.

## 6. Documents: current versus historical

- **Updated (current):** `VOICE-TEAM.md` (C1) and the files in C4.
- **In `PLAN.md`:** update the status block, the gate list, the tool table and the "four tools" sentences (`:121`, `:168`, `:261`). Add **one** "superseded by K3" note where the knowledge design sections begin, instead of rewriting migration history.
- **Governing documents (unchanged by implementation, excluded from the knowledge residual search):** `docs/handover/mcp-only/implementation/KNOWLEDGE-REMOVAL-PLAN.md` and `docs/handover/mcp-only/implementation/LOG-1-PLAN.md`.
  - **Why excluded:** they specify the removal itself, so they necessarily name `search_knowledge`, `knowledge_client`, `knowledge_contract`, `KNOWLEDGE_*` and "four tools".
  - **What applies instead:**
    - Astra must not edit them, and at C4 they must be byte-identical to the base (§10);
    - the contact-rollback trace search still covers them, and must find nothing.
- **Unchanged (historical):**
  - the rest of `docs/handover/mcp-only/implementation/` (121 historical files);
  - `CURRENT-STATE.md`, `OPUS-REVIEW.md`, `FABLE-MASTER-PROMPT.md`, `OWNER-INTEGRATION-MESSAGES.md`, `AZURE-RETIREMENT.md` (`:48`);
  - `docs/review*`;
  - earlier `DECISIONS.md` entries;
  - Manoj's pinned contracts.
- **Note:** `OWNER-INTEGRATION-MESSAGES.md` contains unsent messages to Shobhit. Don't send them.
- **No contact-rollback trace terms in new text.** The search command is in `.context/contact-rollback/OPUS-REVIEW.md`, and the Astra prompt carries it. Refer to release gates singly ("gate 8") or as a range ("gates 1–9").

## 7. Release gates after this plan (the `PLAN.md` update in C4a)

| Gate | New text (summary) |
|---|---|
| 4 | Deployed-adapter credentials, then deployed-transport gates and release smoke against the canary. **No knowledge host** |
| 5 | ContextForge refresh of **our front-desk entries only** (registration `frontdesk-healthcare-canary`, virtual server `frontdesk-healthcare`) to the new schema, with our `search_knowledge` removed, followed by the LiveKit cached tool view. **Stratum's registration and tools are not touched.** Separately approved |
| 6 | Voice-team readiness for SL1's fields **and the three-tool front-desk server**: the agent no longer calls our front-desk `search_knowledge` |
| **8 (new)** | **Before deployment:** Rajeev's team confirms and tests, through Stratum via ContextForge, the symptom and emergency journeys, including transfer behaviour |
| **9 (new, release safeguard)** | **No live voice traffic** until the three-tool adapter is deployed, our front-desk ContextForge entries and the LiveKit tool view are refreshed, and discovery through the voice client path shows **exactly** the three front-desk tools in the front-desk view. A combined view shows those three plus Stratum's tools, and no front-desk `search_knowledge` |
| Cloud cleanup (not a gate) | After an approved deployment, a separately approved removal of the canary's leftover knowledge secret and variables, and of Key Vault `knowledge-token` |

Gates 1, 2, 3 and 7 keep their meaning. Gate 2's 10 October live evidence is in `.context/live-try/RESULTS.md` (uncommitted); recording it in `PLAN.md` is Garima's decision.

## 8. Tests that prove the result (minimum)

1. **Exactly three tools** are visible to the gateway bearer on **our adapter**. Calling `search_knowledge` there gets an unknown-tool error, with **no owner request** (C1).
2. **`/dependencies`** returns `{"operational": …}` with no `knowledge` key; degraded, caching and refresh behaviour is unchanged. **`/health` and `/ready` tests pass unmodified** (C1).
3. **Smoke** (against our adapter) accepts exactly the three tools and fails when one is missing or a fourth is present (C1; hermetic).
4. **Stratum separation in the registration code** (C1; hermetic, `test_deploy.py`). Against a fake gateway listing that contains:
   - our three prefixed tools;
   - **another registration's tools**, including one whose name contains `search_knowledge`;

   `register.py`'s verification reports **no drift**. A **front-desk-prefixed** `search_knowledge`, by contrast, is reported as "a tool the adapter no longer serves".
5. **LOG-1 revision 6** fail-closed tests (§4); every other LOG-1 and M-1 test passes unchanged (C1).
6. **The interface tests** pass with no `search_knowledge` rows; `make schema` equals the new snapshot (C1).
7. **Availability and booking transcript-independence** tests still pass (C1).
8. **Leftover `KNOWLEDGE_*` variables** are ignored by production settings (C2).
9. **The process e2e test** runs against the ops stub only (C2).
10. **Summary values** `EMERGENCY`, `SYMPTOM_ROUTING` and `EMERGENCY_TRANSFERRED` are still accepted. The existing summary tests cover this; none may be removed.

## 9. Benchmark (required)

- **Why two runs:** a difference needs a baseline, so there are two runs, each once, on the same machine in the same session, with no other heavy work running.
  1. **B0, baseline:** at the base SHA, in the clean worktree, before C1.
  2. **After removal:** at C4's head.
- **Command, identical both times:** the fixture benchmark against in-process stubs, `uv run python dev/bench.py --samples 50 --concurrency 1 --log-level INFO --log-file <file>`. That is production's log level, and it covers both slot modes as the bench runs them. **No live benchmark.**
- **Compare:** every scenario present in both runs, which is all scheduling and booking scenarios. `knowledge_answer` exists only in the baseline and is reported as removed.
- **Report for each scenario:** samples, verified outcomes, first call, p50/p95/p99, and the p50 difference in ms and %.
- **Threshold:** a difference counts as **material** when p50 rises by more than 10% **and** more than 1 ms (the LOG-1 threshold). Any material rise is reported as a finding; it is not hidden or rerun.
- **These are local fixture timings,** not real-service or voice latency evidence.

## 10. Verification (each command once; every first-run failure kept)

**General rule:** each check runs **once**. Its full output is saved under the worktree's ignored `.context/knowledge-removal/` (`<commit>-<check>.txt`). If any check fails, Astra **stops**: no retry, no further commit, and it reports the failure as it stands. External profiles are never loaded. Full-script runs use `env -u OPS_E2E_BASE_URL -u KNOWLEDGE_E2E_BASE_URL`.

| Commit | Checks (in order) |
|---|---|
| **B0** | Baseline benchmark (§9) |
| **C1** | `make test-fast`, then the **schema comparison**: `make schema` output compared byte for byte with `tests/contracts/mcp-tools.snapshot.json`, recording size, SHA-256 and `SCHEMA_VERSION` |
| **C2** | `make test-fast`, then `make test-e2e` (process e2e against the ops stub only) |
| **C3** | `env -u OPS_E2E_BASE_URL -u KNOWLEDGE_E2E_BASE_URL ./scripts/test.sh`: install, lint, hermetic suites, process e2e, package build and both Docker image builds. Docker availability reported honestly |
| **C4** (after C4b) | `make test-fast`; the **schema comparison** again; the **residual searches** below; the **after-removal benchmark** and comparison (§9) |

**Residual searches at C4's head (committed tree):**
1. **Knowledge references:**

   ```
   git grep -n -i -e search_knowledge -e knowledge_client -e knowledge_contract -e "KNOWLEDGE_" -e "four tools" -e "four MCP tools" -e "two owner" -e "two local development stubs" HEAD -- . \
     ':(exclude)docs/handover/mcp-only/implementation/KNOWLEDGE-REMOVAL-PLAN.md' \
     ':(exclude)docs/handover/mcp-only/implementation/LOG-1-PLAN.md'
   ```

   The two governing documents are excluded (§6). Every remaining hit must be in a §6 historical file or in Manoj's contracts. Paste the list.
2. **The governing documents are unchanged:** `git diff --exit-code <base> HEAD -- docs/handover/mcp-only/implementation/KNOWLEDGE-REMOVAL-PLAN.md docs/handover/mcp-only/implementation/LOG-1-PLAN.md` prints nothing.
3. **The contact-rollback trace search** (supplied in the Astra prompt) runs over the whole committed tree, governing documents included, and prints nothing.

**Scope evidence in the hand-back:**
- the base SHA and each commit's file list, matching §5 (any extra file explained);
- `git status --porcelain` empty before each commit, apart from that commit's files;
- the des-moines workspace untouched (its file hashes before and after);
- a statement that **no live action** under §1 item 6 happened, with the commands that were run.

## 11. Risks and how they are handled

| Risk | Handling |
|---|---|
| The voice agent still calls our front-desk `search_knowledge` after deployment | Release order in §3; gates 6, 8 and 9 |
| Stratum's registration or tools get modified by mistake | §1 items 2 and 9; registration code and refresh limited to our prefix and virtual server; §8 item 4 test; no ContextForge action in implementation |
| A similarly named Stratum tool is mistaken for ours | "Stop calling" and the gate 9 checks refer to the **front-desk-prefixed** tool only (§1 item 9) |
| Live calls reach a half-refreshed setup | Gate 9: no live voice traffic until discovery shows exactly the three front-desk tools |
| Emergency journeys fail in Stratum | Gate 8, a deployment blocker owned by Rajeev's team |
| A leftover canary variable stops startup | `extra="ignore"` plus the test in §8 (item 8) |
| LOG-1 loses coverage | Revision 6's no-weakening rule, the correspondence list and the re-review |
| C1's size hides an unintended change | Exact file list. Astra may add a file only if a commit can't pass otherwise, with a reason for each; Opus reviews file by file |
| A commit fails between steps | The import map in §5, the checks for each commit in §10, and stop-on-failure |
| Astra works from a different or uncommitted plan | P4 commits the plan and LOG-1 revision 6 before the base SHA; P6 checks that the worktree copies equal the committed blobs |
| Uncommitted user work gets mixed in | P3 first, then a clean worktree (P6); des-moines is never edited |
| Latency regression | The benchmark comparison in §9 |

## 12. Decisions for Garima

1. **Approve revision 3.**
2. **Confirm the wording of gate 8 and gate 9** in §7, including the front-desk and combined views in gate 9.
3. **P4:** who commits the approved plan and LOG-1 revision 6: you, or Opus at your explicit request.
4. **Optional:** record the 10 October gate 2 live evidence in `PLAN.md` within C4a.
