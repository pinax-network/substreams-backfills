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

## Static layout and mapping behavior profile

[`layout-profile-v1.json`](layout-profile-v1.json) is the repository-only M4-A contract.
It binds the exact Matic mapping source's complete local import closure and compares the
target in both directions with the retained deployed `Qma8a81T…` schema artifact. The
retained deployed schema—not the imported Rust source schema—is authoritative for
mutability: all 20 `Qma8a81T…` entities are mutable, while Matic makes `Burn`, `Collect`,
`Flash`, `Mint`, `Swap`, and `Transaction` immutable.

The static gap is larger than four omitted entities. Matic also uses `Bytes!` IDs for
`Pool` and `Token`, makes `Tick.poolAddress` non-null `Bytes!`, omits fee-growth fields and
eleven Tick fields, handles Pool `Collect` directly, keeps `Token.poolCount` at zero, and
has no PositionManager, tick-window, fee-growth, or Flash writer path. Its exact mapping
also saves `Transaction` on every Pool event even though the deployed entity is immutable;
the same-transaction multi-event effect remains a required Graph Node runtime oracle.

No existing V3 map or store is certified unchanged by this profile. It records conditional
reuse candidates (transport, standard event decoders, selected cache stores, and decimal/
sqrt-price math), the required Matic adapters and replacements, and the M2/M3 contracts
that must be complete before promotion. Every implementation, eligibility, runtime,
logical/physical/PoI parity, backfill, and production gate remains false.

The normal verifier checks the retained `Qma8a81T…` schema and M3 closure hashes, the
bidirectional entity/field/type/nullability/mutability difference, the behavior and reuse
contract, and the false readiness gates. The exact-source CI job additionally rechecks
every transitive mapping source byte and Git blob before accepting the byte-exact build.

## Remaining gates

This profile does not authorize implementation, loading, or activation. M4 still requires:

1. fresh 24-hour and same-pod 72-hour evidence proving the fastest healthy Graph Node path
   remains greater than 28 days; and
2. the M2 ordered loader, Matic physical schema profile, and certification harness;
3. a certified M3 Factory/Pool handler, field-writer, runtime-population, and absence
   contract;
4. the target-specific runtime plus fixed-range logical, physical, VID, PoI, failure, and
   PostgreSQL restore certification; and
5. a paused load with separate operational validation and activation approval.

The historical Kan copy remains the native-sync candidate until the eligibility gate says
otherwise. Every eventual backfill lands paused and needs independent certification and
operational approval.
