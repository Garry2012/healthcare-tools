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

Deploy the merged commit using `deploy/azure/deploy.sh rollouts/demo-hospital --profile live` to the existing `mcp-demo-hospital-canary` in `healthcare-rg`. Check the ready revision, image, authentication, all four tools and actual ContextForge discovery. Preserve existing gateway/team/server identities. Record actual results after deployment.

Manoj's summary-write scope and a confirmed synthetic tenant still need evidence before a live write journey. The knowledge provider remains unconfigured. Voice consumers must adopt the eight summary arguments, five result outcomes, single bearer, and five trusted headers described in `docs/handover/VOICE-TEAM.md`. A deployed adapter is not proof of a working complete voice journey or the under-one-second audio target.
