# Environment profiles (non-secret)

One mechanism supplies the owner-service URLs and the Azure target to deployment, the external
integration gates and the benchmark, so an endpoint is written down once:

```bash
eval "$(scripts/env.sh mock)"    # or: live
```

`scripts/env.sh <profile>` prints `export` lines from `deploy/environments/<profile>.env` (plus the
derived `OPS_E2E_*`/`BENCH_*` variables) and refuses a profile whose required values are still blank.
Secret **values** never live here: profiles name Key Vault secrets; local runs read credentials from
the git-ignored `.env` or the shell.

| Profile | OPS_BASE_URL | Auth | Purpose |
|---|---|---|---|
| `mock` | `https://healthcare-contract-mock.icytree-6543aaa9.centralindia.azurecontainerapps.io` (no `/api/v1`) | any client credentials; `401` without a bearer | integration tests and benchmarks against the public Prism contract mock (static bodies, no state) |
| `live` | `https://healthcare-api.icytree-6543aaa9.centralindia.azurecontainerapps.io/api/v1` (Manoj, 2 October 2026; served OpenAPI 0.3.0-draft equals the pinned contract) | registered machine client (Key Vault `ops-client-id` / `ops-client-secret`, accepted by `/auth/token`; scope `appointments.write` only — `calls.write` still missing) | real-service verification and the canary deployment `mcp-demo-hospital-canary` |

Both profiles identify the Azure target explicitly: subscription `4e1c081a-9a6a-4e16-9da2-90217c22378b`
and resource group `healthcare-rg`. `deploy/azure/deploy.sh` requires a profile, forgets any inherited
`OPS_BASE_URL`/`AZ_*` first, stops if the profile cannot be loaded, refuses a different signed-in
subscription, never creates or defaults a resource group, and never creates the shared environment,
registry, vault, log workspace or identity (they must exist). A blank profile value never overwrites a
value exported in the shell (so `KNOWLEDGE_BASE_URL` comes from the environment until Shobhit's host
is in the profile; the canary was deployed with the placeholder `https://knowledge.pending.invalid`, which makes
routing-gated tools answer ROUTING_UNAVAILABLE until his host replaces it). The live profile targets a **canary** app (`mcp-demo-hospital-canary`), because the
voice platform still calls `mcp-demo-hospital` with the legacy integration.

## Ops credentials

Key Vault keeps versions. `deploy.sh` reads the **current** version of `ops-client-id` /
`ops-client-secret` and never overwrites an existing secret from the environment, so exporting new
values does nothing. Manoj stored the registered pair on 2 October 2026 (current versions 04:38 UTC); the
earlier dummy versions are disabled. To rotate, set new versions explicitly (the Container App picks them
up on its next revision):

```bash
az keyvault secret set --vault-name kv-fd-demo-hospi-0574c1 -n ops-client-id     --file <(printf '%s' "$REGISTERED_ID")
az keyvault secret set --vault-name kv-fd-demo-hospi-0574c1 -n ops-client-secret --file <(printf '%s' "$REGISTERED_SECRET")
```

Verify before deploying: `eval "$(scripts/env.sh live)"` with `OPS_E2E_CLIENT_ID`/`OPS_E2E_CLIENT_SECRET`
exported locally (read them from the vault, never paste them into files) and
`cd services/mcp && uv run pytest tests -m external -k "token or absent_bearer"`.

## Changing an endpoint

Edit the one line in the profile (`OPS_BASE_URL`, later `KNOWLEDGE_BASE_URL`), run
`deploy/azure/deploy.sh rollouts/demo-hospital --profile live --dry-run`, then the same without `--dry-run`:
the canary is updated in place with the new environment. Nothing else in the repository names a host.
