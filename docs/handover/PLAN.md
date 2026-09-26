# Build plan — front-desk MVP

Spec: `docs/frontdesk-api/openapi.yaml` + `IMPLEMENTATION.md` §2.2–2.5 (unchanged, normative).

**Assumptions** (flagged in `OPEN-QUESTIONS.md` where the spec is silent)
- One tenant, configured from env; `Asia/Kolkata`, 10-digit national phone, INR.
- Session id `n` = 1-based position of the session in the template; extra sessions use `e<exception seq>`.
- Removed sessions are kept as `status=CANCELLED` tombstones so `unavailable[]` can say why.
- Archived research stays out of git (patient transcripts, real hospital data); only its README is committed.

**Steps**
1. Archive research into `docs/archive/`; scaffold `services/api`, `services/mcp`, `deploy/`, Makefile.
2. Postgres 16 in compose (`dev`, `test` profiles). Owner role runs Alembic; runtime role gets DML
   through default privileges and cannot run DDL. Alembic `0001` creates all 13 tables.
3. Pure domain core in `frontdesk_api.domain`: ids, availability engine (§2.2), text normalisation
   (NFC, honorifics, `indic-transliteration`, Double Metaphone via `metaphone`), date rules, resolver
   (§2.3 without embeddings, `SemanticMatcher` no-op), identity matching (§2.4). Golden unit tests.
4. Services over SQLAlchemy 2 async: directory, scheduling (exceptions → impact → notifications),
   booking (`INSERT … ON CONFLICT DO NOTHING` on the partial unique `slot_id` index), reschedule in
   one transaction, idempotency store, agent facade, call summaries.
5. FastAPI routers per tag, bearer-token scopes via a `TokenVerifier` interface, JSON logs keyed by
   `X-Call-Id`, `/health`, `/ready` (DB + Alembic head). Validation errors → 400 `Error` envelope.
6. Seed (`make seed`): 8 categories, 10 synthetic resources, templates, exceptions, board, ~30
   bookings, trilingual lexicon — all dates relative to the run date, idempotent.
7. `services/mcp`: FastMCP 2.14.7, two hand-written tools, headers from `get_http_headers()`,
   derived idempotency keys, failure envelopes, one same-key write retry. ContextForge `register.py`.
8. Tests: unit (hermetic), integration (real Postgres: 25-way race, atomic reschedule, idempotency,
   exception impact, scopes, `/ready`), contract (generated OpenAPI vs spec; schemathesis), MCP e2e.
9. Handover docs, `scripts/demo.sh`, Docker images (non-root), end-to-end verification.

**Out of scope**: voice agent, UI, outbound sending, OAuth2 server, embedding model.
