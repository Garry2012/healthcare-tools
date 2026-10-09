# Opus final review: T-5 repair and call-summary contact fallback

**Commits reviewed:** `980da73..e208d2d` on `Garry2012/slots-phase-1a-1b`.

| Commit | Content | Files |
|---|---|---|
| `151ea61` | T-5: reset sse-starlette's process-wide drain flag per test server | `tests/conftest.py`, `tests/test_server.py` (2) |
| `3b8cf18` | Commit A: contact fallback and tests | `summary.py`, `test_summary.py`, `test_server.py`, `test_e2e_processes.py`, `test_external.py` (5) |
| `e208d2d` | Commit B: publication and evidence | pack, `prompt.py`, snapshot, `VOICE-TEAM.md`, `DECISIONS.md`, `CLAUDE.md`, `PLAN.md`, hand-back (8) |

**Inputs read:**
- the T-5 brief and the contact-fallback build brief;
- the approved plan (revision 2);
- my earlier blocker review (`OPUS-CONTACT-FALLBACK-REVIEW.md`);
- the hand-back;
- `.context/t5/` and `.context/contact-fallback/`.

## 1. Verdicts

| Item | Verdict |
|---|---|
| **Code (all three commits)** | **APPROVED.** No defect. One Low documentation finding, optional and not blocking (§3) |
| **Deployment readiness** | **Not ready.** Release gates 1–9 in `PLAN.md` are all pending, including the new gate 8 (Manoj's provenance wording) and gate 9 (caller-number provenance). Nothing is merged or deployed |

## 2. Requirements

### 2.1 Contact resolution (`summary.py:103–105`)

The code is unchanged from the draft I reviewed. All four other contact files in `3b8cf18` match Astra's recorded draft SHA-256 hashes. `test_server.py` contains exactly the draft's contact hunks on top of T-5.

| Requirement | Status | Evidence |
|---|---|---|
| A valid explicit number wins | Met | `test_explicit_contact_wins_over_header` (header absent, invalid or valid, for both outcomes) |
| Only omitted or null falls back, through the strict converter with the configured country code | Met | `if request.callerMobile is None and ctx.caller_number` uses `identity.contract_mobile(..., tenant_country_calling_code)`. `test_missing_contact_uses_header_without_verification`, `test_contact_conversion_uses_configured_country` |
| Invalid explicit input stays rejected | Met | `test_invalid_explicit_contact_is_not_replaced_by_header`: `""`, `" "`, E.164, short and long values; no POST |
| An ordinary summary may omit an unusable contact; CALLBACK_NOTED needs a usable one | Met | `test_unusable_header_does_not_invent_contact`, with 10 header variants |
| Resolved once, before validation and body building, with no mutation | Met | `model_copy` runs before `_validate` and `build_body`. The test asserts the original request and context are unchanged |

### 2.2 Security and persistence

| Requirement | Status | Evidence |
|---|---|---|
| No verification is needed, and no booking authority is granted | Met | `authorised_mobile` is never called. With `verification=None`, LIST, CANCEL and RESCHEDULE return `IDENTITY_UNAVAILABLE`, and no `/appointments` request is made (`test_summary_http_contact_is_private_and_never_grants_authority`) |
| Contacts never mix between concurrent requests | Met | `test_concurrent_summaries_keep_their_own_call_and_start_time` uses a different header number per call |
| Numbers don't appear in results, logs or protocol errors | Met | The same HTTP test scans tool content, structured results, `meta`, logs (`JsonFormatter`, `caplog`) and stdout/stderr |
| Replay keeps the first saved summary; retries keep the same body | Met | `test_replay_keeps_original_header_contact`; the lost-write test asserts identical retry bodies |
| The external test inspects the real POST and the raw response, honestly | Met, not executed | `test_external.py:199–224`. The request hook checks the posted contact; the response hook reads the raw 201 body and asserts `callerMobile` when it is present, otherwise records "not independently verified". Exactly one 201 is required. No extra owner call, and `OpsClient` doesn't swallow the hook assertions. It stays `BLOCKED` locally at the HTTPS gate, as expected |

### 2.3 T-5 (`151ea61`)

| Requirement | Status | Evidence |
|---|---|---|
| Only `serving()` resets the flag, through `sys.modules` | Met | `conftest.py:349–354`, at the start of `serving`, before the server is created. There is no other reset and no new import |
| The recorder's strictness is unchanged | Met | The diff touches only those six lines in `conftest.py` |
| The regression test seeds True deterministically, is bounded, cleans up, and makes a real MCP request | Met | `test_serving_resets_previous_server_sse_drain_flag`: the child pytest sets `AppStatus.should_exit = True`, then under `serving` makes a real `get_doctor_availability` call (fixed date `2099-01-05`, `asyncio.timeout(10)`). It asserts `AVAILABILITY`, no incident, and `flag_at_start is False`. `subprocess.run(..., timeout=30)` kills the child on timeout |
| A genuine red | Met | `.context/t5/red.txt`: the child failed with `TimeoutError` after the recorder's confirmed incomplete `POST /mcp/` with `sse_should_exit: true`. That is exactly the mechanism |
| No retries, skips, raised timeouts or weakened assertions | Met | Each gate was run once. The original interrupted run (`09-A-fast.txt`) is kept, and the hand-back states its SIGINT contamination as my blocker review did |
| Safe handling of the draft | Met | Only the five paths were stashed (SHA `a98332…`), applied by SHA without conflict, and dropped by identity. All 15 protected file hashes match now (my check). Garima's unrelated changes are untouched and appear in no commit |

### 2.4 Publication and scope (`e208d2d`)

| Requirement | Status | Evidence (my check) |
|---|---|---|
| Version is `2026-10-10.1` | Met | `prompt.py`; the snapshot's `schemaVersion` and its instructions string |
| Only the version and the summary descriptions change | Met | With descriptions stripped and the version normalised, old and new schemas are **structurally equal**. The instructions differ only in the version. `get_doctor_availability`, `manage_booking` and `search_knowledge` are **byte-identical**. `record_call_summary` differs only at `/description` and `/inputSchema/properties/callerMobile/description` |
| Pack, snapshot, VOICE-TEAM, DECISIONS and CLAUDE agree | Met | The same rule text throughout: explicit wins, omitted or null uses the strictly converted header, invalid is rejected, CALLBACK_NOTED needs a usable contact, no authority. VOICE-TEAM separates the E.164 header from the 10-digit argument, and example 4 is retitled correctly. `CLAUDE.md` is 47 lines |
| Historical records intact | Met | `DECISIONS.md` has only additions (14, 0 removed): the S1 supplement, with the explicit storage-approval sentence, and the SL1 supplement. VOICE-TEAM's earlier "Changes in schema …" sections are untouched; a new 2026-10-10.1 section is appended. The pinned contract is unchanged |
| Gates 8 and 9 pending | Met | `PLAN.md` gates 8 and 9, marked "Pending". Gate 5 and the prompt-and-gateway paragraph refer to `2026-10-10.1` |
| File limits per commit | Met | 2, 5 and 8 files, exactly as specified. No unrelated file is in any commit |

## 3. Findings

### L-1 (Low, documentation): three current statements still describe the T-4 mechanism as unfixed

T-5 implemented the "optional test-setup remedy", but these still say otherwise:

- **`CLAUDE.md:46`:** "Never run two `serving()` blocks sequentially in one test process: sse-starlette's process-wide shutdown flag cuts off the second server's event-stream replies (T-4)."
- **`docs/DECISIONS.md:216` and `:220`** (SL1 test-infrastructure paragraph): "Use one `serving()` server per process…" and "An optional test-setup remedy remains separate."
- **`docs/DECISIONS.md:249`** and **`docs/handover/mcp-only/PLAN.md:52`:** list "an optional test-setup remedy for the T-4 mechanism" as an open item.

**What could go wrong:** a future contributor treats an implemented fix as missing, or removes the reset in `serving()` without knowing it is load-bearing. The stated restriction is merely over-strict, so it is not dangerous.

**The cause is mine:** the build brief didn't ask for these updates.

**The fix** (documentation only; optional; not blocking code approval):
- **`CLAUDE.md:46` becomes:** "`serving()` resets sse-starlette's process-wide drain flag at start (T-5); keep that reset. A previous test server's shutdown would otherwise cut off later event streams (T-4)."
- **`DECISIONS.md`:** add a dated SL1/T-5 supplement line saying the remedy is implemented (`151ea61`). Keep the historical lines.
- **`PLAN.md:52`:** remove "an optional test-setup remedy for the T-4 mechanism" from the open items.

### Observations (no action)

- **`VOICE-TEAM.md` describes `X-Caller-Number` as "End caller's own number".** That is the contract we expect the platform to honour. Whether it actually does is gate 9, which is correctly still pending.
- **The T-5 regression test seeds the flag directly** instead of reproducing the watcher's timing. That was the approved deterministic design. T-4's probe remains the evidence for the natural mechanism.

## 4. Commands I ran

Each run was announced beforehand and run once.

| Command | Result |
|---|---|
| `timeout -k 10 300 uv run pytest tests/test_summary.py -q` | **107 passed** |
| `timeout -k 10 300 uv run pytest tests/test_server.py -q -k "sse_drain or recorder or watchdog or serving or summary_http_contact or concurrent_summaries"` | **37 passed**, 47 deselected |
| `timeout -k 10 300 uv run pytest tests/test_e2e_processes.py::test_journey_and_summary_through_real_transport -q` | **1 passed** |
| `PYTEST_ADDOPTS=--tb=short timeout -k 10 900 make test-fast` | **1,209 passed**, 14 deselected, 2 Authlib warnings, exit 0 (`.context/opus-final-fast.txt`) |
| `make schema` to a file, then `cmp` with the committed snapshot | identical; 64,603 bytes; SHA-256 `d6660205…4fdf`; version `2026-10-10.1` |
| A structural comparison script, `980da73` snapshot against the new one | structurally equal; three tools byte-identical; two description paths changed in the summary tool |
| `ruff check . ../../deploy` | All checks passed |
| `git diff --check 980da73 e208d2d` | clean |
| A protected-hash comparison (15 files) | no mismatches |

**Inspected but not rerun:**
- `./scripts/test.sh`: 1,209 hermetic and 5 e2e tests; all suites passed; the hand-back says the Docker builds actually ran;
- the local external runs in both slot modes: **6 `BLOCKED` and 3 passed in each.** These are expected `BLOCKED` gates, not a passing external suite;
- Vulture (no findings, identical to the baseline);
- T-5's red and green, and both recorded gate runs (1,166 and 1,209 passed).

## 5. Not verified

- **Live storage by Manoj:** whether the response echoes `callerMobile` is unknown. The external hooks have never run.
- **Caller-number source in production:** gate 9.
- **Manoj's provenance wording:** gate 8.
- **ContextForge and voice discovery refresh** to `2026-10-10.1` (gate 5), and voice-team readiness (gate 6).
- **The live bench** (gate 3), **LOG-1** (gate 7, open), and **merge and deployment approval** (gate 1).

## 6. Result

**APPROVED.** The code and publication in `151ea61`, `3b8cf18` and `e208d2d` are correct. L-1 is an optional documentation tidy-up.

**Not ready to deploy:** gates 1–9 are pending.

## 7. Plain-English summary for Garima

**The work is correct.**
- If the voice agent gives a callback number, that number is used. Otherwise the calling number is used, converted strictly.
- Bad numbers are still rejected. Callback summaries still require a usable number. The calling number never grants booking access, and it never shows up in results or logs.
- The test-setup fix (T-5) cleanly removes the old flag problem. The full suite now passes: 1,209 tests, which I reran myself.
- Only the summary tool's descriptions and the version changed in the published interface. Everything else is identical, which I checked byte for byte.

**One small optional tidy-up:** three places in the docs still say the T-4 flag problem is unfixed. It now is.

**Still needed before release:** your merge and deployment approval, Manoj accepting the caller-ID wording, and the voice platform confirming the header is really the caller's own number, plus the earlier gates (live test, live bench, credentials, ContextForge refresh, voice readiness, LOG-1).
