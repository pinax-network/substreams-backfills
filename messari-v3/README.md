# Messari V3 BSC + Base target baselines

This directory retains the exact deployed Graph artifacts for two related but
non-interchangeable targets:

- PancakeSwap V3 BSC `QmQjVBdmgZdjHpQsXGSC5uryWLmPkkTAunHN2AnDApZBa3`
- Uniswap V3 Base `QmawEzRNeDyaTgjPKb1eRrbyzxczgSHUYzvTMaMnN8jyuh`

The provenance contract's top-level `issues` list is the ordered, exhaustive
unique M9 issue set: BSC target #85, shared implementation #90, BSC
certification #92, Base target #94, and Base certification #95. The target
bindings retain target-local traceability associations, `[85, 90, 92]` and
`[94, 90, 95]`; they are not independently executable chains. The dependency
DAG is `#85 + #94 -> #90 -> #92 -> #95`. Both target locks precede shared
implementation, and BSC certification precedes Base certification.

Both schemas contain 24 entities and 388 fields, but byte identity and the
writer contract differ. BSC uses Messari schema 4.0.0, a nine-argument Swap,
`uint32` SetFeeProtocol inputs, and a `uint32` `slot0().feeProtocol` sixth output.
Base uses schema 4.0.1, adds
`Network.BASE`, changes `PositionSnapshot` from `@regularPolling` to
`@hourlySnapshot`, uses a seven-argument Swap, and uses `uint8`
SetFeeProtocol inputs and `slot0().feeProtocol` sixth output.

## Exact artifact boundary

`reference/` vendors every IPFS object reachable from both manifests: two
deployments, two schemas, fourteen target-local ABI references, and eight
mapping WASMs. Shared CIDs are intentionally retained under each target so
each closure is independently offline-verifiable. The provenance contract in
`docs/provenance/messari-v3-targets-v1.json` binds every path, CID, byte count,
SHA-256 digest, handler export, and manifest role.

The deployed BSC manifest contains a material handler mismatch. Its primary
Pool template declares `handleSetFeeProtocol`, but mapping `QmZ8ncas…` does
not export that function; only the separate `PancakeSwapPool` mapping
`QmZh9pwy…` does. Both targets also retain misspelled `LiqudityPool` template
entity metadata, plus duplicate `Token` entries in the primary Pool template.
The verifier must preserve these bytes and refuse attempts to normalize them.

Both manifests also retain nonexistent `mapping.entities` metadata. Factory
lists `_PricesUSD` and `_TokenTracker`; the primary Pool lists
`LiqudityPool`, `PoolDailySnapshot`, `_PricesUSD`, `_Account`,
`_DailyActiveAccount`, and `_TokenTracker`; and the fee-only template lists
`LiqudityPool`. `Protocol` is not in that missing set because it is a declared
schema interface. The machine contract binds the exact order, missing-name
inventory, and `Token: 2` multiplicity independently for BSC and Base.

The machine-readable cross-target ledger is exhaustive at the retained static
boundary. It compares complete ABI entry identities, canonical entry bytes,
input/output types, mutability, constructor shapes, and metadata. In addition
to the event and function differences, it preserves the material
`Pool.slot0().outputs[5]` difference (`uint32` on BSC, `uint8` on Base).

The four paired mapping roles also bind both complete WebAssembly export
tables. Each Base mapping has the two additional Cosmos type-ID globals, and
the ledger records every resulting common-export index difference, including
the additional function-index changes in the position-manager and fee-only
mapping pairs. These are structural byte/export facts only;
`runtime_equivalence_claimed` remains false.

## Market snapshot boundary

The bindings retain the `2026-08-31T17:20:00Z` Gateway QoS payload only for
priority context. It is nested under `market_snapshot`, attributes issue #83
as its authority, and preserves query-fee decimal precision as strings:

| Target | Queries (24h) | Query fees (24h) |
| --- | ---: | ---: |
| PancakeSwap V3 BSC | 143,319 | `170.760 GRT` |
| Uniswap V3 Base | 17,568 | `21.000 GRT` |

This metadata is neither on-chain signal nor eligibility evidence. Mutable
placement and legacy flat `market_qpd`/`qos_snapshot_at` fields are excluded.

## Source boundary

The strongest BSC source anchor is Messari commit `0c4618d…`; its fork-local
schema is byte-identical to the deployed v4.0.0 schema. The strongest Base
anchor is `2c60bd1…`; its fork-local schema is byte-identical and its Factory,
NPM, and Pool ABI files match after removing one repository trailing newline.

Neither anchor is a reproducible deployment workspace. The committed
templates say spec `0.0.2` while the deployed manifests say `0.0.4`, and both
Yarn/npm locks depend on the removed `edgeandnode/gluegun` repository at
`b34b900…`. Frozen installs fail. These commits are behavioral/source anchors,
not exact mapping-WASM reproduction claims.

## Readiness boundary

This is an immutable target/static-diff baseline only. Eligibility still
requires fresh same-pod 24-hour and 72-hour fastest-healthy-copy forecasts,
both greater than 28 days or non-converging. Implementation, runtime behavior,
Graph Store order, error behavior, logical/physical/VID/PoI parity, backfill,
deployment, production, and readiness remain false. Issues #85 and #94 stay
open.

Run the offline verifier and refusal suite with:

```console
find messari-v3/reference -type f -name '*.wasm' -exec wasm-validate {} \;
python3 scripts/verify-messari-v3-targets.py
python3 -m unittest scripts.tests.test_messari_v3_targets
```
