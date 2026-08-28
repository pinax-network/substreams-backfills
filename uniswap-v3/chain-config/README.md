# Uniswap V3 versioned ChainConfig

This directory turns the reviewed mainnet-only source import into one configured
runtime without editing `uniswap-v3/source/`. The overlay is deliberately
separate so the exact source/provenance contract remains independently
verifiable.

## Contract

The runtime accepts only an exact selector of the form:

```text
version=1;network=<mainnet|base>;sha256=<approved raw config digest>
```

Every handler that reads chain-sensitive behavior receives that selector as an
explicit `params` input and validates it before writing or emitting output.
Missing selectors, extra selector keys, duplicate keys, unknown versions or
networks, unapproved digests, malformed JSON, unknown JSON fields, incomplete
objects, malformed addresses, duplicate lists, and inconsistent start
boundaries fail closed.

| Field | Mainnet v1 | Base v1 |
|---|---|---|
| Config SHA-256 | `30f5caf9…6bb55` | `2eeed825…b2832` |
| Factory | `0x1F98431c8aD98523631AE4a59f267346ea31F984` | `0x33128a8fC17869897dcE68Ed026d694621f6FDfD` |
| Position manager | `0xC36442b4a4522E871399CD717aBDD847Ab11FE88` | `0x03a520b32C04BF3bEEf7BEb72E919cf822Ed34f1` |
| Module/factory start | `12,369,621` | `1,371,713` |
| Position-manager start | `12,369,651` | `1,371,713` |
| Wrapped native | mainnet WETH `0xc02a…6cc2` | Base WETH `0x4200…0006` |
| USD reference pool | `0x8ad5…e6d8` | `0x4c36…4b18` |
| Minimum native locked | `52` | `1` |
| Stable/whitelist entries | 6 / 21 | 1 / 4 |
| Static metadata fallbacks | 6 | 0 |

The Base stable list intentionally contains
`0xb97ef9ef8734c71904d8002f8b6bc66dd9c48a6e`, an Avalanche USDC
address. That surprising value is present in the deployed Base mapping WASM and
is preserved rather than “corrected.” The deployed ignored-pool and swap-only
hotfix behavior is likewise pinned. See
`provenance/uniswap-v3-chain-config-v1.json` for the deployment, mapping, ABI,
schema, graft, digest, and read-only reference-pool evidence.

## One binary, two executions

Both generated manifests point to the same single build output:

```text
target/wasm32-unknown-unknown/release/substreams_uniswap_v3.wasm
```

CI builds it once, packs both manifests, parses each SPKG at the protobuf wire
level, and rejects either package unless its one embedded WASM payload is
byte-identical to the shared build and to the other package. Substreams
execution-module hashes are recorded separately: they are expected to differ
because `params` and `initialBlock` are inputs to those hashes.

CI artifacts and their hashes are diagnostic evidence only. CI now combines
the raw imported mainnet package and both configured packages into a
controlled-build candidate manifest. The manifest binds the actual pull-request
head (or push) commit, repository/import trees, config/overlay/target-schema
digests, package and embedded-WASM hashes, every module execution hash, and the
observed toolchain/platform. Its trust boundary remains explicitly false for
promotion, authoritative Graph reference, physical/PoI parity, and production
pinning. This does not freeze a production package.

## Reproduce locally

From the repository root, with the pinned Python dependencies installed:

```bash
python3 scripts/build-uniswap-v3-chain-manifests.py --check
python3 scripts/verify-uniswap-v3-chain-config.py
runtime_dir=$(mktemp -d /tmp/uniswap-v3-configured.XXXXXX)
./scripts/materialize-uniswap-v3-chain-config.sh "$runtime_dir"
```

Build and pack from that materialized directory. Never apply the overlay in
place to `uniswap-v3/source/`.

## Fixed-range mainnet comparison

The sibling
[`mainnet-chain-config-parity-v1.json`](../fixtures/mainnet-chain-config-parity-v1.json)
profile covers `[12,369,621, 12,370,674)`, including the configured
position-manager boundary at `12,369,651` and the historical first-mints smoke
slice at `12,370,624`. The old smoke output was not retained and is range
selection context only.

`scripts/run-uniswap-v3-mainnet-chain-config-parity.sh` is the exact-revision,
operator-only execution contract. It builds the raw and configured packages in
a disposable detached worktree and captures every Ethereum mainnet block hash
and timestamp in the range before and after both streams. The
checksum-authorized Substreams v1.20.3 CLI is used only for `pack` and `info`.
A repository-owned Go 1.26.5 client makes one direct protocol-v3 request per
package and records every block response, including explicit zero-byte
`graph_out` payloads. It accepts completion only after all 1,053 sequential
records and a clean EOF; missing outputs are never reconstructed.

Each invocation sidecar binds its package, exact source revision, source-built
client identity, sanitized request, endpoint, session, completion clocks, and
raw stdout/stderr hashes. The verifier cross-checks both streams against the
unchanged full-range RPC maps and compares exact ordered protobuf bytes. Every
candidate payload is scanned for all supplied secrets before exclusive
publication, immutable output paths cannot be reused, and the private evidence
directory must live outside the repository. These are local provenance records,
not signed remote attestations. See
[`PARITY.md`](../PARITY.md) for the invocation and the exact evidence boundary.

## Evidence boundary

This architecture, offline verifier, and controlled-build candidate machinery
are complete. This repository change does not run the live range. Issue #12
must remain open until the separately controlled gates are complete:

- fixed-range mainnet logical parity against the imported baseline;
- implementation and authoritative coverage for the currently absent
  `Collect` and `Flash` entity rows;
- Base Firehose/reference ranges covering creation, positions, active pools,
  pricing, and aggregate windows;
- a controlled production build and immutable package/module provenance;
- final consumer pin updates.

No live stream, workflow submission, database mutation, deployment, or
production package freeze is performed by this directory or its CI checks.
