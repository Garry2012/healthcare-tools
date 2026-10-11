# Manoj operational contract snapshot

## Current pin: 0.4.0

[manoj-openapi-20261007.yaml](manoj-openapi-20261007.yaml) preserves the served specification byte-for-byte, re-downloaded on 8 October 2026 from [the public OpenAPI URL](https://healthcare-contract-docs.icytree-6543aaa9.centralindia.azurecontainerapps.io/openapi.yaml).
The dated filename identifies the reviewed 7 October contract revision. The source advertises `0.4.0-draft`; identify it by hash, not the version alone.

- Source SHA-256: `d3e93f45498fb86feeb5bb93c0adaba7cff47b48daa21ac810790b5483e96c80`
- Quoting-only [test overlay](manoj-openapi-20261007.test-overlay.yaml) SHA-256: `1217015de39f137ebef159915f4fa90dfcf2fa196277ee43b6e5ce192679ff2f`
- OpenAPI 3.0.3, 33 paths. The contract now includes capabilities and per-doctor slots; the approved integration work is in [SLOTS-PLAN.md](../implementation/SLOTS-PLAN.md). Pinning does not mean those operations are implemented in MCP.

Exactly six flow-mapping descriptions are quoted in the test overlay. No other bytes, fields or semantics change; even the source's literal `: null` fragments inside those descriptions are preserved.

| Line | Field |
|---|---|
| 2327 | `CallSummaryCreate.properties.doctorId` |
| 2328 | `CallSummaryCreate.properties.appointmentId` |
| 2351 | `Error.properties.error.properties.message` |
| 2370 | `ClientCredentialsGrant.properties.scope` |
| 2396 | `LoginResponse.properties.role` |
| 2460 | `AdminStaff.properties.role` |

`tests/test_contract.py` pins both hashes, limits the overlay to quoting on these six lines and checks client literals/patterns and the owner's board example. `tests/test_stubs.py` validates fixture responses against this overlay. Neither file implements the owner's backend. The overlay is test-only and never deployed; the unmodified original remains the integration authority.

```bash
shasum -a 256 docs/handover/mcp-only/contracts/manoj-openapi-20261007.yaml docs/handover/mcp-only/contracts/manoj-openapi-20261007.test-overlay.yaml
```

The 0.3.0 files and the dated observations below remain historical evidence; they are no longer the active test pin. Historical statements about missing slots and live authentication describe the dates recorded below, not current owner readiness.

# Historical 0.3.0 contract snapshot

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

At this revision, `services/mcp/tests/test_contract.py` checked these hashes, the five-line overlay and the client literals. Those active checks now use the 0.4.0 pin above. The overlay is never deployed; it exists so consumer tests can parse the contract. Replace it with the owner's corrected revision when one is published.

The [plan](../PLAN.md) records collective consumer mismatches, authentication, missing agreements and test scenarios. There is no slot endpoint. `/availability` is a live board over the usual schedule, not reservable-slot inventory. The UNKNOWN callback-only policy is our agreed consumer policy; the original specification retains the owner's wording unchanged.

**Live server metadata (1 October 2026, later in the day):** Manoj's deployed backend (`healthcare-api`, `/api/v1`) now serves `/api/v1/openapi.yaml` with SHA-256 `6f827be1b62e22f4f4f0c54174d22a1b40bd02ab130ec74ce5f83b8b9aa80391`. The only difference from this snapshot is the fourth `servers` entry: the `https://{host}/api/v1` placeholder became `https://healthcare-api.icytree-6543aaa9.centralindia.azurecontainerapps.io/api/v1` ("Real API in Azure … Needs registered credentials"). Paths, operations and schemas are unchanged, so the pinned snapshot, overlay and client types stay authoritative; the live copy is kept as evidence in `../implementation/evidence/manoj-openapi-live-20261001-servers-only-diff.yaml`. A revision that changes paths or schemas is a contract change to review before updating fixtures.

**Environments used for integration testing:**

| Environment | Base URL | Auth behaviour observed | Use |
|---|---|---|---|
| Public contract mock (Prism) | `https://healthcare-contract-mock.icytree-6543aaa9.centralindia.azurecontainerapps.io` (no `/api/v1`) | `401` without a bearer; any bearer accepted; `POST /auth/token` issues the example token for any client credentials; bodies are the spec's static examples; no state | transport, base-path, auth-discipline and shape checks (`OPS_E2E_MODE=mock`) |
| Live backend | `https://healthcare-api.icytree-6543aaa9.centralindia.azurecontainerapps.io/api/v1` | `401 Missing bearer token` on reads; `401 Invalid client credentials` for unregistered clients | real-service verification once Manoj registers a client (`OPS_E2E_MODE=live`) | Shobhit's contract is still pending; do not present a guessed endpoint as published documentation.
