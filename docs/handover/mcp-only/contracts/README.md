# Manoj operational contract snapshot

[manoj-openapi-20260930.yaml](manoj-openapi-20260930.yaml) is the unchanged public specification retrieved on 30 September 2026 from [the published OpenAPI URL](https://healthcare-contract-docs.icytree-6543aaa9.centralindia.azurecontainerapps.io/openapi.yaml), linked by the owner's documentation site.

- SHA-256: `b8f282718c2c45410dd0dd403369223b9cbe8dea045ee044207aa1e52ec2de78`
- OpenAPI: 3.0.3; API version: `0.3.0-draft`.
- 20 paths, 23 operations. The draft version alone does not identify a revision; pin the hash.
- The default server is a public contract mock with no `/api/v1` prefix. The listed local backend has that prefix; the deployed backend hostname is a placeholder. Configure the full service base URL explicitly.
- This is an external interface document, not Manoj's backend implementation and not our legacy `docs/frontdesk-api/openapi.yaml`.

Verify the file on macOS with:

```bash
shasum -a 256 docs/handover/mcp-only/contracts/manoj-openapi-20260930.yaml
```

## Known defects at the pinned revision

Five unquoted descriptions in YAML flow mappings contain commas, producing four invalid component schemas:

| Snapshot lines | Field |
|---|---|
| 1208–1209 | `CallSummaryCreate.properties.doctorId` and `.appointmentId` |
| 1235 | `Error.properties.error.properties.message` |
| 1256 | `ClientCredentialsGrant.properties.scope` |
| 1278 | `LoginResponse.properties.role` |

The earlier contract investigation validated 25 discovered typed inline examples successfully; that does not make the full document valid. Request an owner-published correction when available. If development needs a temporary test overlay, quote only these five descriptions, record source/overlay hashes and label it test-only. Do not overwrite this original or silently add guessed semantics. This handover does not contain an implemented overlay or stub.

The [plan](../PLAN.md) records collective consumer mismatches, authentication, missing agreements and test scenarios. There is no slot endpoint. `/availability` is a live board over the usual schedule, not reservable-slot inventory. The UNKNOWN callback-only policy is our agreed consumer policy; the original specification retains the owner's wording unchanged.

A new owner revision should be reviewed as a contract change before updating fixtures. Shobhit's contract is still pending; do not present a guessed endpoint as published documentation.
