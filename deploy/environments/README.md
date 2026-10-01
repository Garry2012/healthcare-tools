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
| `live` | **blank until Manoj supplies the full live base URL** (expected with `/api/v1`) | registered machine client (Key Vault `ops-client-id` / `ops-client-secret`) | real-service verification and deployment; status: **awaiting live integration** |

Both profiles identify the Azure target explicitly: subscription `4e1c081a-9a6a-4e16-9da2-90217c22378b`
and resource group `healthcare-rg`. `deploy/azure/deploy.sh` requires a profile, forgets any inherited
`OPS_BASE_URL`/`AZ_*` first, stops if the profile cannot be loaded, refuses a different signed-in
subscription, never creates or defaults a resource group, and never creates the shared environment,
registry, vault, log workspace or identity (they must exist). A blank profile value never overwrites a
value exported in the shell (so `KNOWLEDGE_BASE_URL` can come from the environment until Shobhit's host
is in the profile). The live profile targets a **canary** app (`mcp-demo-hospital-canary`), because the
voice platform still calls `mcp-demo-hospital` with the legacy integration.

## Replacing the dummy ops credentials with accepted ones

Key Vault keeps versions. `deploy.sh` reads the **current** version of `ops-client-id` /
`ops-client-secret` and never overwrites an existing secret from the environment, so exporting new
values does nothing. Replace them explicitly (new versions become current; the Container App picks
them up on its next revision):

```bash
az keyvault secret set --vault-name kv-fd-demo-hospi-0574c1 -n ops-client-id     --file <(printf '%s' "$REGISTERED_ID")
az keyvault secret set --vault-name kv-fd-demo-hospi-0574c1 -n ops-client-secret --file <(printf '%s' "$REGISTERED_SECRET")
az keyvault secret set --vault-name kv-fd-demo-hospi-0574c1 -n ops-client-id --tags validation=accepted-by-live-api registered-with=manoj
```

Then verify before deploying: `eval "$(scripts/env.sh live)"` with `OPS_E2E_CLIENT_ID`/`OPS_E2E_CLIENT_SECRET`
exported locally and `cd services/mcp && uv run pytest tests -m external -k "token or absent_bearer"`.
