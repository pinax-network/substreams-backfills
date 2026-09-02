# Aerodrome Slipstream CL Base — `QmasYjyp...` (M7)

This directory freezes the exact deployed Graph target for Aerodrome Slipstream
CL on Base. It is an immutable target and static behavior baseline, not a
Substreams implementation, parity result, eligibility decision, or backfill
readiness claim.

## Immutable target

- Deployment: `QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV`
- Schema: `QmTiEqVtfjTDY8DRkj17eLKSAyajHNz8r7Yg9cRgXwrWfF`
- Factory: `0x5e7bb104d84c7cb9b682aac2f3d509f5f406809a`, start block `13,843,704`
- NonfungiblePositionManager: `0x827922686190790b37229fd06084350e74485b72`, start block `13,843,719`
- Network: `base`
- Manifest spec/API: `1.2.0` / `0.0.7`
- Concrete graft: none

`reference/` contains the exact deployed manifest, schema, six ABIs, and three
mapping WASMs. The provenance lock records the byte count, SHA-256 digest, and
CIDv0 for every object. Run its offline verifier with:

```sh
cargo xtask verify-target aerodrome-slipstream-base
```

## Protocol and source boundary

The manifest repository field names `Uniswap/uniswap-v3-subgraph`; that is
lineage metadata, not protocol identity. The deployed Factory has Slipstream's
four-argument `PoolCreated(address,address,int24,address)` event, the deployed
Pool ABI contains Slipstream gauge/reward/unstaked-fee methods, and the target
uses Aerodrome's Base Factory and position-manager addresses.

No public commit was found that contains this exact Slipstream source fork. The
bounded search covered public code matches for the deployment CID, all three
mapping CIDs, and the unique `addMissingWhitelistedPools` helper, plus direct
history/schema inspection of `Uniswap/v3-subgraph` as observed on 2026-08-31.
Consequently the provenance record intentionally leaves the source commit,
tree, parent, and exact build toolchain unset and marks byte reproduction as
not attempted. The deployed IPFS objects remain fully content-addressed;
source provenance is not silently inferred from the manifest's repository
string.

## Static layout and behavior boundary

`layout-profile-v1.json` records the exact component, handler, call-injection,
schema, ABI, mapping-export, constant, and public-prior-art differences. The
20-entity, 302-field target is the retained deployed Qma8 Uniswap V3 schema plus
`Token.version` and `Position.collectedToken0` / `collectedToken1`; all target
entities are mutable.

Neither generic package in sibling `substreams-evm` is a drop-in:

- `dex/aerodrome` decodes Solidly V2 Pool/PoolFactory events, including a
  boolean `stable` PoolCreated field; it is not Slipstream CL.
- `dex/uniswap-v3` is an event map without the target's NPM handlers, Graph
  entity mutations, contract-call inputs, schema, store ordering, or PoI.
  Its Factory decoder also expects canonical V3's separate `fee` and
  `tickSpacing` arguments.

The retained WASM names expose important target-specific work that must be
resolved before implementation: `Token.version`,
`addMissingWhitelistedPools`, Factory `getPool(address,address,int24)`, NPM
position accounting, and a Flash handler that updates Pool fee-growth fields
without creating a `Flash` row. The profile records these as static facts, not
as a complete value/order/persistence proof.

## Remaining gates

Runtime work must not begin until fresh evidence fully accounts for both
required clusters by inventorying every current copy or supplying fresh
structural absence proof. When viable healthy copies exist, independently select the
minimum stable same-pod 24-hour ETA and minimum stable same-pod 72-hour ETA across all viable
copies; the minima may belong to different copies and must both exceed 28 days
or be non-converging. Either minimum at or below 28 days stops implementation,
compute, and load. If no viable copy exists anywhere, eligibility requires fresh
structural absence proof from both clusters. The exact source
revision or an independently complete retained-WASM specification must also be
resolved. After implementation, canonical Base fixtures must prove entity
values, save order, failure behavior, PoI, VID/block ranges, and PostgreSQL
parity. Compute, load, Kubernetes, production, and readiness gates remain
false; issue #86 stays open.
