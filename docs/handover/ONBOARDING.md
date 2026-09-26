# Onboarding a provider (hospital or hotel)

Each provider is its own deployment of the same two images and has its own database
(docs/architecture/TARGET.md A1). Onboarding is configuration and data; it needs no code change.
Rough effort: half a day of setup, plus the provider's time to sign off data and policy.

## 1. Configure (non-secret, committed)

```bash
cp deploy/providers/demo-hospital.env deploy/providers/<provider>.env   # or demo-hotel.env
```

Set `PROVIDER_ID`, `DOMAIN_PACK` (`healthcare`, `hospitality`), timezone, phone pattern,
currency, languages and day parts. The identity policy lines (`TENANT_DISCLOSURE_POLICY`,
`TENANT_CANCEL_ON_SPOKEN_NUMBER`) need the provider's written sign-off (OPEN-QUESTIONS.md
P1–P4). Validate without a database:

```bash
docker run --rm --env-file deploy/providers/<provider>.env frontdesk-api frontdesk-api check-config
```

It exits non-zero on any problem: an unknown timezone, a pack reference to something that
doesn't exist, transfer destinations missing the escalation target, or inverted thresholds.

## 2. Provision (secrets, in the secret store)

- A PostgreSQL database with an owner role and a DML-only runtime role (DEPLOY.md).
- `AUTH_TOKENS_JSON` with an `agent` token for the adapter and staff tokens for the desk app
  (`bookings.staff`, `schedule.write`, `board.write`, `directory.write`, `knowledge.write`).
- `MCP_BEARER_TOKEN` for ContextForge → adapter, and `API_BEARER_TOKEN` for adapter → API.

## 3. Deploy and migrate

`frontdesk-api migrate` as the owner, then `frontdesk-api serve` and `frontdesk-mcp serve`
with the provider file plus secrets. Locally: `PROVIDER_ID=<provider> make up`.

## 4. Load the provider's real data (never the synthetic seed)

Through the staff API, in this order:

1. `PUT /categories/{categoryId}` for each department or service, then `POST /resources` for
   each doctor or therapist, with `dataConfirmed: false` until the provider signs each row off.
2. `PUT /resources/{id}/schedule-template` for each recurring schedule.
3. `POST /lexicon`: the provider's approved terms. For healthcare: symptom routes (**only**
   routes the provider approves), red flags, and service transfers.
4. `POST /knowledge`: approved answers (hours, parking, payment, directions), with question
   variants in every supported language. Leave `approved: false` until signed off.

Edits reach every replica on the next request (version-stamped caches); nothing needs a restart.

## 5. Register the gateway

```bash
set -a; . deploy/providers/<provider>.env; set +a   # PROVIDER_ID, DOMAIN_PACK
MCP_PUBLIC_URL=https://<adapter-host>/mcp/ MCP_BEARER_TOKEN=… \
  uv run --project services/mcp python deploy/contextforge/register.py --dry-run   # then without
```

This creates one gateway named `frontdesk-<provider>`. The voice agent for this provider's phone
number uses that gateway's tools and must forward `X-Call-Id` and `X-Caller-Number`.

## 6. Prove it before go-live

- `scripts/demo.sh` against the deployment (for healthcare; adapt the utterances otherwise).
- Replay the provider's own call recordings as scripted dialogues (IMPLEMENTATION.md §2.8 step 5).
- Check `Server-Timing` on live traffic. The p95 budgets in TARGET.md include the provider's
  database network distance: keep the API and the database in the same region.
