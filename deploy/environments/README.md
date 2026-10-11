# Environment profiles (non-secret)

Edit service addresses once in `deploy/environments/live.env` (or `mock.env`). Deployment, integration
tests and benchmarks derive their addresses from that profile. Secret values stay in Key Vault;
the profile contains only vault and secret names.

| Profile | Operational service | Credentials / purpose |
|---|---|---|
| `mock` | `https://healthcare-contract-mock.icytree-6543aaa9.centralindia.azurecontainerapps.io` | Public example credentials; static Prism responses, no persistence |
| `live` | `https://healthcare-api.icytree-6543aaa9.centralindia.azurecontainerapps.io/api/v1` | Registered machine client from the shared vault; real-service tests and the canary |

The 2 October 2026 inspection recorded a live client authenticating as `jayashree` with
`appointments.write` and a pending `calls.write` grant. This is historical status, not a fresh probe.
Current release readiness requires separately approved owner and deployed-transport checks.

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

`scripts/env.sh live` provides non-secret exports and derives `OPS_E2E_BASE_URL` and
`BENCH_OPS_BASE_URL` from `OPS_BASE_URL`. Switching profiles replaces these operational URLs.
The launcher supplies matching credential aliases from `OPS_CLIENT_ID_SECRET_NAME` and
`OPS_CLIENT_SECRET_SECRET_NAME`; the runtime, external gates and benchmark use the same pair.
External benchmarks omit CREATE by default and report that omission. To benchmark real test bookings,
set `BENCH_ALLOW_WRITES=1`, `OPS_E2E_MODE=live` and `BENCH_WRITE_TENANT` to the owner-designated synthetic
tenant; the same authenticated-tenant check runs first. This deliberately creates synthetic records;
coordinate test-data disposition with the owner. Fixture benchmarks keep all scenarios.

Selecting a profile does not authorize writes. Live write gates additionally require the explicit
write opt-in, an owner-designated synthetic tenant and test data. The test checks that the tenant in
the authenticated owner's token matches `OPS_E2E_WRITE_TENANT` before any writes. Missing, opaque or
mismatching identity fails closed; matching a name does not establish that data is synthetic.

## Deploy or change an endpoint

Edit `OPS_BASE_URL` in the selected profile; keep credentials at its named
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
The legacy `mcp-demo-hospital` and `api-demo-hospital` were deleted on 9 October 2026;
see the [retirement record](../../docs/handover/mcp-only/implementation/AZURE-RETIREMENT-CHECK-20261009.md).
