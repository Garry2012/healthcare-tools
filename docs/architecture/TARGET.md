# Target architecture — reusable front-desk platform

Status: accepted 2026-09-26. Supersedes the single-domain framing in `docs/handover/PLAN.md`;
the domain rules in `docs/frontdesk-api/IMPLEMENTATION.md` still hold, now expressed in
domain-neutral names.

## Goals, in priority order

1. **Fast enough for voice.** A caller hears silence while a tool runs. Budgets below are
   server-side p95 at the API, excluding the gateway and network.
2. **Reusable across domains.** Healthcare first, hospitality next, with the same code. A new
   domain is a *domain pack* (data and wording), not a fork.
3. **Many hospitals.** Each hospital is a *rollout*: its own files and its own deployment of the
   same images. Adding one means writing down its differences, never changing a pack or the core.
4. **Safe by construction.** Identity comes only from trusted call context, writes are
   idempotent, and a failure is never reported as "nothing available".

## Shape

```
LiveKit voice agent ──MCP (+X-Call-Id, X-Caller-Number)──▶ ContextForge gateway
        │                                                   (auth, rate limits, one gateway entry per hospital)
        ▼
frontdesk-mcp  (3 tools: find_availability, manage_booking, search_knowledge; no business rules)
        │ HTTPS, agent-scoped bearer
        ▼
frontdesk-api  (generic core + DOMAIN_PACK) ──▶ PostgreSQL (one database per hospital)
```

## Decisions

| # | Decision | Why | Rejected |
|---|---|---|---|
| A1 | **One deployment per hospital**: api + mcp + database per hospital, same images, configuration from environment only. ContextForge registers one gateway entry per hospital (`frontdesk-<hospital>`). | Hard isolation of patient data with no tenant code paths to get wrong; per-hospital upgrades and data residency; the code stays simple. | Shared database with `tenant_id` + row-level security (cheaper at scale, more code and risk); schema per tenant. Revisit when the hospital count makes per-deployment ops the bottleneck. |
| A2 | **Domain-neutral core.** Resource (doctor, therapist, table), category (department, service), booking (appointment), customer (patient, guest). REST, MCP, database and code use these names. | Hospitality reuses the engine, the resolver, booking and notifications unchanged. | Keep healthcare names and alias them per domain (two vocabularies in one codebase). |
| A3 | **Domain packs** (`DOMAIN_PACK=healthcare`): the MCP server instructions and tool descriptions (the words the LLM sees), the escalation destination for red flags, and the domain's baseline words. (Demo data is a rollout, `rollouts/demo-*`, since A10.) | The LLM needs domain words ("doctor", "department"), but the code doesn't. Hospital-specific wording stays data. | Domain logic in `if domain ==` branches. |
| A4 | **Knowledge base = curated, approved answers first.** Each entry has question variants in any language and script and an approved spoken answer per language. Retrieval is deterministic and in memory (normalise → token and phrase scoring). A `Retriever` protocol leaves room for a document/embedding source later. | Voice latency (no model call on the hot path); nothing unapproved is ever spoken in a healthcare setting; the same normaliser as the resolver handles Kannada/Hindi script and romanisation. | Document RAG first (slower; answers are not pre-approved). |
| A5 | **Read-mostly data is cached per process and versioned.** The directory, lexicon, resolver index and knowledge base are rebuilt only when a write bumps the version (checked with one indexed read per request), never on a timer. Schedules, the board and bookings are always read fresh. | The resolver index (transliteration and phonetic keys) is the main CPU cost of a search. A version check stays correct across replicas. | A TTL cache (serves stale answers after an edit); no cache. |
| A6 | Everything in the MVP decisions D1–D8 (`docs/DECISIONS.md`) stands, with names updated. | — | — |
| A7 | **Architecture rules are a build check** (`import-linter`, contracts in `services/api/pyproject.toml`): routers → services → db; `domain/` is pure; the core never names a pack; packs and locales are data. | A rule only written in CLAUDE.md erodes one plausible import at a time. | Code review alone. |
| A8 | **Language data is separate from domain packs** (`frontdesk_api/locales/<lang>.py`). Words for today/tomorrow, weekdays, months, titles and filler words are per language, shared by every pack; a pack holds only its domain's words. | Language cuts across domains (a hotel in Bangalore needs Kannada too) and across providers. A new language is a data module. | Language words inside the core's matching code (what we had), or inside each pack (duplicated per domain). |
| A9 | **Each business rule is defined once**: the booking lifecycle in `domain/booking_status.py` (tested against the database's unique index and check constraint), period overlap in `domain/intervals.py`. | A status added to one copy but not another would allow double booking. | — |
| A10 | **Three layers: core → domain → rollout** (below). A rollout is files only (`rollouts/<id>/`); a domain is a pack; neither copies the layer beneath it. Settings resolve core default → domain default → rollout value; identity settings have no default. | "Hospital B" must be Hospital B's differences, and a new domain what it adds. Copy-and-modify had already drifted: the hotel prompt listed the hospital's languages, the hotel lexicon had lost English day parts. | Class inheritance per domain or tenant (behaviour hidden in overrides); one config file per provider copied from the closest one (what we had). |

## Latency budgets (server-side p95, API)

| Operation | Budget | Enforced by |
|---|---|---|
| `search_knowledge` | 50 ms | `tests/perf` benchmark on the seeded pack |
| `find_availability` | 250 ms | same, plus `Server-Timing` on every response |
| `manage_booking` write | 400 ms (hard stop 5 s, then `UPSTREAM_TIMEOUT`) | integration tests plus `Server-Timing` |
| MCP adapter overhead | 15 ms | one keep-alive `httpx` client per process (HTTP/1.1), no per-call client |

Measured in process against the seeded healthcare pack (`services/api/scripts/bench.py`, local
PostgreSQL, p50 ms / sequential DB round trips). Round trips are the number that matters on a
networked database, and `tests/integration/test_latency_budget.py` gates them:

| Call | Before | After |
|---|---|---|
| search: named resource, tomorrow evening (kn) | 24.0 / 9 | 7.5 / 5 |
| search: category, next 7 days | 22.2 / 10 | 8.3 / 6 |
| search: anyone available now | 29.6 / 10 | 10.4 / 6 |
| search: red flag | 7.8 / 4 | 3.4 / 1 |
| knowledge search | — | 3.7 / 1 |

What changed: a versioned directory cache (plain rows plus a precomputed resolver view),
memoised normalisation, transliteration and phonetic keys (the resolver was re-transliterating
the whole lexicon on every call), reuse of cached resource rows in the schedule loader, and a
lazy next-bookable horizon. Every response carries `Server-Timing: db;dur=…;desc="N queries",
app;dur=…, total;dur=…`, and the request log has `db_ms` and `queries`.

The voice agent should say a short filler phrase before any tool call expected to exceed ~300 ms
end to end. The `routing`/`outcome` envelope lets it answer follow-ups with no further call
(IMPLEMENTATION.md §2.7).

## Core → domain → rollout (A10)

Composition, not inheritance: the core defines the contracts, a domain pack is data the core
reads, a rollout is files that instantiate one domain. `frontdesk-api rollout validate` checks all
three together; import-linter keeps the dependencies pointing down.

| Layer | Holds | Where | Created by |
|---|---|---|---|
| **Core** | Booking engine and lifecycle, resolver, date rules, knowledge search, identity and idempotency, caching, observability, the three MCP tools and the rules every agent follows, every language module (`locales/`), deployment | `services/*/src/` (not `packs/`), `deploy/` | engineering (`add-agent-tool` for a new tool) |
| **Domain** | Category codes; a versioned baseline of words in every language it knows: department and symptom words, danger signs, severity and service phrases; default destinations; defaults for core settings; the words the LLM reads (`role`, its own rules, tool descriptions) | `packs/<domain>/__init__.py`, `frontdesk_mcp/packs/<domain>.json` | `/new-domain-pack` |
| **Rollout** | Identity (provider, timezone, phone numbering, currency, languages), the settings it changes, its categories (each with a domain code), resources, schedules, local words, approved answers, acceptance dialogues, Azure names and sizes | `rollouts/<id>/` (or a private repository) | `/new-rollout` |

**The core → domain contract** (`packs.Pack`, `frontdesk_mcp.packs.Pack`): `name`, `version`,
`categories` (code → name), `baseline` rows `(type, target, term, language)` whose CATEGORY and
NEED_ROUTE targets are codes, `transfer_destinations`, `escalation_destination`,
`desk_destination`, `settings` (defaults for `tenant_*` fields, never identity), and in the MCP
pack `role`, `instructions` (its own rules only: a test fails if it repeats a core rule) and
`tools`. `packs.validate` checks it.

**The domain → rollout contract** (`rollouts.model`): `rollout.env` (PROVIDER_ID, DOMAIN_PACK,
TENANT_SUPPORTED_LANGUAGES and the other identity fields, then only changed settings; a test
fails if a value equals its default), `data.yaml` (`categories`, `resources`, `terms`,
`knowledge`), `dialogues.yaml` (acceptance lines), optional `azure.env`. `rollouts.validate`
checks references, schedules, languages, destinations and runs the dialogues.

**Composition rules** (`rollouts.compose`):
- The baseline is loaded only in the rollout's languages, except danger signs: those load in
  every language the domain has, since callers mix languages. Its codes attach to the rollout's
  categories with that code (a code with no category is a note, not an error).
- A rollout term re-points a baseline route with the same words (thyroid → Endocrinology).
  Danger signs are add-only: never replaced, and the staff API refuses to switch a baseline
  one off.
- Baseline rows are stored as `DOMAIN_BASELINE`: a new pack version replaces them on the next
  `rollout apply` without touching the provider's own rows.
- Language words (dates, titles, day parts) come from the locales the rollout switches on,
  never from a pack.

**What is not a layer yet.** A domain adds no code today: the booking models it needs
(queue positions, timed slots) are core. The first domain that needs behaviour the core lacks
(hospitality's multi-night rooms) adds a named extension point to the core, not an override.
Integrations (HIS, SMS) are the same: one port per capability when the first real one arrives.

`healthcare` is complete. `hospitality` is a working sample (spa and restaurant: timed and
queued services). Multi-night room inventory is **out of scope**: it isn't a per-day session with
slots, and it belongs to a PMS integration.

## Security and compliance roadmap

Done in this release: bearer tokens with scopes (`agent` for the voice path, staff scopes for the
desk), identity only from trusted call headers, SQL parameters hidden from logs, request and
statement deadlines, a body size limit, and `provider` plus `callId` on every log line.

Next, in order:

1. **Signed call context.** The voice agent signs `X-Call-Id` and `X-Caller-Number` (HMAC or a
   short-lived JWT from the telephony side), and the API verifies it. Today the headers are trusted
   because only the gateway can reach the API.
2. **Per-user staff tokens (OIDC).** Staff actions are audited per shared token today; the desk app
   needs a real sign-in so `actor` is a person.
3. **Append-only booking history.** Every status change as its own row, never updated.
4. **Retention and erasure (DPDP Act 2023).** A scheduled job that deletes or anonymises call
   summaries and customer rows after the provider's retention period, an erasure endpoint for a
   customer's request, and a consent flag recorded when the agent collects a phone number.
5. **A maintenance scheduler** for retention, idempotency-key expiry and notification retries,
   instead of running them inline.

## Out of scope (still)

Outbound sending, the OAuth2 server, an embedding model, the staff UI, and the voice agent itself.
