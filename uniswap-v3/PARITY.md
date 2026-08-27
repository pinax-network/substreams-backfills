# Uniswap V3 parity contract

This file separates what the imported parity source proves from the work still
required before either deployment can be loaded or served.

## Proven by the import

The exact source tree at commit
`42c7b15345e6df80561b694e52a0eb622b374b96` contains 20 GraphQL entity types.
After entity directives are excluded, its complete entity/field/type contract
has SHA-256
`6c801fc4c141c0ae12dbb937652f0dd49c9be5bd3b1b3c8e38bdb92fe6efec5d`,
which matches the schema stored at IPFS CID
`Qma8a81T9XoX5Pbkrk8J3kxMhWdXJzFSYZge1wGi3QZBru`.

The source changes relative to its upstream base are:

- output field renames for `tvlUSD` and `untrackedVolumeUSD` while retaining
  the original Store key names;
- removal of `Pool.totalValueLockedETHUntracked`, which is absent from the
  target schema;
- `TickDayData` and `TickHourData` output wiring using
  `0x{pool}#{tick}-{time_id}` identities and initialized aggregate fields.

The target declares `Transaction`, `Swap`, `Mint`, and `Burn` as mutable. The
imported logical schema declares those four entities immutable. That is a real
physical-layout difference which the future schema profile and loader must
handle; it is not erased by the logical contract match.

## Evidence not yet sufficient for certification

The previously reported 50-block Firehose run is useful smoke evidence, but no
block-hash-bound output, query response, or evidence digest was retained in this
repository. It cannot certify every handler or entity, tick identity parity,
zero-value behavior, temporal rows, or proof of indexing.

The current source is also Ethereum-mainnet-specific. It hard-codes the
factory, position manager, start boundaries, wrapped native token,
reference-price pool and tokens, stablecoins, whitelist, and token exceptions.
Base requires a complete versioned `ChainConfig` wired into every module that
reads those values. Both manifests must then prove they use the same compiled
WASM bytes with different, fully pinned configurations.

Finally, `graph_out` emits standard coalesced `EntityChanges`. That format does
not by itself preserve every intermediate save, empty-but-triggered handler, or
causality detail needed for exact Graph Node proof of indexing. Physical and PoI
certification therefore waits for the V4-derived ordered protocol, schema
profiles, and generic verifier.

## Required order

1. Preserve this exact source import and hermetic logical checks.
2. Implement and differentially test complete mainnet/Base `ChainConfig`.
3. Capture canonical Firehose fixtures and authoritative historical GraphQL or
   read-only database evidence for every handler and aggregate boundary.
4. Certify mainnet through the generic ordered runtime against an exact stopped
   oracle and disposable scratch target.
5. Land mainnet only in named, revalidated targets, paused.
6. Repeat exact certification for Base with the same WASM and its pinned config;
   land paused and request activation separately.
