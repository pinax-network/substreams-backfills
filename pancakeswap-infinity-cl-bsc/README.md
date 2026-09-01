# PancakeSwap Infinity CL BSC — `QmVjXU7y…` (M5)

This directory freezes the exact deployed Graph target and the source revision that
reproduces it. It is the reviewable contract for a future V4-derived implementation;
it is not a runtime-parity or backfill-readiness claim.

## Immutable target and exact source

- Deployment: `QmVjXU7yQNyyLphPGqoz8iBzqu5YXphooFJn15JqZ6ZMFz`
- Schema: `QmcWb81VRk9SycZYgLyr9i6tYCnHsVsPTyTvfNpywDRJfr`
- Source: <https://github.com/NgoKimPhu/infinity-cl-subgraph>
- Exact commit: `40b0021be04cda3e32dde8e3cf0c3397863fc0c0`
- Exact tree: `b7a7778bc5c7f316cc46913b7b1d54ffcfa07c22`
- PoolManager: `0xa0FfB9c1CE1Fe56963B0321B32E7A0302114058b`, start block `47,214,308`
- PositionManager: `0x55f4c8abA71A1e923edC303eb4fEfF14608cC226`, start block `47,215,015`

`reference/` contains the deployment manifest, schema, five ABIs, and mapping
WASM. The provenance lock records every byte count, SHA-256 digest, and CIDv0.
The source repository's historical CI used floating Node `18.x`, unversioned Yarn,
`yarn install`, and `yarn build`; it does not identify an immutable original deployment
toolchain. Independently, a clean build in our newly pinned Node 24.13.1/npm 11.11.0
reproduction environment recreates all seven child artifacts byte-for-byte and resolves
to the exact deployed manifest. Provenance keeps these two facts explicitly separate.

Run the offline lock verifier with:

```sh
python3 scripts/verify-pancakeswap-infinity-cl-bsc-target.py
```

Reproduce the source build and compare it with the deployed bytes with:

```sh
./scripts/verify-pancakeswap-infinity-cl-bsc-source.sh
```

## V4-derived implementation boundary

`layout-profile-v1.json` captures the target-specific contract: authoritative
Pancake pool IDs and PoolKey parameters, hooks registration, static initialize-fee
behavior, intentionally ignored swap/protocol fee fields, PositionManager transfer
semantics, all-17-entities-mutable layout, aggregates, metadata, and BSC pricing.

The imported Uniswap V4 implementation remains prior art, not a drop-in runtime.
Pancake adds `Pool.parameters` and `Pool.hooksRegistration`; omits Arrakis and Base
hook pricing behavior; uses different initialize/swap ABIs and BSC pricing; and must
write six event entities as mutable rather than immutable. These differences require
target-specific decoder/protobuf, Store, reducer, PoI, temporal writer, seed/replay,
schema, package, and fixture work before parity can be claimed.

## Remaining gates

Backfill implementation remains fail-closed until fresh evidence fully accounts
for both required clusters by inventorying every current copy or supplying fresh
structural absence proof. When viable healthy copies exist, independently select
the minimum stable same-pod 24-hour ETA and minimum stable same-pod 72-hour ETA across all viable
copies; the minima may belong to different copies and must both exceed 28 days or
be non-converging. Either minimum at or below 28 days stops implementation,
compute, and load. If no viable copy exists anywhere, eligibility requires fresh
structural absence proof from both clusters. After implementation, canonical BSC
fixtures must prove Graph Node entity,
save-order, PoI, VID, block-range, and PostgreSQL parity. Any restore must first use
a disposable paused target; allocation or activation needs separate approval.
