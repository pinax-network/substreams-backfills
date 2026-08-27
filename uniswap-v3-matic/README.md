# uniswap-v3-matic — `QmWqwrVt…`

This deployment is an older two-component Uniswap V3 variant (`Factory` data source plus
`Pool` template, with no PositionManager or Flash handler). Its 16-entity schema differs
from the 20-entity `Qma8a81T…` mainnet/Base family, so it is a separate family rather than
a chain-configuration-only variant.

Factory `0x1F98431c8aD98523631AE4a59f267346ea31F984` @ 22,757,547 (matic).

## Immutable target baseline

`reference/` vendors the deployed IPFS manifest, schema, and five ABIs. The provenance lock
pins their CIDs, source byte counts and SHA-256 digests, the two deployed mapping WASM CIDs
and digests, exact data-source/template and handler shape, entity mutability, and the full
logical schema difference from the imported `Qma8a81T…` family. Run:

```console
python3 scripts/verify-uniswap-v3-matic-target.py
```

The earliest exact source is Uniswap/v3-subgraph commit
`d07374a05719e68a10a339f79cdfbc048807cfdc`, tree
`8f5cefd138068952bee909522a0f1d88fdc87b42`; mainline merge `4c9c672…` has the same
whole tree. With Node 18.18.0, Yarn 1.22.22, Graph CLI 0.64.1, Graph TS 0.38.1, and the
locked AssemblyScript dependencies, it reproduces both deployed mapping WASM objects
byte-for-byte. The Factory output is 63,842 bytes and the Pool output is 82,750 bytes.

The mapping bytes identify the exact input tree, but not a unique later version label:
later commits that do not change Matic configuration, source, or tooling can retain the
same binaries. The provenance therefore pins the earliest exact commit and records the
equivalent mainline merge without claiming a unique deployment label.

## Remaining gates

This baseline does not authorize implementation, loading, or activation. M4 still requires:

1. fresh 24-hour and same-pod 72-hour evidence proving the fastest healthy Graph Node path
   remains greater than 28 days; and
2. final comparison with the certified V3 family contract after M3.

The historical Kan copy remains the native-sync candidate until the eligibility gate says
otherwise. Every eventual backfill lands paused and needs independent certification and
operational approval.
