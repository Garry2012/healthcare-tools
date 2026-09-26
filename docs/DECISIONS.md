# Decisions

Architecture is fixed by the build brief (`docs/handover/PLAN.md`). This file records the
choices made inside it and every library adopted.

| # | Decision | Why | Alternatives considered |
|---|---|---|---|
| D1 | All domain logic in `frontdesk-api`; `frontdesk-mcp` only maps tools to Agent operations | One place to test and change rules; a second consumer (staff portal) gets the same behaviour | Logic in the MCP layer (duplicated, untestable without the agent); ContextForge REST tools (cannot inject call context) |
| D2 | Availability is a pure function (`domain/availability.py`) evaluated per request, never stored | Today and future are the same question; no cache invalidation; golden tests need no DB | Materialised slots table (stale on every exception or board change) |
| D3 | Slot uniqueness via a partial unique index; `INSERT … ON CONFLICT DO NOTHING`; reschedule as an UPDATE in a savepoint | Correct under concurrency without locks or retries; the 25-way race test proves it | `SELECT … FOR UPDATE` on a session row (serialises all bookings for a session) |
| D4 | Idempotency row inserted first, in the same transaction as the write | A concurrent duplicate blocks on the key and then replays; a rollback leaves no key behind | Check-then-insert (races); storing failures (replays stale conflicts) |
| D5 | Deterministic resolver: lexicon → transliteration → Double Metaphone → difflib suggestions; `SemanticMatcher` no-op | Explainable, testable, no model download (brief); the hospital controls meaning through approved lexicon rows | Sentence-embedding model now (deferred per brief, IMPLEMENTATION.md §2.3 step 4) |
| D6 | Two DB roles: owner runs Alembic, runtime role is DML-only | A compromised API process cannot alter the schema | Single role (simpler, weaker) |
| D7 | Static bearer tokens behind `TokenVerifier` | Enough for the pilot; OAuth2 introspection replaces one class | Build an OAuth2 server (out of scope) |
| D8 | FastMCP tools hand-written (2 tools), not `from_openapi` | Header injection from call context, stable names, the surface a small model handles best | `FastMCP.from_openapi` (five tools, no header injection) |

## Libraries

| Library (pinned) | Used for | Why this one | Fallback |
|---|---|---|---|
| fastapi 0.141.1, starlette 1.7.0, uvicorn 0.53.0 | REST service | Pydantic-native OpenAPI generation, which the contract test compares with the spec | Litestar |
| sqlalchemy 2.0.54 (asyncio), asyncpg 0.31.0 | Persistence | Mature async ORM with `ON CONFLICT` and partial-index support; asyncpg is the fastest PG driver | psycopg 3 async (driver swap only) |
| alembic 1.20.0 | Migrations | The SQLAlchemy standard; the owner role runs it | Plain SQL files with a runner |
| pydantic 2.13.5, pydantic-settings 2.15.0 | Wire models, configuration | Shared by FastAPI and FastMCP | — |
| indic-transliteration 2.3.82 | Kannada/Devanagari/other Indic → Latin | Covers every Indic script via sanscript schemes; pure Python | ICU transliterator (PyICU, native dependency) |
| metaphone 0.6 | Double Metaphone | Small, pure Python, the algorithm the guide names | jellyfish (no Double Metaphone), abydos (heavy) |
| fastmcp 2.14.7, mcp 1.30.0 | MCP adapter | Matches the reference service; streamable HTTP, stateless | The `mcp` SDK's FastMCP directly |
| httpx 0.28.1 | Adapter → API | Async, explicit timeouts, MockTransport for boundary tests | aiohttp |
| schemathesis 4.28.0 (dev) | Property-based contract smoke test | Generates requests from the spec itself | Dredd |
| pytest 9.1.1, pytest-asyncio 1.4.0, pyyaml 6.0.3, ruff 0.16.9 (dev) | Tests, lint | Standard | — |
