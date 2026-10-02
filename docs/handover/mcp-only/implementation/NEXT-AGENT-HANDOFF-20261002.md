# Independent review and next-agent handoff — 2 October 2026

> Historical evidence/instructions for the pre-removal revision. Scheduling-gate statements are superseded by the user-approved K1 decision in docs/DECISIONS.md and ROUTING-REMOVAL-REVIEW.md. Do not implement or deploy from this historical document.

## Follow-up status

The user assigned the two fixes to the reviewing agent. R1 and R2 below are historical findings,
now addressed in the current PR changes: shared URL/credential propagation with a secure profile
launcher; authenticated-tenant checks before external test writes and explicitly enabled benchmark
writes. External benchmarks default to reads. Regression tests cover profile switching, stale values,
credential isolation, missing/mismatched identity and the benchmark opt-in.

Gateway 1.0.11 was inspected; the helper now uses its canonical request fields and refresh route.
See `docs/handover/OWNER-INTEGRATION-MESSAGES.md` for copyable owner messages and `CONTEXTFORGE.md`
(one directory above `mcp-only`) for complete registration/virtual-server instructions. The Stratum VM
`ds-staging-stratum` is in `DS-STAGING-RG`, East US 2; its proposed API integration is documented there.
No cloud settings, service data, secrets or resources were changed during this follow-up.

Follow-up verification:

- `./scripts/test.sh`: lint passed; **339 hermetic + 2 process e2e passed**; source/wheel built;
  production and stub Docker images built; production contains neither stubs nor pytest.
- `scripts/run-profile.sh live -- uv run --project services/mcp pytest services/mcp/tests/test_external.py -q -p no:cacheprovider -m external -k 'machine_token_is_issued or absent_bearer'`:
  **2 read-only live gates passed**, 4 other tests deselected. This proves profile/vault credential
  loading and operational reads; it does not prove live writes or the knowledge service.
- `uv run --project services/mcp python services/mcp/dev/bench.py --samples 1 --concurrency 1`:
  **7/7 fixture scenarios passed**. This is a benchmark smoke check, not production latency evidence.
- The existing PR is updated with these fixes and the visible integration instructions; no merge or
  deployment is included. Remaining owner inputs and real voice-path acceptance are still open.

## Read this first

Workspace: `/Users/garima/conductor/workspaces/healthcare-tools/des-moines`.
Branch: `Garry2012/mcp-external-api`. PR #11: https://github.com/Garry2012/healthcare-tools/pull/11.
Reviewed HEAD: `f5414e16a072c4b661c6506b8edc2571da1abff3`; latest code commit `25f96a3`.
The PR is open, CI passed, and it has not been merged. Preserve the user's untracked `temp/`.

The user wants MCP-only code: Manoj owns the operational backend/database; Shobhit owns knowledge and
clinical routing. Do not implement either service here. There are four MCP tools. UNKNOWN availability
means collect caller name/number, promise a callback, and save a call summary only; no booking/transfer.

This review performed source inspection, local tests and read-only Azure/API checks. It did not deploy,
change Azure settings, alter secrets, write appointments/summaries, modify databases or merge the PR.
This file is a handoff for a new session, not authorization for additional cloud changes. Follow the
user's assignment in that session. All essential findings are here; Conductor comments are supplementary.

## Independently verified, not taken from Fable's console

- Source code: `services/api` has no tracked files. Active MCP code, dependency file and deployment
  tooling have no old backend/database implementation dependency.
- The previous UNKNOWN inconsistency is addressed with shared `board_scope.py`, used by availability
  and booking. In-call reads and writes both default to 0.30 s, with separate background-auth and
  after-call-summary budgets. This is a budget, not proof of the one-second audio-response target.
- Endpoint deployment uses `deploy/environments/live.env`. It names the exact subscription,
  `healthcare-rg`, shared resources and canary app. The deployer no longer invents a resource group or
  provisions shared infrastructure. The existing-app path attaches identities and secret references
  before updating the revision.
- Independently ran `cd services/mcp && uv run --frozen pytest tests -q -p no:cacheprovider -m 'not external'`:
  **320 passed, 9 deselected**, about 19.5 seconds. This includes 318 hermetic tests and 2 process tests.
  CI is green. Full Docker builds were not repeated in this review.
- Read the current `ops-client-id` and `ops-client-secret` from shared Key Vault into process memory:
  live token exchange returned **200**, tenant **jayashree**, scopes **appointments.write** only.
  Live directory reads returned **19 departments and 28 doctors**. No credential values were logged.
- Queried `/availability` with the required `doctorId` and date: doctor
  `30b5941b-1e7a-43cb-b994-eb8b47729736` returned UNKNOWN for today, 2026-10-03 and 2026-10-04.
  An exploratory request without doctorId/department returned 400 as required by the contract; this
  was not a service defect. The contract requires exactly one of doctorId or department.
- Canary `mcp-demo-hospital-canary` is running in `healthcare-rg`, image
  `acrfd399536.azurecr.io/frontdesk-mcp:1d0ad08`. Later code commit `25f96a3` changes the profile,
  benchmark and deployment tests, not the runtime service modules.
- Actual canary environment: `ENV=production`, operational URL is the live API, knowledge URL is
  **https://knowledge.pending.invalid**. `/health`, `/ready` and `/dependencies` return 200;
  `/dependencies` explicitly reports knowledge only as configured, with no agreed health check.
- Actual MCP calls through the canary: LIST returned **NOT_FOUND** (successful empty lookup);
  availability and `search_knowledge` returned **ROUTING_UNAVAILABLE**. The conversational bearer
  discovers three tools; the lifecycle bearer discovers only `record_call_summary`. No summary was
  written during this review. The returned operational token lacks `calls.write`; Fable's earlier
  summary-write attempt reported 403.
- **A gateway now exists in healthcare-rg:** `mcp-gateway`, created 2 October 02:24 UTC, public base
  `https://mcp-gateway.icytree-6543aaa9.centralindia.azurecontainerapps.io`. Its health endpoint works.
  Using its existing `PLATFORM_ADMIN_EMAIL` configuration and shared-vault secret
  `mcpgw-platform-admin-password`, login succeeded. Authenticated read-only `/gateways` and `/servers`
  both returned empty lists. We have access to configure/test it when assigned; do not create another.
- No knowledge-service Container App was found in this group's inventory. That does not establish
  absence elsewhere; Shobhit must identify the actual service/contract.

## Two local follow-ups before final acceptance

### R1 — Complete knowledge-profile propagation

`scripts/env.sh:26–29` derives `OPS_E2E_BASE_URL` and `BENCH_OPS_BASE_URL` only. Tests read
`KNOWLEDGE_E2E_BASE_URL`; the benchmark reads `BENCH_KNOWLEDGE_BASE_URL`. Neither is derived from
the profile's `KNOWLEDGE_BASE_URL`. Consequently, filling Shobhit's URL in the advertised one-place
profile will update deployment but leave tests unconfigured and the benchmark using its local
knowledge stub unless extra variables are manually supplied.

Fix: make runtime, external tests and benchmark consume the same selected knowledge URL and credential
references. Test profile changes and stale exports. Keep secret values out of printed exports, Git and
logs. Deployment already reads vault credentials, but `scripts/test.sh` does not fetch them; document
or implement a secure shared launcher rather than claiming automatic test-time vault loading exists.

Reproduced without contacting a service: after selecting live with `KNOWLEDGE_BASE_URL` populated,
`KNOWLEDGE_E2E_BASE_URL` and `BENCH_KNOWLEDGE_BASE_URL` are both unset.

### R2 — Bind write acceptance tests to the authenticated test tenant

`services/mcp/tests/test_external.py:133–139` checks only that `OPS_E2E_WRITE_TENANT` is nonempty.
It never compares that label with the tenant attached to the credentials. A locally invoked
`_write_gate()` accepted `not-the-authenticated-tenant` with no tenant validation. No backend operation
was called in this probe.

Fix before executing positive live writes: verify the authenticated service's tenant against the
owner-designated synthetic tenant and fail on mismatch/unknown. Use authoritative identity from the
trusted auth exchange or an agreed owner identity endpoint, not an untrusted caller-supplied token.
Add mismatch/missing-identity tests. An owner must still confirm that the tenant contains safe test data;
matching its name does not prove it is synthetic. Keep a failed test journey's cleanup confined to
the synthetic records that journey created.

## Inputs we need, and what we can do ourselves

| Item | Who must supply/confirm | What the next agent can do |
|---|---|---|
| Live URL and current client credentials | Already available | Read profile and existing vault values; no need to ask again |
| `calls.write` scope | Manoj/backend administrator | Recheck scopes after grant; verify summary storage/replay. Changing a vault secret cannot grant a backend permission |
| Synthetic status of `jayashree` | Manoj/data owner | Validate tenant binding; do not infer synthetic status from empty appointment results |
| Known availability for create and reschedule | Manoj/staff service owner | Run the journey once prepared. Need usable rows on **two dates**, not just the create date, plus a separate UNKNOWN date. The current MCP credential lacks staff `availability.write`; do not edit Manoj's database or broaden the runtime client yourself |
| Knowledge OpenAPI, URL and auth | Shobhit | Fetch the published contract once identified; adapt `knowledge_contract.py` and `knowledge_client.py`, then test. Existing `/v1/route`, `/v1/answer` and fields are explicitly provisional: a URL alone may not be enough |
| Gateway configuration and tests | Existing deployment/access available | Inspect actual gateway version/header forwarding, register the canary when authorized, test discovery and header isolation; no new gateway required |
| Voice integration and call-end summary | Voice repo owner / assigned agent with that repo | Implement trusted turn/caller/operation headers, separate lifecycle call and bearer; then run a real call. This MCP repository cannot prove another repo's implementation |
| Azure retirement | Current consumer inventory and data-owner disposition | Refresh exact ownership/consumer map. Retire only exclusive, unused resources from this repo after cutover; retain shared infrastructure, other teams' databases, vault contents and services |

Copyable request to Manoj:

> The live MCP credentials work. Please grant this client `calls.write` in addition to
> `appointments.write`; confirm whether tenant `jayashree` is designated for synthetic test writes;
> and prepare fresh, known availability for doctor `30b5941b-1e7a-43cb-b994-eb8b47729736` on two future
> dates (create, then reschedule), with a separate UNKNOWN date for the negative test. Please identify
> the dates/time windows. Keep credentials in the existing shared vault; no secret values in chat.

Copyable request to Shobhit:

> Please share the versioned knowledge-service OpenAPI URL, service base URL and secure auth reference.
> We need hospital answers plus symptom/department routing and emergency/clarification outcomes.
> Confirm the request fields for original caller words, language and relayed appointment reason.

## Remaining acceptance and reporting

1. R1/R2 are fixed in the follow-up; retain their regression tests and use the shared profile launcher.
2. Integrate the published knowledge contract. Keep local/mocked clinical decisions labelled as stubs.
3. After Manoj's scope and data prerequisites, prove create → list → reschedule → cancel and summary
   store/replay on the designated tenant, plus UNKNOWN → no appointment + callback summary.
4. Verify canary release smoke, existing gateway transport, voice headers, lifecycle call and caller
   verification policy. Keep the old consumers running until the replacement is proven.
5. Measure successful responses and failure rates from Central India and actual voice first-audio time
   under declared load. Laptop RTTs (~1 s in this review) include the remote network; a 0.30 s internal
   deadline is not an end-to-end latency measurement.
6. Return for code/release review. Merge/cutover/retirement follow the user's actual authorization,
   not assumptions based on this handoff.

Fable's **7/9 external gates** mixed real operational calls with a local knowledge stub. They do not
mean seven full-production flows passed. Positive appointment persistence and summary writes remain
unproven. The canary is a partial integration deployment, not customer-ready service.

Correct stale documents: a gateway now exists, live credentials work, and the served contract is not
byte-identical to the pin. Its hash is `6f827be1b62e22f4f4f0c54174d22a1b40bd02ab130ec74ce5f83b8b9aa80391`;
the inspected difference is only the Azure `servers` URL/description, not paths or schemas.

Source evidence: `board_scope.py`, `availability.py`, `booking.py`, `config.py`, `clock.py`,
`ops_client.py`, `summary.py`, `knowledge_contract.py`, `server.py`, `scripts/env.sh`, `deploy.sh`,
and the external/gate tests were inspected. Non-secret raw runtime results are in
`.context/architect-review-20261002/read-only-checks.json`; the essential results are reproduced above
so the next agent does not depend on that ignored scratch file.
