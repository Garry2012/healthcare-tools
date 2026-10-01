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

The earlier contract investigation validated 25 discovered typed inline examples successfully; that does not make the full document valid. Request an owner-published correction when available. Do not overwrite this original or silently add guessed semantics.

## Test-only quoting overlay

[manoj-openapi-20260930.test-overlay.yaml](manoj-openapi-20260930.test-overlay.yaml) is a **test-only** copy of the pinned snapshot in which exactly the five descriptions above are quoted. Nothing else changes: no endpoint, field, enum or wording.

- Source SHA-256: `b8f282718c2c45410dd0dd403369223b9cbe8dea045ee044207aa1e52ec2de78`
- Overlay SHA-256: `e21869b20a6c956d12d69873b138b721fc7676ba6e6f86b5ecc0a4a7af4dd1a3`

`services/mcp/tests/test_contract.py` fails if either file or hash changes, if the overlay differs from the original on any line other than 1208, 1209, 1235, 1256 and 1278, or if the MCP client types in `services/mcp/src/frontdesk_mcp/contract.py` drift from the contract's enums, patterns and examples. The overlay is never deployed; it exists so consumer tests can parse the contract. Replace it with the owner's corrected revision when one is published.

The [plan](../PLAN.md) records collective consumer mismatches, authentication, missing agreements and test scenarios. There is no slot endpoint. `/availability` is a live board over the usual schedule, not reservable-slot inventory. The UNKNOWN callback-only policy is our agreed consumer policy; the original specification retains the owner's wording unchanged.

On 1 October 2026 Manoj's deployed backend (`healthcare-api`, `/api/v1`) served `/api/v1/openapi.yaml` with the same SHA-256 as this snapshot; the deployed server list adds `/api/v1` ("This deployment") first. A new owner revision should be reviewed as a contract change before updating fixtures. Shobhit's contract is still pending; do not present a guessed endpoint as published documentation.
