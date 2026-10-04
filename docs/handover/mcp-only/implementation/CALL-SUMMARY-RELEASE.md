# Call-summary release — 4 October 2026

User authorization: implement the three review cleanups, commit, merge and deploy the reviewed release to Azure. No resource retirement or live patient-data writes are included.

## Review cleanup

- `summary.py`: unexpected HTTP statuses include an integer `httpStatus` in the existing diagnostic log. Wire outcomes, retry policy, privacy, date rules and deadlines are unchanged. Two extra source lines support the safe diagnostic field; no new abstraction or service call.
- `test_summary.py`: the existing HTTP-boundary test now asserts the diagnostic for 202, 404 and 409, alongside unchanged exact result and privacy assertions.
- `test_ops_client.py`: rename the test to describe preservation of created/existing HTTP statuses.
- `register.py`: print “tools” for the four-tool registration.
- The supplied Opus review is tracked unchanged. Reviewer-agent instructions and user-owned `temp/` remain unchanged.

## Verification before merge

Commands and pasted output are retained in `call-summary-evidence/`:

- `18-cleanup-red.txt`: 3 failed, 10 passed; all failures were the missing HTTP-status diagnostic (202, 404, 409).
- `19-cleanup-green.txt`: `make test-fast`, Ruff clean and 462 passed.
- `20-release-full.txt`: `./scripts/test.sh`, Ruff clean, 462 hermetic + 2 process tests passed, wheel/sdist and both Docker images built; production image excludes stubs and pytest. Nine live external gates not run without an owner-approved test tenant. Two existing Authlib deprecation warnings.
- `make schema > /tmp/summary-release-schema.json` and `cmp /tmp/summary-release-schema.json services/mcp/tests/contracts/mcp-tools.snapshot.json`: exit 0. `git diff --check`: exit 0.
- Safety review: no concrete safety/privacy defects; focused 13 status tests passed. Latency review: no added exchanges, retries or deadline changes.

The earlier implementation made two schema bumps: `2026-10-03.3` → `2026-10-04.1` → `2026-10-04.2`. These diagnostic/label cleanups require no further bump.

## Deployment scope and remaining acceptance

Deploy the merged commit using `deploy/azure/deploy.sh rollouts/demo-hospital --profile live` to the existing `mcp-demo-hospital-canary` in `healthcare-rg`. Check the ready revision, image, authentication, all four tools and actual ContextForge discovery. Preserve existing gateway/team/server identities. Actual results are recorded below.

Manoj's summary-write scope and a confirmed synthetic tenant still need evidence before a live write journey. The knowledge provider remains unconfigured. Voice consumers must adopt the eight summary arguments, five result outcomes, single bearer, and five trusted headers described in `docs/handover/VOICE-TEAM.md`. A deployed adapter is not proof of a working complete voice journey or the under-one-second audio target.

## Deployed and gateway-verified

- PR [#13](https://github.com/Garry2012/healthcare-tools/pull/13) merged with history preserved: `e96242fa1e0754d2bd9c6d7f81daf05075f101dd`. PR CI and main CI passed. The deployment image contains exactly this reviewed source tree.
- `deploy/azure/deploy.sh rollouts/demo-hospital --profile live`: exit 0. ACR run `cu5v` succeeded; image `acrfd399536.azurecr.io/frontdesk-mcp:e96242f`, digest `sha256:b9e19e1e5c1231b5aaed0f2a65c2b0d132d5281f6250264671d15192e4001eb3`.
- Ready revision `mcp-demo-hospital-canary--0000002`, 100% latest-revision traffic. URL: `https://mcp-demo-hospital-canary.icytree-6543aaa9.centralindia.azurecontainerapps.io/mcp/`.
- Live smoke passed: health/readiness, operational dependency, unauthenticated rejection, four-tool discovery, availability and honest knowledge `COULD_NOT_CHECK / NOT_CONFIGURED`.
- Existing ContextForge registration `frontdesk-healthcare-canary` and existing team visibility preserved. Passthrough allowlist updated to the five supported headers. Added the summary tool to the existing `frontdesk-healthcare` virtual server, preserving its team and original tool associations.
- Actual gateway input schemas compare structurally equal to the adapter: Opus M1 is verified for this deployed gateway. No comparison was weakened. All output schemas and descriptions also compare equal after the extra refresh below.
- Virtual URL: `https://mcp-gateway.icytree-6543aaa9.centralindia.azurecontainerapps.io/servers/19d78ceb97994906b0c7f1990c7e3b58/mcp`. An admin session discovered four tools and invoked summary without trusted context: exactly `{"outcome":"NOT_SAVED"}`. No summary or appointment was written.
- On initial discovery, the gateway stored `record_call_summary.outputSchema = null`, although its input schema matched. Explicit `POST /v1/gateways/d939402fbd1a4fb5930db984906026e4/tools/refresh` returned HTTP 200, success, `toolsUpdated: 1`; a fresh comparison then passed for every input/output schema and description. The registration helper checks inputs only, so complete output-schema inspection remains a separate release acceptance step.
- No resource groups, database, legacy apps or Key Vault secrets were deleted. The reviewed deploy script removed only the canary's unused `knowledge-token` app reference as it replaced the invalid placeholder knowledge URL with the profile's empty value. The vault secret and legacy lifecycle app reference remain.
- Token exchange using the stored Manoj credentials returned HTTP 200. This does not prove `calls.write`; no live write was attempted without a confirmed synthetic tenant. Knowledge provider, scoped voice-client authorization, live writes and full voice latency remain external acceptance work.

Pasted deployment/check output and the safely projected Azure state are in [21-deployment.txt](call-summary-evidence/21-deployment.txt). [22-contextforge.json](call-summary-evidence/22-contextforge.json) retains a real gateway summary row and the hashes of all four discovered input/output schemas. These are metadata only, with no credentials or caller data.
