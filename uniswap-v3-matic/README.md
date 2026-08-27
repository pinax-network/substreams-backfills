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

The closest located source is Uniswap/v3-subgraph PR 259, tree
`25dc5b93eab5464f197edd7479e2896ce85585df`. Its generated manifest, normalized source
schema, ABIs, and mapping name sections match the deployed artifacts. A locked Graph CLI
0.64.1 / AssemblyScript 0.19.10 build does **not** reproduce either deployed mapping WASM,
so the provenance deliberately labels that commit a structural candidate, not an exact
source pin.

## Remaining gates

This baseline does not authorize implementation, loading, or activation. M4 still requires:

1. exact reproduction or identification of both deployed mapping binaries;
2. fresh 24-hour and same-pod 72-hour evidence proving the fastest healthy Graph Node path
   remains greater than 28 days; and
3. final comparison with the certified V3 family contract after M3.

The historical Kan copy remains the native-sync candidate until the eligibility gate says
otherwise. Every eventual backfill lands paused and needs independent certification and
operational approval.
