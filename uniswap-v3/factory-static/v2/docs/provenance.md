# Factory static v2 provenance

## Audited base

- Commit: `20b3864656bfa1fabb48cfeaba08518b26e81532`
- Tree: `3c04abbd9319d340d41230fc7a06d6a3b44f2453`
- Toolchain: checksum-pinned WABT `1.0.35`

## Direct digest roots

| Input | SHA-256 |
|---|---|
| `scripts/verify-uniswap-v3-factory-pool-price-init.py` | `41f8a7b09fb628bf94dcffd702a7eabdb9ecb0faf9d43b3898b6590024e61786` |
| `uniswap-v3/factory-pool-price-init/v1/contract.json` | `fe441948746b6bf7b7fd8f0872ebc58c8297412a643ed4fe1fd0120dca14e56a` |
| Canonical price-parent contract | `6578d2ed23f60d3535ac7970030f30a4f8ea0b9605576d3a7a5c69e535751f34` |
| `scripts/uniswap_v3_wat_runtime.py` | `bd555b5d44bed144777e35b361fcb63e275d7f21b774db3ffe0e08bef3bf4411` |

The price-parent verifier is rerun, not trusted as opaque JSON. It recursively
verifies the BigInt, fee-growth-initialization, Factory-effects, modern-static,
field-semantics-v2, writer-matrix, writer-compatibility, and retained-artifact
inputs. V2 recursively loads every JSON contract reachable through those
records, checks each declared raw and canonical digest, and records a flattened
transitive input manifest plus its canonical digest as an additional closure
root.

## Retained legacy Factory artifacts

| Profile | Mapping CID | WASM SHA-256 | WAT SHA-256 |
|---|---|---|---|
| `legacy-base-root` | `QmUN4pxwjMTfNem7rf1sKNFNHDsfzpbcTP93RxPAczgkvj` | `0855ce1d5260cd8395628dfac2e18db063909168c58e7d5de118612fee9f9a4e` | `c2e7425784b498481ee8a822be18b59edd7aa6dd27712d8d093696cf0b8b1684` |
| `legacy-mainnet-qmrv` | `QmT8CKmLDFFCgwYnubFhKXUsuer5rfJKPT4PrCsv9tTwjV` | `c90c4b86b184d8ffed606f3264d6f3b921421ef7dce2cb35484dd7faaf452cd4` | `4263d51999d58769c06bef6da1aed4c24c1c846f4b0aaed9142bf3bd912ecf9b` |
| `legacy-mainnet-root` | `QmUu9rnGvUiBbF9pLnuJQab1wHXqjooo3bY5cZDVTyQQgr` | `ab7c84297665ab608ce3c6b8cc71f1c584ae7f2a94ebe674993b069d6b8b5c98` | `1fbcd7b7305dd0e0eb2e9de2e64ecb023e9aa5abe29f7562be4dad72bf561f4d` |
| `legacy-mainnet-stable` | `QmcsaU3DrUqZHZLzrrWT9aW4EVQuS54wxNHynq8g1PvESL` | `1bde476d96fd4ba7720246a351c4de0f129693d838f9a39a660097c85d1edead` | `d44ed8c0bbd1bdf62635871b475fbe1a22c8d3a4b88e5d77e6827e3e61b70f81` |

These four artifacts project to six legacy ancestry segments. Modern v1
provides the remaining two segment proofs.

## Adversarial validation

Focused tests regenerate the committed contract and reject compile-valid WAT
mutations to a direct field key, direct Value wrapper, helper-hidden key,
Entity allocation, entry-array push, and StringArray kind tag. They also reject
scope, checkbox, broad-gate, source-digest, transitive-manifest, segment,
pairwise-diff, and duplicate-JSON-key mutations.

The verifier binds the complete reachable-function body inventory in addition
to the 44-site and 78-invocation ledgers, so a mutation outside a selected
field slice cannot silently refresh the aggregate static claim.
