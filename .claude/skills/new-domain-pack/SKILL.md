---
name: new-domain-pack
description: Create a domain pack (e.g. clinics, salons, restaurants) as only what the domain adds to the core, plus a demo rollout that proves it. Use when asked to support a new domain or vertical.
---
# New domain pack: $ARGUMENTS

A domain is the middle layer of core → domain → rollout (`docs/architecture/TARGET.md` A10). It
adds only what every provider of that domain shares; everything one provider has (its staff,
schedules, answers, languages) is a rollout. Never copy another pack and edit it: write only
what differs from the core.

## 1. Ask (one message, then wait)

- What is booked (resource: doctor, stylist, table) and grouped by (category: department,
  service)? Queue positions (SEQUENCE) or timed slots (TIMED)?
- The standard categories every provider of this domain has, each with a short **code**.
- The words callers use for each category and for needs that lead to one, in each language the
  domain should support.
- What is an emergency (danger signs, always transferred at once) and what goes to a person
  (severity, service requests), and the destinations those go to.
- Settings where this domain's default differs from the core's (slot length, day parts…).
- How the agent should describe itself and each tool in this domain's words.

**Stop if the domain needs behaviour the core lacks** (e.g. multi-night room inventory, a
payment step, an integration). That is core work: say so, and propose the named extension
point in TARGET.md. Never add `if domain == …` anywhere.

## 2. Write the domain (two files)

- `services/api/src/frontdesk_api/packs/<name>/__init__.py`: `CATEGORIES` (code → name),
  `BASELINE` rows `(type, target, term, language)` (CATEGORY and NEED_ROUTE target a code;
  RED_FLAG a label; SERVICE_TRANSFER a destination; no RESOURCE rows), and
  `PACK = Pack(name, version="1", escalation_destination, transfer_destinations, categories,
  baseline, desk_destination, settings)`. No names, numbers or answers of a real provider.
- `services/mcp/src/frontdesk_mcp/packs/<name>.json`: `role`, `instructions` (**only** this
  domain's rules: who is booked per call, what an emergency is; the core rules are added by
  `prompt.py`, and a test fails if you repeat one), and every tool's description and parameters.
- Add `<name>` to `PACKS` in `services/api/tests/unit/test_packs.py` and to the `pack`
  parameters in `services/mcp/tests/test_tools_unit.py`; add `packs.healthcare`-style entries to
  the import-linter contracts in `services/api/pyproject.toml` (core never names it; packs are
  independent).

## 3. Prove it with a demo rollout

Create `rollouts/demo-<name>/` with `/new-rollout`, all synthetic: a few categories using the
codes, a few resources, a knowledge answer or two, and `dialogues.yaml` covering every code,
every danger sign group, a service transfer, and each language. Optionally a dated scenario in
`services/api/src/frontdesk_api/demo/<name>.py`, registered in `demo/__init__.py`.

## 4. Check

```bash
cd services/api && uv run frontdesk-api rollout validate ../../rollouts/demo-<name>
./scripts/test.sh
```
Bump `version` whenever the baseline changes later: `rollout apply` replaces baseline rows the
new version dropped, in every rollout of this domain.
