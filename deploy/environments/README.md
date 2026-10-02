# Environment profiles (non-secret)

Edit service addresses once in `deploy/environments/live.env` (or `mock.env`). Deployment, integration
tests and benchmarks derive their addresses from that profile. Secret values stay in Key Vault;
the profile contains only vault and secret names.

| Profile | Operational service | Credentials / purpose |
|---|---|---|
| `mock` | `https://healthcare-contract-mock.icytree-6543aaa9.centralindia.azurecontainerapps.io` | Public example credentials; static Prism responses, no persistence |
| `live` | `https://healthcare-api.icytree-6543aaa9.centralindia.azurecontainerapps.io/api/v1` | Registered machine client from the shared vault; real-service tests and the canary |

The inspected live contract matches pinned paths/schemas; its `servers` entry differs. As checked on
2 October 2026, the live client authenticates as `jayashree` with `appointments.write`, but still needs
`calls.write`. Shobhit's URL is not supplied. The existing canary has the placeholder
`https://knowledge.pending.invalid` and therefore cannot pass routing-dependent journeys.

## Run tests and benchmarks with the same configuration

From the repository root, the launcher loads the profile and reads current Key Vault credentials into
the child process environment. It never prints their values or writes them to a file. Azure CLI access
to the named vault is required for live credentials. The mock operational service receives example
credentials, never the live client secret.

```bash
# Read-only live authentication gates (no appointment or summary writes):
scripts/run-profile.sh live -- uv run --project services/mcp pytest services/mcp/tests/test_external.py -q -m external -k 'machine_token_is_issued or absent_bearer'

# Benchmark; inspect reported boundaries before treating results as live-service evidence:
scripts/run-profile.sh live -- uv run --project services/mcp python services/mcp/dev/bench.py
```

`scripts/env.sh live` remains available for non-secret exports. It derives the runtime, `OPS_E2E_*`,
`KNOWLEDGE_E2E_*` and `BENCH_*` URL aliases. Blank profile values **clear stale shell values**. The
launcher supplies the corresponding credential aliases from `OPS_CLIENT_ID_SECRET_NAME`,
`OPS_CLIENT_SECRET_SECRET_NAME` and `KNOWLEDGE_BEARER_TOKEN_SECRET_NAME`. With no knowledge URL,
external knowledge gates remain blocked; the benchmark explicitly labels its local knowledge stub.
External benchmarks omit CREATE by default and report that omission. To benchmark real test bookings,
set `BENCH_ALLOW_WRITES=1`, `OPS_E2E_MODE=live` and `BENCH_WRITE_TENANT` to the owner-designated synthetic
tenant; the same authenticated-tenant check runs first. This deliberately creates synthetic records;
coordinate test-data disposition with the owner. Fixture benchmarks keep all scenarios.

Selecting a profile does not authorize writes. Live write gates additionally require the explicit
write opt-in, an owner-designated synthetic tenant and test data. The test checks that the tenant in
the authenticated owner's token matches `OPS_E2E_WRITE_TENANT` before any writes. Missing, opaque or
mismatching identity fails closed; matching a name does not establish that data is synthetic.

## Deploy or change an endpoint

Edit `OPS_BASE_URL` / `KNOWLEDGE_BASE_URL` in the selected profile; keep credentials at its named
vault references. After required owner inputs are available:

```bash
deploy/azure/deploy.sh rollouts/demo-hospital --profile live --dry-run
# Execute the same command without --dry-run only as part of the assigned deployment.
```

The deployer reads the current vault versions and never overwrites an existing secret from shell
values. Rotate a credential by creating a new version at its existing vault name, then deploy the new
revision. The profile controls subscription `4e1c081a-9a6a-4e16-9da2-90217c22378b`, resource group
`healthcare-rg` and the canary `mcp-demo-hospital-canary`. Deployment requires existing shared
infrastructure and does not create a resource group, registry, environment, vault or shared identity.
The legacy `mcp-demo-hospital` remains separate until consumer cutover is verified.
