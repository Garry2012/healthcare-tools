# LOG-1 plan: no sensitive values in production logs

- **Status:** **Revision 6, approved by Garima on 11 October 2026,** after two wording corrections: the accepted `path` set in §R.1, and "caller-provided reason text" in the goal. It adapts LOG-1 to the three-tool server in `KNOWLEDGE-REMOVAL-PLAN.md` (revision 3, approved 11 October 2026).
- **Revision 4:** approved on 10 October 2026, and implemented in `7bf7275`, `b7feb3c`, `29b0562` and `7c44955` (historical record below). Garima also decided to keep both `callId` and `summaryId` in the safe logs for correlation.
- **Revision 6 changes no code by itself.** Its only execution path is **knowledge-removal commit C1**, verified by the removal plan's §10.
- **Approval scope:** implementation only, not merge or deployment.
- **Gate:** release gate 7 (`docs/handover/mcp-only/PLAN.md`).

**Goal:** no caller number, patient name, caller-provided reason text, tool argument or secret can reach production logs, or unexpected-error tool results, while safe and useful diagnostics are kept and voice latency is not affected.

## Changes in revision 6 (Garima's review of revision 5, 11 October 2026)

| # | Garima's point | Where |
|---|---|---|
| 1 | Mark the revision 4 material as historical, implemented and not executable; supersede its future-tense instructions | The banner before the historical record; §6 of the record replaced; §5 of the record marked executed. The revision 5 annotations in the record are reverted, so it reads exactly as revision 4 |
| 2 | Update `test_log1_fields_reject_containers_and_allow_none`, and prove `field` is omitted for `None`, strings and containers | §R.2, item 2 |
| 3 | Tests 9, 10 and 7g use the three-tool harness, with no knowledge setup; privacy assertions unchanged | §R.2, item 1 |
| 4 | Test **every** knowledge-only outcome and next step as omitted, and the shared scheduling values as still accepted | §R.2, item 3 |
| 5 | "other 17 field checks" corrected; at approval, reworded to "18 remaining field-checking mechanisms", with `path` added to the shrinking accepted sets | §R.1 |

## Current specification (revision 6): the three-tool server

**Execution path:** the only implementation is **knowledge-removal commit C1**, verified by the removal plan's §10 (C1: `make test-fast` plus the schema comparison; C3: full `./scripts/test.sh`). Revision 6 and the removal plan are both **committed before** Astra's base SHA is recorded (removal plan §3, step P4). Nothing in the historical record is executed.

### R.1 Code changes in `server.py` (all in C1)

| Item | Revision 4 (implemented) | Revision 6 |
|---|---|---|
| `tool` | `_known(tools.TOOL_NAMES)`, 4 names | **Same expression;** 3 names, because `TOOL_NAMES` drops `search_knowledge` |
| `outcome` | `get_args` of Availability, Booking, **Knowledge** and Summary outcomes | Availability, Booking and Summary outcomes only. **No longer accepted** (knowledge-only): `ANSWERED`, `NO_ANSWER`, `ROUTING_REQUIRED` |
| `nextStep` | `get_args` of `NextStep`, `BookingNextStep`, **`KnowledgeNextStep`** | `NextStep` and `BookingNextStep` only. **No longer accepted** (knowledge-only): `ASK_CLARIFICATION`, `CHECK_AVAILABILITY`, `SAY_NO_ANSWER_AND_OFFER_DESK`, `SPEAK_ANSWER`, `TRANSFER_EMERGENCY` |
| `field` | `knowledge_contract.AnswerResponse.model_fields` (`answer`, `department`, `destination`, `outcome`, `sourceId`) | **Entry deleted.** `field` becomes an unknown name, omitted with its name in `omittedFields` for any value, `None` included (`server.py:163–173`) |
| `path` | 12 route templates, including `knowledge_contract.ANSWER_PATH` (`/v1/answer`) | **11 templates.** `/v1/answer` matches no route and is omitted |
| Imports | `knowledge_contract` | Removed from `server.py` |

**The field table becomes 18 names:** `attempt`, `callId`, `detail`, `env`, `error`, `header`, `httpStatus`, `model`, `nextStep`, `outcome`, `pack`, `path`, `reason`, `retryAfterSeconds`, `schemaVersion`, `status`, `summaryId`, `tool`.

**Shared values stay accepted.** Values that the knowledge enums shared with the scheduling enums keep passing, because they come from the scheduling enums (checked with `typing.get_args` at `42dae2c`):
- outcomes `CLARIFICATION_NEEDED`, `COULD_NOT_CHECK`, `INVALID_REQUEST`;
- next steps `TRANSFER_DESK`, `SAY_COULD_NOT_CHECK`, `ASK_TO_REPHRASE`.

**Knowledge log events are no longer emitted** by the server:
- `knowledge_unreachable`, `knowledge_rejected_adapter_credentials`, `knowledge_error` and `knowledge_answer_malformed` are deleted with `knowledge_client.py` in C1;
- `knowledge_optional_field_dropped` stays in `knowledge_contract.py` until C2, but nothing in the server calls it after C1.

**Unchanged:**
- `JsonFormatter`'s logic;
- **the 18 remaining field-checking mechanisms.** The accepted sets for `tool`, `outcome`, `nextStep` and `path` shrink as listed above; `field` is removed entirely;
- `SAFE_LIBRARY_MESSAGES`;
- the frame helper and the M-1 guard (`record.exc_info[0] is not None`);
- `configure_logging`;
- `mask_error_details=True`;
- `QUIET_LOGGERS`;
- the adapter call sites.

### R.2 Test changes (`services/mcp/tests/test_server.py`, in C1)

**1. Three-tool harness, with no knowledge setup.** These tests build the app as `create_app(h.settings, ops_transport=h.ops.http._transport, clock=h.clock)`, with **no** `knowledge_transport`, `h.knowledge` or `knowledge_contract`:

| Test | Today's knowledge setup | Change |
|---|---|---|
| 9: `test_log1_all_six_logging_sources_have_one_json_owner` | Child script passes `knowledge_transport=h.knowledge.http._transport` (`:1487`) | Removed. **Privacy assertions unchanged:** each of the six records exactly once, as our JSON, with `library_message_omitted`; no fake value in stdout or stderr; stderr holds only the known import warnings; the `fastmcp` logger has no handlers of its own and propagates |
| 10: `test_log1_private_data_stays_out_of_real_http_logs_and_unexpected_errors` | Child script passes `knowledge_transport=…` (`:1549`) | Removed. **Privacy assertions unchanged:** no fake value in stdout or stderr; leak records redacted, with `exception` and `frames`; uvicorn lifecycle visible; masked tool-error content; `callerMobile` absent from the stored summary |
| 7e: `test_log1_all_observed_owner_routes_are_templated` | Calls `search_knowledge` (`:1614`) | The harness run uses the three tools only. The expected set has no `/v1/answer`. Every observed path still maps to a template |
| 7g: `test_log1_real_adapter_events_keep_every_permitted_value` | Imports `knowledge_contract` (`:1637`), passes `knowledge_transport` (`:1643`), triggers `knowledge_optional_field_dropped` (`:1662`), lists it among the events (`:1688`) | All four knowledge parts removed. **Every other event and value assertion unchanged** |
| M-1: `test_log1_exc_info_without_an_active_exception_keeps_logs_private` | none | **Unchanged** |

**2. `field` is no longer permitted.**
- **`test_log1_fields_reject_containers_and_allow_none`:** remove `"field"` from its parameter list, leaving the 18 names in §R.1. Its assertions are unchanged.
- **New test, for example `test_log1_field_is_no_longer_a_permitted_name`,** parametrised over `None`, `"sourceId"` (valid in revision 4), `"zelda_fakename"`, `{"token": "SECRETTOKENXYZ"}` and `["Zelda Fakename"]`. For each value:
  - `omittedFields == ["field"]`;
  - `"field"` is not in the JSON;
  - no `LOG1_PRIVATE` value appears in the line.

**3. Every knowledge-only value is omitted; shared values are accepted.**
- **New parametrised omission test,** or rows added to 7c `test_log1_secret_shaped_values_are_not_safe_codes`. Each value below is omitted, with `omittedFields == [<name>]`:
  - `tool`: `search_knowledge`;
  - `outcome`: `ANSWERED`, `NO_ANSWER`, `ROUTING_REQUIRED`;
  - `nextStep`: `ASK_CLARIFICATION`, `CHECK_AVAILABILITY`, `SAY_NO_ANSWER_AND_OFFER_DESK`, `SPEAK_ANSWER`, `TRANSFER_EMERGENCY`.

  These are literal values, because their source types are deleted in C1. A comment names them as the former knowledge-only values.
- **New parametrised acceptance test:** each value below is kept unchanged, with no `omittedFields`:
  - `outcome`: `CLARIFICATION_NEEDED`, `COULD_NOT_CHECK`, `INVALID_REQUEST`;
  - `nextStep`: `TRANSFER_DESK`, `SAY_COULD_NOT_CHECK`, `ASK_TO_REPHRASE`.
- **Every existing 7c row stays,** including `field="zelda_fakename"`, whose expectation (omitted and listed) still holds.

**4. Routes:** 7d `test_log1_owner_paths_discard_ids_and_refuse_unknown_routes` gains `path="/v1/answer"`, which must be omitted.

**5. Unchanged:** tests 1–6, 7a, 7b, `test_log1_invalid_primitives_are_omitted`, `test_log1_context_call_id_uses_the_existing_syntax_check`, test 8 and the regression tests (11). Apart from the harness change in item 1, the same applies anywhere a `search_knowledge` call was used only to generate traffic: it is replaced with a scheduling tool call, and each replacement is listed in the hand-back.

**No weakening:** each removed or changed LOG-1 assertion must match a deleted tool, outcome, next step, field, route or event (§R.1). The hand-back lists every removed or changed assertion against that list.

### R.3 Verification (within the removal plan only)

- **C1:** `make test-fast` runs every LOG-1 and M-1 test, including the §R.2 additions. Then the schema comparison: the new `SCHEMA_VERSION` comes from the removal, not from LOG-1.
- **C3:** the full `./scripts/test.sh` runs them again.
- **No probe rerun:** revision 6 only removes accepted values and adds no output path. Tests 9 and 10 cover the remaining probe flows.
- **No revision 4 benchmark:** the removal plan's §9 benchmark (B0 and after C4) covers the latency rule.
- **Gate 7** stays "implemented; awaiting review and Garima's closure". Opus re-reviews LOG-1 as part of the removal review.

---

# Historical record: revisions 1–4 (implemented; not executable)

> **Everything below this line is historical.** It records the revision 4 design and its earlier corrections. Revision 4 was approved on 10 October 2026 and implemented in `7bf7275` (P), `b7feb3c` (A), `29b0562` (B) and `7c44955` (M-1). Its future-tense wording ("commit P", "commit A", "before and after", "rerun the probe", base `e53eee2`, schema `2026-10-08.1`, "four tools", "19 names") describes work **already done**.
>
> **Do not execute any of it:**
> - do not recreate commits P, A or B;
> - do not use base `e53eee2`;
> - do not expect schema `2026-10-08.1`;
> - do not rerun `.context/log1/probe.py`;
> - do not repeat the revision 4 WARNING or INFO benchmarks.
>
> Where it differs from the revision 6 specification above, revision 6 wins.

## Revision 4: exact values instead of shape checks

**The gap Garima found:** revision 3's shape checks still accepted secret-shaped values, such as `reason="SECRETTOKENXYZ"`, `detail="JOHN_SMITH"` and `error="BearerSecretAlphaToken"`. Its tests used values that failed the shapes, so they proved nothing.

1. **Codes:** `outcome`, `nextStep`, `detail` and `reason` accept **only exact internal values,** taken from the existing enums and constants (§2.2). No regex.
2. **Type names:** `error` and `model` accept **only known internal class names,** taken from the actual exception and model classes. Unknown names are omitted.
3. **Paths:** raw dynamic paths are **never kept.** A path is converted to its known route template (for example `/doctors/{id}`, `/appointments/{id}/cancel`); a path matching no known route is omitted.
4. **Tests use secret-shaped values that would have passed revision 3's checks,** and prove they are omitted (test 7).
5. **New sources:** three tiny, behaviour-free source changes give these exact values a single home where no constant existed yet (§4, commit A).

The revision 3 INFO-level latency measurement and every other decision stay unchanged.

## Revision 3: Garima's corrections

1. **Benchmarking at INFO.** `make bench` runs with `log_level="WARNING"` (`dev/bench.py:245`), so it never formats the INFO success logs. The existing benchmark stays as it is. A controlled INFO-level measurement is added before and after, with the logs captured identically (§5).
2. **Field values are checked as well as field names.** Each permitted field has its own fail-closed check. A value that fails is dropped, and only its field name is reported. A test proves that sensitive text under an allowed key such as `reason` or `detail` is omitted (§2.2, test 7).
3. **Success logs:** the requirement is now "**no new** success-path log lines". Today's success logs are `tool_result` (once per tool call) and `summary_saved` (once per newly saved summary), and they stay exactly as they are (§5).

## Revision 2: changes from Garima's review

1. **FastMCP's "Error calling tool" message is not allowlisted.** The installed source builds it as an f-string (`fastmcp/tools/tool_manager.py:166`, `logger.exception(f"Error calling tool {key!r}")`), so `record.msg` is already filled in. It is omitted like any other library message.
2. **New: a strict allowlist of adapter field names.** Unknown fields are dropped (§2.2), and a test proves it (test 7).
3. **The logging-ownership test covers six sources:** root, FastMCP, `mcp`, uvicorn, docket and an arbitrary library (test 9).
4. **This work is limited to this repository's MCP server.** No ContextForge change of any kind (§4).
5. **New: voice latency is a requirement that must not regress** (§5). The benchmark runs before and after, and is reported honestly.

## 1. Evidence: every logging path

### 1.1 How logging is wired today (verified in the code)

| Path | What it does | Where it goes |
|---|---|---|
| **Adapter loggers** (`frontdesk_mcp.*`) | Fixed event names plus chosen `fields`. There are 30 calls; none uses `%` placeholders or f-strings. The field names in use (complete list): `attempt`, `callId`, `detail`, `env`, `error`, `field`, `header`, `httpStatus`, `model`, `nextStep`, `outcome`, `pack`, `path`, `reason`, `retryAfterSeconds`, `schemaVersion`, `status`, `summaryId`, `tool`. The `path` values are owner paths with IDs only, never query strings (`ops_client.py:368–416`). | Root handler, JSON, stdout |
| **Root handler** | `configure_logging` (`server.py:67–73`), called once in `create_app` (`server.py:159`), puts one `StreamHandler(stdout)` with `JsonFormatter` on the root | stdout |
| **`JsonFormatter`** (`server.py:39–60`) | Writes `record.getMessage()`, with **values filled in**, and copies **any** `fields` dictionary. **No redaction and no field control.** It ignores `exc_info`, so it writes no tracebacks. | — |
| **`QUIET_LOGGERS`** (`server.py:64`) | Sets `httpx`, `httpcore`, `uvicorn.access`, `mcp` and `docket` to WARNING. Levels only. | — |
| **uvicorn** | `cli.py:52`: `log_config=None`, so no handlers of its own; `uvicorn.error` propagates to the root | Root JSON, stdout |
| **FastMCP** | `fastmcp/__init__.py:9–13` configures logging on import (`log_enabled` defaults to True; `FASTMCP_LOG_ENABLED` is unset). `utilities/logging.py:56–107`: logger `fastmcp` at INFO, `propagate=False`, two Rich handlers on **stderr**, one printing **tracebacks with exception messages**. | stderr, bypassing our JSON |
| **`mcp` library** | `mcp.*` loggers, **plus direct root-logger calls**: `logging.warning(...)` in `mcp/shared/session.py:383`, `:422`, `:430`; and `:384` at DEBUG | Root JSON, stdout |
| **Python `warnings`** | The Authlib deprecations at import. No data. | stderr |

### 1.2 What reaches the logs: the probe

The probe is `.context/log1/probe.py`, uncommitted. It ran once against the local stubs, through real MCP over HTTP, at production `LOG_LEVEL=INFO`, with fake values: `Zelda Fakename`, `9876501234` (header `+919876501234`), `SECRETREASONPAIN` and `SECRETTOKENXYZ`. All of stdout and stderr were captured (`.context/log1/`).

| Flow | Log output | Leak? |
|---|---|---|
| availability by name; CREATE with name, number and reason; LIST; summary with private text; owner 500 on POST | adapter events plus uvicorn lifecycle | No |
| wrong-type or unknown summary argument; bad bearer | nothing logged | No |
| malformed trusted headers carrying the secret | `trusted_header_malformed` with the header **name** only | No |
| **malformed JSON-RPC request** carrying the name and the secret | root WARNING (`mcp/shared/session.py:383`): `Failed to validate request: …`, with pydantic `input_value=` reprs. **The secret reached our JSON stdout.** | **LEAK 1** |
| **unexpected exception in a tool**, with the values in its message | FastMCP's Rich traceback (`tool_manager.py:166`) printed `RuntimeError: unexpected failure for Zelda Fakename 9876501234 SECRETTOKENXYZ` to **stderr** | **LEAK 2** |

**The same routes exist but were not triggered:** `mcp/shared/session.py:430` (the whole notification message), `:384` (DEBUG, the whole message), and `mcp/server/lowlevel/server.py:713` (exception text).

**Results path:** `build_mcp` (`server.py:114–119`) leaves FastMCP's `mask_error_details` at False, so an unexpected tool exception's message is also returned to the client (`tool_manager.py:167–170`).

### 1.3 Root cause

1. `JsonFormatter` fills in every record's values and copies every `fields` dictionary, regardless of where the record came from.
2. FastMCP adds a second, unfiltered output on stderr.

**Raising levels does not fix this,** because both leaks are WARNING or higher. **Switching off FastMCP's handler alone does not fix it either,** because `JsonFormatter` would still print the values.

## 2. Solution: one owner, one rule, all in `server.py`

### 2.1 One output

In `configure_logging`, after the root handler is set (FastMCP is already imported by then):
- remove the `fastmcp` logger's own handlers;
- set it to `propagate=True` and `NOTSET`;
- leave `QUIET_LOGGERS` unchanged.

**No deployment configuration changes.** Every record then reaches the single JSON handler on stdout.

### 2.2 One rule in `JsonFormatter`: no values are filled in, and only allowlisted fields are kept

**Adapter records** (`frontdesk_mcp` and `frontdesk_mcp.*`):
- `msg` is `record.msg`, the fixed event name, without filling in values;
- `fields` are checked against **`SAFE_LOG_FIELDS`**, a single table mapping each of the 19 permitted names in §1.1 to **its own value check**;
- **unknown names are dropped;**
- **a value that fails its check is dropped (fail-closed),** and only its name is added to `"omittedFields"`, so a reader can see that something was withheld without seeing it;
- `None` is kept for every permitted field.

**The per-field checks.** Each permitted field accepts only exact values built once, at import, from the code that produces them. Nothing is hand-typed where a constant exists, and nothing uses a regex for codes or type names.

| Field | Accepted value (anything else is dropped) | Built from |
|---|---|---|
| `tool` | the four tool names | the names registered in `tools.register` (also the pack's `tools` keys) |
| `outcome` | an exact outcome value | `typing.get_args` of `outcomes.AvailabilityOutcome`, `BookingOutcome`, `KnowledgeOutcome` and `SummaryOutcome` |
| `nextStep` | an exact next-step value | `get_args` of `outcomes.NextStep`, `BookingNextStep` and `KnowledgeNextStep` |
| `detail` | an exact read-failure detail | the values of `schedule_reader.READ_FAILURE_DETAILS` (new constant, below) plus `availability.DIRECTORY_FAILURE_DETAIL` (new constant, below). These are the only details any log call emits (`availability_could_not_check`) |
| `reason` | an exact failure reason | `get_args` of `summary.SummaryFailureReason` (new type, below) and `ops_client.UnavailableReason` |
| `error` | a known exception class name | `{c.__name__ for c in schedule_reader.READ_ERRORS}`, plus every subclass of `httpx.RequestError` (walked once at import), plus `TimeoutError`. Those are exactly the classes the adapter's `except` blocks log |
| `model` | a known contract model name | the pydantic model classes defined in `contract` (the models `ops_client._parse` validates) |
| `field` | a known knowledge model field | the `model_fields` names of the `knowledge_contract` answer model (the only `field` log, `knowledge_optional_field_dropped`) |
| `header` | a trusted header name | the keys of `context.FIELD_OF_HEADER` |
| `path` | **a route template, never the raw path** | one table in `server.py` mapping each owner route the clients call to its template:<br>• `/auth/token`, `/departments`, `/doctors`, `/doctors/{id}`, `/availability`, `/availability/{id}/slots`, `/capabilities`, `/appointments`, `/appointments/{id}/cancel`, `/appointments/{id}/reschedule`, `/call-summaries`;<br>• `knowledge_contract.ANSWER_PATH`.<br>The `{id}` segment is matched and **discarded**. A path that matches no route is omitted. A test (7e) proves every request path seen in a recorded harness run maps to a template |
| `callId` (field and context value) | the trusted call-ID syntax (`context._ID`, reused) | **Retained by design** as the cross-service correlation key (`JsonFormatter`'s purpose, `server.py:40`). It is platform-generated, comes only from the trusted header, and is syntax-limited. It cannot be enumerated, so it is a **stated residual risk** (§4) |
| `summaryId` | `summary._LOG_ID`, reused | **Retained by design.** It is owner-generated and already limited to `cs_…` or a UUID. Stated residual risk (§4) |
| `status`, `httpStatus` | an integer from 100 to 599 (booleans excluded) | — |
| `attempt` | an integer from 1 to 10 | — |
| `retryAfterSeconds` | an integer from 0 to 86,400 | — |
| `env` | one of `get_args` of the `Settings.env` literal type | `config.Settings` |
| `pack` | the names of the packs shipped in `packs/` | `packs` |
| `schemaVersion` | exactly `prompt.SCHEMA_VERSION` | `prompt` |

**The three behaviour-free sources that commit A adds,** because no constant exists today:
- `schedule_reader.READ_FAILURE_DETAILS`: the existing dictionary inside `read_failure_detail`, moved to module level. The function is unchanged otherwise.
- `availability.DIRECTORY_FAILURE_DETAIL = "DIRECTORY_UNAVAILABLE"`, used by its one existing call (`availability.py:75`).
- `summary.SummaryFailureReason = Literal["CALL_ID_MISSING", "STARTED_AT_MISSING", "UNEXPECTED_STATUS", "NO_VERIFIED_RESPONSE", "MALFORMED_SUCCESS", "CALL_ID_MISMATCH"]`, typed onto `_failure`'s `reason` parameter, together with `ops_client.UnavailableReason`. These six values are exactly the ones `summary.py` passes today.

None of these changes behaviour or output.

`provider` is kept as today; it comes from configuration, not request data.

The output for today's records is unchanged; test 8 proves it.

**All other records** (libraries and the root logger):
- `msg` is `record.msg` **only if** it is a string in `SAFE_LIBRARY_MESSAGES`; otherwise it is `"library_message_omitted"`;
- values are never filled in, and no `fields` are kept;
- `logger` and `level` are always kept.

`SAFE_LIBRARY_MESSAGES` holds exact **unfilled** templates, each checked against the installed source during implementation:
- the uvicorn lifecycle: "Started server process [%d]", "Waiting for application startup.", "Application startup complete.", "Application startup failed. Exiting.", "Uvicorn running on %s://%s:%d (Press CTRL+C to quit)", "Shutting down", "Waiting for application shutdown.", "Application shutdown complete.", "Finished server process [%d]";
- uvicorn's "Exception in ASGI application\n" and "ASGI callable returned without completing response.";
- mcp's "No response message received before stream closed".

**Excluded:** FastMCP's "Error calling tool …" (already filled in), and any other f-string message.

**Records with `exc_info` only:**
- add `"exception"`: the type name only;
- add `"frames"`: up to the last 10 frames from `traceback.extract_tb`, as `"<path relative to site-packages or the repo>:<line> in <function>"`;
- never the exception message, locals, arguments or source lines.

Frames are processed **only** for error records (§5). The helper is small and private to `server.py`. It reuses the frame-location idea from `tests/conftest.py`; production does not import test code.

### 2.3 Unexpected errors in results (approved)

`build_mcp` sets `mask_error_details=True`.
- **What it changes:** an unexpected exception's message is no longer returned to the voice agent.
- **What it keeps:** `ToolError` messages we raise on purpose, including `SummaryErrorRedaction`, are unchanged. Normal results and validation behaviour are unchanged.

### 2.4 The two leaks after the change

| Leak | After the change |
|---|---|
| Leak 1 | `{"logger": "root", "level": "WARNING", "msg": "library_message_omitted"}` |
| Leak 2 | One JSON line: `{"logger": "fastmcp.tools.tool_manager", "level": "ERROR", "msg": "library_message_omitted", "exception": "RuntimeError", "frames": [...]}`. Nothing on stderr. The client receives FastMCP's masked text. |

## 3. Privacy tests (written to fail first)

Every test uses only fake values: the name `Zelda Fakename`, the number `9876501234` and `+919876501234`, a fake reason, a bearer-like secret, and a dictionary of tool arguments.

### Formatter unit tests (`test_server.py`)

1. A library record whose `msg` already contains the fake values gives `library_message_omitted`, with no value in the line.
2. A library template with args containing the fake values: the args are never filled in.
3. An allowlisted uvicorn template is kept, unfilled.
4. FastMCP's real "Error calling tool 'record_call_summary'" text (as `record.msg`) gives `library_message_omitted`.
5. A root-logger record is treated as a library record.
6. A record with `exc_info` whose message carries the fake values: only `exception` and `frames` appear.
7. **Field names and values:**
   - **(a) Known fields:** an adapter record with `tool`, `outcome` and `nextStep` gives the same JSON as today.
   - **(b) Unknown names:** the same record plus unknown fields (`patientName`, `callerNumber`, `arguments`, `token`) carrying the fake values. The unknowns are dropped and no value appears.
   - **(c) Secret-shaped values that would have passed revision 3's checks** (upper-snake codes, Python identifiers, a clean path). Each must be **omitted**, its field name listed in `omittedFields`, with no fake value anywhere in the line:

     | Field | Value |
     |---|---|
     | `reason` | `"SECRETTOKENXYZ"` |
     | `detail` | `"JOHN_SMITH"` |
     | `outcome` | `"ZELDA_FAKENAME"` |
     | `nextStep` | `"CALL_9876501234"` |
     | `error` | `"BearerSecretAlphaToken"` |
     | `model` | `"ZeldaFakename"` |
     | `field` | `"zelda_fakename"` |
     | `pack` | `"zelda-fakename"` |
     | `header` | `"x-zelda-fakename"` |
     | `tool` | `"lookup_patient"` |
     | `env` | `"zelda"` |
     | `schemaVersion` | `"2026-10-10.9"` |

   - **(d) Paths are templated, never kept:**
     - `path="/doctors/doc_zelda_9876501234"` gives `"/doctors/{id}"`;
     - `path="/appointments/SECRETTOKENXYZ/cancel"` gives `"/appointments/{id}/cancel"`;
     - in both, the identifier appears nowhere in the line;
     - `path="/zelda/fakename"` and `path="/appointments?mobile=9876501234"` are omitted.
   - **(e) Route coverage:** every request path the ops and knowledge clients send during a recorded harness run (all four tools) maps to a template. Nothing real is omitted.
   - **(f) Wrong types:** a known field holding a dictionary or list of fake arguments is dropped, and `status=True` or `status="404"` is dropped.
   - **(g) Every real value passes:** each value the adapter logs today is accepted and shown unchanged, apart from paths, which become their templates. The values are taken from the actual log calls: `ops_write_server_error`, `ops_unreachable` (with a real httpx exception), `summary_write_unverified`, `summary_saved`, `trusted_header_malformed`, `availability_could_not_check`, `ops_malformed_success`, `knowledge_optional_field_dropped` and `service_started`.
8. `test_log_lines_carry_the_call_id_not_the_caller` stays green unchanged.

### Ownership test, in a subprocess

9. After `create_app` and `configure_logging`, one record carrying the fake values is emitted from each of these six sources:

   | Source | Logger and level |
   |---|---|
   | root | `logging.warning` |
   | FastMCP | `fastmcp.tools.tool_manager`, at ERROR with `exc_info` |
   | mcp | `mcp.shared.session`, at WARNING |
   | uvicorn | `uvicorn.error`, at ERROR |
   | docket | `docket.worker`, at WARNING |
   | an arbitrary library | `some.thirdparty.module`, at WARNING |

   **Assert from the child's captured stdout and stderr:**
   - each record appears **exactly once**, as a parseable JSON line through our formatter, with the expected `logger` name and `library_message_omitted`;
   - no fake value appears anywhere;
   - stderr holds no log output (only the known Authlib import warnings);
   - the `fastmcp` logger has no handlers of its own and propagates.

### End-to-end test, in a subprocess

10. Real server, real MCP over HTTP, capturing the child's whole stdout and stderr:
    - (a) a malformed JSON-RPC request with fake arguments;
    - (b) a tool raising an unexpected exception whose message carries the fake values (injected in the child, as the probe does);
    - (c) normal CREATE, LIST and summary flows with the fake name, number and reason.

    **Assert:**
    - no fake value appears in stdout or stderr;
    - the leak records appear redacted, with `exception` and `frames`;
    - the uvicorn lifecycle messages are still visible;
    - for (b), **the tool result content contains no fake value** (`mask_error_details`).

    Use fixed harness data, a hard timeout, and child cleanup on timeout.

### Regression

11. The recorder privacy tests, the T-5 regression test and `SummaryErrorRedaction`'s private-validation test (`test_invalid_summary_does_not_echo_private_input_in_protocol_or_logs`) all stay green unchanged.

## 4. Scope

- **Repository:** this MCP server only, on `Garry2012/slots-phase-1a-1b`, on top of `e53eee2`, in the same unreleased release.
- **No change to:**
  - ContextForge (registration, configuration, scripts);
  - deployment configuration, environment files, the Dockerfile;
  - dependencies, log levels, `QUIET_LOGGERS`;
  - adapter log call sites;
  - the test recorder;
  - the schema (`make schema` stays byte-identical at `2026-10-08.1`).

| Commit | Files |
|---|---|
| **P: bench log level (preparatory, made before the before-measurement)** | `services/mcp/dev/bench.py` (optional `--log-level` defaulting to `WARNING`, and `--log-file`); `services/mcp/tests/test_bench.py` |
| **A: code and tests** | • `services/mcp/src/frontdesk_mcp/server.py`: `configure_logging`, `JsonFormatter`, `SAFE_LOG_FIELDS` with the exact-value checks, the route-template table, `SAFE_LIBRARY_MESSAGES`, the frame helper, `mask_error_details=True`;<br>• `schedule_reader.py`: `READ_FAILURE_DETAILS` moved to module level;<br>• `availability.py`: the `DIRECTORY_FAILURE_DETAIL` constant;<br>• `summary.py`: the `SummaryFailureReason` type;<br>• `services/mcp/tests/test_server.py`.<br>6 files. The three source edits are behaviour-free and exist only so the allowlists are built from one source of truth |
| **B: documents** | `CLAUDE.md` (the results-and-logs rule as implemented, replacing "LOG-1 remains an open pre-deployment gate"); `docs/DECISIONS.md` (a new dated L1 entry: evidence, the decision, alternatives rejected, the remaining risk, the latency result); `docs/handover/mcp-only/PLAN.md` (gate 7: "implemented; awaiting review and Garima's closure") |

**No other filters, wrappers or library patches.**

### Rejected alternatives

| Alternative | Why rejected |
|---|---|
| `FASTMCP_LOG_ENABLED=false` in deployment only | Leaves Leak 1, and is a deployment change |
| Raising library levels | Both leaks are WARNING or higher, and diagnostics would be lost |
| Regex redaction of free text | Unreliable; T-3 chose an allowlist |
| Filters on each logger | Scattered, and new loggers escape them |
| A denylist of field names | A future unknown field would pass; Garima asked for an allowlist |
| Patching FastMCP or mcp | An upstream concern |

### Remaining risks

- **Lost text:** library text outside the allowlist is lost. Exception types and frames make up for most of it.
- **Upgrades:** the library allowlist must be checked when libraries are upgraded. An unknown message is omitted, never leaked.
- **New adapter fields:** a new adapter field needs a deliberate `SAFE_LOG_FIELDS` entry. Until then it is dropped, never leaked.
- **New codes, classes or routes:** a new code, exception class or route that isn't yet in its source set is omitted, never leaked, until its source is updated. Test 7g catches that during development.
- **`callId` and `summaryId` keep their values by design.** `callId` is the cross-service correlation key; it is platform-generated, comes only from the trusted header, and is syntax-limited. `summaryId` is owner-generated and limited to `cs_…` or a UUID. Neither is caller input, but neither can be enumerated. **Garima decided on 10 October 2026 to keep both,** for correlation.
- **Before start-up:** FastMCP's import-time handler is active until `create_app` runs, during start-up only, before any request.
- **Production check:** after deployment, a quick look at the container logs confirms the format.

## 5. Voice latency: must not regress (revision 4; the benchmarks below were executed for revision 4 and are not to be repeated)

**Rules for the implementation:**
- no new REST calls, waits, locks or background tasks;
- **no new success-path log lines.** Today's success logs stay exactly as they are and are the only ones: `tool_result` (INFO, once per tool call) and `summary_saved` (INFO, once per newly saved summary). The INFO measurement below counts log lines by message before and after, and the counts must be identical;
- filtering is constant-time per emitted record: one prefix check, set lookups for field names and messages, primitive-type checks;
- traceback frames are processed **only** when `exc_info` is present (error records);
- no work is added before or after a record is emitted;
- removing FastMCP's Rich handler takes work away rather than adding it.

**Measurement.** There are two benchmarks, each run once before and once after commit A, on the same machine under the same conditions.

**1. The existing benchmark, unchanged:** `make bench` (stubs, 50 samples, concurrency 1, `log_level="WARNING"`), saved to `.context/log1/bench-warning-before.json` and `-after.json`.

**2. A controlled INFO-level benchmark.** `make bench` never formats INFO logs, and production runs at `LOG_LEVEL=INFO` (the default in `config.py:24`). So a preparatory commit **P**, made **before** the before-measurement, adds two optional arguments to `dev/bench.py`:
- `--log-level`, which defaults to `WARNING`, so the existing benchmark is unchanged;
- `--log-file PATH`.

With them, the bench builds its settings at that level and, after `create_app`, points the root JSON handler (set by `configure_logging`) at `PATH`. The bench's JSON report stays alone on stdout, and every adapter and library log line goes to the file.

- **Commit P files:** `dev/bench.py` and `tests/test_bench.py`. The test proves the default still means WARNING with the same report, and that `--log-level INFO --log-file` writes `tool_result` lines to the file while stdout stays parseable JSON.
- **Why this is worth keeping:** gate 3, the live bench, should also measure at production log level.
- **Commands, identical before and after:**

  ```
  cd services/mcp && uv run python dev/bench.py --samples 50 --concurrency 1 --log-level INFO \
    --log-file ../../.context/log1/bench-info-<before|after>.log > ../../.context/log1/bench-info-<before|after>.json
  ```

**Report:**
- **Timings:** for both benchmarks, a per-scenario p50 and p95 comparison for every scenario in both slot modes, with machine conditions noted.
- **Log volume:** for the INFO benchmark, the count of log lines per `msg` value before and after, from the two `.log` files. `tool_result` and `summary_saved` counts must be **identical**, and no new message may appear.
- **Format sample:** one `tool_result` line from each file, showing the format is unchanged.
- **Caveat:** fixture timings are not production latency.
4. **Material regression:** any scenario whose p50 worsens by more than 10 % **and** by more than 1 ms. If that happens, the regression must be **investigated before approval**:
   - profile the formatter path;
   - report every run, and never rerun to get a better number;
   - fix the cause.

   Differences within noise are reported as such.

## 6. Verification for revision 4 (executed; superseded, not executable)

These steps ran once for revision 4: commit P, the before-and-after benchmarks, the red tests, commit A, the probe rerun, `./scripts/test.sh` and commit B. Their results are in `LOG-1-HAND-BACK.md`, and the M-1 correction followed in `7c44955`. **They are not instructions for any future work.** The only current execution path is the revision 6 specification above, implemented in knowledge-removal commit C1.
