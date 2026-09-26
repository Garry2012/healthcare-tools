# Deploy

One deployment per provider (hospital or hotel). Provider settings live in
`deploy/providers/<provider>.env`; `ONBOARDING.md` is the runbook for adding one.

Two images, one database. Configuration is environment only; `.env.example` lists every
variable. No secret is baked into an image.

| Image | Build | Listens | Health |
|---|---|---|---|
| `frontdesk-api` | `docker build services/api` | `PORT` (8000) | `/health`, `/ready` (DB + Alembic head) |
| `frontdesk-mcp` | `docker build services/mcp` | `PORT` (8100), MCP at `/mcp/` | `/health`, `/ready` (API ready) |

Both run as UID 10001 and install exact versions from `uv.lock`.

## Database roles

Migrations run as the **owner**; the API runs as a **DML-only** role and never runs DDL.

```bash
# one-shot, owner credentials
docker run --rm -e DATABASE_URL=postgresql://OWNER:***@HOST:5432/DB frontdesk-api frontdesk-api migrate
# service, runtime credentials
docker run -e DATABASE_URL=postgresql://APP:***@HOST:5432/DB -e AUTH_TOKENS_JSON='…' -p 8000:8000 frontdesk-api
```

### Upgrading an existing database

Revision `0002_domain_neutral_names` renames tables and columns and rewrites stored values. It is
**not zero-downtime**: stop the API and MCP containers, run `migrate`, then start the new images.
Take a backup first; `downgrade` reverses it exactly, but only on the same data. Later revisions
only add objects and can run while the old version serves.

`/ready` is strict: it returns 503 unless the schema is **exactly** the head the image was built
with. A new image is not ready until `migrate` has run, and an old image stops being ready as soon
as it has. Deploy in the order migrate, then roll the new images out promptly; `/health` (liveness)
stays 200 throughout, so orchestrators do not restart the old instances meanwhile.

### Local PostgreSQL (docker compose)

`make up` starts `postgres:16-alpine`. `deploy/postgres/init/01-roles.sh` creates `APP_DB_USER`
on first start and grants it DML on everything the owner creates later. A one-shot `migrate`
container runs Alembic as the owner, then `api` and `mcp` start.

### Supabase (or any managed PostgreSQL)

Only `DATABASE_URL` changes. No Supabase SDK or Supabase-only feature is used.

1. As the project's `postgres` user, create the runtime role once:

   ```sql
   CREATE ROLE frontdesk_app LOGIN PASSWORD '<generated>';
   GRANT USAGE ON SCHEMA public TO frontdesk_app;
   ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
     GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO frontdesk_app;
   ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
     GRANT USAGE, SELECT ON SEQUENCES TO frontdesk_app;
   ```

2. Migrate with the owner connection string (direct connection, port 5432):
   `DATABASE_URL=postgresql://postgres:***@db.<ref>.supabase.co:5432/postgres?ssl=require frontdesk-api migrate`
3. Run the API with the runtime role. With the **transaction pooler** (port 6543), also set
   `DATABASE_DISABLE_PREPARED_STATEMENTS=true`, because pgbouncer can't hold prepared
   statements. Append `?ssl=require` to the URL.

`postgresql://` URLs are converted to the asyncpg driver automatically.

## Required environment

| Variable | Service | Notes |
|---|---|---|
| `DATABASE_URL` | api | owner for `migrate`, runtime role for `serve` |
| `AUTH_TOKENS_JSON` | api | `{"token": ["scope", ...]}`; replace with an OAuth2 verifier later (`auth.TokenVerifier`) |
| `PROVIDER_ID`, `DOMAIN_PACK`, `TENANT_*` | api, mcp | from `deploy/providers/<provider>.env`; validate with `frontdesk-api check-config` |
| `API_BASE_URL`, `API_BEARER_TOKEN` | mcp | the token must hold the `agent` scope |
| `MCP_BEARER_TOKEN` | mcp | what ContextForge presents; required when `ENV=production` |
| `MCP_DEV_CALLER_NUMBER` | mcp | dev only; the service refuses to start with it when `ENV=production` |

## Operations

- `frontdesk-api maintenance` (daily): purges idempotency keys older than 24 h and past
  board entries.
- Logs are JSON on stdout, one object per line, with `provider` (from `PROVIDER_ID`) and `callId`
  on every line in both services, so one log store can serve every deployment. Phone numbers and customer names are not
  logged.
