---
name: new-domain-pack
description: Create a domain pack (e.g. clinics, salons, restaurants) so the same core serves a new industry with data only. Use when asked to support a new domain or vertical.
---
# New domain pack

A pack is data. If you are tempted to add `if pack == ...` to core code, stop and ask: the
core may need a new generic concept instead (discuss in `docs/architecture/TARGET.md`).

1. Copy `services/api/src/frontdesk_api/packs/hospitality/__init__.py` (the smallest) to
   `packs/<name>/__init__.py`. Fill in categories, resources (sessions: SEQUENCE for queues,
   TIMED for appointments), lexicon (CATEGORY, RESOURCE, NEED_ROUTE, RED_FLAG, DAY_PART,
   SERVICE_TRANSFER), knowledge entries, `escalation_destination` (must be a transfer
   destination), and a dated `scenario`. All names and numbers are synthetic.
2. Copy `services/mcp/src/frontdesk_mcp/packs/hospitality.json` to `<name>.json`: instructions
   plus description and parameter wording for every tool, in the domain's words.
3. Add `<name>` to `PACKS` in `services/api/tests/unit/test_packs.py` and parametrise
   `test_domain_pack_sets_the_words_but_not_the_schema` in `services/mcp/tests/test_tools_unit.py`.
   Add resolver cases proving the domain's phrases route correctly.
4. Add `deploy/providers/demo-<name>.env` and a parametrised case in
   `test_committed_provider_files_are_valid`.
5. Smoke: `DOMAIN_PACK=<name> uv run frontdesk-api seed --reset`, serve, and call
   `/agent/availability-search` and `/agent/knowledge-search` with real-sounding utterances.
6. `./scripts/test.sh`.

Out of scope for packs: multi-night inventory (hotel rooms), which isn't a per-day session with
slots.
