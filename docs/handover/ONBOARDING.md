# Onboarding a provider: a new rollout

A provider (a hospital, a hotel) is a **rollout**: one domain pack instantiated with that
provider's differences, written down as files, deployed as its own stack (TARGET.md A1, A10).
Onboarding changes no code and no pack. The one exception is a language no module covers yet
(step 1b). `/new-rollout` walks through these steps with you.

Rough effort: half a day of setup, plus the provider's time to sign off data and policy.

## 1. Write the rollout (non-secret)

```
<rollout>/                      rollouts/<id>/ for demos; a private repository for a real provider
  rollout.env                   identity + only the settings that differ from the domain/core defaults
  data.yaml                     categories, resources and schedules, local terms, approved answers
  dialogues.yaml                what callers say and what must happen (acceptance, checked offline)
  azure.env                     optional: Azure names and sizes (AZURE.md)
```

A real provider's names, schedules and phone numbers are theirs: keep the directory in a private
repository, never in this one. Start from the demo of the same domain
(`rollouts/demo-hospital`), then delete what isn't yours.

**`rollout.env`**: `PROVIDER_ID`, `DOMAIN_PACK` (`healthcare`, `hospitality`), `TENANT_TIMEZONE`,
`TENANT_COUNTRY_CALLING_CODE`, `TENANT_PHONE_PATTERN`, `TENANT_CURRENCY` and
`TENANT_SUPPORTED_LANGUAGES` are required and have no default anywhere. Everything else only if
it differs; `rollout validate` prints each setting with the layer it came from
(`[rollout]`, `[domain]`, `[core]`), and refuses a key that isn't a setting (a typo), a secret, or
deployment wiring (`PORT`, `ROLLOUT_DIR`…). `TENANT_DISPLAY_NAME` (optional) puts the
provider's name in the agent's instructions. The identity policy (`TENANT_DISCLOSURE_POLICY`,
`TENANT_CANCEL_ON_SPOKEN_NUMBER`) defaults to the cautious choice; changing it needs the
provider's written sign-off (OPEN-QUESTIONS.md P1–P4).

**`data.yaml`**:
- `categories`: each department with the domain's **code** (`GM`, `PAED`, `OBG`… for healthcare;
  see `packs/<domain>/__init__.py`). The domain's words for that department and its symptom
  routes reach whichever category carries the code. A department the domain doesn't know takes
  a code of its own and gets words from `terms`.
- `resources`: doctors (therapists, tables) with their categories, names in each language, and
  weekly `sessions`. Set `data_confirmed: false` until the provider signs a row off.
- `terms`: only what the domain baseline lacks: local names ("Garima madam"), a department the
  domain doesn't know, or a route this provider wants elsewhere (`thyroid` → their
  Endocrinology). A term replaces the baseline's meaning of the same words, except a danger
  sign: those are add-only.
- `knowledge`: approved answers (hours, parking, payment, directions), with question variants
  and an answer in every language the rollout serves.

**`dialogues.yaml`**: at least one line per danger sign group, department and approved answer,
in each language, as callers actually say them. Replay the provider's call recordings into here.

### 1b. A language not yet supported (the only code change)

For example, Tamil for a Chennai hospital. Add `services/api/src/frontdesk_api/locales/ta.py`,
modelled on `kn.py`: today/tomorrow, weekdays, months, number words, titles, filler,
availability and day-part words, in native script and the romanised forms speech-to-text
produces. Register it in `AVAILABLE`. `tests/unit/test_locales.py` checks each word is filed
under the right script. Then add the domain's baseline words in Tamil to the pack, where
every future Tamil-speaking rollout reuses them. That is a domain change reviewed with
clinicians, not a rollout change.

## 2. Validate offline

```bash
make rollout-validate ROLLOUT=<rollout>      # or: cd services/api && uv run frontdesk-api rollout validate <rollout>
```

It exits non-zero on any **problem**:
- settings: an unknown timezone, a language with no module, or a missing identity field;
- data: a reference to something that doesn't exist, overlapping sessions, or a term in a
  language the rollout doesn't switch on;
- routing and dialogues: a transfer destination missing, or a dialogue that doesn't behave as
  written.

**Notes** (a domain code with no department, an answer missing in one language) are for the
sign-off, not errors.

## 3. Deploy

**Azure:** `deploy/azure/deploy.sh <rollout>` creates or updates everything. It builds the
images (the rollout's data on top of the platform's), stores secrets in Key Vault, runs the
migrations, writes the rollout with `rollout apply`, and starts the API and the MCP adapter.
Run it with `--dry-run` first (AZURE.md).

**Elsewhere:** the same four things by hand:
1. `frontdesk-api migrate` as the owner role.
2. `frontdesk-api rollout apply <rollout>` as the runtime role.
3. `frontdesk-api serve` and `frontdesk-mcp serve`, with `rollout.env` as environment plus
   secrets (`AUTH_TOKENS_JSON`, `DATABASE_URL`, `API_BEARER_TOKEN`, `MCP_BEARER_TOKEN`).

Locally: `PROVIDER_ID=<id> make up` for a directory under `rollouts/`.

`rollout apply` is idempotent and allowed in production. It writes the domain baseline for the
rollout's languages and the rollout's data, and replaces baseline rows a newer pack version
dropped. It never touches rows the provider added through the staff API. Re-run it (or
`deploy.sh`) after every change to the rollout's files. Day-to-day edits (a doctor on leave, a
new answer) go through the staff API and reach every replica on the next request.

## 4. Register the gateway

```bash
eval "$(scripts/rollout-env.sh <rollout>)"   # PROVIDER_ID, DOMAIN_PACK, ... (never `source` the file)
MCP_PUBLIC_URL=https://<adapter-host>/mcp/ MCP_BEARER_TOKEN=… \
  uv run --project services/mcp python deploy/contextforge/register.py --dry-run   # then without
```

This creates one gateway named `frontdesk-<provider>`. The voice agent for this provider's phone
number uses that gateway's tools and must forward `X-Call-Id` and `X-Caller-Number`.

## 5. Prove it before go-live

- `rollout validate` passes with the provider's own dialogues.
- `scripts/demo.sh` against the deployment (healthcare; adapt the utterances otherwise), and
  the "Try these by hand" table in `TESTING.md` with the provider's names.
- Check `Server-Timing` on live traffic. The p95 budgets in TARGET.md include the provider's
  database network distance: keep the API and the database in the same region.

## A new domain

A domain (salons, clinics, hotels' rooms) is a pack, not a rollout: `/new-domain-pack`. It adds
only what differs from the core: category codes, baseline words, destinations, defaults, and the
LLM's words. If the domain needs behaviour the core lacks (multi-night room inventory), that is
core engineering first (TARGET.md A10, "What is not a layer yet").
