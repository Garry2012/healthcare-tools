# Front-desk platform (voice agent tools)

Reusable front-desk API + MCP tools for a LiveKit voice agent; healthcare first, hospitality next.
Architecture and decisions: `docs/architecture/TARGET.md`. Contract: `docs/frontdesk-api/openapi.yaml`.

## Commands
- Everything (lint, unit, integration, MCP e2e, schemathesis): `./scripts/test.sh`
- No Docker daemon (web sessions): `eval "$(scripts/local-pg.sh start)"` exports `TEST_DATABASE_URL` / `TEST_DATABASE_OWNER_URL`
- API tests: `cd services/api && uv run pytest tests/unit tests/contract/test_openapi_matches_spec.py tests/integration -q`
- MCP tests: `cd services/mcp && uv run pytest tests -q -m "not e2e"`
- Lint: `uv run ruff check .` in each service (a hook also lints every edited file)
- Architecture: `cd services/api && uv run lint-imports` (layer contracts in `pyproject.toml`; CI fails on a violation)
- Latency: `cd services/api && DATABASE_URL=$TEST_DATABASE_URL uv run python scripts/bench.py`
- Provider config check: `uv run frontdesk-api check-config` (reads `deploy/providers/<provider>.env` values from env)

## Rules that the code will not tell you
- IMPORTANT: all business rules live in `services/api`. `services/mcp` only maps tools to `Agent` operations, injects call headers, derives idempotency keys and wraps failures.
- Spec first: change `openapi.yaml`, then code. The contract test fails on any drift in paths, operationIds, required fields or enums.
- Core names are domain-neutral (resource, category, booking, customer). Domain words live only in packs: `services/api/src/frontdesk_api/packs/<pack>/` and `services/mcp/src/frontdesk_mcp/packs/<pack>.json`. Never branch on the domain in code.
- Language words (today/tomorrow, weekdays, months, titles, filler words) live only in `services/api/src/frontdesk_api/locales/<lang>.py`. A new language is a new module there plus one line in `LOCALES`.
- Caller speech is data: never "rename" words inside lexicon terms, honorifics, utterances or pack answers.
- Identity (`X-Call-Id`, `X-Caller-Number`) comes only from trusted headers, never from tool parameters. A mismatch looks exactly like not-found.
- The agent never speaks unapproved text: knowledge answers are returned verbatim, and failures are `COULD_NOT_CHECK` / `COULD_NOT_RECORD`, never "none available".
- Voice latency is a product requirement: any writer of directory/lexicon/knowledge data must call `cache.bump(...)` in its transaction; cached values are plain dataclasses, never ORM rows; `test_latency_budget.py` gates round trips per call.
- Schema changes: add a new Alembic revision (owner role runs it; the API role is DML-only). Never edit an applied revision; write a working `downgrade`.
- One deployment per provider (hospital/hotel); per-provider settings are non-secret files in `deploy/providers/`.

## Gotchas
- Don't `source` provider `.env` files in bash: it strips JSON quotes. Use `docker --env-file` or a line reader.
- Test conftests strip every `Settings` field from the environment; pass overrides via `make_settings(...)`.
