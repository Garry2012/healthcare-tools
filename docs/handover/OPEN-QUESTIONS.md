# Open questions and spec defects

The OpenAPI file was **not changed**. Where it is wrong, silent or ambiguous, the service
implements the choice below and the item is listed here. Items marked **POLICY** change
customer identity handling or hospital policy: the spec's default is implemented and the
hospital (or product owner) must confirm.

## Identity and disclosure (POLICY)

| # | Question | What is implemented |
|---|---|---|
| P1 | How strict is the customer-name match for lookup, cancel, reschedule? | Exact after normalisation (NFC, lower-case, honorifics removed, Indic scripts transliterated). "Lakshmi Rao" vs "ಲಕ್ಷ್ಮಿ ರಾವ್" does **not** match (the Kannada romanises to "rav"), so the caller gets the neutral 404 and the agent should transfer. Looser matching (phonetic, first name only) would reduce transfers but raises the risk of acting on the wrong customer. |
| P2 | `cancelOnSpokenNumber` | The cancel/reschedule bodies carry no phone, so "cancel using the number I say" cannot be expressed. The tenant flag exists (default `false`). Without a network caller number, cancel/reschedule return the neutral 404. A spoken number is accepted only for `LIST` (`identityBasis: SPOKEN_NUMBER`). **Changed (2026-09-26):** a spoken number never lists anything without the customer's name (`NAME_REQUIRED`, `customersOnNumber: 0`, whether or not the number has bookings), with or without caller ID. |
| P3 | One customer on the number, no name given | Returns the booking (`FOUND`) with the customer's name, as the spec's `NAME_REQUIRED` rule applies only when there are two or more customers. A household sharing one phone where only one member has booked will hear that member's name. |
| P4 | Red flags and negation | Red-flag phrases match anywhere in the caller's words. "No chest pain" still transfers to emergency. This is the safe direction, but it will transfer some callers who didn't need it. |

## Spec defects and ambiguities

| # | Where | Issue | Implemented |
|---|---|---|---|
| S1 | `agentAvailabilitySearch` example | Returns Dr. Garima for 2026-09-26, a Saturday, while her template in the same file is MON/THU/FRI. | Template rules. `scripts/demo.sh` searches "tomorrow evening" and, if there is no session, follows `unavailable[].nextBookable`. |
| S2 | `DayPart` | Example EVENING = 17:00–23:00, yet the "tomorrow evening" example offers the 15:00–17:00 session. | Tenant default MORNING 06–12, AFTERNOON 12–16, EVENING 16–23; a session matches a day part if it overlaps. Set `TENANT_DAY_PARTS_JSON`. |
| S3 | `/agent/*` security | The `agent` scope is defined but the Agent operations declare no `security`, so they inherit `oauth2: []` (any valid token). | As written: any valid token can call `/agent/*`. Recommend `security: [{oauth2: [agent]}]` on the five operations. |
| S4 | `Idempotency-Key` | `required: false` in the parameter, "required on the agent path" in its description. | Optional in the schema; agent POSTs without it get `400 VALIDATION_FAILED`. |
| S5 | Undocumented status codes | 400 is missing on cancel, reschedule, DELETE exception (missing `X-Acting-User`), and on GETs with invalid query values. 401 is missing on most operations; 404 on `createScheduleException` (unknown resource); 200 on `deskCreateBooking` (replay/`ALREADY_BOOKED`); 405 everywhere. | Codes returned as needed. Schemathesis `status_code_conformance` is therefore excluded from the smoke run (`tests/contract/test_schemathesis.py`). |
| S6 | `positive_data_acceptance` | Domain rules are stricter than the schema: tenant phone format (10 digits vs `^[0-9]{6,15}$`), slot must exist in the current schedule, board is for today only, exception field combinations. | Excluded from the smoke run for this reason; covered by integration tests instead. |
| S7 | `BoardEntry.updatedBy`, `ScheduleException.createdBy` | Both `required`, yet "staff scope only". | Returned as the literal `"staff"` to non-staff tokens; `reasonCategory` and `note` are omitted for non-staff tokens. |
| S8 | Slot holding | The live set `{BOOKED, CONFIRMED_BY_DESK, RESCHEDULED, ARRIVED}` excludes COMPLETED and NO_SHOW. A completed position today becomes "available" again. | As written. Recommend adding COMPLETED/NO_SHOW to the held set for availability, or hiding past-window positions today. |
| S9 | `ALREADY_BOOKED` | Outcome listed, trigger and status code not. | Same normalised name and same phone already holding a live slot in the same session: `200`, `outcome: ALREADY_BOOKED`, existing booking returned. |
| S10 | Reschedule idempotency key | The §2.5 formula uses "slotId or bookingId". A caller who reschedules twice in one call would get `IDEMPOTENCY_CONFLICT`. | The adapter uses `bookingId|newSlotId` as the target for RESCHEDULE. BOOK and CANCEL follow the formula exactly. |
| S11 | MCP LIST inputs `from?` / `to?` | `from` is a Python keyword. | Tool parameters `fromDate` / `toDate`, sent as `from` / `to`. |
| S12 | TIMED walk-in reserve | Which times are withheld is unspecified. | The last `reserve` time slots of the session are withheld (phone gets the earliest). |
| S13 | `TIME_RANGE` + `UNAVAILABLE` ("partial block") | No semantics given. | A covering block cancels the session; a partial block trims it to the longer remaining part (`status: CHANGED`). |
| S14 | `TIME_CHANGE` scope | WHOLE_DAY/TIME_RANGE meaning is undefined. | `TIME_CHANGE` requires `scope: SESSION` (400 otherwise). Extra sessions cannot be time-changed; withdraw and re-add. |
| S15 | `EXTRA_SESSION` overlap | Unspecified. | Overlapping an existing session on any date in range → `409 CONFLICT`. |
| S16 | Session id `n` | "n" undefined. | Template position (1-based, stable across TIME_CHANGE); `e<seq>` for extra sessions (`seq` = exception creation order). |
| S17 | Withdrawing an exception | Only "return to BOOKED if the slot still fits". | Restored to `BOOKED` (not the earlier status). Never-delivered notifications are deleted; delivered ones get a `DESK_MESSAGE` follow-up `{change: SESSION_RESTORED}`; unrestorable ones get `{change: SLOT_NO_LONGER_AVAILABLE}`. |
| S18 | `markNotificationDelivered` | Status mapping unspecified. | Outcome INFORMED/RESCHEDULED/CANCELLED → `ACKNOWLEDGED`; NO_ANSWER → `FAILED`; no outcome → `SENT`. |
| S19 | `getScheduleTemplate` | Which template when several are effective-dated. | The one effective today, else the most recent. |
| S20 | `setScheduleTemplate` | Body carries `resourceId` as well as the path. | Path wins; body value ignored. |
| S21 | `setBoard` | "(today)" in the summary only. | Any other date → 400 (use an exception). |
| S22 | Search with nothing bookable | Routing has no "nothing to offer" action. | `outcome: NONE_AVAILABLE`, `routing.action: OFFER_SLOTS`, with `unavailable[].nextBookable` and same-category `alternatives`. |
| S23 | "Anyone available right now?" | "all sessions today with presence present/arriving". | All bookable sessions today, PRESENT then ARRIVING first. It doesn't filter to present-only, because on a day the desk hasn't used the board that would offer nothing. |
| S24 | Sequence expected window | "± tolerance" vs the example `[t, t+20]`. | `[t, t + TENANT_SEQUENCE_WINDOW_MINUTES]` (default 20), clamped to session end. |
| S25 | Idempotency on errors | Unspecified. | Only successful responses are stored; a retried 4xx is recomputed. |
| S26 | Unknown query parameters | Not forbidden by OpenAPI 3.0. | Ignored (schemathesis `negative_data_rejection` excluded for this reason). |

## Deliberately not built (per the build brief)

- **Semantic matching** (§2.3 step 4): `SemanticMatcher` is a no-op with a TODO.
- **Rate limiting (429)**: expected at ContextForge; the API never emits 429 itself.
- **OAuth2**: static bearer tokens (`AUTH_TOKENS_JSON`) behind `TokenVerifier`. The spec's `tokenUrl` is a placeholder.
- **Outbound sending**: notifications are queued, with the `delivered` endpoint only.

## Integration checks still to do

1. ContextForge must run with `ENABLE_HEADER_PASSTHROUGH=true` for `X-Call-Id` and
   `X-Caller-Number` to reach the adapter. This hasn't been verified against a live gateway
   (see `CONTEXTFORGE.md`).
2. The voice platform (LiveKit agent) must set `X-Call-Id` and `X-Caller-Number` on its MCP
   requests to ContextForge. Without them, writes are refused (no call id means no idempotency
   key) and lookups return `IDENTITY_UNAVAILABLE`.
3. Supabase's transaction pooler: set `DATABASE_DISABLE_PREPARED_STATEMENTS=true`. This
   hasn't been exercised against Supabase itself.

## Repository

- `docs/archive/` is on disk but git-ignored except its README. It holds patient-call
  transcripts and real hospital names and numbers, so it should not go into version control.
