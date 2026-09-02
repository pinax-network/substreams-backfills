# Uniswap V3 logical-oracle discovery contract

`v1/contract.json` retains the first deployment-scoped GraphQL discovery
snapshot for the current Uniswap V3 mainnet and Base deployment CIDs. It makes
the useful evidence reproducible without pretending that a public gateway
response is already an authoritative differential oracle.

## What the snapshot proves

At the retained observation time, both exact deployment CIDs answered the
current-state query, echoed their own CID in `_meta.deployment`, reported no
indexing error, and returned non-empty `TickDayData`, `Position`, and `Pool`
samples. Both returned empty samples for `Collect`, `Flash`, and
`TickHourData`. This is current-head logical evidence that matches the static
mapping audit; it is not a history-wide absence proof.

The current mainnet deployment also answered at blocks 19,470,000 and
19,470,001. The retained response shows unchanged sample Pool and Position
state across that boundary, but historic `_meta.block.hash` and `timestamp`
were null. A canonical chain-RPC sidecar is therefore still required before
that sample can enter a parity certificate.

The sole Base indexer refused block 19,852,000 as missing/pruned. That refusal
is retained as a required negative result: CI must not convert an unavailable
Base history sample into a passing oracle gate.

## Source and routing boundary

The observed public endpoint routes deployment queries through The Graph
gateway using a server-side key. The contract pins the contemporaneous
`nightswatchhq/lodestar` source revision, tree, Git blobs, and source-file
SHA-256 values that explain the observed behavior. There is no independent
attestation that the production site ran that exact revision, and the gateway
did not identify the exact serving indexer for each query or its Graph Node
version.

The separate status snapshots list candidate serving indexers. They do not
bind a particular query response to one of those indexers.

## Fail-closed promotion boundary

Every production-relevant promotion gate remains false, including:

- authoritative logical oracle and history-wide required absence;
- Base historical access and ancestor-deployment access;
- exact per-query indexer and Graph Node version;
- canonical historic block hashes, physical history, and proof of indexing;
- final parity package and production backfill permission.

Run the hermetic verifier and its negative tests with:

```bash
cargo xtask verify-logical-oracle
cargo test -p xtask logical_oracle
```

The verifier checks every retained byte against a hard-pinned digest, validates
the query shapes and response semantics, and rejects any promoted gate.
